"""
MP-916: DeFi Protocol Adoption Tracker
Tracks adoption metrics for DeFi protocols: user growth, TVL trends,
stickiness, network effects, and adoption velocity.
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

import json
import os
import math
from spa_core.utils import clock

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_adoption_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Adoption labels (based on user_growth_rate_pct monthly)
# --------------------------------------------------------------------------- #
LABEL_HYPERGROWTH = "HYPERGROWTH"
LABEL_GROWING = "GROWING"
LABEL_STABLE = "STABLE"
LABEL_DECLINING = "DECLINING"
LABEL_DYING = "DYING"

# --------------------------------------------------------------------------- #
# Flags
# --------------------------------------------------------------------------- #
FLAG_USER_EXODUS = "USER_EXODUS"
FLAG_TVL_SURGE = "TVL_SURGE"
FLAG_LOW_RETENTION = "LOW_RETENTION"
FLAG_VIRAL_GROWTH = "VIRAL_GROWTH"
FLAG_MULTI_CHAIN_EXPANSION = "MULTI_CHAIN_EXPANSION"


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    """Safe division returning default when denominator is zero."""
    if den == 0:
        return default
    return num / den


def _growth_rate_pct(current: float, previous: float) -> float:
    """Percent growth from previous to current value."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return (current - previous) / abs(previous) * 100.0


def _adoption_velocity_score(
    user_growth_pct: float,
    tvl_growth_pct: float,
    new_user_ratio: float,
) -> float:
    """
    Adoption velocity score 0-100.
    Combines user growth (50%), TVL growth (30%), new user ratio (20%).
    """
    # Normalise each component to 0-100 scale
    ug = min(max((user_growth_pct + 100) / 2, 0), 100)   # -100..+100 → 0..100
    tg = min(max((tvl_growth_pct + 100) / 2, 0), 100)
    nu = min(max(new_user_ratio * 100, 0), 100)
    return round(0.5 * ug + 0.3 * tg + 0.2 * nu, 2)


def _stickiness_score(retention_rate_pct: float) -> float:
    """Stickiness 0-100 directly from retention_rate_pct (0-100)."""
    return round(min(max(retention_rate_pct, 0.0), 100.0), 2)


def _network_effect_score(
    unique_users_all_time: float,
    integrations_count: int,
    chain_count: int,
) -> float:
    """
    Network effect 0-100.
    Based on log(users) * integrations * chains, capped at 100.
    """
    if unique_users_all_time <= 0:
        return 0.0
    log_users = math.log10(max(unique_users_all_time, 1))
    raw = log_users * integrations_count * chain_count
    # Calibrate: score of 100 at raw ≈ 150 (log10(1e6)=6, integrations=5, chains=5)
    calibrated = raw / 150.0 * 100.0
    return round(min(max(calibrated, 0.0), 100.0), 2)


def _adoption_label(user_growth_pct: float) -> str:
    """Assign adoption label based on 30-day user growth rate."""
    if user_growth_pct > 100:
        return LABEL_HYPERGROWTH
    if user_growth_pct > 10:
        return LABEL_GROWING
    if user_growth_pct >= -5:
        return LABEL_STABLE
    if user_growth_pct >= -30:
        return LABEL_DECLINING
    return LABEL_DYING


def _compute_flags(
    user_growth_pct: float,
    tvl_growth_pct: float,
    retention_rate_pct: float,
    new_user_ratio: float,
    chain_count: int,
) -> list:
    flags = []
    if user_growth_pct < -20:
        flags.append(FLAG_USER_EXODUS)
    if tvl_growth_pct > 50:
        flags.append(FLAG_TVL_SURGE)
    if retention_rate_pct < 20:
        flags.append(FLAG_LOW_RETENTION)
    if new_user_ratio > 0.8:
        flags.append(FLAG_VIRAL_GROWTH)
    if chain_count > 3:
        flags.append(FLAG_MULTI_CHAIN_EXPANSION)
    return flags


