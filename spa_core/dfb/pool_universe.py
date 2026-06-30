"""
spa_core/dfb/pool_universe.py — WS-1.1: the deterministic DFB pool-universe model.

Enumerates the FOLLOWED pool universe from the data SPA already produces — the read-only
`ADAPTER_REGISTRY` (~35 markets, incl. the Base / multichain-L2 adapters) PLUS the rates-desk
PT markets carried on the cached `RateSurface`. One canonical `Pool` per (protocol, chain, asset),
with a STABLE deterministic `pool_id`. This is the spine every other DFB module reads.

NO judgment here (mirrors rates_desk/feeds.py): no haircuts, no refusal, no A/B/C/D — that all lives
in `risk_overlay.py` (which calls the SPA engine). This module only turns the live registry + surface
into validated identity rows.

CONVENTIONS: stdlib only · deterministic (sorted output; `as_of` = the DATA date, never the wall
clock) · fail-CLOSED (a missing field is `None`, never fabricated / 0-coerced; APY normalized to a
DECIMAL fraction — MEMORY: adapters mix percent vs decimal) · READ-ONLY (never writes; never imports
execution/). Run:
    python3 -m spa_core.dfb.pool_universe
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.dfb import Pool

_ROOT = Path(__file__).resolve().parents[2]
_SURFACE = _ROOT / "data" / "rates_desk" / "rate_surface.json"

# default chain when an adapter does not declare one (the registry's mainnet adapters are Ethereum;
# the L2 adapters carry an explicit chain in their key — handled in _chain_for_key below).
_DEFAULT_CHAIN = "Ethereum"

# explicit chain inference from the registry key suffixes (deterministic, documented).
_CHAIN_BY_KEY_SUFFIX = (
    ("_arbitrum", "Arbitrum"),
    ("arbitrum", "Arbitrum"),
    ("_optimism", "Optimism"),
    ("optimism", "Optimism"),
    ("_polygon", "Polygon"),
    ("polygon", "Polygon"),
    ("_base", "Base"),
    ("base", "Base"),
)


def _slug(s: str) -> str:
    """Lowercase, collapse any non-[a-z0-9] run to a single '-', strip edges. Deterministic + stable."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "na"


def make_pool_id(protocol: str, chain: str, asset: str) -> str:
    """STABLE, DETERMINISTIC pool_id from identity: '<protocol>__<chain>__<asset>' (each slugged).
    Same identity → same id across runs (history files + detail URLs depend on this)."""
    return f"{_slug(protocol)}__{_slug(chain)}__{_slug(asset)}"


def _chain_for_key(key: str) -> str:
    kl = (key or "").lower()
    for suffix, chain in _CHAIN_BY_KEY_SUFFIX:
        if kl.endswith(suffix) or suffix in kl:
            return chain
    return _DEFAULT_CHAIN


def _norm_apy_decimal(raw: Optional[float]) -> Optional[float]:
    """Normalize a possibly-percent/possibly-decimal APY reading to a DECIMAL fraction, fail-CLOSED.

    The canonical adapter accessor `get_yield_info().apy` is ALWAYS a decimal (per base_adapter.py),
    so we trust it as-is — but we still reject non-finite / negative / absurd values (a value > 5.0,
    i.e. 500%, is treated as malformed → None, never coerced). NEVER fabricates."""
    if raw is None:
        return None
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0.0 or f > 5.0:
        return None
    return f


def _pool_from_adapter(key: str, tier: str, adapter_cls) -> Optional[Pool]:
    """One identity row from a registry adapter, fail-CLOSED. Reads the CANONICAL `get_yield_info()`
    (decimal APY) read-only; any adapter error → a row with `None` cells (never dropped silently — the
    pool is still in the universe, just with holes). NEVER fabricates a number."""
    asset = "USDC"
    apy_total: Optional[float] = None
    tvl: Optional[float] = None
    try:
        inst = adapter_cls()
        asset = getattr(inst, "asset", None) or "USDC"
    except Exception:  # noqa: BLE001 — construction failed → identity-only row, fail-CLOSED holes
        inst = None
    if inst is not None:
        try:
            info = inst.get_yield_info()
            apy_total = _norm_apy_decimal(getattr(info, "apy", None))
            t = getattr(info, "tvl_usd", None)
            tvl = float(t) if isinstance(t, (int, float)) and math.isfinite(float(t)) and t >= 0 else None
            asset = getattr(info, "asset", None) or asset
        except Exception:  # noqa: BLE001 — live feed unavailable → None cells (fail-CLOSED)
            pass
    chain = _chain_for_key(key)
    protocol = key
    return Pool(
        pool_id=make_pool_id(protocol, chain, asset),
        protocol=protocol,
        chain=chain,
        asset=asset,
        tier=tier,
        source="adapter_registry",
        apy_total=apy_total,
        apy_base=None,      # the adapter surface does not split base/reward; overlay fills from surface
        apy_reward=None,
        tvl_usd=tvl,
        il_risk=None,
        exposure=None,
        underlying_kind=None,
        market_id=None,
        as_of=None,         # the adapter feed is "latest"; the overlay stamps the surface/data date
    )


