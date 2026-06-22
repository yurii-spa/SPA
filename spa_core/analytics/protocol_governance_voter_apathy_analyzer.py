#!/usr/bin/env python3
"""Protocol Governance Voter Apathy Analyzer (MP-967) — read-only / advisory.

Analyzes voter apathy patterns in DeFi governance, computing participation
rates, quorum gaps, whale dominance, consensus scores, and aggregate
apathy severity. Flags structurally broken governance (zombie protocols,
whale capture, quorum failures).

Strictly read-only and advisory. Pure stdlib only. Atomic writes via
tmp + os.replace.

CLI::

    python3 -m spa_core.analytics.protocol_governance_voter_apathy_analyzer --check
    python3 -m spa_core.analytics.protocol_governance_voter_apathy_analyzer --run
    python3 -m spa_core.analytics.protocol_governance_voter_apathy_analyzer --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
VERSION = "1.0.0"
MODULE_ID = "MP-967"
LOG_FILE = "governance_apathy_log.json"
LOG_CAP = 100

# Apathy labels
LABEL_ENGAGED = "ENGAGED"
LABEL_MODERATE = "MODERATE"
LABEL_APATHETIC = "APATHETIC"
LABEL_CRITICALLY_APATHETIC = "CRITICALLY_APATHETIC"
LABEL_ZOMBIE = "ZOMBIE_GOVERNANCE"

# Proposal types
TYPE_PARAM_CHANGE = "param_change"
TYPE_TREASURY = "treasury"
TYPE_UPGRADE = "upgrade"
TYPE_EMERGENCY = "emergency"

# Outcomes
OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_QUORUM_FAILED = "quorum_failed"


# ── core analyzer ────────────────────────────────────────────────────────────

class ProtocolGovernanceVoterApathyAnalyzer:
    """Analyze DeFi governance voter apathy across proposals.

    Parameters
    ----------
    config : dict, optional
        Optional threshold overrides:
        - engaged_threshold (default 40.0) — participation >= this → ENGAGED
        - moderate_threshold (default 20.0) — participation >= this → MODERATE
        - apathetic_threshold (default 10.0) — participation >= this → APATHETIC
        - zombie_threshold (default 5.0) — participation < this → ZOMBIE
        - whale_dominated_threshold (default 30.0) — top_voter_pct > this → WHALE_DOMINATED
        - manipulable_participation_threshold (default 10.0)
        - low_competition_consensus_threshold (default 90.0)
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.engaged_threshold: float = float(cfg.get("engaged_threshold", 40.0))
        self.moderate_threshold: float = float(cfg.get("moderate_threshold", 20.0))
        self.apathetic_threshold: float = float(cfg.get("apathetic_threshold", 10.0))
        self.zombie_threshold: float = float(cfg.get("zombie_threshold", 5.0))
        self.whale_dominated_threshold: float = float(
            cfg.get("whale_dominated_threshold", 30.0)
        )
        self.manipulable_participation: float = float(
            cfg.get("manipulable_participation_threshold", 10.0)
        )
        self.low_competition_threshold: float = float(
            cfg.get("low_competition_consensus_threshold", 90.0)
        )

    # ── public API ──────────────────────────────────────────────────────────

    def analyze(self, proposals: list[dict], config: dict | None = None) -> dict:
        """Analyze governance voter apathy across proposals.

        Parameters
        ----------
        proposals : list[dict]
            Each proposal dict must include:
            - protocol (str)
            - proposal_id (str)
            - title (str)
            - total_eligible_voters (int)
            - votes_cast (int)
            - votes_for_pct (float) — 0-100
            - votes_against_pct (float) — 0-100
            - quorum_required_pct (float) — 0-100
            - quorum_reached (bool)
            - proposal_type (str): param_change/treasury/upgrade/emergency
            - days_voting_period (float)
            - proposer_vp_pct (float) — proposer's % of total VP
            - top_voter_vp_pct (float) — top-1 voter's % of total cast votes
            - outcome (str): passed/failed/quorum_failed
        config : dict, optional
            Runtime overrides merged with constructor config.

        Returns
        -------
        dict with keys: proposals (list), aggregates (dict), meta (dict)
        """
        if config:
            self._merge_config(config)

        analyzed: list[dict] = []
        for prop in proposals:
            analyzed.append(self._analyze_proposal(prop))

        aggregates = self._compute_aggregates(analyzed)
        return {
            "proposals": analyzed,
            "aggregates": aggregates,
            "meta": {
                "module": MODULE_ID,
                "version": VERSION,
                "generated_at": _utcnow(),
                "proposal_count": len(analyzed),
            },
        }

    def _merge_config(self, config: dict) -> None:
        key_map = {
            "engaged_threshold": "engaged_threshold",
            "moderate_threshold": "moderate_threshold",
            "apathetic_threshold": "apathetic_threshold",
            "zombie_threshold": "zombie_threshold",
            "whale_dominated_threshold": "whale_dominated_threshold",
            "manipulable_participation_threshold": "manipulable_participation",
            "low_competition_consensus_threshold": "low_competition_threshold",
        }
        for cfg_key, attr in key_map.items():
            if cfg_key in config:
                setattr(self, attr, float(config[cfg_key]))

    # ── per-proposal analysis ───────────────────────────────────────────────

    def _analyze_proposal(self, prop: dict) -> dict:
        protocol = str(prop.get("protocol", "unknown"))
        proposal_id = str(prop.get("proposal_id", "0"))
        title = str(prop.get("title", ""))
        total_eligible = int(prop.get("total_eligible_voters", 1))
        votes_cast = int(prop.get("votes_cast", 0))
        votes_for = float(prop.get("votes_for_pct", 0.0))
        votes_against = float(prop.get("votes_against_pct", 0.0))
        quorum_required = float(prop.get("quorum_required_pct", 0.0))
        quorum_reached = bool(prop.get("quorum_reached", False))
        proposal_type = str(prop.get("proposal_type", TYPE_PARAM_CHANGE))
        days_period = float(prop.get("days_voting_period", 7.0))
        proposer_vp = float(prop.get("proposer_vp_pct", 0.0))
        top_voter_vp = float(prop.get("top_voter_vp_pct", 0.0))
        outcome = str(prop.get("outcome", OUTCOME_FAILED))

        # ── computed metrics ────────────────────────────────────────────────
        if total_eligible > 0:
            participation_rate = round((votes_cast / total_eligible) * 100.0, 6)
        else:
            participation_rate = 0.0

        effective_quorum_gap = round(quorum_required - participation_rate, 6)

        # Whale dominance: top voter's share of votes cast
        if votes_cast > 0:
            whale_dominance = round(top_voter_vp, 6)
        else:
            whale_dominance = 0.0

        # Consensus: how uncontested the vote was (max of for/against)
        consensus_score = round(max(votes_for, votes_against), 4)

        # Apathy severity 0-100: high when participation low & quorum gap large
        apathy_severity = self._compute_apathy_severity(
            participation_rate, effective_quorum_gap, quorum_required
        )

        # ── label ───────────────────────────────────────────────────────────
        if participation_rate >= self.engaged_threshold:
            label = LABEL_ENGAGED
        elif participation_rate >= self.moderate_threshold:
            label = LABEL_MODERATE
        elif participation_rate >= self.apathetic_threshold:
            label = LABEL_APATHETIC
        elif participation_rate >= self.zombie_threshold:
            label = LABEL_CRITICALLY_APATHETIC
        else:
            label = LABEL_ZOMBIE

        # ── flags ───────────────────────────────────────────────────────────
        flags: list[str] = []
        if not quorum_reached or outcome == OUTCOME_QUORUM_FAILED:
            flags.append("QUORUM_FAILED")
        if whale_dominance > self.whale_dominated_threshold:
            flags.append("WHALE_DOMINATED")
        if proposal_type == TYPE_EMERGENCY:
            flags.append("EMERGENCY_PROPOSAL")
        if consensus_score > self.low_competition_threshold:
            flags.append("LOW_COMPETITION")
        # Manipulable: low participation + no quorum protection
        if participation_rate < self.manipulable_participation and quorum_required == 0:
            flags.append("MANIPULABLE")

        return {
            "protocol": protocol,
            "proposal_id": proposal_id,
            "title": title,
            "total_eligible_voters": total_eligible,
            "votes_cast": votes_cast,
            "votes_for_pct": votes_for,
            "votes_against_pct": votes_against,
            "quorum_required_pct": quorum_required,
            "quorum_reached": quorum_reached,
            "proposal_type": proposal_type,
            "days_voting_period": days_period,
            "proposer_vp_pct": proposer_vp,
            "top_voter_vp_pct": top_voter_vp,
            "outcome": outcome,
            "participation_rate_pct": participation_rate,
            "effective_quorum_gap_pct": effective_quorum_gap,
            "whale_dominance_score": whale_dominance,
            "consensus_score": consensus_score,
            "apathy_severity_score": apathy_severity,
            "label": label,
            "flags": flags,
        }

    def _compute_apathy_severity(
        self,
        participation: float,
        quorum_gap: float,
        quorum_required: float,
    ) -> float:
        """Compute apathy severity score 0-100.

        Combines inverse participation with quorum gap magnitude.
        """
        # Inverse participation component (0-60 pts)
        inv_participation = max(0.0, 100.0 - participation)
        part_component = min(inv_participation * 0.6, 60.0)

        # Quorum gap component (0-40 pts) — only when quorum_gap > 0
        if quorum_gap > 0 and quorum_required > 0:
            gap_ratio = min(quorum_gap / quorum_required, 1.0)
            gap_component = gap_ratio * 40.0
        else:
            gap_component = 0.0

        return round(min(part_component + gap_component, 100.0), 4)

    # ── aggregates ──────────────────────────────────────────────────────────

    def _compute_aggregates(self, analyzed: list[dict]) -> dict:
        if not analyzed:
            return {
                "most_engaged_proposal_id": None,
                "most_apathetic_proposal_id": None,
                "average_participation_pct": None,
                "zombie_governance_count": 0,
                "quorum_failure_rate_pct": None,
                "whale_dominated_count": 0,
                "emergency_proposal_count": 0,
                "total_proposals": 0,
            }

        participations = [p["participation_rate_pct"] for p in analyzed]
        avg_participation = round(sum(participations) / len(participations), 6)

        most_engaged = max(analyzed, key=lambda p: p["participation_rate_pct"])
        most_apathetic = min(analyzed, key=lambda p: p["participation_rate_pct"])

        zombie_count = sum(1 for p in analyzed if p["label"] == LABEL_ZOMBIE)

        quorum_failures = sum(1 for p in analyzed if "QUORUM_FAILED" in p["flags"])
        quorum_failure_rate = round((quorum_failures / len(analyzed)) * 100.0, 4)

        whale_dominated = sum(
            1 for p in analyzed if "WHALE_DOMINATED" in p["flags"]
        )
        emergency_count = sum(
            1 for p in analyzed if "EMERGENCY_PROPOSAL" in p["flags"]
        )

        return {
            "most_engaged_proposal_id": most_engaged["proposal_id"],
            "most_apathetic_proposal_id": most_apathetic["proposal_id"],
            "average_participation_pct": avg_participation,
            "zombie_governance_count": zombie_count,
            "quorum_failure_rate_pct": quorum_failure_rate,
            "whale_dominated_count": whale_dominated,
            "emergency_proposal_count": emergency_count,
            "total_proposals": len(analyzed),
        }


