"""
spa_core/dfb/breadth_feed.py — WS-2.2: BREADTH ingestion behind the SPA_DFB_BREADTH flag.

Grows the DFB universe BEYOND the ~35-adapter curated whitelist by ingesting READ-ONLY, KEYLESS
DeFiLlama yield pools — but every breadth pool is just another `Pool` IDENTITY row that the SAME
`risk_overlay.overlay()` then grades. THE INVARIANT: breadth is MORE pools, the SAME risk truth —
**0 pools bypass the overlay**. A breadth pool whose underlying kind / depth the engine cannot resolve
fail-CLOSES to UNKNOWN inside the overlay (never an ungraded "safe" passthrough, never a watered-down
grade).

NO risk math here (the NO-FORK rule): this module only turns the keyless DeFiLlama `/pools` surface
into validated `Pool` identity rows (the same job `pool_universe._pool_from_adapter` does for the
whitelist). All judgment stays in `risk_overlay` → the imported engine.

FLAG: `SPA_DFB_BREADTH` (env, default OFF). Flag OFF → `build_breadth_pools()` returns [] (the
curated whitelist is the universe). Flag ON → the wider keyless universe. This mirrors the charter's
owner-gated flag table: buildable now, activation owner-gated.

CONVENTIONS: stdlib only · deterministic (sorted output; `as_of` = the DATA date) · fail-CLOSED (a
malformed / dead / spam row is DROPPED, never fabricated; a sub-floor TVL row is dropped) · READ-ONLY
(never writes; never imports execution/).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import os
from typing import List, Optional

from spa_core.dfb import Pool

# The flag that gates breadth ingestion (charter § 7 — default OFF, activation owner-gated).
BREADTH_FLAG_ENV = "SPA_DFB_BREADTH"

# Honest floors: a breadth pool below these is DROPPED (a dead/spam pool is not "live", and a
# microscopic pool cannot carry a real exit bound). These are IDENTITY-row admission floors, NOT risk
# math — the overlay still applies its OWN deterministic depth/refusal verdict to every admitted row.
_MIN_TVL_USD = 1_000_000.0     # $1M TVL floor (below this a pool's depth is noise)
_MIN_APY = 0.0                 # reject negative APY (malformed)
_MAX_APY = 5.0                 # reject > 500% APY (malformed/spam, MEMORY: percent-vs-decimal)

# Cap how many breadth rows we admit per build (deterministic, top-by-TVL) so the universe stays
# bounded and the overlay pass stays fast. Owner can lift later (WS-3.2 perf/snapshots).
DEFAULT_MAX_BREADTH_POOLS = 200


def breadth_enabled(override: Optional[bool] = None) -> bool:
    """Resolve the breadth flag. `override` (a test/explicit bool) wins; else read SPA_DFB_BREADTH
    (truthy = "1"/"true"/"yes"/"on", case-insensitive). Default OFF (fail-safe to the whitelist)."""
    if override is not None:
        return bool(override)
    val = (os.environ.get(BREADTH_FLAG_ENV) or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _f(x) -> Optional[float]:
    """Coerce to a finite float, None on malformed (fail-CLOSED)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _norm_apy(raw) -> Optional[float]:
    """DeFiLlama `/pools` APY fields are in PERCENT (e.g. 8.5 == 8.5%); normalize to a DECIMAL fraction,
    fail-CLOSED. Rejects non-finite / out-of-band (MEMORY: adapters mix units — breadth is percent)."""
    v = _f(raw)
    if v is None:
        return None
    frac = v / 100.0
    if frac < _MIN_APY or frac > _MAX_APY:
        return None
    return frac


def _il_risk(row: dict) -> Optional[str]:
    il = row.get("ilRisk")
    if isinstance(il, str) and il.strip():
        return il.strip().lower()
    return None


def _exposure(row: dict) -> Optional[str]:
    ex = row.get("exposure")
    if isinstance(ex, str) and ex.strip():
        return ex.strip().lower()
    return None