def _read_surface() -> Optional[dict]:
    try:
        return json.loads(_SURFACE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _pools_from_surface(surface: Optional[dict]) -> List[Pool]:
    """Rates-desk PT markets from the cached RateSurface (read-only). Each quote → a Pool keyed by
    its underlying + market_id, carrying the UnderlyingKind for the overlay's faithful engine call.
    Deterministic order by market_id. fail-CLOSED on a malformed surface (→ [])."""
    if not isinstance(surface, dict):
        return []
    quotes = surface.get("quotes")
    surface_as_of = surface.get("as_of")
    if not isinstance(quotes, list):
        return []
    out: Dict[str, Pool] = {}
    for q in quotes:
        if not isinstance(q, dict):
            continue
        mid = q.get("market_id")
        underlying = (q.get("underlying") or "").lower()
        if mid is None or not underlying:
            continue
        protocol = (q.get("protocol") or "pendle")
        venue = q.get("venue") or "pendle_pt"
        kind = q.get("kind")  # the UnderlyingKind value if the surface carried it
        # rate (decimal) and tvl from the surface (already Decimal-exact strings)
        def _f(x):
            try:
                v = float(x)
                return v if math.isfinite(v) else None
            except (TypeError, ValueError):
                return None
        apy_total = _f(q.get("quoted_rate"))
        tvl = _f(q.get("tvl_usd"))
        exitl = _f(q.get("exit_liquidity_usd"))
        chain = q.get("chain") or "Ethereum"
        pid = make_pool_id(protocol, chain, underlying)
        pool = Pool(
            pool_id=pid,
            protocol=str(protocol),
            chain=str(chain),
            asset=underlying,
            tier="T2",                  # PT markets register T2 (registry default); overlay may refine
            source="rates_desk_market",
            apy_total=_norm_apy_decimal(apy_total),
            apy_base=None,
            apy_reward=None,
            tvl_usd=tvl if (tvl is not None and tvl >= 0) else None,
            il_risk=None,
            exposure="single",
            underlying_kind=str(kind) if kind else None,
            market_id=str(mid),
            exit_liquidity_usd=exitl if (exitl is not None and exitl >= 0) else None,
            as_of=q.get("as_of") or surface_as_of,
        )
        # de-dup by pool_id keeping the deepest TVL (deterministic)
        prev = out.get(pid)
        if prev is None or (pool.tvl_usd or -1) > (prev.tvl_usd or -1):
            out[pid] = pool
    return [out[k] for k in sorted(out.keys())]


def build_universe(surface: Optional[dict] = None, as_of: Optional[str] = None) -> List[Pool]:
    """The full followed-pool universe: registry adapters + rates-desk PT markets, de-duplicated by
    `pool_id` (deterministic, SORTED). Same inputs → byte-identical list.

    `as_of` stamps the undated registry adapters (a "latest" live feed has no intrinsic date; the
    DATA date is the day it was read — passed explicitly for determinism, defaulting to the surface
    date, else UTC today). The rates-desk surface markets keep their OWN carried `as_of`.

    fail-CLOSED: a pool with no live APY/TVL is KEPT (identity row with `None` cells) — a hole, never
    dropped and never 0-coerced. The surface is read from the cache unless injected (tests/hermetic)."""
    import datetime as _dt

    from spa_core.adapters import ADAPTER_REGISTRY  # read-only registry (lazy: keep import side-effect-free)

    surf = surface if surface is not None else _read_surface()
    stamp = as_of or (surf.get("as_of") if isinstance(surf, dict) else None) or \
        _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    by_id: Dict[str, Pool] = {}
    for entry in ADAPTER_REGISTRY:
        try:
            key, tier, adapter_cls = entry
        except (ValueError, TypeError):
            continue
        pool = _pool_from_adapter(str(key), str(tier), adapter_cls)
        if pool is None:
            continue
        # stamp the undated "latest" registry feed with the build's DATA date (contemporaneous).
        import dataclasses as _dc
        pool = _dc.replace(pool, as_of=stamp)
        prev = by_id.get(pool.pool_id)
        # registry takes precedence over a same-id surface row; among registry rows keep deepest TVL
        if prev is None or (pool.tvl_usd or -1) > (prev.tvl_usd or -1):
            by_id[pool.pool_id] = pool

    for pool in _pools_from_surface(surf):
        if pool.pool_id not in by_id:   # never clobber a registry identity row
            by_id[pool.pool_id] = pool

    return [by_id[k] for k in sorted(by_id.keys())]


# ── printing ────────────────────────────────────────────────────────────────────────────────────
def _fmt(x, money=False) -> str:
    if x is None:
        return "—"
    return f"${float(x):,.0f}" if money else f"{float(x) * 100:.2f}%"


def _print(pools: List[Pool]) -> None:
    print(f"DFB pool universe — {len(pools)} followed markets (deterministic, sorted)\n")
    hdr = f"{'pool_id':>40s} {'tier':>4s} {'apy':>9s} {'tvl':>14s}  source"
    print(hdr)
    print("-" * len(hdr))
    for p in pools:
        print(f"{p.pool_id[-40:]:>40s} {p.tier:>4s} {_fmt(p.apy_total):>9s} "
              f"{_fmt(p.tvl_usd, money=True):>14s}  {p.source}")
    n_holes = sum(1 for p in pools if p.apy_total is None or p.tvl_usd is None)
    print(f"\n{n_holes} pool(s) with at least one fail-CLOSED hole (None cell, never fabricated).")


def main() -> int:
    pools = build_universe()
    _print(pools)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
