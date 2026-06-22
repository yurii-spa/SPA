"""
MP-724: ConcentratedLiquidityAnalyzer
Analyze Uniswap v3-style concentrated liquidity positions — range efficiency,
out-of-range risk, capital efficiency vs full-range, and fee capture probability.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.
"""

from dataclasses import dataclass, field
from typing import List
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/concentrated_liquidity_log.json")
MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PriceRange:
    lower_tick_price: float   # lower bound price (e.g. 1800 USDC per ETH)
    upper_tick_price: float   # upper bound price
    current_price: float


@dataclass
class CLPosition:
    token_a: str
    token_b: str
    fee_tier: float           # e.g. 0.05 for 0.05%, 0.3, 1.0
    price_range: PriceRange
    liquidity_usd: float      # total position value in USD


@dataclass
class CLAnalysis:
    position: CLPosition

    # Range metrics
    range_width_pct: float        # (upper - lower) / lower * 100
    price_position_pct: float     # where current price sits in range: 0–100
    is_in_range: bool             # lower <= current <= upper
    distance_to_lower_pct: float  # (current - lower) / current * 100
    distance_to_upper_pct: float  # (upper - current) / current * 100

    # Capital efficiency vs full-range
    capital_efficiency_ratio: float  # sqrt(upper/lower) / (sqrt(upper/lower) - 1)

    # Fee capture
    fee_capture_probability: float  # max(0.1, min(0.99, 1 - range_width_pct / 200))
    expected_fee_apy: float         # fee_tier * capital_efficiency_ratio * fee_capture_probability * 52

    # IL risk
    il_if_exit_lower_pct: float  # IL if price moves to lower bound
    il_if_exit_upper_pct: float  # IL if price moves to upper bound

    # Recommendations
    range_quality: str        # "TOO_NARROW" | "OPTIMAL" | "WIDE" | "FULL_RANGE"
    action: str               # "HOLD" | "REBALANCE_RANGE" | "EXIT_REPOSITION" | "WIDEN_RANGE"
    warnings: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------

