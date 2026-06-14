"""
MP-1036: DeFiProtocolYieldTokenizationRiskAnalyzer
Analyzes risks of yield tokenization protocols (Pendle-style PT/YT splits).

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.
"""

from dataclasses import dataclass
from typing import List
import json
import math
import os
import time
from pathlib import Path

DATA_FILE = Path("data/yield_tokenization_risk_log.json")
MAX_ENTRIES = 100


@dataclass
class YieldTokenizationInput:
    protocol_name: str
    maturity_days: int            # total days of the PT/YT epoch
    fixed_rate_pct: float         # locked fixed rate (% APY) earned by PT holder
    implied_apy_pct: float        # current market-implied APY (PT price discount → APY)
    underlying_apy_pct: float     # current variable APY of the underlying asset
    tvl_usd: float                # total value locked in the yield tokenization pool
    pt_market_depth_usd: float    # available buy/sell depth for PT in secondary market
    days_to_maturity: int         # remaining days until PT/YT expiry


@dataclass
class YieldTokenizationResult:
    protocol_name: str
    # Scores (0–100)
    rate_lock_value_score: float      # How attractive the fixed rate lock-in is vs underlying
    maturity_risk_score: float        # Risk from remaining time to maturity (0=safe, 100=risky)
    liquidity_exit_risk: float        # Risk of being unable to exit before maturity (0=safe, 100=risky)
    yield_capture_efficiency_pct: float  # fixed_rate / implied_apy * 100 (how much yield captured)
    composite_score: float            # Weighted aggregate (higher = better)
    label: str                        # IDEAL_YIELD_STRIP / GOOD_OPPORTUNITY / MODERATE_RISK / HIGH_RISK / AVOID
    # Raw inputs echoed for logging
    fixed_rate_pct: float
    implied_apy_pct: float
    underlying_apy_pct: float
    tvl_usd: float
    pt_market_depth_usd: float
    days_to_maturity: int


