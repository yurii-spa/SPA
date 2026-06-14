"""
MP-671: CrossChainBridgeRiskAnalyzer
Assess risk of using cross-chain bridges for capital movement.
Bridge hacks have caused billions in losses.

Advisory / read-only. Pure stdlib. Atomic writes (os.replace).
"""

from dataclasses import dataclass, field
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/bridge_risk_log.json")
MAX_ENTRIES = 100

KNOWN_HACKED_BRIDGES = {
    "ronin": 625_000_000,
    "wormhole": 320_000_000,
    "nomad": 190_000_000,
    "harmony": 100_000_000,
    "multichain": 126_000_000,
}


@dataclass
class BridgeProfile:
    bridge_id: str
    bridge_type: str         # "LOCK_MINT", "LIQUIDITY", "NATIVE", "ZK_PROOF"
    tvl_usd: float
    transfer_amount_usd: float
    audit_count: int
    has_multisig: bool       # multi-sig or MPC for validator set
    validator_count: int     # number of independent validators
    has_bug_bounty: bool
    protocol_age_days: int
    previously_hacked: bool  # True if this bridge was ever hacked
    hack_amount_usd: float   # 0 if not hacked


@dataclass
class BridgeRiskReport:
    bridge_id: str
    bridge_type: str
    architecture_risk: float   # 0.0–1.0
    custody_risk: float        # 0.0–1.0 (validator centralization)
    smart_contract_risk: float  # 0.0–1.0
    composite_risk: float
    risk_level: str            # SAFE / LOW / MEDIUM / HIGH / EXTREME
    transfer_risk_usd: float   # estimated expected loss = amount * composite_risk
    recommendations: List[str] = field(default_factory=list)
    bridge_verdict: str = "CAUTION"  # APPROVE / CAUTION / AVOID


# ---------------------------------------------------------------------------
# Architecture type base risks
# ---------------------------------------------------------------------------

_ARCH_BASE = {
    "LOCK_MINT": 0.60,
    "LIQUIDITY": 0.30,
    "NATIVE": 0.15,
    "ZK_PROOF": 0.05,
}


def _arch_risk(bridge_type: str, previously_hacked: bool) -> float:
    base = _ARCH_BASE.get(bridge_type, 0.60)
    if previously_hacked:
        base = min(1.0, base * 1.5)
    return base


def _custody_risk(validator_count: int, has_multisig: bool,
                  has_bug_bounty: bool) -> float:
    base = 1.0 / (validator_count + 1)
    if has_multisig:
        base -= 0.10
    if has_bug_bounty:
        base -= 0.05
    return max(0.02, min(0.95, base))


def _sc_risk(audit_count: int, protocol_age_days: int) -> float:
    base = 0.60
    base -= 0.10 * min(3, audit_count)
    if protocol_age_days > 365:
        base -= 0.10
    return max(0.05, min(0.90, base))


def _composite_risk(arch: float, custody: float, sc: float) -> float:
    return arch * 0.40 + custody * 0.35 + sc * 0.25


def _risk_level(composite: float) -> str:
    if composite < 0.15:
        return "SAFE"
    if composite < 0.30:
        return "LOW"
    if composite < 0.50:
        return "MEDIUM"
    if composite < 0.70:
        return "HIGH"
    return "EXTREME"


def _build_recommendations(arch_risk: float, custody_risk: float,
                            previously_hacked: bool,
                            transfer_amount_usd: float, tvl_usd: float,
                            risk_level: str) -> List[str]:
    recs: List[str] = []
    if arch_risk > 0.5:
        recs.append(
            "⚠️ Lock-mint bridges have highest hack risk — prefer native or ZK bridges"
        )
    if custody_risk > 0.5:
        recs.append(
            "⚠️ Centralized validator set — use higher validator count bridge"
        )
    if previously_hacked:
        recs.append("🚨 This bridge was previously hacked — avoid")
    if tvl_usd > 0 and transfer_amount_usd > tvl_usd * 0.10:
        recs.append("⚠️ Transfer >10% of bridge TVL — liquidity risk")
    if risk_level in ("SAFE", "LOW"):
        recs.append("✅ Bridge risk acceptable for this transfer")
    return recs


