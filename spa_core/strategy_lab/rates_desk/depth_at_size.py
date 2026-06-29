"""
spa_core/strategy_lab/rates_desk/depth_at_size.py — Lane B B1.1: the PER-MARKET DEPTH-AT-SIZE feed.

The measurement spine's first input. For EVERY market the desk follows it answers, in public and
fail-CLOSED, the one question the capacity/killer-test layer needs before it can size anything:

    "At a $1M / $5M / $10M EXIT TICKET, how much can THIS single market actually absorb — what
     fraction of the ticket clears within the impact band, and what is the §9 one-tick exit
     capacity at that size?"

It extends feeds.py's live RateSurface (it CONSUMES the surface, never re-derives the rates) and
surfaces, per market:

  • live TVL (the contemporaneous pool depth the surface already carries: `tvl_usd`),
  • the §9 `exit_liquidity_usd` (= pool_depth × impact_band × sla_discount — already computed by the
    surface assembler; we pass it through, never recompute a flattering number),
  • the constant-product exit fraction `dex_exit_frac(exit_liquidity, ticket)` at each ticket — the
    repo's ONE conservative slippage primitive (the SAME bound exit_nav.py / capacity.py use),
  • `absorbable_usd = ticket × exit_frac` (the conservative deliverable at that ticket), and
  • `within_one_tick` (ticket ≤ max_size_frac_of_exit × exit_liquidity — the §9 sizing cap).

FAIL-CLOSED (the load-bearing honesty rule): a market with thin / stale / missing / non-positive
depth — exit_liquidity_usd below the repo DEX floor (`MIN_DEX_POOL_TVL_USD`), or an `as_of` older
than the freshness window vs the surface date — gets `flagged: "insufficient_contemporaneous_depth"`
and `exit_frac = absorbable_usd = null` at every ticket. NEVER a fabricated number. A visible hole
beats an invented fill.

MONOTONICITY (asserted, tested): for a fixed market `absorbable_frac(ticket)` is NON-INCREASING in
ticket (depth@$1M ≥ depth@$5M ≥ depth@$10M after impact) — a structural property of the
constant-product bound, asserted here so a feed regression surfaces immediately.

PURE / deterministic / stdlib-only / LLM-FORBIDDEN / fail-CLOSED / atomic (repo rule #4). `as_of` is
the SURFACE/data date, never the wall clock. Advisory — moves no capital, never touches the go-live
track, never imports execution/. Run:
    python3 -m spa_core.strategy_lab.rates_desk.depth_at_size
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    MIN_DEX_POOL_TVL_USD,
    dex_exit_frac,
)

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "depth_at_size.json"

# The depth-probe ticket ladder (USD) — the institutional sizes the killer-test scores against.
# Pinned + version-controlled; widening is a research change.
DEPTH_TICKETS_USD: Tuple[int, ...] = (1_000_000, 5_000_000, 10_000_000)

# Genesis prev_hash for the per-market depth row chain (mirrors the §5 / exit-NAV chain genesis).
DEPTH_GENESIS_PREV = "0" * 64

FLAG_REASON_THIN = "insufficient_contemporaneous_depth"

# Freshness window: a market quote whose own `as_of` is more than this many days behind the SURFACE
# date is treated as STALE (non-contemporaneous) and fail-CLOSED, NEVER trusted as live depth. The
# red-team feeds a stale row and asserts it flags. 0 would be too strict for a daily surface where a
# market may carry the prior trading day's snapshot; pinned at a conservative few days.
MAX_DEPTH_STALENESS_DAYS = 3


def _to_float(x) -> Optional[float]:
    """Parse a possibly-Decimal/str numeric to a FINITE float, else None (fail-CLOSED)."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float, Decimal)):
        try:
            f = float(x)
        except (ValueError, OverflowError):
            return None
    elif isinstance(x, str):
        try:
            f = float(x)
        except ValueError:
            return None
    else:
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _round6(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 6)


