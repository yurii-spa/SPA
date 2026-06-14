"""
MP-794: BridgeRiskAssessor
Assesses risk of using specific cross-chain bridges.

Read-only analytics module — stdlib only, atomic writes, ring buffer 100.

Scoring breakdown (max 100 pts):
  incident_component = max(0, 40 − incident_penalty)   [0–40]
  audit_score        = min(30, audit_count × 10) − stale_penalty  [0–30]
  usage_score        = log-scale of daily_volume_usd   [0–20]
  type_score         = NATIVE:10 | LIQUIDITY:7 | LOCK_MINT:4     [4–10]
  total_bridge_score = incident_component + audit_score + usage_score + type_score
                       capped [0, 100]

Tiers:
  TRUSTED      >= 75
  ESTABLISHED  >= 50
  CAUTION      >= 25
  AVOID        <  25
"""

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIDGE_TIER_TRUSTED = "TRUSTED"
BRIDGE_TIER_ESTABLISHED = "ESTABLISHED"
BRIDGE_TIER_CAUTION = "CAUTION"
BRIDGE_TIER_AVOID = "AVOID"

BRIDGE_TYPE_NATIVE = "NATIVE"
BRIDGE_TYPE_LIQUIDITY = "LIQUIDITY"
BRIDGE_TYPE_LOCK_MINT = "LOCK_MINT"

_TYPE_SCORES: Dict[str, int] = {
    BRIDGE_TYPE_NATIVE: 10,
    BRIDGE_TYPE_LIQUIDITY: 7,
    BRIDGE_TYPE_LOCK_MINT: 4,
}

# Incidents within this window are considered "recent" (weighted 2×)
_RECENT_WINDOW_SECONDS: float = 365.0 * 24.0 * 3600.0  # 1 year

# log₁₀ of the reference volume for a full 20-pt usage score ($100 M)
_USAGE_LOG_REF: float = 8.0  # log10(100_000_000)

_DEFAULT_LOG_PATH = "data/bridge_risk_log.json"
_DEFAULT_MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_bridge_tier(score: float) -> str:
    if score >= 75.0:
        return BRIDGE_TIER_TRUSTED
    elif score >= 50.0:
        return BRIDGE_TIER_ESTABLISHED
    elif score >= 25.0:
        return BRIDGE_TIER_CAUTION
    else:
        return BRIDGE_TIER_AVOID


def _compute_incident_penalty(
    incidents: List[Dict[str, Any]],
    tvb: float,
    now: Optional[float] = None,
) -> float:
    """
    Return incident penalty in [0, 40].

    Logic:
      • Each incident contributes loss_usd × weight.
      • Recent incidents (within _RECENT_WINDOW_SECONDS) have weight 2, older weight 1.
      • weighted_loss / tvb × 100 gives the penalty (capped at 40).
      • If tvb ≤ 0 and there are any incidents → full penalty (40).
    """
    if not incidents:
        return 0.0

    _now = now if now is not None else time.time()
    cutoff = _now - _RECENT_WINDOW_SECONDS

    weighted_loss = 0.0
    for inc in incidents:
        loss = float(inc.get("loss_usd", 0.0))
        date_ts = float(inc.get("date_ts", 0.0))
        weight = 2.0 if date_ts >= cutoff else 1.0
        weighted_loss += loss * weight

    if tvb <= 0.0:
        return 40.0 if weighted_loss > 0.0 else 0.0

    loss_ratio = weighted_loss / tvb
    # 40 % of TVB → max penalty
    return min(40.0, loss_ratio * 100.0)


def _compute_audit_score(audit_count: int, days_since_last_audit: float) -> float:
    """
    Return audit score in [0, 30].
    base = min(30, audit_count × 10)
    penalty of 10 pts if days_since_last_audit > 180.
    """
    base = min(30, audit_count * 10)
    if days_since_last_audit > 180.0:
        base = max(0, base - 10)
    return float(base)


