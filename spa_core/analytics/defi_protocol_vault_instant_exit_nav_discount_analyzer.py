"""
MP-1163: DeFiProtocolVaultInstantExitNavDiscountAnalyzer
========================================================
Advisory/read-only analytics module.

Some vaults offer two exit paths: an INSTANT exit at a discount to NAV (a
haircut paid for immediacy), or a STANDARD/queued redemption at full NAV after
a wait. A holder must weigh the instant-exit discount (paid now) against the
opportunity cost of capital being stuck in the redemption queue (yield
available elsewhere that you forgo while you wait).

This isolates the *instant-exit-vs-wait* decision — the effective discount paid
to leave immediately, the opportunity cost of the redemption queue, the
break-even wait beyond which eating the instant discount is cheaper, and which
path saves money.

Distinct from:
  * vault_withdrawal_fee_decay → a time-decaying early-withdrawal fee schedule.
This module answers only the *instant exit at a NAV discount vs queued
redemption at full NAV* question.

HIGHER score = lower exit friction (cheap/fast to get out either way).

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
    "data", "vault_instant_exit_nav_discount_log.json"
)
LOG_CAP = 100

HIGH_DISCOUNT_PCT = 5.0       # instant-exit discount at/above this is "steep"
MODERATE_DISCOUNT_PCT = 2.0   # discount at/above this is "moderate"
MINIMAL_DISCOUNT_PCT = 0.5    # discount at/below this is "minimal" (near-NAV)
LONG_QUEUE_DAYS = 30.0        # redemption queue at/above this is "long"
HIGH_WAIT_COST_PCT = 5.0      # wait opportunity cost at/above this is "high"
DAYS_PER_YEAR = 365.0


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

class DeFiProtocolVaultInstantExitNavDiscountAnalyzer:
    """
    Weighs a vault's INSTANT exit (at a discount to NAV, paid now) against a
    STANDARD/queued redemption (full NAV after a wait), accounting for the
    opportunity cost of capital stuck in the redemption queue.

    HIGHER score = lower exit friction (cheap/fast to get out either way).

    Per-position input dict fields:
        vault / token             : str
        position_usd              : float (default 0; max(0,..))
        nav_per_share_usd         : float (default 0; max(0,..))
        instant_exit_price_usd    : float (default 0; max(0,..))
        instant_exit_discount_pct : float (default 0; clamp 0..100; fallback)
        queue_wait_days           : float (default 0; max(0,..))
        redeploy_apr_pct          : float (default 0; max(0,..))
        vault_apr_pct             : float (default 0; max(0,..))
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
        position_usd = max(0.0, _f(p.get("position_usd")))
        nav_per_share_usd = max(0.0, _f(p.get("nav_per_share_usd")))
        instant_exit_price_usd = max(0.0, _f(p.get("instant_exit_price_usd")))
        instant_exit_discount_pct = _clamp(
            _f(p.get("instant_exit_discount_pct")), 0.0, 100.0)
        queue_wait_days = max(0.0, _f(p.get("queue_wait_days")))
        redeploy_apr_pct = max(0.0, _f(p.get("redeploy_apr_pct")))
        vault_apr_pct = max(0.0, _f(p.get("vault_apr_pct")))

        # Derive the instant-exit discount from NAV vs the instant price if both
        # are present; otherwise fall back to the direct discount input.
        if nav_per_share_usd > 0 and instant_exit_price_usd > 0:
            discount_pct = _clamp(
                (nav_per_share_usd - instant_exit_price_usd)
                / nav_per_share_usd * 100.0,
                0.0, 100.0)
        else:
            discount_pct = instant_exit_discount_pct

        # Insufficient data: no discount and no queue → exit is free either way,
        # there is nothing to decide.
        if discount_pct <= 0 and queue_wait_days <= 0:
            return self._insufficient(token)

        instant_exit_cost_usd = position_usd * discount_pct / 100.0
        # Yield available elsewhere (net of yield still earned while queued).
        excess_apr_pct = max(0.0, redeploy_apr_pct - vault_apr_pct)
        wait_opportunity_cost_pct = (
            excess_apr_pct * queue_wait_days / DAYS_PER_YEAR)
        wait_opportunity_cost_usd = (
            position_usd * wait_opportunity_cost_pct / 100.0)

        # Break-even wait: wait longer than this and eating the instant discount
        # becomes cheaper than the foregone yield. Undefined if no excess yield.
        if excess_apr_pct <= 0:
            breakeven_wait_days = None
        else:
            breakeven_wait_days = discount_pct * DAYS_PER_YEAR / excess_apr_pct

        instant_cheaper = discount_pct <= wait_opportunity_cost_pct
        savings_by_waiting_pct = max(
            0.0, discount_pct - wait_opportunity_cost_pct)
        savings_by_waiting_usd = position_usd * savings_by_waiting_pct / 100.0
        has_queue_option = queue_wait_days > 0

        score = self._score(discount_pct, queue_wait_days,
                            wait_opportunity_cost_pct)
        classification = self._classify(discount_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(
            classification, instant_cheaper, has_queue_option)
        flags = self._flags(
            discount_pct, queue_wait_days, wait_opportunity_cost_pct,
            instant_cheaper, savings_by_waiting_pct, has_queue_option)

        return {
            "token": token,
            "position_usd": round(position_usd, 4),
            "nav_per_share_usd": round(nav_per_share_usd, 4),
            "instant_exit_price_usd": round(instant_exit_price_usd, 4),
            "instant_exit_discount_pct": round(discount_pct, 4),
            "queue_wait_days": round(queue_wait_days, 4),
            "redeploy_apr_pct": round(redeploy_apr_pct, 4),
            "vault_apr_pct": round(vault_apr_pct, 4),
            "instant_exit_cost_usd": round(instant_exit_cost_usd, 4),
            "excess_apr_pct": round(excess_apr_pct, 4),
            "wait_opportunity_cost_pct": round(wait_opportunity_cost_pct, 4),
            "wait_opportunity_cost_usd": round(wait_opportunity_cost_usd, 4),
            "breakeven_wait_days": (
                None if breakeven_wait_days is None
                else round(breakeven_wait_days, 4)),
            "instant_cheaper": instant_cheaper,
            "savings_by_waiting_pct": round(savings_by_waiting_pct, 4),
            "savings_by_waiting_usd": round(savings_by_waiting_usd, 4),
            "has_queue_option": has_queue_option,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        discount_pct: float,
        queue_wait_days: float,
        wait_opportunity_cost_pct: float,
    ) -> float:
        """
        0–100, HIGHER = lower exit friction (cheap/fast to get out). Components:
          low discount (50)   — instant-exit discount inverse of HIGH_DISCOUNT.
          short queue (30)    — redemption queue inverse of LONG_QUEUE_DAYS.
          low wait cost (20)  — wait opportunity cost inverse of HIGH_WAIT_COST.
        """
        low_discount_comp = 50.0 * _clamp(
            1.0 - discount_pct / HIGH_DISCOUNT_PCT, 0.0, 1.0)
        short_queue_comp = 30.0 * _clamp(
            1.0 - queue_wait_days / LONG_QUEUE_DAYS, 0.0, 1.0)
        low_wait_cost_comp = 20.0 * _clamp(
            1.0 - wait_opportunity_cost_pct / HIGH_WAIT_COST_PCT, 0.0, 1.0)
        total = low_discount_comp + short_queue_comp + low_wait_cost_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, discount_pct: float) -> str:
        if discount_pct <= MINIMAL_DISCOUNT_PCT:
            return "MINIMAL_DISCOUNT"
        if discount_pct <= MODERATE_DISCOUNT_PCT:
            return "LOW_DISCOUNT"
        if discount_pct <= HIGH_DISCOUNT_PCT:
            return "MODERATE_DISCOUNT"
        return "STEEP_DISCOUNT"

    def _recommend(
        self,
        classification: str,
        instant_cheaper: bool,
        has_queue_option: bool,
    ) -> str:
        # INSUFFICIENT_DATA → EXIT_OK: full NAV instant exit and no queue means
        # a free exit, so there is nothing to decide.
        if classification == "INSUFFICIENT_DATA":
            return "EXIT_OK"
        if instant_cheaper:
            return "EXIT_INSTANT"
        if has_queue_option:
            return "WAIT_FOR_NAV"
        return "EXIT_INSTANT"

    def _flags(
        self,
        discount_pct: float,
        queue_wait_days: float,
        wait_opportunity_cost_pct: float,
        instant_cheaper: bool,
        savings_by_waiting_pct: float,
        has_queue_option: bool,
    ) -> List[str]:
        flags: List[str] = []

        if discount_pct <= MINIMAL_DISCOUNT_PCT:
            flags.append("NAV_EXIT_AVAILABLE")
        if discount_pct >= HIGH_DISCOUNT_PCT:
            flags.append("STEEP_EXIT_DISCOUNT")
        if queue_wait_days >= LONG_QUEUE_DAYS:
            flags.append("LONG_REDEMPTION_QUEUE")
        if instant_cheaper and has_queue_option:
            flags.append("INSTANT_EXIT_CHEAPER")
        if savings_by_waiting_pct > 0:
            flags.append("WAIT_SAVES_VS_DISCOUNT")
        if wait_opportunity_cost_pct >= HIGH_WAIT_COST_PCT:
            flags.append("HIGH_WAIT_OPPORTUNITY_COST")
        if (not has_queue_option) and discount_pct > 0:
            flags.append("NO_QUEUE_OPTION")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "position_usd": 0.0,
            "nav_per_share_usd": 0.0,
            "instant_exit_price_usd": 0.0,
            "instant_exit_discount_pct": 0.0,
            "queue_wait_days": 0.0,
            "redeploy_apr_pct": 0.0,
            "vault_apr_pct": 0.0,
            "instant_exit_cost_usd": 0.0,
            "excess_apr_pct": 0.0,
            "wait_opportunity_cost_pct": 0.0,
            "wait_opportunity_cost_usd": 0.0,
            "breakeven_wait_days": None,
            "instant_cheaper": False,
            "savings_by_waiting_pct": 0.0,
            "savings_by_waiting_usd": 0.0,
            "has_queue_option": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "EXIT_OK",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "easiest_exit_vault": None,
                "hardest_exit_vault": None,
                "avg_score": 0.0,
                "steep_discount_count": 0,
                "position_count": len(results),
            }
        # Higher score = lower exit friction → highest score is easiest exit.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        steep = sum(
            1 for r in results
            if r["classification"] == "STEEP_DISCOUNT")
        return {
            "easiest_exit_vault": by_score[-1]["token"],
            "hardest_exit_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "steep_discount_count": steep,
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
            "vault": "USDC-Vault-NavExit",
            "position_usd": 10000.0,
            "nav_per_share_usd": 1.0,
            "instant_exit_price_usd": 0.999,
            "queue_wait_days": 0.0,
            "redeploy_apr_pct": 8.0,
            "vault_apr_pct": 6.0,
        },
        {
            "vault": "ETH-Vault-SteepDiscountLongQueue",
            "position_usd": 25000.0,
            "nav_per_share_usd": 1.0,
            "instant_exit_price_usd": 0.93,
            "queue_wait_days": 30.0,
            "redeploy_apr_pct": 12.0,
            "vault_apr_pct": 4.0,
        },
        {
            "vault": "DAI-Vault-FreeExit",
            "position_usd": 5000.0,
            "nav_per_share_usd": 0.0,
            "instant_exit_price_usd": 0.0,
            "instant_exit_discount_pct": 0.0,
            "queue_wait_days": 0.0,
            "redeploy_apr_pct": 6.0,
            "vault_apr_pct": 6.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1163 Vault Instant Exit NAV Discount Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultInstantExitNavDiscountAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
