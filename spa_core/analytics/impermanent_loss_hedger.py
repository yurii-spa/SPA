# spa_core/analytics/impermanent_loss_hedger.py
# MP-722 — ImpermanentLossHedger (pure stdlib, advisory/read-only)
#
# Calculates impermanent loss for AMM positions (constant-product formula)
# and recommends hedging strategies to offset IL risk.
#
# IL formula: IL = 2*sqrt(k) / (1 + k) - 1  where k = current_price_ratio / entry_price_ratio
# All writes are atomic (tmp + os.replace). Ring-buffer cap: 100 entries.
# LLM_FORBIDDEN: this module must never invoke LLM agents.

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

DATA_FILE = Path("data/il_hedger_log.json")
MAX_ENTRIES = 100

# Severity thresholds (% IL)
_NEGLIGIBLE_MAX = 0.5
_LOW_MAX = 2.0
_MODERATE_MAX = 5.0
# > MODERATE_MAX → HIGH

# Hedge strategy catalogue
_STRATEGIES = [
    {"strategy": "SHORT_PERP",    "cost_pct": 0.8,  "coverage_pct": 80},
    {"strategy": "OPTIONS_PUT",   "cost_pct": 1.5,  "coverage_pct": 90},
    {"strategy": "RANGE_TIGHTEN", "cost_pct": 0.3,  "coverage_pct": 50},
    {"strategy": "IL_INSURANCE",  "cost_pct": 2.0,  "coverage_pct": 95},
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ILCalculation:
    """Result of impermanent loss calculation for a single AMM position."""
    token_a: str
    token_b: str
    entry_price_ratio: float       # price_b / price_a at entry
    current_price_ratio: float     # price_b / price_a now
    position_value_usd: float

    # Derived (set by calculate)
    price_ratio_change: float = 0.0   # current / entry
    il_pct: float = 0.0               # % loss vs holding (positive number)
    il_usd: float = 0.0               # position_value * il_pct / 100

    # Breakeven
    yield_apy: float = 0.0
    days_to_breakeven_il: float = 0.0  # il_usd / (position_value * yield_apy / 365 / 100)

    severity: str = "NEGLIGIBLE"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HedgeRecommendation:
    """Full hedge recommendation wrapping an ILCalculation."""
    il_calc: ILCalculation

    hedge_strategies: List[dict] = field(default_factory=list)

    recommended_hedge: str = "NO_HEDGE"
    hedge_cost_pct: float = 0.0
    coverage_pct: float = 0.0
    net_il_after_hedge_pct: float = 0.0

    worth_hedging: bool = False
    reasoning: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    saved_to: str = ""

    def to_dict(self) -> dict:
        d = {
            "il_calc": self.il_calc.to_dict(),
            "hedge_strategies": self.hedge_strategies,
            "recommended_hedge": self.recommended_hedge,
            "hedge_cost_pct": self.hedge_cost_pct,
            "coverage_pct": self.coverage_pct,
            "net_il_after_hedge_pct": self.net_il_after_hedge_pct,
            "worth_hedging": self.worth_hedging,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
            "saved_to": self.saved_to,
        }
        return d


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def calculate_il(entry_price_ratio: float, current_price_ratio: float) -> float:
    """Return impermanent loss as a positive percentage.

    Uses the constant-product AMM formula:
        k = current_price_ratio / entry_price_ratio
        IL = 2 * sqrt(k) / (1 + k) - 1   (negative number)
        returns abs(IL) * 100
    """
    if entry_price_ratio <= 0:
        raise ValueError("entry_price_ratio must be > 0")
    if current_price_ratio < 0:
        raise ValueError("current_price_ratio must be >= 0")

    k = current_price_ratio / entry_price_ratio
    if k == 0:
        # Entire value of one token went to zero — maximum IL
        return 100.0

    il_fraction = 2.0 * math.sqrt(k) / (1.0 + k) - 1.0  # <= 0
    return abs(il_fraction) * 100.0


def severity_label(il_pct: float) -> str:
    """Map IL percentage to a severity label."""
    if il_pct < _NEGLIGIBLE_MAX:
        return "NEGLIGIBLE"
    if il_pct < _LOW_MAX:
        return "LOW"
    if il_pct < _MODERATE_MAX:
        return "MODERATE"
    return "HIGH"


def get_hedge_strategies(il_pct: float, position_usd: float) -> List[dict]:
    """Return all 4 hedge strategies with net_benefit_pct computed."""
    strategies = []
    for tmpl in _STRATEGIES:
        net = il_pct * tmpl["coverage_pct"] / 100.0 - tmpl["cost_pct"]
        strategies.append({
            "strategy": tmpl["strategy"],
            "cost_pct": tmpl["cost_pct"],
            "coverage_pct": tmpl["coverage_pct"],
            "net_benefit_pct": round(net, 6),
        })
    return strategies


def _days_to_breakeven(il_usd: float, position_value_usd: float, yield_apy: float) -> float:
    """Days for yield to recover the IL loss."""
    if position_value_usd <= 0 or yield_apy <= 0:
        return float("inf")
    daily_yield_usd = position_value_usd * yield_apy / 365.0 / 100.0
    if daily_yield_usd <= 0:
        return float("inf")
    return il_usd / daily_yield_usd


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def recommend(
    token_a: str,
    token_b: str,
    entry_price_ratio: float,
    current_price_ratio: float,
    position_value_usd: float,
    yield_apy: float,
) -> HedgeRecommendation:
    """Compute IL and produce a full hedge recommendation."""

    # ---- IL calculation ----
    il_pct = calculate_il(entry_price_ratio, current_price_ratio)
    k = current_price_ratio / entry_price_ratio if entry_price_ratio > 0 else 0
    il_usd = position_value_usd * il_pct / 100.0
    days_be = _days_to_breakeven(il_usd, position_value_usd, yield_apy)
    sev = severity_label(il_pct)

    il_calc = ILCalculation(
        token_a=token_a,
        token_b=token_b,
        entry_price_ratio=entry_price_ratio,
        current_price_ratio=current_price_ratio,
        position_value_usd=position_value_usd,
        price_ratio_change=k,
        il_pct=il_pct,
        il_usd=il_usd,
        yield_apy=yield_apy,
        days_to_breakeven_il=days_be,
        severity=sev,
    )

    # ---- Strategies ----
    strategies = get_hedge_strategies(il_pct, position_value_usd)

    # ---- Pick best strategy ----
    if il_pct < _NEGLIGIBLE_MAX:
        best_name = "NO_HEDGE"
        best_cost = 0.0
        best_cov = 0.0
    else:
        positives = [s for s in strategies if s["net_benefit_pct"] > 0]
        if not positives:
            best_name = "NO_HEDGE"
            best_cost = 0.0
            best_cov = 0.0
        else:
            best = max(positives, key=lambda s: s["net_benefit_pct"])
            best_name = best["strategy"]
            best_cost = best["cost_pct"]
            best_cov = best["coverage_pct"]

    # net IL after hedge: il_pct - coverage * il_pct / 100 - cost
    if best_name != "NO_HEDGE":
        net_il = il_pct - best_cov * il_pct / 100.0 - best_cost
    else:
        net_il = il_pct

    worth = (best_name != "NO_HEDGE") and (sev in ("MODERATE", "HIGH"))

    # ---- Reasoning ----
    reasoning: List[str] = []
    reasoning.append(f"IL = {il_pct:.4f}% ({sev})")
    if best_name == "NO_HEDGE":
        reasoning.append("No hedge warranted: IL too small or no strategy offers positive net benefit.")
    else:
        reasoning.append(
            f"Best hedge: {best_name} — covers {best_cov}% of IL at cost {best_cost}%."
        )
    if worth:
        reasoning.append("Hedging recommended: severity is MODERATE or HIGH and net benefit is positive.")
    else:
        reasoning.append("Hedging not recommended at this time.")

    # ---- Warnings ----
    warnings: List[str] = []
    if il_pct > 10.0:
        warnings.append("Severe IL (>10%) — consider exiting the position.")
    if days_be > 90.0 and days_be != float("inf"):
        warnings.append("Yield will not cover IL within 90 days — breakeven is slow.")
    if days_be == float("inf"):
        warnings.append("Yield is zero or position is zero — IL will never be recovered by yield.")

    rec = HedgeRecommendation(
        il_calc=il_calc,
        hedge_strategies=strategies,
        recommended_hedge=best_name,
        hedge_cost_pct=best_cost,
        coverage_pct=best_cov,
        net_il_after_hedge_pct=net_il,
        worth_hedging=worth,
        reasoning=reasoning,
        warnings=warnings,
        saved_to="",
    )
    return rec


def compare_positions(recommendations: List[HedgeRecommendation]) -> List[HedgeRecommendation]:
    """Sort recommendations by IL % descending (highest IL first)."""
    return sorted(recommendations, key=lambda r: r.il_calc.il_pct, reverse=True)


# ---------------------------------------------------------------------------
# Persistence (atomic, ring-buffer 100)
# ---------------------------------------------------------------------------

def _resolve_data_file(data_file: Optional[Path] = None) -> Path:
    return data_file if data_file is not None else DATA_FILE


def save_results(rec: HedgeRecommendation, data_file: Optional[Path] = None) -> str:
    """Append recommendation to ring-buffer log. Returns path written."""
    path = _resolve_data_file(data_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing
    try:
        with open(path, "r") as f:
            history = json.load(f)
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    entry = rec.to_dict()
    entry["_saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    history.append(entry)

    # Ring-buffer trim
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    # Atomic write
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp, path)

    rec.saved_to = str(path)
    return str(path)


def load_history(data_file: Optional[Path] = None) -> list:
    """Load full recommendation history from disk."""
    path = _resolve_data_file(data_file)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-722 ImpermanentLossHedger")
    parser.add_argument("--token-a", default="ETH", help="Token A symbol")
    parser.add_argument("--token-b", default="USDC", help="Token B symbol")
    parser.add_argument("--entry-price-ratio", type=float, default=1800.0)
    parser.add_argument("--current-price-ratio", type=float, default=2400.0)
    parser.add_argument("--position-usd", type=float, default=100_000.0)
    parser.add_argument("--yield-apy", type=float, default=15.0)
    parser.add_argument("--save", action="store_true", help="Save result to data/il_hedger_log.json")
    args = parser.parse_args()

    result = recommend(
        token_a=args.token_a,
        token_b=args.token_b,
        entry_price_ratio=args.entry_price_ratio,
        current_price_ratio=args.current_price_ratio,
        position_value_usd=args.position_usd,
        yield_apy=args.yield_apy,
    )

    print(f"\n=== ImpermanentLossHedger (MP-722) ===")
    print(f"Pair:          {result.il_calc.token_a}/{result.il_calc.token_b}")
    print(f"IL:            {result.il_calc.il_pct:.4f}% ({result.il_calc.severity})")
    print(f"IL (USD):      ${result.il_calc.il_usd:,.2f}")
    print(f"Days breakeven:{result.il_calc.days_to_breakeven_il:.1f}")
    print(f"Recommended:   {result.recommended_hedge}")
    print(f"Worth hedging: {result.worth_hedging}")
    for line in result.reasoning:
        print(f"  • {line}")
    for w in result.warnings:
        print(f"  ⚠ {w}")

    if args.save:
        path = save_results(result)
        print(f"\nSaved → {path}")