def _compute_usage_score(daily_volume_usd: float) -> float:
    """
    Return usage score in [0, 20] on a log₁₀ scale.
    Reference: $100 M daily volume → full 20 pts.
    """
    if daily_volume_usd <= 0.0:
        return 0.0
    log_vol = math.log10(max(1.0, daily_volume_usd))
    score = (log_vol / _USAGE_LOG_REF) * 20.0
    return max(0.0, min(20.0, score))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class BridgeRiskAssessor:
    """
    Assesses cross-chain bridge risk and assigns a composite score + tier.

    Usage::

        assessor = BridgeRiskAssessor()
        result   = assessor.assess(bridge_data)
        tier     = assessor.get_bridge_tier()
        summary  = assessor.get_risk_summary()

    Ring-buffer log is written atomically (tmp + os.replace) to *log_path*,
    capped at *max_entries* entries.
    """

    def __init__(
        self,
        log_path: str = _DEFAULT_LOG_PATH,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.log_path = log_path
        self.max_entries = int(max_entries)
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(
        self,
        bridge_data: Dict[str, Any],
        _now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Assess *bridge_data* and return a risk result dict.

        Expected keys in *bridge_data*:
          bridge_name            – str
          total_value_bridged_usd– float  (TVB)
          incident_history       – list[{date_ts, loss_usd, type}]
          audit_count            – int
          days_since_last_audit  – float
          bridge_type            – LOCK_MINT | LIQUIDITY | NATIVE
          daily_volume_usd       – float
        """
        bridge_name = str(bridge_data.get("bridge_name", "unknown"))
        tvb = float(bridge_data.get("total_value_bridged_usd", 0.0))
        incidents: List[Dict[str, Any]] = list(
            bridge_data.get("incident_history", [])
        )
        audit_count = int(bridge_data.get("audit_count", 0))
        days_since_last_audit = float(
            bridge_data.get("days_since_last_audit", 9999.0)
        )
        bridge_type = str(
            bridge_data.get("bridge_type", BRIDGE_TYPE_LOCK_MINT)
        )
        daily_volume_usd = float(bridge_data.get("daily_volume_usd", 0.0))

        _ts = _now if _now is not None else time.time()

        # Sub-scores
        incident_penalty = _compute_incident_penalty(incidents, tvb, now=_ts)
        audit_score = _compute_audit_score(audit_count, days_since_last_audit)
        usage_score = _compute_usage_score(daily_volume_usd)
        type_score = _TYPE_SCORES.get(bridge_type, _TYPE_SCORES[BRIDGE_TYPE_LOCK_MINT])

        # Composite score
        incident_component = max(0.0, 40.0 - incident_penalty)
        total_score = incident_component + audit_score + usage_score + type_score
        total_score = max(0.0, min(100.0, total_score))

        tier = _get_bridge_tier(total_score)

        result: Dict[str, Any] = {
            "timestamp": _ts,
            "bridge_name": bridge_name,
            "total_value_bridged_usd": tvb,
            "bridge_type": bridge_type,
            "daily_volume_usd": daily_volume_usd,
            "incident_count": len(incidents),
            "incident_penalty": round(incident_penalty, 6),
            "incident_component": round(incident_component, 6),
            "audit_score": round(audit_score, 6),
            "usage_score": round(usage_score, 6),
            "type_score": type_score,
            "total_bridge_score": round(total_score, 6),
            "bridge_tier": tier,
        }

        self._last_result = result
        self._append_to_log(result)
        return result

    def get_bridge_tier(self) -> Optional[str]:
        """Return the tier from the last *assess()* call, or None."""
        if self._last_result is None:
            return None
        return self._last_result.get("bridge_tier")

    def get_risk_summary(self) -> Dict[str, Any]:
        """
        Return a concise risk summary from the last *assess()* call.
        Returns {} if *assess()* hasn't been called yet.
        """
        if self._last_result is None:
            return {}
        r = self._last_result
        return {
            "bridge_name": r["bridge_name"],
            "total_bridge_score": r["total_bridge_score"],
            "bridge_tier": r["bridge_tier"],
            "incident_penalty": r["incident_penalty"],
            "audit_score": r["audit_score"],
            "usage_score": r["usage_score"],
            "type_score": r["type_score"],
            "incident_count": r["incident_count"],
        }

    # ------------------------------------------------------------------
    # Persistence helpers (atomic ring-buffer)
    # ------------------------------------------------------------------

    def _load_log(self) -> List[Dict[str, Any]]:
        try:
            with open(self.log_path, "r") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def _append_to_log(self, entry: Dict[str, Any]) -> None:
        log = self._load_log()
        log.append(entry)
        if len(log) > self.max_entries:
            log = log[-self.max_entries :]
        self._atomic_write(log)

    def _atomic_write(self, data: Any) -> None:
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(path) + ".tmp"
        try:
            with open(tmp_path, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
