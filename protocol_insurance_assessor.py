"""
MP-677: ProtocolInsuranceAssessor
Assess the value of protocol insurance coverage and recommend coverage amounts
based on position risk.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/insurance_assessor_log.json")
MAX_ENTRIES = 100

# Known DeFi insurance protocols and their characteristics
INSURANCE_PROTOCOLS = {
    "nexus_mutual":   {"annual_premium_pct": 2.6, "max_cover_usd": 1_000_000, "payout_speed_days": 30},
    "insurace":       {"annual_premium_pct": 2.0, "max_cover_usd": 500_000,   "payout_speed_days": 14},
    "unslashed":      {"annual_premium_pct": 3.5, "max_cover_usd": 200_000,   "payout_speed_days": 7},
    "ribbon_protect": {"annual_premium_pct": 1.5, "max_cover_usd": 250_000,   "payout_speed_days": 21},
}


@dataclass
class InsuranceNeed:
    position_id: str
    protocol: str
    position_value_usd: float
    protocol_risk_score: float      # 0.0–1.0 from ProtocolRiskScorer
    smart_contract_risk: float      # 0.0–1.0 specific SC risk
    has_existing_coverage: bool
    existing_coverage_usd: float    # 0 if no coverage


@dataclass
class InsuranceRecommendation:
    position_id: str
    recommended_cover_usd: float        # suggested coverage amount
    coverage_gap_usd: float             # recommended - existing (min 0)
    annual_premium_usd: float           # estimated annual cost
    premium_as_pct_of_position: float   # annual_premium / position_value * 100
    best_provider: str                  # name from INSURANCE_PROTOCOLS
    is_cost_effective: bool             # True if premium < expected_loss
    expected_annual_loss_usd: float     # position * composite_risk
    recommendation: str                 # COVER / PARTIAL / SKIP
    rationale: str


class ProtocolInsuranceAssessor:
    """
    Assesses insurance needs for DeFi protocol positions.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _composite_risk(need: InsuranceNeed) -> float:
        """Weighted average of protocol and smart-contract risk. Clamped [0, 1]."""
        score = need.protocol_risk_score * 0.5 + need.smart_contract_risk * 0.5
        return max(0.0, min(1.0, score))

    @staticmethod
    def _recommended_cover(
        position_value: float, composite_risk: float, existing_coverage: float
    ) -> float:
        """
        Risk-weighted coverage = position_value * composite_risk * 1.5.
        At minimum equals existing coverage; capped at position_value.
        """
        raw = position_value * composite_risk * 1.5
        cover = max(raw, existing_coverage)
        return min(cover, position_value)

    @staticmethod
    def _coverage_gap(recommended: float, existing: float) -> float:
        """Gap between recommended cover and existing coverage. Never negative."""
        return max(0.0, recommended - existing)

    @staticmethod
    def _expected_annual_loss(position_value: float, composite_risk: float) -> float:
        """Expected annual loss = position_value * composite_risk."""
        return position_value * composite_risk

    @staticmethod
    def _best_provider(recommended_cover: float) -> str:
        """
        Filter providers where max_cover >= recommended_cover.
        Among qualifying providers, select lowest annual_premium_pct.
        If none qualify, return the provider with the highest max_cover_usd.
        """
        qualifying = {
            name: info
            for name, info in INSURANCE_PROTOCOLS.items()
            if info["max_cover_usd"] >= recommended_cover
        }
        if qualifying:
            return min(qualifying, key=lambda n: qualifying[n]["annual_premium_pct"])
        # fallback: highest max_cover
        return max(INSURANCE_PROTOCOLS, key=lambda n: INSURANCE_PROTOCOLS[n]["max_cover_usd"])

    @staticmethod
    def _annual_premium(recommended_cover: float, provider: str) -> float:
        """Annual premium = recommended_cover * provider's annual_premium_pct / 100."""
        pct = INSURANCE_PROTOCOLS[provider]["annual_premium_pct"]
        return recommended_cover * pct / 100.0

    @staticmethod
    def _is_cost_effective(annual_premium: float, expected_annual_loss: float) -> bool:
        """True if premium < expected annual loss."""
        return annual_premium < expected_annual_loss

    @staticmethod
    def _recommendation(
        composite_risk: float,
        is_cost_effective: bool,
    ) -> str:
        """
        SKIP   : composite_risk < 0.15
        COVER  : is_cost_effective
        PARTIAL: composite_risk >= 0.4
        SKIP   : otherwise
        """
        if composite_risk < 0.15:
            return "SKIP"
        if is_cost_effective:
            return "COVER"
        if composite_risk >= 0.4:
            return "PARTIAL"
        return "SKIP"

    @staticmethod
    def _rationale(
        recommendation: str,
        annual_premium: float,
        expected_annual_loss: float,
        composite_risk: float,
    ) -> str:
        if recommendation == "COVER":
            return (
                f"Premium ${annual_premium:.0f}/yr is less than expected loss "
                f"${expected_annual_loss:.0f}/yr — cost effective"
            )
        if recommendation == "PARTIAL":
            return (
                f"Premium exceeds expected loss but composite risk "
                f"{composite_risk:.1%} warrants partial coverage"
            )
        # SKIP
        return (
            f"Composite risk {composite_risk:.1%} too low to justify insurance cost"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, need: InsuranceNeed) -> InsuranceRecommendation:
        """Compute a full InsuranceRecommendation for a single position."""
        composite = self._composite_risk(need)
        rec_cover = self._recommended_cover(
            need.position_value_usd, composite, need.existing_coverage_usd
        )
        gap = self._coverage_gap(rec_cover, need.existing_coverage_usd)
        expected_loss = self._expected_annual_loss(need.position_value_usd, composite)
        provider = self._best_provider(rec_cover)
        premium = self._annual_premium(rec_cover, provider)
        cost_effective = self._is_cost_effective(premium, expected_loss)
        rec = self._recommendation(composite, cost_effective)
        rationale = self._rationale(rec, premium, expected_loss, composite)
        premium_pct = (
            premium / need.position_value_usd * 100.0
            if need.position_value_usd > 0
            else 0.0
        )

        return InsuranceRecommendation(
            position_id=need.position_id,
            recommended_cover_usd=rec_cover,
            coverage_gap_usd=gap,
            annual_premium_usd=premium,
            premium_as_pct_of_position=premium_pct,
            best_provider=provider,
            is_cost_effective=cost_effective,
            expected_annual_loss_usd=expected_loss,
            recommendation=rec,
            rationale=rationale,
        )

    def assess_batch(self, needs: List[InsuranceNeed]) -> List[InsuranceRecommendation]:
        """Assess a list of insurance needs. Returns [] for empty input."""
        return [self.assess(n) for n in needs]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(
        self,
        recommendations: List[InsuranceRecommendation],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append recommendations to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        new_entries = [
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "position_id": r.position_id,
                "recommended_cover_usd": r.recommended_cover_usd,
                "coverage_gap_usd": r.coverage_gap_usd,
                "annual_premium_usd": r.annual_premium_usd,
                "premium_as_pct_of_position": r.premium_as_pct_of_position,
                "best_provider": r.best_provider,
                "is_cost_effective": r.is_cost_effective,
                "expected_annual_loss_usd": r.expected_annual_loss_usd,
                "recommendation": r.recommendation,
                "rationale": r.rationale,
            }
            for r in recommendations
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
    assessor = ProtocolInsuranceAssessor()
    demo_need = InsuranceNeed(
        position_id="aave_v3_usdc_main",
        protocol="aave_v3",
        position_value_usd=100_000.0,
        protocol_risk_score=0.3,
        smart_contract_risk=0.25,
        has_existing_coverage=False,
        existing_coverage_usd=0.0,
    )
    rec = assessor.assess(demo_need)
    print(f"Position:              {rec.position_id}")
    print(f"Recommended cover:     ${rec.recommended_cover_usd:,.0f}")
    print(f"Coverage gap:          ${rec.coverage_gap_usd:,.0f}")
    print(f"Annual premium:        ${rec.annual_premium_usd:,.0f}")
    print(f"Premium % of position: {rec.premium_as_pct_of_position:.2f}%")
    print(f"Best provider:         {rec.best_provider}")
    print(f"Cost effective:        {rec.is_cost_effective}")
    print(f"Expected annual loss:  ${rec.expected_annual_loss_usd:,.0f}")
    print(f"Recommendation:        {rec.recommendation}")
    print(f"Rationale:             {rec.rationale}")


if __name__ == "__main__":
    _demo()
