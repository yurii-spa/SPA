"""
MP-974 DeFiBorrowRateForecaster
================================
Advisory-only, read-only analytics module.
Forecasts DeFi borrow rate changes using a kinked interest rate model,
utilization trends, seasonal adjustments, and risk signals.

Input market fields:
    protocol, asset, current_utilization_pct, kink_pct,
    base_rate, slope1, slope2, utilization_7d_ago_pct,
    utilization_30d_avg_pct, net_inflow_30d_usd, total_supply_usd,
    large_borrower_exposure_pct, seasonal_adjustment

Computed per market:
    current_borrow_rate_pct        kinked IR model output
    trend_direction                rising | stable | falling  (7d delta)
    forecast_7d_utilization_pct    linear extrapolation × seasonal, clamped [0,100]
    forecast_7d_borrow_rate_pct    kink model applied to forecast utilization
    rate_change_bps                (forecast − current) × 100, basis points
    rate_shock_risk_score          0-100, high when near kink + rising

Labels:
    RATE_SPIKE_IMMINENT  util > kink AND trend rising
    RATE_NORMALIZATION   util > kink AND trend falling
    RISING               rate_change_bps > 50
    FALLING              rate_change_bps < -50
    STABLE               otherwise

Flags:
    NEAR_KINK              |util − kink| ≤ 5 pp
    LARGE_BORROWER_RISK    large_borrower_exposure_pct > 30
    SUPPLY_INFLOW          net_inflow_30d_usd > 5 % of total_supply_usd
    RATE_ABOVE_10PCT       current_borrow_rate_pct > 10
    TREND_REVERSAL         7d direction opposite to 30d-avg direction

Aggregates:
    highest_rate_risk      protocol with max rate_shock_risk_score
    most_stable            protocol with min |rate_change_bps|
    average_forecast_rate  mean of all forecast_7d_borrow_rate_pct
    spike_imminent_count   count of RATE_SPIKE_IMMINENT markets
    falling_count          count of FALLING markets

Ring-buffer log → data/borrow_rate_forecast_log.json (cap 100, atomic write)
Pure stdlib only. No external dependencies.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from spa_core.utils import clock

# ── Constants ─────────────────────────────────────────────────────────────────
_RING_CAP = 100
_LOG_FILENAME = "borrow_rate_forecast_log.json"

_TREND_RISING_THRESHOLD = 2.0    # pct-point delta → "rising"
_TREND_FALLING_THRESHOLD = -2.0  # pct-point delta → "falling"
_NEAR_KINK_MARGIN_PP = 5.0       # pct-point distance to kink → NEAR_KINK
_LARGE_BORROWER_THRESHOLD = 30.0 # large_borrower_exposure_pct > this
_SUPPLY_INFLOW_PCT = 5.0         # net_inflow > this % of total_supply → SUPPLY_INFLOW
_RATE_HIGH_THRESHOLD = 10.0      # current_rate > this → RATE_ABOVE_10PCT
_STABLE_BPS_THRESHOLD = 50.0     # |rate_change_bps| within this → STABLE


# ── Kinked interest rate model ────────────────────────────────────────────────

def _kink_rate(
    utilization_pct: float,
    kink_pct: float,
    base_rate: float,
    slope1: float,
    slope2: float,
) -> float:
    """
    Two-slope kinked interest rate model.

    If util ≤ kink:  rate = base_rate + slope1 * util
    If util >  kink:  rate = base_rate + slope1 * kink + slope2 * (util − kink)

    All inputs in pct (0-100). Returns rate in pct.
    """
    if utilization_pct <= kink_pct:
        return base_rate + slope1 * utilization_pct
    return base_rate + slope1 * kink_pct + slope2 * (utilization_pct - kink_pct)


# ── Risk score ────────────────────────────────────────────────────────────────

def _risk_score(
    utilization_pct: float,
    kink_pct: float,
    trend_direction: str,
    rate_change_bps: float,
) -> int:
    """
    Compute rate_shock_risk_score 0-100.
    Higher when: close to kink, above kink, rising trend, large rate change.
    """
    score = 0

    dist = abs(utilization_pct - kink_pct)
    if dist <= 2.0:
        score += 40
    elif dist <= 5.0:
        score += 25
    elif dist <= 10.0:
        score += 10

    if utilization_pct > kink_pct:
        score += 20

    if trend_direction == "rising":
        score += 20
    elif trend_direction == "stable":
        score += 5

    if rate_change_bps > 200:
        score += 20
    elif rate_change_bps > 100:
        score += 10
    elif rate_change_bps > 50:
        score += 5

    return min(100, max(0, score))


# ── Forecast label ────────────────────────────────────────────────────────────

def _forecast_label(
    utilization_pct: float,
    kink_pct: float,
    trend_direction: str,
    rate_change_bps: float,
) -> str:
    """
    Priority order:
    1. RATE_SPIKE_IMMINENT  – above kink AND rising
    2. RATE_NORMALIZATION   – above kink AND falling
    3. RISING               – rate_change_bps > threshold
    4. FALLING              – rate_change_bps < -threshold
    5. STABLE               – everything else
    """
    if utilization_pct > kink_pct and trend_direction == "rising":
        return "RATE_SPIKE_IMMINENT"
    if utilization_pct > kink_pct and trend_direction == "falling":
        return "RATE_NORMALIZATION"
    if rate_change_bps > _STABLE_BPS_THRESHOLD:
        return "RISING"
    if rate_change_bps < -_STABLE_BPS_THRESHOLD:
        return "FALLING"
    return "STABLE"


# ── Atomic write helper ───────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


# ── Ring-buffer log ───────────────────────────────────────────────────────────

def _append_log(entry: dict, data_dir: str, cap: int) -> None:
    log_path = os.path.join(data_dir, _LOG_FILENAME)
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            log: list = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(log_path, log)


# ── Main class ────────────────────────────────────────────────────────────────

class DeFiBorrowRateForecaster:
    """
    Forecasts DeFi borrow rates for a list of lending markets.

    Usage::

        forecaster = DeFiBorrowRateForecaster()
        result = forecaster.forecast(markets, config)
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def forecast(
        self,
        markets: List[Dict],
        config: Optional[Dict] = None,
    ) -> Dict:
        """
        Forecast borrow rates for all provided markets.

        Parameters
        ----------
        markets:
            List of market dicts with required/optional fields (see module docstring).
        config:
            Optional configuration overrides:
                data_dir   (str)  Directory for log output. Default: ``"data"``.
                log_cap    (int)  Ring-buffer size. Default: 100.
                write_log  (bool) Whether to persist the log. Default: True.

        Returns
        -------
        dict with keys ``timestamp``, ``markets`` (list of per-market results),
        ``aggregates``.
        """
        if config is None:
            config = {}

        data_dir = str(config.get("data_dir", "data"))
        log_cap = int(config.get("log_cap", _RING_CAP))
        write_log = bool(config.get("write_log", True))

        market_results = [self._forecast_market(m) for m in markets]

        aggregates = self._compute_aggregates(market_results)

        output: Dict = {
            "timestamp": clock.utcnow().isoformat() + "Z",
            "markets": market_results,
            "aggregates": aggregates,
        }

        if write_log:
            _append_log(output, data_dir, log_cap)

        return output

    # ── Per-market computation ────────────────────────────────────────────────

    def _forecast_market(self, m: Dict) -> Dict:
        protocol = str(m.get("protocol", "unknown"))
        asset = str(m.get("asset", "USDC"))
        util = float(m.get("current_utilization_pct", 0.0))
        kink = float(m.get("kink_pct", 80.0))
        base_rate = float(m.get("base_rate", 0.0))
        slope1 = float(m.get("slope1", 0.05))
        slope2 = float(m.get("slope2", 0.5))
        util_7d = float(m.get("utilization_7d_ago_pct", util))
        util_30d_avg = float(m.get("utilization_30d_avg_pct", util))
        net_inflow = float(m.get("net_inflow_30d_usd", 0.0))
        total_supply = float(m.get("total_supply_usd", 0.0))
        large_exposure = float(m.get("large_borrower_exposure_pct", 0.0))
        seasonal = float(m.get("seasonal_adjustment", 1.0))

        # Current rate via kink model
        current_rate = _kink_rate(util, kink, base_rate, slope1, slope2)

        # Trend direction from 7-day delta
        delta_7d = util - util_7d
        if delta_7d > _TREND_RISING_THRESHOLD:
            trend = "rising"
        elif delta_7d < _TREND_FALLING_THRESHOLD:
            trend = "falling"
        else:
            trend = "stable"

        # 30d comparison for TREND_REVERSAL
        diff_from_30d = util - util_30d_avg

        # Forecast utilization: linear extrapolation × seasonal, clamped [0,100]
        forecast_util = util + delta_7d * seasonal
        forecast_util = max(0.0, min(100.0, forecast_util))

        # Forecast rate
        forecast_rate = _kink_rate(forecast_util, kink, base_rate, slope1, slope2)

        # Rate change in basis points
        rate_change_bps = round((forecast_rate - current_rate) * 100.0, 4)

        # Risk score
        risk_score = _risk_score(util, kink, trend, rate_change_bps)

        # Label
        label = _forecast_label(util, kink, trend, rate_change_bps)

        # Flags
        flags: List[str] = []
        if abs(util - kink) <= _NEAR_KINK_MARGIN_PP:
            flags.append("NEAR_KINK")
        if large_exposure > _LARGE_BORROWER_THRESHOLD:
            flags.append("LARGE_BORROWER_RISK")
        if total_supply > 0.0 and net_inflow > (_SUPPLY_INFLOW_PCT / 100.0) * total_supply:
            flags.append("SUPPLY_INFLOW")
        if current_rate > _RATE_HIGH_THRESHOLD:
            flags.append("RATE_ABOVE_10PCT")
        # TREND_REVERSAL: 7d direction opposite to 30d-avg direction
        if (delta_7d > 0.0 and diff_from_30d < 0.0) or (delta_7d < 0.0 and diff_from_30d > 0.0):
            flags.append("TREND_REVERSAL")

        return {
            "protocol": protocol,
            "asset": asset,
            "current_utilization_pct": round(util, 6),
            "current_borrow_rate_pct": round(current_rate, 6),
            "trend_direction": trend,
            "forecast_7d_utilization_pct": round(forecast_util, 6),
            "forecast_7d_borrow_rate_pct": round(forecast_rate, 6),
            "rate_change_bps": rate_change_bps,
            "rate_shock_risk_score": risk_score,
            "forecast_label": label,
            "flags": flags,
        }

    # ── Aggregates ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_aggregates(results: List[Dict]) -> Dict:
        if not results:
            return {
                "highest_rate_risk": None,
                "most_stable": None,
                "average_forecast_rate": 0.0,
                "spike_imminent_count": 0,
                "falling_count": 0,
            }

        highest_risk = max(results, key=lambda r: r["rate_shock_risk_score"])
        most_stable = min(results, key=lambda r: abs(r["rate_change_bps"]))
        avg_rate = sum(r["forecast_7d_borrow_rate_pct"] for r in results) / len(results)
        spike_count = sum(1 for r in results if r["forecast_label"] == "RATE_SPIKE_IMMINENT")
        fall_count = sum(1 for r in results if r["forecast_label"] == "FALLING")

        return {
            "highest_rate_risk": highest_risk["protocol"],
            "most_stable": most_stable["protocol"],
            "average_forecast_rate": round(avg_rate, 6),
            "spike_imminent_count": spike_count,
            "falling_count": fall_count,
        }
