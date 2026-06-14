"""
MP-934 DeFiVolatilitySurfaceAnalyzer
--------------------------------------
Analyses implied volatility surface for DeFi options.

For each option it computes:
  - moneyness:              ITM | ATM | OTM
  - bid_ask_spread_pct:     (ask - bid) / mid * 100
  - vol_premium_pct:        (IV - historical_vol) / historical_vol * 100
  - time_value_usd:         option_mid - intrinsic_value_usd
  - intrinsic_value_usd:    max(0, S-K) call / max(0, K-S) put

Summary surfaces:
  - vol_smile:              {strike: avg_iv} sorted by strike
  - vol_term_structure:     {expiry_days: avg_iv} sorted by expiry
  - put_call_skew:          {strike: put_avg_iv - call_avg_iv}

Vol label (per option): VERY_LOW (<20%) / LOW (<40%) / NORMAL (<80%) / HIGH (<150%) / EXTREME (>=150%)

Flags per option:
  WIDE_SPREAD     bid_ask_spread_pct > 10%
  DEEP_ITM        ITM and |S-K|/K > 20%
  EXPIRING_SOON   expiry_days < 3
  HIGH_GAMMA_RISK gamma > gamma_threshold (default 0.1)
  VOL_PREMIUM     IV > 2x historical_vol

Aggregates:
  highest_iv_option, lowest_iv_option, total_open_interest_usd,
  average_iv, put_call_ratio

Ring-buffer log → data/vol_surface_log.json (cap 100, atomic write).
Advisory / read-only. Pure stdlib.
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
    os.path.dirname(__file__), "..", "..", "data", "vol_surface_log.json"
)
_LOG_CAP = 100

_ATM_THRESHOLD_PCT = 0.01   # within 1% of strike → ATM
_DEEP_ITM_THRESHOLD_PCT = 0.20  # |S-K|/K > 20% → DEEP_ITM flag
_WIDE_SPREAD_THRESHOLD = 10.0   # bid-ask spread % > 10
_EXPIRING_SOON_DAYS = 3
_DEFAULT_GAMMA_THRESHOLD = 0.10
_VOL_PREMIUM_MULTIPLIER = 2.0   # IV > 2x historical → VOL_PREMIUM flag
_DEFAULT_HISTORICAL_VOL_PCT = 60.0  # fallback if not in config

# Vol label thresholds
_LABEL_EXTREME = 150.0
_LABEL_HIGH = 80.0
_LABEL_NORMAL = 40.0
_LABEL_LOW = 20.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


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


def _vol_label(iv_pct: float) -> str:
    if iv_pct >= _LABEL_EXTREME:
        return "EXTREME"
    if iv_pct >= _LABEL_HIGH:
        return "HIGH"
    if iv_pct >= _LABEL_NORMAL:
        return "NORMAL"
    if iv_pct >= _LABEL_LOW:
        return "LOW"
    return "VERY_LOW"


def _moneyness(option_type: str, strike: float, current_price: float) -> str:
    """Return ITM / ATM / OTM for a single option."""
    if strike <= 0.0 or current_price <= 0.0:
        return "ATM"
    rel = abs(current_price - strike) / strike
    if rel <= _ATM_THRESHOLD_PCT:
        return "ATM"
    otype = str(option_type).lower()
    if otype == "call":
        return "ITM" if current_price > strike else "OTM"
    # put
    return "ITM" if current_price < strike else "OTM"


def _intrinsic_value(option_type: str, strike: float, current_price: float) -> float:
    otype = str(option_type).lower()
    if otype == "call":
        return max(0.0, current_price - strike)
    return max(0.0, strike - current_price)


def _bid_ask_spread_pct(bid: float, ask: float) -> float:
    """Spread as % of mid price."""
    mid = (bid + ask) / 2.0
    if mid <= 0.0:
        return 0.0
    return ((ask - bid) / mid) * 100.0


def _vol_premium_pct(iv_pct: float, hist_vol_pct: float) -> float:
    if hist_vol_pct <= 0.0:
        return 0.0
    return ((iv_pct - hist_vol_pct) / hist_vol_pct) * 100.0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiVolatilitySurfaceAnalyzer:
    """
    Analyses implied volatility surface for a batch of DeFi options.

    Usage::

        analyzer = DeFiVolatilitySurfaceAnalyzer()
        result = analyzer.analyze(options, config)

    config keys (all optional):
        historical_vol_pct   float   default 60.0 — baseline historical vol
        gamma_threshold      float   default 0.10 — HIGH_GAMMA_RISK trigger
        log_path             str     override log file location
        write_log            bool    default True
    """

    # ------------------------------------------------------------------
    # Per-option analysis
    # ------------------------------------------------------------------

    def _analyze_option(self, opt: dict, hist_vol: float, gamma_threshold: float) -> dict:
        protocol        = str(opt.get("protocol", "unknown"))
        underlying      = str(opt.get("underlying", "unknown"))
        strike          = float(opt.get("strike_price_usd", 0.0))
        current         = float(opt.get("current_price_usd", 0.0))
        expiry_days     = float(opt.get("expiry_days", 0.0))
        option_type     = str(opt.get("option_type", "call")).lower()
        iv_pct          = float(opt.get("implied_vol_pct", 0.0))
        bid             = float(opt.get("bid_usd", 0.0))
        ask             = float(opt.get("ask_usd", 0.0))
        delta           = float(opt.get("delta", 0.0))
        gamma           = float(opt.get("gamma", 0.0))
        theta_daily     = float(opt.get("theta_daily_usd", 0.0))
        oi_usd          = float(opt.get("open_interest_usd", 0.0))

        # Derived fields
        money = _moneyness(option_type, strike, current)
        intrinsic = _intrinsic_value(option_type, strike, current)
        mid_price = (bid + ask) / 2.0
        time_value = max(0.0, mid_price - intrinsic)
        spread_pct = _bid_ask_spread_pct(bid, ask)
        vprem = _vol_premium_pct(iv_pct, hist_vol)
        label = _vol_label(iv_pct)

        # Flags
        flags: list[str] = []
        if spread_pct > _WIDE_SPREAD_THRESHOLD:
            flags.append("WIDE_SPREAD")
        if money == "ITM" and strike > 0.0 and abs(current - strike) / strike > _DEEP_ITM_THRESHOLD_PCT:
            flags.append("DEEP_ITM")
        if expiry_days < _EXPIRING_SOON_DAYS:
            flags.append("EXPIRING_SOON")
        if gamma > gamma_threshold:
            flags.append("HIGH_GAMMA_RISK")
        if hist_vol > 0.0 and iv_pct > _VOL_PREMIUM_MULTIPLIER * hist_vol:
            flags.append("VOL_PREMIUM")

        return {
            "protocol":             protocol,
            "underlying":           underlying,
            "strike_price_usd":     strike,
            "current_price_usd":    current,
            "expiry_days":          expiry_days,
            "option_type":          option_type,
            "implied_vol_pct":      round(iv_pct, 4),
            "bid_usd":              bid,
            "ask_usd":              ask,
            "delta":                delta,
            "gamma":                gamma,
            "theta_daily_usd":      theta_daily,
            "open_interest_usd":    oi_usd,
            "moneyness":            money,
            "bid_ask_spread_pct":   round(spread_pct, 4),
            "vol_premium_pct":      round(vprem, 4),
            "intrinsic_value_usd":  round(intrinsic, 6),
            "time_value_usd":       round(time_value, 6),
            "vol_label":            label,
            "flags":                flags,
        }

    # ------------------------------------------------------------------
    # Surface summary builders
    # ------------------------------------------------------------------

    def _build_vol_smile(self, results: list[dict]) -> dict:
        """Strike → average IV across options at that strike."""
        buckets: dict[float, list[float]] = {}
        for r in results:
            s = r["strike_price_usd"]
            buckets.setdefault(s, []).append(r["implied_vol_pct"])
        return {
            str(k): round(sum(v) / len(v), 4)
            for k, v in sorted(buckets.items())
        }

    def _build_vol_term_structure(self, results: list[dict]) -> dict:
        """Expiry-days → average IV across options at that expiry."""
        buckets: dict[float, list[float]] = {}
        for r in results:
            e = r["expiry_days"]
            buckets.setdefault(e, []).append(r["implied_vol_pct"])
        return {
            str(k): round(sum(v) / len(v), 4)
            for k, v in sorted(buckets.items())
        }

    def _build_put_call_skew(self, results: list[dict]) -> dict:
        """Strike → (avg_put_IV - avg_call_IV). Skips strikes with only one type."""
        put_ivs: dict[float, list[float]] = {}
        call_ivs: dict[float, list[float]] = {}
        for r in results:
            s = r["strike_price_usd"]
            if r["option_type"] == "put":
                put_ivs.setdefault(s, []).append(r["implied_vol_pct"])
            else:
                call_ivs.setdefault(s, []).append(r["implied_vol_pct"])
        skew: dict[str, float] = {}
        all_strikes = set(put_ivs) | set(call_ivs)
        for s in sorted(all_strikes):
            if s in put_ivs and s in call_ivs:
                p_avg = sum(put_ivs[s]) / len(put_ivs[s])
                c_avg = sum(call_ivs[s]) / len(call_ivs[s])
                skew[str(s)] = round(p_avg - c_avg, 4)
        return skew

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _build_aggregates(self, results: list[dict]) -> dict:
        if not results:
            return {
                "highest_iv_option":        None,
                "lowest_iv_option":         None,
                "total_open_interest_usd":  0.0,
                "average_iv":               0.0,
                "put_call_ratio":           0.0,
            }

        ivs = [r["implied_vol_pct"] for r in results]
        max_idx = ivs.index(max(ivs))
        min_idx = ivs.index(min(ivs))
        highest_iv = {
            "protocol":   results[max_idx]["protocol"],
            "underlying": results[max_idx]["underlying"],
            "iv_pct":     results[max_idx]["implied_vol_pct"],
        }
        lowest_iv = {
            "protocol":   results[min_idx]["protocol"],
            "underlying": results[min_idx]["underlying"],
            "iv_pct":     results[min_idx]["implied_vol_pct"],
        }
        total_oi = sum(r["open_interest_usd"] for r in results)
        avg_iv = sum(ivs) / len(ivs)
        call_count = sum(1 for r in results if r["option_type"] == "call")
        put_count  = sum(1 for r in results if r["option_type"] == "put")
        put_call_ratio = (put_count / call_count) if call_count > 0 else 0.0

        return {
            "highest_iv_option":        highest_iv,
            "lowest_iv_option":         lowest_iv,
            "total_open_interest_usd":  round(total_oi, 2),
            "average_iv":               round(avg_iv, 4),
            "put_call_ratio":           round(put_call_ratio, 4),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, options: list, config: dict | None = None) -> dict:
        """
        Analyse implied volatility surface for a list of DeFi options.

        Parameters
        ----------
        options : list[dict]
            Each dict describes one option (see module docstring).
        config : dict, optional
            Optional overrides (see class docstring).

        Returns
        -------
        dict with keys:
            results          list[dict]   per-option analysis
            summary          dict         vol_smile, vol_term_structure, put_call_skew
            aggregates       dict         portfolio-level aggregates
            timestamp        float        unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(options, list):
            raise TypeError("options must be a list")

        hist_vol       = float(config.get("historical_vol_pct", _DEFAULT_HISTORICAL_VOL_PCT))
        gamma_thresh   = float(config.get("gamma_threshold", _DEFAULT_GAMMA_THRESHOLD))

        results = [self._analyze_option(opt, hist_vol, gamma_thresh) for opt in options]

        summary = {
            "vol_smile":          self._build_vol_smile(results),
            "vol_term_structure": self._build_vol_term_structure(results),
            "put_call_skew":      self._build_put_call_skew(results),
        }

        aggregates = self._build_aggregates(results)
        ts = time.time()

        output: dict[str, Any] = {
            "results":    results,
            "summary":    summary,
            "aggregates": aggregates,
            "timestamp":  ts,
        }

        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp":     ts,
                        "option_count":  len(results),
                        "aggregates":    aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output
