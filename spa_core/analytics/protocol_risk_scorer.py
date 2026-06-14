"""Protocol Risk Scorer — MP-651.

Scores DeFi protocols on risk using 5 weighted factors (0–100 each).
Lower composite score = higher risk.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/protocol_risk_scores.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/protocol_risk_scores.json")
MAX_ENTRIES = 100

# Weights must sum to 1.0
WEIGHTS: Dict[str, float] = {
    "tvl":         0.25,
    "audit":       0.25,
    "age":         0.20,
    "incident":    0.20,
    "upgradeable": 0.10,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProtocolInput:
    """Raw inputs describing a single DeFi protocol."""
    protocol_id: str
    tvl_usd: float        # total value locked in USD
    audit_count: int      # number of public security audits
    age_days: int         # days since protocol launch
    incident_count: int   # security incidents in the last 365 days
    is_upgradeable: bool  # True if contracts use an upgradeable proxy pattern


@dataclass
class ProtocolRiskScore:
    """Scored output for a single protocol."""
    protocol_id: str
    tvl_score: float            # 0-100
    audit_score: float          # 0-100
    age_score: float            # 0-100
    incident_score: float       # 0-100
    upgradeability_score: float # 0-100
    composite_score: float      # weighted average 0-100
    grade: str                  # A(>=80) / B(>=65) / C(>=50) / D(<50)
    tier_recommendation: str    # T1 / T2 / T3 / SUSPEND
    risk_flags: List[str]       # human-readable risk reasons


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class ProtocolRiskScorer:
    """Score one or many protocols and persist results atomically."""

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Sub-scorers (each returns 0-100, higher = safer)
    # ------------------------------------------------------------------

    def _tvl_score(self, tvl: float) -> float:
        """
        Piecewise-linear TVL safety score.

        >=500M -> 100
        >=100M -> 80  (linear up to 100 at 500M)
        >=10M  -> 60  (linear up to 80 at 100M)
        >=1M   -> 30  (linear up to 60 at 10M)
        <1M    -> 0..30 linear
        """
        if tvl >= 500_000_000:
            return 100.0
        if tvl >= 100_000_000:
            return 80.0 + 20.0 * (tvl - 100_000_000) / 400_000_000
        if tvl >= 10_000_000:
            return 60.0 + 20.0 * (tvl - 10_000_000) / 90_000_000
        if tvl >= 1_000_000:
            return 30.0 + 30.0 * (tvl - 1_000_000) / 9_000_000
        return max(0.0, tvl / 1_000_000 * 30.0)

    def _audit_score(self, count: int) -> float:
        """
        Discrete audit-count safety score.

        0 -> 0, 1 -> 25, 2 -> 50, 3 -> 75, >=4 -> 100
        """
        mapping = {0: 0.0, 1: 25.0, 2: 50.0, 3: 75.0}
        return mapping.get(count, 100.0)

    def _age_score(self, days: int) -> float:
        """
        Piecewise-linear age safety score.

        >=730d (2yr) -> 100
        >=365d       -> 70  (linear up to 100 at 730d)
        >=180d       -> 40  (linear up to 70 at 365d)
        >=30d        -> 10  (linear up to 40 at 180d)
        <30d         -> 0..10 linear
        """
        if days >= 730:
            return 100.0
        if days >= 365:
            return 70.0 + 30.0 * (days - 365) / 365
        if days >= 180:
            return 40.0 + 30.0 * (days - 180) / 185
        if days >= 30:
            return 10.0 + 30.0 * (days - 30) / 150
        return max(0.0, days / 30.0 * 10.0)

    def _incident_score(self, count: int) -> float:
        """
        Incident-count safety score.

        0 -> 100, 1 -> 50, 2 -> 20, >=3 -> 0
        """
        if count <= 0:
            return 100.0
        if count == 1:
            return 50.0
        if count == 2:
            return 20.0
        return 0.0

    def _upgradeability_score(self, upgradeable: bool) -> float:
        """
        Upgradeability safety score.

        Non-upgradeable (immutable) = safer = 80.
        Upgradeable (proxy) = 40.
        """
        return 40.0 if upgradeable else 80.0

    # ------------------------------------------------------------------
    # Risk flags and tier helpers
    # ------------------------------------------------------------------

    def _risk_flags(self, p: ProtocolInput, scores: Dict[str, float]) -> List[str]:
        """Return human-readable flags for any notable risk factors."""
        flags: List[str] = []
        if p.tvl_usd < 10_000_000:
            flags.append("LOW_TVL")
        if p.audit_count == 0:
            flags.append("NO_AUDITS")
        if p.age_days < 180:
            flags.append("NEW_PROTOCOL")
        if p.incident_count >= 1:
            flags.append("PRIOR_INCIDENT")
        if p.is_upgradeable:
            flags.append("UPGRADEABLE_CONTRACTS")
        return flags

    def _tier_rec(self, composite: float) -> str:
        """Recommend an allocation tier based on composite score."""
        if composite >= 80:
            return "T1"
        if composite >= 65:
            return "T2"
        if composite >= 50:
            return "T3"
        return "SUSPEND"

    def _grade(self, composite: float) -> str:
        """Letter grade: A >= 80, B >= 65, C >= 50, D < 50."""
        grade_map = [(80.0, "A"), (65.0, "B"), (50.0, "C"), (0.0, "D")]
        return next(g for threshold, g in grade_map if composite >= threshold)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, p: ProtocolInput) -> ProtocolRiskScore:
        """Compute the full risk score for a single protocol."""
        tvl = self._tvl_score(p.tvl_usd)
        aud = self._audit_score(p.audit_count)
        age = self._age_score(p.age_days)
        inc = self._incident_score(p.incident_count)
        upg = self._upgradeability_score(p.is_upgradeable)

        composite = (
            tvl * WEIGHTS["tvl"]
            + aud * WEIGHTS["audit"]
            + age * WEIGHTS["age"]
            + inc * WEIGHTS["incident"]
            + upg * WEIGHTS["upgradeable"]
        )

        scores = {
            "tvl": tvl,
            "audit": aud,
            "age": age,
            "incident": inc,
            "upgradeable": upg,
        }
        flags = self._risk_flags(p, scores)

        return ProtocolRiskScore(
            protocol_id=p.protocol_id,
            tvl_score=round(tvl, 2),
            audit_score=round(aud, 2),
            age_score=round(age, 2),
            incident_score=round(inc, 2),
            upgradeability_score=round(upg, 2),
            composite_score=round(composite, 4),
            grade=self._grade(composite),
            tier_recommendation=self._tier_rec(composite),
            risk_flags=flags,
        )

    def score_batch(self, protocols: List[ProtocolInput]) -> List[ProtocolRiskScore]:
        """Score a list of protocols, returning one result per protocol."""
        return [self.score(p) for p in protocols]

    def save_scores(self, scores: List[ProtocolRiskScore]) -> None:
        """Atomically append scored entries to the ring-buffer JSON file."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: list = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        ts = time.time()
        for s in scores:
            existing.append(
                {
                    "timestamp": ts,
                    "protocol_id": s.protocol_id,
                    "composite_score": s.composite_score,
                    "grade": s.grade,
                    "tier_recommendation": s.tier_recommendation,
                    "risk_flags": s.risk_flags,
                }
            )
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return the full history list from the JSON file, or [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
