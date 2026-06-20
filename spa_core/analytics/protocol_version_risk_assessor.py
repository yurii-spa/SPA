"""
MP-783: ProtocolVersionRiskAssessor
Assesses deployment risk for specific protocol versions.

Scoring (max 100 pts before penalty):
  maturity_score   0-40  based on days_since_release  (40 pts at ≥ 365 days)
  security_score   0-40  based on audit_count (0-20) + audit recency (0-20)
  adoption_score   0-20  based on log-scale TVS       (20 pts at ≥ $1 B)

  total_version_score = max(0, raw_score - 20 × known_vulnerabilities)

Risk tiers:
  BATTLE_TESTED  >= 80
  ESTABLISHED    >= 60
  MATURING       >= 40
  EXPERIMENTAL   <  40

Pure stdlib.  Atomic write (tmp + os.replace).  Ring-buffer log capped at 100.
"""

import json
import math
import os
import time
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_version_risk_log.json"
)

RING_BUFFER_SIZE = 100

VULNERABILITY_PENALTY = 20  # pts per known vulnerability

# Tier thresholds
_TIER_BATTLE_TESTED = 80
_TIER_ESTABLISHED   = 60
_TIER_MATURING      = 40

TIER_BATTLE_TESTED = "BATTLE_TESTED"
TIER_ESTABLISHED   = "ESTABLISHED"
TIER_MATURING      = "MATURING"
TIER_EXPERIMENTAL  = "EXPERIMENTAL"

# Scoring sub-maxima
_MATURITY_MAX  = 40.0
_AUDIT_MAX     = 20.0   # audit_count component
_RECENCY_MAX   = 20.0   # last_audit recency component
_ADOPTION_MAX  = 20.0

_MATURITY_FULL_DAYS    = 365.0   # days for full maturity score
_AUDIT_PTS_EACH        = 5.0     # pts per audit (capped at 4 audits)
_RECENCY_FULL_DAYS     = 365.0   # 0 days ago → full recency; 365+ → 0
_ADOPTION_LOG_LOW      = 5.0     # log10($100 K) → 0 pts
_ADOPTION_LOG_HIGH     = 9.0     # log10($1 B)   → 20 pts


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _load_log(path: str) -> List:
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Pure scoring functions (importable for tests)
# ---------------------------------------------------------------------------

def compute_maturity_score(days_since_release: float) -> float:
    """
    0–40 pts.  Linear ramp from 0 to 40 over the first 365 days.
    Capped at 40 pts for any duration >= 365 days.
    """
    if days_since_release <= 0:
        return 0.0
    return min(_MATURITY_MAX, (days_since_release / _MATURITY_FULL_DAYS) * _MATURITY_MAX)


def compute_security_score(audit_count: int, last_audit_days_ago: float) -> float:
    """
    0–40 pts total split equally:
      audit_count component (0-20 pts): 5 pts each, capped at 4 audits.
      recency    component  (0-20 pts): linear decay over 365 days.
        If audit_count == 0 → recency pts = 0 (no audit to be recent).
    """
    audit_pts = min(_AUDIT_MAX, float(max(0, audit_count)) * _AUDIT_PTS_EACH)

    if audit_count <= 0:
        recency_pts = 0.0
    else:
        days = max(0.0, float(last_audit_days_ago))
        recency_pts = max(0.0, _RECENCY_MAX * (1.0 - days / _RECENCY_FULL_DAYS))

    return audit_pts + recency_pts


def compute_adoption_score(total_value_secured_usd: float) -> float:
    """
    0–20 pts using a log-scale of TVS.
    < $100 K (10^5) → 0 pts
    $1 B   (10^9) → 20 pts
    Linear interpolation between log10=5 and log10=9.
    """
    if total_value_secured_usd <= 0:
        return 0.0
    log_tvs = math.log10(total_value_secured_usd)
    log_range = _ADOPTION_LOG_HIGH - _ADOPTION_LOG_LOW          # 4 decades
    raw = (log_tvs - _ADOPTION_LOG_LOW) / log_range * _ADOPTION_MAX
    return max(0.0, min(_ADOPTION_MAX, raw))


