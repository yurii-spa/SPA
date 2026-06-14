"""
MP-953: ProtocolGovernanceAttackResistanceScorer
Evaluates DeFi protocol governance resistance to 51% voting attacks,
flash loan attacks, and plutocracy.
Pure stdlib, read-only analytics, atomic writes.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import datetime
from typing import Any

__version__ = "1.0.0"
__mp__ = "MP-953"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "data",
    "governance_attack_resistance_log.json",
)
LOG_CAP = 100

RESISTANCE_LABELS = ["FORTRESS", "ROBUST", "ADEQUATE", "VULNERABLE", "CRITICAL"]

# Score thresholds (composite_resistance_score 0-100, high = more resistant)
_LABEL_THRESHOLDS = [
    (80.0, "FORTRESS"),
    (60.0, "ROBUST"),
    (40.0, "ADEQUATE"),
    (20.0, "VULNERABLE"),
    (0.0, "CRITICAL"),
]

# Attack cost threshold for LOW_ATTACK_COST flag ($M)
_LOW_ATTACK_COST_USD = 1_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append_log(path: str, entry: dict, cap: int) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _attack_cost_usd(market_cap: float) -> float:
    """
    Cost to acquire 51% of governance token supply at current market price.
    Simplified: 51% of market cap (ignores slippage / float).
    """
    return market_cap * 0.51


def _plutocracy_score(top_10_pct: float) -> float:
    """
    Plutocracy score 0-100 where high = bad (concentrated).
    Based on top-10 holder percentage of total supply.
    Score = top_10_pct clamped to [0,100].
    """
    return _clamp(float(top_10_pct))


def _flashloan_vulnerability(
    flash_loan_protected: bool,
    snapshot_based: bool,
    voting_period_hours: float,
) -> float:
    """
    Flash loan vulnerability 0-100 (high = vulnerable).
    - If snapshot_based: very low (off-chain snapshot)
    - If flash_loan_protected: low
    - Short voting periods increase vulnerability
    """
    if snapshot_based:
        return 5.0  # Off-chain; essentially immune to flash loans
    if flash_loan_protected:
        base = 10.0
    else:
        base = 70.0
    # Shorter voting periods → harder to defend
    period_penalty = _clamp(48.0 / max(voting_period_hours, 1.0) * 20.0, 0.0, 30.0)
    return _clamp(base + period_penalty)


def _governance_participation_score(
    total_unique_voters_30d: int,
    quorum_pct: float,
    delegation_enabled: bool,
) -> float:
    """
    Participation score 0-100 (high = healthy participation).
    Components:
    - voter count (log-scale, saturates at 10,000 voters)
    - quorum requirement (higher quorum → harder to pass bad proposals)
    - delegation bonus
    """
    voters = max(0, total_unique_voters_30d)
    # log10(1) = 0, log10(10000) = 4 → normalise to 0-50
    voter_score = _clamp(math.log10(voters + 1) / math.log10(10001) * 50.0, 0.0, 50.0)

    # Quorum: higher quorum harder to manipulate → up to 30 pts
    quorum_score = _clamp(float(quorum_pct) / 50.0 * 30.0, 0.0, 30.0)

    # Delegation bonus: 20 pts
    deleg_score = 20.0 if delegation_enabled else 0.0

    return _clamp(voter_score + quorum_score + deleg_score)


def _composite_resistance_score(
    attack_cost: float,
    plutocracy: float,
    flash_vuln: float,
    participation: float,
    timelock_hours: float,
    proposal_threshold_pct: float,
) -> float:
    """
    Composite resistance score 0-100 (high = resistant).

    Weights:
    - Attack cost:       25% (log-scale: $1B = full marks)
    - Plutocracy:        25% (inverted: 0% concentration = max)
    - Flash loan vuln:   20% (inverted)
    - Participation:     20%
    - Timelock:          5%  (48h timelock ≈ full marks)
    - Proposal threshold:5%  (higher threshold → harder to spam)
    """
    # Attack cost score (log10 scale: $0=0, $1B=100)
    cost_score = _clamp(math.log10(max(attack_cost, 1.0)) / 9.0 * 100.0)

    plut_score = _clamp(100.0 - plutocracy)       # inverted
    flash_score = _clamp(100.0 - flash_vuln)       # inverted

    # Timelock score: 0h→0, 48h→100 (saturates)
    timelock_score = _clamp(float(timelock_hours) / 48.0 * 100.0)

    # Proposal threshold score: higher % harder to create spam proposals
    prop_score = _clamp(float(proposal_threshold_pct) / 5.0 * 100.0)

    composite = (
        cost_score * 0.25
        + plut_score * 0.25
        + flash_score * 0.20
        + participation * 0.20
        + timelock_score * 0.05
        + prop_score * 0.05
    )
    return _clamp(composite)


def _resistance_label(score: float) -> str:
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Per-protocol analysis
# ---------------------------------------------------------------------------

def _build_protocol_result(protocol: dict) -> dict:
    name = protocol.get("name", "")
    market_cap = float(protocol.get("governance_token_market_cap_usd", 0.0))
    top_10_pct = float(protocol.get("top_10_holder_pct", 0.0))
    quorum_pct = float(protocol.get("quorum_pct", 0.0))
    timelock_hours = float(protocol.get("timelock_hours", 0.0))
    flash_protected = bool(protocol.get("flash_loan_protected", False))
    delegation = bool(protocol.get("delegation_enabled", False))
    voting_period_hours = float(protocol.get("voting_period_hours", 24.0))
    proposal_threshold_pct = float(protocol.get("proposal_threshold_pct", 0.0))
    unique_voters = int(protocol.get("total_unique_voters_30d", 0))
    snapshot_based = bool(protocol.get("snapshot_based", False))

    attack_cost = _attack_cost_usd(market_cap)
    plutocracy = _plutocracy_score(top_10_pct)
    flash_vuln = _flashloan_vulnerability(flash_protected, snapshot_based, voting_period_hours)
    participation = _governance_participation_score(unique_voters, quorum_pct, delegation)
    composite = _composite_resistance_score(
        attack_cost,
        plutocracy,
        flash_vuln,
        participation,
        timelock_hours,
        proposal_threshold_pct,
    )

    label = _resistance_label(composite)

    # Flags
    flags: list[str] = []
    if not flash_protected and not snapshot_based:
        flags.append("FLASH_LOAN_VULNERABLE")
    if unique_voters < 100:
        flags.append("LOW_PARTICIPATION")
    if top_10_pct > 70.0:
        flags.append("PLUTOCRATIC")
    if timelock_hours < 24.0:
        flags.append("SHORT_TIMELOCK")
    if attack_cost < _LOW_ATTACK_COST_USD:
        flags.append("LOW_ATTACK_COST")

    return {
        "name": name,
        "attack_cost_usd": round(attack_cost, 2),
        "plutocracy_score": round(plutocracy, 4),
        "flashloan_vulnerability": round(flash_vuln, 4),
        "governance_participation_score": round(participation, 4),
        "composite_resistance_score": round(composite, 4),
        "resistance_label": label,
        "flags": flags,
        "score_breakdown": {
            "attack_cost_component": round(
                _clamp(math.log10(max(attack_cost, 1.0)) / 9.0 * 100.0) * 0.25, 4
            ),
            "plutocracy_component": round((100.0 - plutocracy) * 0.25, 4),
            "flash_component": round((100.0 - flash_vuln) * 0.20, 4),
            "participation_component": round(participation * 0.20, 4),
            "timelock_component": round(
                _clamp(timelock_hours / 48.0 * 100.0) * 0.05, 4
            ),
            "proposal_threshold_component": round(
                _clamp(proposal_threshold_pct / 5.0 * 100.0) * 0.05, 4
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolGovernanceAttackResistanceScorer:
    """
    Scores DeFi protocol governance robustness against attack vectors:
    - 51% vote acquisition cost
    - Flash loan attack surface
    - Plutocracy / token concentration
    - Participation health
    """

    def __init__(self, log_path: str | None = None, log_cap: int = LOG_CAP):
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def score(self, protocols: list[dict], config: dict | None = None) -> dict:
        """
        Score governance attack resistance for each protocol.

        Parameters
        ----------
        protocols : list[dict]
            Each dict must include the fields described in the module docstring.
        config : dict, optional
            Reserved for future thresholds/overrides.

        Returns
        -------
        dict
            {
              "protocols": [...],   # per-protocol scored results
              "aggregates": {...},  # cross-protocol stats
              "analysis_timestamp": str,
            }
        """
        if config is None:
            config = {}

        results = []
        for p in protocols:
            results.append(_build_protocol_result(p))

        aggregates = self._compute_aggregates(results)

        output = {
            "protocols": results,
            "aggregates": aggregates,
            "analysis_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "module": __mp__,
            "version": __version__,
        }

        log_entry = {
            "ts": output["analysis_timestamp"],
            "count": len(results),
            "average_resistance": aggregates.get("average_resistance"),
            "fortress_count": aggregates.get("fortress_count"),
            "critical_count": aggregates.get("critical_count"),
        }
        try:
            _append_log(self._log_path, log_entry, self._log_cap)
        except Exception:
            pass

        return output

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_aggregates(results: list[dict]) -> dict:
        if not results:
            return {
                "most_resistant": None,
                "most_vulnerable": None,
                "average_resistance": None,
                "fortress_count": 0,
                "critical_count": 0,
                "total_count": 0,
            }

        sorted_r = sorted(results, key=lambda r: r["composite_resistance_score"], reverse=True)
        most_resistant = sorted_r[0]["name"]
        most_vulnerable = sorted_r[-1]["name"]

        scores = [r["composite_resistance_score"] for r in results]
        avg = sum(scores) / len(scores)

        fortress_count = sum(1 for r in results if r["resistance_label"] == "FORTRESS")
        critical_count = sum(1 for r in results if r["resistance_label"] == "CRITICAL")

        return {
            "most_resistant": most_resistant,
            "most_vulnerable": most_vulnerable,
            "average_resistance": round(avg, 4),
            "fortress_count": fortress_count,
            "critical_count": critical_count,
            "total_count": len(results),
        }
