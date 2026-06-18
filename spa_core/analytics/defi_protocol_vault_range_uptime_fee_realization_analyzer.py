"""
MP-1198: DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer
==========================================================
Advisory/read-only analytics module.

Concentrated-liquidity (CLMM, Uniswap-v3-style) LP vaults advertise a fee APR
computed AS IF the position were IN-RANGE and collecting trading fees 100% of the
time. But a concentrated position only earns fees while the market price sits
INSIDE its chosen tick band. Whenever the price wanders OUTSIDE that band the
position is INACTIVE: it earns ZERO trading fees and sits entirely in a single
asset until price re-enters (or the vault rebalances). Over a finite holding
horizon the realised fee APR is therefore the headline scaled by the fraction of
time the position was actually in-range:

    realised_fee_apr = headline_fee_apr * time_in_range_fraction

Narrower bands quote a HIGHER in-range fee rate (more liquidity per tick) but
spend MORE time out of range (lower uptime), so the boosted headline overstates
the time-averaged realised fee yield. This module audits HEADLINE HONESTY by
measuring observed in-range uptime from a sequence of range-status samples and
reporting the fee-uptime drag.

Angle: "a CLMM vault advertises a 60% fee APR (the IN-RANGE rate), but over the
trailing window the price sat outside the band ~35% of the time (out-of-range
intervals earn ZERO fees) → the realised fee APR a holder actually captured is
≈ 60% * 0.65 ≈ 39%; the ~21pp gap is pure fee-uptime drag, and a long
out-of-range streak signals the band is mis-placed / too narrow."

HIGHER score = high in-range uptime (position earns fees almost all the time,
realised ≈ headline) → the fee headline is realisable. LOWER score = low uptime
(position frequently out of range, earning nothing) → the headline overstates the
fee yield a holder captures.

Distinct from:
  * defi_protocol_vault_deployment_ramp_drag_analyzer — a ONE-TIME entry warm-up
    (capital idle for N days, then PERMANENTLY productive). HERE the inactivity is
    RECURRING and price/band-driven: the position repeatedly enters and exits range
    across the horizon, so uptime is a standing property of the band, not a transient.
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — dispersion of a
    (generally positive) earned yield → geometric < arithmetic. HERE out-of-range
    periods earn EXACTLY ZERO fees (a binary availability), not a second-moment
    penalty on positive returns.
  * concentrated_liquidity / protocol_defi_concentrated_liquidity_range_optimizer —
    PRESCRIPTIVE: choose the optimal tick band. HERE we are descriptive / honesty:
    realised fee APR = headline * OBSERVED in-range uptime, independent of which
    band would be optimal.
  * defi_amm_impermanent_loss_* — measure DIVERGENCE (impermanent) LOSS on the
    position's VALUE from price movement (a principal/value effect). HERE we measure
    the FEE-INCOME shortfall from inactive liquidity (income side) — orthogonal to IL
    and additive to it.
  * defi_protocol_vault_utilization_peak_headline_revert_analyzer — mean-reversion of
    an always-positive lending UTILIZATION (borrow APR level). HERE the signal is a
    BINARY in/out-of-range availability for LP fee accrual.

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
    "data", "vault_range_uptime_fee_realization_log.json"
)
LOG_CAP = 100

# Minimum range-status samples required to judge in-range uptime.
MIN_SAMPLES = 2

# Classification thresholds on the out-of-range fraction (1 - time_in_range).
FULL_UPTIME_OOR = 0.02      # at/below → full uptime
MINOR_DRIFT_OOR = 0.10      # at/below → minor drift
MODERATE_DRIFT_OOR = 0.30   # at/below → moderate drift; above → severe drift

# Uptime at/below this is flagged as a narrow-band / low-uptime position.
LOW_UPTIME = 0.50
# Out-of-range streak at/above this fraction of samples → persistently out of range.
PERSISTENT_STREAK_FRAC = 0.50
# Range-flip (in↔out transition) rate at/above this is flagged as rebalance churn.
HIGH_CHURN_RATIO = 0.40


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


def _coerce_in_range(sample) -> Optional[bool]:
    """
    Coerce a single range-status sample to True (in-range) / False (out-of-range),
    or None if it is not interpretable (skipped). Accepts:
      * bool                       — as-is
      * int/float                  — finite; >0 → in-range, <=0 → out-of-range
      * str                        — 'in'/'in_range'/'true'/'1'/'active' → in-range;
                                     'out'/'out_of_range'/'false'/'0'/'inactive' → out
    """
    if isinstance(sample, bool):
        return sample
    if isinstance(sample, (int, float)):
        try:
            fv = float(sample)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(fv):
            return None
        return fv > 0.0
    if isinstance(sample, str):
        s = sample.strip().lower()
        if s in ("in", "in_range", "inrange", "true", "1", "active", "yes"):
            return True
        if s in ("out", "out_of_range", "outofrange", "false", "0",
                 "inactive", "no"):
            return False
        return None
    return None


def _longest_false_streak(flags: List[bool]) -> int:
    """Longest run of consecutive out-of-range (False) samples."""
    best = 0
    cur = 0
    for fl in flags:
        if not fl:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _range_flips(flags: List[bool]) -> int:
    """Number of in↔out transitions across adjacent samples."""
    flips = 0
    for a, b in zip(flags, flags[1:]):
        if a != b:
            flips += 1
    return flips


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

class DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer:
    """
    Quantifies the FEE-UPTIME DRAG between a concentrated-liquidity vault's
    IN-RANGE fee APR headline and the realised fee APR a holder actually captures,
    which equals the headline scaled by the fraction of time the position was
    in-range. Out-of-range intervals earn ZERO trading fees, so a band that the
    price frequently exits realises materially less than its advertised fee APR.

    HIGHER score = high in-range uptime (realised ≈ headline) → the fee headline is
    realisable. LOWER score = low uptime (position often inactive) → the headline
    overstates the captured fee yield.

    Per-position input dict fields:
        vault / token        : str
        headline_fee_apr_pct : float — advertised IN-RANGE fee APR; must be finite
                               and > 0
        range_status_samples : list — per-interval range status, newest last. Each
                               element may be bool, 0/1, or a string
                               ('in'/'out'/'active'/'inactive'/...). Non-interpretable
                               elements are skipped.
        time_in_range_fraction : float — OPTIONAL direct override of uptime in [0,1];
                               used only when range_status_samples is absent/empty.
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
        headline = _f(p.get("headline_fee_apr_pct"))
        samples_raw = p.get("range_status_samples") or []

        # Collect interpretable in-range flags (skip non-interpretable elements).
        flags: List[bool] = []
        for s in samples_raw:
            cv = _coerce_in_range(s)
            if cv is not None:
                flags.append(cv)

        n = len(flags)

        # Determine uptime: prefer observed samples; else a direct override.
        used_samples = n >= MIN_SAMPLES
        if used_samples:
            time_in_range_fraction = _mean([1.0 if fl else 0.0 for fl in flags])
            longest_oor_streak = _longest_false_streak(flags)
            range_flips = _range_flips(flags)
            currently_out_of_range = not flags[-1]
        else:
            override = p.get("time_in_range_fraction")
            if override is None:
                return self._insufficient(token)
            tif = _f(override, default=float("nan"))
            if not math.isfinite(tif):
                return self._insufficient(token)
            time_in_range_fraction = _clamp(tif, 0.0, 1.0)
            longest_oor_streak = 0
            range_flips = 0
            currently_out_of_range = time_in_range_fraction < 0.5

        # Headline must be finite and positive to be meaningful.
        if not math.isfinite(headline) or headline <= 0:
            return self._insufficient(token)

        out_of_range_fraction = _clamp(1.0 - time_in_range_fraction, 0.0, 1.0)
        realized_fee_apr_pct = headline * time_in_range_fraction
        fee_uptime_drag_pct = headline - realized_fee_apr_pct
        realization_ratio = time_in_range_fraction  # = realised / headline

        # Churn ratio: flips per adjacent-pair (only meaningful with samples).
        if used_samples and n >= 2:
            churn_ratio = range_flips / (n - 1)
        else:
            churn_ratio = 0.0

        persistent_out_of_range = bool(
            used_samples and n >= 1
            and longest_oor_streak >= math.ceil(PERSISTENT_STREAK_FRAC * n))
        low_uptime = bool(time_in_range_fraction <= LOW_UPTIME)
        frequent_rebalance_churn = bool(
            used_samples and churn_ratio >= HIGH_CHURN_RATIO)

        score = self._score(time_in_range_fraction, churn_ratio, used_samples)
        classification = self._classify(out_of_range_fraction)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification, currently_out_of_range, persistent_out_of_range,
            low_uptime, frequent_rebalance_churn, used_samples)

        return {
            "token": token,
            "headline_fee_apr_pct": round(headline, 4),
            "realized_fee_apr_pct": round(realized_fee_apr_pct, 4),
            "fee_uptime_drag_pct": round(fee_uptime_drag_pct, 4),
            "time_in_range_fraction": round(time_in_range_fraction, 4),
            "out_of_range_fraction": round(out_of_range_fraction, 4),
            "realization_ratio": round(realization_ratio, 4),
            "longest_out_of_range_streak": longest_oor_streak,
            "range_flips": range_flips,
            "churn_ratio": round(churn_ratio, 4),
            "sample_count": n,
            "uptime_from_samples": used_samples,
            "currently_out_of_range": currently_out_of_range,
            "persistent_out_of_range": persistent_out_of_range,
            "low_uptime": low_uptime,
            "frequent_rebalance_churn": frequent_rebalance_churn,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        time_in_range_fraction: float,
        churn_ratio: float,
        used_samples: bool,
    ) -> float:
        """
        0–100, HIGHER = more in-range uptime (realised fee APR closer to headline)
        and a more stable (less churning) position. Two components:
          * uptime    = time_in_range_fraction (the realised fee APR as a share of
            the headline; out-of-range earns nothing → 0),
          * stability = clamp(1 − churn_ratio, 0, 1) (few in↔out flips → ~1; a band
            the price constantly crosses → 0).
        Weighted 80/20 toward uptime (the realised shortfall is the dominant signal;
        churn is a corroborating instability view). When uptime comes from a direct
        override (no samples) churn is unknown → stability contributes its neutral
        full weight (churn_ratio = 0).
        """
        uptime = _clamp(time_in_range_fraction, 0.0, 1.0)
        stability = _clamp(1.0 - churn_ratio, 0.0, 1.0)
        return _clamp(80.0 * uptime + 20.0 * stability, 0.0, 100.0)

    def _classify(self, out_of_range_fraction: float) -> str:
        if out_of_range_fraction <= FULL_UPTIME_OOR:
            return "FULL_UPTIME"
        if out_of_range_fraction <= MINOR_DRIFT_OOR:
            return "MINOR_DRIFT"
        if out_of_range_fraction <= MODERATE_DRIFT_OOR:
            return "MODERATE_DRIFT"
        return "SEVERE_DRIFT"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "FULL_UPTIME":
            return "TRUST_HEADLINE"
        if classification == "MINOR_DRIFT":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_DRIFT":
            return "DISCOUNT_HEADLINE"
        # SEVERE_DRIFT
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        currently_out_of_range: bool,
        persistent_out_of_range: bool,
        low_uptime: bool,
        frequent_rebalance_churn: bool,
        used_samples: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "FULL_UPTIME":
            flags.append("FULL_UPTIME")
        if classification == "MINOR_DRIFT":
            flags.append("MINOR_DRIFT")
        if classification == "MODERATE_DRIFT":
            flags.append("MODERATE_DRIFT")
        if classification == "SEVERE_DRIFT":
            flags.append("SEVERE_DRIFT")
        if currently_out_of_range:
            flags.append("CURRENTLY_OUT_OF_RANGE")
        if persistent_out_of_range:
            flags.append("PERSISTENTLY_OUT_OF_RANGE")
        if low_uptime:
            flags.append("NARROW_BAND_LOW_UPTIME")
        if frequent_rebalance_churn:
            flags.append("FREQUENT_REBALANCE_CHURN")
        if not used_samples:
            flags.append("UPTIME_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_fee_apr_pct": 0.0,
            "realized_fee_apr_pct": None,
            "fee_uptime_drag_pct": None,
            "time_in_range_fraction": None,
            "out_of_range_fraction": None,
            "realization_ratio": None,
            "longest_out_of_range_streak": 0,
            "range_flips": 0,
            "churn_ratio": None,
            "sample_count": 0,
            "uptime_from_samples": False,
            "currently_out_of_range": False,
            "persistent_out_of_range": False,
            "low_uptime": False,
            "frequent_rebalance_churn": False,
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
                "severe_count": 0,
                "position_count": len(results),
            }
        # Higher score = headline more realisable → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_DRIFT")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_count": severe,
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
            # FULL_UPTIME: wide band, price almost always in-range.
            "vault": "USDC-ETH-Wide-Band",
            "headline_fee_apr_pct": 18.0,
            "range_status_samples": [
                True, True, True, True, True, True, True, True, True, True],
        },
        {
            # MINOR_DRIFT: occasional brief excursions out of range.
            "vault": "ETH-USDT-Balanced",
            "headline_fee_apr_pct": 32.0,
            "range_status_samples": [
                1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1],
        },
        {
            # SEVERE_DRIFT: narrow band, price outside ~half the time + churn.
            "vault": "WBTC-ETH-Narrow",
            "headline_fee_apr_pct": 60.0,
            "range_status_samples": [
                "in", "out", "in", "out", "out", "in", "out", "out",
                "in", "out"],
        },
        {
            # MODERATE_DRIFT via direct override (no per-interval samples).
            "vault": "ARB-USDC-OverrideUptime",
            "headline_fee_apr_pct": 25.0,
            "time_in_range_fraction": 0.78,
        },
        {
            # INSUFFICIENT_DATA: positive headline but no samples / no override.
            "vault": "SOL-USDC-NoData",
            "headline_fee_apr_pct": 40.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1198 Vault Range Uptime Fee Realization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
