"""
MP-990: DeFiProtocolTVLMomentumAnalyzer
Analyzes TVL momentum and trend dynamics across DeFi protocols.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import os
import time
import math
from datetime import datetime, timezone

# ── constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "tvl_momentum_log.json"
)
LOG_CAP = 100

# momentum_score weights
W_7D  = 0.35
W_30D = 0.40
W_ACC = 0.25


# ── helpers ──────────────────────────────────────────────────────────────────

def _pct_change(old: float, new: float) -> float:
    """Return percentage change; 0 when old is 0."""
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100.0


def _linear_slope(series: list) -> float:
    """OLS slope of series[i] vs i.  Returns 0 on <2 points."""
    n = len(series)
    if n < 2:
        return 0.0
    sx = n * (n - 1) / 2          # sum of 0..n-1
    sx2 = (n - 1) * n * (2 * n - 1) / 6
    sy  = sum(series)
    sxy = sum(i * v for i, v in enumerate(series))
    denom = n * sx2 - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _normalize_slope_to_score(slope: float, scale: float = 1_000_000.0) -> float:
    """Convert a raw TVL slope (USD/day) to a 0-100 contribution score."""
    # sigmoid-like: score = 50 + 50 * tanh(slope/scale)
    ratio = slope / scale
    # tanh approximation via exp (stdlib only)
    try:
        if ratio > 20:
            t = 1.0
        elif ratio < -20:
            t = -1.0
        else:
            e2 = math.exp(2 * ratio)
            t = (e2 - 1) / (e2 + 1)
    except OverflowError:
        t = 1.0 if ratio > 0 else -1.0
    return 50.0 + 50.0 * t


# ── main class ───────────────────────────────────────────────────────────────

class DeFiProtocolTVLMomentumAnalyzer:
    """
    Analyzes TVL momentum (trend dynamics) for a list of DeFi protocols.

    Each protocol dict (input):
        name               : str
        category           : str          (e.g. "lending", "dex", "yield")
        tvl_history_usd    : list[float]  30 daily snapshots, oldest→newest
        current_tvl_usd    : float
        all_time_high_tvl_usd : float
        ath_date           : str          (ISO date string, informational)
        chain              : str          ("ethereum", "multi", …)
        weekly_active_users: int
        user_growth_pct_30d: float        (percent, can be negative)

    config (optional keys):
        hypergrowth_30d_threshold : float  (default 50)
        strong_growth_30d         : float  (default 20)
        recovering_low_pct        : float  (default 20) — improvement vs 6mo low
        collapse_30d_threshold    : float  (default -40)
        collapse_ath_drawdown     : float  (default 80)
        slope_scale               : float  (default 1_000_000)
        log_path                  : str    (override for tests)
        log_cap                   : int    (override for tests)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, protocols: list, config: dict) -> dict:
        cfg = self._merge_config(config)
        results = [self._analyze_one(p, cfg) for p in protocols]

        agg = self._aggregate(results, cfg)
        self._write_log(results, agg, cfg)

        return {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(results),
            "protocols": results,
            "aggregates": agg,
        }

    # ── config ────────────────────────────────────────────────────────────────

    def _merge_config(self, config: dict) -> dict:
        defaults = {
            "hypergrowth_30d_threshold": 50.0,
            "strong_growth_30d":         20.0,
            "recovering_low_pct":        20.0,
            "collapse_30d_threshold":   -40.0,
            "collapse_ath_drawdown":     80.0,
            "slope_scale":         1_000_000.0,
            "log_path":            LOG_PATH,
            "log_cap":             LOG_CAP,
        }
        merged = dict(defaults)
        merged.update(config)
        return merged

    # ── per-protocol analysis ─────────────────────────────────────────────────

    def _analyze_one(self, p: dict, cfg: dict) -> dict:
        history = list(p.get("tvl_history_usd", []))
        current = float(p.get("current_tvl_usd", 0))
        ath     = float(p.get("all_time_high_tvl_usd", current))
        weekly_users = int(p.get("weekly_active_users", 0))
        user_growth  = float(p.get("user_growth_pct_30d", 0))

        # Ensure history has ≥1 element with current at end
        if not history:
            history = [current]

        # ── 7d / 30d TVL change ───────────────────────────────────────────────
        tvl_7d_ago  = history[-8]  if len(history) >= 8  else history[0]
        tvl_30d_ago = history[-31] if len(history) >= 31 else history[0]
        tvl_7d_ago  = float(tvl_7d_ago)
        tvl_30d_ago = float(tvl_30d_ago)

        change_7d  = _pct_change(tvl_7d_ago,  current)
        change_30d = _pct_change(tvl_30d_ago, current)

        # ── trend acceleration ────────────────────────────────────────────────
        # slope over last 7 days vs slope over prior 7 days
        last7  = [float(v) for v in history[-7:]]
        prev7  = [float(v) for v in history[-14:-7]] if len(history) >= 14 else last7
        slope_last7 = _linear_slope(last7)
        slope_prev7 = _linear_slope(prev7)
        trend_acceleration = slope_last7 - slope_prev7

        # ── ATH drawdown ─────────────────────────────────────────────────────
        ath_dd = ((ath - current) / ath * 100.0) if ath > 0 else 0.0
        ath_dd = _clamp(ath_dd, 0.0, 100.0)

        # ── 6-month low (use oldest 6 months of history = up to 180 points) ──
        six_mo_slice = history[:-1][-180:] if len(history) > 1 else history
        six_mo_low   = min(float(v) for v in six_mo_slice) if six_mo_slice else current

        # ── user/TVL ratio (engagement density) ─────────────────────────────
        tvl_M = current / 1_000_000.0 if current > 0 else 1.0
        user_tvl_ratio = weekly_users / tvl_M if tvl_M > 0 else 0.0

        # ── momentum score (0-100) ────────────────────────────────────────────
        score_7d  = _normalize_slope_to_score(slope_last7, cfg["slope_scale"])
        score_30d = _normalize_slope_to_score(
            _linear_slope([float(v) for v in history[-30:]]) if len(history) >= 30
            else slope_last7,
            cfg["slope_scale"]
        )
        score_acc = _normalize_slope_to_score(trend_acceleration, cfg["slope_scale"] * 0.5)

        momentum_score = _clamp(
            W_7D * score_7d + W_30D * score_30d + W_ACC * score_acc,
            0.0, 100.0
        )

        # ── label ─────────────────────────────────────────────────────────────
        label = self._classify_label(
            change_30d, trend_acceleration, ath_dd, current, six_mo_low, cfg
        )

        # ── flags ─────────────────────────────────────────────────────────────
        flags = self._compute_flags(
            current, ath, ath_dd, change_30d, trend_acceleration,
            user_growth, change_7d, cfg
        )

        return {
            "name":                p.get("name", ""),
            "category":            p.get("category", ""),
            "chain":               p.get("chain", ""),
            "current_tvl_usd":     current,
            "all_time_high_tvl_usd": ath,
            "tvl_change_pct_7d":   round(change_7d, 4),
            "tvl_change_pct_30d":  round(change_30d, 4),
            "trend_acceleration":  round(trend_acceleration, 2),
            "slope_last_7d":       round(slope_last7, 2),
            "slope_prev_7d":       round(slope_prev7, 2),
            "ath_drawdown_pct":    round(ath_dd, 4),
            "user_tvl_ratio":      round(user_tvl_ratio, 4),
            "momentum_score":      round(momentum_score, 2),
            "momentum_label":      label,
            "flags":               flags,
        }

    # ── label classifier ─────────────────────────────────────────────────────

    def _classify_label(
        self, change_30d, trend_acceleration, ath_dd,
        current, six_mo_low, cfg
    ) -> str:
        hyper_thr  = cfg["hypergrowth_30d_threshold"]
        strong_thr = cfg["strong_growth_30d"]
        recover_thr = cfg["recovering_low_pct"]
        collapse_30d = cfg["collapse_30d_threshold"]
        collapse_ath  = cfg["collapse_ath_drawdown"]

        if ath_dd > collapse_ath or change_30d < collapse_30d:
            return "COLLAPSE"
        if change_30d > hyper_thr and trend_acceleration > 0:
            return "HYPERGROWTH"
        if change_30d > strong_thr:
            return "STRONG_GROWTH"
        # Recovering: current is >recover_thr% above 6-month low
        if six_mo_low > 0:
            improvement_vs_low = _pct_change(six_mo_low, current)
            if improvement_vs_low > recover_thr and change_30d > 0:
                return "RECOVERING"
        if change_30d < 0:
            return "DECLINING"
        return "STABLE"

    # ── flags ─────────────────────────────────────────────────────────────────

    def _compute_flags(
        self, current, ath, ath_dd, change_30d, trend_acceleration,
        user_growth, change_7d, cfg
    ) -> list:
        flags = []

        # NEW_ATH
        if current >= ath and ath > 0:
            flags.append("NEW_ATH")

        # ATH_DRAWDOWN_SEVERE
        if ath_dd > 60.0:
            flags.append("ATH_DRAWDOWN_SEVERE")

        # USER_GROWTH_DIVERGING: users +20% but TVL flat/down
        if user_growth >= 20.0 and change_30d <= 0:
            flags.append("USER_GROWTH_DIVERGING")

        # TVL_WITHOUT_USERS: TVL +30% but users flat (user_growth <5%)
        if change_30d >= 30.0 and user_growth < 5.0:
            flags.append("TVL_WITHOUT_USERS")

        # MOMENTUM_REVERSAL: acceleration negative after growth
        if trend_acceleration < 0 and change_7d > 5.0:
            flags.append("MOMENTUM_REVERSAL")

        return flags

    # ── aggregates ───────────────────────────────────────────────────────────

    def _aggregate(self, results: list, cfg: dict) -> dict:
        if not results:
            return {
                "fastest_growing": None,
                "fastest_declining": None,
                "avg_momentum_score": 0.0,
                "hypergrowth_count": 0,
                "collapse_count": 0,
            }

        by_30d = sorted(results, key=lambda r: r["tvl_change_pct_30d"], reverse=True)
        fastest_growing  = by_30d[0]["name"]  if by_30d else None
        fastest_declining = by_30d[-1]["name"] if by_30d else None

        avg_score = sum(r["momentum_score"] for r in results) / len(results)
        hyper = sum(1 for r in results if r["momentum_label"] == "HYPERGROWTH")
        collapse = sum(1 for r in results if r["momentum_label"] == "COLLAPSE")

        return {
            "fastest_growing":    fastest_growing,
            "fastest_declining":  fastest_declining,
            "avg_momentum_score": round(avg_score, 2),
            "hypergrowth_count":  hyper,
            "collapse_count":     collapse,
        }

    # ── ring-buffer log ──────────────────────────────────────────────────────

    def _write_log(self, results: list, agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]

        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(results),
            "aggregates":     agg,
            "snapshots": [
                {
                    "name":           r["name"],
                    "momentum_score": r["momentum_score"],
                    "momentum_label": r["momentum_label"],
                    "tvl_change_pct_30d": r["tvl_change_pct_30d"],
                }
                for r in results
            ],
        }

        # Read existing log
        log = []
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
