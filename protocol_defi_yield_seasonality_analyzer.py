"""
MP-1129: ProtocolDeFiYieldSeasonalityAnalyzer
----------------------------------------------
Analyzes seasonal patterns in DeFi yield. Some strategies (e.g., yield farming,
governance mining) peak at specific times: end of quarter (rebalancing), bull
markets, high-activity periods. Detects if current APY is seasonal and likely
to revert.

Read-only / advisory — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer JSON log (cap 100).

Input dict keys:
  current_apy_pct    : float
  apy_30d_avg_pct    : float  (rolling 30-day average)
  apy_90d_avg_pct    : float  (rolling 90-day average)
  apy_180d_avg_pct   : float  (rolling 180-day average)
  yield_type         : str  (trading_fees / emissions / lending_interest /
                             staking_rewards / points)
  market_condition   : str  (bull / bear / sideways / high_volatility)
  days_into_quarter  : int  (0-90, day within current quarter)
  protocol_name      : str

Output dict keys:
  protocol_name               : str   (echo)
  yield_type                  : str   (echo)
  market_condition            : str   (echo)
  apy_vs_30d_ratio            : float (current_apy / 30d_avg; 1.0 if avg<=0)
  apy_vs_90d_ratio            : float (current_apy / 90d_avg; 1.0 if avg<=0)
  apy_vs_180d_ratio           : float (current_apy / 180d_avg; 1.0 if avg<=0)
  is_above_all_averages       : bool
  reversion_probability_pct   : float (estimated % chance APY reverts within 30d)
  expected_normalized_apy_pct : float (weighted blend: 0.2*30d + 0.4*90d + 0.4*180d)
  seasonality_label           : str   one of:
                                      STABLE_YIELD / SLIGHTLY_ELEVATED /
                                      ELEVATED_LIKELY_REVERTING / SPIKE_EXPECT_REVERSION /
                                      UNSUSTAINABLE_SPIKE
  analyzed_at                 : str   (ISO-8601 UTC)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_seasonality_log.json"
)
_LOG_CAP = 100

# Normalized APY blend weights (must sum to 1.0)
_W_30D = 0.2
_W_90D = 0.4
_W_180D = 0.4

# Reversion probability: ratio component
# Excess ratio (ratio - 1) at saturation → max contribution
_RATIO_EXCESS_SATURATION = 2.0
_RATIO_MAX_CONTRIBUTION = 60.0

# Reversion probability: yield type base (0-20)
_YIELD_TYPE_BASE = {
    "points": 20.0,
    "emissions": 15.0,
    "trading_fees": 10.0,
    "staking_rewards": 5.0,
    "lending_interest": 5.0,
}
_YIELD_TYPE_BASE_DEFAULT = 10.0

# Reversion probability: market condition adjustment (0-12)
_MARKET_CONDITION_ADJ = {
    "bull": 10.0,
    "high_volatility": 12.0,
    "sideways": 5.0,
    "bear": 5.0,
}
_MARKET_CONDITION_ADJ_DEFAULT = 5.0

# Reversion probability: quarter-end adjustment
_QUARTER_END_HIGH_THRESHOLD = 75   # last 15 days of quarter
_QUARTER_END_HIGH_ADJ = 5.0
_QUARTER_END_MID_THRESHOLD = 60    # last 30 days of quarter
_QUARTER_END_MID_ADJ = 3.0

# Seasonality label bands (apy_vs_90d_ratio → label)
_LABEL_BANDS = [
    (1.1,  "STABLE_YIELD"),
    (1.3,  "SLIGHTLY_ELEVATED"),
    (1.7,  "ELEVATED_LIKELY_REVERTING"),
    (2.5,  "SPIKE_EXPECT_REVERSION"),
    (float("inf"), "UNSUSTAINABLE_SPIKE"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _safe_ratio(current: float, avg: float) -> float:
    """Return current / avg; if avg <= 0, return 1.0 (neutral ratio)."""
    if avg <= 0.0:
        return 1.0
    return round(current / avg, 6)


def _compute_apy_vs_30d_ratio(current_apy_pct: float, apy_30d_avg_pct: float) -> float:
    """Ratio of current APY to 30-day average."""
    return _safe_ratio(current_apy_pct, apy_30d_avg_pct)


def _compute_apy_vs_90d_ratio(current_apy_pct: float, apy_90d_avg_pct: float) -> float:
    """Ratio of current APY to 90-day average (used for label decision)."""
    return _safe_ratio(current_apy_pct, apy_90d_avg_pct)


def _compute_apy_vs_180d_ratio(
    current_apy_pct: float, apy_180d_avg_pct: float
) -> float:
    """Ratio of current APY to 180-day average."""
    return _safe_ratio(current_apy_pct, apy_180d_avg_pct)


def _compute_is_above_all_averages(
    current_apy_pct: float,
    apy_30d_avg_pct: float,
    apy_90d_avg_pct: float,
    apy_180d_avg_pct: float,
) -> bool:
    """True if current APY strictly exceeds all three rolling averages."""
    return (
        current_apy_pct > apy_30d_avg_pct
        and current_apy_pct > apy_90d_avg_pct
        and current_apy_pct > apy_180d_avg_pct
    )


def _compute_expected_normalized_apy_pct(
    apy_30d_avg_pct: float,
    apy_90d_avg_pct: float,
    apy_180d_avg_pct: float,
) -> float:
    """
    Weighted blend of rolling averages to estimate normalized APY.

    Weights: 20% × 30d + 40% × 90d + 40% × 180d
    Longer windows dominate to suppress short-term noise.
    """
    result = (
        _W_30D * apy_30d_avg_pct
        + _W_90D * apy_90d_avg_pct
        + _W_180D * apy_180d_avg_pct
    )
    return round(result, 6)


def _compute_ratio_component(apy_vs_90d_ratio: float) -> float:
    """
    Ratio contribution to reversion probability (0–60 pts).

    Linear ramp from ratio=1.0 (0 pts) to ratio=3.0+ (60 pts).
    """
    excess = max(0.0, apy_vs_90d_ratio - 1.0)
    frac = _clamp(excess / _RATIO_EXCESS_SATURATION, 0.0, 1.0)
    return frac * _RATIO_MAX_CONTRIBUTION


def _compute_yield_type_base(yield_type: str) -> float:
    """Yield type base contribution to reversion probability (5–20 pts)."""
    return _YIELD_TYPE_BASE.get(yield_type, _YIELD_TYPE_BASE_DEFAULT)


def _compute_market_condition_adj(market_condition: str) -> float:
    """Market condition contribution to reversion probability (5–12 pts)."""
    return _MARKET_CONDITION_ADJ.get(market_condition, _MARKET_CONDITION_ADJ_DEFAULT)


def _compute_quarter_end_adj(days_into_quarter: int) -> float:
    """
    Quarter-end adjustment to reversion probability (0–5 pts).

    Higher reversion expected near end of quarter due to rebalancing flows.
      days 75-90 → +5 pts
      days 60-74 → +3 pts
      days 0-59  → 0 pts
    """
    if days_into_quarter >= _QUARTER_END_HIGH_THRESHOLD:
        return _QUARTER_END_HIGH_ADJ
    if days_into_quarter >= _QUARTER_END_MID_THRESHOLD:
        return _QUARTER_END_MID_ADJ
    return 0.0


def _compute_reversion_probability_pct(
    apy_vs_90d_ratio: float,
    yield_type: str,
    market_condition: str,
    days_into_quarter: int,
) -> float:
    """
    Estimate % probability that current APY reverts toward long-term avg within 30d.

    Components:
      ratio_component    = min((ratio-1) / 2.0, 1) * 60   [0–60]
      yield_type_base    = per-type constant               [5–20]
      market_adj         = per-condition constant          [5–12]
      quarter_end_adj    = based on days_into_quarter      [0–5]
    total = clamp(sum, 0, 99)
    """
    ratio_comp = _compute_ratio_component(apy_vs_90d_ratio)
    type_base = _compute_yield_type_base(yield_type)
    market_adj = _compute_market_condition_adj(market_condition)
    quarter_adj = _compute_quarter_end_adj(days_into_quarter)
    raw = ratio_comp + type_base + market_adj + quarter_adj
    return round(_clamp(raw, 0.0, 99.0), 4)


def _compute_seasonality_label(apy_vs_90d_ratio: float) -> str:
    """
    Map apy_vs_90d_ratio to a seasonality label.

    Bands:
      <= 1.1 → STABLE_YIELD
      <= 1.3 → SLIGHTLY_ELEVATED
      <= 1.7 → ELEVATED_LIKELY_REVERTING
      <= 2.5 → SPIKE_EXPECT_REVERSION
      >  2.5 → UNSUSTAINABLE_SPIKE
    """
    for upper, label in _LABEL_BANDS:
        if apy_vs_90d_ratio <= upper:
            return label
    return "UNSUSTAINABLE_SPIKE"


def _atomic_append_log(log_path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array; atomic write via tmp+replace."""
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
    if len(data) > cap:
        data = data[-cap:]

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(abs_path), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldSeasonalityAnalyzer:
    """
    Analyzes seasonal patterns in DeFi yield and estimates reversion probability.

    Usage::

        analyzer = ProtocolDeFiYieldSeasonalityAnalyzer()
        result = analyzer.analyze({
            "protocol_name": "Uniswap V3",
            "current_apy_pct": 12.5,
            "apy_30d_avg_pct": 8.0,
            "apy_90d_avg_pct": 7.0,
            "apy_180d_avg_pct": 6.5,
            "yield_type": "trading_fees",
            "market_condition": "bull",
            "days_into_quarter": 80,
        })
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Static helpers exposed for unit testing
    # ------------------------------------------------------------------

    @staticmethod
    def apy_vs_30d_ratio(current_apy_pct: float, apy_30d_avg_pct: float) -> float:
        """Ratio current / 30d_avg."""
        return _compute_apy_vs_30d_ratio(current_apy_pct, apy_30d_avg_pct)

    @staticmethod
    def apy_vs_90d_ratio(current_apy_pct: float, apy_90d_avg_pct: float) -> float:
        """Ratio current / 90d_avg."""
        return _compute_apy_vs_90d_ratio(current_apy_pct, apy_90d_avg_pct)

    @staticmethod
    def apy_vs_180d_ratio(current_apy_pct: float, apy_180d_avg_pct: float) -> float:
        """Ratio current / 180d_avg."""
        return _compute_apy_vs_180d_ratio(current_apy_pct, apy_180d_avg_pct)

    @staticmethod
    def is_above_all_averages(
        current_apy_pct: float,
        apy_30d_avg_pct: float,
        apy_90d_avg_pct: float,
        apy_180d_avg_pct: float,
    ) -> bool:
        """True if current > all three rolling averages."""
        return _compute_is_above_all_averages(
            current_apy_pct, apy_30d_avg_pct, apy_90d_avg_pct, apy_180d_avg_pct
        )

    @staticmethod
    def expected_normalized_apy_pct(
        apy_30d_avg_pct: float,
        apy_90d_avg_pct: float,
        apy_180d_avg_pct: float,
    ) -> float:
        """Weighted blend of rolling averages (0.2/0.4/0.4)."""
        return _compute_expected_normalized_apy_pct(
            apy_30d_avg_pct, apy_90d_avg_pct, apy_180d_avg_pct
        )

    @staticmethod
    def reversion_probability_pct(
        apy_vs_90d_ratio: float,
        yield_type: str,
        market_condition: str,
        days_into_quarter: int,
    ) -> float:
        """Estimate reversion probability (0–99%)."""
        return _compute_reversion_probability_pct(
            apy_vs_90d_ratio, yield_type, market_condition, days_into_quarter
        )

    @staticmethod
    def seasonality_label(apy_vs_90d_ratio: float) -> str:
        """Map 90d ratio to seasonality label."""
        return _compute_seasonality_label(apy_vs_90d_ratio)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(
        self, data: dict[str, Any], *, write_log: bool = True
    ) -> dict[str, Any]:
        """
        Analyze DeFi yield seasonality for a protocol.

        Parameters
        ----------
        data : dict
            Input dictionary with keys documented at module level.
        write_log : bool
            If True (default) append result to the ring-buffer log file.

        Returns
        -------
        dict
            Output dictionary with all seasonality metrics.
        """
        protocol_name = str(data.get("protocol_name", "unknown"))
        current_apy_pct = float(data.get("current_apy_pct", 0.0))
        apy_30d_avg_pct = float(data.get("apy_30d_avg_pct", 0.0))
        apy_90d_avg_pct = float(data.get("apy_90d_avg_pct", 0.0))
        apy_180d_avg_pct = float(data.get("apy_180d_avg_pct", 0.0))
        yield_type = str(data.get("yield_type", "trading_fees"))
        market_condition = str(data.get("market_condition", "sideways"))
        days_into_quarter = int(data.get("days_into_quarter", 0))

        ratio_30d = _compute_apy_vs_30d_ratio(current_apy_pct, apy_30d_avg_pct)
        ratio_90d = _compute_apy_vs_90d_ratio(current_apy_pct, apy_90d_avg_pct)
        ratio_180d = _compute_apy_vs_180d_ratio(current_apy_pct, apy_180d_avg_pct)
        above_all = _compute_is_above_all_averages(
            current_apy_pct, apy_30d_avg_pct, apy_90d_avg_pct, apy_180d_avg_pct
        )
        normalized_apy = _compute_expected_normalized_apy_pct(
            apy_30d_avg_pct, apy_90d_avg_pct, apy_180d_avg_pct
        )
        reversion_prob = _compute_reversion_probability_pct(
            ratio_90d, yield_type, market_condition, days_into_quarter
        )
        label = _compute_seasonality_label(ratio_90d)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            "yield_type": yield_type,
            "market_condition": market_condition,
            "apy_vs_30d_ratio": ratio_30d,
            "apy_vs_90d_ratio": ratio_90d,
            "apy_vs_180d_ratio": ratio_180d,
            "is_above_all_averages": above_all,
            "reversion_probability_pct": reversion_prob,
            "expected_normalized_apy_pct": normalized_apy,
            "seasonality_label": label,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if write_log:
            _atomic_append_log(self._log_path, result)

        return result
