"""
MP-989: ProtocolCrossChainBridgeRiskMonitor
Monitors risks of cross-chain bridges: TVL concentration, validator sets,
historical incidents.  Pure stdlib — no external dependencies.
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

LOG_CAP = 100
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "bridge_risk_log.json",
)

# Recognised bridge types
BRIDGE_TYPES = frozenset(
    {"lock_mint", "liquidity_network", "optimistic", "zk_proof", "canonical"}
)

# Risk label thresholds (composite score, ascending risk)
_RISK_THRESHOLDS = [
    (20.0, "LOW_RISK"),
    (45.0, "MODERATE_RISK"),
    (70.0, "HIGH_RISK"),
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _compute_centralization_score(
    bridge_type: str,
    validator_count: int,
    validator_threshold_pct: float,
) -> float:
    """0–100; higher = more centralised.

    Base by type (ZK = 5 … lock_mint = 40) plus:
    - validator penalty: scarce validators → +30 (log-scale, capped)
    - threshold penalty: high signing threshold → +30
    """
    _base = {
        "zk_proof": 5.0,
        "canonical": 10.0,
        "optimistic": 20.0,
        "liquidity_network": 30.0,
        "lock_mint": 40.0,
    }
    base = _base.get(bridge_type, 40.0)

    if validator_count > 0:
        # fewer validators → higher penalty (up to 30)
        validator_penalty = max(
            0.0, 30.0 - math.log1p(validator_count) * 8.0
        )
        # higher signing threshold → more centralised (up to 30)
        threshold_penalty = (max(0.0, min(validator_threshold_pct, 100.0)) / 100.0) * 30.0
    else:
        validator_penalty = 0.0
        threshold_penalty = 0.0

    return round(min(base + validator_penalty + threshold_penalty, 100.0), 4)


def _compute_incident_risk_score(
    incidents_count: int,
    days_since_last_incident: int,
    amount_lost_all_time_usd: float,
    total_tvl_usd: float,
) -> float:
    """0–100 incident-risk score.

    Components:
      - frequency (0–40): 10 pts per incident, capped at 40
      - recency  (0–40): monotone linear decay over 720 days (40→0)
      - severity (0–20): amount-lost / TVL ratio
    """
    if incidents_count == 0:
        return 0.0

    frequency = min(incidents_count * 10.0, 40.0)

    d = max(0, days_since_last_incident)
    if d >= 720:
        recency = 0.0
    else:
        recency = max(0.0, 40.0 * (1.0 - d / 720.0))

    if total_tvl_usd > 0 and amount_lost_all_time_usd > 0:
        loss_ratio = amount_lost_all_time_usd / total_tvl_usd
        severity = min(loss_ratio * 20.0, 20.0)
    else:
        severity = 0.0

    return round(min(frequency + recency + severity, 100.0), 4)


def _compute_coverage_ratio(
    insurance_coverage_usd: float,
    total_tvl_usd: float,
) -> float:
    """Insurance coverage as % of TVL (0–∞, though >100 is possible)."""
    if total_tvl_usd <= 0:
        return 0.0
    return round((insurance_coverage_usd / total_tvl_usd) * 100.0, 4)


def _compute_composite_risk_score(
    centralization_score: float,
    incident_risk_score: float,
    coverage_ratio: float,
) -> float:
    """Composite 0–100 (higher = riskier).

    Weights: centralisation 40 %, incident-risk 45 %, coverage bonus −15 %.
    """
    coverage_bonus = min((coverage_ratio / 100.0) * 15.0, 15.0)
    raw = (centralization_score * 0.40) + (incident_risk_score * 0.45) - coverage_bonus
    return round(max(0.0, min(raw, 100.0)), 4)


def _compute_risk_label(
    bridge_type: str,
    incidents_count: int,
    days_since_last_incident: int,
    audit_count: int,
    composite_risk_score: float,
    validator_count: int,
) -> str:
    """Classify bridge by risk tier.

    CRITICAL overrides:
      - multisig (lock_mint) AND validators < 5
      - any incident within the last 90 days

    FORTRESS: ZK + no incidents + ≥ 2 audits.
    Otherwise: composite-score thresholds.
    """
    is_lock_mint = bridge_type == "lock_mint"
    recent_hack = incidents_count > 0 and days_since_last_incident < 90

    if (is_lock_mint and validator_count < 5) or recent_hack:
        return "CRITICAL"

    if bridge_type == "zk_proof" and incidents_count == 0 and audit_count >= 2:
        return "FORTRESS"

    for threshold, label in _RISK_THRESHOLDS:
        if composite_risk_score < threshold:
            return label
    return "CRITICAL"


def _compute_flags(
    bridge_type: str,
    validator_count: int,
    incidents_count: int,
    days_since_last_incident: int,
    coverage_ratio: float,
    top_asset_concentration_pct: float,
    canonical_bridge: bool,
) -> list:
    """Return advisory flags for a bridge."""
    flags = []
    # MULTISIG_RISK: lock-and-mint with fewer than 7 validators
    if bridge_type == "lock_mint" and validator_count < 7:
        flags.append("MULTISIG_RISK")
    # RECENT_INCIDENT: any exploit within 180 days
    if incidents_count > 0 and days_since_last_incident < 180:
        flags.append("RECENT_INCIDENT")
    # UNINSURED: coverage below 5 % of TVL
    if coverage_ratio < 5.0:
        flags.append("UNINSURED")
    # ASSET_CONCENTRATED: single token > 60 % of bridged TVL
    if top_asset_concentration_pct > 60.0:
        flags.append("ASSET_CONCENTRATED")
    # CANONICAL_SAFE: official L2 bridge using ZK proofs
    if canonical_bridge and bridge_type == "zk_proof":
        flags.append("CANONICAL_SAFE")
    return flags


# ── main class ─────────────────────────────────────────────────────────────────

class ProtocolCrossChainBridgeRiskMonitor:
    """MP-989 — monitors cross-chain bridge risks.

    Usage::

        monitor = ProtocolCrossChainBridgeRiskMonitor()
        result = monitor.monitor(bridges, config)

    ``config`` keys:
      - ``persist`` (bool, default False): append result to ring-buffer log.
    """

    def __init__(self, log_path: str = DEFAULT_LOG_PATH) -> None:
        self.log_path = log_path

    # ── public ─────────────────────────────────────────────────────────────

    def monitor(self, bridges: list, config: dict) -> dict:
        """Monitor each bridge and return aggregated risk report.

        Required bridge keys:
          name, bridge_type, total_tvl_bridged_usd,
          top_asset_concentration_pct, validator_count,
          validator_threshold_pct, audit_count,
          incidents_count_all_time, amount_lost_all_time_usd,
          days_since_last_incident, canonical_bridge,
          insurance_coverage_usd
        """
        persist = bool(config.get("persist", False))
        results = []

        for bridge in bridges:
            name = bridge.get("name", "unknown")
            bridge_type = bridge.get("bridge_type", "lock_mint")
            tvl = float(bridge.get("total_tvl_bridged_usd", 0.0))
            top_asset_conc = float(bridge.get("top_asset_concentration_pct", 0.0))
            validator_count = int(bridge.get("validator_count", 0))
            validator_threshold_pct = float(bridge.get("validator_threshold_pct", 66.0))
            audit_count = int(bridge.get("audit_count", 0))
            incidents_count = int(bridge.get("incidents_count_all_time", 0))
            amount_lost = float(bridge.get("amount_lost_all_time_usd", 0.0))
            days_since_last = int(bridge.get("days_since_last_incident", 9999))
            canonical_bridge = bool(bridge.get("canonical_bridge", False))
            insurance_coverage = float(bridge.get("insurance_coverage_usd", 0.0))

            centralization_score = _compute_centralization_score(
                bridge_type, validator_count, validator_threshold_pct
            )
            incident_risk_score = _compute_incident_risk_score(
                incidents_count, days_since_last, amount_lost, tvl
            )
            coverage_ratio = _compute_coverage_ratio(insurance_coverage, tvl)
            composite_risk_score = _compute_composite_risk_score(
                centralization_score, incident_risk_score, coverage_ratio
            )
            risk_label = _compute_risk_label(
                bridge_type, incidents_count, days_since_last,
                audit_count, composite_risk_score, validator_count,
            )
            flags = _compute_flags(
                bridge_type, validator_count, incidents_count, days_since_last,
                coverage_ratio, top_asset_conc, canonical_bridge,
            )

            results.append({
                "name": name,
                "bridge_type": bridge_type,
                "total_tvl_bridged_usd": tvl,
                "top_asset_concentration_pct": top_asset_conc,
                "validator_count": validator_count,
                "validator_threshold_pct": validator_threshold_pct,
                "audit_count": audit_count,
                "incidents_count_all_time": incidents_count,
                "amount_lost_all_time_usd": amount_lost,
                "days_since_last_incident": days_since_last,
                "canonical_bridge": canonical_bridge,
                "insurance_coverage_usd": insurance_coverage,
                "centralization_score": centralization_score,
                "incident_risk_score": incident_risk_score,
                "coverage_ratio": coverage_ratio,
                "composite_risk_score": composite_risk_score,
                "risk_label": risk_label,
                "flags": flags,
            })

        # ── aggregates ─────────────────────────────────────────────────────
        if results:
            sorted_by_risk = sorted(
                results, key=lambda r: r["composite_risk_score"]
            )
            safest_bridge = sorted_by_risk[0]["name"]
            riskiest_bridge = sorted_by_risk[-1]["name"]
            total_tvl_at_risk = sum(
                r["total_tvl_bridged_usd"]
                for r in results
                if r["risk_label"] in ("HIGH_RISK", "CRITICAL")
            )
            critical_count = sum(1 for r in results if r["risk_label"] == "CRITICAL")
            fortress_count = sum(1 for r in results if r["risk_label"] == "FORTRESS")
        else:
            safest_bridge = None
            riskiest_bridge = None
            total_tvl_at_risk = 0.0
            critical_count = 0
            fortress_count = 0

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bridge_count": len(bridges),
            "bridges": results,
            "aggregates": {
                "safest_bridge": safest_bridge,
                "riskiest_bridge": riskiest_bridge,
                "total_tvl_at_risk_usd": total_tvl_at_risk,
                "critical_count": critical_count,
                "fortress_count": fortress_count,
            },
        }

        if persist:
            self._append_log(output)

        return output

    # ── private ────────────────────────────────────────────────────────────

    def _append_log(self, entry: dict) -> None:
        """Append entry to ring-buffer log (cap = LOG_CAP), atomic write."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []
        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]
        _atomic_write(self.log_path, log)
