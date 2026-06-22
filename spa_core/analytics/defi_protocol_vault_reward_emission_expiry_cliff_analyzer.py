"""
MP-1186: DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer
===========================================================
Advisory/read-only analytics module.

Part of a vault's headline APR is frequently funded by a token-emission /
incentive program that carries a SCHEDULED END DATE — an emission "cliff". In
contrast to a smooth gradual decay, on the cliff date the reward-APR drops to
~0 and the headline collapses down to the underlying base-APR. This measures
how DURABLE the headline quote is over YOUR intended holding horizon: how much
of the headline is funded by the cliff-bound emission, how many days remain
until the cliff, the post-cliff run-rate (base_apr), and the FORWARD-EFFECTIVE
APR you would actually realise across the horizon if you hold through the cliff.

Angle: "headline 40% APR, but 28% of it is emission ending in 10 days and your
horizon is 90 days → blended forward APR is far below 40%; the headline is not
durable for your horizon."

HIGHER score = the headline is durable over your horizon (cliff is far away
and/or the emission share is small).

Distinct from:
  * defi_protocol_vault_trailing_window_boost_backdating_analyzer — that module
    is about a PAST boost inflating a BACKWARD-looking trailing average; THIS
    module is about a FUTURE hard cliff that has not happened yet.
  * defi_protocol_gauge_emission_decay_forecaster /
    protocol_incentive_decay_monitor — those model a SMOOTH gradual decay of
    incentives; THIS module models a DISCRETE drop on a single scheduled date.

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
    "data", "vault_reward_emission_expiry_cliff_log.json"
)
LOG_CAP = 100

# Default holding horizon (days) when none / non-positive supplied.
DEFAULT_HOLDING_HORIZON_DAYS = 30.0

# Classification thresholds on the durable_fraction (forward_apr / headline).
# durable_fraction at/above this → DURABLE.
DURABLE_FRACTION = 0.90
# at/above this → MOSTLY_DURABLE.
MOSTLY_DURABLE_FRACTION = 0.75
# at/above this → SOFT_CLIFF.
SOFT_CLIFF_FRACTION = 0.55
# at/above this → HARD_CLIFF; below → CLIFF_COLLAPSE.
HARD_CLIFF_FRACTION = 0.35

# Flag: emission funds a large share of headline.
HIGH_EMISSION_SHARE = 0.5
# Flag: cliff is imminent within this many days.
IMMINENT_CLIFF_DAYS = 7.0
# Flag: post-cliff base run-rate is negligible (most of yield evaporates).
THIN_BASE_FRACTION = 0.25

# Cap used to keep ratios finite.
RATIO_CAP = 1.0


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

class DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer:
    """
    Measures how durable a vault's headline APR is across the holder's intended
    horizon when part of that headline is funded by an emission program with a
    hard scheduled end (cliff). base_apr is the post-cliff run-rate; the
    emission-funded share is headline - base. days_to_cliff is the fraction of
    the holding horizon for which the emission is still live; after the cliff
    only the base remains. The forward-effective APR is the horizon-weighted
    blend of the (pre-cliff) headline and the (post-cliff) base. The
    durable_fraction = forward_apr / headline; HIGHER means the headline holds
    up across your horizon. Advisory only — it does not move funds.

    Per-position input dict fields:
        vault / token          : str
        headline_apr_pct       : float; <=0 / non-finite → INSUFFICIENT_DATA.
        base_apr_pct           : float (clamp [0, headline]) — the post-cliff
                                 run-rate once the emission ends.
        days_to_cliff          : float (max(0,..)) — days until the emission
                                 ends; 0 → cliff already reached (post-cliff
                                 immediately).
        holding_horizon_days   : float (max(0,..); default 30.0) — your intended
                                 holding period; <=0 → default.
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

        # Insufficient data fast-path: a non-positive / non-finite headline gives
        # nothing to judge durability against.
        if headline <= 0 or not math.isfinite(headline):
            return self._insufficient(token)

        base = _clamp(_f(p.get("base_apr_pct")), 0.0, headline)
        if not math.isfinite(base):
            base = 0.0

        days_to_cliff = max(0.0, _f(p.get("days_to_cliff")))
        if not math.isfinite(days_to_cliff):
            days_to_cliff = 0.0

        horizon = max(0.0, _f(p.get("holding_horizon_days"),
                              DEFAULT_HOLDING_HORIZON_DAYS))
        if horizon <= 0 or not math.isfinite(horizon):
            horizon = DEFAULT_HOLDING_HORIZON_DAYS

        # emission-funded share of headline.
        emission_apr = max(0.0, headline - base)
        emission_share = _clamp(
            _safe_div(emission_apr, headline, 0.0), 0.0, 1.0)

        # Fraction of the horizon during which the emission is still live.
        pre_cliff_days = min(days_to_cliff, horizon)
        live_fraction = _clamp(
            _safe_div(pre_cliff_days, horizon, 0.0), 0.0, 1.0)
        if not math.isfinite(live_fraction):
            live_fraction = 0.0

        cliff_reached = bool(days_to_cliff <= 0)
        cliff_within_horizon = bool(days_to_cliff < horizon)

        # Forward-effective APR over the horizon: headline while emission live,
        # base afterwards.
        forward_apr = headline * live_fraction + base * (1.0 - live_fraction)
        if not math.isfinite(forward_apr):
            forward_apr = base
        forward_apr = _clamp(forward_apr, 0.0, headline)

        durable_fraction = _clamp(
            _safe_div(forward_apr, headline, 0.0), 0.0, 1.0)
        if not math.isfinite(durable_fraction):
            durable_fraction = 0.0

        base_fraction = _clamp(
            _safe_div(base, headline, 0.0), 0.0, 1.0)

        # headline yield lost over the horizon relative to staying at headline.
        forward_drop_pct = _clamp(headline - forward_apr, 0.0, headline)

        high_emission_share = bool(emission_share >= HIGH_EMISSION_SHARE)
        imminent_cliff = bool(
            cliff_within_horizon and days_to_cliff <= IMMINENT_CLIFF_DAYS)
        thin_base = bool(base_fraction <= THIN_BASE_FRACTION)

        score = self._score(durable_fraction)
        classification = self._classify(durable_fraction)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, cliff_reached, cliff_within_horizon,
            high_emission_share, imminent_cliff, thin_base)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base, 4),
            "emission_apr_pct": round(emission_apr, 4),
            "emission_share": round(emission_share, 4),
            "days_to_cliff": round(days_to_cliff, 4),
            "holding_horizon_days": round(horizon, 4),
            "live_fraction": round(live_fraction, 4),
            "cliff_reached": cliff_reached,
            "cliff_within_horizon": cliff_within_horizon,
            "forward_apr_pct": round(forward_apr, 4),
            "forward_drop_pct": round(forward_drop_pct, 4),
            "durable_fraction": round(durable_fraction, 4),
            "base_fraction": round(base_fraction, 4),
            "high_emission_share": high_emission_share,
            "imminent_cliff": imminent_cliff,
            "thin_base": thin_base,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, durable_fraction: float) -> float:
        """
        0–100, HIGHER = more durable headline over the horizon.
          durability (100) — 100 × durable_fraction, where durable_fraction is
            forward_apr / headline. A headline that is fully durable across the
            horizon scores 100; a headline that collapses entirely to a zero
            base immediately scores 0.
        """
        frac = _clamp(durable_fraction, 0.0, 1.0)
        total = 100.0 * frac
        return _clamp(total, 0.0, 100.0)

    def _classify(self, durable_fraction: float) -> str:
        frac = _clamp(durable_fraction, 0.0, 1.0)
        if frac >= DURABLE_FRACTION:
            return "DURABLE"
        if frac >= MOSTLY_DURABLE_FRACTION:
            return "MOSTLY_DURABLE"
        if frac >= SOFT_CLIFF_FRACTION:
            return "SOFT_CLIFF"
        if frac >= HARD_CLIFF_FRACTION:
            return "HARD_CLIFF"
        return "CLIFF_COLLAPSE"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "DURABLE":
            return "NO_ACTION"
        if classification == "MOSTLY_DURABLE":
            return "MONITOR"
        if classification == "SOFT_CLIFF":
            return "DISCOUNT_HEADLINE"
        if classification == "HARD_CLIFF":
            return "PLAN_EXIT_AT_CLIFF"
        # CLIFF_COLLAPSE
        return "USE_BASE_APR"

    def _flags(
        self,
        classification: str,
        cliff_reached: bool,
        cliff_within_horizon: bool,
        high_emission_share: bool,
        imminent_cliff: bool,
        thin_base: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "DURABLE":
            flags.append("DURABLE")
        if classification == "MOSTLY_DURABLE":
            flags.append("MOSTLY_DURABLE")
        if classification == "SOFT_CLIFF":
            flags.append("SOFT_CLIFF")
        if classification == "HARD_CLIFF":
            flags.append("HARD_CLIFF")
        if classification == "CLIFF_COLLAPSE":
            flags.append("CLIFF_COLLAPSE")
        if cliff_reached:
            flags.append("CLIFF_REACHED")
        elif cliff_within_horizon:
            flags.append("CLIFF_WITHIN_HORIZON")
        if high_emission_share:
            flags.append("HIGH_EMISSION_SHARE")
        if imminent_cliff:
            flags.append("IMMINENT_CLIFF")
        if thin_base:
            flags.append("THIN_BASE_RUN_RATE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "emission_apr_pct": 0.0,
            "emission_share": None,
            "days_to_cliff": 0.0,
            "holding_horizon_days": round(DEFAULT_HOLDING_HORIZON_DAYS, 4),
            "live_fraction": None,
            "cliff_reached": False,
            "cliff_within_horizon": False,
            "forward_apr_pct": None,
            "forward_drop_pct": None,
            "durable_fraction": None,
            "base_fraction": None,
            "high_emission_share": False,
            "imminent_cliff": False,
            "thin_base": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_durable_vault": None,
                "least_durable_vault": None,
                "avg_score": 0.0,
                "cliff_collapse_count": 0,
                "avg_forward_drop_pct": 0.0,
                "position_count": len(results),
            }
        # Higher score = more durable → highest score is the most durable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        collapse = sum(
            1 for r in results
            if r["classification"] == "CLIFF_COLLAPSE")
        avg_drop = _mean([
            r["forward_drop_pct"] for r in scored
            if isinstance(r["forward_drop_pct"], (int, float))])
        return {
            "most_durable_vault": by_score[-1]["token"],
            "least_durable_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "cliff_collapse_count": collapse,
            "avg_forward_drop_pct": round(avg_drop, 4),
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
            "vault": "USDC-Vault-Durable",
            "headline_apr_pct": 12.0,
            "base_apr_pct": 11.5,
            "days_to_cliff": 365.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "ETH-Vault-MostlyDurable",
            "headline_apr_pct": 20.0,
            "base_apr_pct": 12.0,
            "days_to_cliff": 17.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "ARB-Vault-SoftCliff",
            "headline_apr_pct": 30.0,
            "base_apr_pct": 10.0,
            "days_to_cliff": 12.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "OP-Vault-HardCliff",
            "headline_apr_pct": 40.0,
            "base_apr_pct": 8.0,
            "days_to_cliff": 20.0,
            "holding_horizon_days": 60.0,
        },
        {
            "vault": "CRV-Vault-Collapse",
            "headline_apr_pct": 50.0,
            "base_apr_pct": 2.0,
            "days_to_cliff": 0.0,
            "holding_horizon_days": 90.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "days_to_cliff": 30.0,
            "holding_horizon_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1186 Vault Reward Emission Expiry Cliff Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
