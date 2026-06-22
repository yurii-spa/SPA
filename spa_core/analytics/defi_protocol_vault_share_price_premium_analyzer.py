"""
MP-1182: DeFiProtocolVaultSharePricePremiumAnalyzer
===================================================
Advisory/read-only analytics module.

A vault share (or its secondary-market price) can trade ABOVE its NAV. Entering
at a premium erodes your return because the price is expected to converge back
toward NAV over a horizon. The wider the premium (and the shorter the
convergence horizon), the larger the annualized drag you pay just to get in.

Angle: "NAV is $1.00 but the share trades at $1.05 → you pay a 5% premium that
converges over 30 days, an ~60% annualized drag → wait for convergence."

HIGHER score = cheaper entry (at/below NAV).

Distinct from:
  * defi_protocol_vault_instant_exit_nav_discount_analyzer — the EXIT side: how
    much you lose selling/redeeming a share BELOW its NAV (a discount on exit).
  THIS module is the ENTRY-side mirror — how much extra you pay buying a share
  ABOVE its NAV (a premium on entry) and the annualized drag that premium
  imposes until it converges.

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
    "data", "vault_share_price_premium_log.json"
)
LOG_CAP = 100

# Default convergence horizon (days) when none / non-positive supplied.
DEFAULT_CONVERGENCE_HORIZON_DAYS = 30.0

# premium_pct classification thresholds.
SLIGHT_PREMIUM_PCT = 1.0      # premium at/below this → slight
MODERATE_PREMIUM_PCT = 3.0    # premium at/below this → moderate
HIGH_PREMIUM_PCT = 7.0        # premium at/below this → high; above → extreme

# Scoring references.
PREMIUM_SCORE_CEILING = 10.0  # premium_pct at/above which the premium component
#                               zeroes out (full erosion of the entry credit).
DRAG_SCORE_CEILING = 100.0    # annualized_drag_pct at/above which the drag
#                               component zeroes out.

# High-annualized-drag flag threshold (annualized_drag_pct).
HIGH_DRAG_PCT = 50.0

# Caps to keep metrics finite.
PREMIUM_PCT_FLOOR = -100.0
PREMIUM_PCT_CAP = 1000.0
DRAG_PCT_CAP = 1e6


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

class DeFiProtocolVaultSharePricePremiumAnalyzer:
    """
    Measures how much PREMIUM (over NAV) you pay to ENTER a vault share. The
    premium_pct = (market_price - nav)/nav * 100; a positive premium erodes the
    return because the price is expected to converge back toward NAV over a
    convergence horizon. The premium is converted to an annualized drag and,
    optionally, to a yield-payback period. The result discounts the
    attractiveness of entering; it does not change the headline APR itself.

    HIGHER score = cheaper entry (at/below NAV).

    Per-position input dict fields:
        vault / token             : str
        nav_per_share             : float; <=0 → INSUFFICIENT_DATA.
        market_price_per_share    : float; <=0 → INSUFFICIENT_DATA.
        expected_apr_pct          : float (default 0; max(0,..)) — used for the
                                    premium payback metric.
        convergence_horizon_days  : float (max(0,..); default 30.0) — horizon
                                    over which the premium converges; <=0 →
                                    falls back to default.
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
        nav = _f(p.get("nav_per_share"))
        market = _f(p.get("market_price_per_share"))

        # Insufficient data fast-path: a non-positive NAV or price gives no
        # meaningful premium to judge.
        if nav <= 0 or market <= 0 or not math.isfinite(nav) \
                or not math.isfinite(market):
            return self._insufficient(token)

        expected_apr = max(0.0, _f(p.get("expected_apr_pct")))
        if not math.isfinite(expected_apr):
            expected_apr = 0.0

        horizon = max(
            0.0, _f(p.get("convergence_horizon_days"),
                    DEFAULT_CONVERGENCE_HORIZON_DAYS))
        if horizon <= 0 or not math.isfinite(horizon):
            horizon = DEFAULT_CONVERGENCE_HORIZON_DAYS

        # premium_pct = (market - nav)/nav * 100 (negative = discount = good).
        premium_pct = (market - nav) / nav * 100.0
        premium_pct = _clamp(premium_pct, PREMIUM_PCT_FLOOR, PREMIUM_PCT_CAP)
        # Round to a stable precision so classification band boundaries are
        # deterministic (avoids float artefacts like 7.000000000000001).
        premium_pct = round(premium_pct, 6)

        is_premium = bool(premium_pct > 0)

        # annualized_drag_pct: premium spread over the convergence horizon,
        # annualized. Only a positive premium imposes a drag.
        if premium_pct > 0:
            annualized_drag_pct = premium_pct * (365.0 / horizon)
        else:
            annualized_drag_pct = 0.0
        annualized_drag_pct = _clamp(annualized_drag_pct, 0.0, DRAG_PCT_CAP)

        # payback_days: days of yield needed to recoup the premium.
        if premium_pct > 0 and expected_apr > 0:
            payback_days = premium_pct / expected_apr * 365.0
            if not math.isfinite(payback_days):
                payback_days = None
            else:
                payback_days = round(payback_days, 4)
        elif premium_pct <= 0:
            payback_days = 0.0
        else:
            # premium exists but no APR to recoup it → undefined.
            payback_days = None

        high_drag = bool(annualized_drag_pct >= HIGH_DRAG_PCT)

        score = self._score(premium_pct, annualized_drag_pct)
        classification = self._classify(premium_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(classification, premium_pct, is_premium, high_drag)

        return {
            "token": token,
            "nav_per_share": round(nav, 8),
            "market_price_per_share": round(market, 8),
            "expected_apr_pct": round(expected_apr, 4),
            "convergence_horizon_days": round(horizon, 4),
            "premium_pct": round(premium_pct, 4),
            "is_premium": is_premium,
            "annualized_drag_pct": round(annualized_drag_pct, 4),
            "payback_days": payback_days,
            "high_drag": high_drag,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        premium_pct: float,
        annualized_drag_pct: float,
    ) -> float:
        """
        0–100, HIGHER = cheaper entry (at/below NAV). Components:
          premium (70) — full 70 when premium_pct<=0 (at/below NAV); otherwise
            70 × (1 - frac) where frac = clamp(premium_pct/PREMIUM_SCORE_CEILING,
            0, 1); decays linearly to 0 at/above the ceiling.
          drag (30) — full 30 when there is no drag; otherwise reduced by the
            drag severity drag_frac = clamp(annualized_drag_pct/DRAG_SCORE_CEILING,
            0, 1): 30 × (1 - drag_frac).
        A non-premium (premium_pct<=0) entry → 100.
        """
        if premium_pct <= 0:
            return 100.0

        frac = _clamp(premium_pct / PREMIUM_SCORE_CEILING, 0.0, 1.0)
        premium_comp = 70.0 * (1.0 - frac)

        drag_frac = _clamp(
            annualized_drag_pct / DRAG_SCORE_CEILING, 0.0, 1.0)
        drag_comp = 30.0 * (1.0 - drag_frac)

        total = premium_comp + drag_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, premium_pct: float) -> str:
        if premium_pct <= 0:
            return "AT_OR_BELOW_NAV"
        if premium_pct <= SLIGHT_PREMIUM_PCT:
            return "SLIGHT_PREMIUM"
        if premium_pct <= MODERATE_PREMIUM_PCT:
            return "MODERATE_PREMIUM"
        if premium_pct <= HIGH_PREMIUM_PCT:
            return "HIGH_PREMIUM"
        return "EXTREME_PREMIUM"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "AT_OR_BELOW_NAV":
            return "ENTER_AT_FAIR_VALUE"
        if classification == "SLIGHT_PREMIUM":
            return "ENTER_MINOR_PREMIUM"
        if classification == "MODERATE_PREMIUM":
            return "ENTER_WITH_CAUTION"
        if classification == "HIGH_PREMIUM":
            return "WAIT_FOR_CONVERGENCE"
        # EXTREME_PREMIUM
        return "AVOID_PREMIUM"

    def _flags(
        self,
        classification: str,
        premium_pct: float,
        is_premium: bool,
        high_drag: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "AT_OR_BELOW_NAV":
            flags.append("AT_OR_BELOW_NAV")
        if classification == "SLIGHT_PREMIUM":
            flags.append("SLIGHT_PREMIUM")
        if classification == "MODERATE_PREMIUM":
            flags.append("MODERATE_PREMIUM")
        if classification == "HIGH_PREMIUM":
            flags.append("HIGH_PREMIUM")
        if classification == "EXTREME_PREMIUM":
            flags.append("EXTREME_PREMIUM")
        if is_premium:
            flags.append("PREMIUM")
        if premium_pct < 0:
            flags.append("DISCOUNT")
        if high_drag:
            flags.append("HIGH_ANNUALIZED_DRAG")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "nav_per_share": 0.0,
            "market_price_per_share": 0.0,
            "expected_apr_pct": 0.0,
            "convergence_horizon_days": round(
                DEFAULT_CONVERGENCE_HORIZON_DAYS, 4),
            "premium_pct": None,
            "is_premium": False,
            "annualized_drag_pct": None,
            "payback_days": None,
            "high_drag": False,
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
                "cheapest_entry_vault": None,
                "most_premium_vault": None,
                "avg_score": 0.0,
                "extreme_premium_count": 0,
                "position_count": len(results),
            }
        # Higher score = cheaper entry → highest score is the cheapest entry.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        extreme = sum(
            1 for r in results
            if r["classification"] == "EXTREME_PREMIUM")
        return {
            "cheapest_entry_vault": by_score[-1]["token"],
            "most_premium_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "extreme_premium_count": extreme,
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
            "vault": "USDC-Vault-Discount",
            "nav_per_share": 1.00,
            "market_price_per_share": 0.98,
            "expected_apr_pct": 8.0,
            "convergence_horizon_days": 30.0,
        },
        {
            "vault": "ETH-Vault-Slight",
            "nav_per_share": 1.00,
            "market_price_per_share": 1.005,
            "expected_apr_pct": 10.0,
            "convergence_horizon_days": 30.0,
        },
        {
            "vault": "ARB-Vault-Moderate",
            "nav_per_share": 1.00,
            "market_price_per_share": 1.02,
            "expected_apr_pct": 12.0,
            "convergence_horizon_days": 30.0,
        },
        {
            "vault": "CRV-Vault-High",
            "nav_per_share": 1.00,
            "market_price_per_share": 1.05,
            "expected_apr_pct": 14.0,
            "convergence_horizon_days": 30.0,
        },
        {
            "vault": "CVX-Vault-Extreme",
            "nav_per_share": 1.00,
            "market_price_per_share": 1.15,
            "expected_apr_pct": 20.0,
            "convergence_horizon_days": 14.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "nav_per_share": 0.0,
            "market_price_per_share": 0.0,
            "expected_apr_pct": 0.0,
            "convergence_horizon_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1182 Vault Share Price Premium Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultSharePricePremiumAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
