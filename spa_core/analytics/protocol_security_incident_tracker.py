"""
MP-919: Protocol Security Incident Tracker
Tracks security history and scores safety of DeFi protocols.
Pure stdlib, no external dependencies.
"""

import json
import os
from datetime import datetime, timezone

LOG_CAP = 100
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_PATH = os.path.join(_HERE, "..", "..", "data", "security_incident_log.json")

SEVERITY_WEIGHTS = {
    "CRITICAL": 1.0,
    "HIGH": 0.75,
    "MEDIUM": 0.50,
    "LOW": 0.25,
}

TYPE_WEIGHTS = {
    "hack": 1.0,
    "exploit": 0.9,
    "rug": 1.0,
    "oracle": 0.7,
    "governance": 0.5,
}

SAFETY_THRESHOLDS = [
    (80, "VERY_SAFE"),
    (60, "SAFE"),
    (40, "CAUTION"),
    (20, "RISKY"),
    (0,  "AVOID"),
]


class ProtocolSecurityIncidentTracker:
    """Tracks security incidents and scores protocol safety."""

    def __init__(self, log_path: str = None):
        self.log_path = log_path or DEFAULT_LOG_PATH

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def track(self, protocols: list, config: dict = None) -> dict:
        """
        Track security history for a list of protocols.

        Each protocol dict may contain:
            name (str), incidents (list[dict]), total_tvl_peak_usd (float),
            current_tvl_usd (float), bug_bounty_usd (float), audits_count (int),
            last_audit_days_ago (float), insurance_coverage_usd (float)

        Each incident dict:
            date_days_ago (float), type (str: hack/exploit/rug/oracle/governance),
            amount_lost_usd (float), recovered_pct (float 0-100),
            severity (str: LOW/MEDIUM/HIGH/CRITICAL)

        Returns dict with 'results', 'aggregates', 'timestamp', 'protocol_count'.
        """
        config = config or {}
        results = [self._track_protocol(p, config) for p in protocols]
        aggregates = self._compute_aggregates(results)

        output = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(protocols),
        }
        self._append_log(output)
        return output

    # ------------------------------------------------------------------ #
    # Per-protocol scoring
    # ------------------------------------------------------------------ #

    def _track_protocol(self, protocol: dict, config: dict) -> dict:
        name = str(protocol.get("name", "unknown"))
        raw_incidents = protocol.get("incidents", [])
        peak_tvl = float(protocol.get("total_tvl_peak_usd", 1.0))
        current_tvl = float(protocol.get("current_tvl_usd", 0.0))
        bug_bounty = float(protocol.get("bug_bounty_usd", 0.0))
        audits_count = int(protocol.get("audits_count", 0))
        last_audit_days = float(protocol.get("last_audit_days_ago", 9999.0))
        insurance = float(protocol.get("insurance_coverage_usd", 0.0))

        if peak_tvl <= 0:
            peak_tvl = 1.0

        incidents = [self._parse_incident(i) for i in raw_incidents]

        incident_rate_score = self._incident_rate_score(incidents, peak_tvl)
        recovery_rate_pct = self._recovery_rate(incidents)
        security_investment_score = self._security_investment_score(
            bug_bounty, audits_count, last_audit_days, insurance, peak_tvl
        )
        recency_risk = self._recency_risk(incidents)
        composite_safety_score = self._composite_safety(
            incident_rate_score, security_investment_score,
            recency_risk, recovery_rate_pct
        )
        safety_label = self._safety_label(composite_safety_score)
        flags = self._flags(incidents, insurance, audits_count, recovery_rate_pct)

        total_lost = sum(i["amount_lost_usd"] for i in incidents)
        total_recovered = sum(
            i["amount_lost_usd"] * i["recovered_pct"] / 100.0
            for i in incidents
        )

        return {
            "name": name,
            "incident_count": len(incidents),
            "incident_rate_score": round(incident_rate_score, 2),
            "recovery_rate_pct": round(recovery_rate_pct, 2),
            "security_investment_score": round(security_investment_score, 2),
            "recency_risk": round(recency_risk, 2),
            "composite_safety_score": round(composite_safety_score, 2),
            "safety_label": safety_label,
            "flags": flags,
            "total_lost_usd": round(total_lost, 2),
            "total_recovered_usd": round(total_recovered, 2),
        }

    def _parse_incident(self, inc: dict) -> dict:
        return {
            "date_days_ago": float(inc.get("date_days_ago", 9999.0)),
            "type": str(inc.get("type", "hack")),
            "amount_lost_usd": float(inc.get("amount_lost_usd", 0.0)),
            "recovered_pct": float(inc.get("recovered_pct", 0.0)),
            "severity": str(inc.get("severity", "MEDIUM")),
        }

    def _incident_rate_score(self, incidents: list, peak_tvl: float) -> float:
        """0-100; higher = worse."""
        if not incidents:
            return 0.0
        score = 0.0
        for inc in incidents:
            sw = SEVERITY_WEIGHTS.get(inc["severity"], 0.5)
            tw = TYPE_WEIGHTS.get(inc["type"], 0.7)
            loss_ratio = inc["amount_lost_usd"] / max(peak_tvl, 1.0)
            loss_comp = min(30.0, loss_ratio * 100.0 * 3.0)
            score += sw * tw * (10.0 + loss_comp)
        return min(100.0, score)

    def _recovery_rate(self, incidents: list) -> float:
        """Average recovered_pct; 100 if no incidents."""
        if not incidents:
            return 100.0
        return sum(i["recovered_pct"] for i in incidents) / len(incidents)

    def _security_investment_score(self, bug_bounty: float, audits_count: int,
                                    last_audit_days: float, insurance: float,
                                    peak_tvl: float) -> float:
        """0-100; higher = better security investment."""
        s = 0.0
        # Bug bounty (max 30)
        if bug_bounty > 0 and peak_tvl > 0:
            s += min(30.0, (bug_bounty / peak_tvl) * 10_000.0)
        # Audit count (max 30; 5 per audit)
        s += min(30.0, audits_count * 5.0)
        # Audit freshness (max 20)
        if last_audit_days <= 30:
            s += 20.0
        elif last_audit_days <= 90:
            s += 15.0
        elif last_audit_days <= 180:
            s += 10.0
        elif last_audit_days <= 365:
            s += 5.0
        # Insurance coverage (max 20)
        if insurance > 0 and peak_tvl > 0:
            s += min(20.0, (insurance / peak_tvl) * 100.0)
        return min(100.0, max(0.0, s))

    def _recency_risk(self, incidents: list) -> float:
        """0-100; higher = more recent dangerous incidents."""
        if not incidents:
            return 0.0
        score = 0.0
        for inc in incidents:
            days = inc["date_days_ago"]
            sw = SEVERITY_WEIGHTS.get(inc["severity"], 0.5)
            if days <= 30:
                rw = 1.0
            elif days <= 90:
                rw = 0.8
            elif days <= 180:
                rw = 0.6
            elif days <= 365:
                rw = 0.4
            else:
                rw = 0.2
            score += sw * rw * 20.0
        return min(100.0, score)

    def _composite_safety(self, incident_rate_score: float,
                           security_investment_score: float,
                           recency_risk: float,
                           recovery_rate_pct: float) -> float:
        """0-100; higher = safer."""
        raw = (
            (100.0 - incident_rate_score) * 0.35
            + security_investment_score * 0.30
            + (100.0 - recency_risk) * 0.20
            + recovery_rate_pct * 0.15
        )
        return min(100.0, max(0.0, raw))

    def _safety_label(self, score: float) -> str:
        for threshold, label in SAFETY_THRESHOLDS:
            if score >= threshold:
                return label
        return "AVOID"

    def _flags(self, incidents: list, insurance: float,
                audits_count: int, recovery_rate_pct: float) -> list:
        flags = []

        recent_hacks = [
            i for i in incidents
            if i["date_days_ago"] <= 90 and i["type"] in ("hack", "exploit")
        ]
        if recent_hacks:
            flags.append("RECENT_HACK")

        critical_count = sum(1 for i in incidents if i["severity"] == "CRITICAL")
        if critical_count > 1:
            flags.append("REPEAT_OFFENDER")

        if insurance <= 0:
            flags.append("NO_INSURANCE")

        if audits_count == 0:
            flags.append("UNAUDITED")

        if recovery_rate_pct > 50.0:
            flags.append("RECOVERED_FUNDS")

        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "safest_protocol": None,
                "most_risky": None,
                "total_lost_usd": 0.0,
                "total_recovered_usd": 0.0,
                "avoid_count": 0,
            }

        by_safety = sorted(results, key=lambda r: r["composite_safety_score"], reverse=True)
        total_lost = sum(r["total_lost_usd"] for r in results)
        total_recovered = sum(r["total_recovered_usd"] for r in results)
        avoid_count = sum(1 for r in results if r["safety_label"] == "AVOID")

        return {
            "safest_protocol": by_safety[0]["name"],
            "most_risky": by_safety[-1]["name"],
            "total_lost_usd": round(total_lost, 2),
            "total_recovered_usd": round(total_recovered, 2),
            "avoid_count": avoid_count,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log
    # ------------------------------------------------------------------ #

    def _append_log(self, output: dict) -> None:
        log_path = self.log_path
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

        log = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append({
            "timestamp": output["timestamp"],
            "protocol_count": output["protocol_count"],
            "aggregates": output["aggregates"],
        })

        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        tmp = log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, log_path)
