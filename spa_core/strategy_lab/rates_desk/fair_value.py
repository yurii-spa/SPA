"""
spa_core/strategy_lab/rates_desk/fair_value.py — risk-adjusted fair implied yield + CARRY/REFUSE.

RESEARCH module (Rates-Desk de-risk). Pure stdlib, deterministic, LLM-forbidden, fail-CLOSED.

The core of the thesis: separate "real excess spread" (CARRY — harvest it) from "tail
compensation you'll pay back" (REFUSE it).

    fair_implied_yield = baseline_yield(underlying) - tail_risk_haircut
    tail_risk_haircut  = MAX_TAIL_HAIRCUT_APY * tail_score          (linear in 0..1 score)

A market is:
  CARRY   when  quoted_implied - fair_implied > COST_BUFFER   AND   tail_score < refuse_threshold
          i.e. there is genuine spread above fair value AND it is NOT explained by tail risk.
  REFUSE  otherwise — specifically:
            - tail_score >= refuse_threshold  → the high yield IS tail-comp (refuse on risk), OR
            - spread <= COST_BUFFER           → no harvestable edge after cost.

`baseline_yield` is the protocol's own honest yield (e.g. the PT's underlyingApy, or a token's
restaking/staking APY) — the yield you'd fairly expect absent mispricing. `quoted_implied` is
what the market is actually offering (the PT implied APY). The GAP between them, net of the tail
haircut and cost, is the edge — but ONLY when the tail score says the gap isn't risk premium.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass

from spa_core.strategy_lab.rates_desk import config as C


@dataclass
class FairValueVerdict:
    underlying: str
    date: str
    quoted_implied: float       # market-offered implied APY (decimal)
    baseline_yield: float       # honest expected yield absent mispricing (decimal)
    tail_score: float           # 0..1
    tail_haircut: float         # APY subtracted for tail risk (decimal)
    fair_implied: float         # baseline - haircut (decimal)
    spread_vs_fair: float       # quoted - fair (decimal); the raw edge before the tail gate
    classification: str         # "CARRY" | "REFUSE"
    refuse_reason: str = ""     # why REFUSE ("tail" | "no_spread" | "")


def fair_value(
    underlying: str,
    date: str,
    quoted_implied: float,
    baseline_yield: float,
    tail_score: float,
    cfg=C,
) -> FairValueVerdict:
    """Deterministic CARRY/REFUSE verdict for one market on one date.

    FAIL-CLOSED: a tail_score outside [0,1] is clamped to 1.0 (treat malformed risk as MAX risk);
    a non-finite quoted/baseline yields a REFUSE."""
    # fail-closed on malformed inputs
    if not (isinstance(quoted_implied, (int, float)) and isinstance(baseline_yield, (int, float))):
        return FairValueVerdict(underlying, date, 0.0, 0.0, 1.0, cfg.MAX_TAIL_HAIRCUT_APY,
                                0.0, 0.0, "REFUSE", "bad_data")
    ts = tail_score
    if not (0.0 <= ts <= 1.0):
        ts = 1.0  # malformed risk score → treat as maximum risk (fail-closed)

    haircut = cfg.MAX_TAIL_HAIRCUT_APY * ts
    fair = baseline_yield - haircut
    spread = quoted_implied - fair

    if ts >= cfg.TAIL_REFUSE_THRESHOLD:
        cls, reason = "REFUSE", "tail"
    elif spread <= cfg.COST_BUFFER_APY:
        cls, reason = "REFUSE", "no_spread"
    else:
        cls, reason = "CARRY", ""

    return FairValueVerdict(
        underlying=underlying, date=date,
        quoted_implied=round(float(quoted_implied), 6),
        baseline_yield=round(float(baseline_yield), 6),
        tail_score=round(ts, 6),
        tail_haircut=round(haircut, 6),
        fair_implied=round(fair, 6),
        spread_vs_fair=round(spread, 6),
        classification=cls, refuse_reason=reason,
    )
