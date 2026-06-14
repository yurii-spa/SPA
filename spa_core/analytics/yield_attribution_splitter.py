"""
MP-773: YieldAttributionSplitter
Splits total yield into components:
  base_rate, liquidity_premium, governance_rewards,
  incentive_emissions, price_appreciation.

Computes:
  sustainable_yield = base_rate + liquidity_premium
  sustainability_score = sustainable_yield / total_yield * 100
  attribution_grade: A (>=80%), B (>=60%), C (>=40%), D (>=20%), F otherwise

Advisory/read-only. Pure stdlib only. Atomic JSON writes (tmp + os.replace).
Ring-buffer cap: 100 entries. Output: data/yield_attribution_log.json.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_FILE = Path("data/yield_attribution_log.json")
MAX_ENTRIES = 100

# Sustainability grade thresholds (sustainability_score %)
_GRADE_A: float = 80.0
_GRADE_B: float = 60.0
_GRADE_C: float = 40.0
_GRADE_D: float = 20.0

# Tolerance for component-sum check (percentage points)
_SUM_TOLERANCE: float = 0.01


# ─── Input / output dataclasses ──────────────────────────────────────────────

@dataclass
class YieldComponents:
    """
    Input: yield components for a single protocol/position.
    All values are in APY percentage points (e.g. 5.0 = 5%).
    Components should sum to total_yield_pct, but this is not enforced.
    """
    protocol: str
    total_yield_pct: float
    base_rate_pct: float            # core lending / liquidity rate
    liquidity_premium_pct: float    # extra yield for providing deep liquidity
    governance_rewards_pct: float   # on-chain governance token rewards
    incentive_emissions_pct: float  # temporary token emission incentives
    price_appreciation_pct: float   # price appreciation component


@dataclass
class YieldAttributionReport:
    """Per-protocol computed attribution report."""
    protocol: str
    total_yield_pct: float

    # Each component expressed as its share of total yield (pct of 100)
    base_rate_share_pct: float
    liquidity_premium_share_pct: float
    governance_rewards_share_pct: float
    incentive_emissions_share_pct: float
    price_appreciation_share_pct: float
    components_sum_pct: float          # sum of the five shares; should ≈ 100

    # Sustainability fields
    sustainable_yield_pct: float       # base_rate_pct + liquidity_premium_pct (actual APY)
    sustainability_score: float        # sustainable_yield / total_yield * 100
    attribution_grade: str             # A / B / C / D / F
    is_sustainable: bool               # True when grade is A or B
    note: str                          # human-readable verdict


@dataclass
class YieldAttributionSummary:
    """Portfolio-level attribution summary across all protocols."""
    timestamp: float
    protocols: List[YieldAttributionReport]
    portfolio_avg_sustainability_score: float
    portfolio_attribution_grade: str
    sustainable_protocols: List[str]    # grade A or B
    unsustainable_protocols: List[str]  # grade D or F
    avg_total_yield_pct: float
    avg_sustainable_yield_pct: float


# ─── Pure computation functions (testable without I/O) ───────────────────────

def compute_component_share(component_pct: float,
                             total_pct: float) -> float:
    """
    Share of a component as % of total_yield.
    Returns 0.0 if total_yield == 0 (avoid division by zero).
    """
    if total_pct == 0.0:
        return 0.0
    return component_pct / total_pct * 100.0


def compute_sustainable_yield(base_rate_pct: float,
                               liquidity_premium_pct: float) -> float:
    """
    sustainable_yield = base_rate + liquidity_premium.
    Governance rewards, emissions, and price appreciation are excluded.
    """
    return base_rate_pct + liquidity_premium_pct


def compute_sustainability_score(sustainable_yield_pct: float,
                                  total_yield_pct: float) -> float:
    """
    sustainability_score = sustainable_yield / total_yield * 100.
    Special cases:
      - total_yield == 0 → 100.0 (zero yield is not unsustainable)
      - sustainable_yield <= 0 → 0.0
    """
    if total_yield_pct == 0.0:
        return 100.0
    if sustainable_yield_pct <= 0.0:
        return 0.0
    return sustainable_yield_pct / total_yield_pct * 100.0


def compute_attribution_grade(sustainability_score: float) -> str:
    """
    Map sustainability_score to grade:
      A : score >= 80
      B : score >= 60
      C : score >= 40
      D : score >= 20
      F : score <  20
    """
    if sustainability_score >= _GRADE_A:
        return "A"
    if sustainability_score >= _GRADE_B:
        return "B"
    if sustainability_score >= _GRADE_C:
        return "C"
    if sustainability_score >= _GRADE_D:
        return "D"
    return "F"


def compute_components_sum(c: YieldComponents) -> float:
    """Sum of all five yield components (in APY pct points)."""
    return (
        c.base_rate_pct
        + c.liquidity_premium_pct
        + c.governance_rewards_pct
        + c.incentive_emissions_pct
        + c.price_appreciation_pct
    )


def check_components_sum(c: YieldComponents) -> bool:
    """
    Return True if components sum is within _SUM_TOLERANCE of total_yield_pct.
    Handles zero total (trivially True when total == 0 and sum == 0).
    """
    if c.total_yield_pct == 0.0:
        return abs(compute_components_sum(c)) < _SUM_TOLERANCE
    return abs(compute_components_sum(c) - c.total_yield_pct) < _SUM_TOLERANCE


def _build_note(grade: str, sum_ok: bool) -> str:
    """Build a human-readable verdict string."""
    parts: List[str] = []
    if not sum_ok:
        parts.append("WARNING: components do not sum to total yield")
    if grade == "A":
        parts.append("Highly sustainable — driven by base rate and liquidity premium")
    elif grade == "B":
        parts.append("Mostly sustainable — minor reliance on non-sustainable components")
    elif grade == "C":
        parts.append("Moderate sustainability — meaningful emissions/price dependency")
    elif grade == "D":
        parts.append("Low sustainability — heavy reliance on incentives or price appreciation")
    else:
        parts.append("Unsustainable yield — dominated by emissions or price appreciation")
    return "; ".join(parts)


def split_one(c: YieldComponents) -> YieldAttributionReport:
    """Compute the full attribution report for a single protocol."""
    total = c.total_yield_pct

    # Shares of each component as % of total
    base_share = compute_component_share(c.base_rate_pct, total)
    liq_share = compute_component_share(c.liquidity_premium_pct, total)
    gov_share = compute_component_share(c.governance_rewards_pct, total)
    emit_share = compute_component_share(c.incentive_emissions_pct, total)
    price_share = compute_component_share(c.price_appreciation_pct, total)

    sum_of_shares = base_share + liq_share + gov_share + emit_share + price_share

    sustainable = compute_sustainable_yield(c.base_rate_pct, c.liquidity_premium_pct)
    score = compute_sustainability_score(sustainable, total)
    grade = compute_attribution_grade(score)
    sum_ok = check_components_sum(c)
    note = _build_note(grade, sum_ok)

    return YieldAttributionReport(
        protocol=c.protocol,
        total_yield_pct=total,
        base_rate_share_pct=base_share,
        liquidity_premium_share_pct=liq_share,
        governance_rewards_share_pct=gov_share,
        incentive_emissions_share_pct=emit_share,
        price_appreciation_share_pct=price_share,
        components_sum_pct=sum_of_shares,
        sustainable_yield_pct=sustainable,
        sustainability_score=score,
        attribution_grade=grade,
        is_sustainable=grade in ("A", "B"),
        note=note,
    )


# ─── Persistence helpers ─────────────────────────────────────────────────────

def _summary_to_dict(s: YieldAttributionSummary) -> Dict[str, Any]:
    return {
        "timestamp": s.timestamp,
        "protocols": [asdict(r) for r in s.protocols],
        "portfolio_avg_sustainability_score": s.portfolio_avg_sustainability_score,
        "portfolio_attribution_grade": s.portfolio_attribution_grade,
        "sustainable_protocols": s.sustainable_protocols,
        "unsustainable_protocols": s.unsustainable_protocols,
        "avg_total_yield_pct": s.avg_total_yield_pct,
        "avg_sustainable_yield_pct": s.avg_sustainable_yield_pct,
    }


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load ring-buffer list from disk; returns [] if file is missing or corrupt."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        text = data_file.read_text().strip()
        if not text:
            return []
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return []


def save_summary(summary: YieldAttributionSummary,
                 data_file: Path = DATA_FILE) -> None:
    """Append summary to ring-buffer JSON log (capped at MAX_ENTRIES). Atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(data_file)
    history.append(_summary_to_dict(summary))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(tmp, data_file)


