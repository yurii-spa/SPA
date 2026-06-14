"""
MP-668: MEVRiskDetector
Detect Maximal Extractable Value (MEV) risk for DeFi transactions.
Estimate likelihood of front-running, sandwich attacks, and liquidation bots.

Advisory/read-only — never modifies allocator, risk, or execution domains.
Pure stdlib only. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/mev_risk_log.json")
MAX_ENTRIES = 100

# MEV attack type definitions
MEV_ATTACK_TYPES = {
    "SANDWICH": "Bot places buy before and sell after victim tx",
    "FRONTRUN": "Bot copies profitable tx with higher gas",
    "LIQUIDATION": "Bot triggers and profits from liquidation",
    "ARBITRAGE": "Bot exploits price differences (neutral to victim)",
}


@dataclass
class TransactionProfile:
    tx_type: str               # "SWAP", "DEPOSIT", "WITHDRAW", "LIQUIDATE"
    token_in: str              # input token symbol
    token_out: str             # output token symbol
    amount_usd: float          # transaction size in USD
    pool_tvl_usd: float        # pool TVL
    slippage_tolerance_pct: float  # user-set max slippage (e.g. 0.5 = 0.5%)
    gas_price_gwei: float      # tx gas price
    mempool_gas_gwei: float    # current mempool baseline gas
    is_private_mempool: bool   # True = flashbots/private RPC (MEV protected)


@dataclass
class MEVRiskAssessment:
    tx_type: str
    amount_usd: float
    sandwich_risk: float       # 0.0–1.0 probability
    frontrun_risk: float       # 0.0–1.0 probability
    liquidation_risk: float    # 0.0–1.0 probability
    composite_risk: float      # weighted max, 0.0–1.0
    risk_level: str            # LOW / MEDIUM / HIGH / CRITICAL
    protected: bool            # True if using private mempool
    estimated_loss_usd: float  # expected MEV loss = amount * slippage/100 * sandwich_risk
    recommendations: List[str]


class MEVRiskDetector:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _sandwich_risk(self, profile: TransactionProfile) -> float:
        """
        Sandwich risk based on:
        - Large trade relative to pool (>1% TVL = high risk)
        - High slippage tolerance (>1% = high risk)
        - Public mempool (not private RPC)
        Base: 0.1 if swap, else 0.02
        """
        if profile.tx_type != "SWAP":
            return 0.02

        base = 0.10
        # Size factor: large trades are more attractive to MEV bots
        size_ratio = profile.amount_usd / profile.pool_tvl_usd if profile.pool_tvl_usd > 0 else 0.0
        size_factor = min(1.0, size_ratio * 20)  # 5% of pool = max factor

        # Slippage factor: high tolerance = more profit for bot
        slip_factor = min(1.0, profile.slippage_tolerance_pct / 3.0)  # 3% = max

        risk = base + 0.5 * size_factor + 0.4 * slip_factor
        if profile.is_private_mempool:
            risk *= 0.05  # 95% reduction with MEV protection

        return round(min(1.0, risk), 4)

    def _frontrun_risk(self, profile: TransactionProfile) -> float:
        """
        Frontrun risk for large, profitable-looking transactions.
        Higher for SWAP, lower for DEPOSIT/WITHDRAW.
        """
        if profile.tx_type not in ("SWAP",):
            return 0.01

        # Gas competition: if tx gas is much higher than baseline, bot is interested
        gas_premium = (
            (profile.gas_price_gwei - profile.mempool_gas_gwei) / profile.mempool_gas_gwei
            if profile.mempool_gas_gwei > 0 else 0.0
        )
        gas_factor = min(1.0, max(0.0, gas_premium))

        # Tx size matters
        size_factor = min(1.0, profile.amount_usd / 100_000)  # 100k = saturated

        risk = 0.05 + 0.3 * size_factor + 0.2 * gas_factor
        if profile.is_private_mempool:
            risk *= 0.05

        return round(min(1.0, risk), 4)

    def _liquidation_risk(self, profile: TransactionProfile) -> float:
        """Liquidation MEV risk applies only to LIQUIDATE transactions."""
        if profile.tx_type != "LIQUIDATE":
            return 0.0
        # Liquidations are always high-value MEV targets
        base = 0.7
        if profile.is_private_mempool:
            base *= 0.3
        return round(base, 4)

    def _composite(self, s: float, f: float, l: float) -> float:
        """Composite = max of components, weighted."""
        return round(max(s * 0.5, f * 0.3, l * 0.8), 4)

    def _risk_level(self, composite: float) -> str:
        if composite >= 0.6:
            return "CRITICAL"
        if composite >= 0.3:
            return "HIGH"
        if composite >= 0.1:
            return "MEDIUM"
        return "LOW"

    def _recommendations(
        self,
        profile: TransactionProfile,
        sandwich: float,
        frontrun: float,
    ) -> List[str]:
        recs = []
        if profile.is_private_mempool:
            recs.append("✅ Private mempool active — MEV protected")
        else:
            recs.append("⚠️ Use private mempool (Flashbots, MEV Blocker)")
        if sandwich > 0.3:
            recs.append(
                f"🥪 Sandwich risk {sandwich:.0%} — reduce slippage tolerance to <0.5%"
            )
        if frontrun > 0.2:
            recs.append(f"🏃 Frontrun risk {frontrun:.0%} — split large trades")
        if profile.slippage_tolerance_pct > 1.0:
            recs.append(
                "⚠️ Slippage tolerance >1% makes sandwich attacks more profitable"
            )
        if not recs or (len(recs) == 1 and profile.is_private_mempool):
            recs.append("✅ Low MEV risk — proceed normally")
        return recs

    def assess(self, profile: TransactionProfile) -> MEVRiskAssessment:
        s = self._sandwich_risk(profile)
        f = self._frontrun_risk(profile)
        l = self._liquidation_risk(profile)
        composite = self._composite(s, f, l)
        level = self._risk_level(composite)
        est_loss = round(
            profile.amount_usd * (profile.slippage_tolerance_pct / 100) * s, 4
        )
        return MEVRiskAssessment(
            tx_type=profile.tx_type,
            amount_usd=round(profile.amount_usd, 2),
            sandwich_risk=s,
            frontrun_risk=f,
            liquidation_risk=l,
            composite_risk=composite,
            risk_level=level,
            protected=profile.is_private_mempool,
            estimated_loss_usd=est_loss,
            recommendations=self._recommendations(profile, s, f),
        )

    def assess_batch(
        self, profiles: List[TransactionProfile]
    ) -> List[MEVRiskAssessment]:
        return [self.assess(p) for p in profiles]

    def high_risk_txs(
        self, results: List[MEVRiskAssessment]
    ) -> List[MEVRiskAssessment]:
        return [r for r in results if r.risk_level in ("HIGH", "CRITICAL")]

    def save_results(self, results: List[MEVRiskAssessment]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append(
                {
                    "timestamp": time.time(),
                    "tx_type": r.tx_type,
                    "composite_risk": r.composite_risk,
                    "risk_level": r.risk_level,
                    "estimated_loss_usd": r.estimated_loss_usd,
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
