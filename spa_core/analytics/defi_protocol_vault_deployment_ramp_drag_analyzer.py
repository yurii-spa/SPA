"""
MP-1195: DeFiProtocolVaultDeploymentRampDragAnalyzer
====================================================
Advisory/read-only analytics module.

A vault's HEADLINE APR assumes deposited capital is productive from t0. In
practice many vaults impose a DEPLOYMENT RAMP: fresh capital sits idle (queued /
warming up / waiting to be allocated into strategies) for a number of days before
it actually starts earning. During that non-earning ramp the principal earns 0%.
A depositor's REALIZED annualised APR over a target holding horizon is therefore
the headline scaled by the PRODUCTIVE fraction of the horizon:

    realized_apr = headline × max(0, horizon - ramp) / horizon

The non-earning ramp is a pure TIME drag on principal (no explicit fee) and bites
hardest on SHORT horizons, where a fixed ramp consumes a large share of the holding
window. This module measures how diluted the realized APR is versus the headline —
a headline-honesty/quality signal for capital with a finite holding horizon.

Angle: "headline 12% assumes day-one productivity, but new deposits sit idle for a
10-day deployment ramp; over a 30-day horizon only 20 of 30 days earn → realized
≈ 8%; discount the headline for short holds."

HIGHER score = realized APR is close to the headline (ramp negligible relative to
the horizon) → headline honest for the depositor's holding window.

Distinct from:
  * defi_protocol_vault_entry_fee_amortization_analyzer /
    defi_protocol_vault_gas_breakeven_analyzer /
    defi_protocol_vault_round_trip_cost_analyzer — amortise a FIXED one-off COST
    over deposit size / horizon; here there is no cost, only a non-earning TIME
    LAG on otherwise-productive principal.
  * defi_protocol_vault_harvest_cycle_entry_timing_analyzer /
    protocol_defi_epoch_reward_timing_analyzer — REWARD-capture timing relative to
    a harvest/epoch boundary (missing already-accrued rewards); here the PRINCIPAL
    itself is not yet deployed/earning during the ramp.
  * defi_protocol_vault_pending_harvest_premium_analyzer — overpaying for
    already-accrued unharvested rewards (opposite sign).
  * defi_protocol_vault_withdrawal_fee_decay_analyzer /
    defi_lockup_opportunity_cost_analyzer — EXIT-side frictions; here the drag is
    on the ENTRY-side deployment warm-up.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_deployment_ramp_drag_log.json"
)
LOG_CAP = 100

# Default holding horizon (days) used when not supplied.
DEFAULT_HORIZON_DAYS = 365.0

# Ramp-fraction tolerance: ramp at/below this share of the horizon is negligible.
NEGLIGIBLE_RAMP_FRACTION = 0.01
# Classification thresholds on ramp_fraction (ramp_days / horizon_days).
MINOR_RAMP_FRACTION = 0.05      # at/below → minor
MODERATE_RAMP_FRACTION = 0.15   # at/below → moderate; above → severe

# A horizon at/below this many days is flagged as short (ramp drag amplified).
SHORT_HORIZON_DAYS = 30.0
# A ramp at/above this many days is flagged as a long ramp.
LONG_RAMP_DAYS = 7.0


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

class DeFiProtocolVaultDeploymentRampDragAnalyzer:
    """
    Measures how diluted a depositor's REALIZED annualised APR is versus the
    vault's HEADLINE APR because fresh capital sits idle (non-earning) during a
    DEPLOYMENT RAMP before becoming productive. Over a finite holding horizon the
    realized APR is the headline scaled by the productive fraction of the horizon:
    realized = headline × max(0, horizon - ramp) / horizon. The shorter the
    horizon relative to the ramp, the larger the drag.

    HIGHER score = realized APR is close to the headline (ramp negligible).

    Per-position input dict fields:
        vault / token            : str
        headline_apr_pct         : float (default 0) — advertised APR
        ramp_days                : float (default 0; max(0, ..)) — non-earning
                                   deployment/warm-up lag in days
        holding_horizon_days     : float (default DEFAULT_HORIZON_DAYS;
                                   max(0, ..)) — depositor's target holding window
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
        headline = _f(p.get("headline_apr_pct"))
        ramp_raw = _f(p.get("ramp_days"))
        horizon_raw = _f(p.get("holding_horizon_days"), DEFAULT_HORIZON_DAYS)

        # Insufficient data: non-finite/non-positive headline, non-finite ramp,
        # or non-finite/non-positive horizon (cannot scale). Validate the RAW
        # inputs before clamping so a NaN/inf ramp is not silently coerced to 0.
        if (not math.isfinite(headline) or headline <= 0
                or not math.isfinite(ramp_raw)
                or not math.isfinite(horizon_raw) or horizon_raw <= 0):
            return self._insufficient(token)

        ramp_days = max(0.0, ramp_raw)
        horizon = max(0.0, horizon_raw)

        productive_days = max(0.0, horizon - ramp_days)
        productive_fraction = _clamp(
            _safe_div(productive_days, horizon, 0.0), 0.0, 1.0)
        ramp_fraction = _clamp(
            _safe_div(ramp_days, horizon, 1.0), 0.0, 1.0)

        realized_apr = headline * productive_fraction
        drag_pct = headline - realized_apr

        realization_ratio = _safe_div(realized_apr, headline, None)
        if realization_ratio is not None and not math.isfinite(
                realization_ratio):
            realization_ratio = None

        full_horizon_lost = bool(ramp_days >= horizon)
        short_horizon = bool(horizon <= SHORT_HORIZON_DAYS)
        long_ramp = bool(ramp_days >= LONG_RAMP_DAYS)

        score = self._score(productive_fraction)
        classification = self._classify(ramp_fraction)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, full_horizon_lost, short_horizon, long_ramp)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "realized_apr_pct": round(realized_apr, 4),
            "drag_pct": round(drag_pct, 4),
            "realization_ratio": (
                None if realization_ratio is None
                else round(realization_ratio, 4)),
            "productive_fraction": round(productive_fraction, 4),
            "ramp_fraction": round(ramp_fraction, 4),
            "ramp_days": round(ramp_days, 4),
            "holding_horizon_days": round(horizon, 4),
            "productive_days": round(productive_days, 4),
            "full_horizon_lost": full_horizon_lost,
            "short_horizon": short_horizon,
            "long_ramp": long_ramp,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, productive_fraction: float) -> float:
        """
        0–100, HIGHER = realized APR closer to the headline. The realized APR is
        the headline scaled by the productive fraction of the horizon, so the
        honesty of the headline for this depositor is exactly that fraction.
        productive_fraction 1.0 (no ramp) → 100; 0.0 (ramp >= horizon) → 0.
        """
        return _clamp(100.0 * productive_fraction, 0.0, 100.0)

    def _classify(self, ramp_fraction: float) -> str:
        if ramp_fraction <= NEGLIGIBLE_RAMP_FRACTION:
            return "NEGLIGIBLE_RAMP"
        if ramp_fraction <= MINOR_RAMP_FRACTION:
            return "MINOR_RAMP"
        if ramp_fraction <= MODERATE_RAMP_FRACTION:
            return "MODERATE_RAMP"
        return "SEVERE_RAMP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "NEGLIGIBLE_RAMP":
            return "TRUST_HEADLINE"
        if classification == "MINOR_RAMP":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_RAMP":
            return "DISCOUNT_HEADLINE"
        # SEVERE_RAMP
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        full_horizon_lost: bool,
        short_horizon: bool,
        long_ramp: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NEGLIGIBLE_RAMP":
            flags.append("NEGLIGIBLE_RAMP")
        if classification == "MINOR_RAMP":
            flags.append("MINOR_RAMP")
        if classification == "MODERATE_RAMP":
            flags.append("MODERATE_RAMP")
        if classification == "SEVERE_RAMP":
            flags.append("SEVERE_RAMP")
        if full_horizon_lost:
            flags.append("FULL_HORIZON_LOST")
        if short_horizon:
            flags.append("SHORT_HORIZON")
        if long_ramp:
            flags.append("LONG_RAMP")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "realized_apr_pct": None,
            "drag_pct": 0.0,
            "realization_ratio": None,
            "productive_fraction": None,
            "ramp_fraction": None,
            "ramp_days": None,
            "holding_horizon_days": None,
            "productive_days": None,
            "full_horizon_lost": False,
            "short_horizon": False,
            "long_ramp": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_honest_vault": None,
                "least_honest_vault": None,
                "avg_score": 0.0,
                "severe_ramp_count": 0,
                "position_count": len(results),
            }
        # Higher score = headline more honest → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results if r["classification"] == "SEVERE_RAMP")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_ramp_count": severe,
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
            # NEGLIGIBLE_RAMP: no deployment lag over a 1y horizon.
            "vault": "USDC-Vault-NoRamp",
            "headline_apr_pct": 12.0,
            "ramp_days": 0.0,
            "holding_horizon_days": 365.0,
        },
        {
            # SEVERE_RAMP: 10-day ramp consumes a third of a 30-day horizon.
            "vault": "GMX-Vault-ShortHoldRamp",
            "headline_apr_pct": 12.0,
            "ramp_days": 10.0,
            "holding_horizon_days": 30.0,
        },
        {
            # MINOR_RAMP: 7-day ramp over a 1y horizon.
            "vault": "DAI-Vault-MinorRamp",
            "headline_apr_pct": 8.0,
            "ramp_days": 7.0,
            "holding_horizon_days": 365.0,
        },
        {
            # INSUFFICIENT_DATA: non-positive headline.
            "vault": "ETH-Vault-NoData",
            "headline_apr_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1195 Vault Deployment Ramp Drag Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDeploymentRampDragAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
