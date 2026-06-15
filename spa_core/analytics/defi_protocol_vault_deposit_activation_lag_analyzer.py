"""
MP-1176: DeFiProtocolVaultDepositActivationLagAnalyzer
======================================================
Advisory/read-only analytics module.

New capital deposited into a vault can sit IDLE — not yet deployed into the
income-earning strategy — for some number of hours/days before it begins
accruing yield (warmup period / deposit queue / epoch boundary). During the
hold this lowers the EFFECTIVE realized APR, because the early days earn
nothing. The shorter the intended hold, the more the one-off activation lag
dilutes the realized return.

Angle: "a vault advertises 10% APR, but a fresh deposit sits idle 3 days before
it is deployed; over a 30-day hold the effective APR is ~9%, but over a 5-day
hold it collapses to ~4%."

HIGHER score = faster deployment / less activation drag.

Distinct from:
  * idle_cash_drag — the STRUCTURAL, permanent reserve a vault keeps unused at
    all times (a standing buffer), not a one-off entry lag.
  * defi_protocol_vault_redemption_cooldown — a lock on the EXIT (withdrawal
    side), not the deployment of fresh deposits on entry.
  * defi_protocol_vault_harvest_cycle_entry_timing_analyzer (MP-1173) — WHERE in
    the harvest cycle you enter (accrued-but-unrealized yield timing).
  THIS module isolates the ONE-OFF deployment lag of NEW capital relative to the
  holder's intended horizon, and how much realized APR it costs.

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
    "data", "vault_deposit_activation_lag_log.json"
)
LOG_CAP = 100

# drag_ratio (= lag_days / hold_days) classification thresholds.
INSTANT_RATIO = 0.02     # ratio at/below this → instant deployment
MINOR_RATIO = 0.10       # ratio at/below this → minor lag
MATERIAL_RATIO = 0.30    # ratio at/below this → material; above → severe

# Absolute-lag scoring reference: a lag of LAG_CEILING_DAYS zeroes the absolute
# component.
LAG_CEILING_DAYS = 7.0

# Activation considered effectively instant at/below this many hours.
INSTANT_HOURS = 1.0

# Horizon flag thresholds (hold_days).
LONG_HORIZON_DAYS = 90.0   # hold at/above this → long horizon, lag amortizes
SHORT_HORIZON_DAYS = 7.0   # hold at/below this → short horizon, lag bites


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


def _safe_div(num: float, den: float, sentinel):
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

class DeFiProtocolVaultDepositActivationLagAnalyzer:
    """
    Measures how much a vault's ONE-OFF deposit activation lag — the idle window
    before fresh capital is deployed into the income strategy — dilutes the
    realized APR over a holder's intended horizon. The lag earns nothing, so the
    effective APR is headline scaled by earning_days / hold_days. A short horizon
    amplifies the dilution; a long horizon amortizes it.

    HIGHER score = faster deployment / less activation drag.

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float (max(0,..)); <=0 → INSUFFICIENT.
        activation_lag_hours : float (default 0; max(0,..)) — idle hours before
                               the fresh deposit is deployed into the strategy.
        intended_hold_days   : float (default 30; max(0,..)); <=0 → INSUFFICIENT
                               — the holder's planned holding horizon in days.
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
        headline = max(0.0, _f(p.get("headline_apr_pct")))

        # Insufficient data fast-path: a non-positive headline gives no basis
        # for an effective-APR computation.
        if headline <= 0:
            return self._insufficient(token)

        lag_hours = max(0.0, _f(p.get("activation_lag_hours")))
        hold_days = max(0.0, _f(p.get("intended_hold_days"), 30.0))

        # A non-positive horizon gives no basis for a dilution computation.
        if hold_days <= 0:
            return self._insufficient(token)

        lag_days = lag_hours / 24.0
        earning_days = max(0.0, hold_days - lag_days)

        # Effective realized APR: only the earning days accrue.
        effective_apr = _safe_div(headline * earning_days, hold_days, 0.0)
        if effective_apr is None or not math.isfinite(effective_apr):
            effective_apr = 0.0
        effective_apr = _clamp(effective_apr, 0.0, headline)

        yield_drag = max(0.0, headline - effective_apr)
        drag_ratio = _clamp(_safe_div(lag_days, hold_days, 1.0), 0.0, 1.0)

        lag_exceeds_hold = bool(lag_days >= hold_days)
        is_instant = bool(lag_hours <= INSTANT_HOURS)
        long_horizon = bool(hold_days >= LONG_HORIZON_DAYS)
        short_horizon = bool(hold_days <= SHORT_HORIZON_DAYS)

        score = self._score(drag_ratio, lag_days)
        classification = self._classify(drag_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(
            classification, lag_exceeds_hold)
        flags = self._flags(
            classification,
            lag_exceeds_hold,
            is_instant,
            long_horizon,
            short_horizon,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "activation_lag_hours": round(lag_hours, 4),
            "lag_days": round(lag_days, 4),
            "intended_hold_days": round(hold_days, 4),
            "earning_days": round(earning_days, 4),
            "effective_apr_pct": round(effective_apr, 4),
            "yield_drag_pct": round(yield_drag, 4),
            "drag_ratio": round(drag_ratio, 4),
            "lag_exceeds_hold": lag_exceeds_hold,
            "is_instant": is_instant,
            "long_horizon": long_horizon,
            "short_horizon": short_horizon,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        drag_ratio: float,
        lag_days: float,
    ) -> float:
        """
        0–100, HIGHER = faster deployment. Components:
          efficiency (70) — (1 - drag_ratio) × 70; the share of the horizon that
            actually earns.
          absolute_lag (30) — (1 - clamp(lag_days / LAG_CEILING_DAYS)) × 30; an
            absolute penalty so a long lag is bad even with a very long horizon.
        A lag of 0 → 100; penalties scale with the lag.
        """
        ratio = _clamp(drag_ratio, 0.0, 1.0)
        efficiency_comp = 70.0 * (1.0 - ratio)
        absolute_lag_comp = 30.0 * (
            1.0 - _clamp(lag_days / LAG_CEILING_DAYS, 0.0, 1.0))
        total = efficiency_comp + absolute_lag_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, drag_ratio: float) -> str:
        if drag_ratio <= INSTANT_RATIO:
            return "INSTANT_DEPLOYMENT"
        if drag_ratio <= MINOR_RATIO:
            return "MINOR_LAG"
        if drag_ratio <= MATERIAL_RATIO:
            return "MATERIAL_LAG"
        return "SEVERE_LAG"

    def _recommend(
        self,
        classification: str,
        lag_exceeds_hold: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if lag_exceeds_hold:
            return "AVOID_FOR_SHORT_HOLD"
        if classification == "SEVERE_LAG":
            return "LENGTHEN_HORIZON_OR_VERIFY"
        if classification == "MATERIAL_LAG":
            return "ACCEPTABLE_FOR_HORIZON"
        # INSTANT_DEPLOYMENT or MINOR_LAG
        return "DEPLOY_NOW"

    def _flags(
        self,
        classification: str,
        lag_exceeds_hold: bool,
        is_instant: bool,
        long_horizon: bool,
        short_horizon: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "INSTANT_DEPLOYMENT":
            flags.append("INSTANT_DEPLOYMENT")
        if classification == "MINOR_LAG":
            flags.append("MINOR_LAG")
        if classification == "MATERIAL_LAG":
            flags.append("MATERIAL_LAG")
        if classification == "SEVERE_LAG":
            flags.append("SEVERE_LAG")
        if lag_exceeds_hold:
            flags.append("LAG_EXCEEDS_HOLD")
        if is_instant:
            flags.append("INSTANT_ACTIVATION")
        if long_horizon:
            flags.append("LONG_HORIZON_OK")
        if short_horizon:
            flags.append("SHORT_HORIZON")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "activation_lag_hours": 0.0,
            "lag_days": 0.0,
            "intended_hold_days": 0.0,
            "earning_days": None,
            "effective_apr_pct": None,
            "yield_drag_pct": None,
            "drag_ratio": None,
            "lag_exceeds_hold": False,
            "is_instant": False,
            "long_horizon": False,
            "short_horizon": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "fastest_vault": None,
                "slowest_vault": None,
                "avg_score": 0.0,
                "severe_lag_count": 0,
                "position_count": len(results),
            }
        # Higher score = faster deployment → highest score is fastest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_LAG")
        return {
            "fastest_vault": by_score[-1]["token"],
            "slowest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_lag_count": severe,
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
                    "score": r["score"],
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
            "vault": "USDC-Vault-Instant",
            "headline_apr_pct": 10.0,
            "activation_lag_hours": 0.0,
            "intended_hold_days": 30.0,
        },
        {
            "vault": "ETH-Vault-MinorLag",
            "headline_apr_pct": 12.0,
            "activation_lag_hours": 24.0,
            "intended_hold_days": 30.0,
        },
        {
            "vault": "ARB-Vault-MaterialLag",
            "headline_apr_pct": 16.0,
            "activation_lag_hours": 72.0,
            "intended_hold_days": 14.0,
        },
        {
            "vault": "CRV-Vault-SevereLag-ShortHold",
            "headline_apr_pct": 14.0,
            "activation_lag_hours": 120.0,
            "intended_hold_days": 3.0,
        },
        {
            "vault": "CVX-Vault-LongHorizon",
            "headline_apr_pct": 18.0,
            "activation_lag_hours": 48.0,
            "intended_hold_days": 180.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "activation_lag_hours": 0.0,
            "intended_hold_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1176 Vault Deposit Activation Lag Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDepositActivationLagAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
