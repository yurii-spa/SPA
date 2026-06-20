"""
MP-987: ProtocolYieldFarmingLifecycleAnalyzer
Analyzes the lifecycle of yield farming programs from launch to sunset.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Lifecycle labels
# ---------------------------------------------------------------------------
LABEL_LAUNCH_PHASE  = "LAUNCH_PHASE"
LABEL_GROWTH_PHASE  = "GROWTH_PHASE"
LABEL_MATURITY      = "MATURITY"
LABEL_DECLINE       = "DECLINE"
LABEL_SUNSET        = "SUNSET"
LABEL_ZOMBIE        = "ZOMBIE"

# Flags
FLAG_APY_CRASHED           = "APY_CRASHED"
FLAG_MERCENARY_CAPITAL     = "MERCENARY_CAPITAL"
FLAG_EMISSIONS_ENDING_SOON = "EMISSIONS_ENDING_SOON"
FLAG_HIGH_VALUE_EXTRACTION = "HIGH_VALUE_EXTRACTION"
FLAG_STICKY_FARMERS        = "STICKY_FARMERS"

# Ring-buffer cap
_LOG_CAP = 100
_LOG_PATH_DEFAULT = "data/farming_lifecycle_log.json"

# Zombie thresholds
_ZOMBIE_APY_THRESHOLD     = 2.0   # % — very low APY
_ZOMBIE_FARMER_THRESHOLD  = 10    # absolute unique farmers count


def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _classify_lifecycle(farm: dict,
                         apy_decay_rate: float,
                         tvl_retention: float,
                         farmer_retention: float) -> str:
    """Return lifecycle label for a single farm."""
    launch_days_ago   = float(farm.get("launch_date_days_ago", 0))
    initial_apy       = float(farm.get("initial_apy_pct", 0.0))
    current_apy       = float(farm.get("current_apy_pct", 0.0))
    peak_apy          = float(farm.get("peak_apy_pct", 0.0))
    emission_remain   = float(farm.get("emission_schedule_remaining_pct", 100.0))
    is_deprecated     = bool(farm.get("is_deprecated", False))
    unique_current    = int(farm.get("unique_farmers_current", 0))

    # SUNSET: explicitly deprecated
    if is_deprecated:
        return LABEL_SUNSET

    # ZOMBIE: low APY, low farmers, still running
    if (current_apy < _ZOMBIE_APY_THRESHOLD
            and unique_current < _ZOMBIE_FARMER_THRESHOLD
            and not is_deprecated):
        return LABEL_ZOMBIE

    # LAUNCH_PHASE: <30d AND current APY ≥ 80% of peak
    if launch_days_ago < 30 and peak_apy > 0 and current_apy >= 0.8 * peak_apy:
        return LABEL_LAUNCH_PHASE

    # GROWTH_PHASE: tvl_retention growing (>1 means peak hasn't been reached yet,
    #               or we proxy by high farmer retention + emission remaining)
    if tvl_retention >= 90.0 and farmer_retention >= 80.0 and emission_remain >= 50.0:
        return LABEL_GROWTH_PHASE

    # DECLINE: rapidly losing TVL and farmers
    if tvl_retention < 40.0 or farmer_retention < 30.0:
        return LABEL_DECLINE

    # MATURITY: stable, mid-lifecycle
    return LABEL_MATURITY


def _analyze_farm(farm: dict) -> dict:
    """Analyze a single farm and return its result dict."""
    protocol           = farm.get("protocol", "unknown")
    pair               = farm.get("pair", "unknown")
    launch_days_ago    = float(farm.get("launch_date_days_ago", 0))
    initial_apy        = float(farm.get("initial_apy_pct", 0.0))
    current_apy        = float(farm.get("current_apy_pct", 0.0))
    peak_apy           = float(farm.get("peak_apy_pct", 0.0))
    tvl_at_launch      = float(farm.get("tvl_at_launch_usd", 0.0))
    tvl_at_peak        = float(farm.get("tvl_at_peak_usd", 0.0))
    tvl_current        = float(farm.get("tvl_current_usd", 0.0))
    emission_remain    = float(farm.get("emission_schedule_remaining_pct", 100.0))
    unique_current     = int(farm.get("unique_farmers_current", 0))
    unique_at_peak     = int(farm.get("unique_farmers_at_peak", 1))
    rewards_claimed    = float(farm.get("rewards_claimed_pct", 0.0))
    is_deprecated      = bool(farm.get("is_deprecated", False))

    # apy_decay_rate_pct: how fast APY fell from peak
    # Defined as (peak - current) / peak * 100, clipped to [0, 100]
    if peak_apy > 0:
        apy_decay_rate = round(max(0.0, min((peak_apy - current_apy) / peak_apy * 100.0, 100.0)), 2)
    else:
        apy_decay_rate = 0.0

    # tvl_retention_rate_pct: current / peak * 100
    if tvl_at_peak > 0:
        tvl_retention = round(min(tvl_current / tvl_at_peak * 100.0, 200.0), 2)
    else:
        tvl_retention = 100.0

    # farmer_retention_rate_pct: current / peak * 100
    if unique_at_peak > 0:
        farmer_retention = round(min(unique_current / unique_at_peak * 100.0, 200.0), 2)
    else:
        farmer_retention = 100.0

    # lifecycle_stage_days: days in current lifecycle stage
    # Simple heuristic: if <30d ago → launch_days_ago; else use launch_days_ago
    lifecycle_stage_days = int(launch_days_ago)

    # value_extraction_ratio: rewards_claimed_pct / initial_tvl × 100
    # Using rewards_claimed_pct directly as the ratio (already represents %)
    # Spec: rewards_claimed / initial_tvl × 100 — but rewards_claimed is already a pct
    # Interpret: claimed rewards $amount = rewards_claimed_pct% of initial_tvl
    if tvl_at_launch > 0:
        value_extraction_ratio = round(
            (rewards_claimed / 100.0) * tvl_at_launch / max(tvl_at_launch, 1.0) * 100.0, 2
        )
    else:
        value_extraction_ratio = round(rewards_claimed, 2)

    # Lifecycle label
    lifecycle_label = _classify_lifecycle(farm, apy_decay_rate, tvl_retention, farmer_retention)

    # Flags
    flags = []
    if peak_apy > 0 and current_apy < 0.1 * peak_apy:
        flags.append(FLAG_APY_CRASHED)
    if farmer_retention < 20.0 and tvl_retention < 30.0:
        flags.append(FLAG_MERCENARY_CAPITAL)
    if emission_remain < 10.0:
        flags.append(FLAG_EMISSIONS_ENDING_SOON)
    if value_extraction_ratio > 50.0:
        flags.append(FLAG_HIGH_VALUE_EXTRACTION)
    if farmer_retention > 70.0:
        flags.append(FLAG_STICKY_FARMERS)

    return {
        "protocol": protocol,
        "pair": pair,
        "launch_date_days_ago": launch_days_ago,
        "current_apy_pct": current_apy,
        "peak_apy_pct": peak_apy,
        "tvl_current_usd": tvl_current,
        "tvl_at_peak_usd": tvl_at_peak,
        "apy_decay_rate_pct": apy_decay_rate,
        "tvl_retention_rate_pct": tvl_retention,
        "farmer_retention_rate_pct": farmer_retention,
        "lifecycle_stage_days": lifecycle_stage_days,
        "value_extraction_ratio": value_extraction_ratio,
        "lifecycle_label": lifecycle_label,
        "flags": flags,
        "emission_schedule_remaining_pct": emission_remain,
        "unique_farmers_current": unique_current,
        "unique_farmers_at_peak": unique_at_peak,
        "is_deprecated": is_deprecated,
    }


class ProtocolYieldFarmingLifecycleAnalyzer:
    """
    Analyzes yield farming lifecycle stages from launch to sunset.

    analyze(farms, config) -> dict
    """

    def __init__(self, log_path: str = _LOG_PATH_DEFAULT):
        self._log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, farms: list, config: dict | None = None) -> dict:
        """
        Analyze all farms and return lifecycle summary.

        Parameters
        ----------
        farms  : list[dict]  — farm descriptors (see module docstring)
        config : dict        — optional overrides (log_path)

        Returns
        -------
        dict with keys: farms (list of results), aggregates, timestamp
        """
        if config is None:
            config = {}

        log_path = config.get("log_path", self._log_path)

        if not farms:
            result = {
                "farms": [],
                "aggregates": {
                    "newest_farm": None,
                    "oldest_farm": None,
                    "average_tvl_retention": 0.0,
                    "zombie_count": 0,
                    "sunset_count": 0,
                    "total_farms": 0,
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._append_log(result, log_path)
            return result

        analyzed = [_analyze_farm(f) for f in farms]

        # Aggregates
        launch_ages = [a["launch_date_days_ago"] for a in analyzed]
        newest = min(analyzed, key=lambda a: a["launch_date_days_ago"])
        oldest = max(analyzed, key=lambda a: a["launch_date_days_ago"])

        tvl_retentions = [a["tvl_retention_rate_pct"] for a in analyzed]
        avg_tvl_retention = round(sum(tvl_retentions) / len(tvl_retentions), 2)

        zombie_count = sum(1 for a in analyzed if a["lifecycle_label"] == LABEL_ZOMBIE)
        sunset_count = sum(1 for a in analyzed if a["lifecycle_label"] == LABEL_SUNSET)

        result = {
            "farms": analyzed,
            "aggregates": {
                "newest_farm": {
                    "protocol": newest["protocol"],
                    "pair":     newest["pair"],
                    "launch_date_days_ago": newest["launch_date_days_ago"],
                    "lifecycle_label": newest["lifecycle_label"],
                },
                "oldest_farm": {
                    "protocol": oldest["protocol"],
                    "pair":     oldest["pair"],
                    "launch_date_days_ago": oldest["launch_date_days_ago"],
                    "lifecycle_label": oldest["lifecycle_label"],
                },
                "average_tvl_retention": avg_tvl_retention,
                "zombie_count": zombie_count,
                "sunset_count": sunset_count,
                "total_farms": len(analyzed),
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self._append_log(result, log_path)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_log(self, result: dict, log_path: str) -> None:
        """Append entry to ring-buffer log (cap=100, atomic write)."""
        log = _load_log(log_path)
        entry = {
            "timestamp": result.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S")),
            "total_farms": result["aggregates"].get("total_farms", 0),
            "average_tvl_retention": result["aggregates"].get("average_tvl_retention", 0.0),
            "zombie_count": result["aggregates"].get("zombie_count", 0),
            "sunset_count": result["aggregates"].get("sunset_count", 0),
        }
        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(log_path, log)
