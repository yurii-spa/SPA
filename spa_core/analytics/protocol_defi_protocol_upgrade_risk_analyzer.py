"""
MP-1039 ProtocolDeFiProtocolUpgradeRiskAnalyzer
Advisory-only analytics module.

Analyzes risk associated with DeFi protocol upgrades, considering proxy patterns,
timelock enforcement, governance decentralisation, audit coverage, and upgrade cadence.

Inputs:
  upgrade_mechanism          — one of: proxy / immutable / timelock / multisig / dao
  timelock_hours             — enforced delay before an upgrade executes (hours, ≥0)
  governance_participation_pct — active voter share (0-100)
  last_upgrade_days_ago      — days since the last upgrade (0 = just upgraded; -1 = never)
  audit_coverage_pct         — percentage of code covered by independent security audits (0-100)
  upgrade_frequency_per_year — expected upgrades per calendar year

Outputs:
  upgrade_risk_score    (0-100, higher = more risky),
  governance_quality_score (0-100, higher = better),
  surprise_upgrade_risk (0-100, higher = more surprise-prone),
  label: BATTLE_TESTED / WELL_GOVERNED / MODERATE_RISK / HIGH_UPGRADE_RISK / UNILATERAL_CONTROL

Data log: data/protocol_upgrade_risk_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_RING_SIZE = 100

# Recognised upgrade mechanism values (case-insensitive)
_VALID_MECHANISMS = {"proxy", "immutable", "timelock", "multisig", "dao"}

# Risk-score label thresholds (inclusive upper bound of each band except last)
_THRESHOLD_BATTLE_TESTED  = 20.0
_THRESHOLD_WELL_GOVERNED  = 40.0
_THRESHOLD_MODERATE_RISK  = 60.0
_THRESHOLD_HIGH_RISK      = 80.0

# Component weights for upgrade_risk_score
_W_MECHANISM  = 0.35
_W_TIMELOCK   = 0.20
_W_GOVERNANCE = 0.15
_W_AUDIT      = 0.15
_W_FREQUENCY  = 0.10
_W_RECENCY    = 0.05

# ---------------------------------------------------------------------------
# Component risk helpers (each returns 0-100; higher = more risk)
# ---------------------------------------------------------------------------


def _mechanism_risk(mechanism: str) -> float:
    """
    Base upgrade risk from the mechanism type.
    immutable → 0 (cannot be changed), proxy → 75 (unilateral upgrade possible).
    """
    table = {
        "immutable": 0.0,
        "timelock":  15.0,
        "dao":       25.0,
        "multisig":  60.0,
        "proxy":     75.0,
    }
    return table.get(mechanism.lower(), 65.0)


def _timelock_risk(mechanism: str, timelock_hours: float) -> float:
    """
    Risk from insufficient timelock delay.
    immutable → 0.  Otherwise short (or absent) timelock raises risk.
    """
    if mechanism.lower() == "immutable":
        return 0.0
    if timelock_hours >= 168.0:   # 1 week
        return 5.0
    if timelock_hours >= 72.0:    # 3 days
        return 15.0
    if timelock_hours >= 48.0:    # 2 days
        return 25.0
    if timelock_hours >= 24.0:    # 1 day
        return 45.0
    if timelock_hours > 0.0:
        return 70.0
    return 100.0                   # no timelock at all


def _governance_risk(mechanism: str, participation_pct: float) -> float:
    """
    Governance risk from low voter participation.
    immutable → 0.  proxy without meaningful governance → high risk.
    """
    if mechanism.lower() == "immutable":
        return 0.0
    if participation_pct >= 40.0:
        base = 10.0
    elif participation_pct >= 20.0:
        base = 30.0
    elif participation_pct >= 10.0:
        base = 50.0
    elif participation_pct >= 5.0:
        base = 70.0
    else:
        base = 90.0

    # Mechanisms that are inherently less governance-driven push risk up/down
    mech_adj = {
        "dao":      -10.0,
        "timelock": -5.0,
        "multisig": +10.0,
        "proxy":    +15.0,
    }.get(mechanism.lower(), 0.0)
    return max(0.0, min(100.0, base + mech_adj))


def _audit_risk(audit_coverage_pct: float) -> float:
    """Risk from insufficient audit coverage of the codebase."""
    if audit_coverage_pct >= 90.0:
        return 5.0
    if audit_coverage_pct >= 75.0:
        return 20.0
    if audit_coverage_pct >= 50.0:
        return 40.0
    if audit_coverage_pct >= 25.0:
        return 65.0
    return 90.0


def _frequency_risk(mechanism: str, upgrade_frequency_per_year: float) -> float:
    """Risk from frequent protocol upgrades."""
    if mechanism.lower() == "immutable":
        return 0.0
    freq = upgrade_frequency_per_year
    if freq == 0.0:
        return 20.0    # Never upgraded yet — unknown behaviour
    if freq < 1.0:
        return 30.0
    if freq < 2.0:
        return 50.0
    if freq < 4.0:
        return 70.0
    if freq < 8.0:
        return 85.0
    return 95.0


def _recency_risk(mechanism: str, last_upgrade_days_ago: float) -> float:
    """
    Risk from how recently the protocol was upgraded.
    Very recent upgrades carry higher unknown risk.
    last_upgrade_days_ago = -1  means  never upgraded.
    """
    if mechanism.lower() == "immutable":
        return 0.0
    if last_upgrade_days_ago < 0:       # never upgraded
        return 20.0
    if last_upgrade_days_ago < 7.0:
        return 90.0
    if last_upgrade_days_ago < 30.0:
        return 60.0
    if last_upgrade_days_ago < 90.0:
        return 35.0
    if last_upgrade_days_ago < 365.0:
        return 15.0
    return 5.0


# ---------------------------------------------------------------------------
# Composite scores
# ---------------------------------------------------------------------------


def _upgrade_risk_score(
    mechanism: str,
    timelock_hours: float,
    governance_participation_pct: float,
    last_upgrade_days_ago: float,
    audit_coverage_pct: float,
    upgrade_frequency_per_year: float,
) -> float:
    """
    Weighted composite upgrade risk score (0-100).
    Higher score → greater upgrade risk to capital.
    """
    r_mech  = _mechanism_risk(mechanism)
    r_tl    = _timelock_risk(mechanism, timelock_hours)
    r_gov   = _governance_risk(mechanism, governance_participation_pct)
    r_audit = _audit_risk(audit_coverage_pct)
    r_freq  = _frequency_risk(mechanism, upgrade_frequency_per_year)
    r_rec   = _recency_risk(mechanism, last_upgrade_days_ago)

    score = (
        _W_MECHANISM  * r_mech
        + _W_TIMELOCK   * r_tl
        + _W_GOVERNANCE * r_gov
        + _W_AUDIT      * r_audit
        + _W_FREQUENCY  * r_freq
        + _W_RECENCY    * r_rec
    )
    return round(max(0.0, min(100.0, score)), 4)


def _governance_quality_score(
    mechanism: str,
    governance_participation_pct: float,
) -> float:
    """
    Governance quality score (0-100; higher = better governed).
    Combines mechanism quality and voter participation.
    """
    # Mechanism intrinsic quality
    mech_score = {
        "immutable": 95.0,
        "dao":        80.0,
        "timelock":   65.0,
        "multisig":   40.0,
        "proxy":      20.0,
    }.get(mechanism.lower(), 35.0)

    # Participation quality
    if governance_participation_pct >= 40.0:
        part_score = 100.0
    elif governance_participation_pct >= 20.0:
        part_score = 75.0
    elif governance_participation_pct >= 10.0:
        part_score = 50.0
    elif governance_participation_pct >= 5.0:
        part_score = 25.0
    else:
        part_score = 10.0

    # Immutable needs no governance participation
    if mechanism.lower() == "immutable":
        return round(mech_score, 4)

    combined = 0.5 * mech_score + 0.5 * part_score
    return round(max(0.0, min(100.0, combined)), 4)


def _surprise_upgrade_risk(
    mechanism: str,
    timelock_hours: float,
    upgrade_frequency_per_year: float,
) -> float:
    """
    Surprise upgrade risk (0-100): how likely is a sudden, unexpected upgrade.
    immutable → 0.  Proxy with no timelock and high frequency → very high.
    """
    if mechanism.lower() == "immutable":
        return 0.0

    base = {
        "proxy":     70.0,
        "multisig":  60.0,
        "timelock":  20.0,
        "dao":       15.0,
    }.get(mechanism.lower(), 50.0)

    # Timelock length dampens surprise risk
    if timelock_hours >= 168.0:
        tl_factor = 0.25
    elif timelock_hours >= 72.0:
        tl_factor = 0.40
    elif timelock_hours >= 48.0:
        tl_factor = 0.55
    elif timelock_hours >= 24.0:
        tl_factor = 0.70
    elif timelock_hours > 0.0:
        tl_factor = 0.90
    else:
        tl_factor = 1.00

    # High upgrade frequency amplifies surprise exposure
    if upgrade_frequency_per_year >= 8.0:
        freq_factor = 1.30
    elif upgrade_frequency_per_year >= 4.0:
        freq_factor = 1.15
    elif upgrade_frequency_per_year >= 2.0:
        freq_factor = 1.05
    else:
        freq_factor = 1.00

    return round(max(0.0, min(100.0, base * tl_factor * freq_factor)), 4)


def _label(risk_score: float) -> str:
    """Map upgrade risk score to qualitative label."""
    if risk_score <= _THRESHOLD_BATTLE_TESTED:
        return "BATTLE_TESTED"
    if risk_score <= _THRESHOLD_WELL_GOVERNED:
        return "WELL_GOVERNED"
    if risk_score <= _THRESHOLD_MODERATE_RISK:
        return "MODERATE_RISK"
    if risk_score <= _THRESHOLD_HIGH_RISK:
        return "HIGH_UPGRADE_RISK"
    return "UNILATERAL_CONTROL"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    upgrade_mechanism: str,
    timelock_hours: float = 0.0,
    governance_participation_pct: float = 0.0,
    last_upgrade_days_ago: float = -1.0,
    audit_coverage_pct: float = 0.0,
    upgrade_frequency_per_year: float = 0.0,
) -> dict:
    """
    Analyze upgrade risk for a DeFi protocol.

    Parameters
    ----------
    upgrade_mechanism : str
        One of: proxy, immutable, timelock, multisig, dao.
    timelock_hours : float
        Enforced delay before upgrade executes (0 = no timelock).
    governance_participation_pct : float
        Active voter share in governance (0-100).
    last_upgrade_days_ago : float
        Days since the last upgrade.  Use -1 for "never upgraded".
    audit_coverage_pct : float
        Percentage of codebase independently audited (0-100).
    upgrade_frequency_per_year : float
        Expected or historic upgrade count per year.

    Returns
    -------
    dict with all inputs, component scores, composite scores, label, and timestamp.
    """
    mech = upgrade_mechanism.lower().strip()

    r_mech  = _mechanism_risk(mech)
    r_tl    = _timelock_risk(mech, timelock_hours)
    r_gov   = _governance_risk(mech, governance_participation_pct)
    r_audit = _audit_risk(audit_coverage_pct)
    r_freq  = _frequency_risk(mech, upgrade_frequency_per_year)
    r_rec   = _recency_risk(mech, last_upgrade_days_ago)

    urs = _upgrade_risk_score(
        mech, timelock_hours, governance_participation_pct,
        last_upgrade_days_ago, audit_coverage_pct, upgrade_frequency_per_year,
    )
    gqs = _governance_quality_score(mech, governance_participation_pct)
    sur = _surprise_upgrade_risk(mech, timelock_hours, upgrade_frequency_per_year)
    lbl = _label(urs)

    return {
        # Inputs (normalised)
        "upgrade_mechanism": mech,
        "timelock_hours": timelock_hours,
        "governance_participation_pct": governance_participation_pct,
        "last_upgrade_days_ago": last_upgrade_days_ago,
        "audit_coverage_pct": audit_coverage_pct,
        "upgrade_frequency_per_year": upgrade_frequency_per_year,
        # Component risk scores (each 0-100)
        "mechanism_risk": round(r_mech, 4),
        "timelock_risk": round(r_tl, 4),
        "governance_risk": round(r_gov, 4),
        "audit_risk": round(r_audit, 4),
        "frequency_risk": round(r_freq, 4),
        "recency_risk": round(r_rec, 4),
        # Composite scores
        "upgrade_risk_score": urs,
        "governance_quality_score": gqs,
        "surprise_upgrade_risk": sur,
        # Label
        "label": lbl,
        "timestamp": time.time(),
    }


class ProtocolDeFiProtocolUpgradeRiskAnalyzer:
    """
    Class wrapper for MP-1039 DeFi protocol upgrade risk analysis.

    Stateless — each call to analyze() is independent.
    """

    def analyze(
        self,
        upgrade_mechanism: str,
        timelock_hours: float = 0.0,
        governance_participation_pct: float = 0.0,
        last_upgrade_days_ago: float = -1.0,
        audit_coverage_pct: float = 0.0,
        upgrade_frequency_per_year: float = 0.0,
    ) -> dict:
        """Analyze upgrade risk for a DeFi protocol.  See module-level analyze()."""
        return analyze(
            upgrade_mechanism=upgrade_mechanism,
            timelock_hours=timelock_hours,
            governance_participation_pct=governance_participation_pct,
            last_upgrade_days_ago=last_upgrade_days_ago,
            audit_coverage_pct=audit_coverage_pct,
            upgrade_frequency_per_year=upgrade_frequency_per_year,
        )


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append a compact snapshot to the ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "protocol_upgrade_risk_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "upgrade_mechanism": result["upgrade_mechanism"],
        "timelock_hours": result["timelock_hours"],
        "upgrade_risk_score": result["upgrade_risk_score"],
        "governance_quality_score": result["governance_quality_score"],
        "surprise_upgrade_risk": result["surprise_upgrade_risk"],
        "label": result["label"],
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-1039 ProtocolDeFiProtocolUpgradeRiskAnalyzer")
    parser.add_argument("--mechanism", default="timelock", help="Upgrade mechanism")
    parser.add_argument("--timelock-hours", type=float, default=48.0)
    parser.add_argument("--participation", type=float, default=15.0)
    parser.add_argument("--last-upgrade-days", type=float, default=90.0)
    parser.add_argument("--audit-coverage", type=float, default=80.0)
    parser.add_argument("--frequency", type=float, default=1.0)
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run",   action="store_true", help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(
        upgrade_mechanism=args.mechanism,
        timelock_hours=args.timelock_hours,
        governance_participation_pct=args.participation,
        last_upgrade_days_ago=args.last_upgrade_days,
        audit_coverage_pct=args.audit_coverage,
        upgrade_frequency_per_year=args.frequency,
    )

    print(f"Mechanism           : {result['upgrade_mechanism']}")
    print(f"Timelock (hours)    : {result['timelock_hours']}")
    print(f"Gov. participation  : {result['governance_participation_pct']}%")
    print(f"Last upgrade        : {result['last_upgrade_days_ago']} days ago")
    print(f"Audit coverage      : {result['audit_coverage_pct']}%")
    print(f"Upgrade frequency   : {result['upgrade_frequency_per_year']}/year")
    print()
    print(f"Mechanism risk      : {result['mechanism_risk']:.2f}")
    print(f"Timelock risk       : {result['timelock_risk']:.2f}")
    print(f"Governance risk     : {result['governance_risk']:.2f}")
    print(f"Audit risk          : {result['audit_risk']:.2f}")
    print(f"Frequency risk      : {result['frequency_risk']:.2f}")
    print(f"Recency risk        : {result['recency_risk']:.2f}")
    print()
    print(f"Upgrade risk score  : {result['upgrade_risk_score']:.2f}")
    print(f"Gov. quality score  : {result['governance_quality_score']:.2f}")
    print(f"Surprise upg. risk  : {result['surprise_upgrade_risk']:.2f}")
    print(f"Label               : {result['label']}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to      : {args.data_dir}/protocol_upgrade_risk_log.json")
