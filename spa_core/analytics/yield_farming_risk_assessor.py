"""
MP-670: YieldFarmingRiskAssessor
Assess risks specific to yield farming: impermanent loss exposure,
smart contract risk, reward token inflation, and protocol emissions sustainability.

Advisory / read-only. Pure stdlib. Atomic writes (os.replace).
"""

from dataclasses import dataclass, field
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_farming_risk_log.json")
MAX_ENTRIES = 100


@dataclass
class YieldFarmProfile:
    farm_id: str
    protocol: str
    pool_type: str          # "STABLE_STABLE", "STABLE_VOLATILE", "VOLATILE_VOLATILE"
    tvl_usd: float
    apy_base_pct: float     # base trading fee APY (sustainable)
    apy_reward_pct: float   # reward token APY (inflationary)
    reward_token_inflation_pct: float  # annual emission inflation rate (e.g. 50.0 = 50%)
    audit_count: int        # number of independent audits
    protocol_age_days: int  # how long the protocol has been live
    has_time_lock: bool     # contract changes have a time lock
    rug_pull_risk_score: float  # 0.0–1.0, set externally (0=safe, 1=rug)


@dataclass
class YieldFarmRiskReport:
    farm_id: str
    pool_type: str
    il_risk: float              # 0.0–1.0 impermanent loss risk
    smart_contract_risk: float  # 0.0–1.0
    inflation_risk: float       # reward sustainability risk 0.0–1.0
    rug_risk: float             # 0.0–1.0 (from input)
    composite_risk: float       # weighted
    risk_grade: str             # A / B / C / D / F
    real_apy_estimate_pct: float  # base_apy adjusted for IL + inflation decay
    recommendation: str         # FARM / MONITOR / REDUCE / EXIT
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IL_BASELINES = {
    "STABLE_STABLE": 0.02,
    "STABLE_VOLATILE": 0.30,
    "VOLATILE_VOLATILE": 0.65,
}


def _il_risk(pool_type: str) -> float:
    """Return IL risk baseline for the pool type."""
    return _IL_BASELINES.get(pool_type, 0.65)


def _sc_risk(audit_count: int, has_time_lock: bool, protocol_age_days: int) -> float:
    """Smart-contract risk: 0.5 base, reduced by audits / timelock / age."""
    base = 0.5
    audit_reduction = min(0.3, 0.1 * audit_count)
    base -= audit_reduction
    if has_time_lock:
        base -= 0.1
    if protocol_age_days > 365:
        base -= 0.1
    return max(0.05, min(0.90, base))


def _inflation_risk(apy_reward_pct: float, apy_base_pct: float,
                    reward_token_inflation_pct: float) -> float:
    """Reward-token inflation / emission sustainability risk."""
    if apy_reward_pct == 0.0:
        return 0.0
    ratio = reward_token_inflation_pct / 100.0
    reward_share = apy_reward_pct / (apy_base_pct + apy_reward_pct + 0.001)
    risk = ratio * 0.8 + reward_share * 0.4
    return min(1.0, risk)


def _composite_risk(il: float, sc: float, inflation: float, rug: float) -> float:
    """Weighted composite: IL*0.30 + SC*0.30 + inflation*0.25 + rug*0.15."""
    return il * 0.30 + sc * 0.30 + inflation * 0.25 + rug * 0.15


def _risk_grade(composite: float) -> str:
    if composite < 0.20:
        return "A"
    if composite < 0.35:
        return "B"
    if composite < 0.50:
        return "C"
    if composite < 0.65:
        return "D"
    return "F"


def _real_apy_estimate(apy_base_pct: float, apy_reward_pct: float,
                       il_risk: float, inflation_risk: float) -> float:
    """Base APY adjusted for IL haircut + inflation decay on reward APY."""
    return apy_base_pct * (1.0 - il_risk * 0.5) + apy_reward_pct * (1.0 - inflation_risk * 0.6)


def _recommendation(risk_grade: str) -> str:
    if risk_grade in ("A", "B"):
        return "FARM"
    if risk_grade == "C":
        return "MONITOR"
    if risk_grade == "D":
        return "REDUCE"
    return "EXIT"


