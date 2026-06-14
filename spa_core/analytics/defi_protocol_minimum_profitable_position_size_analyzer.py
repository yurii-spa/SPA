"""
MP-1150: DeFiProtocolMinimumProfitablePositionSizeAnalyzer
==========================================================
Advisory/read-only analytics module.

Given a yield position's economics, compute the MINIMUM position size (USD) at
which net yield over the holding horizon covers round-trip transaction costs
(entry gas + exit gas, plus any extra claim/migration txs) PLUS an
opportunity-cost hurdle (risk-free / next-best alternative). In other words:
"is this deposit even worth it after gas, or is it dust?"

This isolates the *entry-economics break-even / dust-threshold* question — at
what size does the spread of (gross APR − opportunity APR) over the holding
period repay the one-off gas drag, and how far above (or below) that threshold
is the proposed position.

Distinct from:
  * gas_cost monitors            → they track the gas PRICE / gas drag itself.
  * exit_liquidity analyzers      → they model EXIT slippage / depth.
  * yield_harvesting_frequency_optimizer → it picks compounding CADENCE.
This module answers only the minimum-profitable-size / break-even question.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "minimum_profitable_position_size_log.json"
)
LOG_CAP = 100

SIZE_SENTINEL_NEVER = 1e15     # spread <= 0 → no size is ever profitable
DAYS_SENTINEL_NEVER = 1e9      # spread <= 0 → never breaks even
RATIO_SENTINEL_INF = 1e9       # gas ~ 0 → yield-per-gas effectively infinite

DEFAULT_HOLDING_DAYS = 365.0
DEFAULT_OPP_COST_APR = 4.0

# Gas-drag thresholds (round-trip gas as % of position)
HIGH_GAS_DRAG_PCT = 2.0        # gas eats >=2% of capital → heavy drag
LOW_GAS_DRAG_PCT = 0.25        # gas <0.25% of capital → negligible

# Net-excess (over horizon) classification thresholds, as ratio to roundtrip gas
EXCESS_HIGH = 5.0              # net excess >= 5x gas → highly profitable
EXCESS_GOOD = 1.5             # net excess >= 1.5x gas → profitable
EXCESS_MARGINAL = 0.0         # net excess just positive → marginal

# Break-even-vs-horizon thresholds (entry_breakeven_days / horizon)
FAST_BREAKEVEN_FRAC = 0.1     # break even in <10% of horizon → fast
LONG_BREAKEVEN_FRAC = 1.0     # break even only beyond horizon → too slow


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolMinimumProfitablePositionSizeAnalyzer:
    """
    Analyzes minimum-profitable position size / entry break-even for yield deposits.

    Per-position input dict fields:
        token                      : str
        position_usd               : float  (proposed deposit size)
        gross_apr_pct              : float  (headline yield of the position)
        entry_gas_usd              : float  (one-off cost to enter)
        exit_gas_usd               : float  (one-off cost to exit)
        holding_period_days        : float  (default 365)
        opportunity_cost_apr_pct   : float  (hurdle / risk-free, default 4.0)
        expected_extra_tx_count    : float  (claims/migrations, default 0)
        gas_per_extra_tx_usd       : float  (default 0)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("token", "UNKNOWN")
        position = _f(p.get("position_usd"))
        gross_apr = _f(p.get("gross_apr_pct"))
        entry_gas = max(0.0, _f(p.get("entry_gas_usd")))
        exit_gas = max(0.0, _f(p.get("exit_gas_usd")))
        days = _f(p.get("holding_period_days"), DEFAULT_HOLDING_DAYS)
        if days <= 0:
            days = DEFAULT_HOLDING_DAYS
        opp_apr = _f(p.get("opportunity_cost_apr_pct"), DEFAULT_OPP_COST_APR)
        extra_tx = max(0.0, _f(p.get("expected_extra_tx_count")))
        gas_per_extra = max(0.0, _f(p.get("gas_per_extra_tx_usd")))

        # Insufficient data: no position, or no/negative gross yield to analyze.
        if position <= 0 or gross_apr <= 0:
            return self._insufficient(token, position)

        roundtrip_gas = entry_gas + exit_gas + extra_tx * gas_per_extra
        horizon_frac = days / 365.0

        gross_yield = position * gross_apr / 100.0 * horizon_frac
        opp_cost = position * opp_apr / 100.0 * horizon_frac
        net_excess = gross_yield - opp_cost - roundtrip_gas

        gas_as_pct = _safe_div(roundtrip_gas, position, RATIO_SENTINEL_INF) * 100.0
        if gas_as_pct >= RATIO_SENTINEL_INF:
            gas_as_pct = RATIO_SENTINEL_INF

        spread = gross_apr - opp_apr  # the per-annum % spread over the hurdle

        # min profitable position: roundtrip_gas / (spread/100 * horizon_frac)
        spread_yield_per_dollar = spread / 100.0 * horizon_frac
        if spread_yield_per_dollar <= 0:
            min_profitable = SIZE_SENTINEL_NEVER
        else:
            min_profitable = _safe_div(roundtrip_gas, spread_yield_per_dollar, SIZE_SENTINEL_NEVER)

        # entry break-even days at THIS position size
        spread_yield_per_day = position * spread / 100.0 / 365.0
        if spread_yield_per_day <= 0:
            breakeven_days = DAYS_SENTINEL_NEVER
        else:
            breakeven_days = _safe_div(roundtrip_gas, spread_yield_per_day, DAYS_SENTINEL_NEVER)

        yield_per_gas = _safe_div(gross_yield, roundtrip_gas, RATIO_SENTINEL_INF)
        if yield_per_gas >= RATIO_SENTINEL_INF:
            yield_per_gas = RATIO_SENTINEL_INF

        score = self._efficiency_score(
            net_excess, roundtrip_gas, gas_as_pct, breakeven_days, days, spread,
        )
        classification = self._classify(
            net_excess, roundtrip_gas, spread, position, min_profitable,
        )
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, position, min_profitable, spread)
        flags = self._flags(
            spread, position, min_profitable, gas_as_pct, breakeven_days,
            days, net_excess, classification,
        )

        return {
            "token": token,
            "position_usd": round(position, 2),
            "roundtrip_gas_usd": round(roundtrip_gas, 2),
            "gross_yield_over_horizon_usd": round(gross_yield, 2),
            "opportunity_cost_over_horizon_usd": round(opp_cost, 2),
            "net_excess_over_horizon_usd": round(net_excess, 2),
            "gas_as_pct_of_position": (
                None if gas_as_pct >= RATIO_SENTINEL_INF else round(gas_as_pct, 4)
            ),
            "min_profitable_position_usd": (
                None if min_profitable >= SIZE_SENTINEL_NEVER else round(min_profitable, 2)
            ),
            "entry_breakeven_days": (
                None if breakeven_days >= DAYS_SENTINEL_NEVER else round(breakeven_days, 2)
            ),
            "yield_per_gas_ratio": (
                None if yield_per_gas >= RATIO_SENTINEL_INF else round(yield_per_gas, 4)
            ),
            "capital_efficiency_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _efficiency_score(
        self,
        net_excess: float,
        roundtrip_gas: float,
        gas_as_pct: float,
        breakeven_days: float,
        days: float,
        spread: float,
    ) -> float:
        """
        0–100, higher = better. Weighted:
          net-excess ratio (≈45) + low gas drag (≈25)
          + horizon coverage vs breakeven (≈20) + positive-spread bonus (≈10).
        """
        # Net-excess component — ratio of net excess to round-trip gas, saturating.
        if roundtrip_gas <= 0:
            excess_ratio = EXCESS_HIGH if net_excess > 0 else 0.0
        else:
            excess_ratio = net_excess / roundtrip_gas
        excess = 45.0 * _clamp(excess_ratio / EXCESS_HIGH, 0.0, 1.0)

        # Gas-drag component — 0% drag → full, HIGH_GAS_DRAG_PCT+ → 0.
        if gas_as_pct >= RATIO_SENTINEL_INF:
            gas = 0.0
        else:
            gas = 25.0 * _clamp(1.0 - gas_as_pct / HIGH_GAS_DRAG_PCT, 0.0, 1.0)

        # Horizon-coverage component — break even well within horizon → full.
        if breakeven_days >= DAYS_SENTINEL_NEVER or days <= 0:
            coverage = 0.0
        else:
            frac = breakeven_days / days
            coverage = 20.0 * _clamp(1.0 - frac, 0.0, 1.0)

        # Positive-spread bonus.
        bonus = 10.0 if spread > 0 else 0.0

        return _clamp(excess + gas + coverage + bonus, 0.0, 100.0)

    def _classify(
        self,
        net_excess: float,
        roundtrip_gas: float,
        spread: float,
        position: float,
        min_profitable: float,
    ) -> str:
        if spread <= 0:
            return "UNPROFITABLE"
        if net_excess <= 0:
            # positive spread but doesn't cover gas at this size
            if min_profitable < SIZE_SENTINEL_NEVER and position < min_profitable:
                return "DUST"
            return "UNPROFITABLE"
        if roundtrip_gas <= 0:
            ratio = EXCESS_HIGH
        else:
            ratio = net_excess / roundtrip_gas
        if ratio >= EXCESS_HIGH:
            return "HIGHLY_PROFITABLE"
        if ratio >= EXCESS_GOOD:
            return "PROFITABLE"
        return "MARGINAL"

    def _recommend(
        self,
        classification: str,
        position: float,
        min_profitable: float,
        spread: float,
    ) -> str:
        if classification in ("HIGHLY_PROFITABLE", "PROFITABLE", "MARGINAL"):
            return "DEPLOY"
        if classification == "DUST" and spread > 0 and min_profitable < SIZE_SENTINEL_NEVER:
            return "DEPLOY_LARGER"
        return "SKIP"

    def _flags(
        self,
        spread: float,
        position: float,
        min_profitable: float,
        gas_as_pct: float,
        breakeven_days: float,
        days: float,
        net_excess: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if spread <= 0:
            flags.append("NEGATIVE_SPREAD")

        below_min = min_profitable < SIZE_SENTINEL_NEVER and position < min_profitable
        if below_min:
            flags.append("BELOW_MIN_SIZE")
            flags.append("DUST_POSITION")
        else:
            if spread > 0 and net_excess > 0:
                flags.append("CLEARS_HURDLE")

        if gas_as_pct >= HIGH_GAS_DRAG_PCT and gas_as_pct < RATIO_SENTINEL_INF:
            flags.append("HIGH_GAS_DRAG")

        if breakeven_days >= DAYS_SENTINEL_NEVER:
            pass
        elif breakeven_days > days:
            flags.append("LONG_BREAKEVEN")
        elif breakeven_days <= days * FAST_BREAKEVEN_FRAC:
            flags.append("FAST_BREAKEVEN")

        if net_excess <= 0:
            flags.append("UNPROFITABLE_AT_HORIZON")

        return flags

    def _insufficient(self, token: str, position: float) -> dict:
        return {
            "token": token,
            "position_usd": round(max(0.0, position), 2),
            "roundtrip_gas_usd": 0.0,
            "gross_yield_over_horizon_usd": 0.0,
            "opportunity_cost_over_horizon_usd": 0.0,
            "net_excess_over_horizon_usd": 0.0,
            "gas_as_pct_of_position": None,
            "min_profitable_position_usd": None,
            "entry_breakeven_days": None,
            "yield_per_gas_ratio": None,
            "capital_efficiency_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "SKIP",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_efficient_position": None,
                "least_efficient_position": None,
                "avg_capital_efficiency_score": 0.0,
                "dust_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["capital_efficiency_score"])
        avg = _mean([r["capital_efficiency_score"] for r in scored])
        dust = sum(1 for r in results if r["classification"] == "DUST")
        return {
            "most_efficient_position": by_score[-1]["token"],
            "least_efficient_position": by_score[0]["token"],
            "avg_capital_efficiency_score": round(avg, 2),
            "dust_count": dust,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "capital_efficiency_score": r["capital_efficiency_score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "token": "USDC-Aave",
            "position_usd": 100_000.0,
            "gross_apr_pct": 8.0,
            "entry_gas_usd": 15.0,
            "exit_gas_usd": 15.0,
            "holding_period_days": 365.0,
            "opportunity_cost_apr_pct": 4.0,
            "expected_extra_tx_count": 4,
            "gas_per_extra_tx_usd": 5.0,
        },
        {
            "token": "DustFarm",
            "position_usd": 250.0,
            "gross_apr_pct": 12.0,
            "entry_gas_usd": 40.0,
            "exit_gas_usd": 40.0,
            "holding_period_days": 90.0,
            "opportunity_cost_apr_pct": 4.0,
            "expected_extra_tx_count": 2,
            "gas_per_extra_tx_usd": 20.0,
        },
        {
            "token": "BelowHurdle",
            "position_usd": 50_000.0,
            "gross_apr_pct": 3.0,
            "entry_gas_usd": 10.0,
            "exit_gas_usd": 10.0,
            "holding_period_days": 365.0,
            "opportunity_cost_apr_pct": 4.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1150 Minimum Profitable Position Size Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolMinimumProfitablePositionSizeAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
