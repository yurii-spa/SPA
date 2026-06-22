"""
PositionProfitabilityTracker (SPA-V596 / MP-718) — advisory / read-only.

Tracks actual realized profitability of DeFi positions, accounting for yield
collected, impermanent loss, gas costs, and token price changes.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/profitability_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

CLI
---
  python3 -m spa_core.analytics.position_profitability_tracker --check
  python3 -m spa_core.analytics.position_profitability_tracker --run
  python3 -m spa_core.analytics.position_profitability_tracker --run --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "profitability_log.json"
_RING_BUFFER_MAX = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProfitabilitySnapshot:
    timestamp_iso: str
    position_value_usd: float    # current market value of position
    yield_collected_usd: float   # cumulative yield collected since entry
    gas_spent_usd: float         # cumulative gas spent


@dataclass
class ProfitabilityReport:
    protocol: str
    pool: str
    entry_value_usd: float
    entry_timestamp_iso: str
    current_timestamp_iso: str

    snapshots: List[ProfitabilitySnapshot]

    # P&L breakdown
    current_position_value_usd: float
    total_yield_collected_usd: float
    total_gas_spent_usd: float
    impermanent_loss_usd: float         # provided externally (estimated)

    # Net P&L
    unrealized_pnl_usd: float           # current_value - entry_value
    realized_yield_usd: float           # yield_collected - gas_spent
    total_pnl_usd: float                # unrealized + realized - il
    total_pnl_pct: float                # total_pnl / entry_value * 100

    # Time metrics
    days_held: int
    annualized_return_pct: float        # total_pnl_pct / days_held * 365 (0 if days=0)
    daily_return_usd: float             # total_pnl / max(days_held, 1)

    # Efficiency
    yield_to_gas_ratio: float           # yield_collected / max(gas_spent, 0.01)
    il_drag_pct: float                  # il / entry_value * 100

    # Classification
    profitability_label: str    # "EXCELLENT" | "GOOD" | "BREAKEVEN" | "LOSS"
    gas_efficiency: str         # "EFFICIENT" | "MODERATE" | "EXPENSIVE"

    warnings: List[str]
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def add_snapshot(
    snapshots: List[ProfitabilitySnapshot],
    position_value_usd: float,
    yield_collected_usd: float,
    gas_spent_usd: float,
    timestamp_iso: str,
) -> List[ProfitabilitySnapshot]:
    """Append a new snapshot to the list and return the updated list."""
    snap = ProfitabilitySnapshot(
        timestamp_iso=timestamp_iso,
        position_value_usd=position_value_usd,
        yield_collected_usd=yield_collected_usd,
        gas_spent_usd=gas_spent_usd,
    )
    return snapshots + [snap]


def _parse_date(iso_str: str) -> date:
    """Parse YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS… into a date."""
    # Accept full ISO datetime or date-only
    return date.fromisoformat(iso_str[:10])


def analyze(
    protocol: str,
    pool: str,
    entry_value_usd: float,
    entry_timestamp_iso: str,
    current_timestamp_iso: str,
    snapshots: List[ProfitabilitySnapshot],
    impermanent_loss_usd: float = 0.0,
) -> ProfitabilityReport:
    """
    Compute a full ProfitabilityReport from position history.
    Uses the last snapshot for current values.
    """
    if not snapshots:
        # No snapshots: use entry value as current, zeroed metrics
        current_value = entry_value_usd
        yield_collected = 0.0
        gas_spent = 0.0
    else:
        last = snapshots[-1]
        current_value = last.position_value_usd
        yield_collected = last.yield_collected_usd
        gas_spent = last.gas_spent_usd

    # ---- Time ----
    entry_date = _parse_date(entry_timestamp_iso)
    current_date = _parse_date(current_timestamp_iso)
    days_held = max(0, (current_date - entry_date).days)

    # ---- P&L ----
    safe_entry = max(entry_value_usd, 0.01)

    unrealized_pnl = current_value - entry_value_usd
    realized_yield = yield_collected - gas_spent
    total_pnl = unrealized_pnl + realized_yield - impermanent_loss_usd
    total_pnl_pct = total_pnl / safe_entry * 100.0

    # ---- Annualized ----
    if days_held == 0:
        annualized_return_pct = 0.0
    else:
        annualized_return_pct = total_pnl_pct / days_held * 365.0

    daily_return_usd = total_pnl / max(days_held, 1)

    # ---- Efficiency ----
    yield_to_gas_ratio = yield_collected / max(gas_spent, 0.01)
    il_drag_pct = impermanent_loss_usd / safe_entry * 100.0

    # ---- Labels ----
    if annualized_return_pct >= 20.0:
        profitability_label = "EXCELLENT"
    elif annualized_return_pct >= 10.0:
        profitability_label = "GOOD"
    elif annualized_return_pct >= 0.0:
        profitability_label = "BREAKEVEN"
    else:
        profitability_label = "LOSS"

    if yield_to_gas_ratio > 10.0:
        gas_efficiency = "EFFICIENT"
    elif yield_to_gas_ratio > 3.0:
        gas_efficiency = "MODERATE"
    else:
        gas_efficiency = "EXPENSIVE"

    # ---- Warnings ----
    warnings: List[str] = []
    if il_drag_pct > 5.0:
        warnings.append("significant IL drag")
    if gas_efficiency == "EXPENSIVE":
        warnings.append("high gas costs eating yield")
    if total_pnl < 0.0:
        warnings.append("position in loss")

    return ProfitabilityReport(
        protocol=protocol,
        pool=pool,
        entry_value_usd=entry_value_usd,
        entry_timestamp_iso=entry_timestamp_iso,
        current_timestamp_iso=current_timestamp_iso,
        snapshots=snapshots,
        current_position_value_usd=current_value,
        total_yield_collected_usd=yield_collected,
        total_gas_spent_usd=gas_spent,
        impermanent_loss_usd=impermanent_loss_usd,
        unrealized_pnl_usd=unrealized_pnl,
        realized_yield_usd=realized_yield,
        total_pnl_usd=total_pnl,
        total_pnl_pct=total_pnl_pct,
        days_held=days_held,
        annualized_return_pct=annualized_return_pct,
        daily_return_usd=daily_return_usd,
        yield_to_gas_ratio=yield_to_gas_ratio,
        il_drag_pct=il_drag_pct,
        profitability_label=profitability_label,
        gas_efficiency=gas_efficiency,
        warnings=warnings,
    )


def compare_positions(reports: List[ProfitabilityReport]) -> List[ProfitabilityReport]:
    """Return reports sorted by annualized_return_pct descending."""
    return sorted(reports, key=lambda r: r.annualized_return_pct, reverse=True)


def find_best_performing(reports: List[ProfitabilityReport]) -> Optional[ProfitabilityReport]:
    """Return the report with highest total_pnl_pct, or None if list is empty."""
    if not reports:
        return None
    return max(reports, key=lambda r: r.total_pnl_pct)


# ---------------------------------------------------------------------------
# Persistence (ring-buffer, atomic write)
# ---------------------------------------------------------------------------

def _log_path(data_dir: Optional[Path] = None) -> Path:
    base = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
    return Path(base) / _LOG_FILENAME


def _report_to_dict(report: ProfitabilityReport) -> dict:
    """Convert ProfitabilityReport to a JSON-serialisable dict."""
    d = asdict(report)
    return d


def save_results(
    report: ProfitabilityReport,
    data_dir: Optional[Path] = None,
) -> str:
    """
    Append report to the ring-buffer log (max 100 entries).
    Returns the path written to.
    """
    path = _log_path(data_dir)

    # Load existing
    existing: list = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    # Append new entry
    entry = _report_to_dict(report)
    entry["_saved_at"] = datetime.now(timezone.utc).isoformat()
    existing.append(entry)

    # Trim to ring-buffer cap
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    # Atomic write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(existing, str(path))
    report.saved_to = str(path)
    return str(path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load all persisted profitability records."""
    path = _log_path(data_dir)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report: ProfitabilityReport) -> None:
    print("\n=== PositionProfitabilityTracker ===")
    print(f"  Protocol    : {report.protocol} / {report.pool}")
    print(f"  Entry       : ${report.entry_value_usd:,.2f}  on {report.entry_timestamp_iso[:10]}")
    print(f"  Current     : ${report.current_position_value_usd:,.2f}  on {report.current_timestamp_iso[:10]}")
    print(f"  Days held   : {report.days_held}")
    print(f"  Unrealized  : ${report.unrealized_pnl_usd:+,.2f}")
    print(f"  Realized    : ${report.realized_yield_usd:+,.2f}  (yield ${report.total_yield_collected_usd:,.2f} - gas ${report.total_gas_spent_usd:,.2f})")
    print(f"  IL          : -${report.impermanent_loss_usd:,.2f}  (drag {report.il_drag_pct:.2f}%)")
    print(f"  Total P&L   : ${report.total_pnl_usd:+,.2f}  ({report.total_pnl_pct:+.2f}%)")
    print(f"  Annualized  : {report.annualized_return_pct:+.2f}%  → {report.profitability_label}")
    print(f"  Gas ratio   : {report.yield_to_gas_ratio:.1f}x  → {report.gas_efficiency}")
    if report.warnings:
        print(f"  ⚠  Warnings : {'; '.join(report.warnings)}")
    print()


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="PositionProfitabilityTracker (MP-718)")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute, print, and save")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else None

    # Demo run: build a sample report from history or synthetic data
    history = load_history(data_dir)
    if history:
        print(f"Loaded {len(history)} historical profitability records.")
    else:
        print("No history found — generating demo report.")
        snaps = add_snapshot([], 10_500.0, 120.0, 15.0, "2026-06-01")
        snaps = add_snapshot(snaps, 10_800.0, 250.0, 20.0, "2026-06-10")
        report = analyze(
            protocol="Aave V3",
            pool="USDC",
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-06-10",
            snapshots=snaps,
            impermanent_loss_usd=0.0,
        )
        _print_report(report)
        if args.run:
            path = save_results(report, data_dir)
            print(f"Saved to: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
