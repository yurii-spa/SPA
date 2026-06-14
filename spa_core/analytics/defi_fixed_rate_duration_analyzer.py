"""
MP-949 DeFiFixedRateDurationAnalyzer
====================================
Analyses fixed-rate yield instruments / zero-coupon discount tokens such as
Pendle Principal Tokens (PT), Notional fCash and Yield Protocol fyTokens.
Each trades at a discount to a known redemption (face) value and matures at a
fixed date, so it behaves like a zero-coupon bond: locking in a fixed
yield-to-maturity in exchange for interest-rate (duration) risk.

For each instrument it computes yield-to-maturity, Macaulay & modified
duration, convexity, the approximate price sensitivity to a rate move, and the
yield pickup versus the current variable/spot rate.

Math (zero-coupon discount instrument)
--------------------------------------
    t_years = days_to_maturity / 365

    ytm (annualized, compounding):
        ytm = ((face / price) ** (1 / t_years) - 1) * 100

    Macaulay duration of a zero-coupon equals its time to maturity:
        macaulay_duration = t_years   (years)

    modified_duration = macaulay_duration / (1 + ytm_decimal)

    convexity = t_years * (t_years + 1) / (1 + ytm_decimal) ** 2

    price_sensitivity (approx % price change for a +1pp / +100bps rate move):
        price_sensitivity_pct_per_1pct = -modified_duration

    yield_pickup_pct = ytm - spot_apy
        (positive => the fixed rate locks in a better yield than the spot)

All divisions are guarded (price <= 0, face <= 0, t_years <= 0 -> invalid).

Classification by days_to_maturity:
    SHORT     <= 30
    MEDIUM    <= 180
    LONG      <= 365
    VERY_LONG  > 365

Flags:
  INSUFFICIENT_DATA      price <= 0 or face <= 0 or days_to_maturity <= 0
  DISCOUNT_TO_FACE       price < face  (normal; informational)
  PREMIUM_TO_FACE        price > face  (unusual; warn)
  HIGH_DURATION_RISK     macaulay_duration > 1.0 year
  NEGATIVE_YIELD_PICKUP  yield_pickup_pct < 0
  DEEP_DISCOUNT          price < 0.9 * face

Input instrument keys:
  name / symbol       str
  price_usd           float   current market price of the discount token / PT
  face_value_usd      float   redemption value at maturity (default 1.0)
  days_to_maturity    float   days remaining until maturity (> 0)
  spot_apy_pct        float   current variable/spot APY for comparison (default 0)

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "fixed_rate_duration_log.json"
)
_LOG_CAP = 100

_DAYS_PER_YEAR = 365.0
_DEFAULT_FACE_VALUE = 1.0

# Classification thresholds on days_to_maturity
_SHORT_DAYS = 30.0
_MEDIUM_DAYS = 180.0
_LONG_DAYS = 365.0

# Flag thresholds
_HIGH_DURATION_YEARS = 1.0
_DEEP_DISCOUNT_FRACTION = 0.9

# Score grade thresholds
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


def _classify(days_to_maturity: float) -> str:
    if days_to_maturity <= _SHORT_DAYS:
        return "SHORT"
    if days_to_maturity <= _MEDIUM_DAYS:
        return "MEDIUM"
    if days_to_maturity <= _LONG_DAYS:
        return "LONG"
    return "VERY_LONG"


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
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiFixedRateDurationAnalyzer:
    """
    Analyses fixed-rate zero-coupon yield instruments (Pendle PT, Notional
    fCash, fyTokens) for yield-to-maturity, duration, convexity and
    rate-sensitivity.

    Usage::

        analyzer = DeFiFixedRateDurationAnalyzer()
        result = analyzer.analyze(instruments, config)

    config keys (all optional):
        log_path   str   override default log file location
        write_log  bool  default True; set False to skip disk write
    """

    # ------------------------------------------------------------------
    # Per-instrument calculations
    # ------------------------------------------------------------------

    def _ytm_pct(self, price: float, face: float, t_years: float) -> float:
        """Annualized yield-to-maturity of a zero-coupon discount token."""
        if price <= 0.0 or face <= 0.0 or t_years <= 0.0:
            return 0.0
        ytm = (face / price) ** (1.0 / t_years) - 1.0
        return round(ytm * 100.0, 6)

    def _score(
        self,
        ytm_pct: float,
        yield_pickup_pct: float,
        macaulay_duration: float,
    ) -> float:
        """
        0-100 (higher = better). Rewards a higher YTM and positive yield
        pickup over spot, penalises long duration (rate risk).
        """
        # Base 40, each 1pp of YTM ~ +3 points.
        score = 40.0 + ytm_pct * 3.0

        # Yield pickup bonus / penalty (each 1pp ~ +/- 4 points).
        score += yield_pickup_pct * 4.0

        # Duration (rate-risk) penalty: each year ~ -8 points.
        score -= macaulay_duration * 8.0

        return round(_clamp(score, 0.0, 100.0), 4)

    def _compute_flags(
        self,
        price: float,
        face: float,
        macaulay_duration: float,
        yield_pickup_pct: float,
        valid: bool,
    ) -> list:
        """Return list of applicable flag strings."""
        flags: list[str] = []

        if not valid:
            flags.append("INSUFFICIENT_DATA")
            return flags

        if price < face:
            flags.append("DISCOUNT_TO_FACE")

        if price > face:
            flags.append("PREMIUM_TO_FACE")

        if macaulay_duration > _HIGH_DURATION_YEARS:
            flags.append("HIGH_DURATION_RISK")

        if yield_pickup_pct < 0.0:
            flags.append("NEGATIVE_YIELD_PICKUP")

        if price < _DEEP_DISCOUNT_FRACTION * face:
            flags.append("DEEP_DISCOUNT")

        return flags

    # ------------------------------------------------------------------
    # Single-instrument analysis
    # ------------------------------------------------------------------

    def _analyze_instrument(self, instrument: dict) -> dict:
        """Analyse one fixed-rate instrument and return result dict."""
        name = instrument.get("name", instrument.get("symbol", "unknown"))
        price = float(instrument.get("price_usd", 0.0))
        face = float(instrument.get("face_value_usd", _DEFAULT_FACE_VALUE))
        days = float(instrument.get("days_to_maturity", 0.0))
        spot_apy = float(instrument.get("spot_apy_pct", 0.0))

        valid = price > 0.0 and face > 0.0 and days > 0.0

        if valid:
            t_years = days / _DAYS_PER_YEAR
            ytm_pct = self._ytm_pct(price, face, t_years)
            ytm_decimal = ytm_pct / 100.0

            macaulay_duration = round(t_years, 6)
            denom = 1.0 + ytm_decimal
            if denom <= 0.0:
                modified_duration = 0.0
                convexity = 0.0
            else:
                modified_duration = round(t_years / denom, 6)
                convexity = round(t_years * (t_years + 1.0) / (denom ** 2), 6)

            price_sensitivity_pct_per_1pct = round(-modified_duration, 6)
            yield_pickup_pct = round(ytm_pct - spot_apy, 6)

            classification = _classify(days)
            score = self._score(ytm_pct, yield_pickup_pct, macaulay_duration)
            grade = _grade_from_score(score)
        else:
            t_years = 0.0
            ytm_pct = 0.0
            macaulay_duration = 0.0
            modified_duration = 0.0
            convexity = 0.0
            price_sensitivity_pct_per_1pct = 0.0
            yield_pickup_pct = 0.0
            classification = "SHORT"
            score = 0.0
            grade = "F"

        flags = self._compute_flags(
            price, face, macaulay_duration, yield_pickup_pct, valid
        )

        return {
            "name": name,
            "price_usd": price,
            "face_value_usd": face,
            "days_to_maturity": days,
            "t_years": round(t_years, 6),
            "spot_apy_pct": spot_apy,
            "ytm_pct": ytm_pct,
            "macaulay_duration": macaulay_duration,
            "modified_duration": modified_duration,
            "convexity": convexity,
            "price_sensitivity_pct_per_1pct": price_sensitivity_pct_per_1pct,
            "yield_pickup_pct": yield_pickup_pct,
            "classification": classification,
            "score": score,
            "grade": grade,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, instruments: list, config: dict | None = None) -> dict:
        """
        Analyse a list of fixed-rate / zero-coupon discount instruments.

        Parameters
        ----------
        instruments : list[dict]
            Each dict describes one instrument (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path  str   custom log file path
                write_log bool  set False to skip log write (default True)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-instrument analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(instruments, list):
            raise TypeError("instruments must be a list")

        results = [self._analyze_instrument(i) for i in instruments]

        # -- Aggregates --------------------------------------------------
        if results:
            scores = [r["score"] for r in results]
            durations = [r["macaulay_duration"] for r in results]
            ytms = [r["ytm_pct"] for r in results]
            mod_durations = [r["modified_duration"] for r in results]
            pickups = [r["yield_pickup_pct"] for r in results]

            best_idx = scores.index(max(scores))
            longest_idx = durations.index(max(durations))
            highest_pickup_idx = pickups.index(max(pickups))

            best_fixed_rate = results[best_idx]["name"]
            longest_duration_instrument = results[longest_idx]["name"]
            average_ytm_pct = sum(ytms) / len(ytms)
            average_modified_duration = sum(mod_durations) / len(mod_durations)
            highest_yield_pickup_instrument = results[highest_pickup_idx]["name"]
            negative_pickup_count = sum(
                1 for r in results if "NEGATIVE_YIELD_PICKUP" in r["flags"]
            )
        else:
            best_fixed_rate = None
            longest_duration_instrument = None
            average_ytm_pct = 0.0
            average_modified_duration = 0.0
            highest_yield_pickup_instrument = None
            negative_pickup_count = 0

        aggregates = {
            "best_fixed_rate": best_fixed_rate,
            "longest_duration_instrument": longest_duration_instrument,
            "average_ytm_pct": round(average_ytm_pct, 6),
            "average_modified_duration": round(average_modified_duration, 6),
            "highest_yield_pickup_instrument": highest_yield_pickup_instrument,
            "negative_pickup_count": negative_pickup_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # -- Ring-buffer log --------------------------------------------
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "item_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output