def _analyse_protocol(proto: dict) -> dict:
    """Compute derived metrics for a single protocol dict."""
    name = proto.get("name", "unknown")
    unique_users_30d = float(proto.get("unique_users_30d", 0))
    unique_users_90d = float(proto.get("unique_users_90d", 0))
    unique_users_all_time = float(proto.get("unique_users_all_time", 0))
    transactions_30d = int(proto.get("transactions_30d", 0))
    tvl_usd = float(proto.get("tvl_usd", 0))
    tvl_30d_ago_usd = float(proto.get("tvl_30d_ago_usd", 0))
    retention_rate_pct = float(proto.get("retention_rate_pct", 0))
    new_users_30d = float(proto.get("new_users_30d", 0))
    chain_count = int(proto.get("chain_count", 1))
    integrations_count = int(proto.get("integrations_count", 0))

    # Core growth rates
    user_growth_pct = _growth_rate_pct(unique_users_30d, unique_users_90d / 3.0)
    tvl_growth_pct = _growth_rate_pct(tvl_usd, tvl_30d_ago_usd)

    # New user ratio (new / total monthly active)
    new_user_ratio = _safe_div(new_users_30d, unique_users_30d, 0.0)

    # Scores
    adoption_velocity = _adoption_velocity_score(
        user_growth_pct, tvl_growth_pct, new_user_ratio
    )
    stickiness = _stickiness_score(retention_rate_pct)
    network_effect = _network_effect_score(
        unique_users_all_time, integrations_count, chain_count
    )

    # Label & flags
    label = _adoption_label(user_growth_pct)
    flags = _compute_flags(
        user_growth_pct, tvl_growth_pct, retention_rate_pct, new_user_ratio, chain_count
    )

    return {
        "name": name,
        "user_growth_rate_pct": round(user_growth_pct, 2),
        "tvl_growth_rate_pct": round(tvl_growth_pct, 2),
        "new_user_ratio": round(new_user_ratio, 4),
        "adoption_velocity_score": adoption_velocity,
        "stickiness_score": stickiness,
        "network_effect_score": network_effect,
        "adoption_label": label,
        "flags": flags,
        # pass-through raw fields
        "unique_users_30d": unique_users_30d,
        "unique_users_90d": unique_users_90d,
        "unique_users_all_time": unique_users_all_time,
        "transactions_30d": transactions_30d,
        "tvl_usd": tvl_usd,
        "retention_rate_pct": retention_rate_pct,
        "new_users_30d": new_users_30d,
        "chain_count": chain_count,
        "integrations_count": integrations_count,
    }


def _build_aggregates(results: list) -> dict:
    if not results:
        return {
            "fastest_growing": None,
            "most_declining": None,
            "total_ecosystem_users": 0,
            "average_retention": 0.0,
            "hypergrowth_count": 0,
        }

    sorted_by_growth = sorted(results, key=lambda r: r["user_growth_rate_pct"], reverse=True)
    fastest_growing = sorted_by_growth[0]["name"]
    most_declining = sorted_by_growth[-1]["name"]

    total_ecosystem_users = sum(r["unique_users_all_time"] for r in results)
    average_retention = _safe_div(
        sum(r["retention_rate_pct"] for r in results), len(results)
    )
    hypergrowth_count = sum(1 for r in results if r["adoption_label"] == LABEL_HYPERGROWTH)

    return {
        "fastest_growing": fastest_growing,
        "most_declining": most_declining,
        "total_ecosystem_users": total_ecosystem_users,
        "average_retention": round(average_retention, 2),
        "hypergrowth_count": hypergrowth_count,
    }


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append entry to ring-buffer JSON log atomically."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


class DeFiProtocolAdoptionTracker:
    """
    Tracks DeFi protocol adoption metrics across a set of protocols.

    Usage::

        tracker = DeFiProtocolAdoptionTracker()
        result = tracker.track(protocols, config)
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def track(self, protocols: list, config: dict | None = None) -> dict:
        """
        Analyse adoption metrics for a list of protocol dicts.

        Parameters
        ----------
        protocols : list[dict]
            Each dict must contain the keys described in the module docstring.
        config : dict, optional
            Reserved for future configuration (ignored currently).

        Returns
        -------
        dict with keys:
            protocols   – list of per-protocol result dicts
            aggregates  – ecosystem-level aggregates
            timestamp   – ISO-8601 UTC timestamp
        """
        if config is None:
            config = {}

        results = [_analyse_protocol(p) for p in protocols]
        aggregates = _build_aggregates(results)

        timestamp = clock.utcnow().isoformat() + "Z"

        output = {
            "protocols": results,
            "aggregates": aggregates,
            "timestamp": timestamp,
        }

        # Persist to ring-buffer log
        log_entry = {
            "timestamp": timestamp,
            "protocol_count": len(results),
            "aggregates": aggregates,
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return output
