"""
MP-1037: ProtocolDeFiConcentratedLiquidityRangeOptimizer
Analyzes optimal price range for concentrated liquidity positions (Uniswap V3 style).

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

DATA_FILE = Path("data/concentrated_liquidity_range_log.json")
MAX_ENTRIES = 100


@dataclass
class ConcentratedLiquidityInput:
    current_price: float          # current spot price (e.g. 2000 USDC per ETH)
    lower_tick_price: float       # lower bound of LP range
    upper_tick_price: float       # upper bound of LP range
    price_volatility_30d_pct: float  # 30-day realized price volatility (%)
    fee_tier_bps: int             # pool fee tier in basis points (e.g. 5, 30, 100)
    daily_volume_usd: float       # pool's 24h trading volume in USD
    position_size_usd: float      # LP position size in USD


@dataclass
class ConcentratedLiquidityResult:
    # Scores / metrics
    range_utilization_pct: float      # estimated % of time price stays in range (0–100)
    expected_fee_apy_pct: float       # estimated annual fee yield on position
    il_risk_score: float              # impermanent-loss risk (0=safe, 100=extreme IL)
    capital_efficiency_multiplier: float  # liquidity multiplier vs full-range v2
    composite_score: float            # weighted aggregate (higher = better)
    label: str                        # OPTIMAL_RANGE / EFFICIENT / SUBOPTIMAL / WIDE_RANGE / OUT_OF_RANGE_RISK
    is_in_range: bool                 # True when lower <= current <= upper
    # Raw inputs echoed for logging
    current_price: float
    lower_tick_price: float
    upper_tick_price: float
    price_volatility_30d_pct: float
    fee_tier_bps: int
    daily_volume_usd: float
    position_size_usd: float


class ProtocolDeFiConcentratedLiquidityRangeOptimizer:
    """
    Analyze the efficiency and risk of a Uniswap V3-style concentrated
    liquidity position given a specific price range.

    Key metrics:
      • range_utilization_pct     — how often the price stays inside the range
                                    (estimated via log-width vs 2-sigma volatility)
      • expected_fee_apy_pct      — annual fee revenue as % of position size
                                    (fee_rate × volume_turnover × utilization × 365)
      • il_risk_score             — impermanent-loss exposure (volatility / range half-width)
      • capital_efficiency_multiplier — liquidity provided per dollar vs full-range
                                        1 / (1 - sqrt(lower/upper))

    Labels:
      OPTIMAL_RANGE     — high utilization, high efficiency, manageable IL
      EFFICIENT         — good balance of utilization and IL risk
      SUBOPTIMAL        — moderate range quality, consider adjusting
      WIDE_RANGE        — overly wide range; low capital efficiency
      OUT_OF_RANGE_RISK — current price outside [lower, upper]; earning no fees

    All outputs are advisory; no execution or risk state is modified.
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal computation helpers
    # ------------------------------------------------------------------

    def _is_in_range(
        self, current_price: float, lower: float, upper: float
    ) -> bool:
        return lower <= current_price <= upper

    def _range_utilization_pct(
        self,
        current_price: float,
        lower: float,
        upper: float,
        vol_30d_pct: float,
    ) -> float:
        """
        Estimate the fraction of time the price remains within [lower, upper].

        If the current price is already out of range the utilization is
        penalised based on how far outside the range it is.

        When in range: uses the log-width of the range vs 2-sigma volatility.
            log_width  = ln(upper / lower)
            two_sigma  = 2 × (vol_30d_pct / 100)
            utilization = clamp(log_width / two_sigma, 0.05, 1.0) × 100

        A range wider than 2 standard deviations → ≥ 100% (capped at 100).
        """
        if lower <= 0 or upper <= 0 or current_price <= 0:
            return 0.0

        if not self._is_in_range(current_price, lower, upper):
            if current_price < lower:
                gap_pct = (lower - current_price) / lower * 100.0
            else:
                gap_pct = (current_price - upper) / upper * 100.0
            # Each 1pp gap cuts 5 points off a 5-point base
            return round(max(0.0, 5.0 - gap_pct), 2)

        if vol_30d_pct <= 0:
            # Zero volatility → price never moves → always in range
            return 100.0
        log_width = math.log(upper / lower)
        two_sigma = 2.0 * (vol_30d_pct / 100.0)
        ratio = log_width / two_sigma
        utilization = min(1.0, max(0.05, ratio)) * 100.0
        return round(utilization, 2)

    def _capital_efficiency_multiplier(
        self, lower: float, upper: float, current_price: float
    ) -> float:
        """
        Uniswap V3 capital efficiency relative to a full-range (v2) position.

        For an in-range position centred at current_price:
            multiplier = 1 / (1 - sqrt(lower / upper))

        Out-of-range positions provide no active liquidity → multiplier = 1.0.
        Capped at 500× to avoid extreme values for very tight ranges.
        """
        if not self._is_in_range(current_price, lower, upper):
            return 1.0
        if lower <= 0 or upper <= 0:
            return 1.0
        ratio = math.sqrt(lower / upper)
        denom = 1.0 - ratio
        if denom <= 0:
            return 1.0
        multiplier = 1.0 / denom
        return round(min(500.0, max(1.0, multiplier)), 4)

    def _expected_fee_apy_pct(
        self,
        fee_tier_bps: int,
        daily_volume_usd: float,
        position_size_usd: float,
        range_utilization_pct: float,
    ) -> float:
        """
        Estimate the annualised fee APY for the position.

        fee_rate = fee_tier_bps / 10 000
        The position earns fees proportional to volume turnover and the
        fraction of time it is active (range_utilization_pct).

            fee_apy_pct = fee_rate
                          × (daily_volume_usd / position_size_usd)
                          × 365
                          × (range_utilization_pct / 100)
                          × 100          ← convert to percentage

        Capped at 1 000% to avoid runaway estimates for extreme volume ratios.
        """
        if position_size_usd <= 0 or daily_volume_usd <= 0:
            return 0.0
        fee_rate = fee_tier_bps / 10_000.0
        volume_turnover = daily_volume_usd / position_size_usd
        apy = fee_rate * volume_turnover * 365 * (range_utilization_pct / 100.0) * 100.0
        return round(min(1_000.0, max(0.0, apy)), 4)

    def _il_risk_score(
        self,
        current_price: float,
        lower: float,
        upper: float,
        vol_30d_pct: float,
    ) -> float:
        """
        Impermanent-loss risk score (0–100).

        If the price is outside the range → maximum risk (100).
        If in range: compares 30-day volatility to the half-width of the range.

            range_half_pct = (upper - lower) / (2 × current_price) × 100
            il_risk = clamp(vol_30d_pct / range_half_pct × 100, 0, 100)

        A range half-width that equals the 30-day volatility → 100 (high risk).
        A range half-width 3× the volatility → ~33 (moderate risk).
        """
        if not self._is_in_range(current_price, lower, upper):
            return 100.0
        if current_price <= 0:
            return 100.0
        range_half_pct = (upper - lower) / (2.0 * current_price) * 100.0
        if range_half_pct <= 0:
            return 100.0
        risk = (vol_30d_pct / range_half_pct) * 100.0
        return round(max(0.0, min(100.0, risk)), 2)

    def _composite_score(
        self,
        range_utilization_pct: float,
        il_risk_score: float,
        expected_fee_apy_pct: float,
    ) -> float:
        """
        Weighted composite quality score (0–100).  Higher is better.

          • range utilization weight 0.40
          • IL safety (100-il_risk) weight 0.40
          • fee APY (capped 100 for normalisation) weight 0.20
        """
        fee_norm = min(100.0, expected_fee_apy_pct)
        il_safety = 100.0 - il_risk_score
        composite = (
            range_utilization_pct * 0.40
            + il_safety * 0.40
            + fee_norm * 0.20
        )
        return round(max(0.0, min(100.0, composite)), 2)

    def _label(
        self,
        composite_score: float,
        is_in_range: bool,
        range_utilization_pct: float,
        capital_efficiency_multiplier: float,
    ) -> str:
        """Map composite score and flags to a categorical label."""
        if not is_in_range:
            return "OUT_OF_RANGE_RISK"
        # Very wide range (low capital efficiency) regardless of composite
        if capital_efficiency_multiplier < 1.5:
            return "WIDE_RANGE"
        if composite_score >= 75.0:
            return "OPTIMAL_RANGE"
        if composite_score >= 55.0:
            return "EFFICIENT"
        if composite_score >= 35.0:
            return "SUBOPTIMAL"
        return "WIDE_RANGE"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, inp: ConcentratedLiquidityInput) -> ConcentratedLiquidityResult:
        """Analyse a single concentrated liquidity position."""
        in_range = self._is_in_range(
            inp.current_price, inp.lower_tick_price, inp.upper_tick_price
        )
        util = self._range_utilization_pct(
            inp.current_price,
            inp.lower_tick_price,
            inp.upper_tick_price,
            inp.price_volatility_30d_pct,
        )
        eff = self._capital_efficiency_multiplier(
            inp.lower_tick_price, inp.upper_tick_price, inp.current_price
        )
        fee_apy = self._expected_fee_apy_pct(
            inp.fee_tier_bps,
            inp.daily_volume_usd,
            inp.position_size_usd,
            util,
        )
        il_risk = self._il_risk_score(
            inp.current_price,
            inp.lower_tick_price,
            inp.upper_tick_price,
            inp.price_volatility_30d_pct,
        )
        comp = self._composite_score(util, il_risk, fee_apy)
        lbl = self._label(comp, in_range, util, eff)
        return ConcentratedLiquidityResult(
            range_utilization_pct=util,
            expected_fee_apy_pct=fee_apy,
            il_risk_score=il_risk,
            capital_efficiency_multiplier=eff,
            composite_score=comp,
            label=lbl,
            is_in_range=in_range,
            current_price=round(inp.current_price, 6),
            lower_tick_price=round(inp.lower_tick_price, 6),
            upper_tick_price=round(inp.upper_tick_price, 6),
            price_volatility_30d_pct=round(inp.price_volatility_30d_pct, 4),
            fee_tier_bps=inp.fee_tier_bps,
            daily_volume_usd=round(inp.daily_volume_usd, 2),
            position_size_usd=round(inp.position_size_usd, 2),
        )

    def analyze_batch(
        self, inputs: List[ConcentratedLiquidityInput]
    ) -> List[ConcentratedLiquidityResult]:
        """Analyse a list of inputs and return results in order."""
        return [self.analyze(inp) for inp in inputs]

    def best_range(
        self, results: List[ConcentratedLiquidityResult]
    ) -> ConcentratedLiquidityResult:
        """Return the result with the highest composite_score."""
        if not results:
            raise ValueError("Empty results list")
        return max(results, key=lambda r: r.composite_score)

    def filter_by_label(
        self, results: List[ConcentratedLiquidityResult], label: str
    ) -> List[ConcentratedLiquidityResult]:
        """Return all results matching the given label."""
        return [r for r in results if r.label == label]

    def filter_in_range(
        self, results: List[ConcentratedLiquidityResult]
    ) -> List[ConcentratedLiquidityResult]:
        """Return only in-range positions."""
        return [r for r in results if r.is_in_range]

    def save_results(self, results: List[ConcentratedLiquidityResult]) -> None:
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
                "range_utilization_pct": r.range_utilization_pct,
                "expected_fee_apy_pct": r.expected_fee_apy_pct,
                "il_risk_score": r.il_risk_score,
                "capital_efficiency_multiplier": r.capital_efficiency_multiplier,
                "composite_score": r.composite_score,
                "label": r.label,
                "is_in_range": r.is_in_range,
                "current_price": r.current_price,
                "lower_tick_price": r.lower_tick_price,
                "upper_tick_price": r.upper_tick_price,
                "fee_tier_bps": r.fee_tier_bps,
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
    optimizer = ProtocolDeFiConcentratedLiquidityRangeOptimizer()
    sample = ConcentratedLiquidityInput(
        current_price=2_000.0,
        lower_tick_price=1_800.0,
        upper_tick_price=2_200.0,
        price_volatility_30d_pct=15.0,
        fee_tier_bps=30,
        daily_volume_usd=5_000_000.0,
        position_size_usd=50_000.0,
    )
    result = optimizer.analyze(sample)
    print(f"Range Utilization : {result.range_utilization_pct}%")
    print(f"Fee APY           : {result.expected_fee_apy_pct}%")
    print(f"IL Risk Score     : {result.il_risk_score}")
    print(f"Capital Efficiency: {result.capital_efficiency_multiplier}×")
    print(f"Composite Score   : {result.composite_score}")
    print(f"Label             : {result.label}")