def classify_risk_tier(score: float) -> str:
    """Map a total_version_score to a risk tier label."""
    if score >= _TIER_BATTLE_TESTED:
        return TIER_BATTLE_TESTED
    if score >= _TIER_ESTABLISHED:
        return TIER_ESTABLISHED
    if score >= _TIER_MATURING:
        return TIER_MATURING
    return TIER_EXPERIMENTAL


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolVersionRiskAssessor:
    """
    MP-783: Assesses deployment risk for specific protocol versions.

    Scoring components:
      maturity_score   0-40   (days since release)
      security_score   0-40   (audit count + recency)
      adoption_score   0-20   (TVS log-scale)

    Penalty: -20 pts × known_vulnerabilities (floor 0).

    Risk tiers: BATTLE_TESTED / ESTABLISHED / MATURING / EXPERIMENTAL.

    Usage
    -----
    assessor = ProtocolVersionRiskAssessor()
    result   = assessor.assess(protocol_data)
    tier     = assessor.get_risk_tier()
    breakdown= assessor.get_score_breakdown()
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file: str = os.path.abspath(data_file or _DEFAULT_DATA_FILE)
        self._log: List[Dict] = _load_log(self._data_file)
        self._last_result: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, protocol_data: Dict) -> Dict:
        """
        Assess risk for a protocol version.

        Required keys (all have defaults if absent):
          protocol               (str)   – e.g. "Aave"
          version_string         (str)   – e.g. "v3.1"
          days_since_release     (float) – calendar days the version has been live
          total_value_secured_usd(float) – total TVS in USD
          known_vulnerabilities  (int)   – count of public known vulnerabilities
          audit_count            (int)   – number of completed security audits
          last_audit_days_ago    (float) – days since the most recent audit

        Returns a result dict with score_breakdown, total_version_score, risk_tier.
        Appends result to ring-buffer log (atomic write).
        """
        protocol               = str(protocol_data.get("protocol", "UNKNOWN"))
        version_string         = str(protocol_data.get("version_string", "unknown"))
        days_since_release     = float(protocol_data.get("days_since_release", 0))
        total_value_secured    = float(protocol_data.get("total_value_secured_usd", 0))
        known_vulnerabilities  = int(protocol_data.get("known_vulnerabilities", 0))
        audit_count            = int(protocol_data.get("audit_count", 0))
        last_audit_days_ago    = float(protocol_data.get("last_audit_days_ago", 9999))

        maturity_score  = compute_maturity_score(days_since_release)
        security_score  = compute_security_score(audit_count, last_audit_days_ago)
        adoption_score  = compute_adoption_score(total_value_secured)

        raw_score    = maturity_score + security_score + adoption_score
        vuln_penalty = float(VULNERABILITY_PENALTY * max(0, known_vulnerabilities))
        total_version_score = max(0.0, raw_score - vuln_penalty)

        risk_tier = classify_risk_tier(total_version_score)

        result: Dict = {
            "protocol":               protocol,
            "version_string":         version_string,
            "days_since_release":     days_since_release,
            "total_value_secured_usd": total_value_secured,
            "known_vulnerabilities":  known_vulnerabilities,
            "audit_count":            audit_count,
            "last_audit_days_ago":    last_audit_days_ago,
            "score_breakdown": {
                "maturity_score":       maturity_score,
                "security_score":       security_score,
                "adoption_score":       adoption_score,
                "raw_score":            raw_score,
                "vuln_penalty":         vuln_penalty,
                "total_version_score":  total_version_score,
            },
            "total_version_score": total_version_score,
            "risk_tier":           risk_tier,
            "timestamp":           time.time(),
        }

        self._last_result = result
        self._log.append(result)
        if len(self._log) > RING_BUFFER_SIZE:
            self._log = self._log[-RING_BUFFER_SIZE:]
        _atomic_write_json(self._data_file, self._log)
        return result

    def get_risk_tier(self) -> Optional[str]:
        """Return the risk tier from the most recent assess() call, or None."""
        if self._last_result is None:
            return None
        return self._last_result["risk_tier"]

    def get_score_breakdown(self) -> Optional[Dict]:
        """Return a copy of the score breakdown from the most recent assess() call."""
        if self._last_result is None:
            return None
        return dict(self._last_result["score_breakdown"])

    def get_log(self) -> List[Dict]:
        """Return a shallow copy of the in-memory ring-buffer log."""
        return list(self._log)
