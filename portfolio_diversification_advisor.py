"""
PortfolioDiversificationAdvisor (MP-727)
=========================================

Provides comprehensive diversification advice across protocols, chains,
categories, and risk tiers. Identifies concentration risks and recommends
specific allocation adjustments.

Diversification axes:
  1. PROTOCOL  — per-protocol % of portfolio
  2. CHAIN     — per-chain % of portfolio
  3. CATEGORY  — lending / dex / yield_aggregator / liquid_staking / cdp / other
  4. RISK_TIER — T1 / T2 / T3

Scores: 0–100 (100 = perfectly diversified)
Grades: A (≥80) | B (60–79) | C (40–59) | D (<40)

Output: data/diversification_advisory_log.json (ring-buffer 100 entries)

Design constraints
------------------
* Pure stdlib only.
* Advisory / read-only: never imports execution/, risk/, monitoring/.
* Atomic writes: tmp + os.replace.
* Deterministic: identical input → identical output.
* CLI: --check (default) | --run (+ save) | --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILE = "diversification_advisory_log.json"
_RING_BUFFER_MAX = 100

# HHI threshold for "concentrated" classification
_HHI_CONCENTRATION_THRESHOLD = 0.33
_TOP_CONCENTRATION_THRESHOLD = 50.0  # %
_T3_HIGH_THRESHOLD = 40.0            # % of portfolio
_T1_LOW_THRESHOLD = 20.0             # % of portfolio


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Holding:
    name: str
    protocol: str
    chain: str
    category: str    # "lending" | "dex" | "yield_aggregator" | "liquid_staking" | "cdp" | "other"
    risk_tier: str   # "T1" | "T2" | "T3"
    value_usd: float
    apy: float


@dataclass
class DiversificationAxis:
    axis: str                    # "PROTOCOL" | "CHAIN" | "CATEGORY" | "RISK_TIER"
    breakdown: Dict[str, float]  # {label: pct_of_portfolio}
    hhi: float                   # Herfindahl-Hirschman Index
    top_concentration: str       # label with highest %
    top_concentration_pct: float
    is_concentrated: bool        # HHI > 0.33 or top > 50%
    recommendation: str


@dataclass
class DiversificationReport:
    total_value_usd: float
    holdings: List[Holding]
    axes: List[DiversificationAxis]
    overall_diversification_score: float  # 0–100
    concentration_alerts: List[str]
    add_protocols: List[str]
    reduce_positions: List[str]
    grade: str
    saved_to: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def compute_breakdown(
    holdings: List[Holding],
    key_fn: Callable[[Holding], str],
) -> Dict[str, float]:
    """Return {label: pct_of_portfolio} using key_fn to extract the label."""
    total = sum(h.value_usd for h in holdings)
    if total == 0.0:
        return {}
    result: Dict[str, float] = {}
    for h in holdings:
        label = key_fn(h)
        result[label] = result.get(label, 0.0) + h.value_usd
    return {label: (val / total) * 100.0 for label, val in result.items()}


def compute_hhi(breakdown: Dict[str, float]) -> float:
    """
    Herfindahl-Hirschman Index from a {label: pct} dict.
    HHI = Σ (pct/100)²  → range [1/n, 1.0]
    """
    if not breakdown:
        return 1.0  # fully concentrated (degenerate case)
    return sum((pct / 100.0) ** 2 for pct in breakdown.values())


def _top_entry(breakdown: Dict[str, float]) -> tuple:
    """Return (label, pct) for the highest-% entry."""
    if not breakdown:
        return ("", 100.0)
    top_label = max(breakdown, key=lambda k: breakdown[k])
    return (top_label, breakdown[top_label])


def _axis_recommendation(
    axis: str,
    is_concentrated: bool,
    breakdown: Dict[str, float],
) -> str:
    if axis == "PROTOCOL":
        if is_concentrated:
            return "Add more protocols, max single protocol should be <30%"
        return "Protocol diversification is adequate"

    if axis == "CHAIN":
        if is_concentrated:
            return "Expand to additional chains"
        return "Chain diversification is adequate"

    if axis == "CATEGORY":
        if is_concentrated:
            return "Balance across lending/DEX/staking/aggregators"
        return "Category diversification is adequate"

    if axis == "RISK_TIER":
        t1_pct = breakdown.get("T1", 0.0)
        t3_pct = breakdown.get("T3", 0.0)
        if t1_pct < _T1_LOW_THRESHOLD:
            return "Increase T1 allocation for stability"
        if t3_pct > _T3_HIGH_THRESHOLD:
            return "Reduce T3 exposure"
        if is_concentrated:
            return "Diversify risk tier allocation"
        return "Risk tier allocation is adequate"

    return "Review this axis allocation"


def analyze_axis(
    holdings: List[Holding],
    axis_name: str,
    key_fn: Callable[[Holding], str],
) -> DiversificationAxis:
    """Analyse a single diversification axis."""
    breakdown = compute_breakdown(holdings, key_fn)
    hhi = compute_hhi(breakdown)
    top_label, top_pct = _top_entry(breakdown)
    is_concentrated = hhi > _HHI_CONCENTRATION_THRESHOLD or top_pct > _TOP_CONCENTRATION_THRESHOLD
    recommendation = _axis_recommendation(axis_name, is_concentrated, breakdown)
    return DiversificationAxis(
        axis=axis_name,
        breakdown=breakdown,
        hhi=hhi,
        top_concentration=top_label,
        top_concentration_pct=top_pct,
        is_concentrated=is_concentrated,
        recommendation=recommendation,
    )


def _overall_score(axes: List[DiversificationAxis]) -> float:
    """Mean of (1 - HHI) * 100 across all axes."""
    if not axes:
        return 0.0
    return sum((1.0 - ax.hhi) * 100.0 for ax in axes) / len(axes)


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def _build_add_protocols(holdings: List[Holding], axes: List[DiversificationAxis]) -> List[str]:
    suggestions: List[str] = []
    categories_present = {h.category for h in holdings}
    tiers_present = {h.risk_tier for h in holdings}

    if "liquid_staking" not in categories_present:
        suggestions.append("Add liquid staking protocols (e.g., Lido, Rocket Pool)")
    if "dex" not in categories_present:
        suggestions.append("Add DEX/AMM protocols for yield diversification")
    if "T1" not in tiers_present:
        suggestions.append("Add T1-rated protocols for portfolio stability")
    if len(categories_present) == 1:
        missing = {"lending", "dex", "yield_aggregator", "liquid_staking"} - categories_present
        for cat in sorted(missing):
            suggestions.append(f"Add {cat} exposure")
    return suggestions


def _build_reduce_positions(
    holdings: List[Holding],
    total_value: float,
) -> List[str]:
    if total_value == 0.0 or len(holdings) == 0:
        return []
    sorted_holdings = sorted(holdings, key=lambda h: h.value_usd, reverse=True)
    top2 = sorted_holdings[:2]
    top2_pct = sum(h.value_usd for h in top2) / total_value * 100.0
    if top2_pct > 60.0:
        return [
            f"Consider reducing {h.name} ({h.value_usd / total_value * 100:.1f}% of portfolio)"
            for h in top2
        ]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def advise(
    holdings: List[Holding],
    data_dir: Optional[Path] = None,
) -> DiversificationReport:
    """Produce a full DiversificationReport from a list of Holding objects."""
    total_value = sum(h.value_usd for h in holdings)

    axes = [
        analyze_axis(holdings, "PROTOCOL",  lambda h: h.protocol),
        analyze_axis(holdings, "CHAIN",     lambda h: h.chain),
        analyze_axis(holdings, "CATEGORY",  lambda h: h.category),
        analyze_axis(holdings, "RISK_TIER", lambda h: h.risk_tier),
    ]

    score = _overall_score(axes)
    grade = _grade(score)

    concentration_alerts = [
        ax.recommendation
        for ax in axes
        if ax.is_concentrated
    ]

    add_proto = _build_add_protocols(holdings, axes)
    reduce_pos = _build_reduce_positions(holdings, total_value)

    dd = data_dir or _DEFAULT_DATA_DIR
    saved_to = str(dd / _LOG_FILE)

    return DiversificationReport(
        total_value_usd=total_value,
        holdings=holdings,
        axes=axes,
        overall_diversification_score=score,
        concentration_alerts=concentration_alerts,
        add_protocols=add_proto,
        reduce_positions=reduce_pos,
        grade=grade,
        saved_to=saved_to,
    )


def compare_portfolios(reports: List[DiversificationReport]) -> List[DiversificationReport]:
    """Return reports sorted by overall_diversification_score descending."""
    return sorted(reports, key=lambda r: r.overall_diversification_score, reverse=True)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _holding_to_dict(h: Holding) -> dict:
    return {
        "name": h.name,
        "protocol": h.protocol,
        "chain": h.chain,
        "category": h.category,
        "risk_tier": h.risk_tier,
        "value_usd": h.value_usd,
        "apy": h.apy,
    }


def _axis_to_dict(ax: DiversificationAxis) -> dict:
    return {
        "axis": ax.axis,
        "breakdown": ax.breakdown,
        "hhi": ax.hhi,
        "top_concentration": ax.top_concentration,
        "top_concentration_pct": ax.top_concentration_pct,
        "is_concentrated": ax.is_concentrated,
        "recommendation": ax.recommendation,
    }


def _report_to_dict(report: DiversificationReport) -> dict:
    return {
        "timestamp": report.timestamp,
        "total_value_usd": report.total_value_usd,
        "holdings": [_holding_to_dict(h) for h in report.holdings],
        "axes": [_axis_to_dict(ax) for ax in report.axes],
        "overall_diversification_score": report.overall_diversification_score,
        "concentration_alerts": report.concentration_alerts,
        "add_protocols": report.add_protocols,
        "reduce_positions": report.reduce_positions,
        "grade": report.grade,
        "saved_to": report.saved_to,
    }


def save_results(report: DiversificationReport, data_dir: Optional[Path] = None) -> str:
    """Append report to ring-buffer log (max 100). Returns path written."""
    dd = data_dir or _DEFAULT_DATA_DIR
    dd.mkdir(parents=True, exist_ok=True)
    log_path = dd / _LOG_FILE

    existing: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(_report_to_dict(report))
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    tmp_fd, tmp_path = tempfile.mkstemp(dir=dd, prefix=".diversification_tmp_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(log_path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load all saved reports as raw dicts."""
    dd = data_dir or _DEFAULT_DATA_DIR
    log_path = dd / _LOG_FILE
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_holdings() -> List[Holding]:
    return [
        Holding("Aave USDC", "Aave", "Ethereum", "lending",         "T1", 30_000.0, 3.5),
        Holding("Compound USDC", "Compound", "Ethereum", "lending",  "T1", 25_000.0, 4.8),
        Holding("Morpho USDC", "Morpho", "Ethereum", "lending",      "T1", 20_000.0, 6.5),
        Holding("Curve 3pool", "Curve", "Ethereum", "dex",           "T2", 10_000.0, 5.2),
        Holding("Lido stETH", "Lido", "Ethereum", "liquid_staking",  "T2",  8_000.0, 4.0),
        Holding("Yearn USDC", "Yearn", "Ethereum", "yield_aggregator","T2", 7_000.0, 7.1),
    ]