def _build_warnings(inflation_risk: float, il_risk: float,
                    rug_risk: float, sc_risk: float) -> List[str]:
    warnings: List[str] = []
    if inflation_risk > 0.5:
        warnings.append("⚠️ High reward inflation — APY may collapse")
    if il_risk > 0.5:
        warnings.append("⚠️ High IL exposure — consider stable pairs")
    if rug_risk > 0.3:
        warnings.append("🚨 Rug risk flagged")
    if sc_risk > 0.6:
        warnings.append("⚠️ Low audit coverage")
    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class YieldFarmingRiskAssessor:
    """Advisory yield farming risk assessor. Read-only analytics, stdlib only."""

    def assess(self, profile: YieldFarmProfile) -> YieldFarmRiskReport:
        """Assess risk for a single farm profile and return a risk report."""
        il = _il_risk(profile.pool_type)
        sc = _sc_risk(profile.audit_count, profile.has_time_lock,
                      profile.protocol_age_days)
        inf = _inflation_risk(profile.apy_reward_pct, profile.apy_base_pct,
                              profile.reward_token_inflation_pct)
        rug = max(0.0, min(1.0, profile.rug_pull_risk_score))

        composite = _composite_risk(il, sc, inf, rug)
        grade = _risk_grade(composite)
        real_apy = _real_apy_estimate(profile.apy_base_pct, profile.apy_reward_pct,
                                      il, inf)
        rec = _recommendation(grade)
        warns = _build_warnings(inf, il, rug, sc)

        return YieldFarmRiskReport(
            farm_id=profile.farm_id,
            pool_type=profile.pool_type,
            il_risk=il,
            smart_contract_risk=sc,
            inflation_risk=inf,
            rug_risk=rug,
            composite_risk=composite,
            risk_grade=grade,
            real_apy_estimate_pct=real_apy,
            recommendation=rec,
            warnings=warns,
        )

    def assess_batch(self, profiles: List[YieldFarmProfile]) -> List[YieldFarmRiskReport]:
        """Assess a list of farm profiles."""
        return [self.assess(p) for p in profiles]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_results(self, reports: List[YieldFarmRiskReport],
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
                "farm_id": r.farm_id,
                "pool_type": r.pool_type,
                "il_risk": r.il_risk,
                "smart_contract_risk": r.smart_contract_risk,
                "inflation_risk": r.inflation_risk,
                "rug_risk": r.rug_risk,
                "composite_risk": r.composite_risk,
                "risk_grade": r.risk_grade,
                "real_apy_estimate_pct": r.real_apy_estimate_pct,
                "recommendation": r.recommendation,
                "warnings": r.warnings,
            }
            for r in reports
        ]

        combined = existing + new_entries
        # Ring-buffer: keep last MAX_ENTRIES
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
    assessor = YieldFarmingRiskAssessor()

    profiles = [
        YieldFarmProfile(
            farm_id="aave-usdc-usdt",
            protocol="Aave V3",
            pool_type="STABLE_STABLE",
            tvl_usd=500_000_000,
            apy_base_pct=4.0,
            apy_reward_pct=1.0,
            reward_token_inflation_pct=15.0,
            audit_count=5,
            protocol_age_days=900,
            has_time_lock=True,
            rug_pull_risk_score=0.02,
        ),
        YieldFarmProfile(
            farm_id="new-degen-eth-shib",
            protocol="DegernFi",
            pool_type="VOLATILE_VOLATILE",
            tvl_usd=2_000_000,
            apy_base_pct=0.5,
            apy_reward_pct=250.0,
            reward_token_inflation_pct=200.0,
            audit_count=0,
            protocol_age_days=30,
            has_time_lock=False,
            rug_pull_risk_score=0.8,
        ),
    ]

    reports = assessor.assess_batch(profiles)
    for r in reports:
        print(f"\n{'='*60}")
        print(f"Farm       : {r.farm_id}")
        print(f"Pool type  : {r.pool_type}")
        print(f"IL risk    : {r.il_risk:.3f}")
        print(f"SC risk    : {r.smart_contract_risk:.3f}")
        print(f"Inflation  : {r.inflation_risk:.3f}")
        print(f"Rug risk   : {r.rug_risk:.3f}")
        print(f"Composite  : {r.composite_risk:.3f}")
        print(f"Grade      : {r.risk_grade}")
        print(f"Real APY   : {r.real_apy_estimate_pct:.2f}%")
        print(f"Action     : {r.recommendation}")
        for w in r.warnings:
            print(f"  {w}")


if __name__ == "__main__":
    _demo()
