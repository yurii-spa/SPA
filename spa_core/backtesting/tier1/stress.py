"""
spa_core/backtesting/tier1/stress.py — deterministic stress scenarios (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. A risk-tier package must be
judged on its WORST case, not its average yield. This applies fixed, transparent crisis
scenarios to a strategy's allocation and reports the 1-year P&L under each, plus the worst.

Scenarios (deterministic, version-pinned — change → new ADR):
  • rate_collapse — DeFi yields halve for the year (APY × 0.5).
  • stable_depeg   — a 2% principal loss on stablecoin exposure (held stables wobble).
  • t2_exploit     — a held T2/T3 protocol suffers a 50% principal loss on its sleeve.

Reuses the tail-risk tier map for protocol classification. Reports per-strategy and
per-package worst-case so the packages page can show honest downside, not just APY.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict

from spa_core.backtesting.tier1.tail_risk import PROTOCOL_TIER

STRESS_VERSION = "v1.0"
RATE_COLLAPSE_FACTOR = 0.5     # yields halve
DEPEG_LOSS_PCT = 2.0           # 2% principal loss on stable exposure
EXPLOIT_LOSS_PCT = 50.0        # 50% loss on the worst single T2/T3 sleeve


def _nonzero(allocation: Dict[str, float]) -> Dict[str, float]:
    return {k: float(v) for k, v in (allocation or {}).items() if k != "cash" and v}


def stress_strategy(net_apy_pct: float, allocation: Dict[str, float]) -> dict:
    """1-year P&L (%) under each scenario + the worst case."""
    weights = _nonzero(allocation)
    deployed = sum(weights.values()) or 1.0

    # rate_collapse: keep half the net yield
    rate_collapse = net_apy_pct * RATE_COLLAPSE_FACTOR

    # stable_depeg: full net yield minus a 2% loss on deployed stable exposure
    depeg = net_apy_pct - DEPEG_LOSS_PCT * deployed

    # t2_exploit: lose 50% of the single largest T2/T3 sleeve (worst-case concentration)
    t2t3 = {p: w for p, w in weights.items() if PROTOCOL_TIER.get(p, "T2") in ("T2", "T3")}
    worst_sleeve = max(t2t3.values()) if t2t3 else 0.0
    exploit = net_apy_pct - EXPLOIT_LOSS_PCT * worst_sleeve

    scenarios = {
        "rate_collapse_pct": round(rate_collapse, 3),
        "stable_depeg_pct": round(depeg, 3),
        "t2_exploit_pct": round(exploit, 3),
    }
    worst_name = min(scenarios, key=scenarios.get)
    return {
        "version": STRESS_VERSION,
        "base_net_apy_pct": round(net_apy_pct, 3),
        "scenarios": scenarios,
        "worst_case_pct": scenarios[worst_name],
        "worst_scenario": worst_name.replace("_pct", ""),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(stress_strategy(4.5, {"aave_v3": 0.5, "maple": 0.3, "cash": 0.2}), indent=2))