def _pool_from_llama_row(row: dict, as_of: str):
    """One breadth `Pool` identity row from a raw DeFiLlama `/pools` element, fail-CLOSED.

    Returns the Pool, OR None if the row is malformed / dead / below the admission floors. NEVER
    fabricates a number. The `underlying_kind` / `market_id` are left None: the overlay resolves the
    kind from the asset symbol via the desk config and fail-CLOSES to UNKNOWN if it cannot — so a
    breadth pool the engine can't classify is graded UNKNOWN, never shown as a bare passthrough.
    """
    from spa_core.dfb.pool_universe import make_pool_id

    if not isinstance(row, dict):
        return None
    project = row.get("project")
    chain = row.get("chain")
    symbol = row.get("symbol")
    if not (isinstance(project, str) and project.strip()
            and isinstance(chain, str) and chain.strip()
            and isinstance(symbol, str) and symbol.strip()):
        return None

    tvl = _f(row.get("tvlUsd"))
    if tvl is None or tvl < _MIN_TVL_USD:
        return None

    apy_total = _norm_apy(row.get("apy"))
    apy_base = _norm_apy(row.get("apyBase"))
    apy_reward = _norm_apy(row.get("apyReward"))
    if apy_total is None:  # a live pool must carry a sane total APY (fail-CLOSED otherwise)
        return None

    asset = symbol.strip()
    return Pool(
        pool_id="breadth-" + make_pool_id(project, chain, asset),
        protocol=project.strip(),
        chain=chain.strip(),
        asset=asset,
        tier="T3",                      # breadth = un-curated → the most conservative tier tag
        source="defillama_breadth",
        apy_total=apy_total,
        apy_base=apy_base,
        apy_reward=apy_reward,
        tvl_usd=tvl,
        il_risk=_il_risk(row),
        exposure=_exposure(row),
        underlying_kind=None,           # overlay resolves from symbol → else UNKNOWN (0 bypass)
        market_id=None,
        as_of=as_of,
    )


def build_breadth_pools(
    *,
    enabled: Optional[bool] = None,
    rows: Optional[List[dict]] = None,
    as_of: Optional[str] = None,
    max_pools: int = DEFAULT_MAX_BREADTH_POOLS,
    feed=None,
) -> List[Pool]:
    """The keyless-DeFiLlama BREADTH pool slice, behind the SPA_DFB_BREADTH flag.

    Flag OFF → []. Flag ON → up to `max_pools` admitted `Pool` identity rows (top by TVL, deterministic
    SORTED by pool_id). `rows` injects the raw `/pools` list (tests/hermetic); else the keyless
    `DeFiLlamaFeed` is read (read-only, cached). fail-CLOSED at every layer: feed unavailable → [];
    a malformed/dead/sub-floor row → dropped (never fabricated). EVERY admitted row is a plain Pool
    that `risk_overlay.overlay()` then grades (0 bypass)."""
    if not breadth_enabled(enabled):
        return []

    import datetime as _dt
    stamp = as_of or _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    raw_rows = rows
    if raw_rows is None:
        try:
            from spa_core.adapters.defillama_feed import DeFiLlamaFeed
            f = feed if feed is not None else DeFiLlamaFeed()
            raw_rows = f._fetch_pools()  # the keyless /pools list (read-only, cached)
        except Exception:  # noqa: BLE001 — fail-CLOSED: no breadth rather than a crash
            raw_rows = None
    if not isinstance(raw_rows, list):
        return []

    pools: List[Pool] = []
    for r in raw_rows:
        pool = _pool_from_llama_row(r, stamp)
        if pool is not None:
            pools.append(pool)

    # de-dup by pool_id (keep deepest TVL), then take the top `max_pools` by TVL, return SORTED by id.
    by_id = {}
    for p in pools:
        prev = by_id.get(p.pool_id)
        if prev is None or (p.tvl_usd or -1) > (prev.tvl_usd or -1):
            by_id[p.pool_id] = p
    ranked = sorted(by_id.values(), key=lambda p: (-(p.tvl_usd or 0.0), p.pool_id))
    top = ranked[: max(0, int(max_pools))]
    return sorted(top, key=lambda p: p.pool_id)
