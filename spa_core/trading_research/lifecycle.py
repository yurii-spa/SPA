"""Promotion lifecycle. Stages advance ONLY through the transitions below; everything else refuses.

    DISCOVERED → BACKTESTING → BACKTEST_QUALIFIED → FORWARD_PAPER → ROBUST      (automatic, GREEN:
                            ↘ REJECTED  (with the failed criteria as the reason)   research only)
    ROBUST → CHAMPION_CANDIDATE → SHADOW                                        (YELLOW: needs a recorded
                                                                                 owner decision)
    SHADOW → LIMITED_LIVE → PRODUCTION                                          (RED: refused in code —
                                                                                 real capital; a later
                                                                                 dedicated risk review)
"""
from __future__ import annotations

STAGES = ("DISCOVERED", "BACKTESTING", "BACKTEST_QUALIFIED", "REJECTED", "FORWARD_PAPER", "ROBUST",
          "CHAMPION_CANDIDATE", "SHADOW", "LIMITED_LIVE", "PRODUCTION")
AUTO = {
    (None, "DISCOVERED"), ("DISCOVERED", "BACKTESTING"),
    ("BACKTESTING", "BACKTEST_QUALIFIED"), ("BACKTESTING", "REJECTED"),
    ("BACKTEST_QUALIFIED", "FORWARD_PAPER"), ("FORWARD_PAPER", "ROBUST"),
    # re-evaluation on a newer backtest: a qualified candidate may lose it, a rejected one may earn it
    ("BACKTEST_QUALIFIED", "REJECTED"), ("FORWARD_PAPER", "REJECTED"), ("ROBUST", "REJECTED"),
    ("REJECTED", "BACKTEST_QUALIFIED"),
}
OWNER_REVIEW = {("ROBUST", "CHAMPION_CANDIDATE"), ("CHAMPION_CANDIDATE", "SHADOW")}
FORBIDDEN_TARGETS = {"LIMITED_LIVE", "PRODUCTION"}

#: Forward evidence needed before ROBUST (GREEN, still paper): time, trades, and consistency with OOS.
ROBUST_RULES = {"min_days": 30, "min_trades": 5, "min_sharpe": 0.5, "max_degradation": 0.5}


class TransitionRefused(Exception):
    pass


def check(from_stage, to_stage, *, owner_decision_ref: str | None = None) -> str:
    """Return the actor class for an allowed transition, else raise TransitionRefused."""
    if to_stage in FORBIDDEN_TARGETS:
        raise TransitionRefused(f"{to_stage} involves real capital — RED, owner-gated outside this engine")
    if (from_stage, to_stage) in AUTO:
        return "auto"
    if (from_stage, to_stage) in OWNER_REVIEW:
        if not owner_decision_ref:
            raise TransitionRefused(f"{from_stage}→{to_stage} needs a recorded owner decision (YELLOW)")
        return "owner"
    raise TransitionRefused(f"{from_stage}→{to_stage} is not a lifecycle transition")
