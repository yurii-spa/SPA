"""
MP-1014: DeFiProtocolAdminKeyControlRiskAnalyzer
=================================================
Advisory-only analytics module.

Assesses *administrative / key-control centralization risk* of a DeFi protocol —
i.e. how much power a privileged operator (admin key, multisig, guardian) holds
over user funds and how quickly they can act. This is the "can they rug / freeze /
upgrade, and how fast?" angle, distinct from on-chain governance-vote modules
(protocol_governance_attack_resistance_scorer, protocol_upgrade_risk_assessor) which
score token-vote dynamics and upgrade *impact*, not admin-key concentration + timelock.

Per protocol it computes:
  multisig_strength_score   0-100  (m-of-n quality, adjusted for signer independence)
  timelock_score            0-100  (longer admin delay → safer for users)
  control_surface_score     0-100  (how much of TVL the admin can touch + powers held)
  admin_control_risk_score  0-100  (HIGHER = more centralized / riskier)
  decentralization_grade    A-F
  classification            FULLY_DECENTRALIZED / MOSTLY_DECENTRALIZED /
                            SEMI_CENTRALIZED / HIGHLY_CENTRALIZED / CRITICAL_CENTRALIZATION

Flags: INSTANT_ADMIN_ACTIONS, SINGLE_KEY_CONTROL, UPGRADEABLE_NO_TIMELOCK,
PAUSABLE_FUNDS, SINGLE_GUARDIAN, LOW_SIGNER_INDEPENDENCE, ADMIN_CONTROLS_MAJORITY_TVL,
STRONG_TIMELOCK, WELL_DISTRIBUTED_MULTISIG, UNAUDITED, INSUFFICIENT_DATA

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/admin_key_control_risk_log.json
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "admin_key_control_risk_log.json",
)
LOG_MAX_ENTRIES = 100

# Timelock scoring (hours → safety). 0h = instant = worst.
TIMELOCK_STRONG_HOURS = 48.0      # >= 48h considered strong
TIMELOCK_MODERATE_HOURS = 24.0    # >= 24h considered moderate

# Classification thresholds on admin_control_risk_score (higher = more centralized)
CRITICAL_CENTRALIZATION = 80.0
HIGHLY_CENTRALIZED = 60.0
SEMI_CENTRALIZED = 40.0
MOSTLY_DECENTRALIZED = 20.0

# Flag thresholds
MAJORITY_TVL_THRESHOLD = 50.0
LOW_INDEPENDENCE_THRESHOLD = 40.0
WELL_DISTRIBUTED_MIN_SIGNERS = 5
WELL_DISTRIBUTED_MIN_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_protocol(p: dict, idx: int) -> None:
    """Validate required fields in a protocol dict."""
    required = {
        "name",
        "multisig_threshold",
        "multisig_signers",
        "timelock_hours",
        "upgradeable",
        "pausable",
        "has_guardian",
        "admin_controlled_tvl_pct",
        "signer_independence_pct",
    }
    missing = required - set(p.keys())
    if missing:
        raise ValueError(
            f"Protocol {idx} ('{p.get('name', '?')}') missing fields: {missing}"
        )
    m = p["multisig_threshold"]
    n = p["multisig_signers"]
    if not isinstance(m, int) or not isinstance(n, int):
        raise ValueError(f"Protocol {idx}: multisig_threshold/signers must be ints")
    if n < 1 or m < 1 or m > n:
        raise ValueError(
            f"Protocol {idx}: require 1 <= multisig_threshold <= multisig_signers"
        )
    if p["timelock_hours"] < 0:
        raise ValueError(f"Protocol {idx}: timelock_hours must be >= 0")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _multisig_strength_score(m: int, n: int, independence_pct: float) -> float:
    """
    Score 0-100 for multisig quality.

    A 1-of-1 (single key) is the worst. Strength grows with the number of
    required signers (m) and the total set (n), and is scaled by how independent
    the signers are (an N-of-N controlled by one entity is no better than 1-of-1).
    """
    if n <= 1:
        base = 0.0
    else:
        # Threshold contribution: more required signers is safer (cap influence at 5).
        thresh_component = min(m, 5) / 5.0 * 60.0
        # Set-size contribution: a larger signer pool dilutes single-actor capture.
        size_component = min(n, 9) / 9.0 * 40.0
        base = thresh_component + size_component
    # Independence scaling: collapses score toward 0 when signers are not independent.
    indep = max(0.0, min(independence_pct, 100.0)) / 100.0
    return round(base * (0.4 + 0.6 * indep), 2)


def _timelock_score(timelock_hours: float) -> float:
    """
    Score 0-100 for the admin-action timelock. Longer delay → users have time to
    exit before a malicious or mistaken admin action lands → safer.
    """
    h = max(0.0, float(timelock_hours))
    if h >= TIMELOCK_STRONG_HOURS:
        # 48h → 90, scaling up to 100 around 168h (1 week).
        extra = min((h - TIMELOCK_STRONG_HOURS) / (168.0 - TIMELOCK_STRONG_HOURS), 1.0)
        return round(90.0 + 10.0 * extra, 2)
    if h >= TIMELOCK_MODERATE_HOURS:
        # 24h → 60, 48h → 90 (linear).
        return round(60.0 + (h - TIMELOCK_MODERATE_HOURS) /
                     (TIMELOCK_STRONG_HOURS - TIMELOCK_MODERATE_HOURS) * 30.0, 2)
    # 0h → 0, 24h → 60 (linear).
    return round(h / TIMELOCK_MODERATE_HOURS * 60.0, 2)


def _control_surface_score(upgradeable: bool, pausable: bool,
                           has_guardian: bool,
                           admin_controlled_tvl_pct: float) -> float:
    """
    Score 0-100 for how large the admin's *control surface* is (HIGHER = more
    powers / more reachable TVL = more centralized).
    """
    tvl = max(0.0, min(float(admin_controlled_tvl_pct), 100.0))
    # TVL reach is the dominant term (0-55).
    score = tvl / 100.0 * 55.0
    if upgradeable:
        score += 20.0   # arbitrary code upgrade is the most dangerous power
    if pausable:
        score += 15.0   # freezing user funds
    if has_guardian:
        score += 10.0   # single emergency actor
    return round(min(score, 100.0), 2)


def _admin_control_risk_score(multisig_strength: float, timelock: float,
                              control_surface: float) -> float:
    """
    Composite admin-control risk 0-100 (HIGHER = more centralized / riskier).

    Weak multisig and weak timelock *raise* risk; both are protective so they
    enter as (100 - score). Control surface enters directly.
    """
    weak_multisig = 100.0 - multisig_strength
    weak_timelock = 100.0 - timelock
    risk = (
        0.35 * weak_multisig +
        0.30 * weak_timelock +
        0.35 * control_surface
    )
    return round(max(0.0, min(risk, 100.0)), 2)


def _classify(risk: float) -> str:
    if risk >= CRITICAL_CENTRALIZATION:
        return "CRITICAL_CENTRALIZATION"
    if risk >= HIGHLY_CENTRALIZED:
        return "HIGHLY_CENTRALIZED"
    if risk >= SEMI_CENTRALIZED:
        return "SEMI_CENTRALIZED"
    if risk >= MOSTLY_DECENTRALIZED:
        return "MOSTLY_DECENTRALIZED"
    return "FULLY_DECENTRALIZED"


def _grade(risk: float) -> str:
    """A (safe/decentralized) → F (critically centralized)."""
    if risk < 20.0:
        return "A"
    if risk < 40.0:
        return "B"
    if risk < 60.0:
        return "C"
    if risk < 80.0:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def _compute_flags(p: dict, multisig_strength: float, timelock: float) -> list:
    flags = []
    m = p["multisig_threshold"]
    n = p["multisig_signers"]
    timelock_hours = float(p["timelock_hours"])
    independence = float(p["signer_independence_pct"])
    tvl = float(p["admin_controlled_tvl_pct"])

    if timelock_hours <= 0.0:
        flags.append("INSTANT_ADMIN_ACTIONS")
    if n <= 1 or m <= 1:
        flags.append("SINGLE_KEY_CONTROL")
    if p["upgradeable"] and timelock_hours < TIMELOCK_MODERATE_HOURS:
        flags.append("UPGRADEABLE_NO_TIMELOCK")
    if p["pausable"]:
        flags.append("PAUSABLE_FUNDS")
    if p["has_guardian"]:
        flags.append("SINGLE_GUARDIAN")
    if independence < LOW_INDEPENDENCE_THRESHOLD:
        flags.append("LOW_SIGNER_INDEPENDENCE")
    if tvl > MAJORITY_TVL_THRESHOLD:
        flags.append("ADMIN_CONTROLS_MAJORITY_TVL")
    if timelock_hours >= TIMELOCK_STRONG_HOURS:
        flags.append("STRONG_TIMELOCK")
    if n >= WELL_DISTRIBUTED_MIN_SIGNERS and m >= WELL_DISTRIBUTED_MIN_THRESHOLD \
            and independence >= LOW_INDEPENDENCE_THRESHOLD:
        flags.append("WELL_DISTRIBUTED_MULTISIG")
    if not p.get("audited", True):
        flags.append("UNAUDITED")
    return flags


# ---------------------------------------------------------------------------
# Per-protocol analysis
# ---------------------------------------------------------------------------

def _analyze_one(p: dict) -> dict:
    m = p["multisig_threshold"]
    n = p["multisig_signers"]
    independence = float(p["signer_independence_pct"])
    timelock_hours = float(p["timelock_hours"])
    tvl = float(p["admin_controlled_tvl_pct"])

    multisig_strength = _multisig_strength_score(m, n, independence)
    timelock = _timelock_score(timelock_hours)
    control_surface = _control_surface_score(
        bool(p["upgradeable"]), bool(p["pausable"]),
        bool(p["has_guardian"]), tvl
    )
    risk = _admin_control_risk_score(multisig_strength, timelock, control_surface)
    classification = _classify(risk)
    grade = _grade(risk)
    flags = _compute_flags(p, multisig_strength, timelock)

    return {
        "name": p["name"],
        "multisig": f"{m}-of-{n}",
        "multisig_strength_score": multisig_strength,
        "timelock_hours": round(timelock_hours, 2),
        "timelock_score": timelock,
        "control_surface_score": control_surface,
        "admin_controlled_tvl_pct": round(tvl, 2),
        "admin_control_risk_score": risk,
        "decentralization_grade": grade,
        "classification": classification,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolAdminKeyControlRiskAnalyzer:
    """
    Analyzes administrative / key-control centralization risk across DeFi protocols.
    Advisory / read-only. No execution side-effects.
    """

    def analyze(self, protocols: list, config: Optional[dict] = None) -> dict:
        """
        Parameters
        ----------
        protocols : list[dict]
            Each dict must contain:
                name                     str
                multisig_threshold       int   (m in m-of-n)
                multisig_signers         int   (n in m-of-n)
                timelock_hours           float (admin-action delay; 0 = instant)
                upgradeable              bool
                pausable                 bool
                has_guardian             bool
                admin_controlled_tvl_pct float (0-100)
                signer_independence_pct  float (0-100)
                audited                  bool  (optional, default True)
        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys:
            protocols                list[dict]
            safest_protocol          str | None
            riskiest_protocol        str | None
            avg_admin_control_risk   float
            critical_count           int
            decentralized_count      int
            analyzed_at              str  ISO timestamp
        """
        if config is None:
            config = {}
        if not isinstance(protocols, list) or len(protocols) == 0:
            raise ValueError("protocols must be a non-empty list")

        for idx, p in enumerate(protocols):
            _validate_protocol(p, idx)

        results = [_analyze_one(p) for p in protocols]

        avg_risk = round(
            sum(r["admin_control_risk_score"] for r in results) / len(results), 2
        )
        critical_count = sum(
            1 for r in results if r["classification"] == "CRITICAL_CENTRALIZATION"
        )
        decentralized_count = sum(
            1 for r in results
            if r["classification"] in ("FULLY_DECENTRALIZED", "MOSTLY_DECENTRALIZED")
        )

        sorted_safe = sorted(results, key=lambda r: r["admin_control_risk_score"])
        safest = sorted_safe[0]["name"] if sorted_safe else None
        riskiest = sorted_safe[-1]["name"] if sorted_safe else None

        output = {
            "protocols": results,
            "safest_protocol": safest,
            "riskiest_protocol": riskiest,
            "avg_admin_control_risk": avg_risk,
            "critical_count": critical_count,
            "decentralized_count": decentralized_count,
            "analyzed_at": _iso_now(),
        }

        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _init_log(path: str) -> list:
    """Load existing log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result snapshot to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "protocol_count": len(result.get("protocols", [])),
        "avg_admin_control_risk": result.get("avg_admin_control_risk"),
        "critical_count": result.get("critical_count"),
        "decentralized_count": result.get("decentralized_count"),
        "safest_protocol": result.get("safest_protocol"),
        "riskiest_protocol": result.get("riskiest_protocol"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to DeFiProtocolAdminKeyControlRiskAnalyzer."""
    return DeFiProtocolAdminKeyControlRiskAnalyzer().analyze(protocols, config)
