"""
spa_core/backtesting/tier1/tail_risk.py — principal/tail-risk model for yield (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. For stablecoin yield the real
risk is NOT return volatility (≈0) — it is PRINCIPAL loss: depeg, bad debt, smart-contract
exploit, oracle failure. Sharpe/vol ignore this entirely. This assigns each protocol a tier
and a conservative annualised expected-loss estimate, and computes a strategy's
allocation-weighted tail-risk + a risk-adjusted net yield (net APY minus tail-risk drag).

Estimates are deterministic, conservative, and version-pinned (change → new ADR). They are
NOT live probabilities — they are a transparent risk overlay so packages reflect principal
risk, complementing the deterministic RiskPolicy (which still governs live exposure).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict

TAIL_RISK_VERSION = "v1.0"

# protocol → tier
PROTOCOL_TIER: Dict[str, str] = {
    "aave_v3": "T1", "compound_v3": "T1", "spark_susds": "T1", "sky_susds": "T1",
    "morpho_steakhouse": "T2", "morpho_blue": "T2", "euler_v2": "T2", "yearn_v3": "T2",
    "fluid": "T2", "maple": "T2", "ethena_susde": "T2", "sdai": "T1", "sfrax": "T2",
    "pendle": "T3", "aerodrome": "T3",
}
# tier → conservative annual expected-loss (percent of principal)
TIER_EXPECTED_LOSS_PCT: Dict[str, float] = {
    "T1": 0.30,   # blue-chip lending: deep, audited, battle-tested
    "T2": 1.50,   # newer/yield-bearing: more contract & peg surface
    "T3": 5.00,   # exotic / leverage / LP: meaningfully higher principal risk
    "cash": 0.0,
    "_default": 2.50,
}


def protocol_tail_risk_pct(protocol: str) -> float:
    if protocol == "cash":
        return 0.0
    tier = PROTOCOL_TIER.get(protocol)
    return TIER_EXPECTED_LOSS_PCT.get(tier, TIER_EXPECTED_LOSS_PCT["_default"])


def strategy_tail_risk(allocation: Dict[str, float]) -> dict:
    """Allocation-weighted annual expected-loss (%) for a strategy."""
    weights = {k: float(v) for k, v in (allocation or {}).items() if v}
    wsum = sum(w for k, w in weights.items())
    if wsum <= 0:
        return {"tail_risk_pct": 0.0, "version": TAIL_RISK_VERSION, "tier_mix": {}}
    risk = 0.0
    tier_mix: Dict[str, float] = {}
    for p, w in weights.items():
        risk += (w / wsum) * protocol_tail_risk_pct(p)
        t = "cash" if p == "cash" else PROTOCOL_TIER.get(p, "T2")
        tier_mix[t] = round(tier_mix.get(t, 0.0) + w / wsum, 4)
    return {"tail_risk_pct": round(risk, 4), "version": TAIL_RISK_VERSION, "tier_mix": tier_mix}


def risk_adjusted_net_apy(net_apy_pct: float, allocation: Dict[str, float]) -> dict:
    """net APY minus tail-risk drag — yield you keep after expected principal loss."""
    tr = strategy_tail_risk(allocation)
    return {
        "net_apy_pct": round(net_apy_pct, 4),
        "tail_risk_pct": tr["tail_risk_pct"],
        "risk_adjusted_apy_pct": round(net_apy_pct - tr["tail_risk_pct"], 4),
        "tier_mix": tr["tier_mix"],
    }


if __name__ == "__main__":
    import json
    demo = {"aave_v3": 0.5, "compound_v3": 0.2, "maple": 0.1, "cash": 0.2}
    print(json.dumps(risk_adjusted_net_apy(4.5, demo), indent=2))