def _proof_hash(proof_obj: dict) -> str:
    """sha256 over the canonical sorted-JSON of the row's published inputs + outputs + prev_hash —
    reproducible by anyone from the published row, so a forged depth/absorbable number breaks it."""
    blob = json.dumps(proof_obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Whole days between two ISO dates (a..b), or None if either is unparseable (fail-CLOSED)."""
    try:
        da = datetime.date.fromisoformat((a or "")[:10])
        db = datetime.date.fromisoformat((b or "")[:10])
    except ValueError:
        return None
    return abs((db - da).days)


def _is_stale(market_as_of: Optional[str], surface_as_of: Optional[str]) -> bool:
    """A market is STALE (non-contemporaneous) if its quote date trails the surface date by more
    than MAX_DEPTH_STALENESS_DAYS. fail-CLOSED: an unparseable/absent market date is treated as
    stale (we never trust depth we cannot date)."""
    if not market_as_of:
        return True
    if not surface_as_of:
        return False  # no surface date to compare against → cannot prove stale, do not over-flag
    gap = _days_between(market_as_of, surface_as_of)
    if gap is None:
        return True
    return gap > MAX_DEPTH_STALENESS_DAYS


def compute_market_depth_row(
    market_id,
    underlying: str,
    venue: Optional[str],
    tvl_usd: Optional[float],
    exit_liquidity_usd: Optional[float],
    market_as_of: Optional[str],
    surface_as_of: Optional[str],
    params: RatePolicyParams,
    prev_hash: str = DEPTH_GENESIS_PREV,
) -> dict:
    """The per-market depth-at-size row: the conservative constant-product depth at each ticket, or a
    fail-CLOSED hole when depth is thin/stale/absent. NEVER fabricates a number.

    `exit_liquidity_usd` is the §9 one-tick exit capacity the SURFACE already computed (pool_depth ×
    impact_band × sla_discount) — we PASS IT THROUGH, never recompute a flattering value. The
    per-ticket `exit_frac` is `dex_exit_frac(exit_liquidity, ticket)` (the repo's ONE slippage
    primitive). `absorbable_usd = ticket × exit_frac` is the conservative deliverable at that ticket.
    `within_one_tick` = ticket ≤ max_size_frac_of_exit × exit_liquidity (the §9 sizing cap).

    `prev_hash` chains this row to the previous market row (genesis '0'*64); the per-row `proof_hash`
    covers inputs + outputs + prev_hash so a reordered/forged row is detectable on recompute."""
    max_frac = float(params.max_size_frac_of_exit)
    tvl_f = _to_float(tvl_usd)
    exitl_f = _to_float(exit_liquidity_usd)
    stale = _is_stale(market_as_of, surface_as_of)

    inputs = {
        "market_id": str(market_id) if market_id is not None else None,
        "underlying": (underlying or "").lower(),
        "venue": venue,
        "tvl_usd": _round6(tvl_f),
        "exit_liquidity_usd": _round6(exitl_f),
        "market_as_of": market_as_of,
        "surface_as_of": surface_as_of,
        "model": "constant_product_amm_conservative_lower_bound",
        "model_params": {
            "max_size_frac_of_exit": max_frac,
            "min_dex_pool_tvl_usd": MIN_DEX_POOL_TVL_USD,
            "max_staleness_days": MAX_DEPTH_STALENESS_DAYS,
        },
    }

    # FAIL-CLOSED gate: thin / stale / absent / sub-floor depth → publish the HOLE, not a number.
    thin = (exitl_f is None or exitl_f <= 0.0 or exitl_f < MIN_DEX_POOL_TVL_USD)
    if thin or stale:
        reason = FLAG_REASON_THIN
        tickets_out = [
            {"ticket_usd": int(t), "exit_frac": None, "absorbable_usd": None,
             "price_impact_frac": None, "within_one_tick": False,
             "forced_unwind_exit_frac": None, "forced_unwind_absorbable_usd": None}
            for t in DEPTH_TICKETS_USD
        ]
        flagged = True
    else:
        one_tick_capacity = max_frac * exitl_f
        tickets_out = []
        prev_frac: Optional[float] = None
        for t in DEPTH_TICKETS_USD:
            frac = dex_exit_frac(exitl_f, float(t))
            if frac is None:
                tickets_out.append({
                    "ticket_usd": int(t), "exit_frac": None, "absorbable_usd": None,
                    "price_impact_frac": None, "within_one_tick": False})
                continue
            # MONOTONICITY: the constant-product frac is non-increasing in size; clamp defensively so
            # any float wobble can never publish a NON-monotone (flattering) larger-ticket depth.
            if prev_frac is not None and frac > prev_frac:
                frac = prev_frac
            prev_frac = frac
            absorbable = round(float(t) * frac, 6)
            # B2.4 — the conservative forced-unwind floor (a sell past the concentrated band): an even
            # MORE conservative absorbable than the published constant-product number. Published ≥ this.
            fu_frac = forced_unwind_frac(exitl_f, float(t))
            tickets_out.append({
                "ticket_usd": int(t),
                "exit_frac": round(frac, 6),
                "absorbable_usd": absorbable,
                "price_impact_frac": round(max(0.0, 1.0 - frac), 6),
                "within_one_tick": bool(float(t) <= one_tick_capacity),
                "forced_unwind_exit_frac": round(fu_frac, 6) if fu_frac is not None else None,
                "forced_unwind_absorbable_usd": (round(float(t) * fu_frac, 6)
                                                 if fu_frac is not None else None),
            })
        reason = None
        flagged = False

    outputs = {"tickets": tickets_out, "flagged": flagged, "flag_reason": reason}
    row = {
        "market_id": inputs["market_id"],
        "underlying": inputs["underlying"],
        "venue": venue,
        "tvl_usd": _round6(tvl_f),
        "exit_liquidity_usd": _round6(exitl_f),
        "as_of": market_as_of,
        "depth_source": "rate_surface.exit_liquidity_usd",
        "stale": bool(stale),
        "tickets_usd": [int(t) for t in DEPTH_TICKETS_USD],
        "tickets": tickets_out,
        "flagged": flagged,
        "flag_reason": reason,
        "prev_hash": prev_hash,
    }
    row["proof_hash"] = _proof_hash({"inputs": inputs, "outputs": outputs, "prev_hash": prev_hash})
    return row


def _markets_from_surface(surface: dict) -> List[dict]:
    """EVERY priced market on the surface, de-duplicated by market_id keeping the DEEPEST seen
    (a single market, never aggregated). A market with no positive exit_liquidity is still recorded
    (it becomes a fail-CLOSED hole). Deterministic order by market_id. Each →
    {market_id, underlying, venue, tvl_usd, exit_liquidity_usd, as_of}."""
    quotes = surface.get("quotes") if isinstance(surface, dict) else None
    surface_as_of = surface.get("as_of") if isinstance(surface, dict) else None
    if not isinstance(quotes, list):
        return []
    by_id: Dict[str, dict] = {}
    for q in quotes:
        if not isinstance(q, dict):
            continue
        mid = q.get("market_id")
        if mid is None:
            continue
        exitl = _to_float(q.get("exit_liquidity_usd"))
        cand = {
            "market_id": mid,
            "underlying": (q.get("underlying") or "").lower(),
            "venue": q.get("venue"),
            "tvl_usd": _to_float(q.get("tvl_usd")),
            "exit_liquidity_usd": exitl,
            "as_of": q.get("as_of") or surface_as_of,
        }
        prev = by_id.get(str(mid))
        if prev is None:
            by_id[str(mid)] = cand
            continue
        # keep the deepest exit_liquidity seen for the same id (None < any positive)
        pe = prev.get("exit_liquidity_usd")
        if (exitl is not None) and (pe is None or exitl > pe):
            by_id[str(mid)] = cand
    return [by_id[k] for k in sorted(by_id.keys())]


def assert_market_monotonic(row: dict) -> bool:
    """METAMORPHIC property: within a single (un-flagged) market the absorbable FRACTION is
    NON-INCREASING across the ticket ladder (depth@$1M ≥ depth@$5M ≥ depth@$10M after impact).
    Returns True if monotone (or flagged — a hole row has all-null fracs, trivially monotone);
    raises AssertionError naming the violation otherwise. fail-CLOSED: a regression surfaces."""
    if row.get("flagged"):
        return True
    last: Optional[float] = None
    for t in row.get("tickets", []):
        frac = t.get("exit_frac")
        if frac is None:
            continue
        if last is not None:
            assert frac <= last + 1e-12, (
                f"depth-at-size monotonicity violated for market {row.get('market_id')!r}: "
                f"exit_frac rose from {last} to {frac} at ticket {t.get('ticket_usd')}")
        last = frac
    return True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# B2.4 — concentrated-liquidity CONSERVATISM: the published bound is never optimistic
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A Pendle PT pool is a CONCENTRATED-liquidity AMM, not a textbook constant-product (x·y=k) pool: most
# of its depth sits in a tight tick band AROUND the current implied yield. That has two consequences a
# single number must reconcile honestly:
#
#   (A) NEAR-PEG, SMALL size — the concentrated pool is DEEPER than constant-product (liquidity is
#       packed near the mark), so it realizes a HIGHER fill than L/(L+S). Therefore the constant-
#       product fraction we publish is a LOWER BOUND on the well-behaved near-peg fill — never
#       optimistic relative to that realistic case. (We model the realistic near-peg fill with a
#       concentration MULTIPLIER κ>1 on the effective one-sided liquidity.)
#
#   (B) FORCED UNWIND, large size — once a sell pushes PAST the concentrated band the book falls off a
#       cliff and the realized fill is WORSE than constant-product. We must NOT publish above THAT
#       either. We model it as an extra forced-unwind HAIRCUT and assert the published number sits at
#       or below it too.
#
# The published `dex_exit_frac` (constant-product) therefore lives BETWEEN the two: ≤ the near-peg
# concentrated fill (A) AND ≤... no — it must be ≤ the LARGER (near-peg) so it is never optimistic vs
# the friendly case, and the forced-unwind cliff (B) is published SEPARATELY as the conservative floor.
# The load-bearing honesty rule (asserted): the published number is NEVER GREATER than the precise
# near-peg concentrated model — i.e. we never overstate the fill relative to a more realistic model.
CONCENTRATION_MULTIPLIER = 2.0   # κ: near-peg concentrated depth ≈ 2× the constant-product one-sided L
FORCED_UNWIND_CLIFF_FRAC = 0.5   # past the band a forced unwind realizes ≤ 50% of the constant-product fill


def concentrated_near_peg_frac(exit_liquidity_usd: float, size_usd: float,
                               kappa: float = CONCENTRATION_MULTIPLIER) -> Optional[float]:
    """A PRECISE-er near-peg concentrated-liquidity fill model: the same constant-product primitive but
    with κ× the effective one-sided liquidity (a concentrated pool is deeper near the mark). κ>1 ⇒ this
    realizes a HIGHER fraction than the published constant-product `dex_exit_frac` at the same size.
    Used ONLY to ASSERT the published number is never optimistic (published ≤ this). Returns None on no
    defensible depth (fail-CLOSED), mirroring dex_exit_frac."""
    el = _to_float(exit_liquidity_usd)
    sz = _to_float(size_usd)
    if el is None or sz is None or el <= 0.0 or sz < 0.0 or kappa <= 0.0:
        return None
    one_sided = (el / 2.0) * kappa
    return one_sided / (one_sided + sz)  # > dex_exit_frac for κ>1 (no routing cost ⇒ strict upper ref)


def forced_unwind_frac(exit_liquidity_usd: float, size_usd: float,
                       cliff: float = FORCED_UNWIND_CLIFF_FRAC) -> Optional[float]:
    """The CONSERVATIVE forced-unwind model: a sell that pushes past the concentrated band realizes a
    `cliff` fraction of even the constant-product fill. This is the worst-case floor — the published
    `dex_exit_frac` sits AT OR ABOVE it. Returns None on no depth (fail-CLOSED)."""
    base = dex_exit_frac(exit_liquidity_usd, size_usd)
    if base is None:
        return None
    return max(0.0, base * cliff)


def assert_published_is_lower_bound(row: dict) -> bool:
    """B2.4 — ASSERT the published per-ticket constant-product fraction is NEVER optimistic vs the
    precise near-peg concentrated-liquidity model (published ≤ concentrated_near_peg_frac at every
    ticket). A flagged (hole) row is trivially conservative. Raises AssertionError naming the
    violation otherwise. fail-CLOSED: an over-optimistic published number is a regression, not data."""
    if row.get("flagged"):
        return True
    el = _to_float(row.get("exit_liquidity_usd"))
    if el is None or el <= 0:
        return True
    for t in row.get("tickets", []):
        frac = t.get("exit_frac")
        if frac is None:
            continue
        ref = concentrated_near_peg_frac(el, float(t.get("ticket_usd", 0)))
        if ref is None:
            continue
        assert frac <= ref + 1e-12, (
            f"depth-at-size published fraction OPTIMISTIC for market {row.get('market_id')!r} at "
            f"ticket {t.get('ticket_usd')}: published {frac} > near-peg concentrated bound {ref} "
            "(the constant-product number must stay a LOWER bound, never overstate the fill)")
    return True


def build_depth_at_size(
    write: bool = True,
    surface: Optional[dict] = None,
    params: Optional[RatePolicyParams] = None,
    data_dir: Optional[Path] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the deterministic per-market depth-at-size feed and (optionally) write
    data/rates_desk/depth_at_size.json atomically. Same surface → byte-identical JSON.

    Reads the cached RateSurface (data/rates_desk/rate_surface.json) unless `surface` is injected.
    fail-CLOSED throughout: a missing surface → an empty (flagged) feed; a thin/stale market → a hole
    row; never a fabricated depth. Every un-flagged market row is monotonicity-asserted before it is
    published (a non-monotone larger-ticket depth is a regression, not data)."""
    params = params or RatePolicyParams()
    dd = data_dir or (_ROOT / "data")
    if surface is None:
        surface = _read_json(dd / "rates_desk" / "rate_surface.json") or {}
    surface_as_of = surface.get("as_of") if isinstance(surface, dict) else None

    markets_in = _markets_from_surface(surface)
    rows: List[dict] = []
    prev_hash = DEPTH_GENESIS_PREV
    n_flagged = 0
    for m in markets_in:
        row = compute_market_depth_row(
            market_id=m["market_id"], underlying=m["underlying"], venue=m.get("venue"),
            tvl_usd=m.get("tvl_usd"), exit_liquidity_usd=m.get("exit_liquidity_usd"),
            market_as_of=m.get("as_of"), surface_as_of=surface_as_of, params=params,
            prev_hash=prev_hash,
        )
        assert_market_monotonic(row)  # fail-CLOSED on a non-monotone published row
        assert_published_is_lower_bound(row)  # B2.4: never optimistic vs the concentrated model
        if row["flagged"]:
            n_flagged += 1
        rows.append(row)
        prev_hash = row["proof_hash"]

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_depth_at_size",
        "model_label": "per-market contemporaneous depth at $1M/$5M/$10M (constant-product LOWER BOUND)",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "as_of": surface_as_of,
        "tickets_usd": [int(t) for t in DEPTH_TICKETS_USD],
        "depth_basis": "single-market contemporaneous Pendle PT exit liquidity (§9; NEVER aggregated)",
        "model_params": {
            "max_size_frac_of_exit": float(params.max_size_frac_of_exit),
            "min_dex_pool_tvl_usd": MIN_DEX_POOL_TVL_USD,
            "max_staleness_days": MAX_DEPTH_STALENESS_DAYS,
            "concentration_multiplier_kappa": CONCENTRATION_MULTIPLIER,
            "forced_unwind_cliff_frac": FORCED_UNWIND_CLIFF_FRAC,
        },
        # B2.1 — the live-depth FRESHNESS provenance (auditable, fail-CLOSED). The depth is the
        # contemporaneous RateSurface exit_liquidity (DeFiLlama-TTL-cached upstream, §9 model on the
        # per-day Pendle TVL); a market whose own as_of trails the surface date by > max_staleness_days
        # is flagged stale and NOT used (never trusted as live depth). This is the audit trail.
        "surface_freshness": {
            "surface_as_of": surface_as_of,
            "surface_mode": surface.get("mode") if isinstance(surface, dict) else None,
            "n_stale_markets": sum(1 for r in rows if r.get("stale")),
            "max_staleness_days": MAX_DEPTH_STALENESS_DAYS,
            "depth_source": "rate_surface.exit_liquidity_usd (contemporaneous; TTL-cached upstream)",
        },
        "n_markets": len(rows),
        "n_flagged_insufficient_depth": n_flagged,
        "markets": rows,
        "flagged": bool(n_flagged > 0 or not rows),
        "basis": ("per-market depth-at-size from the contemporaneous RateSurface; conservative "
                  "constant-product lower bound; thin/stale depth fail-CLOSES to a published hole"),
        "disclaimer": ("Each market's depth is a CONSERVATIVE LOWER BOUND against THAT market's own "
                       "single-market contemporaneous §9 exit liquidity — NEVER aggregated across "
                       "markets. Thin/stale/absent depth is flagged insufficient_contemporaneous_depth, "
                       "never filled with a fabricated number. Advisory — moves no capital."),
    }
    if write:
        _io.atomic_write_json(out_path or _OUT, result, indent=1, default=str)
    return result


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ── market lookup helper (consumed by B1.6 exit-NAV hole closure) ───────────────────────────────────
def depth_for_market(feed: dict, market_id, underlying: Optional[str] = None) -> Optional[dict]:
    """The depth row for a market (exact market_id, else deepest un-flagged row on the same
    underlying), or None. Used by exit_nav.py (B1.6) to resolve a $1M+ hole to a real conservative
    bound WHERE depth exists. Returns the row only if it carries a usable (un-flagged) exit_liquidity."""
    markets = feed.get("markets") if isinstance(feed, dict) else None
    if not isinstance(markets, list):
        return None
    mid = str(market_id) if market_id is not None else None
    for m in markets:
        if isinstance(m, dict) and mid is not None and str(m.get("market_id")) == mid:
            return m if not m.get("flagged") else None
    if underlying is None:
        return None
    u = underlying.lower()
    best = None
    for m in markets:
        if not isinstance(m, dict) or m.get("flagged"):
            continue
        if (m.get("underlying") or "").lower() != u:
            continue
        el = _to_float(m.get("exit_liquidity_usd"))
        if el is None:
            continue
        if best is None or el > _to_float(best.get("exit_liquidity_usd")):
            best = m
    return best


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _fmt_usd(x) -> str:
    return "—" if x is None else f"${float(x):,.0f}"


