"""
MP-1106  DeFiProtocolRewardDilutionVelocityTracker
--------------------------------------------------
Tracks how fast TVL growth dilutes per-dollar reward rates.  When TVL grows
faster than reward emissions, APY collapses.  Predicts APY trajectory.

Inputs
------
- current_tvl_usd                       : float
- tvl_7d_ago_usd                        : float
- tvl_30d_ago_usd                       : float
- current_reward_emission_usd_per_day   : float
- emission_7d_ago_usd_per_day           : float
- current_apy_pct                       : float
- apy_7d_ago_pct                        : float
- apy_30d_ago_pct                       : float
- protocol_name                         : str

Outputs
-------
- tvl_growth_7d_pct       : float
- tvl_growth_30d_pct      : float
- emission_change_7d_pct  : float
- apy_decay_7d_pct        : float  (negative = declining)
- apy_decay_30d_pct       : float
- dilution_velocity_score : float  (TVL growth rate / APY decay rate ratio)
- predicted_apy_30d_pct   : float  (simple extrapolation of 30-day trend)
- dilution_label          : str    (STABLE_APY / MILD_DILUTION / ... / APY_COLLAPSE)

Label by apy_decay_30d_pct
--------------------------
  decay > -10%      → STABLE_APY
  -10% to -25%      → MILD_DILUTION
  -25% to -50%      → MODERATE_DILUTION
  -50% to -75%      → RAPID_DILUTION
  < -75%            → APY_COLLAPSE

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
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
    "reward_dilution_velocity_log.json",
)
_LOG_CAP = 100
_EPS = 1e-9

# Label constants
LABEL_STABLE_APY = "STABLE_APY"
LABEL_MILD_DILUTION = "MILD_DILUTION"
LABEL_MODERATE_DILUTION = "MODERATE_DILUTION"
LABEL_RAPID_DILUTION = "RAPID_DILUTION"
LABEL_APY_COLLAPSE = "APY_COLLAPSE"

ALL_LABELS = (
    LABEL_STABLE_APY,
    LABEL_MILD_DILUTION,
    LABEL_MODERATE_DILUTION,
    LABEL_RAPID_DILUTION,
    LABEL_APY_COLLAPSE,
)

# Label boundary thresholds (apy_decay_30d_pct)
_THRESHOLD_STABLE = -10.0
_THRESHOLD_MILD = -25.0
_THRESHOLD_MODERATE = -50.0
_THRESHOLD_RAPID = -75.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce *val* to float; return *default* on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _pct_change(current: float, prior: float) -> float:
    """((current - prior) / |prior|) * 100; returns 0.0 when prior ≈ 0."""
    if abs(prior) < _EPS:
        return 0.0
    return (current - prior) / abs(prior) * 100.0


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap = _LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, list):
                data = []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = []
    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(abs_path))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Metric computation functions (all pure, testable independently)
# ---------------------------------------------------------------------------

def _compute_tvl_growth_7d_pct(current_tvl: float, tvl_7d_ago: float) -> float:
    """Percentage change in TVL over 7 days."""
    return _pct_change(current_tvl, tvl_7d_ago)


def _compute_tvl_growth_30d_pct(current_tvl: float, tvl_30d_ago: float) -> float:
    """Percentage change in TVL over 30 days."""
    return _pct_change(current_tvl, tvl_30d_ago)


def _compute_emission_change_7d_pct(
    current_emission: float, emission_7d_ago: float
) -> float:
    """Percentage change in reward emission over 7 days."""
    return _pct_change(current_emission, emission_7d_ago)


def _compute_apy_decay_7d_pct(current_apy: float, apy_7d_ago: float) -> float:
    """(current - 7d_ago) / |7d_ago| * 100.  Negative means APY is falling."""
    return _pct_change(current_apy, apy_7d_ago)


def _compute_apy_decay_30d_pct(current_apy: float, apy_30d_ago: float) -> float:
    """(current - 30d_ago) / |30d_ago| * 100.  Negative means APY is falling."""
    return _pct_change(current_apy, apy_30d_ago)


def _compute_dilution_velocity_score(
    tvl_growth_7d_pct: float,
    apy_decay_7d_pct: float,
) -> float:
    """
    Ratio of TVL growth rate to APY decay magnitude over 7 days, clamped to
    [0, 100].  Higher score = TVL growing much faster than APY is falling
    (more dilution pressure per unit of observed APY drop).

    Only positive TVL growth counts — shrinking TVL actually reduces dilution.
    When APY is flat (|decay| ≈ 0) and TVL is growing, the score equals the
    TVL growth percentage (capped at 100), representing latent dilution
    pressure before the APY has yet to respond.
    """
    tvl_growth = max(0.0, tvl_growth_7d_pct)
    decay_mag = abs(apy_decay_7d_pct)
    if decay_mag < _EPS:
        # APY has not yet reacted; dilution pressure proportional to TVL surge.
        return min(100.0, tvl_growth)
    return min(100.0, tvl_growth / decay_mag)


def _compute_predicted_apy_30d_pct(
    current_apy: float,
    apy_30d_ago: float,
) -> float:
    """
    Simple linear extrapolation of the 30-day APY trend for another 30 days.

    Method: daily_change = (current - apy_30d_ago) / 30
            predicted    = current + daily_change * 30
                         = 2 * current - apy_30d_ago

    Result clamped at 0 (APY cannot go negative).
    """
    predicted = 2.0 * current_apy - apy_30d_ago
    return max(0.0, predicted)


def _compute_dilution_label(apy_decay_30d_pct: float) -> str:
    """
    Classify dilution severity by 30-day APY decay.

    apy_decay_30d_pct > -10%    → STABLE_APY
    -10% ≥ decay > -25%         → MILD_DILUTION
    -25% ≥ decay > -50%         → MODERATE_DILUTION
    -50% ≥ decay > -75%         → RAPID_DILUTION
    decay ≤ -75%                → APY_COLLAPSE
    """
    if apy_decay_30d_pct > _THRESHOLD_STABLE:
        return LABEL_STABLE_APY
    elif apy_decay_30d_pct > _THRESHOLD_MILD:
        return LABEL_MILD_DILUTION
    elif apy_decay_30d_pct > _THRESHOLD_MODERATE:
        return LABEL_MODERATE_DILUTION
    elif apy_decay_30d_pct > _THRESHOLD_RAPID:
        return LABEL_RAPID_DILUTION
    else:
        return LABEL_APY_COLLAPSE


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------

def analyze(
    data: dict | None = None,
    config: dict | None = None,
    *,
    current_tvl_usd: float | None = None,
    tvl_7d_ago_usd: float | None = None,
    tvl_30d_ago_usd: float | None = None,
    current_reward_emission_usd_per_day: float | None = None,
    emission_7d_ago_usd_per_day: float | None = None,
    current_apy_pct: float | None = None,
    apy_7d_ago_pct: float | None = None,
    apy_30d_ago_pct: float | None = None,
    protocol_name: str | None = None,
) -> dict:
    """
    Compute reward dilution velocity metrics for a DeFi protocol.

    Inputs may be supplied as a *data* dict and/or via keyword arguments
    (keywords take precedence over dict values).

    Returns a complete result dict.  Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)
    d = data if isinstance(data, dict) else {}

    def _pick(kw: Any, key: str, default: float = 0.0) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(d.get(key, default), default)

    name = (
        protocol_name
        if protocol_name is not None
        else str(d.get("protocol_name", "UNKNOWN"))
    )

    cur_tvl = max(0.0, _pick(current_tvl_usd, "current_tvl_usd"))
    tvl_7d = max(0.0, _pick(tvl_7d_ago_usd, "tvl_7d_ago_usd"))
    tvl_30d = max(0.0, _pick(tvl_30d_ago_usd, "tvl_30d_ago_usd"))
    cur_emission = max(
        0.0, _pick(current_reward_emission_usd_per_day, "current_reward_emission_usd_per_day")
    )
    emission_7d = max(
        0.0, _pick(emission_7d_ago_usd_per_day, "emission_7d_ago_usd_per_day")
    )
    cur_apy = max(0.0, _pick(current_apy_pct, "current_apy_pct"))
    apy_7d = max(0.0, _pick(apy_7d_ago_pct, "apy_7d_ago_pct"))
    apy_30d = max(0.0, _pick(apy_30d_ago_pct, "apy_30d_ago_pct"))

    tvl_growth_7d = _compute_tvl_growth_7d_pct(cur_tvl, tvl_7d)
    tvl_growth_30d = _compute_tvl_growth_30d_pct(cur_tvl, tvl_30d)
    emission_change_7d = _compute_emission_change_7d_pct(cur_emission, emission_7d)
    apy_decay_7d = _compute_apy_decay_7d_pct(cur_apy, apy_7d)
    apy_decay_30d = _compute_apy_decay_30d_pct(cur_apy, apy_30d)
    dilution_score = _compute_dilution_velocity_score(tvl_growth_7d, apy_decay_7d)
    predicted_apy = _compute_predicted_apy_30d_pct(cur_apy, apy_30d)
    label = _compute_dilution_label(apy_decay_30d)

    result: dict[str, Any] = {
        "protocol_name": name,
        "current_tvl_usd": cur_tvl,
        "tvl_7d_ago_usd": tvl_7d,
        "tvl_30d_ago_usd": tvl_30d,
        "current_reward_emission_usd_per_day": cur_emission,
        "emission_7d_ago_usd_per_day": emission_7d,
        "current_apy_pct": cur_apy,
        "apy_7d_ago_pct": apy_7d,
        "apy_30d_ago_pct": apy_30d,
        "tvl_growth_7d_pct": tvl_growth_7d,
        "tvl_growth_30d_pct": tvl_growth_30d,
        "emission_change_7d_pct": emission_change_7d,
        "apy_decay_7d_pct": apy_decay_7d,
        "apy_decay_30d_pct": apy_decay_30d,
        "dilution_velocity_score": dilution_score,
        "predicted_apy_30d_pct": predicted_apy,
        "dilution_label": label,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory — never crash caller

    return result


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolRewardDilutionVelocityTracker:
    """
    Object-oriented wrapper around the functional ``analyze`` function.

    >>> tracker = DeFiProtocolRewardDilutionVelocityTracker()
    >>> result = tracker.analyze({"protocol_name": "Aave-V3", ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, data: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(data, config=self._config, **kwargs)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    import sys

    _sample = {
        "protocol_name": "Aave-V3-USDC",
        "current_tvl_usd": 500_000_000.0,
        "tvl_7d_ago_usd": 400_000_000.0,
        "tvl_30d_ago_usd": 300_000_000.0,
        "current_reward_emission_usd_per_day": 50_000.0,
        "emission_7d_ago_usd_per_day": 52_000.0,
        "current_apy_pct": 3.5,
        "apy_7d_ago_pct": 4.8,
        "apy_30d_ago_pct": 7.0,
    }
    print(_json.dumps(analyze(_sample), indent=2, default=str))
    sys.exit(0)