# ── ring-buffer log writer ───────────────────────────────────────────────────

def write_log(result: dict, data_dir: Path) -> None:
    """Atomically append result to ring-buffer log (cap LOG_CAP)."""
    log_path = data_dir / LOG_FILE
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []

    existing.append(result)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]

    _atomic_write(log_path, json.dumps(existing, indent=2, ensure_ascii=False))
    logger.info("Log written: %s (%d entries)", log_path, len(existing))


def _atomic_write(path: Path, content: str) -> None:
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CLI ─────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Protocol Governance Voter Apathy Analyzer (MP-967)"
    )
    p.add_argument("--check", action="store_true", help="Compute and print (default)")
    p.add_argument("--run", action="store_true", help="Compute, print and write log")
    p.add_argument("--data-dir", default="data", help="Directory for log file")
    return p


def _sample_proposals() -> list[dict]:
    return [
        {
            "protocol": "Aave",
            "proposal_id": "AIP-123",
            "title": "Increase USDC supply cap",
            "total_eligible_voters": 100000,
            "votes_cast": 45000,
            "votes_for_pct": 85.0,
            "votes_against_pct": 15.0,
            "quorum_required_pct": 30.0,
            "quorum_reached": True,
            "proposal_type": "param_change",
            "days_voting_period": 7,
            "proposer_vp_pct": 2.5,
            "top_voter_vp_pct": 12.0,
            "outcome": "passed",
        },
        {
            "protocol": "Compound",
            "proposal_id": "CGP-077",
            "title": "Emergency risk parameter update",
            "total_eligible_voters": 200000,
            "votes_cast": 3000,
            "votes_for_pct": 98.0,
            "votes_against_pct": 2.0,
            "quorum_required_pct": 4.0,
            "quorum_reached": False,
            "proposal_type": "emergency",
            "days_voting_period": 2,
            "proposer_vp_pct": 5.0,
            "top_voter_vp_pct": 45.0,
            "outcome": "quorum_failed",
        },
    ]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    analyzer = ProtocolGovernanceVoterApathyAnalyzer()
    proposals = _sample_proposals()
    result = analyzer.analyze(proposals, {})

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.run:
        data_dir = Path(args.data_dir)
        write_log(result, data_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
