"""
MP-669: FlashLoanRiskAnalyzer
Assess flash loan attack risk for DeFi protocols in the portfolio.
Flash loans enable price manipulation and oracle attacks within a single block.

Advisory/read-only — never modifies allocator, risk, or execution domains.
Pure stdlib only. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/flash_loan_risk_log.json")
MAX_ENTRIES = 100

# Flash loan attack vectors
ATTACK_VECTORS = {
    "PRICE_MANIPULATION": "Manipulate AMM price within single block",
    "ORACLE_ATTACK": "Exploit spot price oracles via large swap",
    "GOVERNANCE_ATTACK": "Borrow voting tokens, pass malicious proposal",
    "COLLATERAL_ATTACK": "Manipulate collateral price to drain lending protocol",
}


@dataclass
class ProtocolFlashLoanProfile:
    protocol_id: str
    protocol_type: str            # "AMM", "LENDING", "GOVERNANCE", "YIELD"
    tvl_usd: float
    uses_spot_price_oracle: bool  # True = vulnerable to oracle manipulation
    has_time_weighted_oracle: bool  # TWAP is resistant to flash loan attack
    governance_token_pct_in_amm: float  # % of gov tokens that can be borrowed
    min_block_delay: int          # governance delay in blocks (0 = vulnerable)
    flash_loan_available: bool    # can flash loans be taken against this protocol?


@dataclass
class FlashLoanRisk:
    protocol_id: str
    protocol_type: str
    price_manipulation_risk: float   # 0.0–1.0
    oracle_attack_risk: float        # 0.0–1.0
    governance_attack_risk: float    # 0.0–1.0
    composite_risk: float            # weighted average
    risk_tier: str                   # NEGLIGIBLE / LOW / MEDIUM / HIGH / CRITICAL
    attack_vectors: List[str]        # active vectors
    mitigations: List[str]           # what's protecting against attacks
    advisory: str


class FlashLoanRiskAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _price_manip_risk(self, p: ProtocolFlashLoanProfile) -> float:
        if p.protocol_type != "AMM":
            return 0.05
        base = 0.2
        # Small TVL = easier to manipulate
        tvl_factor = max(0.0, 1.0 - p.tvl_usd / 100_000_000)  # 100M TVL = 0 factor
        return round(min(1.0, base + 0.5 * tvl_factor), 4)

    def _oracle_risk(self, p: ProtocolFlashLoanProfile) -> float:
        if not p.uses_spot_price_oracle:
            return 0.05
        if p.has_time_weighted_oracle:
            return 0.10  # TWAP is resistant
        # Spot oracle = high risk
        base = 0.6
        tvl_factor = max(0.0, 1.0 - p.tvl_usd / 500_000_000)
        return round(min(1.0, base + 0.3 * tvl_factor), 4)

    def _governance_risk(self, p: ProtocolFlashLoanProfile) -> float:
        if p.protocol_type != "GOVERNANCE":
            return 0.02
        if p.min_block_delay >= 100:
            return 0.05  # time delay protects
        # Large % of gov tokens in AMM = vulnerable
        base = 0.3 * p.governance_token_pct_in_amm
        if p.min_block_delay == 0:
            base += 0.4
        return round(min(1.0, base), 4)

    def _composite(self, pm: float, ora: float, gov: float) -> float:
        return round((pm * 0.35 + ora * 0.40 + gov * 0.25), 4)

    def _risk_tier(self, composite: float) -> str:
        if composite >= 0.70:
            return "CRITICAL"
        if composite >= 0.45:
            return "HIGH"
        if composite >= 0.25:
            return "MEDIUM"
        if composite >= 0.10:
            return "LOW"
        return "NEGLIGIBLE"

    def _attack_vectors(
        self,
        p: ProtocolFlashLoanProfile,
        pm: float,
        ora: float,
        gov: float,
    ) -> List[str]:
        vectors = []
        if pm > 0.3:
            vectors.append("PRICE_MANIPULATION")
        if ora > 0.3:
            vectors.append("ORACLE_ATTACK")
        if gov > 0.3:
            vectors.append("GOVERNANCE_ATTACK")
        return vectors

    def _mitigations(self, p: ProtocolFlashLoanProfile) -> List[str]:
        mits = []
        if p.has_time_weighted_oracle:
            mits.append("TWAP oracle (flash-loan resistant)")
        if p.min_block_delay >= 100:
            mits.append(f"Governance delay: {p.min_block_delay} blocks")
        if p.tvl_usd >= 100_000_000:
            mits.append(
                f"High TVL (${p.tvl_usd / 1e6:.0f}M — expensive to manipulate)"
            )
        if not p.flash_loan_available:
            mits.append("Flash loans not available in this protocol")
        if not mits:
            mits.append("No significant mitigations detected")
        return mits

    def _advisory(self, tier: str, vectors: List[str]) -> str:
        vec_str = ", ".join(vectors) if vectors else "none"
        advisories = {
            "CRITICAL": f"⛔ CRITICAL flash loan risk. Active vectors: {vec_str}. Avoid or exit.",
            "HIGH": f"🚨 HIGH risk. Vectors: {vec_str}. Reduce exposure.",
            "MEDIUM": f"⚠️ MEDIUM risk. Vectors: {vec_str}. Monitor closely.",
            "LOW": "📋 LOW risk. No immediate concern.",
            "NEGLIGIBLE": "✅ Flash loan risk negligible.",
        }
        return advisories[tier]

    def analyze(self, p: ProtocolFlashLoanProfile) -> FlashLoanRisk:
        pm = self._price_manip_risk(p)
        ora = self._oracle_risk(p)
        gov = self._governance_risk(p)
        composite = self._composite(pm, ora, gov)
        tier = self._risk_tier(composite)
        vectors = self._attack_vectors(p, pm, ora, gov)
        mits = self._mitigations(p)
        return FlashLoanRisk(
            protocol_id=p.protocol_id,
            protocol_type=p.protocol_type,
            price_manipulation_risk=pm,
            oracle_attack_risk=ora,
            governance_attack_risk=gov,
            composite_risk=composite,
            risk_tier=tier,
            attack_vectors=vectors,
            mitigations=mits,
            advisory=self._advisory(tier, vectors),
        )

    def analyze_batch(
        self, profiles: List[ProtocolFlashLoanProfile]
    ) -> List[FlashLoanRisk]:
        return [self.analyze(p) for p in profiles]

    def critical_protocols(
        self, results: List[FlashLoanRisk]
    ) -> List[FlashLoanRisk]:
        return [r for r in results if r.risk_tier in ("HIGH", "CRITICAL")]

    def save_results(self, results: List[FlashLoanRisk]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append(
                {
                    "timestamp": time.time(),
                    "protocol_id": r.protocol_id,
                    "composite_risk": r.composite_risk,
                    "risk_tier": r.risk_tier,
                    "attack_vectors": r.attack_vectors,
                }
            )
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
