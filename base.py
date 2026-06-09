"""
spa_core.strategies.base — shared primitives for the shadow-strategy framework.

Defines the ``Strategy`` Protocol every shadow strategy implements, helpers for
reading the adapter-orchestrator snapshot, and ``apply_risk_policy`` — the single
external risk guard applied uniformly to the output of *any* strategy.

Stdlib only. Advisory/read-only: nothing here imports execution, feed_health or
the deterministic risk agents.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# Concentration caps mirror the deterministic RiskConfig v1.0 (CLAUDE.md):
#   Tier 1 protocols  -> max 40% of portfolio each
#   Tier 2 protocols  -> max 20% of portfolio each
# These are *copied constants*, not an import of the risk agent — the shadow
# framework must never reach into capital-touching risk code.
MAX_CONCENTRATION_T1 = 0.40
MAX_CONCENTRATION_T2 = 0.20


@runtime_checkable
class Strategy(Protocol):
    """A candidate allocation policy evaluated in shadow mode.

    Implementations return *raw* target weights; the framework applies
    ``apply_risk_policy`` as a uniform external guard afterwards.
    """

    name: str            # unique id, snake_case (e.g. "s3_risk_parity")
    label: str           # human-readable label
    risk_level: str      # "low" | "medium" | "high"

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        """Return ``{pool_id: weight}`` with ``sum(weights) <= 1.0``.

        The unallocated remainder is held as cash. ``snapshot`` is the
        adapter-orchestrator status dict; ``state`` carries optional context
        (e.g. APY ``history``) supplied by the runner.
        """
        ...


def active_pools(snapshot: dict) -> list[dict]:
    """Return the list of tradeable pools from an orchestrator snapshot.

    A pool is active when its adapter reported ``status == "ok"`` and a usable,
    strictly-positive ``apy_pct``. Each returned dict is normalised to::

        {"pool_id": str, "apy_pct": float, "tier": str, "health_score": float}
    """
    pools: list[dict] = []
    for ad in (snapshot or {}).get("adapters", []) or []:
        if not isinstance(ad, dict):
            continue
        if ad.get("status") != "ok":
            continue
        apy = _as_float(ad.get("apy_pct"))
        if apy is None or apy <= 0:
            continue
        pool_id = ad.get("protocol")
        if not pool_id:
            continue
        pools.append(
            {
                "pool_id": str(pool_id),
                "apy_pct": apy,
                "tier": str(ad.get("tier") or "T2").upper(),
                "health_score": _as_float(ad.get("health_score")) or 0.0,
            }
        )
    return pools


def tier_map(snapshot: dict) -> dict[str, str]:
    """Map ``pool_id -> tier`` (``"T1"`` / ``"T2"``) from a snapshot.

    Pools with an unknown/missing tier are treated as ``"T2"`` (the stricter
    cap), so the guard never under-protects.
    """
    out: dict[str, str] = {}
    for ad in (snapshot or {}).get("adapters", []) or []:
        if isinstance(ad, dict) and ad.get("protocol"):
            out[str(ad["protocol"])] = str(ad.get("tier") or "T2").upper()
    return out


def apply_risk_policy(weights: dict[str, float], caps: dict[str, str]) -> dict[str, float]:
    """Clip per-pool weights to the tier concentration caps.

    ``caps`` maps ``pool_id -> tier``. T1 pools are capped at
    :data:`MAX_CONCENTRATION_T1`, everything else at
    :data:`MAX_CONCENTRATION_T2`. This is a pure *guard*: it only ever reduces a
    weight (the freed capital becomes cash), so it is idempotent and safe to
    apply to the output of any strategy. Negative or non-finite weights are
    floored to 0.
    """
    out: dict[str, float] = {}
    for pool_id, w in (weights or {}).items():
        wf = _as_float(w)
        if wf is None or wf <= 0:
            continue
        tier = str((caps or {}).get(pool_id, "T2")).upper()
        cap = MAX_CONCENTRATION_T1 if tier == "T1" else MAX_CONCENTRATION_T2
        out[pool_id] = min(wf, cap)
    return out


def normalize(weights: dict[str, float]) -> dict[str, float]:
    """Scale strictly-positive weights so they sum to 1.0.

    Returns ``{}`` when the input has no positive mass (caller decides cash).
    """
    total = sum(w for w in weights.values() if _as_float(w) and w > 0)
    if total <= 0:
        return {}
    return {k: v / total for k, v in weights.items() if _as_float(v) and v > 0}


def pool_apy_history(history: list[dict]) -> dict[str, list[float]]:
    """Extract a per-pool chronological APY series from orchestrator runs.

    ``history`` is the ``runs`` list of ``data/orchestrator_runs.json`` (oldest
    first). Only runs that carry a per-adapter ``adapters`` breakdown contribute
    a data point — summary-only runs are skipped. Returns
    ``{pool_id: [apy_oldest, ..., apy_newest]}``.
    """
    series: dict[str, list[float]] = {}
    for run in history or []:
        if not isinstance(run, dict):
            continue
        adapters = run.get("adapters")
        if not isinstance(adapters, list):
            continue
        for ad in adapters:
            if not isinstance(ad, dict) or not ad.get("protocol"):
                continue
            apy = _as_float(ad.get("apy_pct"))
            if apy is None:
                continue
            series.setdefault(str(ad["protocol"]), []).append(apy)
    return series


def _as_float(value) -> float | None:
    """Best-effort float coercion; ``None`` for unparseable / non-finite input."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return f
