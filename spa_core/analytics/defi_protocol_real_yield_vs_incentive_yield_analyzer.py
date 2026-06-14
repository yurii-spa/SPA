"""
MP-1064 DeFiProtocolRealYieldVsIncentiveYieldAnalyzer
------------------------------------------------------
Decomposes a DeFi protocol's total APY into real (fee-based) yield and
incentive (token-emission) yield, scores emission sustainability, and
classifies yield quality.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "real_yield_vs_incentive_yield_log.json"
)
_LOG_CAP = 100

# yield_quality_label thresholds (real_yield_ratio)
_PURE_REAL_YIELD_THRESHOLD    = 0.90
_PREDOMINANTLY_REAL_THRESHOLD = 0.60
_BALANCED_THRESHOLD           = 0.40
_INCENTIVE_HEAVY_THRESHOLD    = 0.10
# ratio < _INCENTIVE_HEAVY_THRESHOLD → PURE_PONZI_YIELD

# incentive_sustainability_score components
_VEST_MAX_DAYS      = 365    # days of vesting at which vest pts are maxed
_INFLATION_HIGH_PCT = 50.0   # annual token inflation ≥ this → 0 inflation pts
_DAILY_DILUTION_CAP = 0.005  # token_incentive_per_day / market_cap ≥ this → 0 dilution pts


# ---------------------------------------------------------------------------
# Internal helpers (module-level for direct unit testing)
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
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


def _real_yield_pct(fee_revenue_usd_per_day: float, tvl_usd: float) -> float:
    """Annualised real (fee-based) yield as % of TVL.

    real_yield_pct = fee_revenue_usd_per_day * 365 / tvl_usd * 100
    Returns 0.0 when tvl_usd <= 0.
    """
    if tvl_usd <= 0.0:
        return 0.0
    return round(fee_revenue_usd_per_day * 365.0 / tvl_usd * 100.0, 6)


def _incentive_yield_pct(token_incentive_usd_per_day: float, tvl_usd: float) -> float:
    """Annualised incentive (token-emission) yield as % of TVL.

    incentive_yield_pct = token_incentive_usd_per_day * 365 / tvl_usd * 100
    Returns 0.0 when tvl_usd <= 0.
    """
    if tvl_usd <= 0.0:
        return 0.0
    return round(token_incentive_usd_per_day * 365.0 / tvl_usd * 100.0, 6)


def _real_yield_ratio(real_yield: float, total_apy: float) -> float:
    """Ratio of real yield to total APY, clamped to [0.0, 1.0].

    When total_apy <= 0 and real_yield > 0 returns 1.0.
    When both are <= 0 returns 0.0.
    """
    if total_apy <= 0.0:
        return 1.0 if real_yield > 0.0 else 0.0
    return round(max(0.0, min(1.0, real_yield / total_apy)), 6)


def _incentive_sustainability_score(
    token_inflation_rate_pct: float,
    emissions_vest_days: float,
    token_incentive_usd_per_day: float,
    token_price_usd: float,
    token_circulating_supply: float,
) -> float:
    """
    0–100 score measuring sustainability of token incentives.

    Components
    ----------
    Inflation (40 pts): 0 % inflation → 40 pts; ≥ 50 % inflation → 0 pts.
    Vesting   (30 pts): 0 days → 0 pts; ≥ 365 days → 30 pts.
    Dilution  (30 pts): 0 daily dilution → 30 pts; ≥ 0.5 % market-cap/day → 0 pts.
               If market_cap is 0, award neutral 15 pts on dilution component.
    """
    # 1. Inflation pts
    infl = max(0.0, min(_INFLATION_HIGH_PCT, token_inflation_rate_pct))
    inflation_pts = (1.0 - infl / _INFLATION_HIGH_PCT) * 40.0

    # 2. Vesting pts
    vest = max(0.0, min(float(_VEST_MAX_DAYS), emissions_vest_days))
    vest_pts = (vest / float(_VEST_MAX_DAYS)) * 30.0

    # 3. Daily dilution pts
    market_cap = token_price_usd * token_circulating_supply
    if market_cap > 0.0:
        daily_dilution = token_incentive_usd_per_day / market_cap
        dil = max(0.0, min(_DAILY_DILUTION_CAP, daily_dilution))
        dilution_pts = (1.0 - dil / _DAILY_DILUTION_CAP) * 30.0
    else:
        dilution_pts = 15.0  # neutral when market cap unknown

    return round(min(100.0, inflation_pts + vest_pts + dilution_pts), 2)


def _yield_quality_label(ratio: float) -> str:
    """Map real_yield_ratio → yield quality label (one of five categories)."""
    if ratio >= _PURE_REAL_YIELD_THRESHOLD:
        return "PURE_REAL_YIELD"
    if ratio >= _PREDOMINANTLY_REAL_THRESHOLD:
        return "PREDOMINANTLY_REAL"
    if ratio >= _BALANCED_THRESHOLD:
        return "BALANCED"
    if ratio >= _INCENTIVE_HEAVY_THRESHOLD:
        return "INCENTIVE_HEAVY"
    return "PURE_PONZI_YIELD"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolRealYieldVsIncentiveYieldAnalyzer:
    """
    Decomposes total APY into real (fee) and incentive (token emission) yield,
    scores sustainability of emissions, and assigns a yield quality label.

    Advisory / read-only — never modifies positions, risk policy, or trades.

    Usage
    -----
    analyzer = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer()
    result   = analyzer.analyze(data)
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        """
        Analyze a single protocol's yield decomposition.

        Parameters
        ----------
        data : dict
            protocol_name            : str
            total_apy_pct            : float  — reported total APY (%)
            fee_revenue_usd_per_day  : float  — daily protocol fee revenue (USD)
            tvl_usd                  : float  — total value locked (USD)
            token_incentive_usd_per_day : float — daily token emission value (USD)
            token_price_usd          : float  — current token price (USD)
            token_circulating_supply : float  — circulating supply (units)
            token_inflation_rate_pct : float  — annual token supply inflation (%)
            emissions_vest_days      : float  — vesting period of emissions (days)

        config : dict, optional
            log_path  : str   — override default log file path
            write_log : bool  — write to log (default True)

        Returns
        -------
        dict
            protocol_name, total_apy_pct, real_yield_pct, incentive_yield_pct,
            real_yield_ratio, incentive_sustainability_score, yield_quality_label,
            timestamp
        """
        cfg = config or {}
        log_path  = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        name         = str(data.get("protocol_name", "UNKNOWN"))
        total_apy    = float(data.get("total_apy_pct", 0.0))
        fee_rev_day  = float(data.get("fee_revenue_usd_per_day", 0.0))
        tvl          = float(data.get("tvl_usd", 0.0))
        incent_day   = float(data.get("token_incentive_usd_per_day", 0.0))
        token_price  = float(data.get("token_price_usd", 0.0))
        circ_supply  = float(data.get("token_circulating_supply", 0.0))
        inflation    = float(data.get("token_inflation_rate_pct", 0.0))
        vest_days    = float(data.get("emissions_vest_days", 0.0))

        real_yield   = _real_yield_pct(fee_rev_day, tvl)
        incent_yield = _incentive_yield_pct(incent_day, tvl)
        ratio        = _real_yield_ratio(real_yield, total_apy)
        sust_score   = _incentive_sustainability_score(
            inflation, vest_days, incent_day, token_price, circ_supply
        )
        label        = _yield_quality_label(ratio)

        ts: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        result: dict[str, Any] = {
            "protocol_name":               name,
            "total_apy_pct":               total_apy,
            "real_yield_pct":              real_yield,
            "incentive_yield_pct":         incent_yield,
            "real_yield_ratio":            ratio,
            "incentive_sustainability_score": sust_score,
            "yield_quality_label":         label,
            "timestamp":                   ts,
        }

        if write_log:
            _atomic_log(log_path, {
                "timestamp":                   ts,
                "protocol_name":               name,
                "real_yield_pct":              real_yield,
                "incentive_yield_pct":         incent_yield,
                "real_yield_ratio":            ratio,
                "incentive_sustainability_score": sust_score,
                "yield_quality_label":         label,
            })

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(data: dict, config: dict | None = None) -> dict:
    """Module-level convenience wrapper around DeFiProtocolRealYieldVsIncentiveYieldAnalyzer."""
    return DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(data, config)
