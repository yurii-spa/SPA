"""
MP-1179: DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer
=========================================================
Advisory/read-only analytics module.

For a vault/LP whose yield comes from TRADING FEES, the fee-APR depends on a
volatile trading volume. A high trailing fee-APR captured during a volume spike
may not persist. High fee-APR volatility and/or a declining volume trend mean
the headline fee-APR is an unreliable / overstated signal of future yield.

Angle: "12% fee-APR, but a fee coefficient-of-variation of 70% and volume down
40% over the period → the sustainable fee-APR is closer to ~6%, discount it."

HIGHER score = more stable / more predictable fee yield.

Distinct from:
  * defi_protocol_volume_to_tvl_efficiency_analyzer — the LEVEL of the
    volume/TVL efficiency (a snapshot).
  * protocol_defi_lp_fee_vs_il_breakeven_analyzer — fees vs impermanent loss
    (the breakeven).
  * apy_anomaly_detector — one-off APY anomalies.
  THIS module isolates the VOLATILITY and TREND of the trading-fee APR itself
  and its durability — whether it is a stable signal or an artifact of a volume
  spike.

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
    "data", "vault_trading_fee_apr_volatility_log.json"
)
LOG_CAP = 100

# normalized_volatility (coefficient of variation of fee-APR) thresholds.
STABLE_VOLATILITY = 0.20      # norm_vol at/below this → stable
MODERATE_VOLATILITY = 0.50    # norm_vol at/below this → moderate
HIGH_VOLATILITY = 1.0         # norm_vol at/below this → high; above → unstable

# Small epsilon to avoid division by a near-zero fee-APR.
FEE_APR_EPSILON = 0.01

# Cap on the normalized volatility (coefficient of variation).
NORM_VOL_CAP = 10.0

# Volume-trend thresholds (volume_change_pct, signed).
VOLUME_DECLINING_PCT = -1.0   # below this → declining
VOLUME_RISING_PCT = 1.0       # above this → rising

# Severe volume-collapse threshold; with a material fee share lowers the
# recommendation.
VOLUME_COLLAPSE_PCT = -40.0

# Scoring references.
VOL_CEILING = 1.0             # norm_vol at/above this zeroes the stability comp
VOLUME_DROP_CEILING = 50.0    # a volume drop at/above this zeroes the trend comp

# High-fee-share flag threshold (fee_share_pct).
HIGH_FEE_SHARE_PCT = 50.0


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

class DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer:
    """
    Measures the VOLATILITY and TREND of a vault/LP's trading-fee APR to judge
    how durable the headline fee yield is. The coefficient of variation of the
    fee-APR (its volatility normalized by its own level) plus the direction of
    the volume trend drive a sustainable-fee-APR estimate, which discounts the
    fee slice of the APR. The base (non-fee) APR is unaffected. A high trailing
    fee-APR captured during a volume spike is an artifact the headline does not
    show.

    HIGHER score = more stable / more predictable fee yield.

    Per-position input dict fields:
        vault / token          : str
        headline_apr_pct       : float (max(0,..)); <=0 → INSUFFICIENT.
        fee_apr_pct            : float (default 0; max(0,..); clamped <=
                                 headline) — the APR slice from trading fees.
                                 <=0 → NO_FEE_YIELD.
        fee_apr_volatility_pct : float (default 0; max(0,..)) — standard
                                 deviation / spread of the fee-APR in pp or %.
        volume_change_pct      : float (signed, default 0) — volume trend (last
                                 period vs trailing).
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
        # for a fee-share / volatility computation.
        if headline <= 0:
            return self._insufficient(token)

        fee_apr = max(0.0, _f(p.get("fee_apr_pct")))
        fee_vol = max(0.0, _f(p.get("fee_apr_volatility_pct")))
        volume_change = _f(p.get("volume_change_pct"))
        if not math.isfinite(volume_change):
            volume_change = 0.0

        # Fee APR cannot exceed the headline.
        fee_apr = min(fee_apr, headline)
        base_apr = max(0.0, headline - fee_apr)

        # Share of the headline that comes from trading fees.
        fee_share = _safe_div(fee_apr * 100.0, headline, 0.0)
        if fee_share is None or not math.isfinite(fee_share):
            fee_share = 0.0

        # No fee yield: the headline is fully trustworthy on the volatility axis.
        if fee_apr <= 0:
            return self._no_fee_yield(token, headline, base_apr, fee_share)

        # Coefficient of variation of the fee-APR.
        normalized_volatility = _safe_div(
            fee_vol, max(fee_apr, FEE_APR_EPSILON), None)
        if (normalized_volatility is None
                or not math.isfinite(normalized_volatility)):
            normalized_volatility = 0.0
        normalized_volatility = _clamp(normalized_volatility, 0.0, NORM_VOL_CAP)

        volume_declining = bool(volume_change < VOLUME_DECLINING_PCT)
        volume_rising = bool(volume_change > VOLUME_RISING_PCT)
        volume_collapse = bool(volume_change <= VOLUME_COLLAPSE_PCT)

        # Sustainable fee-APR: discount for volatility, then for a declining
        # volume trend (a drop of up to 100% maps to up to a 50% haircut).
        vol_haircut = _clamp(normalized_volatility, 0.0, 1.0)
        drop = abs(min(0.0, volume_change))
        trend_haircut = _clamp(drop / 100.0, 0.0, 0.5)
        sustainable_fee_apr = fee_apr * (1.0 - vol_haircut) * (1.0 - trend_haircut)
        sustainable_fee_apr = _clamp(sustainable_fee_apr, 0.0, fee_apr)
        realized_headline_apr = base_apr + sustainable_fee_apr
        fee_apr_at_risk = max(0.0, fee_apr - sustainable_fee_apr)

        high_fee_share = bool(fee_share >= HIGH_FEE_SHARE_PCT)
        severe_collapse = bool(volume_collapse and high_fee_share)

        score = self._score(normalized_volatility, volume_change, fee_share)
        classification = self._classify(normalized_volatility)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, severe_collapse)
        flags = self._flags(
            classification,
            volume_declining,
            volume_rising,
            high_fee_share,
            volume_collapse,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "fee_apr_pct": round(fee_apr, 4),
            "fee_share_pct": round(fee_share, 4),
            "fee_apr_volatility_pct": round(fee_vol, 4),
            "volume_change_pct": round(volume_change, 4),
            "normalized_volatility": round(normalized_volatility, 4),
            "sustainable_fee_apr_pct": round(sustainable_fee_apr, 4),
            "fee_apr_at_risk_pct": round(fee_apr_at_risk, 4),
            "realized_headline_apr_pct": round(realized_headline_apr, 4),
            "volume_declining": volume_declining,
            "volume_rising": volume_rising,
            "high_fee_share": high_fee_share,
            "volume_collapse": volume_collapse,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        normalized_volatility: float,
        volume_change: float,
        fee_share: float,
    ) -> float:
        """
        0–100, HIGHER = more stable / more predictable fee yield. Components:
          stability (60) — (1 - clamp(norm_vol / VOL_CEILING)) × 60; the direct
            fee-APR predictability.
          trend (40) — 40 - 40 × clamp(volume_drop / VOLUME_DROP_CEILING) ×
            fee_share_frac; a declining-volume penalty scaled by how much of the
            headline rides on the fee layer.
        A norm_vol of 0 with stable volume → 100; penalties scale with impact.
        """
        stability_comp = 60.0 * (
            1.0 - _clamp(normalized_volatility / VOL_CEILING, 0.0, 1.0))
        drop = abs(min(0.0, volume_change))
        fee_share_frac = _clamp(fee_share / 100.0, 0.0, 1.0)
        trend_penalty = _clamp(
            drop / VOLUME_DROP_CEILING, 0.0, 1.0) * fee_share_frac
        trend_comp = 40.0 - 40.0 * trend_penalty
        total = stability_comp + trend_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, normalized_volatility: float) -> str:
        if normalized_volatility <= STABLE_VOLATILITY:
            return "STABLE_FEE_YIELD"
        if normalized_volatility <= MODERATE_VOLATILITY:
            return "MODERATE_VOLATILITY"
        if normalized_volatility <= HIGH_VOLATILITY:
            return "HIGH_VOLATILITY"
        return "UNSTABLE"

    def _recommend(
        self,
        classification: str,
        severe_collapse: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        # A severe volume collapse with a material fee share overrides to
        # AVOID_OR_VERIFY regardless of the trailing volatility class.
        if severe_collapse:
            return "AVOID_OR_VERIFY"
        if classification in ("NO_FEE_YIELD", "STABLE_FEE_YIELD"):
            return "TRUST_HEADLINE"
        if classification == "MODERATE_VOLATILITY":
            return "MINOR_FEE_DISCOUNT"
        if classification == "HIGH_VOLATILITY":
            return "DISCOUNT_FEE_LAYER"
        # UNSTABLE
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        volume_declining: bool,
        volume_rising: bool,
        high_fee_share: bool,
        volume_collapse: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_FEE_YIELD":
            flags.append("NO_FEE_YIELD")
        if classification == "STABLE_FEE_YIELD":
            flags.append("STABLE_FEE_YIELD")
        if classification == "MODERATE_VOLATILITY":
            flags.append("MODERATE_VOLATILITY")
        if classification == "HIGH_VOLATILITY":
            flags.append("HIGH_VOLATILITY")
        if classification == "UNSTABLE":
            flags.append("UNSTABLE")
        if volume_declining:
            flags.append("VOLUME_DECLINING")
        if volume_rising:
            flags.append("VOLUME_RISING")
        if high_fee_share:
            flags.append("HIGH_FEE_SHARE")
        if volume_collapse:
            flags.append("VOLUME_COLLAPSE")

        return flags

    def _no_fee_yield(
        self,
        token: str,
        headline: float,
        base_apr: float,
        fee_share: float,
    ) -> dict:
        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "fee_apr_pct": 0.0,
            "fee_share_pct": round(fee_share, 4),
            "fee_apr_volatility_pct": 0.0,
            "volume_change_pct": 0.0,
            "normalized_volatility": 0.0,
            "sustainable_fee_apr_pct": 0.0,
            "fee_apr_at_risk_pct": 0.0,
            "realized_headline_apr_pct": round(headline, 4),
            "volume_declining": False,
            "volume_rising": False,
            "high_fee_share": False,
            "volume_collapse": False,
            "score": 100.0,
            "classification": "NO_FEE_YIELD",
            "recommendation": "TRUST_HEADLINE",
            "grade": "A",
            "flags": ["NO_FEE_YIELD"],
        }

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "fee_apr_pct": 0.0,
            "fee_share_pct": None,
            "fee_apr_volatility_pct": 0.0,
            "volume_change_pct": 0.0,
            "normalized_volatility": None,
            "sustainable_fee_apr_pct": None,
            "fee_apr_at_risk_pct": None,
            "realized_headline_apr_pct": None,
            "volume_declining": False,
            "volume_rising": False,
            "high_fee_share": False,
            "volume_collapse": False,
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
                "most_stable_vault": None,
                "most_volatile_vault": None,
                "avg_score": 0.0,
                "unstable_count": 0,
                "position_count": len(results),
            }
        # Higher score = more stable → highest score is most stable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        unstable = sum(
            1 for r in results
            if r["classification"] == "UNSTABLE")
        return {
            "most_stable_vault": by_score[-1]["token"],
            "most_volatile_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "unstable_count": unstable,
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
            "vault": "USDC-Vault-NoFeeYield",
            "headline_apr_pct": 8.0,
            "fee_apr_pct": 0.0,
            "fee_apr_volatility_pct": 0.0,
            "volume_change_pct": 0.0,
        },
        {
            "vault": "ETH-Vault-Stable",
            "headline_apr_pct": 12.0,
            "fee_apr_pct": 6.0,
            "fee_apr_volatility_pct": 0.6,
            "volume_change_pct": 5.0,
        },
        {
            "vault": "ARB-Vault-ModerateVol",
            "headline_apr_pct": 14.0,
            "fee_apr_pct": 8.0,
            "fee_apr_volatility_pct": 3.2,
            "volume_change_pct": -10.0,
        },
        {
            "vault": "CRV-Vault-HighVol",
            "headline_apr_pct": 16.0,
            "fee_apr_pct": 10.0,
            "fee_apr_volatility_pct": 7.0,
            "volume_change_pct": -20.0,
        },
        {
            "vault": "CVX-Vault-Unstable-Collapse",
            "headline_apr_pct": 20.0,
            "fee_apr_pct": 14.0,
            "fee_apr_volatility_pct": 18.0,
            "volume_change_pct": -50.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "fee_apr_pct": 0.0,
            "fee_apr_volatility_pct": 0.0,
            "volume_change_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1179 Vault Trading Fee APR Volatility Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
