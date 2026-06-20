"""
MP-977: ProtocolUpgradeImpactAssessor

Advisory/read-only module. Assesses the impact of upcoming or past DeFi protocol
upgrades: urgency, disruption severity, preparedness, and net risk—helping operators
plan around governance events before they affect yield positions.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "upgrade_impact_log.json"
)

# ---------------------------------------------------------------------------
# Valid upgrade types
# ---------------------------------------------------------------------------
_VALID_UPGRADE_TYPES = {
    "fee_change",
    "collateral_factor",
    "rate_model",
    "oracle",
    "smart_contract",
    "tokenomics",
    "governance",
}

# ---------------------------------------------------------------------------
# Impact labels
# ---------------------------------------------------------------------------
_LABEL_SMOOTH = "SMOOTH_TRANSITION"
_LABEL_LOW = "LOW_IMPACT"
_LABEL_MODERATE = "MODERATE_DISRUPTION"
_LABEL_HIGH = "HIGH_IMPACT"
_LABEL_CRITICAL = "CRITICAL_UPGRADE"

# ---------------------------------------------------------------------------
# Flag constants
# ---------------------------------------------------------------------------
FLAG_USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
FLAG_NO_AUDIT = "NO_AUDIT"
FLAG_LOW_COMMUNITY_SUPPORT = "LOW_COMMUNITY_SUPPORT"
FLAG_IMMINENT = "IMMINENT"
FLAG_REPEAT_ISSUES = "REPEAT_ISSUES"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


class ProtocolUpgradeImpactAssessor:
    """Assess the impact of DeFi protocol upgrades on yield and risk."""

    def __init__(self, data_file: Optional[str] = None):
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, upgrades: List[dict], config: Optional[dict] = None) -> dict:
        """
        Assess impact of protocol upgrades.

        Parameters
        ----------
        upgrades : list[dict]
            Each dict must contain:
              protocol, upgrade_type, scheduled_date_days (negative = past),
              magnitude_score (1-10), affected_tvl_usd, user_action_required (bool),
              migration_period_days, historical_similar_upgrades_count,
              last_upgrade_issues_count, community_approval_pct, has_audit (bool)
        config : dict, optional
            Optional overrides for thresholds.

        Returns
        -------
        dict with keys: assessments (list), aggregates (dict), run_ts (str)
        """
        if config is None:
            config = {}

        imminent_days = int(config.get("imminent_days_threshold", 7))
        low_community_pct = float(config.get("low_community_support_threshold", 60.0))
        critical_net_risk = float(config.get("critical_net_risk_threshold", 70.0))
        smooth_net_risk = float(config.get("smooth_net_risk_threshold", 20.0))
        low_impact_net_risk = float(config.get("low_impact_net_risk_threshold", 40.0))
        moderate_net_risk = float(config.get("moderate_net_risk_threshold", 60.0))

        assessments = []
        for u in upgrades:
            result = self._assess_upgrade(
                u,
                imminent_days=imminent_days,
                low_community_pct=low_community_pct,
                critical_net_risk=critical_net_risk,
                smooth_net_risk=smooth_net_risk,
                low_impact_net_risk=low_impact_net_risk,
                moderate_net_risk=moderate_net_risk,
            )
            assessments.append(result)

        aggregates = self._compute_aggregates(assessments)
        run_ts = datetime.now(timezone.utc).isoformat()

        output = {
            "assessments": assessments,
            "aggregates": aggregates,
            "run_ts": run_ts,
            "upgrade_count": len(assessments),
        }

        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    # Upgrade evaluation
    # ------------------------------------------------------------------

    def _assess_upgrade(
        self,
        u: dict,
        *,
        imminent_days: int,
        low_community_pct: float,
        critical_net_risk: float,
        smooth_net_risk: float,
        low_impact_net_risk: float,
        moderate_net_risk: float,
    ) -> dict:
        protocol = str(u.get("protocol", "unknown"))
        upgrade_type = str(u.get("upgrade_type", "smart_contract"))
        scheduled_date_days = int(u.get("scheduled_date_days", 0))
        magnitude = float(u.get("magnitude_score", 5.0))
        affected_tvl = float(u.get("affected_tvl_usd", 0.0))
        user_action = bool(u.get("user_action_required", False))
        migration_days = int(u.get("migration_period_days", 0))
        historical_count = int(u.get("historical_similar_upgrades_count", 0))
        last_issues = int(u.get("last_upgrade_issues_count", 0))
        community_pct = float(u.get("community_approval_pct", 50.0))
        has_audit = bool(u.get("has_audit", False))

        # Urgency score: closer to 0 days = higher urgency
        urgency_score = self._compute_urgency(scheduled_date_days)

        # Disruption score: magnitude × TVL factor
        disruption_score = self._compute_disruption(magnitude, affected_tvl)

        # Preparedness score: audit + community approval + migration period
        preparedness_score = self._compute_preparedness(
            has_audit=has_audit,
            community_pct=community_pct,
            migration_days=migration_days,
            historical_count=historical_count,
        )

        # Net risk score: disruption - preparedness, capped 0-100
        net_risk_score = _clamp(disruption_score - preparedness_score * 0.5)

        # Impact label
        label = self._compute_label(
            net_risk_score=net_risk_score,
            user_action=user_action,
            critical_net_risk=critical_net_risk,
            smooth_net_risk=smooth_net_risk,
            low_impact_net_risk=low_impact_net_risk,
            moderate_net_risk=moderate_net_risk,
        )

        # Flags
        flags = self._compute_flags(
            user_action=user_action,
            has_audit=has_audit,
            community_pct=community_pct,
            scheduled_date_days=scheduled_date_days,
            last_issues=last_issues,
            imminent_days=imminent_days,
            low_community_pct=low_community_pct,
        )

        return {
            "protocol": protocol,
            "upgrade_type": upgrade_type,
            "scheduled_date_days": scheduled_date_days,
            "magnitude_score": magnitude,
            "affected_tvl_usd": affected_tvl,
            "user_action_required": user_action,
            "migration_period_days": migration_days,
            "community_approval_pct": community_pct,
            "has_audit": has_audit,
            "urgency_score": round(urgency_score, 4),
            "disruption_score": round(disruption_score, 4),
            "preparedness_score": round(preparedness_score, 4),
            "net_risk_score": round(net_risk_score, 4),
            "label": label,
            "flags": flags,
        }

    def _compute_urgency(self, scheduled_date_days: int) -> float:
        """
        Urgency increases as |days| approaches 0.
        Days=0 => 100, days>=90 => ~0
        """
        abs_days = abs(scheduled_date_days)
        if abs_days == 0:
            return 100.0
        # Exponential decay: urgency = 100 * e^(-abs_days / 20)
        urgency = 100.0 * math.exp(-abs_days / 20.0)
        return _clamp(urgency)

    def _compute_disruption(self, magnitude: float, affected_tvl_usd: float) -> float:
        """
        Disruption = magnitude (1-10, scaled to 0-70) × TVL factor (0-30).
        Total range: 0-100.
        """
        magnitude_component = _clamp(magnitude / 10.0 * 70.0, 0.0, 70.0)

        # TVL factor: log scale, $1B TVL → full 30 points
        if affected_tvl_usd <= 0:
            tvl_component = 0.0
        else:
            tvl_component = _clamp(math.log10(max(affected_tvl_usd, 1)) / 9.0 * 30.0, 0.0, 30.0)

        return _clamp(magnitude_component + tvl_component)

    def _compute_preparedness(
        self,
        *,
        has_audit: bool,
        community_pct: float,
        migration_days: int,
        historical_count: int,
    ) -> float:
        """
        Preparedness: 0-100.
        - Audit present: +40 pts
        - Community approval: up to 30 pts (pct/100 × 30)
        - Migration period: up to 20 pts (log scale, 30d → full 20)
        - Historical upgrades (experience): up to 10 pts
        """
        audit_pts = 40.0 if has_audit else 0.0
        community_pts = _clamp(community_pct / 100.0 * 30.0, 0.0, 30.0)

        if migration_days <= 0:
            migration_pts = 0.0
        else:
            migration_pts = _clamp(
                math.log1p(migration_days) / math.log1p(30) * 20.0, 0.0, 20.0
            )

        historical_pts = _clamp(min(historical_count, 5) / 5.0 * 10.0, 0.0, 10.0)

        return _clamp(audit_pts + community_pts + migration_pts + historical_pts)

    def _compute_label(
        self,
        *,
        net_risk_score: float,
        user_action: bool,
        critical_net_risk: float,
        smooth_net_risk: float,
        low_impact_net_risk: float,
        moderate_net_risk: float,
    ) -> str:
        if user_action and net_risk_score > critical_net_risk:
            return _LABEL_CRITICAL
        if net_risk_score <= smooth_net_risk:
            return _LABEL_SMOOTH
        if net_risk_score <= low_impact_net_risk:
            return _LABEL_LOW
        if net_risk_score <= moderate_net_risk:
            return _LABEL_MODERATE
        return _LABEL_HIGH

    def _compute_flags(
        self,
        *,
        user_action: bool,
        has_audit: bool,
        community_pct: float,
        scheduled_date_days: int,
        last_issues: int,
        imminent_days: int,
        low_community_pct: float,
    ) -> List[str]:
        flags = []

        if user_action:
            flags.append(FLAG_USER_ACTION_REQUIRED)

        if not has_audit:
            flags.append(FLAG_NO_AUDIT)

        if community_pct < low_community_pct:
            flags.append(FLAG_LOW_COMMUNITY_SUPPORT)

        if abs(scheduled_date_days) <= imminent_days:
            flags.append(FLAG_IMMINENT)

        if last_issues > 0:
            flags.append(FLAG_REPEAT_ISSUES)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, assessments: List[dict]) -> dict:
        if not assessments:
            return {
                "highest_impact": None,
                "smoothest": None,
                "total_affected_tvl_usd": 0.0,
                "critical_count": 0,
                "imminent_count": 0,
            }

        sorted_by_risk = sorted(assessments, key=lambda a: a["net_risk_score"], reverse=True)
        total_tvl = sum(a["affected_tvl_usd"] for a in assessments)
        critical_count = sum(1 for a in assessments if a["label"] == _LABEL_CRITICAL)
        imminent_count = sum(1 for a in assessments if FLAG_IMMINENT in a["flags"])

        return {
            "highest_impact": sorted_by_risk[0]["protocol"],
            "smoothest": sorted_by_risk[-1]["protocol"],
            "total_affected_tvl_usd": round(total_tvl, 2),
            "critical_count": critical_count,
            "imminent_count": imminent_count,
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

            atomic_save(log, str(self))
        except Exception:
            # Advisory module — never crash the caller
            pass