class DeFiProtocolYieldTokenizationRiskAnalyzer:
    """
    Analyze risks of yield tokenization (Pendle-style PT/YT) positions.

    Yield tokenization splits a yield-bearing asset into:
      • PT (Principal Token): guarantees fixed principal + fixed yield at maturity.
      • YT (Yield Token):     receives all variable yield until maturity.

    This analyzer focuses on the PT-side risk/reward profile.

    Scoring dimensions:
      1. rate_lock_value_score   — premium of fixed_rate vs underlying_apy (higher = better deal)
      2. maturity_risk_score     — uncertainty from remaining time (longer = riskier)
      3. liquidity_exit_risk     — secondary market depth vs TVL (thin market = risky exit)
      4. yield_capture_efficiency_pct — fixed_rate / implied_apy (>100% = buying at discount)

    All outputs are advisory; no execution or risk state is modified.
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal computation helpers
    # ------------------------------------------------------------------

    def _rate_lock_value_score(
        self, fixed_rate_pct: float, underlying_apy_pct: float
    ) -> float:
        """
        Score (0–100) reflecting how attractive the fixed-rate lock is.

        A fixed rate equal to the underlying APY → 50 (neutral).
        Each 1pp above underlying adds 10 points; each 1pp below subtracts 10.
        """
        premium = fixed_rate_pct - underlying_apy_pct
        score = 50.0 + premium * 10.0
        return round(max(0.0, min(100.0, score)), 2)

    def _maturity_risk_score(self, days_to_maturity: int) -> float:
        """
        Score (0–100) reflecting uncertainty from remaining time.

        0 days → 0 (safe, already matured / about to mature).
        730 days → 100 (maximum risk horizon).
        Linear between 0–730; capped at 100.
        """
        score = (days_to_maturity / 730.0) * 100.0
        return round(max(0.0, min(100.0, score)), 2)

    def _liquidity_exit_risk(
        self, pt_market_depth_usd: float, tvl_usd: float
    ) -> float:
        """
        Score (0–100) reflecting secondary-market exit risk.

        depth_ratio = pt_market_depth_usd / tvl_usd.
        depth_ratio >= 0.50 → 0  (ample liquidity, easy exit).
        depth_ratio = 0    → 100 (no liquidity, cannot exit).
        Linear interpolation between the two endpoints.
        """
        if tvl_usd <= 0:
            return 100.0
        depth_ratio = pt_market_depth_usd / tvl_usd
        # clamp ratio to [0, 0.5]; map linearly to [100, 0]
        ratio_clamped = max(0.0, min(0.5, depth_ratio))
        score = (1.0 - ratio_clamped / 0.5) * 100.0
        return round(max(0.0, min(100.0, score)), 2)

    def _yield_capture_efficiency_pct(
        self, fixed_rate_pct: float, implied_apy_pct: float
    ) -> float:
        """
        Percentage of the market-implied APY captured as a fixed rate.

        = fixed_rate_pct / implied_apy_pct * 100.
        Capped at 200% (buying PT at discount can give > 100% efficiency).
        Returns 0 when implied_apy_pct <= 0.
        """
        if implied_apy_pct <= 0.0:
            return 0.0
        efficiency = (fixed_rate_pct / implied_apy_pct) * 100.0
        return round(max(0.0, min(200.0, efficiency)), 2)

    def _composite_score(
        self,
        rate_lock_value_score: float,
        maturity_risk_score: float,
        liquidity_exit_risk: float,
        yield_capture_efficiency_pct: float,
    ) -> float:
        """
        Weighted composite score (0–100).  Higher is better.

          • rate_lock_value_score      weight 0.35  (attractiveness of fixed rate)
          • maturity safety            weight 0.25  (100 - maturity_risk_score)
          • liquidity safety           weight 0.25  (100 - liquidity_exit_risk)
          • yield_capture (capped 100) weight 0.15
        """
        maturity_safety = 100.0 - maturity_risk_score
        liquidity_safety = 100.0 - liquidity_exit_risk
        efficiency_norm = min(100.0, yield_capture_efficiency_pct)
        composite = (
            rate_lock_value_score * 0.35
            + maturity_safety * 0.25
            + liquidity_safety * 0.25
            + efficiency_norm * 0.15
        )
        return round(max(0.0, min(100.0, composite)), 2)

    def _label(self, composite_score: float) -> str:
        """Map composite score to a human-readable label."""
        if composite_score >= 75.0:
            return "IDEAL_YIELD_STRIP"
        if composite_score >= 60.0:
            return "GOOD_OPPORTUNITY"
        if composite_score >= 45.0:
            return "MODERATE_RISK"
        if composite_score >= 30.0:
            return "HIGH_RISK"
        return "AVOID"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, inp: YieldTokenizationInput) -> YieldTokenizationResult:
        """Analyse a single yield tokenization opportunity."""
        rlvs = self._rate_lock_value_score(inp.fixed_rate_pct, inp.underlying_apy_pct)
        mrs = self._maturity_risk_score(inp.days_to_maturity)
        ler = self._liquidity_exit_risk(inp.pt_market_depth_usd, inp.tvl_usd)
        yce = self._yield_capture_efficiency_pct(inp.fixed_rate_pct, inp.implied_apy_pct)
        comp = self._composite_score(rlvs, mrs, ler, yce)
        lbl = self._label(comp)
        return YieldTokenizationResult(
            protocol_name=inp.protocol_name,
            rate_lock_value_score=rlvs,
            maturity_risk_score=mrs,
            liquidity_exit_risk=ler,
            yield_capture_efficiency_pct=yce,
            composite_score=comp,
            label=lbl,
            fixed_rate_pct=round(inp.fixed_rate_pct, 6),
            implied_apy_pct=round(inp.implied_apy_pct, 6),
            underlying_apy_pct=round(inp.underlying_apy_pct, 6),
            tvl_usd=round(inp.tvl_usd, 2),
            pt_market_depth_usd=round(inp.pt_market_depth_usd, 2),
            days_to_maturity=inp.days_to_maturity,
        )

    def analyze_batch(
        self, inputs: List[YieldTokenizationInput]
    ) -> List[YieldTokenizationResult]:
        """Analyse a list of inputs and return results in order."""
        return [self.analyze(inp) for inp in inputs]

    def best_opportunity(
        self, results: List[YieldTokenizationResult]
    ) -> YieldTokenizationResult:
        """Return the result with the highest composite_score."""
        if not results:
            raise ValueError("Empty results list")
        return max(results, key=lambda r: r.composite_score)

    def filter_by_label(
        self, results: List[YieldTokenizationResult], label: str
    ) -> List[YieldTokenizationResult]:
        """Return all results matching the given label."""
        return [r for r in results if r.label == label]

    def filter_investable(
        self, results: List[YieldTokenizationResult]
    ) -> List[YieldTokenizationResult]:
        """Return results labelled IDEAL_YIELD_STRIP or GOOD_OPPORTUNITY."""
        return [
            r for r in results
            if r.label in {"IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY"}
        ]

    def save_results(self, results: List[YieldTokenizationResult]) -> None:
        """
        Append results to the ring-buffer JSON log (max MAX_ENTRIES).
        Atomic write: tmp + os.replace.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        ts = time.time()
        for r in results:
            existing.append({
                "timestamp": ts,
                "protocol_name": r.protocol_name,
                "rate_lock_value_score": r.rate_lock_value_score,
                "maturity_risk_score": r.maturity_risk_score,
                "liquidity_exit_risk": r.liquidity_exit_risk,
                "yield_capture_efficiency_pct": r.yield_capture_efficiency_pct,
                "composite_score": r.composite_score,
                "label": r.label,
                "days_to_maturity": r.days_to_maturity,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


if __name__ == "__main__":
    import sys

    analyzer = DeFiProtocolYieldTokenizationRiskAnalyzer()
    sample = YieldTokenizationInput(
        protocol_name="Pendle-USDC",
        maturity_days=180,
        fixed_rate_pct=8.5,
        implied_apy_pct=9.0,
        underlying_apy_pct=6.5,
        tvl_usd=50_000_000,
        pt_market_depth_usd=5_000_000,
        days_to_maturity=90,
    )
    result = analyzer.analyze(sample)
    print(f"Protocol     : {result.protocol_name}")
    print(f"Rate Lock    : {result.rate_lock_value_score}")
    print(f"Maturity Risk: {result.maturity_risk_score}")
    print(f"Exit Risk    : {result.liquidity_exit_risk}")
    print(f"Efficiency   : {result.yield_capture_efficiency_pct}%")
    print(f"Composite    : {result.composite_score}")
    print(f"Label        : {result.label}")
