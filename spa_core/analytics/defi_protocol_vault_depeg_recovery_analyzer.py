"""
MP-1165: DeFiProtocolVaultDepegRecoveryAnalyzer
===============================================
Advisory/read-only analytics module.

A vault holds a pegged asset (stablecoin / LST / LRT) that has drifted away
from its peg. The holder must weigh the current discount-to-peg against the
asset's historical recovery profile: wait for the peg to be reclaimed, or exit
now and crystallise the loss. This module scores how safe it is to hold for a
recovery, weighing depeg depth, how long the depeg has persisted, the
historical recovery rate, and the presence/strength of collateral backing and
redemption availability.

HIGHER score = safer / higher chance of recovery (hold).

Distinct from:
  * defi_stablecoin_depeg_risk_monitor (Tier-A) → forward-looking depeg RISK.
This module is the *holder's recovery decision* on an asset that has ALREADY
depegged: hold for recovery vs exit at the discount.

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
    "data", "vault_depeg_recovery_log.json"
)
LOG_CAP = 100

# Discount-to-peg classification thresholds (%).
AT_PEG_PCT = 0.5            # discount at/below this is "at peg"
MINOR_DEPEG_PCT = 2.0       # discount at/below this is minor
MODERATE_DEPEG_PCT = 10.0   # discount at/below this is moderate; above → severe

# Discount scoring ceiling for the shallow-depeg component.
DISCOUNT_SCORE_CEILING_PCT = 15.0

# Staleness / freshness thresholds (days).
FRESH_DEPEG_DAYS = 7.0
STALE_DEPEG_DAYS = 30.0

# Recovery-history thresholds (%).
STRONG_RECOVERY_PCT = 70.0
WEAK_RECOVERY_PCT = 30.0

# Collateral threshold (%).
FULL_COLLATERAL_PCT = 100.0

# Severe-discount flag threshold (%).
SEVERE_DISCOUNT_PCT = 10.0


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

class DeFiProtocolVaultDepegRecoveryAnalyzer:
    """
    Scores the hold-for-recovery decision on a vault holding a pegged asset that
    has drifted off peg. Weighs the current discount-to-peg against historical
    recovery rate, depeg staleness, collateral backing and redemption
    availability.

    HIGHER score = safer / higher chance of recovery (hold).

    Per-position input dict fields:
        vault / token           : str
        current_price_usd        : float (default 0)
        peg_target_usd           : float (default 1.0; must be >0)
        days_depegged            : float (default 0; max(0,..))
        historical_recoveries    : float (default 0; max(0,..))
        historical_depegs        : float (default 0; max(0,..))
        is_collateralized        : bool  (default False)
        collateral_ratio_pct     : float (default 0; max(0,..))
        redemption_available     : bool  (default False)
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
        current_price_usd = _f(p.get("current_price_usd"))
        peg_target_usd = _f(p.get("peg_target_usd"), 1.0)
        days_depegged = max(0.0, _f(p.get("days_depegged")))
        historical_recoveries = max(0.0, _f(p.get("historical_recoveries")))
        historical_depegs = max(0.0, _f(p.get("historical_depegs")))
        is_collateralized = bool(p.get("is_collateralized", False))
        collateral_ratio_pct = max(0.0, _f(p.get("collateral_ratio_pct")))
        redemption_available = bool(p.get("redemption_available", False))

        # Insufficient data: no live price → nothing to analyze.
        if current_price_usd <= 0:
            return self._insufficient(token)
        # A non-positive peg target is unusable; treat as insufficient.
        if peg_target_usd <= 0:
            return self._insufficient(token)

        # Depeg %: positive = below peg (discount), negative = premium.
        depeg_pct = _safe_div(
            peg_target_usd - current_price_usd, peg_target_usd, 0.0) * 100.0
        depeg_pct = _clamp(depeg_pct, -1000.0, 100.0)
        # Round to a working precision so boundary comparisons are stable
        # against float artefacts (e.g. 0.5000000000000004 → 0.5).
        depeg_pct = round(depeg_pct, 6)
        discount_to_peg_pct = max(0.0, depeg_pct)

        recovery_rate_pct = _clamp(
            _safe_div(historical_recoveries, historical_depegs, 0.0) * 100.0,
            0.0, 100.0)

        # Upside if it returns to peg: (peg/price - 1)*100, clamped >= 0.
        upside_if_recovers_pct = max(
            0.0, _safe_div(peg_target_usd, current_price_usd, 0.0) * 100.0
            - 100.0)
        if not math.isfinite(upside_if_recovers_pct):
            upside_if_recovers_pct = 0.0

        is_stale_depeg = days_depegged >= STALE_DEPEG_DAYS
        undercollateralized = (
            is_collateralized and collateral_ratio_pct < FULL_COLLATERAL_PCT)

        score = self._score(
            discount_to_peg_pct, recovery_rate_pct, days_depegged,
            is_collateralized, collateral_ratio_pct, redemption_available)
        classification = self._classify(discount_to_peg_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, recovery_rate_pct)
        flags = self._flags(
            discount_to_peg_pct, days_depegged, recovery_rate_pct,
            historical_depegs, is_collateralized, collateral_ratio_pct,
            redemption_available)

        return {
            "token": token,
            "current_price_usd": round(current_price_usd, 6),
            "peg_target_usd": round(peg_target_usd, 6),
            "days_depegged": round(days_depegged, 4),
            "historical_recoveries": round(historical_recoveries, 4),
            "historical_depegs": round(historical_depegs, 4),
            "is_collateralized": is_collateralized,
            "collateral_ratio_pct": round(collateral_ratio_pct, 4),
            "redemption_available": redemption_available,
            "depeg_pct": round(depeg_pct, 4),
            "discount_to_peg_pct": round(discount_to_peg_pct, 4),
            "recovery_rate_pct": round(recovery_rate_pct, 4),
            "upside_if_recovers_pct": round(upside_if_recovers_pct, 4),
            "is_stale_depeg": is_stale_depeg,
            "undercollateralized": undercollateralized,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        discount_to_peg_pct: float,
        recovery_rate_pct: float,
        days_depegged: float,
        is_collateralized: bool,
        collateral_ratio_pct: float,
        redemption_available: bool,
    ) -> float:
        """
        0–100, HIGHER = safer / higher chance of recovery. Components:
          shallow depeg (35)   — smaller discount relative to the ceiling.
          recovery history (25)— historical recovery rate.
          fresh not stale (15) — fewer days depegged relative to staleness.
          collateralized (15)  — collateral ratio toward/over 100%.
          redemption (10)      — direct redemption available.
        """
        shallow_comp = 35.0 * _clamp(
            1.0 - discount_to_peg_pct / DISCOUNT_SCORE_CEILING_PCT, 0.0, 1.0)
        recovery_comp = 25.0 * _clamp(recovery_rate_pct / 100.0, 0.0, 1.0)
        fresh_comp = 15.0 * _clamp(
            1.0 - days_depegged / STALE_DEPEG_DAYS, 0.0, 1.0)
        if is_collateralized:
            collateral_comp = 15.0 * _clamp(
                collateral_ratio_pct / 100.0, 0.0, 1.0)
        else:
            collateral_comp = 0.0
        redemption_comp = 10.0 if redemption_available else 0.0
        total = (
            shallow_comp + recovery_comp + fresh_comp
            + collateral_comp + redemption_comp)
        return _clamp(total, 0.0, 100.0)

    def _classify(self, discount_to_peg_pct: float) -> str:
        if discount_to_peg_pct <= AT_PEG_PCT:
            return "AT_PEG"
        if discount_to_peg_pct <= MINOR_DEPEG_PCT:
            return "MINOR_DEPEG"
        if discount_to_peg_pct <= MODERATE_DEPEG_PCT:
            return "MODERATE_DEPEG"
        return "SEVERE_DEPEG"

    def _recommend(self, classification: str, recovery_rate_pct: float) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "EXIT"
        if classification == "AT_PEG":
            return "HOLD"
        if classification == "MINOR_DEPEG":
            return "HOLD_FOR_RECOVERY"
        if classification == "MODERATE_DEPEG":
            # Strong recovery history → still worth holding for recovery.
            if recovery_rate_pct >= STRONG_RECOVERY_PCT:
                return "HOLD_FOR_RECOVERY"
            return "EXIT_PARTIAL"
        # SEVERE_DEPEG
        if recovery_rate_pct >= STRONG_RECOVERY_PCT:
            return "EXIT_PARTIAL"
        return "EXIT"

    def _flags(
        self,
        discount_to_peg_pct: float,
        days_depegged: float,
        recovery_rate_pct: float,
        historical_depegs: float,
        is_collateralized: bool,
        collateral_ratio_pct: float,
        redemption_available: bool,
    ) -> List[str]:
        flags: List[str] = []

        if discount_to_peg_pct <= AT_PEG_PCT:
            flags.append("AT_PEG")
        if days_depegged < FRESH_DEPEG_DAYS:
            flags.append("FRESH_DEPEG")
        if days_depegged >= STALE_DEPEG_DAYS:
            flags.append("STALE_DEPEG")
        if recovery_rate_pct >= STRONG_RECOVERY_PCT:
            flags.append("STRONG_RECOVERY_HISTORY")
        if historical_depegs > 0 and recovery_rate_pct < WEAK_RECOVERY_PCT:
            flags.append("WEAK_RECOVERY_HISTORY")
        if is_collateralized:
            flags.append("COLLATERALIZED")
        if is_collateralized and collateral_ratio_pct < FULL_COLLATERAL_PCT:
            flags.append("UNDERCOLLATERALIZED")
        if redemption_available:
            flags.append("REDEMPTION_AVAILABLE")
        if discount_to_peg_pct >= SEVERE_DISCOUNT_PCT:
            flags.append("SEVERE_DISCOUNT")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "current_price_usd": 0.0,
            "peg_target_usd": 0.0,
            "days_depegged": 0.0,
            "historical_recoveries": 0.0,
            "historical_depegs": 0.0,
            "is_collateralized": False,
            "collateral_ratio_pct": 0.0,
            "redemption_available": False,
            "depeg_pct": 0.0,
            "discount_to_peg_pct": 0.0,
            "recovery_rate_pct": 0.0,
            "upside_if_recovers_pct": 0.0,
            "is_stale_depeg": False,
            "undercollateralized": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "EXIT",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_stable_vault": None,
                "least_stable_vault": None,
                "avg_score": 0.0,
                "severe_depeg_count": 0,
                "position_count": len(results),
            }
        # Higher score = safer/more stable → highest score is most stable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results if r["classification"] == "SEVERE_DEPEG")
        return {
            "most_stable_vault": by_score[-1]["token"],
            "least_stable_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_depeg_count": severe,
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
            "vault": "USDC-Vault-AtPeg",
            "current_price_usd": 0.9995,
            "peg_target_usd": 1.0,
            "days_depegged": 0.0,
            "historical_recoveries": 9.0,
            "historical_depegs": 10.0,
            "is_collateralized": True,
            "collateral_ratio_pct": 105.0,
            "redemption_available": True,
        },
        {
            "vault": "UST-Vault-SevereDepeg",
            "current_price_usd": 0.40,
            "peg_target_usd": 1.0,
            "days_depegged": 60.0,
            "historical_recoveries": 0.0,
            "historical_depegs": 3.0,
            "is_collateralized": False,
            "collateral_ratio_pct": 0.0,
            "redemption_available": False,
        },
        {
            "vault": "DAI-Vault-NoPrice",
            "current_price_usd": 0.0,
            "peg_target_usd": 1.0,
            "days_depegged": 0.0,
            "historical_recoveries": 0.0,
            "historical_depegs": 0.0,
            "is_collateralized": False,
            "collateral_ratio_pct": 0.0,
            "redemption_available": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1165 Vault Depeg Recovery Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDepegRecoveryAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
