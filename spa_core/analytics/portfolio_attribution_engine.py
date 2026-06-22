"""Portfolio Attribution Engine (MP-692) — Brinson-Hood-Beebower Decomposition.

Decomposes portfolio active return into three sources following the classic
Brinson-Hood-Beebower (BHB) attribution model, adapted for DeFi yield
portfolios:

    Allocation Effect  = (w_p - w_b) × r_b
    Selection Effect   = w_b × (r_p - r_b)
    Interaction Effect = (w_p - w_b) × (r_p - r_b)
    ──────────────────────────────────────────────
    Total Active Return = Allocation + Selection + Interaction
                        = r_portfolio - r_benchmark

where:
    w_p  = portfolio weight in segment
    w_b  = benchmark weight in segment
    r_p  = portfolio return in segment
    r_b  = benchmark return in segment

Design constraints
------------------
* Pure stdlib — no external deps (no numpy / scipy / pandas / requests).
* Advisory / read-only analytics — never touches allocator / risk / execution.
* Atomic writes: tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Ring-buffer cap: MAX_ENTRIES = 100.

Public API
----------
``PortfolioAttributionEngine(data_dir="data")``

    generate_report(report_id, segments) → PortfolioAttributionReport
    save_results(report)                 → None  (atomic ring-buffer write)
    load_history()                       → List[dict]

Data file: data/attribution_log.json  (ring-buffer, max 100 entries)

MP-692.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

DATA_FILENAME = "attribution_log.json"
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    """A single allocation segment (protocol or category)."""

    name: str                        # e.g. "Aave V3" or "T1 Lending"
    portfolio_weight: float          # 0–1 fractional weight in portfolio
    benchmark_weight: float          # 0–1 fractional weight in benchmark
    portfolio_return_pct: float      # return % earned by portfolio in segment
    benchmark_return_pct: float      # benchmark return % in segment


@dataclass
class AttributionResult:
    """BHB attribution decomposition for one segment."""

    segment_name: str
    allocation_effect: float         # (w_p - w_b) * r_b
    selection_effect: float          # w_b * (r_p - r_b)
    interaction_effect: float        # (w_p - w_b) * (r_p - r_b)
    total_active_return: float       # allocation + selection + interaction


@dataclass
class PortfolioAttributionReport:
    """Full BHB attribution report for a portfolio snapshot."""

    report_id: str
    total_portfolio_return_pct: float   # Σ w_p * r_p
    total_benchmark_return_pct: float  # Σ w_b * r_b
    total_active_return_pct: float     # portfolio - benchmark
    segments: List[AttributionResult]
    top_contributor: str               # segment with highest total_active_return
    top_detractor: str                 # segment with lowest total_active_return
    allocation_total: float            # Σ allocation effects
    selection_total: float             # Σ selection effects
    interaction_total: float           # Σ interaction effects
    skill_assessment: str              # ALPHA_GENERATOR / MIXED / BETA_FOLLOWER / UNDERPERFORMER
    summary: str
    generated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Core computation helpers (module-level, easily unit-tested)
# ---------------------------------------------------------------------------


def compute_allocation_effect(wp: float, wb: float, rb: float) -> float:
    """BHB allocation effect for one segment.

    (portfolio_weight - benchmark_weight) * benchmark_return_pct
    """
    return (wp - wb) * rb


def compute_selection_effect(wb: float, rp: float, rb: float) -> float:
    """BHB selection effect for one segment.

    benchmark_weight * (portfolio_return_pct - benchmark_return_pct)
    """
    return wb * (rp - rb)


def compute_interaction_effect(wp: float, wb: float, rp: float, rb: float) -> float:
    """BHB interaction effect for one segment.

    (portfolio_weight - benchmark_weight) * (portfolio_return_pct - benchmark_return_pct)
    """
    return (wp - wb) * (rp - rb)


def _skill_assessment(
    total_active_return_pct: float,
    selection_total: float,
) -> str:
    """Classify manager skill based on active return and selection contribution.

    Rules:
        ALPHA_GENERATOR : active > 1.0 AND selection_total > 0
        MIXED           : active > 0  (positive but not entirely selection-driven)
        BETA_FOLLOWER   : -0.5 <= active <= 0
        UNDERPERFORMER  : active < -0.5
    """
    if total_active_return_pct > 1.0 and selection_total > 0:
        return "ALPHA_GENERATOR"
    if total_active_return_pct > 0:
        return "MIXED"
    if total_active_return_pct >= -0.5:
        return "BETA_FOLLOWER"
    return "UNDERPERFORMER"


# ---------------------------------------------------------------------------
# Main engine class
# ---------------------------------------------------------------------------


class PortfolioAttributionEngine:
    """Brinson-Hood-Beebower attribution engine for DeFi yield portfolios.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory where ``attribution_log.json`` is written.
        Defaults to ``<repo_root>/data``.
    """

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_file = self._data_dir / DATA_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        report_id: str,
        segments: List[Segment],
    ) -> PortfolioAttributionReport:
        """Compute BHB attribution for a list of Segment inputs.

        Parameters
        ----------
        report_id : str
            Caller-supplied unique identifier for this report run.
        segments : list[Segment]
            One entry per protocol / category being attributed.

        Returns
        -------
        PortfolioAttributionReport
            Fully populated report with per-segment decomposition and totals.

        Raises
        ------
        ValueError
            If ``segments`` is empty.
        """
        if not segments:
            raise ValueError("segments must contain at least one Segment")

        attr_results: List[AttributionResult] = []
        for seg in segments:
            alloc = compute_allocation_effect(
                seg.portfolio_weight, seg.benchmark_weight, seg.benchmark_return_pct
            )
            sel = compute_selection_effect(
                seg.benchmark_weight, seg.portfolio_return_pct, seg.benchmark_return_pct
            )
            inter = compute_interaction_effect(
                seg.portfolio_weight, seg.benchmark_weight,
                seg.portfolio_return_pct, seg.benchmark_return_pct,
            )
            total_ar = alloc + sel + inter
            attr_results.append(
                AttributionResult(
                    segment_name=seg.name,
                    allocation_effect=alloc,
                    selection_effect=sel,
                    interaction_effect=inter,
                    total_active_return=total_ar,
                )
            )

        total_portfolio = sum(s.portfolio_weight * s.portfolio_return_pct for s in segments)
        total_benchmark = sum(s.benchmark_weight * s.benchmark_return_pct for s in segments)
        total_active = total_portfolio - total_benchmark

        allocation_total = sum(r.allocation_effect for r in attr_results)
        selection_total = sum(r.selection_effect for r in attr_results)
        interaction_total = sum(r.interaction_effect for r in attr_results)

        top_contributor = max(attr_results, key=lambda r: r.total_active_return).segment_name
        top_detractor = min(attr_results, key=lambda r: r.total_active_return).segment_name

        skill = _skill_assessment(total_active, selection_total)

        summary = (
            f"Portfolio {total_portfolio:.2f}% vs Benchmark {total_benchmark:.2f}% = "
            f"{total_active:.2f}% active return. "
            f"Top contributor: {top_contributor}. "
            f"Assessment: {skill}"
        )

        return PortfolioAttributionReport(
            report_id=report_id,
            total_portfolio_return_pct=total_portfolio,
            total_benchmark_return_pct=total_benchmark,
            total_active_return_pct=total_active,
            segments=attr_results,
            top_contributor=top_contributor,
            top_detractor=top_detractor,
            allocation_total=allocation_total,
            selection_total=selection_total,
            interaction_total=interaction_total,
            skill_assessment=skill,
            summary=summary,
        )

    def save_results(self, report: PortfolioAttributionReport) -> None:
        """Persist report to ring-buffer JSON (max MAX_ENTRIES).

        Uses atomic tmp + os.replace write pattern.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        history = self.load_history()

        # Serialize report — convert nested dataclasses to dicts
        entry = asdict(report)
        history.append(entry)

        # Ring-buffer trim
        if len(history) > MAX_ENTRIES:
            history = history[-MAX_ENTRIES:]

        _atomic_write(self._data_file, history)

    def load_history(self) -> List[dict]:
        """Load ring-buffer history from disk.

        Returns empty list if file is missing or corrupt.
        """
        if not self._data_file.exists():
            return []
        try:
            with self._data_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: object) -> None:
    """Write *payload* to *path* atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(payload, str(path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_demo_segments() -> List[Segment]:
    """Return representative demo segments for CLI smoke-test."""
    return [
        Segment("Aave V3",          portfolio_weight=0.40, benchmark_weight=0.35,
                portfolio_return_pct=3.5, benchmark_return_pct=3.2),
        Segment("Compound V3",      portfolio_weight=0.30, benchmark_weight=0.30,
                portfolio_return_pct=4.8, benchmark_return_pct=4.5),
        Segment("Morpho Steakhouse", portfolio_weight=0.25, benchmark_weight=0.25,
                portfolio_return_pct=6.5, benchmark_return_pct=5.8),
        Segment("Cash",             portfolio_weight=0.05, benchmark_weight=0.10,
                portfolio_return_pct=0.0, benchmark_return_pct=0.0),
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MP-692 Portfolio Attribution Engine")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run",   action="store_true", help="Compute and write to data/")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_dir = args.data_dir or str(_DEFAULT_DATA_DIR)
    engine = PortfolioAttributionEngine(data_dir=data_dir)
    segments = _build_demo_segments()
    report = engine.generate_report("cli_demo", segments)

    print(report.summary)
    print(f"  Allocation  total: {report.allocation_total:.4f}%")
    print(f"  Selection   total: {report.selection_total:.4f}%")
    print(f"  Interaction total: {report.interaction_total:.4f}%")
    print(f"  Skill: {report.skill_assessment}")

    if args.run:
        engine.save_results(report)
        print(f"  ✓ Saved to {engine._data_file}")

    sys.exit(0)
