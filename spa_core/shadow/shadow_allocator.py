"""
shadow_allocator — MP-106: target weights for each shadow strategy S0–S5.

``compute_shadow_allocation`` is a pure function: adapters in, weights out.
Weights are fractions of the strategy's own virtual equity; the unallocated
remainder (1 − Σw) is held as zero-yield cash. No I/O, no network, stdlib only.

Adapter dicts are accepted in both the MP-106 spec form
(``id`` / ``apy`` / ``tier`` / ``tvl_usd``) and the orchestrator snapshot form
(``protocol`` / ``apy_pct`` / ``tier`` / ``tvl_usd`` / ``status``) — adapters
with a non-usable ``status`` (anything other than ok/partial) are dropped.
"""
from __future__ import annotations

from .shadow_registry import STRATEGIES

# S1 MaxSharpe: until the shadow track accumulates its own return history, the
# Sharpe ratio is proxied as apy / tier-volatility (T1 lending pools are
# materially less volatile than T2). Deterministic by construction.
_TIER_VOL_PROXY = {"T1": 1.0, "T2": 2.0}
_DEFAULT_VOL_PROXY = 3.0  # unknown tier → treated as riskier than T2

# S4 Conservative: fixed 40/40/20; the protocol legs are matched by substring
# so both registry keys ("aave_v3", "compound_v3") and feed ids match.
_S4_LEGS = (("aave", 0.40), ("compound", 0.40))


def _as_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def _normalize_adapters(adapters) -> list[dict]:
    """Coerce heterogeneous adapter dicts to ``{id, apy, tier, tvl_usd}``."""
    out: list[dict] = []
    for a in adapters or []:
        if not isinstance(a, dict):
            continue
        status = a.get("status")
        if status is not None and status not in ("ok", "partial"):
            continue
        pid = a.get("id") or a.get("protocol")
        apy = _as_float(a.get("apy", a.get("apy_pct")))
        if not pid or apy is None:
            continue
        out.append(
            {
                "id": str(pid),
                "apy": apy,
                "tier": str(a.get("tier") or "T2").upper(),
                "tvl_usd": _as_float(a.get("tvl_usd")) or 0.0,
            }
        )
    # Deterministic order regardless of feed ordering.
    out.sort(key=lambda d: d["id"])
    return out


def _equal_weights(pool_ids: list[str]) -> dict[str, float]:
    if not pool_ids:
        return {}
    w = 1.0 / len(pool_ids)
    return {p: w for p in pool_ids}


def compute_shadow_allocation(
    strategy_id: str,
    adapters: list[dict],
    current_spa_allocation: dict[str, float] | None = None,
    *,
    real_equity: float | None = None,
) -> dict[str, float]:
    """Target weights (fractions of equity, Σ ≤ 1.0) for one shadow strategy.

    Parameters
    ----------
    strategy_id : "S0".."S5" (see ``shadow_registry.STRATEGIES``).
    adapters    : live adapter snapshot (spec or orchestrator key form).
    current_spa_allocation : real allocator output, pool → USD (used by S5).
    real_equity : real-track total equity in USD — the S5 weight denominator,
                  so the mirror keeps the real strategy's structural cash.
                  Default: Σ of the allocation itself (fully-deployed mirror).
    """
    if strategy_id not in STRATEGIES:
        raise KeyError(f"unknown shadow strategy: {strategy_id!r}")

    pools = _normalize_adapters(adapters)

    if strategy_id == "S0":  # MaxYield — winner takes all
        if not pools:
            return {}
        best = max(pools, key=lambda p: (p["apy"], p["id"]))
        return {best["id"]: 1.0}

    if strategy_id == "S1":  # MaxSharpe — weights ∝ apy / tier-vol proxy
        scores = {
            p["id"]: p["apy"] / _TIER_VOL_PROXY.get(p["tier"], _DEFAULT_VOL_PROXY)
            for p in pools
            if p["apy"] > 0
        }
        total = sum(scores.values())
        if total <= 0:
            return {}
        return {p: s / total for p, s in scores.items()}

    if strategy_id == "S2":  # EqualWeight — all active adapters
        return _equal_weights([p["id"] for p in pools])

    if strategy_id == "S3":  # T1Only — equal weights across T1
        return _equal_weights([p["id"] for p in pools if p["tier"] == "T1"])

    if strategy_id == "S4":  # Conservative — 40% Aave + 40% Compound + 20% cash
        ids = [p["id"] for p in pools]
        weights: dict[str, float] = {}
        for needle, w in _S4_LEGS:
            match = next((i for i in ids if needle in i.lower()), None)
            if match:
                # A missing leg stays in cash — never reallocated elsewhere.
                weights[match] = weights.get(match, 0.0) + w
        return weights

    # S5 CurrentSPA — mirror of the real allocator (the baseline).
    alloc = {
        str(p): float(v)
        for p, v in (current_spa_allocation or {}).items()
        if _as_float(v) is not None and float(v) > 0
    }
    if not alloc:
        return {}
    denom = real_equity if real_equity and real_equity > 0 else sum(alloc.values())
    weights = {p: v / denom for p, v in alloc.items()}
    total = sum(weights.values())
    if total > 1.0:  # floating-point / stale-equity guard: never exceed 100%
        weights = {p: w / total for p, w in weights.items()}
    return weights