def _bridge_verdict(risk_level: str) -> str:
    if risk_level in ("SAFE", "LOW"):
        return "APPROVE"
    if risk_level == "MEDIUM":
        return "CAUTION"
    return "AVOID"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CrossChainBridgeRiskAnalyzer:
    """Advisory cross-chain bridge risk analyzer. Read-only analytics, stdlib only."""

    def analyze(self, profile: BridgeProfile) -> BridgeRiskReport:
        """Analyze risk for a single bridge profile and return a risk report."""
        arch = _arch_risk(profile.bridge_type, profile.previously_hacked)
        custody = _custody_risk(profile.validator_count, profile.has_multisig,
                                profile.has_bug_bounty)
        sc = _sc_risk(profile.audit_count, profile.protocol_age_days)
        composite = _composite_risk(arch, custody, sc)
        level = _risk_level(composite)
        expected_loss = profile.transfer_amount_usd * composite
        recs = _build_recommendations(
            arch, custody, profile.previously_hacked,
            profile.transfer_amount_usd, profile.tvl_usd, level,
        )
        verdict = _bridge_verdict(level)

        return BridgeRiskReport(
            bridge_id=profile.bridge_id,
            bridge_type=profile.bridge_type,
            architecture_risk=arch,
            custody_risk=custody,
            smart_contract_risk=sc,
            composite_risk=composite,
            risk_level=level,
            transfer_risk_usd=expected_loss,
            recommendations=recs,
            bridge_verdict=verdict,
        )

    def analyze_batch(self, profiles: List[BridgeProfile]) -> List[BridgeRiskReport]:
        """Analyze a list of bridge profiles."""
        return [self.analyze(p) for p in profiles]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_results(self, reports: List[BridgeRiskReport],
                     data_file: Path = DATA_FILE) -> None:
        """Atomically append results to ring-buffer JSON (max MAX_ENTRIES)."""
        data_file = Path(data_file)
        data_file.parent.mkdir(parents=True, exist_ok=True)

        existing: list = []
        if data_file.exists():
            try:
                with open(data_file) as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        new_entries = [
            {
                "ts": timestamp,
                "bridge_id": r.bridge_id,
                "bridge_type": r.bridge_type,
                "architecture_risk": r.architecture_risk,
                "custody_risk": r.custody_risk,
                "smart_contract_risk": r.smart_contract_risk,
                "composite_risk": r.composite_risk,
                "risk_level": r.risk_level,
                "transfer_risk_usd": r.transfer_risk_usd,
                "recommendations": r.recommendations,
                "bridge_verdict": r.bridge_verdict,
            }
            for r in reports
        ]

        combined = existing + new_entries
        combined = combined[-MAX_ENTRIES:]

        tmp = str(data_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(combined, f, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load persisted history; returns [] on missing or corrupt file."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo() -> None:
    analyzer = CrossChainBridgeRiskAnalyzer()

    profiles = [
        BridgeProfile(
            bridge_id="zkbridge-eth-arb",
            bridge_type="ZK_PROOF",
            tvl_usd=200_000_000,
            transfer_amount_usd=50_000,
            audit_count=4,
            has_multisig=True,
            validator_count=21,
            has_bug_bounty=True,
            protocol_age_days=500,
            previously_hacked=False,
            hack_amount_usd=0,
        ),
        BridgeProfile(
            bridge_id="ronin-copycat",
            bridge_type="LOCK_MINT",
            tvl_usd=50_000_000,
            transfer_amount_usd=10_000_000,
            audit_count=0,
            has_multisig=False,
            validator_count=1,
            has_bug_bounty=False,
            protocol_age_days=90,
            previously_hacked=True,
            hack_amount_usd=100_000_000,
        ),
    ]

    reports = analyzer.analyze_batch(profiles)
    for r in reports:
        print(f"\n{'='*60}")
        print(f"Bridge     : {r.bridge_id}")
        print(f"Type       : {r.bridge_type}")
        print(f"Arch risk  : {r.architecture_risk:.3f}")
        print(f"Custody    : {r.custody_risk:.3f}")
        print(f"SC risk    : {r.smart_contract_risk:.3f}")
        print(f"Composite  : {r.composite_risk:.3f}")
        print(f"Level      : {r.risk_level}")
        print(f"Est. loss  : ${r.transfer_risk_usd:,.0f}")
        print(f"Verdict    : {r.bridge_verdict}")
        for rec in r.recommendations:
            print(f"  {rec}")


if __name__ == "__main__":
    _demo()
