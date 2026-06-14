"""Exit-latency liquidity policy (SPA-V412) — strictly read-only / advisory.

Each adapter declares an ``EXIT_LATENCY_HOURS`` profile (surfaced on
:class:`~spa_core.adapters.base_adapter.YieldInfo.exit_latency_hours`): the
typical wall-clock time to fully withdraw a USDC position back to liquid cash.
``0.0`` means instant (blue-chip lending pools); a large value means a
withdrawal queue (e.g. Maple's epoch-based redemption).

This module provides two pure, side-effect-free helpers over a portfolio's
weighted positions:

* :func:`check_exit_latency_policy` — verifies the *liquidity policy*: the
  combined weight of positions whose exit takes longer than
  :data:`ILLIQUID_THRESHOLD_HOURS` must not exceed :data:`MAX_ILLIQUID_SHARE`.
* :func:`kill_switch_exit_order` — returns the order in which positions should
  be unwound *if* a kill-switch fires: most-liquid first, so the portfolio
  reaches safety as fast as possible.

IMPORTANT — read-only boundary (SPA-BL-011 / LLM_FORBIDDEN_AGENTS):
this module is **advisory metadata only**. It never moves capital, never calls
``execution/``, ``risk/`` or ``feed_health/``, and ``kill_switch_exit_order``
merely *computes an ordering* — it does not trigger or execute any exit. The
deterministic risk/execution agents remain the sole authority on actually
unwinding positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

# A position is identified by a protocol name and carries a portfolio weight
# (fraction of capital in [0, 1]) and a declared exit latency in hours.
PositionsInput = Union[
    Mapping[str, Mapping[str, Optional[float]]],
    Sequence[Tuple[str, float, Optional[float]]],
]

# Policy thresholds (mirror the SPA-V412 / MP-113 specification).
ILLIQUID_THRESHOLD_HOURS: float = 72.0
MAX_ILLIQUID_SHARE: float = 0.25


@dataclass(frozen=True)
class _Position:
    protocol: str
    weight: float
    exit_latency_hours: Optional[float]


def classify_exit_latency(
    exit_latency_hours: Optional[float],
    threshold_hours: float = ILLIQUID_THRESHOLD_HOURS,
) -> str:
    """Bucket an exit-latency value.

    Returns ``"instant"`` (0h), ``"liquid"`` (>0 and <= ``threshold_hours``),
    ``"illiquid"`` (> ``threshold_hours``), or ``"unknown"`` (``None`` —
    adapter did not declare a profile; treated as illiquid by the policy check
    so an undeclared position can never silently pass).
    """
    if exit_latency_hours is None:
        return "unknown"
    if exit_latency_hours <= 0.0:
        return "instant"
    if exit_latency_hours <= threshold_hours:
        return "liquid"
    return "illiquid"


def _normalize(positions: PositionsInput) -> List[_Position]:
    """Coerce the supported input shapes into a list of ``_Position``."""
    out: List[_Position] = []
    if isinstance(positions, Mapping):
        for protocol, info in positions.items():
            if not isinstance(info, Mapping):
                raise TypeError(
                    f"position {protocol!r} must map to a dict with 'weight' "
                    f"and 'exit_latency_hours', got {type(info).__name__}"
                )
            weight = info.get("weight")
            latency = info.get("exit_latency_hours")
            out.append(_Position(str(protocol), float(weight or 0.0), _opt_float(latency)))
    else:
        for row in positions:
            protocol, weight, latency = row
            out.append(_Position(str(protocol), float(weight or 0.0), _opt_float(latency)))
    return out


def _opt_float(v: Optional[float]) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def check_exit_latency_policy(
    positions: PositionsInput,
    threshold_hours: float = ILLIQUID_THRESHOLD_HOURS,
    max_illiquid_share: float = MAX_ILLIQUID_SHARE,
) -> Dict[str, object]:
    """Check the illiquid-share liquidity policy. Pure / read-only.

    A position counts as *illiquid* when its declared exit latency exceeds
    ``threshold_hours`` (or is undeclared / ``None`` — see
    :func:`classify_exit_latency`). The combined weight of illiquid positions
    must not exceed ``max_illiquid_share``.

    Returns a report dict::

        {
            "ok": bool,                  # True iff illiquid_share <= max
            "illiquid_share": float,     # sum of illiquid position weights
            "liquid_share": float,       # sum of instant/liquid weights
            "threshold_hours": float,
            "max_illiquid_share": float,
            "illiquid_positions": [protocol, ...],   # offenders / unknowns
            "breakdown": {protocol: {"weight", "exit_latency_hours", "bucket"}},
        }

    The function does not mutate inputs and performs no I/O.
    """
    parsed = _normalize(positions)

    illiquid_share = 0.0
    liquid_share = 0.0
    illiquid_positions: List[str] = []
    breakdown: Dict[str, Dict[str, object]] = {}

    for p in parsed:
        bucket = classify_exit_latency(p.exit_latency_hours, threshold_hours)
        breakdown[p.protocol] = {
            "weight": p.weight,
            "exit_latency_hours": p.exit_latency_hours,
            "bucket": bucket,
        }
        if bucket in ("illiquid", "unknown"):
            illiquid_share += p.weight
            illiquid_positions.append(p.protocol)
        else:
            liquid_share += p.weight

    # Guard against float dust so an exact-cap portfolio (e.g. 0.25) passes.
    ok = illiquid_share <= max_illiquid_share + 1e-9

    return {
        "ok": ok,
        "illiquid_share": illiquid_share,
        "liquid_share": liquid_share,
        "threshold_hours": threshold_hours,
        "max_illiquid_share": max_illiquid_share,
        "illiquid_positions": illiquid_positions,
        "breakdown": breakdown,
    }


def kill_switch_exit_order(positions: PositionsInput) -> List[str]:
    """Return protocols ordered most-liquid-first for a kill-switch unwind.

    Advisory ordering ONLY — this computes the sequence in which positions
    *should* be exited (lowest exit latency first) so the portfolio reaches
    safety fastest. It does not execute, schedule, or trigger any exit. An
    undeclared latency (``None``) sorts last (treated as the slowest to exit).

    Ties are broken by descending weight (drain the biggest liquid bucket
    first), then alphabetically by protocol for determinism.
    """
    parsed = _normalize(positions)

    def sort_key(p: _Position) -> Tuple[float, float, str]:
        latency = float("inf") if p.exit_latency_hours is None else p.exit_latency_hours
        return (latency, -p.weight, p.protocol)

    return [p.protocol for p in sorted(parsed, key=sort_key)]
