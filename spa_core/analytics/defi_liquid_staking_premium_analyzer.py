"""
MP-933 DeFiLiquidStakingPremiumAnalyzer
=======================================
Analyses the secondary-market price of liquid-staking / liquid-restaking
tokens (LSTs/LRTs such as stETH, rETH, weETH, ezETH…) relative to their
underlying NAV (redemption value), to spot discount-buying opportunities and
premium/depeg risk.

When an LST trades **below NAV** a buyer who can redeem at NAV captures an
extra implied yield on top of the native staking APY; when it trades **above
NAV** the buyer overpays. Redemption speed and availability gate whether a
discount is actually capturable.

For each token it computes:
  premium_discount_pct     (market_price - nav) / nav × 100   (neg = discount)
  discount_capture_apy_pct  annualised gain from buy@price → redeem@NAV
  effective_buy_apy_pct     base_staking_apy + discount_capture_apy
  buy_score                 0–100 attractiveness for a buyer (higher = better)

Classification (from premium/discount):
  DEEP_DISCOUNT | DISCOUNT | FAIR | PREMIUM | OVERPRICED

Flags:
  INSUFFICIENT_DATA      price or nav <= 0
  DEPEG_RISK             |premium_discount_pct| > 3 %
  DEEP_DISCOUNT          premium_discount_pct < -2 %
  TRADING_PREMIUM        premium_discount_pct > 1 %
  SLOW_REDEMPTION        redemption_days > 14
  NO_REDEMPTION          can_redeem is False
  ARBITRAGE_OPPORTUNITY  discount < -1 % AND can_redeem AND redemption_days <= 7

Input token keys:
  name / symbol         str
  market_price_usd      float
  nav_usd               float   fair/redemption value per token
  base_staking_apy_pct  float   native staking yield (default 0)
  redemption_days       float   days to redeem at NAV (default 7)
  can_redeem            bool    redemption available (default True)
  tvl_usd               float   optional

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "liquid_staking_premium_log.json"
)
_LOG_CAP = 100

_DAYS_PER_YEAR = 365.0
_DEFAULT_REDEMPTION_DAYS = 7.0

# Classification thresholds on premium_discount_pct
_DEEP_DISCOUNT_PCT = -3.0
_DISCOUNT_PCT = -0.5
_FAIR_UPPER_PCT = 0.5
_PREMIUM_UPPER_PCT = 2.0

# Flag thresholds
_DEPEG_ABS_PCT = 3.0
_DEEP_DISCOUNT_FLAG_PCT = -2.0
_PREMIUM_FLAG_PCT = 1.0
_SLOW_REDEMPTION_DAYS = 14.0
_ARB_DISCOUNT_PCT = -1.0
_ARB_MAX_REDEMPTION_DAYS = 7.0

# Buy-score grade thresholds
_GRADE_A = 85.0
_GRADE_B = 70.0
_GRADE_C = 55.0
_GRADE_D = 40.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _grade_from_score(score: float) -> str:
    if score >= _GRADE_A:
        return "A"
    if score >= _GRADE_B:
        return "B"
    if score >= _GRADE_C:
        return "C"
    if score >= _GRADE_D:
        return "D"
    return "F"


def _classify(premium_discount_pct: float) -> str:
    if premium_discount_pct <= _DEEP_DISCOUNT_PCT:
        return "DEEP_DISCOUNT"
    if premium_discount_pct <= _DISCOUNT_PCT:
        return "DISCOUNT"
    if premium_discount_pct < _FAIR_UPPER_PCT:
        return "FAIR"
    if premium_discount_pct < _PREMIUM_UPPER_PCT:
        return "PREMIUM"
    return "OVERPRICED"


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiLiquidStakingPremiumAnalyzer:
    """
    Analyses LST/LRT market price vs NAV (premium/discount) and the buyer's
    discount-capture opportunity.

    Usage::

        analyzer = DeFiLiquidStakingPremiumAnalyzer()
        result = analyzer.analyze(tokens, config)

    config keys (all optional):
        log_path   str   override default log file location
        write_log  bool  default True; set False to skip disk write
    """

    # ------------------------------------------------------------------
    # Per-token calculations
    # ------------------------------------------------------------------

    def _premium_discount_pct(self, price: float, nav: float) -> float:
        """(price - nav) / nav × 100. Guarded against nav <= 0."""
        if nav <= 0.0:
            return 0.0
        return round((price - nav) / nav * 100.0, 6)

    def _discount_capture_apy_pct(
        self,
        price: float,
        nav: float,
        redemption_days: float,
        can_redeem: bool,
    ) -> float:
        """
        Annualised gain from buying at market price and redeeming at NAV.

        gain_per_redemption = nav/price - 1   (positive for a discount)
        annualised          = gain × (365 / redemption_days)

        Only realisable when redemption is available; returns 0 otherwise.
        """
        if not can_redeem:
            return 0.0
        if price <= 0.0 or nav <= 0.0:
            return 0.0
        days = redemption_days if redemption_days > 0.0 else _DEFAULT_REDEMPTION_DAYS
        gain = (nav / price) - 1.0
        annualised = gain * (_DAYS_PER_YEAR / days)
        return round(annualised * 100.0, 6)

    def _buy_score(
        self,
        premium_discount_pct: float,
        redemption_days: float,
        can_redeem: bool,
    ) -> float:
        """
        0–100 attractiveness for a buyer. Discount raises the score; premium
        lowers it. Redemption frictions adjust how capturable a discount is.
        """
        # Base: each 1 % of discount ≈ +10 points around a neutral 50.
        score = 50.0 - premium_discount_pct * 10.0

        if not can_redeem:
            score -= 15.0
        if redemption_days > _SLOW_REDEMPTION_DAYS:
            score -= 10.0
        elif redemption_days <= 3.0:
            score += 5.0

        return round(_clamp(score, 0.0, 100.0), 4)

    def _compute_flags(
        self,
        premium_discount_pct: float,
        redemption_days: float,
        can_redeem: bool,
        valid: bool,
    ) -> list:
        """Return list of applicable flag strings."""
        flags: list[str] = []

        if not valid:
            flags.append("INSUFFICIENT_DATA")
            return flags

        if abs(premium_discount_pct) > _DEPEG_ABS_PCT:
            flags.append("DEPEG_RISK")

        if premium_discount_pct < _DEEP_DISCOUNT_FLAG_PCT:
            flags.append("DEEP_DISCOUNT")

        if premium_discount_pct > _PREMIUM_FLAG_PCT:
            flags.append("TRADING_PREMIUM")

        if redemption_days > _SLOW_REDEMPTION_DAYS:
            flags.append("SLOW_REDEMPTION")

        if not can_redeem:
            flags.append("NO_REDEMPTION")

        if (
            premium_discount_pct < _ARB_DISCOUNT_PCT
            and can_redeem
            and redemption_days <= _ARB_MAX_REDEMPTION_DAYS
        ):
            flags.append("ARBITRAGE_OPPORTUNITY")

        return flags

    # ------------------------------------------------------------------
    # Single-token analysis
    # ------------------------------------------------------------------

    def _analyze_token(self, token: dict) -> dict:
        """Analyse one LST/LRT and return result dict."""
        name = token.get("name", token.get("symbol", "unknown"))
        price = float(token.get("market_price_usd", 0.0))
        nav = float(token.get("nav_usd", 0.0))
        base_apy = float(token.get("base_staking_apy_pct", 0.0))
        redemption_days = float(
            token.get("redemption_days", _DEFAULT_REDEMPTION_DAYS)
        )
        can_redeem = bool(token.get("can_redeem", True))

        valid = price > 0.0 and nav > 0.0

        if valid:
            premium_discount = self._premium_discount_pct(price, nav)
            capture_apy = self._discount_capture_apy_pct(
                price, nav, redemption_days, can_redeem
            )
            effective_buy_apy = round(base_apy + capture_apy, 6)
            buy_score = self._buy_score(
                premium_discount, redemption_days, can_redeem
            )
            classification = _classify(premium_discount)
            grade = _grade_from_score(buy_score)
        else:
            premium_discount = 0.0
            capture_apy = 0.0
            effective_buy_apy = round(base_apy, 6)
            buy_score = 0.0
            classification = "FAIR"
            grade = "F"

        flags = self._compute_flags(
            premium_discount, redemption_days, can_redeem, valid
        )

        return {
            "name": name,
            "market_price_usd": price,
            "nav_usd": nav,
            "premium_discount_pct": premium_discount,
            "base_staking_apy_pct": base_apy,
            "discount_capture_apy_pct": capture_apy,
            "effective_buy_apy_pct": effective_buy_apy,
            "redemption_days": redemption_days,
            "can_redeem": can_redeem,
            "buy_score": buy_score,
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, tokens: list, config: dict | None = None) -> dict:
        """
        Analyse a list of liquid-staking / restaking tokens.

        Parameters
        ----------
        tokens : list[dict]
            Each dict describes one LST/LRT (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path  str   custom log file path
                write_log bool  set False to skip log write (default True)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-token analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(tokens, list):
            raise TypeError("tokens must be a list")

        results = [self._analyze_token(t) for t in tokens]

        # ── Aggregates ───────────────────────────────────────────────
        if results:
            scores = [r["buy_score"] for r in results]
            premiums = [r["premium_discount_pct"] for r in results]
            eff_apys = [r["effective_buy_apy_pct"] for r in results]

            best_idx = scores.index(max(scores))
            worst_idx = scores.index(min(scores))

            best_buy_opportunity = results[best_idx]["name"]
            most_overpriced = results[worst_idx]["name"]
            avg_premium = sum(premiums) / len(premiums)
            avg_eff_apy = sum(eff_apys) / len(eff_apys)
            deep_discount_count = sum(
                1 for r in results if r["classification"] == "DEEP_DISCOUNT"
            )
            arbitrage_count = sum(
                1 for r in results if "ARBITRAGE_OPPORTUNITY" in r["flags"]
            )
        else:
            best_buy_opportunity = None
            most_overpriced = None
            avg_premium = 0.0
            avg_eff_apy = 0.0
            deep_discount_count = 0
            arbitrage_count = 0

        aggregates = {
            "best_buy_opportunity": best_buy_opportunity,
            "most_overpriced": most_overpriced,
            "average_premium_discount_pct": round(avg_premium, 6),
            "average_effective_buy_apy_pct": round(avg_eff_apy, 6),
            "deep_discount_count": deep_discount_count,
            "arbitrage_opportunity_count": arbitrage_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # ── Ring-buffer log ──────────────────────────────────────────
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "token_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output
