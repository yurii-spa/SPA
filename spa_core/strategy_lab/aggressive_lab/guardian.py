"""Dynamic Leverage Guardian — a deterministic, real-time de-risk overlay for aggressive strategies.

Research (docs/DYNAMIC_LEVERAGE_GUARDIAN.md) proved, OUT-OF-SAMPLE, that a de-risk overlay reduces a
strategy's realized max-drawdown on historical crises. This module is the production-grade, reusable
implementation so the same overlay can run in BOTH the backtest scorecard and the forward paper harness
(never in the live conservative track — this is the aggressive/advisory book only).

TWO overlays (both take a daily equity series, return a guarded equity series):
  • `apply_guardian_drawdown` — REACTIVE: cut exposure once drawdown from the running peak breaches a
    threshold; re-enter after recovery. Simple, robust; the first `derisk_dd` of any move is unavoidable.
  • `apply_guardian_vol`      — PRE-EMPTIVE: cut exposure when the strategy's own rolling realized vol
    spikes above its trailing baseline (a regime signal that often LEADS the loss); re-enter when vol calms.

HONEST LIMITS (do not oversell — see the doc): a guardian cannot outrun a GAP (instant exploit / depeg /
drained exit liquidity); it reduces the COMPOUNDING of SLOW drawdowns, not the first jump. "Safe leverage"
can NEVER be proven forward — only stress-tested against past crises. Optional `roundtrip_cost` charges the
churn honestly. Deterministic, stdlib-only, LLM-forbidden.
"""
from __future__ import annotations

from typing import List, Sequence

__all__ = ["apply_guardian_drawdown", "apply_guardian_vol", "stdev"]


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation (0.0 for < 2 points)."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def _daily_returns(equity: Sequence[float]) -> List[float]:
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]


def apply_guardian_drawdown(
    equity: Sequence[float],
    *,
    derisk_dd: float = 0.04,
    derisk_frac: float = 0.25,
    reenter_frac: float = 0.5,
) -> List[float]:
    """REACTIVE overlay. Exposure cuts to `derisk_frac` once drawdown from the guarded running peak
    breaches `derisk_dd`, restores to 1.0 after recovering `reenter_frac` of the way back to the peak.
    Reacts to OBSERVED drawdown (honest: the first `derisk_dd` is unavoidable)."""
    equity = list(equity)
    if len(equity) < 2:
        return equity
    guarded = [equity[0]]
    peak = equity[0]
    exposure = 1.0
    for i in range(1, len(equity)):
        raw = equity[i] / equity[i - 1] - 1.0 if equity[i - 1] else 0.0
        new_eq = guarded[-1] * (1.0 + raw * exposure)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = new_eq / peak - 1.0
        if exposure >= 1.0 and dd <= -derisk_dd:
            exposure = derisk_frac
        elif exposure < 1.0 and new_eq >= peak * (1.0 - derisk_dd * (1.0 - reenter_frac)):
            exposure = 1.0
    return guarded


def apply_guardian_vol(
    equity: Sequence[float],
    *,
    lookback: int = 10,
    vol_mult: float = 2.0,
    derisk_frac: float = 0.0,
    calm_mult: float = 1.2,
    roundtrip_cost: float = 0.0,
) -> List[float]:
    """PRE-EMPTIVE overlay. De-risk when the strategy's own rolling realized vol spikes above
    `vol_mult` × its trailing baseline (a regime signal that often LEADS the drawdown); re-enter when
    vol calms below `calm_mult` × baseline. `roundtrip_cost` (fraction) is charged each time exposure
    changes — the honest churn drag. Uses only the strategy's own returns (self-contained)."""
    equity = list(equity)
    if len(equity) < lookback + 2:
        return equity
    rets = _daily_returns(equity)
    guarded = [equity[0]]
    exposure = 1.0
    for i in range(len(rets)):
        if i >= lookback:
            recent = stdev(rets[i - lookback + 1: i + 1])
            base = stdev(rets[max(0, i - 4 * lookback): i - lookback + 1]) or 1e-9
            prev = exposure
            if exposure >= 1.0 and recent > vol_mult * base:
                exposure = derisk_frac
            elif exposure < 1.0 and recent < calm_mult * base:
                exposure = 1.0
            if exposure != prev and roundtrip_cost:
                guarded[-1] *= (1.0 - roundtrip_cost * abs(prev - exposure))
        guarded.append(guarded[-1] * (1.0 + rets[i] * exposure))
    return guarded
