"""
MP-1162: DeFiProtocolVaultManagementFeeAccrualAnalyzer
======================================================
Advisory/read-only analytics module.

Many vaults charge a TIME-BASED management (AUM) fee: a fee accrued *continuously*
on the assets-under-management irrespective of whether the strategy earns anything.
Unlike a performance fee (taken only from PROFIT), a management fee drags on the
position every single day it is held. A holder needs to know how much management
fee has already accrued over the holding period, the annualized drag on the
effective APR, and the net APR after the management fee is deducted.

This isolates the *continuous AUM-fee* question — accrued fee over days held, the
annual fee drag, net APR after the fee, and what fraction of the gross yield the
fee consumes.

Distinct from:
  * performance_fee_high_water_mark / performance_fee_crystallization → fees taken
    only from PROFIT above a high-water mark.
  * withdrawal_fee_decay → a one-time fee charged on EXIT, not continuously.
This module answers only the *continuous time-based AUM management fee* question.

HIGHER score = cheaper / lower drag (a small management fee that leaves most of
the gross yield intact).

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional

# constants
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_management_fee_accrual_log.json"
)
LOG_CAP = 100

HIGH_MGMT_FEE_PCT = 2.0
MODERATE_MGMT_FEE_PCT = 1.0
LOW_MGMT_FEE_PCT = 0.5
EXCESSIVE_MGMT_FEE_PCT = 4.0
FEE_HALF_YIELD_PCT = 50.0
DAYS_PER_YEAR = 365.0
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

class DeFiProtocolVaultManagementFeeAccrualAnalyzer:
    """
    Models a vault's CONTINUOUS time-based management (AUM) fee: how much fee has
    accrued over the holding period, the annual drag on APR, the net APR after the
    fee, and what fraction of the gross yield the fee consumes.

    HIGHER score = cheaper / lower drag.

    Per-position input dict fields:
        vault / token              : str
        management_fee_pct_annual  : float (default 0; clamp 0..100)
        position_usd               : float (default 0; max(0,..))
        days_held                  : float (default 0; max(0,..))
        gross_apr_pct              : float (default 0)
        accrual_basis_days         : float (default 365)
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
        mgmt_fee = _clamp(_f(p.get("management_fee_pct_annual")), 0.0, 100.0)
        position_usd = max(0.0, _f(p.get("position_usd")))
        days_held = max(0.0, _f(p.get("days_held")))
        gross_apr_pct = _f(p.get("gross_apr_pct"))
        accrual_basis_days = _f(p.get("accrual_basis_days"), DAYS_PER_YEAR)
        if accrual_basis_days <= 0:
            accrual_basis_days = DAYS_PER_YEAR

        # Insufficient data: no management fee and no position -> nothing to
        # compute. A zero fee means a free hold, so the recommendation is HOLD_OK.
        if mgmt_fee <= 0 and position_usd <= 0:
            return self._insufficient(token)

        # accrued management fee over the holding period (time-based AUM fee).
        accrued_fee_pct = mgmt_fee * days_held / accrual_basis_days
        accrued_fee_usd = position_usd * accrued_fee_pct / 100.0
        annual_fee_drag_pct = mgmt_fee
        net_apr_pct = gross_apr_pct - mgmt_fee
        daily_fee_usd = position_usd * mgmt_fee / 100.0 / DAYS_PER_YEAR

        # gross yield (pct) earned over the holding period; the management fee as a
        # share of that gross yield. Sentinel when there is no positive gross yield.
        gross_yield_period_pct = gross_apr_pct * days_held / DAYS_PER_YEAR
        fee_as_pct_of_gross_yield = _safe_div(
            accrued_fee_pct * 100.0, gross_yield_period_pct, SENTINEL)
        if fee_as_pct_of_gross_yield < 0:
            fee_as_pct_of_gross_yield = SENTINEL

        score = self._score(mgmt_fee, gross_apr_pct, net_apr_pct)
        classification = self._classify(mgmt_fee)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            mgmt_fee, net_apr_pct, fee_as_pct_of_gross_yield)

        return {
            "token": token,
            "management_fee_pct_annual": round(mgmt_fee, 4),
            "position_usd": round(position_usd, 4),
            "days_held": round(days_held, 4),
            "gross_apr_pct": round(gross_apr_pct, 4),
            "accrual_basis_days": round(accrual_basis_days, 4),
            "accrued_fee_pct": round(accrued_fee_pct, 4),
            "accrued_fee_usd": round(accrued_fee_usd, 4),
            "annual_fee_drag_pct": round(annual_fee_drag_pct, 4),
            "net_apr_pct": round(net_apr_pct, 4),
            "fee_as_pct_of_gross_yield": round(fee_as_pct_of_gross_yield, 4),
            "daily_fee_usd": round(daily_fee_usd, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # scoring

    def _score(
        self,
        mgmt_fee: float,
        gross_apr_pct: float,
        net_apr_pct: float,
    ) -> float:
        """
        0-100, HIGHER = cheaper / lower drag. Components:
          low management fee (55) - inverse of HIGH_MGMT_FEE_PCT.
          high net/gross ratio (30) - fraction of gross yield surviving the fee.
          positive net APR (15)    - net APR is still positive after the fee.
        """
        low_fee_comp = 55.0 * _clamp(
            1.0 - mgmt_fee / HIGH_MGMT_FEE_PCT, 0.0, 1.0)
        # net/gross ratio: how much of the gross yield survives the fee.
        ratio = _safe_div(net_apr_pct, gross_apr_pct, SENTINEL)
        high_ratio_comp = 30.0 * _clamp(ratio, 0.0, 1.0)
        positive_net_comp = 15.0 if net_apr_pct > 0 else 0.0
        total = low_fee_comp + high_ratio_comp + positive_net_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, mgmt_fee: float) -> str:
        if mgmt_fee >= EXCESSIVE_MGMT_FEE_PCT:
            return "EXCESSIVE_FEE"
        if mgmt_fee >= HIGH_MGMT_FEE_PCT:
            return "HIGH_FEE"
        if mgmt_fee >= MODERATE_MGMT_FEE_PCT:
            return "MODERATE_FEE"
        return "LOW_FEE"

    def _recommend(self, classification: str) -> str:
        # INSUFFICIENT_DATA -> HOLD_OK: no management fee means a free hold, so
        # there is nothing to act on.
        if classification == "INSUFFICIENT_DATA":
            return "HOLD_OK"
        if classification == "LOW_FEE":
            return "HOLD_OK"
        if classification == "MODERATE_FEE":
            return "ACCEPTABLE"
        if classification == "HIGH_FEE":
            return "REVIEW_FEE"
        # EXCESSIVE_FEE
        return "AVOID_HIGH_FEE"

    def _flags(
        self,
        mgmt_fee: float,
        net_apr_pct: float,
        fee_as_pct_of_gross_yield: float,
    ) -> List[str]:
        flags: List[str] = []

        if mgmt_fee <= 0:
            flags.append("ZERO_MANAGEMENT_FEE")
        if mgmt_fee < LOW_MGMT_FEE_PCT:
            flags.append("LOW_MANAGEMENT_FEE")
        if mgmt_fee >= HIGH_MGMT_FEE_PCT:
            flags.append("HIGH_MANAGEMENT_FEE")
        if mgmt_fee >= EXCESSIVE_MGMT_FEE_PCT:
            flags.append("EXCESSIVE_FEE")
        if net_apr_pct < 0:
            flags.append("NEGATIVE_NET_APR")
        if fee_as_pct_of_gross_yield >= FEE_HALF_YIELD_PCT:
            flags.append("FEE_EXCEEDS_HALF_YIELD")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "management_fee_pct_annual": 0.0,
            "position_usd": 0.0,
            "days_held": 0.0,
            "gross_apr_pct": 0.0,
            "accrual_basis_days": 0.0,
            "accrued_fee_pct": 0.0,
            "accrued_fee_usd": 0.0,
            "annual_fee_drag_pct": 0.0,
            "net_apr_pct": 0.0,
            "fee_as_pct_of_gross_yield": 0.0,
            "daily_fee_usd": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "HOLD_OK",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # aggregate

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cheapest_vault": None,
                "most_expensive_vault": None,
                "avg_score": 0.0,
                "high_fee_count": 0,
                "position_count": len(results),
            }
        # Higher score = cheaper -> highest score is cheapest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_fee = sum(
            1 for r in results
            if r["classification"] in ("HIGH_FEE", "EXCESSIVE_FEE"))
        return {
            "cheapest_vault": by_score[-1]["token"],
            "most_expensive_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_fee_count": high_fee,
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
            "vault": "USDC-Vault-LowFee",
            "management_fee_pct_annual": 0.3,
            "position_usd": 10000.0,
            "days_held": 90.0,
            "gross_apr_pct": 8.0,
            "accrual_basis_days": 365.0,
        },
        {
            "vault": "ETH-Vault-HighFee",
            "management_fee_pct_annual": 4.5,
            "position_usd": 25000.0,
            "days_held": 180.0,
            "gross_apr_pct": 6.0,
            "accrual_basis_days": 365.0,
        },
        {
            "vault": "DAI-Vault-NoFee",
            "management_fee_pct_annual": 0.0,
            "position_usd": 0.0,
            "days_held": 30.0,
            "gross_apr_pct": 5.0,
            "accrual_basis_days": 365.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1162 Vault Management Fee Accrual Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultManagementFeeAccrualAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