class ConcentratedLiquidityAnalyzer:
    """
    Analyse Uniswap v3-style concentrated liquidity positions.

    All computations are advisory estimates.  The module never writes to
    allocator, risk, or execution state.
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Pure calculation helpers
    # ------------------------------------------------------------------

    def calculate_il_to_price(self, current_price: float, target_price: float) -> float:
        """
        Impermanent-loss percentage when price moves from *current_price* to
        *target_price* in a constant-product AMM (Uniswap v2 formula).

        Returns IL as a positive percentage (e.g. 5.72 for ~5.72% loss).

        Special case: if current_price <= 0 or target_price <= 0 return 0.0.
        """
        if current_price <= 0 or target_price <= 0:
            return 0.0
        if current_price == target_price:
            return 0.0
        k = target_price / current_price
        il = abs(2.0 * (k ** 0.5) / (1.0 + k) - 1.0) * 100.0
        return round(il, 6)

    def capital_efficiency(self, lower: float, upper: float) -> float:
        """
        Capital efficiency multiplier of a concentrated position vs full-range.

        Approximation: sqrt(upper/lower) / (sqrt(upper/lower) - 1)

        Returns 1.0 for degenerate ranges (lower == upper, or lower <= 0).
        """
        if lower <= 0 or upper <= lower:
            return 1.0
        sqrt_ratio = (upper / lower) ** 0.5
        denominator = sqrt_ratio - 1.0
        if denominator <= 0:
            return 1.0
        return round(sqrt_ratio / denominator, 6)

    # ------------------------------------------------------------------
    # Range quality helpers
    # ------------------------------------------------------------------

    def _range_quality(self, range_width_pct: float) -> str:
        if range_width_pct < 5.0:
            return "TOO_NARROW"
        if range_width_pct < 30.0:
            return "OPTIMAL"
        if range_width_pct < 100.0:
            return "WIDE"
        return "FULL_RANGE"

    def _action(
        self,
        is_in_range: bool,
        range_quality: str,
        price_position_pct: float,
    ) -> str:
        if not is_in_range:
            return "EXIT_REPOSITION"
        if range_quality == "TOO_NARROW":
            return "WIDEN_RANGE"
        if price_position_pct < 15.0 or price_position_pct > 85.0:
            return "REBALANCE_RANGE"
        return "HOLD"

    def _warnings(
        self,
        is_in_range: bool,
        price_position_pct: float,
        il_if_exit_lower_pct: float,
    ) -> List[str]:
        warns: List[str] = []
        if not is_in_range:
            warns.append("position out of range (earning 0 fees)")
        if price_position_pct < 10.0:
            warns.append("price near lower bound")
        if price_position_pct > 90.0:
            warns.append("price near upper bound")
        if il_if_exit_lower_pct > 20.0:
            warns.append("high IL if lower bound hit")
        return warns

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, position: CLPosition) -> CLAnalysis:
        """Compute a full CLAnalysis for a single CLPosition."""
        pr = position.price_range
        lower = pr.lower_tick_price
        upper = pr.upper_tick_price
        current = pr.current_price

        # ---- range metrics ----
        # Protect against degenerate lower==0
        if lower > 0:
            range_width_pct = (upper - lower) / lower * 100.0
        else:
            range_width_pct = 0.0

        is_in_range = lower <= current <= upper

        if not is_in_range:
            price_position_pct = 0.0 if current < lower else 100.0
        else:
            span = upper - lower
            if span == 0:
                price_position_pct = 50.0
            else:
                price_position_pct = (current - lower) / span * 100.0

        if current > 0:
            distance_to_lower_pct = (current - lower) / current * 100.0
            distance_to_upper_pct = (upper - current) / current * 100.0
        else:
            distance_to_lower_pct = 0.0
            distance_to_upper_pct = 0.0

        # ---- capital efficiency ----
        cap_eff = self.capital_efficiency(lower, upper)

        # ---- fee capture ----
        fee_capture_prob = max(0.1, min(0.99, 1.0 - range_width_pct / 200.0))

        # fee_tier is expressed as percentage (e.g. 0.05 for 0.05%)
        # convert to decimal for multiplication: fee_tier / 100
        fee_tier_decimal = position.fee_tier / 100.0
        expected_fee_apy = fee_tier_decimal * cap_eff * fee_capture_prob * 52.0

        # ---- IL at bounds ----
        il_lower = self.calculate_il_to_price(current, lower)
        il_upper = self.calculate_il_to_price(current, upper)

        # ---- quality / action / warnings ----
        rq = self._range_quality(range_width_pct)
        action = self._action(is_in_range, rq, price_position_pct)
        warns = self._warnings(is_in_range, price_position_pct, il_lower)

        return CLAnalysis(
            position=position,
            range_width_pct=round(range_width_pct, 6),
            price_position_pct=round(price_position_pct, 6),
            is_in_range=is_in_range,
            distance_to_lower_pct=round(distance_to_lower_pct, 6),
            distance_to_upper_pct=round(distance_to_upper_pct, 6),
            capital_efficiency_ratio=cap_eff,
            fee_capture_probability=round(fee_capture_prob, 6),
            expected_fee_apy=round(expected_fee_apy, 6),
            il_if_exit_lower_pct=il_lower,
            il_if_exit_upper_pct=il_upper,
            range_quality=rq,
            action=action,
            warnings=warns,
            saved_to="",
        )

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_positions(self, analyses: List[CLAnalysis]) -> List[CLAnalysis]:
        """Return analyses sorted by expected_fee_apy descending."""
        return sorted(analyses, key=lambda a: a.expected_fee_apy, reverse=True)

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic write)
    # ------------------------------------------------------------------

    def _analysis_to_dict(self, analysis: CLAnalysis) -> dict:
        pos = analysis.position
        pr = pos.price_range
        return {
            "timestamp": time.time(),
            "token_a": pos.token_a,
            "token_b": pos.token_b,
            "fee_tier": pos.fee_tier,
            "lower_tick_price": pr.lower_tick_price,
            "upper_tick_price": pr.upper_tick_price,
            "current_price": pr.current_price,
            "liquidity_usd": pos.liquidity_usd,
            "range_width_pct": analysis.range_width_pct,
            "price_position_pct": analysis.price_position_pct,
            "is_in_range": analysis.is_in_range,
            "distance_to_lower_pct": analysis.distance_to_lower_pct,
            "distance_to_upper_pct": analysis.distance_to_upper_pct,
            "capital_efficiency_ratio": analysis.capital_efficiency_ratio,
            "fee_capture_probability": analysis.fee_capture_probability,
            "expected_fee_apy": analysis.expected_fee_apy,
            "il_if_exit_lower_pct": analysis.il_if_exit_lower_pct,
            "il_if_exit_upper_pct": analysis.il_if_exit_upper_pct,
            "range_quality": analysis.range_quality,
            "action": analysis.action,
            "warnings": analysis.warnings,
        }

    def save_results(self, analysis: CLAnalysis) -> str:
        """
        Append one analysis result to the ring-buffer JSON log (max MAX_ENTRIES).
        Uses atomic write: tmp + os.replace.
        Returns the path of the data file as a string.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        existing.append(self._analysis_to_dict(analysis))
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)
        analysis.saved_to = str(self.data_file)
        return str(self.data_file)

    def load_history(self) -> list:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _demo_position() -> CLPosition:
    """Return a sample position for the default CLI demo."""
    return CLPosition(
        token_a="ETH",
        token_b="USDC",
        fee_tier=0.05,
        price_range=PriceRange(
            lower_tick_price=1_800.0,
            upper_tick_price=2_200.0,
            current_price=2_000.0,
        ),
        liquidity_usd=50_000.0,
    )