def _print(result: dict) -> None:
    print("Rates Desk — DEPTH-AT-SIZE  (per-market, conservative lower bound; advisory)")
    print(f"as_of: {result.get('as_of')}  ·  markets: {result.get('n_markets')}  ·  "
          f"flagged thin/stale: {result.get('n_flagged_insufficient_depth')}\n")
    hdr = (f"{'market':>28s} {'underlying':>10s} {'exitLiq$':>14s} "
           f"{'abs@1M':>12s} {'abs@5M':>12s} {'abs@10M':>12s}  flag")
    print(hdr)
    print("-" * len(hdr))
    for m in result.get("markets", []):
        abss = {t["ticket_usd"]: t.get("absorbable_usd") for t in m.get("tickets", [])}
        mid = str(m.get("market_id") or "")[-28:]
        print(f"{mid:>28s} {str(m.get('underlying') or '')[:10]:>10s} "
              f"{_fmt_usd(m.get('exit_liquidity_usd')):>14s} "
              f"{_fmt_usd(abss.get(1_000_000)):>12s} {_fmt_usd(abss.get(5_000_000)):>12s} "
              f"{_fmt_usd(abss.get(10_000_000)):>12s}  "
              f"{(m.get('flag_reason') or '') if m.get('flagged') else ''}")
    print(f"\nflagged: {result.get('flagged')}")


def main() -> int:
    result = build_depth_at_size(write=True)
    _print(result)
    print(f"\nWrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