# ─── Main class ───────────────────────────────────────────────────────────────

class YieldAttributionSplitter:
    """
    MP-773: Splits total yield into sustainable vs non-sustainable components.

    Usage::

        splitter = YieldAttributionSplitter()
        data = [
            YieldComponents("Aave V3",   5.0, 3.5, 0.5, 0.5, 0.3, 0.2),
            YieldComponents("Compound",  8.0, 2.0, 1.0, 0.0, 4.5, 0.5),
        ]
        summary = splitter.split(data)
        sust    = splitter.get_sustainable_yield()   # portfolio avg
        full    = splitter.get_attribution_summary() # YieldAttributionSummary
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = Path(data_file)
        self._last_summary: Optional[YieldAttributionSummary] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def split(self, yield_data: List[YieldComponents]) -> YieldAttributionSummary:
        """
        Compute attribution for all protocols and persist to ring-buffer log.
        Accepts an empty list.

        :param yield_data: list of YieldComponents descriptors
        :returns: YieldAttributionSummary with per-protocol reports + aggregates
        """
        if not yield_data:
            summary = YieldAttributionSummary(
                timestamp=time.time(),
                protocols=[],
                portfolio_avg_sustainability_score=100.0,
                portfolio_attribution_grade="A",
                sustainable_protocols=[],
                unsustainable_protocols=[],
                avg_total_yield_pct=0.0,
                avg_sustainable_yield_pct=0.0,
            )
            self._last_summary = summary
            save_summary(summary, self.data_file)
            return summary

        reports = [split_one(c) for c in yield_data]
        n = len(reports)

        avg_score = sum(r.sustainability_score for r in reports) / n
        avg_total = sum(r.total_yield_pct for r in reports) / n
        avg_sust = sum(r.sustainable_yield_pct for r in reports) / n
        portfolio_grade = compute_attribution_grade(avg_score)

        sustainable_p = [r.protocol for r in reports if r.attribution_grade in ("A", "B")]
        unsustainable_p = [r.protocol for r in reports if r.attribution_grade in ("D", "F")]

        summary = YieldAttributionSummary(
            timestamp=time.time(),
            protocols=reports,
            portfolio_avg_sustainability_score=avg_score,
            portfolio_attribution_grade=portfolio_grade,
            sustainable_protocols=sustainable_p,
            unsustainable_protocols=unsustainable_p,
            avg_total_yield_pct=avg_total,
            avg_sustainable_yield_pct=avg_sust,
        )
        self._last_summary = summary
        save_summary(summary, self.data_file)
        return summary

    def get_sustainable_yield(self) -> float:
        """
        Return avg_sustainable_yield_pct from the most recent split() call.
        Returns 0.0 if split() has not been called yet.
        """
        if self._last_summary is None:
            return 0.0
        return self._last_summary.avg_sustainable_yield_pct

    def get_attribution_summary(self) -> Optional[YieldAttributionSummary]:
        """
        Return the full YieldAttributionSummary from the most recent split() call.
        Returns None if split() has not been called yet.
        """
        return self._last_summary


# ─── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-773 YieldAttributionSplitter — run with sample data"
    )
    parser.add_argument("--data-dir", default="data",
                        help="Directory for output JSON (default: data/)")
    args = parser.parse_args()

    data_file = Path(args.data_dir) / "yield_attribution_log.json"
    splitter = YieldAttributionSplitter(data_file=data_file)

    sample = [
        YieldComponents("Aave V3",           5.0, 3.5, 1.0, 0.3, 0.1, 0.1),
        YieldComponents("Compound V3",        4.8, 3.0, 0.8, 0.5, 0.3, 0.2),
        YieldComponents("Morpho Steakhouse",  6.5, 2.5, 1.0, 0.5, 1.5, 1.0),
        YieldComponents("Delta-Neutral S8",  27.5, 5.0, 2.0, 0.5, 15.0, 5.0),
    ]
    summary = splitter.split(sample)

    print(f"\n=== Yield Attribution Splitter (MP-773) ===")
    print(f"Portfolio grade      : {summary.portfolio_attribution_grade}")
    print(f"Avg sustainability   : {summary.portfolio_avg_sustainability_score:.1f}%")
    print(f"Sustainable protocols: {summary.sustainable_protocols}")
    print(f"Unsustainable        : {summary.unsustainable_protocols}")
    print()
    for r in summary.protocols:
        print(
            f"  {r.protocol:25s}  total={r.total_yield_pct:5.1f}%  "
            f"sust={r.sustainable_yield_pct:5.1f}%  "
            f"score={r.sustainability_score:5.1f}%  grade={r.attribution_grade}"
        )
    print(f"\nSaved → {data_file}")
