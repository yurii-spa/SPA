"""
MP-1010 DeFiProtocolLendingRateSpreadAnalyzer
Advisory/read-only. Pure stdlib. No external dependencies.

Analyzes spreads between borrow and supply rates in DeFi lending markets,
evaluating market efficiency, protocol revenue, and lending/borrowing conditions.

Data log: data/lending_rate_spread_log.json (ring-buffer 100, atomic write)
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "lending_rate_spread_log.json"
)
_LOG_CAP = 100

_DEFAULT_RISK_FREE_RATE = 4.5   # % — approximate T-bill / RWA benchmark
_DEFAULT_BENCHMARK_BORROW = 6.0  # % — benchmark borrow rate for comparisons


# ---------------------------------------------------------------------------
# Labels & Flags
# ---------------------------------------------------------------------------

LABEL_TIGHT_SPREAD = "TIGHT_SPREAD"        # spread<1.5%, util 60-80%
LABEL_EFFICIENT = "EFFICIENT"               # spread<3%
LABEL_NORMAL = "NORMAL"                     # spread 3-5%
LABEL_WIDE_SPREAD = "WIDE_SPREAD"           # spread>5%
LABEL_INEFFICIENT = "INEFFICIENT"           # spread>8% OR util>95%

FLAG_HIGH_UTILIZATION_RISK = "HIGH_UTILIZATION_RISK"          # util>90%
FLAG_WIDE_SPREAD_OPPORTUNITY = "WIDE_SPREAD_OPPORTUNITY"      # spread>6% — arb possible
FLAG_LOW_RESERVE_FACTOR = "LOW_RESERVE_FACTOR"                # reserve<5% — minimal protocol income
FLAG_PREMIUM_YIELD = "PREMIUM_YIELD"                          # lender_premium>3%
FLAG_LIQUIDATION_PROXIMITY = "LIQUIDATION_PROXIMITY"          # util>85% AND liquidation_bonus<10%
FLAG_TIGHT_EFFICIENT_MARKET = "TIGHT_EFFICIENT_MARKET"        # spread<2% AND util 70-85%


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _spread_efficiency_score(gross_spread_pct: float, utilization_rate_pct: float) -> float:
    """
    0-100 score: narrow spread + healthy utilization = efficient market.
    Ideal: spread ~1-2%, util ~70-80%.
    """
    # Spread component: narrow is better
    if gross_spread_pct <= 0.5:
        spread_score = 95.0
    elif gross_spread_pct <= 1.5:
        spread_score = 85.0
    elif gross_spread_pct <= 3.0:
        spread_score = 65.0
    elif gross_spread_pct <= 5.0:
        spread_score = 40.0
    elif gross_spread_pct <= 8.0:
        spread_score = 20.0
    else:
        spread_score = 5.0

    # Utilization component: 60-85% is optimal band
    if 60.0 <= utilization_rate_pct <= 85.0:
        util_score = 90.0
    elif 50.0 <= utilization_rate_pct < 60.0 or 85.0 < utilization_rate_pct <= 90.0:
        util_score = 65.0
    elif 40.0 <= utilization_rate_pct < 50.0 or 90.0 < utilization_rate_pct <= 95.0:
        util_score = 40.0
    elif utilization_rate_pct > 95.0:
        util_score = 15.0
    else:
        util_score = 25.0

    return round(_clamp(spread_score * 0.65 + util_score * 0.35, 0.0, 100.0), 2)


def _classify_market(
    gross_spread_pct: float,
    effective_spread_pct: float,
    utilization_rate_pct: float,
) -> str:
    """Assign market label based on spread and utilization."""
    if gross_spread_pct > 8.0 or utilization_rate_pct > 95.0:
        return LABEL_INEFFICIENT
    if gross_spread_pct > 5.0:
        return LABEL_WIDE_SPREAD
    if gross_spread_pct < 1.5 and 60.0 <= utilization_rate_pct <= 80.0:
        return LABEL_TIGHT_SPREAD
    if gross_spread_pct < 3.0:
        return LABEL_EFFICIENT
    return LABEL_NORMAL


def _compute_flags(
    gross_spread_pct: float,
    reserve_factor_pct: float,
    utilization_rate_pct: float,
    lender_yield_premium_pct: float,
    liquidation_bonus_pct: float,
) -> list:
    flags = []
    if utilization_rate_pct > 90.0:
        flags.append(FLAG_HIGH_UTILIZATION_RISK)
    if gross_spread_pct > 6.0:
        flags.append(FLAG_WIDE_SPREAD_OPPORTUNITY)
    if reserve_factor_pct < 5.0:
        flags.append(FLAG_LOW_RESERVE_FACTOR)
    if lender_yield_premium_pct > 3.0:
        flags.append(FLAG_PREMIUM_YIELD)
    if utilization_rate_pct > 85.0 and liquidation_bonus_pct < 10.0:
        flags.append(FLAG_LIQUIDATION_PROXIMITY)
    if gross_spread_pct < 2.0 and 70.0 <= utilization_rate_pct <= 85.0:
        flags.append(FLAG_TIGHT_EFFICIENT_MARKET)
    return flags


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class DeFiProtocolLendingRateSpreadAnalyzer:
    """
    Analyzes borrow-vs-supply rate spreads in DeFi lending markets.

    Each market dict:
        name                    str
        protocol                str
        asset                   str
        supply_apy_pct          float   — annual yield for lenders
        borrow_apy_pct          float   — annual cost for borrowers
        utilization_rate_pct    float   — % of supplied capital currently borrowed
        total_supplied_usd      float
        total_borrowed_usd      float
        reserve_factor_pct      float   — % of interest going to protocol reserve
        spread_benchmark_pct    float   — typical spread for this asset category
        liquidation_threshold_pct float — LTV at which position is liquidated
        liquidation_bonus_pct   float   — bonus for liquidators (%)
        protocol_fee_pct        float   — fee above gross spread charged by protocol

    Config keys (optional):
        risk_free_rate_pct      float   (default 4.5)
        benchmark_borrow_rate_pct float (default 6.0)
    """

    def analyze(self, markets: list, config: dict) -> dict:
        if not isinstance(markets, list) or not markets:
            return {
                "status": "no_data",
                "markets": [],
                "aggregates": {},
                "timestamp": time.time(),
            }

        risk_free = float(config.get("risk_free_rate_pct", _DEFAULT_RISK_FREE_RATE))
        benchmark_borrow = float(
            config.get("benchmark_borrow_rate_pct", _DEFAULT_BENCHMARK_BORROW)
        )

        results = []
        for mkt in markets:
            result = self._analyze_market(mkt, risk_free, benchmark_borrow)
            results.append(result)

        aggregates = self._aggregate(results)

        output = {
            "status": "ok",
            "markets": results,
            "aggregates": aggregates,
            "timestamp": time.time(),
        }

        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    def _analyze_market(
        self, mkt: dict, risk_free: float, benchmark_borrow: float
    ) -> dict:
        name = str(mkt.get("name", "unknown"))
        protocol = str(mkt.get("protocol", "unknown"))
        asset = str(mkt.get("asset", "unknown"))

        supply_apy = float(mkt.get("supply_apy_pct", 0.0))
        borrow_apy = float(mkt.get("borrow_apy_pct", 0.0))
        utilization = float(mkt.get("utilization_rate_pct", 0.0))
        total_supplied = float(mkt.get("total_supplied_usd", 0.0))
        total_borrowed = float(mkt.get("total_borrowed_usd", 0.0))
        reserve_factor = float(mkt.get("reserve_factor_pct", 10.0))
        spread_benchmark = float(mkt.get("spread_benchmark_pct", 2.0))
        liquidation_threshold = float(mkt.get("liquidation_threshold_pct", 80.0))
        liquidation_bonus = float(mkt.get("liquidation_bonus_pct", 5.0))
        protocol_fee = float(mkt.get("protocol_fee_pct", 0.0))

        # Core spread metrics
        gross_spread_pct = round(borrow_apy - supply_apy, 4)
        effective_spread_pct = round(gross_spread_pct - (reserve_factor / 100.0) * borrow_apy, 4)

        # Implied protocol revenue: reserve_factor × utilization/100 × supply_apy
        implied_protocol_revenue_pct = round(
            (reserve_factor / 100.0) * (utilization / 100.0) * supply_apy, 4
        )

        # Lender yield premium: supply_apy - risk_free_rate
        lender_yield_premium_pct = round(supply_apy - risk_free, 4)

        # Borrower cost premium: borrow_apy - benchmark_borrow_rate
        borrower_cost_premium_pct = round(borrow_apy - benchmark_borrow, 4)

        # Spread vs benchmark
        spread_vs_benchmark_pct = round(gross_spread_pct - spread_benchmark, 4)

        # Efficiency score 0-100
        efficiency_score = _spread_efficiency_score(gross_spread_pct, utilization)

        # Label
        label = _classify_market(gross_spread_pct, effective_spread_pct, utilization)

        # Flags
        flags = _compute_flags(
            gross_spread_pct,
            reserve_factor,
            utilization,
            lender_yield_premium_pct,
            liquidation_bonus,
        )

        # Derived: implied total borrowed from utilization if not given directly
        implied_borrowed_usd = round(total_supplied * utilization / 100.0, 2)
        cross_check_borrowed = round(total_borrowed, 2)

        return {
            "name": name,
            "protocol": protocol,
            "asset": asset,
            "supply_apy_pct": supply_apy,
            "borrow_apy_pct": borrow_apy,
            "utilization_rate_pct": utilization,
            "total_supplied_usd": total_supplied,
            "total_borrowed_usd": total_borrowed,
            "implied_borrowed_usd": implied_borrowed_usd,
            "reserve_factor_pct": reserve_factor,
            "spread_benchmark_pct": spread_benchmark,
            "liquidation_threshold_pct": liquidation_threshold,
            "liquidation_bonus_pct": liquidation_bonus,
            "protocol_fee_pct": protocol_fee,
            # Computed
            "gross_spread_pct": gross_spread_pct,
            "effective_spread_pct": effective_spread_pct,
            "implied_protocol_revenue_pct": implied_protocol_revenue_pct,
            "lender_yield_premium_pct": lender_yield_premium_pct,
            "borrower_cost_premium_pct": borrower_cost_premium_pct,
            "spread_vs_benchmark_pct": spread_vs_benchmark_pct,
            "spread_efficiency_score": efficiency_score,
            # Classification
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    def _aggregate(self, results: list) -> dict:
        if not results:
            return {}

        spreads = [r["gross_spread_pct"] for r in results]
        efficiencies = [r["spread_efficiency_score"] for r in results]

        tightest = min(results, key=lambda r: r["gross_spread_pct"])
        widest = max(results, key=lambda r: r["gross_spread_pct"])
        most_efficient = max(results, key=lambda r: r["spread_efficiency_score"])

        inefficient_count = sum(1 for r in results if r["label"] == LABEL_INEFFICIENT)
        wide_count = sum(1 for r in results if r["label"] == LABEL_WIDE_SPREAD)
        tight_count = sum(
            1 for r in results if r["label"] in (LABEL_TIGHT_SPREAD, LABEL_EFFICIENT)
        )

        avg_spread = round(sum(spreads) / len(spreads), 4) if spreads else 0.0
        avg_efficiency = round(sum(efficiencies) / len(efficiencies), 2) if efficiencies else 0.0

        flagged_high_util = sum(
            1 for r in results if FLAG_HIGH_UTILIZATION_RISK in r["flags"]
        )

        return {
            "market_count": len(results),
            "tightest_spread": {
                "name": tightest["name"],
                "gross_spread_pct": tightest["gross_spread_pct"],
            },
            "widest_spread": {
                "name": widest["name"],
                "gross_spread_pct": widest["gross_spread_pct"],
            },
            "most_efficient_market": {
                "name": most_efficient["name"],
                "spread_efficiency_score": most_efficient["spread_efficiency_score"],
            },
            "avg_spread_pct": avg_spread,
            "avg_efficiency_score": avg_efficiency,
            "inefficient_count": inefficient_count,
            "wide_spread_count": wide_count,
            "tight_count": tight_count,
            "high_utilization_risk_count": flagged_high_util,
        }

    # ------------------------------------------------------------------
    def _append_log(self, output: dict) -> None:
        """Append compressed record to ring-buffer log (atomic write)."""
        log_path = os.path.abspath(_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        record = {
            "ts": output["timestamp"],
            "market_count": len(output.get("markets", [])),
            "aggregates": output.get("aggregates", {}),
        }

        try:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            else:
                log = []
        except (json.JSONDecodeError, OSError):
            log = []

        log.append(record)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DeFi Lending Rate Spread Analyzer")
    parser.add_argument("--check", action="store_true", help="Run with sample data (no write)")
    parser.add_argument("--run", action="store_true", help="Run and write log")
    args = parser.parse_args()

    sample_markets = [
        {
            "name": "Aave-V3-USDC",
            "protocol": "Aave V3",
            "asset": "USDC",
            "supply_apy_pct": 3.5,
            "borrow_apy_pct": 5.8,
            "utilization_rate_pct": 72.0,
            "total_supplied_usd": 500_000_000,
            "total_borrowed_usd": 360_000_000,
            "reserve_factor_pct": 10.0,
            "spread_benchmark_pct": 2.0,
            "liquidation_threshold_pct": 80.0,
            "liquidation_bonus_pct": 5.0,
            "protocol_fee_pct": 0.3,
        },
        {
            "name": "Compound-V3-USDC",
            "protocol": "Compound V3",
            "asset": "USDC",
            "supply_apy_pct": 4.8,
            "borrow_apy_pct": 7.2,
            "utilization_rate_pct": 78.0,
            "total_supplied_usd": 300_000_000,
            "total_borrowed_usd": 234_000_000,
            "reserve_factor_pct": 8.0,
            "spread_benchmark_pct": 2.0,
            "liquidation_threshold_pct": 82.0,
            "liquidation_bonus_pct": 6.0,
            "protocol_fee_pct": 0.0,
        },
        {
            "name": "Morpho-Steakhouse-USDC",
            "protocol": "Morpho",
            "asset": "USDC",
            "supply_apy_pct": 6.5,
            "borrow_apy_pct": 8.1,
            "utilization_rate_pct": 91.0,
            "total_supplied_usd": 80_000_000,
            "total_borrowed_usd": 72_800_000,
            "reserve_factor_pct": 3.0,
            "spread_benchmark_pct": 2.0,
            "liquidation_threshold_pct": 85.0,
            "liquidation_bonus_pct": 4.0,
            "protocol_fee_pct": 0.5,
        },
    ]

    analyzer = DeFiProtocolLendingRateSpreadAnalyzer()
    result = analyzer.analyze(sample_markets, {})
    print(json.dumps(result, indent=2))