def _print_analysis(a: CLAnalysis) -> None:
    pos = a.position
    pr = pos.price_range
    print(f"\n{'='*60}")
    print("  ConcentratedLiquidityAnalyzer — MP-724")
    print(f"  Pair: {pos.token_a}/{pos.token_b}  Fee: {pos.fee_tier}%")
    print(f"  Range: [{pr.lower_tick_price:,.2f} – {pr.upper_tick_price:,.2f}]  "
          f"Current: {pr.current_price:,.2f}")
    print(f"  Liquidity: ${pos.liquidity_usd:,.0f}")
    print(f"{'='*60}")
    print(f"  range_width_pct        : {a.range_width_pct:.2f}%")
    print(f"  price_position_pct     : {a.price_position_pct:.2f}%")
    print(f"  is_in_range            : {a.is_in_range}")
    print(f"  distance_to_lower_pct  : {a.distance_to_lower_pct:.2f}%")
    print(f"  distance_to_upper_pct  : {a.distance_to_upper_pct:.2f}%")
    print(f"  capital_efficiency_ratio: {a.capital_efficiency_ratio:.4f}x")
    print(f"  fee_capture_probability: {a.fee_capture_probability:.4f}")
    print(f"  expected_fee_apy       : {a.expected_fee_apy:.4f}%")
    print(f"  il_if_exit_lower_pct   : {a.il_if_exit_lower_pct:.4f}%")
    print(f"  il_if_exit_upper_pct   : {a.il_if_exit_upper_pct:.4f}%")
    print(f"  range_quality          : {a.range_quality}")
    print(f"  action                 : {a.action}")
    if a.warnings:
        for w in a.warnings:
            print(f"  ⚠  {w}")
    if a.saved_to:
        print(f"  saved_to               : {a.saved_to}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    run_mode = "--run" in sys.argv

    analyzer = ConcentratedLiquidityAnalyzer()
    pos = _demo_position()
    result = analyzer.analyze(pos)

    if run_mode:
        analyzer.save_results(result)

    _print_analysis(result)
    sys.exit(0)
