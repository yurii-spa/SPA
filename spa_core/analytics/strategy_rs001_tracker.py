"""
spa_core/analytics/strategy_rs001_tracker.py — RS-001 Shadow Tracker (MP-1302)

Tracks hypothetical performance of Research Strategy RS-001 "Anti-Crisis"
versus the real portfolio equity curve.

Data file: data/research/rs001_shadow.json (ring-buffer, cap=100 entries)

Schema per entry:
    {
        "date":                str (ISO date YYYY-MM-DD),
        "rs001_blended_apy":   float,    # RS-001 weighted APY % (placeholder)
        "rs001_daily_return":  float,    # daily return fraction
        "portfolio_daily_return": float, # real portfolio daily return fraction (if available)
        "capital_hypothetical": float,   # hypothetical cumulative capital
        "vs_portfolio_delta":  float,    # rs001_daily_return - portfolio_daily_return
        "strict_eligible_fraction": float,  # fraction eligible in strict mode
        "timestamp":           str,      # ISO datetime of record creation
    }

Rules:
  - stdlib only; no external dependencies
  - Atomic writes: tmp file + os.replace
  - read-only / advisory — does NOT modify allocator/risk/execution
  - LLM FORBIDDEN
  - ring-buffer cap = 100 days (oldest entries dropped when cap exceeded)
  - Exit code: 0 always (never raises from main)

CLI:
    python3 -m spa_core.analytics.strategy_rs001_tracker --check   # compute, no write
    python3 -m spa_core.analytics.strategy_rs001_tracker --run     # compute + atomic write

Date: 2026-06-19 (MP-1302, Sprint v9.18)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────────────

RING_BUFFER_CAP: int = 100
DATA_FILE_REL:   str = "data/research/rs001_shadow.json"

# Default repo root: two levels up from this file (spa_core/analytics/ → repo)
_HERE = Path(__file__).resolve().parent
_DEFAULT_REPO_ROOT = _HERE.parent.parent


# ─── RS001ShadowTracker ───────────────────────────────────────────────────────

class RS001ShadowTracker:
    """Track hypothetical RS-001 performance vs real portfolio.

    Maintains a ring-buffer of daily shadow entries in
    data/research/rs001_shadow.json. All writes are atomic
    (tmp file + os.replace). Read-only advisory module.

    Args:
        data_dir: Override for the data/research/ directory.
                  Defaults to <repo_root>/data/research/.
    """

    RING_BUFFER_CAP = RING_BUFFER_CAP

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir is not None:
            self._data_file = Path(data_dir) / "rs001_shadow.json"
        else:
            self._data_file = _DEFAULT_REPO_ROOT / DATA_FILE_REL
        self._data_file.parent.mkdir(parents=True, exist_ok=True)

    # ── IO helpers ─────────────────────────────────────────────────────────────

    def _load(self) -> list:
        """Load existing ring-buffer from disk. Returns [] if not found or invalid."""
        if not self._data_file.exists():
            return []
        try:
            with open(self._data_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "entries" in data:
                return list(data["entries"])
            if isinstance(data, list):
                return data
        except Exception:  # noqa: BLE001
            pass
        return []

    def _save(self, entries: list) -> None:
        """Atomically write ring-buffer to disk (tmp + os.replace)."""
        payload = {
            "schema_version": "1.0",
            "strategy_id":    "S20",
            "ring_buffer_cap": RING_BUFFER_CAP,
            "entries":        entries,
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._data_file.parent),
            prefix=".rs001_shadow_",
            suffix=".tmp.json",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_path, str(self._data_file))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── Ring-buffer logic ──────────────────────────────────────────────────────

    @staticmethod
    def _trim(entries: list, cap: int) -> list:
        """Keep only the most recent `cap` entries (oldest dropped first)."""
        if len(entries) > cap:
            return entries[-cap:]
        return entries

    # ── Portfolio integration ──────────────────────────────────────────────────

    def _read_portfolio_daily_return(self) -> Optional[float]:
        """Read the most recent daily return from equity_curve_daily.json.

        Returns None if data is unavailable or malformed.
        """
        equity_path = _DEFAULT_REPO_ROOT / "data" / "equity_curve_daily.json"
        if not equity_path.exists():
            return None
        try:
            with open(equity_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            entries = data if isinstance(data, list) else data.get("entries", [])
            if len(entries) < 2:
                return None
            last  = entries[-1]
            prev  = entries[-2]
            e_last = float(last.get("equity", last.get("total_value", 0.0)))
            e_prev = float(prev.get("equity", prev.get("total_value", 0.0)))
            if e_prev <= 0:
                return None
            return (e_last - e_prev) / e_prev
        except Exception:  # noqa: BLE001
            return None

    # ── Core computation ───────────────────────────────────────────────────────

    def _compute_entry(
        self,
        blended_apy_pct: float,
        strict_eligible_fraction: float,
        capital_hypothetical: float,
        portfolio_daily_return: Optional[float],
    ) -> dict:
        """Build a single daily shadow entry dict."""
        # Daily return from annual APY: (1 + apy/100)^(1/365) - 1
        if blended_apy_pct > 0:
            rs001_daily = (1.0 + blended_apy_pct / 100.0) ** (1.0 / 365.0) - 1.0
        else:
            rs001_daily = 0.0

        port_ret = portfolio_daily_return if portfolio_daily_return is not None else 0.0
        delta = rs001_daily - port_ret

        new_capital = capital_hypothetical * (1.0 + rs001_daily)

        return {
            "date":                     date.today().isoformat(),
            "rs001_blended_apy":        round(blended_apy_pct, 6),
            "rs001_daily_return":       round(rs001_daily, 8),
            "portfolio_daily_return":   round(port_ret, 8) if portfolio_daily_return is not None else None,
            "capital_hypothetical":     round(new_capital, 4),
            "vs_portfolio_delta":       round(delta, 8),
            "strict_eligible_fraction": round(strict_eligible_fraction, 6),
            "timestamp":                datetime.now(timezone.utc).isoformat(),
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def compute(self, blended_apy_pct: float = 18.2, initial_capital: float = 50_000.0) -> dict:
        """Compute today's shadow entry without writing to disk.

        Args:
            blended_apy_pct:   RS-001 blended APY in percent (default 18.2).
            initial_capital:   Hypothetical capital for first entry (subsequent
                               entries compound from previous entry's capital).

        Returns:
            dict with today's shadow entry fields.
        """
        from spa_core.strategies.s20_anticrisis_research import (  # type: ignore
            AntiCrisisResearchStrategy,
        )
        strategy = AntiCrisisResearchStrategy()
        blended = strategy.blended_apy()
        strict_frac = strategy.strict_eligible_fraction()
        port_ret = self._read_portfolio_daily_return()

        # Determine capital: last entry's capital or initial_capital
        entries = self._load()
        if entries:
            prev_capital = entries[-1].get("capital_hypothetical", initial_capital)
        else:
            prev_capital = initial_capital

        entry = self._compute_entry(blended, strict_frac, prev_capital, port_ret)
        return entry

    def record(
        self,
        blended_apy_pct: float = 18.2,
        initial_capital: float = 50_000.0,
    ) -> dict:
        """Compute today's entry and append it to the ring-buffer file atomically.

        If today's date is already the last entry, the last entry is replaced
        (idempotent daily run). Enforces ring-buffer cap = 100.

        Args:
            blended_apy_pct: RS-001 blended APY % (default 18.2).
            initial_capital: Starting capital for first historical entry.

        Returns:
            The newly written entry dict.
        """
        entries = self._load()

        # Determine current capital from last entry (or initial)
        if entries:
            prev_capital = entries[-1].get("capital_hypothetical", initial_capital)
        else:
            prev_capital = initial_capital

        from spa_core.strategies.s20_anticrisis_research import (  # type: ignore
            AntiCrisisResearchStrategy,
        )
        strategy = AntiCrisisResearchStrategy()
        blended = strategy.blended_apy()
        strict_frac = strategy.strict_eligible_fraction()
        port_ret = self._read_portfolio_daily_return()

        entry = self._compute_entry(blended, strict_frac, prev_capital, port_ret)

        # Replace today's entry if already present (idempotent)
        today_str = entry["date"]
        if entries and entries[-1].get("date") == today_str:
            entries[-1] = entry
        else:
            entries.append(entry)

        # Enforce ring-buffer cap
        entries = self._trim(entries, RING_BUFFER_CAP)

        self._save(entries)
        return entry

    def read_all(self) -> list:
        """Return all ring-buffer entries from disk."""
        return self._load()

    def summary(self) -> dict:
        """Return a brief summary of the shadow tracker state."""
        entries = self._load()
        if not entries:
            return {
                "entry_count":   0,
                "ring_buffer_cap": RING_BUFFER_CAP,
                "latest_entry":  None,
                "oldest_entry":  None,
            }
        return {
            "entry_count":   len(entries),
            "ring_buffer_cap": RING_BUFFER_CAP,
            "latest_entry":  entries[-1],
            "oldest_entry":  entries[0],
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    """CLI entry point for rs001 shadow tracker."""
    import argparse
    parser = argparse.ArgumentParser(
        description="RS-001 Anti-Crisis Shadow Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print today's entry without writing to disk.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically write today's entry to data/research/rs001_shadow.json.",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Override data/research/ directory path.",
    )
    args = parser.parse_args()

    tracker = RS001ShadowTracker(data_dir=args.data_dir)

    if args.run:
        entry = tracker.record()
        print(json.dumps(entry, indent=2))
        summary = tracker.summary()
        print(
            f"\nShadow tracker: {summary['entry_count']}/{RING_BUFFER_CAP} entries recorded.",
            file=sys.stderr,
        )
    else:
        # Default: --check
        entry = tracker.compute()
        print(json.dumps(entry, indent=2))
        print("\n[DRY RUN] No data written. Use --run to persist.", file=sys.stderr)


if __name__ == "__main__":
    try:
        _cli()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(0)   # always exit 0 per analytics conventions