def _print_report(report: DiversificationReport) -> None:
    print("\n=== PortfolioDiversificationAdvisor (MP-727) ===")
    print(f"  Timestamp     : {report.timestamp}")
    print(f"  Total Value   : ${report.total_value_usd:,.0f}")
    print(f"  Holdings      : {len(report.holdings)}")
    print(f"  Overall Score : {report.overall_diversification_score:.1f}/100")
    print(f"  Grade         : {report.grade}")
    print()
    print("  Axes:")
    for ax in report.axes:
        conc = "⚠ CONCENTRATED" if ax.is_concentrated else "✓ OK"
        print(f"    {ax.axis:<12} HHI={ax.hhi:.3f}  top={ax.top_concentration} "
              f"({ax.top_concentration_pct:.1f}%)  {conc}")
        print(f"               → {ax.recommendation}")
    print()
    if report.concentration_alerts:
        print("  Alerts:")
        for alert in report.concentration_alerts:
            print(f"    ⚠ {alert}")
    if report.add_protocols:
        print("  Add protocols:")
        for p in report.add_protocols:
            print(f"    + {p}")
    if report.reduce_positions:
        print("  Reduce positions:")
        for p in report.reduce_positions:
            print(f"    ↓ {p}")
    print()


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv
    data_dir = _DEFAULT_DATA_DIR
    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir = Path(argv[idx + 1])

    holdings = _sample_holdings()
    report = advise(holdings, data_dir=data_dir)
    _print_report(report)

    if run_mode:
        path = save_results(report, data_dir=data_dir)
        print(f"  Saved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
