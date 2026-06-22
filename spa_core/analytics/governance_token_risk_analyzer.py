"""
MP-675: GovernanceTokenRiskAnalyzer
Assess governance token concentration risk, voting power centralization,
and protocol capture risk.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/governance_risk_log.json")
MAX_ENTRIES = 100


@dataclass
class GovernanceProfile:
    protocol_id: str
    token_symbol: str
    total_supply: float           # total token supply
    circulating_supply: float     # tokens in circulation
    top10_holder_pct: float       # % held by top 10 addresses (0-100)
    team_held_pct: float          # % held by team/foundation
    dao_treasury_pct: float       # % held by DAO treasury
    active_voters_30d: int        # number of unique voters in last 30 days
    total_proposals_90d: int      # governance proposals last 90 days
    quorum_threshold_pct: float   # minimum participation needed (0-100)
    timelock_hours: int           # hours before approved changes take effect
    has_veto_multisig: bool       # emergency veto exists


@dataclass
class GovernanceRiskReport:
    protocol_id: str
    token_symbol: str
    centralization_score: float    # 0.0–1.0 (1=fully centralized)
    plutocracy_risk: float         # 0.0–1.0 (token-weighted voting captured by whales)
    governance_activity: str       # ACTIVE / MODERATE / DORMANT
    capture_risk: str              # LOW / MEDIUM / HIGH / CRITICAL
    voter_apathy_score: float      # 0.0–1.0 (1=no one votes)
    safety_score: float            # 0.0–1.0 (1=well protected)
    overall_grade: str             # A / B / C / D / F
    recommendations: List[str]


class GovernanceTokenRiskAnalyzer:
    """
    Analyzes governance token risk for DeFi protocols.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _centralization_score(top10_holder_pct: float, team_held_pct: float) -> float:
        """
        Weighted: (top10/100)*0.5 + (team/100)*0.5
        Clamped to [0, 1].
        """
        score = (top10_holder_pct / 100.0) * 0.5 + (team_held_pct / 100.0) * 0.5
        return max(0.0, min(1.0, score))

    @staticmethod
    def _plutocracy_risk(top10_holder_pct: float) -> float:
        """
        risk = min(1.0, top10_holder_pct / 100 * 1.5)
        """
        return min(1.0, top10_holder_pct / 100.0 * 1.5)

    @staticmethod
    def _governance_activity(
        total_proposals_90d: int,
        active_voters_30d: int,
    ) -> str:
        """
        ACTIVE: proposals>=3 AND voters>=100
        MODERATE: proposals>=1 AND voters>=20
        DORMANT: otherwise
        """
        if total_proposals_90d >= 3 and active_voters_30d >= 100:
            return "ACTIVE"
        if total_proposals_90d >= 1 and active_voters_30d >= 20:
            return "MODERATE"
        return "DORMANT"

    @staticmethod
    def _voter_apathy_score(active_voters_30d: int) -> float:
        """
        1.0 - min(1.0, active_voters_30d / 500)
        500+ voters → 0.0; 0 voters → 1.0
        """
        return 1.0 - min(1.0, active_voters_30d / 500.0)

    @staticmethod
    def _safety_score(
        timelock_hours: int,
        has_veto_multisig: bool,
        quorum_threshold_pct: float,
    ) -> float:
        """
        Base 0.5
        +0.2 if timelock_hours >= 48
        +0.2 if has_veto_multisig
        +0.1 if quorum_threshold_pct >= 5
        -0.2 if timelock_hours == 0
        Clamped [0, 1]
        """
        score = 0.5
        if timelock_hours >= 48:
            score += 0.2
        if has_veto_multisig:
            score += 0.2
        if quorum_threshold_pct >= 5:
            score += 0.1
        if timelock_hours == 0:
            score -= 0.2
        return max(0.0, min(1.0, score))

    @staticmethod
    def _capture_risk(
        centralization_score: float,
        team_held_pct: float,
        plutocracy_risk: float,
    ) -> str:
        """
        CRITICAL: centralization>0.7 OR team_held_pct>50
        HIGH:     centralization>0.5 OR plutocracy>0.7
        MEDIUM:   centralization>0.3
        LOW:      otherwise
        """
        if centralization_score > 0.7 or team_held_pct > 50:
            return "CRITICAL"
        if centralization_score > 0.5 or plutocracy_risk > 0.7:
            return "HIGH"
        if centralization_score > 0.3:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _overall_grade(
        centralization_score: float,
        plutocracy_risk: float,
        safety_score: float,
        voter_apathy_score: float,
    ) -> str:
        """
        avg = ((1-centralization) + (1-plutocracy) + safety + (1-voter_apathy)) / 4
        ≥0.8→A, ≥0.65→B, ≥0.5→C, ≥0.35→D, else→F
        """
        avg = (
            (1.0 - centralization_score)
            + (1.0 - plutocracy_risk)
            + safety_score
            + (1.0 - voter_apathy_score)
        ) / 4.0
        if avg >= 0.8:
            return "A"
        if avg >= 0.65:
            return "B"
        if avg >= 0.5:
            return "C"
        if avg >= 0.35:
            return "D"
        return "F"

    @staticmethod
    def _recommendations(
        profile: GovernanceProfile,
        centralization_score: float,
        voter_apathy_score: float,
        safety_score: float,
    ) -> List[str]:
        """Generate advisory recommendation strings."""
        recs: List[str] = []
        if centralization_score > 0.6:
            recs.append(
                "⚠️ High token concentration — governance capture risk"
            )
        if profile.team_held_pct > 20:
            recs.append(
                f"⚠️ Team holds {profile.team_held_pct:.0f}% — conflict of interest risk"
            )
        if voter_apathy_score > 0.7:
            recs.append(
                "📋 Low voter participation — protocol health concern"
            )
        if profile.timelock_hours < 24:
            recs.append(
                "🚨 Short timelock (<24h) — insufficient protection against malicious proposals"
            )
        if not profile.has_veto_multisig:
            recs.append(
                "⚠️ No emergency veto — consider multisig safety net"
            )
        if safety_score > 0.7:
            recs.append("✅ Strong governance safety mechanisms")
        return recs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, profile: GovernanceProfile) -> GovernanceRiskReport:
        """Compute a full GovernanceRiskReport for a single protocol."""
        centralization = self._centralization_score(
            profile.top10_holder_pct, profile.team_held_pct
        )
        plutocracy = self._plutocracy_risk(profile.top10_holder_pct)
        activity = self._governance_activity(
            profile.total_proposals_90d, profile.active_voters_30d
        )
        voter_apathy = self._voter_apathy_score(profile.active_voters_30d)
        safety = self._safety_score(
            profile.timelock_hours,
            profile.has_veto_multisig,
            profile.quorum_threshold_pct,
        )
        capture = self._capture_risk(centralization, profile.team_held_pct, plutocracy)
        grade = self._overall_grade(centralization, plutocracy, safety, voter_apathy)
        recs = self._recommendations(profile, centralization, voter_apathy, safety)

        return GovernanceRiskReport(
            protocol_id=profile.protocol_id,
            token_symbol=profile.token_symbol,
            centralization_score=round(centralization, 4),
            plutocracy_risk=round(plutocracy, 4),
            governance_activity=activity,
            capture_risk=capture,
            voter_apathy_score=round(voter_apathy, 4),
            safety_score=round(safety, 4),
            overall_grade=grade,
            recommendations=recs,
        )

    def analyze_batch(
        self, profiles: List[GovernanceProfile]
    ) -> List[GovernanceRiskReport]:
        """Analyze a list of governance profiles, return list of reports."""
        return [self.analyze(p) for p in profiles]

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic writes)
    # ------------------------------------------------------------------

    def save_results(
        self,
        reports: List[GovernanceRiskReport],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append reports to ring-buffer JSON file (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        new_entries = [
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "protocol_id": r.protocol_id,
                "token_symbol": r.token_symbol,
                "centralization_score": r.centralization_score,
                "plutocracy_risk": r.plutocracy_risk,
                "governance_activity": r.governance_activity,
                "capture_risk": r.capture_risk,
                "voter_apathy_score": r.voter_apathy_score,
                "safety_score": r.safety_score,
                "overall_grade": r.overall_grade,
                "recommendations": r.recommendations,
            }
            for r in reports
        ]

        combined = existing + new_entries
        combined = combined[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load history from ring-buffer JSON. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    analyzer = GovernanceTokenRiskAnalyzer()
    demo_profile = GovernanceProfile(
        protocol_id="aave-v3",
        token_symbol="AAVE",
        total_supply=16_000_000.0,
        circulating_supply=14_000_000.0,
        top10_holder_pct=28.0,
        team_held_pct=10.0,
        dao_treasury_pct=15.0,
        active_voters_30d=340,
        total_proposals_90d=8,
        quorum_threshold_pct=4.0,
        timelock_hours=24,
        has_veto_multisig=True,
    )
    report = analyzer.analyze(demo_profile)
    print(f"Protocol:              {report.protocol_id} ({report.token_symbol})")
    print(f"Centralization score:  {report.centralization_score:.4f}")
    print(f"Plutocracy risk:       {report.plutocracy_risk:.4f}")
    print(f"Governance activity:   {report.governance_activity}")
    print(f"Capture risk:          {report.capture_risk}")
    print(f"Voter apathy score:    {report.voter_apathy_score:.4f}")
    print(f"Safety score:          {report.safety_score:.4f}")
    print(f"Overall grade:         {report.overall_grade}")
    print("Recommendations:")
    for rec in report.recommendations:
        print(f"  {rec}")


if __name__ == "__main__":
    _demo()
