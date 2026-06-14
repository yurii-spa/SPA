"""
MP-1159: DeFiProtocolVaultRoundTripCostAnalyzer
===============================================
Advisory/read-only analytics module.

Rotating capital into and out of a vault incurs a ROUND-TRIP cost: a deposit
fee + a withdrawal fee + (optionally) entry and exit slippage. A yield optimizer
must decide whether the vault's APR advantage over the planned holding period
covers this one-off round-trip cost before the rotation is worthwhile.

This module isolates the *round-trip break-even* question — the total one-off
cost of entering and exiting (in percent of principal), the daily yield edge
that must repay it, how many days until break-even, the net gain at the planned
horizon, and whether the horizon is long enough to cover the round trip.

This isolates the *round-trip cost / break-even* question — deposit + withdraw +
slippage cost, break-even days vs. holding horizon, and net gain at horizon.

Distinct from:
  * idle_cash_drag             → it models uninvested capital and APY drag.
  * pending_harvest_premium    → it models a pending share-price step.
  * performance-fee analyzers  → they model ongoing fee drag on returns.
This module answers only the round-trip-cost / break-even question.

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
    "data", "vault_round_trip_cost_log.json"
)
LOG_CAP = 100

DAYS_PER_YEAR = 365.0

# Break-even-days classification bands (days)
CHEAP_DAYS = 7.0            # break-even <= 7 days → cheap
FAIR_DAYS = 30.0           # break-even <= 30 days → fair
EXPENSIVE_DAYS = 90.0      # break-even <= 90 days → expensive
# break-even > 90 days → prohibitive

# Flag thresholds
HIGH_ROUND_TRIP_PCT = 2.0   # round-trip cost >= 2% → high cost


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

class DeFiProtocolVaultRoundTripCostAnalyzer:
    """
    Analyzes the round-trip cost of rotating capital into and out of a vault and
    whether the vault's APR advantage repays that cost within the holding period.

    HIGHER score = BETTER (cheaper round trip and breaks even within horizon).

    Per-position input dict fields:
        vault / token         : str
        deposit_fee_pct       : float  (default 0)
        withdrawal_fee_pct    : float  (default 0)
        entry_slippage_pct    : float  (default 0)
        exit_slippage_pct     : float  (default 0)
        apr_advantage_pct     : float  (extra APR over next-best, default 0)
        expected_holding_days : float  (planned holding horizon, default 0)
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
        token = p.get("vault", p.get("token", "UNKNOWN"))
        deposit_fee = _clamp(_f(p.get("deposit_fee_pct")), 0.0, 100.0)
        withdrawal_fee = _clamp(_f(p.get("withdrawal_fee_pct")), 0.0, 100.0)
        entry_slip = _clamp(_f(p.get("entry_slippage_pct")), 0.0, 100.0)
        exit_slip = _clamp(_f(p.get("exit_slippage_pct")), 0.0, 100.0)
        apr_advantage = _f(p.get("apr_advantage_pct"))
        holding_days = max(0.0, _f(p.get("expected_holding_days")))

        round_trip_cost_pct = deposit_fee + withdrawal_fee + entry_slip + exit_slip

        # Insufficient data: nothing to assess if there's neither cost nor edge.
        if round_trip_cost_pct == 0.0 and apr_advantage == 0.0:
            return self._insufficient(token)

        daily_advantage_pct = apr_advantage / DAYS_PER_YEAR

        # Break-even days: None when the advantage never repays the cost.
        breakeven_raw = _safe_div(round_trip_cost_pct, daily_advantage_pct, None)
        breakeven_days = round(breakeven_raw, 4) if breakeven_raw is not None else None

        net_gain_pct = apr_advantage * holding_days / DAYS_PER_YEAR \
            - round_trip_cost_pct

        covers_horizon = (
            breakeven_days is not None
            and breakeven_days <= holding_days
            and holding_days > 0
        )

        classification = self._classify(breakeven_days, round_trip_cost_pct,
                                        apr_advantage)
        score = self._cost_score(round_trip_cost_pct, breakeven_days, holding_days)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, covers_horizon)
        flags = self._flags(
            round_trip_cost_pct, apr_advantage, breakeven_days, covers_horizon,
            net_gain_pct, holding_days,
        )

        return {
            "token": token,
            "deposit_fee_pct": round(deposit_fee, 4),
            "withdrawal_fee_pct": round(withdrawal_fee, 4),
            "entry_slippage_pct": round(entry_slip, 4),
            "exit_slippage_pct": round(exit_slip, 4),
            "round_trip_cost_pct": round(round_trip_cost_pct, 4),
            "apr_advantage_pct": round(apr_advantage, 4),
            "daily_advantage_pct": round(daily_advantage_pct, 6),
            "breakeven_days": breakeven_days,
            "expected_holding_days": round(holding_days, 4),
            "net_gain_pct": round(net_gain_pct, 4),
            "covers_horizon": covers_horizon,
            "cost_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _cost_score(
        self,
        round_trip_cost_pct: float,
        breakeven_days: Optional[float],
        holding_days: float,
    ) -> float:
        """
        0–100, HIGHER = BETTER. Weighted:
          cost component (≈60, full when round-trip cost is ~0, fades to 0 at 2%)
          + speed component (≈40, full when it breaks even within the horizon,
            else fades with break-even days toward 90).
        """
        cost_comp = 60.0 * _clamp(1.0 - round_trip_cost_pct / 2.0, 0.0, 1.0)
        if breakeven_days is not None and breakeven_days <= holding_days \
                and holding_days > 0:
            speed_comp = 40.0
        else:
            speed_comp = 40.0 * _clamp(
                1.0 - (breakeven_days if breakeven_days is not None else 999.0)
                / 90.0,
                0.0, 1.0,
            )
        return _clamp(cost_comp + speed_comp, 0.0, 100.0)

    def _classify(
        self,
        breakeven_days: Optional[float],
        round_trip_cost_pct: float,
        apr_advantage: float,
    ) -> str:
        if breakeven_days is None:
            return "NEVER_BREAKS_EVEN"
        if breakeven_days <= CHEAP_DAYS:
            return "CHEAP"
        if breakeven_days <= FAIR_DAYS:
            return "FAIR"
        if breakeven_days <= EXPENSIVE_DAYS:
            return "EXPENSIVE"
        return "PROHIBITIVE"

    def _recommend(self, classification: str, covers_horizon: bool) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID"
        if covers_horizon and classification in ("CHEAP", "FAIR"):
            return "ROTATE"
        if classification == "EXPENSIVE":
            return "ROTATE_IF_LONG_HOLD"
        if classification in ("PROHIBITIVE", "NEVER_BREAKS_EVEN"):
            return "STAY"
        # CHEAP / FAIR but horizon does not yet cover break-even.
        return "STAY"

    def _flags(
        self,
        round_trip_cost_pct: float,
        apr_advantage: float,
        breakeven_days: Optional[float],
        covers_horizon: bool,
        net_gain_pct: float,
        holding_days: float,
    ) -> List[str]:
        flags: List[str] = []

        if round_trip_cost_pct == 0.0 and apr_advantage > 0:
            flags.append("FREE_ENTRY_EXIT")

        if covers_horizon:
            flags.append("BREAKS_EVEN_IN_HORIZON")

        if breakeven_days is None and round_trip_cost_pct > 0:
            flags.append("NEVER_BREAKS_EVEN")

        if round_trip_cost_pct >= HIGH_ROUND_TRIP_PCT:
            flags.append("HIGH_ROUND_TRIP_COST")

        if net_gain_pct < 0 and holding_days > 0:
            flags.append("NEGATIVE_NET_AT_HORIZON")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "deposit_fee_pct": 0.0,
            "withdrawal_fee_pct": 0.0,
            "entry_slippage_pct": 0.0,
            "exit_slippage_pct": 0.0,
            "round_trip_cost_pct": 0.0,
            "apr_advantage_pct": 0.0,
            "daily_advantage_pct": 0.0,
            "breakeven_days": None,
            "expected_holding_days": 0.0,
            "net_gain_pct": 0.0,
            "covers_horizon": False,
            "cost_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cheapest_vault": None,
                "most_expensive_vault": None,
                "avg_score": 0.0,
                "rotate_count": 0,
                "position_count": len(results),
            }
        # Higher score = cheaper/faster → highest score is cheapest.
        by_score = sorted(scored, key=lambda r: r["cost_score"])
        avg = _mean([r["cost_score"] for r in scored])
        rotate = sum(
            1 for r in results if r["recommendation"].startswith("ROTATE"))
        return {
            "cheapest_vault": by_score[-1]["token"],
            "most_expensive_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "rotate_count": rotate,
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
                    "cost_score": r["cost_score"],
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
            "vault": "USDC-Vault-Cheap",
            "deposit_fee_pct": 0.0,
            "withdrawal_fee_pct": 0.05,
            "entry_slippage_pct": 0.02,
            "exit_slippage_pct": 0.02,
            "apr_advantage_pct": 5.0,
            "expected_holding_days": 30.0,
        },
        {
            "vault": "ETH-Vault-Expensive",
            "deposit_fee_pct": 0.5,
            "withdrawal_fee_pct": 0.5,
            "entry_slippage_pct": 0.1,
            "exit_slippage_pct": 0.1,
            "apr_advantage_pct": 6.0,
            "expected_holding_days": 14.0,
        },
        {
            "vault": "DAI-Vault-NoEdge",
            "deposit_fee_pct": 0.1,
            "withdrawal_fee_pct": 0.1,
            "entry_slippage_pct": 0.0,
            "exit_slippage_pct": 0.0,
            "apr_advantage_pct": 0.0,
            "expected_holding_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1159 Vault Round Trip Cost Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRoundTripCostAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
