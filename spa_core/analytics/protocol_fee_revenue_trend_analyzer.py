"""
MP-979: ProtocolFeeRevenueTrendAnalyzer

Advisory/read-only module. Analyzes trends in DeFi protocol fee revenues,
computing growth rates, linear regression trends, cycle-adjusted metrics,
and competitive positioning.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "fee_revenue_trend_log.json"
)

# ---------------------------------------------------------------------------
# Trend label constants
# ---------------------------------------------------------------------------
LABEL_HYPERGROWTH = "HYPERGROWTH"
LABEL_STRONG_GROWTH = "STRONG_GROWTH"
LABEL_STABLE = "STABLE"
LABEL_DECLINING = "DECLINING"
LABEL_COLLAPSING = "COLLAPSING"

# ---------------------------------------------------------------------------
# Flag constants
# ---------------------------------------------------------------------------
FLAG_BEATS_COMPETITORS = "BEATS_COMPETITORS"
FLAG_LOSING_MARKET_SHARE = "LOSING_MARKET_SHARE"
FLAG_ONE_TIME_INFLATED = "ONE_TIME_INFLATED"
FLAG_TREND_REVERSAL = "TREND_REVERSAL"
FLAG_STRONG_TREND = "STRONG_TREND"

# ---------------------------------------------------------------------------
# Market cycle multipliers
# ---------------------------------------------------------------------------
_CYCLE_FACTORS = {"bull": 1.3, "neutral": 1.0, "bear": 0.7}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    return num / denom if denom != 0.0 else default


def _linear_regression(y: List[float]):
    """Return (slope, r_squared) for y values indexed 0..n-1."""
    n = len(y)
    if n < 2:
        return 0.0, 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n
    ss_xy = sum((i - x_mean) * (yi - y_mean) for i, yi in enumerate(y))
    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    ss_yy = sum((yi - y_mean) ** 2 for yi in y)
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    if ss_yy == 0:
        r_squared = 1.0 if ss_xy == 0 else 0.0
    else:
        r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)
    return slope, r_squared


class ProtocolFeeRevenueTrendAnalyzer:
    """Analyze fee revenue trends for DeFi protocols."""

    def __init__(self, data_file: Optional[str] = None):
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: List[dict], config: Optional[dict] = None) -> dict:
        """
        Analyze fee revenue trends for a list of protocols.

        Parameters
        ----------
        protocols : list[dict]
            Each dict must contain:
              name, revenue_by_week_usd (list[float], 12 weeks newest last),
              protocol_type (dex/lending/perp/bridge/staking),
              total_tvl_usd, competitor_avg_revenue_growth_pct,
              market_cycle (bull/neutral/bear), seasonal_factor (0.8-1.2),
              one_time_events_usd

        config : dict, optional
            Optional overrides: hypergrowth_threshold, strong_growth_threshold,
            declining_threshold, collapsing_threshold, beats_competitors_factor,
            losing_market_share_factor, one_time_inflated_threshold,
            strong_trend_r_squared

        Returns
        -------
        dict with keys: results (list), aggregates (dict), run_ts (str), protocol_count (int)
        """
        if config is None:
            config = {}

        hypergrowth_thresh = float(config.get("hypergrowth_threshold", 50.0))
        strong_growth_thresh = float(config.get("strong_growth_threshold", 20.0))
        declining_thresh = float(config.get("declining_threshold", -10.0))
        collapsing_thresh = float(config.get("collapsing_threshold", -30.0))
        beats_factor = float(config.get("beats_competitors_factor", 1.2))
        losing_factor = float(config.get("losing_market_share_factor", 0.5))
        one_time_thresh = float(config.get("one_time_inflated_threshold", 0.2))
        strong_trend_rsq = float(config.get("strong_trend_r_squared", 0.8))

        results = []
        for proto in protocols:
            r = self._analyze_protocol(
                proto,
                hypergrowth_thresh=hypergrowth_thresh,
                strong_growth_thresh=strong_growth_thresh,
                declining_thresh=declining_thresh,
                collapsing_thresh=collapsing_thresh,
                beats_factor=beats_factor,
                losing_factor=losing_factor,
                one_time_thresh=one_time_thresh,
                strong_trend_rsq=strong_trend_rsq,
            )
            results.append(r)

        aggregates = self._compute_aggregates(results)

        run_ts = datetime.now(timezone.utc).isoformat()
        output = {
            "results": results,
            "aggregates": aggregates,
            "run_ts": run_ts,
            "protocol_count": len(protocols),
        }

        self._append_log({"run_ts": run_ts, "protocol_count": len(protocols), "aggregates": aggregates})
        return output

    # ------------------------------------------------------------------
    # Per-protocol analysis
    # ------------------------------------------------------------------

    def _analyze_protocol(
        self,
        proto: dict,
        *,
        hypergrowth_thresh: float,
        strong_growth_thresh: float,
        declining_thresh: float,
        collapsing_thresh: float,
        beats_factor: float,
        losing_factor: float,
        one_time_thresh: float,
        strong_trend_rsq: float,
    ) -> dict:
        name = str(proto.get("name", ""))
        protocol_type = str(proto.get("protocol_type", "dex"))
        total_tvl_usd = float(proto.get("total_tvl_usd", 0.0))
        competitor_avg_growth = float(proto.get("competitor_avg_revenue_growth_pct", 0.0))
        market_cycle = str(proto.get("market_cycle", "neutral"))
        seasonal_factor = float(proto.get("seasonal_factor", 1.0))
        one_time_usd = float(proto.get("one_time_events_usd", 0.0))

        raw_weeks = proto.get("revenue_by_week_usd", [])
        # Ensure we have floats
        try:
            weeks = [float(w) for w in raw_weeks]
        except (TypeError, ValueError):
            weeks = []

        # Pad to at least 12 weeks with zeros if needed
        if len(weeks) < 2:
            weeks = weeks + [0.0] * max(0, 12 - len(weeks))

        # Use up to 12 weeks
        weeks_12 = weeks[-12:] if len(weeks) >= 12 else weeks

        # 4-week and 12-week averages (use last 4 and all 12)
        last_4 = weeks_12[-4:] if len(weeks_12) >= 4 else weeks_12
        revenue_4w_avg = sum(last_4) / len(last_4) if last_4 else 0.0

        revenue_12w_avg = sum(weeks_12) / len(weeks_12) if weeks_12 else 0.0

        # MoM growth: last 4w vs previous 4w
        prev_4 = weeks_12[-8:-4] if len(weeks_12) >= 8 else []
        if prev_4:
            prev_4_avg = sum(prev_4) / len(prev_4)
        else:
            prev_4_avg = revenue_12w_avg  # fallback

        if prev_4_avg != 0.0:
            mom_growth_pct = _safe_div(revenue_4w_avg - prev_4_avg, abs(prev_4_avg)) * 100.0
        else:
            mom_growth_pct = 0.0 if revenue_4w_avg == 0.0 else 100.0

        # Linear regression on 12w
        if len(weeks_12) >= 2:
            trend_slope, trend_r_squared = _linear_regression(weeks_12)
        else:
            trend_slope, trend_r_squared = 0.0, 0.0

        # Normalized revenue (remove one-time events from 4w avg)
        weeks_per_period = len(last_4)
        one_time_per_week = one_time_usd / weeks_per_period if weeks_per_period > 0 else 0.0
        normalized_revenue_usd = max(0.0, revenue_4w_avg - one_time_per_week)

        # Cycle factor
        cycle_factor = _CYCLE_FACTORS.get(market_cycle, 1.0)

        # Cycle-adjusted growth
        if cycle_factor != 0.0:
            cycle_adjusted_growth = mom_growth_pct / cycle_factor
        else:
            cycle_adjusted_growth = mom_growth_pct

        # Apply seasonal factor adjustment
        cycle_adjusted_growth = cycle_adjusted_growth / seasonal_factor if seasonal_factor != 0.0 else cycle_adjusted_growth

        # Trend label
        label = self._compute_label(
            mom_growth_pct=mom_growth_pct,
            hypergrowth_thresh=hypergrowth_thresh,
            strong_growth_thresh=strong_growth_thresh,
            declining_thresh=declining_thresh,
            collapsing_thresh=collapsing_thresh,
        )

        # Flags
        flags = self._compute_flags(
            cycle_adjusted_growth=cycle_adjusted_growth,
            competitor_avg_growth=competitor_avg_growth,
            one_time_usd=one_time_usd,
            revenue_4w_avg=revenue_4w_avg,
            trend_slope=trend_slope,
            trend_r_squared=trend_r_squared,
            weeks_12=weeks_12,
            beats_factor=beats_factor,
            losing_factor=losing_factor,
            one_time_thresh=one_time_thresh,
            strong_trend_rsq=strong_trend_rsq,
        )

        return {
            "name": name,
            "protocol_type": protocol_type,
            "total_tvl_usd": round(total_tvl_usd, 2),
            "revenue_4w_avg_usd": round(revenue_4w_avg, 2),
            "revenue_12w_avg_usd": round(revenue_12w_avg, 2),
            "mom_growth_pct": round(mom_growth_pct, 4),
            "trend_slope": round(trend_slope, 4),
            "trend_r_squared": round(trend_r_squared, 4),
            "normalized_revenue_usd": round(normalized_revenue_usd, 2),
            "cycle_adjusted_growth": round(cycle_adjusted_growth, 4),
            "market_cycle": market_cycle,
            "seasonal_factor": seasonal_factor,
            "competitor_avg_revenue_growth_pct": competitor_avg_growth,
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _compute_label(
        self,
        *,
        mom_growth_pct: float,
        hypergrowth_thresh: float,
        strong_growth_thresh: float,
        declining_thresh: float,
        collapsing_thresh: float,
    ) -> str:
        if mom_growth_pct >= hypergrowth_thresh:
            return LABEL_HYPERGROWTH
        if mom_growth_pct >= strong_growth_thresh:
            return LABEL_STRONG_GROWTH
        if mom_growth_pct > declining_thresh:
            return LABEL_STABLE
        if mom_growth_pct > collapsing_thresh:
            return LABEL_DECLINING
        return LABEL_COLLAPSING

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        *,
        cycle_adjusted_growth: float,
        competitor_avg_growth: float,
        one_time_usd: float,
        revenue_4w_avg: float,
        trend_slope: float,
        trend_r_squared: float,
        weeks_12: List[float],
        beats_factor: float,
        losing_factor: float,
        one_time_thresh: float,
        strong_trend_rsq: float,
    ) -> List[str]:
        flags = []

        # Beats competitors
        if cycle_adjusted_growth > competitor_avg_growth * beats_factor:
            flags.append(FLAG_BEATS_COMPETITORS)

        # Losing market share
        if cycle_adjusted_growth < competitor_avg_growth * losing_factor:
            flags.append(FLAG_LOSING_MARKET_SHARE)

        # One-time inflated
        if revenue_4w_avg > 0 and one_time_usd > revenue_4w_avg * one_time_thresh:
            flags.append(FLAG_ONE_TIME_INFLATED)

        # Trend reversal: positive slope but recent 2w negative
        if trend_slope > 0 and len(weeks_12) >= 2:
            recent_2 = weeks_12[-2:]
            if recent_2[-1] < recent_2[0]:
                flags.append(FLAG_TREND_REVERSAL)

        # Strong trend
        if trend_r_squared >= strong_trend_rsq:
            flags.append(FLAG_STRONG_TREND)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: List[dict]) -> dict:
        if not results:
            return {
                "fastest_growing": None,
                "fastest_declining": None,
                "average_mom_growth": 0.0,
                "hypergrowth_count": 0,
                "collapsing_count": 0,
            }

        sorted_by_growth = sorted(results, key=lambda r: r["mom_growth_pct"], reverse=True)
        fastest_growing = sorted_by_growth[0]["name"]
        fastest_declining = sorted_by_growth[-1]["name"]

        growths = [r["mom_growth_pct"] for r in results]
        avg_growth = sum(growths) / len(growths)

        hypergrowth_count = sum(1 for r in results if r["label"] == LABEL_HYPERGROWTH)
        collapsing_count = sum(1 for r in results if r["label"] == LABEL_COLLAPSING)

        return {
            "fastest_growing": fastest_growing,
            "fastest_declining": fastest_declining,
            "average_mom_growth": round(avg_growth, 4),
            "hypergrowth_count": hypergrowth_count,
            "collapsing_count": collapsing_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, record: dict) -> None:
        """Atomically append record to ring-buffer log (cap 100)."""
        try:
            log = []
            if os.path.exists(self._data_file):
                try:
                    with open(self._data_file, "r", encoding="utf-8") as fh:
                        log = json.load(fh)
                    if not isinstance(log, list):
                        log = []
                except (json.JSONDecodeError, OSError):
                    log = []

            log.append(record)
            if len(log) > 100:
                log = log[-100:]

            dir_name = os.path.dirname(self._data_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            atomic_save(log, str(self._data_file))
        except Exception:
            # Advisory module — never crash the caller
            pass
