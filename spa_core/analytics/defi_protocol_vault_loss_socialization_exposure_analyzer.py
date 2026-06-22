"""
MP-1163: DeFiProtocolVaultLossSocializationExposureAnalyzer
===========================================================
Advisory/read-only analytics module.

When a vault absorbs bad debt or a strategy loss, the loss is *socialized* — it is
spread pro-rata across every share-holder, so the share price drops for everyone
at once. A holder needs to estimate their pro-rata slice of any potential loss:
the outstanding (uncovered) bad-debt pool, whether an insurance / backstop buffer
covers it, the holder's share of the vault, and the estimated haircut to the
share price.

This isolates the holder's *pro-rata exposure to loss socialization* — position
share of the vault, uncovered loss after the insurance buffer, the holder's USD
loss exposure, and the estimated share-price haircut.

Distinct from:
  * defi_lending_protocol_bad_debt_monitor → monitors bad debt at the PROTOCOL
    level, not the holder's slice.
  * vault_share_inflation_attack_exposure → first-depositor inflation attack.
This module answers only the holder's *pro-rata loss-socialization* exposure.

HIGHER score = safer (little uncovered loss, well covered, backstopped, senior).

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional

# constants
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_loss_socialization_exposure_log.json"
)
LOG_CAP = 100

HIGH_HAIRCUT_PCT = 5.0
MODERATE_HAIRCUT_PCT = 1.0
LOW_COVERAGE_PCT = 50.0
CONCENTRATED_SHARE_PCT = 25.0
SUBORDINATED_LOSS_MULTIPLIER = 2.0
SENTINEL = 0.0


# helpers

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


# main class

class DeFiProtocolVaultLossSocializationExposureAnalyzer:
    """
    Models a holder's pro-rata exposure to a vault's loss socialization: the
    position's share of the vault, the uncovered loss after the insurance buffer,
    the holder's USD loss exposure, and the estimated share-price haircut.

    HIGHER score = safer.

    Per-position input dict fields:
        vault / token             : str
        vault_tvl_usd             : float (default 0; max(0,..))
        position_usd              : float (default 0; max(0,..))
        outstanding_bad_debt_usd  : float (default 0; max(0,..))
        insurance_buffer_usd      : float (default 0; max(0,..))
        has_loss_backstop         : bool  (default False)
        subordinated_tranche      : bool  (default False)
    """

    # public API

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

    # per-position

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        vault_tvl_usd = max(0.0, _f(p.get("vault_tvl_usd")))
        position_usd = max(0.0, _f(p.get("position_usd")))
        outstanding_bad_debt_usd = max(0.0, _f(p.get("outstanding_bad_debt_usd")))
        insurance_buffer_usd = max(0.0, _f(p.get("insurance_buffer_usd")))
        has_loss_backstop = bool(p.get("has_loss_backstop", False))
        subordinated_tranche = bool(p.get("subordinated_tranche", False))

        # Insufficient data: no vault and no position -> nothing to analyze.
        if vault_tvl_usd <= 0 and position_usd <= 0:
            return self._insufficient(token)

        position_share_pct = _safe_div(
            position_usd * 100.0, vault_tvl_usd, SENTINEL)
        position_share_pct = _clamp(position_share_pct, 0.0, 100.0)

        uncovered_loss_usd = max(
            0.0, outstanding_bad_debt_usd - insurance_buffer_usd)

        # buffer coverage as a pct of outstanding bad debt; sentinel if no debt.
        buffer_coverage_pct = _safe_div(
            insurance_buffer_usd * 100.0, outstanding_bad_debt_usd, SENTINEL)
        buffer_coverage_pct = _clamp(buffer_coverage_pct, 0.0, 100.0)

        # holder's pro-rata slice of the uncovered loss. A subordinated (junior)
        # tranche absorbs loss first, so apply an amplified multiplier capped at
        # the position size (cannot lose more than the position).
        share_fraction = position_share_pct / 100.0
        my_loss_exposure_usd = uncovered_loss_usd * share_fraction
        if subordinated_tranche:
            my_loss_exposure_usd *= SUBORDINATED_LOSS_MULTIPLIER
        my_loss_exposure_usd = _clamp(my_loss_exposure_usd, 0.0, position_usd)

        # estimated share-price haircut: uncovered loss as a pct of vault TVL.
        estimated_share_price_haircut_pct = _safe_div(
            uncovered_loss_usd * 100.0, vault_tvl_usd, SENTINEL)
        estimated_share_price_haircut_pct = max(
            0.0, estimated_share_price_haircut_pct)

        score = self._score(
            estimated_share_price_haircut_pct, buffer_coverage_pct,
            outstanding_bad_debt_usd, has_loss_backstop, subordinated_tranche)
        classification = self._classify(estimated_share_price_haircut_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            outstanding_bad_debt_usd, uncovered_loss_usd, insurance_buffer_usd,
            has_loss_backstop, subordinated_tranche,
            estimated_share_price_haircut_pct, position_share_pct)

        return {
            "token": token,
            "vault_tvl_usd": round(vault_tvl_usd, 4),
            "position_usd": round(position_usd, 4),
            "outstanding_bad_debt_usd": round(outstanding_bad_debt_usd, 4),
            "insurance_buffer_usd": round(insurance_buffer_usd, 4),
            "has_loss_backstop": has_loss_backstop,
            "subordinated_tranche": subordinated_tranche,
            "position_share_pct": round(position_share_pct, 4),
            "uncovered_loss_usd": round(uncovered_loss_usd, 4),
            "buffer_coverage_pct": round(buffer_coverage_pct, 4),
            "my_loss_exposure_usd": round(my_loss_exposure_usd, 4),
            "estimated_share_price_haircut_pct": round(
                estimated_share_price_haircut_pct, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # scoring

    def _score(
        self,
        haircut_pct: float,
        buffer_coverage_pct: float,
        outstanding_bad_debt_usd: float,
        has_loss_backstop: bool,
        subordinated_tranche: bool,
    ) -> float:
        """
        0-100, HIGHER = safer. Components:
          low uncovered loss vs TVL (40) - inverse of HIGH_HAIRCUT_PCT.
          high buffer coverage (30)      - coverage of bad debt (full when no debt).
          has loss backstop (15)         - an external backstop is present.
          not subordinated (15)          - position is senior, not junior tranche.
        """
        low_haircut_comp = 40.0 * _clamp(
            1.0 - haircut_pct / HIGH_HAIRCUT_PCT, 0.0, 1.0)
        # No bad debt at all -> treat as fully covered for the coverage component.
        coverage = 100.0 if outstanding_bad_debt_usd <= 0 else buffer_coverage_pct
        coverage_comp = 30.0 * _clamp(coverage / 100.0, 0.0, 1.0)
        backstop_comp = 15.0 if has_loss_backstop else 0.0
        senior_comp = 0.0 if subordinated_tranche else 15.0
        total = low_haircut_comp + coverage_comp + backstop_comp + senior_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, haircut_pct: float) -> str:
        if haircut_pct >= HIGH_HAIRCUT_PCT:
            return "HIGH_LOSS_EXPOSURE"
        if haircut_pct >= MODERATE_HAIRCUT_PCT:
            return "ELEVATED"
        if haircut_pct > 0:
            return "MODERATE"
        return "LOW"

    def _recommend(self, classification: str) -> str:
        # INSUFFICIENT_DATA -> HOLD: nothing to analyze.
        if classification == "INSUFFICIENT_DATA":
            return "HOLD"
        if classification == "LOW":
            return "HOLD"
        if classification == "MODERATE":
            return "HOLD_WITH_CAUTION"
        if classification == "ELEVATED":
            return "REDUCE_EXPOSURE"
        # HIGH_LOSS_EXPOSURE
        return "EXIT"

    def _flags(
        self,
        outstanding_bad_debt_usd: float,
        uncovered_loss_usd: float,
        insurance_buffer_usd: float,
        has_loss_backstop: bool,
        subordinated_tranche: bool,
        haircut_pct: float,
        position_share_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if outstanding_bad_debt_usd <= 0:
            flags.append("NO_BAD_DEBT")
        else:
            if uncovered_loss_usd <= 0:
                flags.append("FULLY_COVERED")
            elif insurance_buffer_usd > 0:
                flags.append("PARTIALLY_COVERED")
            if uncovered_loss_usd > 0:
                flags.append("UNCOVERED_LOSS")

        if has_loss_backstop:
            flags.append("HAS_BACKSTOP")
        else:
            flags.append("NO_BACKSTOP")
        if subordinated_tranche:
            flags.append("SUBORDINATED_TRANCHE")
        if haircut_pct >= HIGH_HAIRCUT_PCT:
            flags.append("LARGE_HAIRCUT")
        if position_share_pct >= CONCENTRATED_SHARE_PCT:
            flags.append("CONCENTRATED_POSITION")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "vault_tvl_usd": 0.0,
            "position_usd": 0.0,
            "outstanding_bad_debt_usd": 0.0,
            "insurance_buffer_usd": 0.0,
            "has_loss_backstop": False,
            "subordinated_tranche": False,
            "position_share_pct": 0.0,
            "uncovered_loss_usd": 0.0,
            "buffer_coverage_pct": 0.0,
            "my_loss_exposure_usd": 0.0,
            "estimated_share_price_haircut_pct": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "HOLD",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # aggregate

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "safest_vault": None,
                "riskiest_vault": None,
                "avg_score": 0.0,
                "high_exposure_count": 0,
                "position_count": len(results),
            }
        # Higher score = safer -> highest score is safest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_exposure = sum(
            1 for r in results
            if r["classification"] == "HIGH_LOSS_EXPOSURE")
        return {
            "safest_vault": by_score[-1]["token"],
            "riskiest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_exposure_count": high_exposure,
            "position_count": len(results),
        }

    # ring-buffer log

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


# CLI

def _demo_positions() -> List[dict]:
    return [
        {
            "vault": "USDC-Vault-Safe",
            "vault_tvl_usd": 5000000.0,
            "position_usd": 10000.0,
            "outstanding_bad_debt_usd": 0.0,
            "insurance_buffer_usd": 200000.0,
            "has_loss_backstop": True,
            "subordinated_tranche": False,
        },
        {
            "vault": "ETH-Vault-Stressed",
            "vault_tvl_usd": 2000000.0,
            "position_usd": 600000.0,
            "outstanding_bad_debt_usd": 300000.0,
            "insurance_buffer_usd": 50000.0,
            "has_loss_backstop": False,
            "subordinated_tranche": True,
        },
        {
            "vault": "DAI-Vault-Empty",
            "vault_tvl_usd": 0.0,
            "position_usd": 0.0,
            "outstanding_bad_debt_usd": 0.0,
            "insurance_buffer_usd": 0.0,
            "has_loss_backstop": False,
            "subordinated_tranche": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1163 Vault Loss Socialization Exposure Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultLossSocializationExposureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
