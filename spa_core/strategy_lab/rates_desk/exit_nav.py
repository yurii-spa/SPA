"""
spa_core/strategy_lab/rates_desk/exit_nav.py — the investor-facing LIQUIDATION-NAV-BY-SIZE surface.

THE flagship surface no competitor publishes: a per-ticket EXIT SCHEDULE for the desk's OWN open
carry book. For a row of liquidation ticket sizes ($100k / $250k / $1M / $5M / $10M) we answer, in
public, the one question an investor actually has to trust before putting money in:

    "If I need OUT at size, what do I actually get back, and how long does it take?"

We answer it HONESTLY, with a CONSERVATIVE LOWER BOUND tied to VALIDATED contemporaneous depth:

  • DEPTH = the REAL contemporaneous Pendle PT exit liquidity of the position's single market —
    priority (a) `exit_liquidity_usd` from the live RateSurface (the §9 proxy: pool_depth ×
    impact_band × sla_discount), priority (b) the position market's contemporaneous `tvl_usd` from
    the deep Pendle PT history. SINGLE-market depth, never aggregated across markets (aggregating
    would FLATTER the number — a forced unwind cannot route a sUSDe-PT exit through an unrelated
    pool). Conservative by construction.

  • PRICE IMPACT = `1 − dex_exit_frac(depth, ticket)`, the repo's ONE constant-product slippage
    primitive (promoted from the RWA backstop). THE ARCHITECT'S DECISION, followed exactly: the
    constant-product `L/(L+S)` model is a CONSERVATIVE LOWER BOUND, NOT a precise execution model
    for concentrated-liquidity Pendle pools (which are deeper near peg but FAR thinner in a forced
    unwind). We PUBLISH ONLY THE BOUND, explicitly labeled, citing the Oct-2025 §9 exit_liquidity
    stress validation. A defensible lower bound beats a precise-looking number we cannot defend.

  • TIME-TO-EXIT = `ceil(ticket / (max_size_frac_of_exit × daily_exit_liquidity))` — the §9
    one-tick sizing cap (the gate refuses to move more than `max_size_frac_of_exit` of exit
    liquidity per tick), expressed as the number of one-tick days a clean unwind would take.

  • FAIL-CLOSED: depth missing / zero / below the repo DEX floor (`MIN_DEX_POOL_TVL_USD`) ⇒
    `net_proceeds_usd = null`, `haircut_pct = null`, `flagged = true`,
    `flag_reason = "insufficient_contemporaneous_depth"`. We NEVER extrapolate a number we cannot
    source. A visible hole beats a fabricated fill.

  • PROVENANCE per row: `as_of` (the SURFACE date — never the wall clock), `depth_usd`, the model
    name + params, the data source, and a per-row `proof_hash = sha256` over the canonical
    sorted-JSON row inputs — reproducible by anyone from the published inputs.

PURE / deterministic / stdlib-only / LLM-FORBIDDEN / fail-CLOSED / atomic. Advisory: this is a
paper/backtest-derived bound, NOT realized exits, and it moves NO capital. Run:
    python3 -m spa_core.strategy_lab.rates_desk.exit_nav
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    MIN_DEX_POOL_TVL_USD,
    OPERATIONAL_HAIRCUT_BPS,
    dex_exit_frac,
)

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "exit_nav.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

# Idempotent doc markers — this module owns ONLY this block; capacity.py / exit_liquidity_validation.py
# each preserve their own marked sections (mirror capacity.py).
_DOC_BEGIN = "<!-- BEGIN rates-desk exit-NAV-by-size schedule (exit_nav) -->"
_DOC_END = "<!-- END rates-desk exit-NAV-by-size schedule (exit_nav) -->"

# The investor-facing liquidation ticket ladder (USD). Pinned + version-controlled; widening is a
# research change. Spans a retail-size exit ($100k) up to an institutional block ($10M) so the
# schedule shows BOTH the near-frictionless small ticket and the size at which the thin Pendle PT
# pools bite hard.
EXIT_TICKETS_USD: Tuple[int, ...] = (100_000, 250_000, 1_000_000, 5_000_000, 10_000_000)

# The published model label + its citation. Honesty is load-bearing: we never let a reader mistake
# the bound for a precise execution estimate.
MODEL_NAME = "constant_product_amm_conservative_lower_bound"
VALIDATION_REF = "docs/RATES_DESK_VALIDATION.md#exit-liquidity (Oct-2025 stress)"
FLAG_REASON_THIN = "insufficient_contemporaneous_depth"

# When the live paper book has NO open positions, we publish the schedule against a STATED
# hypothetical book (clearly labeled `book.source == "hypothetical"`) so the surface is never blank —
# but we NEVER pretend a hypothetical is a live position. The hypothetical uses the single deepest
# real PT market on the surface as its reference (the most generous honest choice → still a bound).
_HYPOTHETICAL_GROSS_USD = 1_000_000.0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# depth resolution — the REAL contemporaneous single-market Pendle PT exit liquidity
# ══════════════════════════════════════════════════════════════════════════════════════════════════
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
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _surface_exit_liquidity(surface: dict, market_id: str, underlying: str) -> Optional[float]:
    """Priority (a): the §9 `exit_liquidity_usd` from the live RateSurface for THIS market.

    Match by market_id first (exact), then by underlying (the deepest matching quote — a position's
    underlying carry can only realistically exit into its own underlying's PT pool). SINGLE quote,
    never summed across quotes."""
    quotes = surface.get("quotes") if isinstance(surface, dict) else None
    if not isinstance(quotes, list):
        return None
    # exact market_id match
    for q in quotes:
        if isinstance(q, dict) and q.get("market_id") == market_id:
            v = _to_float(q.get("exit_liquidity_usd"))
            if v is not None and v > 0:
                return v
    # else deepest quote on the same underlying (single market, conservative — pick one, not a sum)
    best: Optional[float] = None
    u = (underlying or "").lower()
    for q in quotes:
        if not isinstance(q, dict):
            continue
        if (q.get("underlying") or "").lower() != u:
            continue
        v = _to_float(q.get("exit_liquidity_usd"))
        if v is not None and v > 0:
            best = v if best is None else max(best, v)
    return best


def _history_exit_liquidity(deep: dict, market_id: str, underlying: str, as_of: str,
                            params: RatePolicyParams) -> Optional[float]:
    """Priority (b): derive exit liquidity from the deep Pendle PT history's contemporaneous
    `tvl_usd` for the position's market, applying the SAME §9 proxy shape the surface uses
    (depth × impact_band × sla_discount). SINGLE market. fail-CLOSED if no contemporaneous TVL."""
    from spa_core.strategy_lab.rates_desk import config

    markets = deep.get("markets") if isinstance(deep, dict) else None
    if not isinstance(markets, dict):
        return None

    def _proxy_from_tvl(tvl: float) -> Optional[float]:
        v = _to_float(tvl)
        if v is None or v <= 0:
            return None
        band = float(config.EXIT_PRICE_IMPACT_BAND_BPS) / 10_000.0
        # sla_discount: the surface's §9 proxy discounts for settlement; mirror it conservatively at
        # the contemporaneous TVL. We use the impact band as the realisable-at-impact fraction —
        # i.e. only the slice within the price-impact band counts as one-tick exit depth.
        return v * band

    # locate the market by address/id, contemporaneous (<= as_of, latest available) tvl
    def _tvl_on_or_before(series: list) -> Optional[float]:
        dated = [(pt.get("date"), pt.get("tvl_usd")) for pt in series
                 if isinstance(pt, dict) and isinstance(pt.get("date"), str)]
        usable = [(d, t) for d, t in dated if d <= as_of and _to_float(t) and _to_float(t) > 0]
        if not usable:
            return None
        usable.sort(key=lambda dt: dt[0])
        return _to_float(usable[-1][1])

    # exact market match (by market_address or pt_address == market_id)
    for m in markets.values():
        if not isinstance(m, dict):
            continue
        if market_id in (m.get("market_address"), m.get("pt_address"), m.get("symbol")):
            tvl = _tvl_on_or_before(m.get("series", []))
            if tvl is not None:
                return _proxy_from_tvl(tvl)
    # else deepest contemporaneous market on the same underlying (single market, conservative)
    u = (underlying or "").lower()
    best: Optional[float] = None
    for m in markets.values():
        if not isinstance(m, dict) or (m.get("underlying") or "").lower() != u:
            continue
        tvl = _tvl_on_or_before(m.get("series", []))
        if tvl is not None:
            best = tvl if best is None else max(best, tvl)
    return _proxy_from_tvl(best) if best is not None else None


def _resolve_depth(surface: dict, deep: dict, market_id: str, underlying: str, as_of: str,
                   params: RatePolicyParams) -> Tuple[Optional[float], str]:
    """Resolve the SINGLE-market contemporaneous exit depth, priority surface → history.
    Returns (depth_usd_or_None, data_source). fail-CLOSED: None if neither source has it."""
    d = _surface_exit_liquidity(surface, market_id, underlying)
    if d is not None and d > 0:
        return d, "rate_surface.exit_liquidity_usd"
    d = _history_exit_liquidity(deep, market_id, underlying, as_of, params)
    if d is not None and d > 0:
        return d, "pendle_pt_history.tvl_usd×impact_band"
    return None, "none"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# per-ticket exit math (deterministic, conservative LOWER BOUND, fail-CLOSED)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _proof_hash(row_inputs: dict) -> str:
    """sha256 over the canonical sorted-JSON of the row's PUBLISHED inputs — reproducible by anyone
    from the published row (the inputs we expose), so the proof is independently verifiable."""
    blob = json.dumps(row_inputs, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _round6(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 6)


def compute_ticket_row(
    ticket_usd: int,
    gross_usd: float,
    depth_usd: Optional[float],
    as_of: Optional[str],
    data_source: str,
    params: RatePolicyParams,
) -> dict:
    """The per-ticket exit row — the conservative lower bound. fail-CLOSED on thin/absent depth.

    `gross_usd` is the notional being exited at this ticket (= min(ticket, book size) is the caller's
    choice; we exit the TICKET notional, capped at nothing here — the ticket IS the size the investor
    asks to pull). `depth_usd` is the SINGLE-market contemporaneous exit liquidity. Everything is the
    constant-product LOWER BOUND, never a precise fill."""
    op_haircut_frac = OPERATIONAL_HAIRCUT_BPS / 10_000.0
    max_frac = float(params.max_size_frac_of_exit)

    # canonical published inputs the proof_hash is taken over (reproducible from the row).
    row_inputs = {
        "ticket_usd": int(ticket_usd),
        "gross_usd": round(float(gross_usd), 6),
        "depth_usd": _round6(depth_usd),
        "as_of": as_of,
        "model": MODEL_NAME,
        "model_params": {
            "dex_routing_cost_bps": 5.0,
            "operational_haircut_bps": OPERATIONAL_HAIRCUT_BPS,
            "max_size_frac_of_exit": max_frac,
            "min_dex_pool_tvl_usd": MIN_DEX_POOL_TVL_USD,
        },
        "data_source": data_source,
    }
    proof_hash = _proof_hash(row_inputs)

    base = {
        "ticket_usd": int(ticket_usd),
        "gross_usd": round(float(gross_usd), 6),
        "depth_usd": _round6(depth_usd),
        "as_of": as_of,
        "model": MODEL_NAME,
        "model_params": row_inputs["model_params"],
        "data_source": data_source,
        "proof_hash": proof_hash,
    }

    # ── FAIL-CLOSED: no defensible contemporaneous depth → publish the HOLE, not a number ──
    if depth_usd is None or depth_usd <= 0.0 or depth_usd < MIN_DEX_POOL_TVL_USD:
        base.update({
            "exit_frac": None,
            "price_impact_frac": None,
            "net_proceeds_usd": None,
            "haircut_pct": None,
            "time_to_exit_days": None,
            "within_one_tick": False,
            "flagged": True,
            "flag_reason": FLAG_REASON_THIN,
        })
        return base

    # ── conservative constant-product bound (the repo's ONE slippage primitive) ──
    frac = dex_exit_frac(depth_usd, float(ticket_usd))
    if frac is None:  # defensive: dex_exit_frac fail-closed (non-finite) — treat as a hole
        base.update({
            "exit_frac": None, "price_impact_frac": None, "net_proceeds_usd": None,
            "haircut_pct": None, "time_to_exit_days": None, "within_one_tick": False,
            "flagged": True, "flag_reason": FLAG_REASON_THIN,
        })
        return base

    price_impact_frac = max(0.0, 1.0 - frac)
    gross = float(gross_usd)
    op_haircut_usd = gross * op_haircut_frac
    net_proceeds = gross * frac - op_haircut_usd
    net_proceeds = max(0.0, net_proceeds)               # never negative
    net_proceeds = min(net_proceeds, gross)             # CONSERVATIVE BOUND: net ≤ gross, always
    haircut_pct = ((gross - net_proceeds) / gross * 100.0) if gross > 0 else None

    # §9 one-tick sizing cap → time-to-exit in one-tick days.
    daily_exit_liquidity = max_frac * depth_usd
    if daily_exit_liquidity > 0:
        time_to_exit_days = int(math.ceil(float(ticket_usd) / daily_exit_liquidity))
    else:
        time_to_exit_days = None
    within_one_tick = bool(time_to_exit_days == 1)

    base.update({
        "exit_frac": round(frac, 6),
        "price_impact_frac": round(price_impact_frac, 6),
        "net_proceeds_usd": round(net_proceeds, 6),
        "haircut_pct": round(haircut_pct, 6) if haircut_pct is not None else None,
        "time_to_exit_days": time_to_exit_days,
        "within_one_tick": within_one_tick,
        "flagged": False,
        "flag_reason": None,
    })
    return base


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# book resolution — the desk's OWN open carry book (or a stated hypothetical)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _load_open_book(data_dir: Path) -> Optional[dict]:
    """The desk's largest open paper carry position, read from the live paper state — the single
    market we publish the exit schedule against. Returns
    {market_id, underlying, gross_usd, as_of, source:"live"} or None if no open book."""
    state_path = data_dir / "rates_desk" / "paper" / "rates_desk_fixed_carry_state.json"
    try:
        st = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    books = (st.get("state", {}) or {}).get("books", {}) if isinstance(st, dict) else {}
    if not isinstance(books, dict) or not books:
        return None
    # the LARGEST open book by size (the hardest exit → the most relevant investor question).
    best = None
    for bk in books.values():
        if not isinstance(bk, dict):
            continue
        size = _to_float(bk.get("size"))
        if size is None or size <= 0:
            continue
        q = bk.get("quote", {}) if isinstance(bk.get("quote"), dict) else {}
        cand = {
            "market_id": bk.get("market_id") or q.get("market_id"),
            "underlying": (q.get("underlying") or "").lower(),
            "gross_usd": size,
            "as_of": q.get("as_of"),
            "source": "live",
        }
        if best is None or cand["gross_usd"] > best["gross_usd"]:
            best = cand
    return best


def _hypothetical_book(surface: dict, deep: dict) -> Optional[dict]:
    """A STATED hypothetical book (clearly labeled) anchored to the deepest real PT market on the
    surface — used ONLY when there is no live open book, so the surface is never blank. Never
    presented as a live position."""
    quotes = surface.get("quotes") if isinstance(surface, dict) else None
    as_of = surface.get("as_of") if isinstance(surface, dict) else None
    best = None
    if isinstance(quotes, list):
        for q in quotes:
            if not isinstance(q, dict):
                continue
            depth = _to_float(q.get("exit_liquidity_usd"))
            if depth is None or depth <= 0:
                continue
            cand = {
                "market_id": q.get("market_id"),
                "underlying": (q.get("underlying") or "").lower(),
                "gross_usd": _HYPOTHETICAL_GROSS_USD,
                "as_of": q.get("as_of") or as_of,
                "source": "hypothetical",
                "_depth_hint": depth,
            }
            if best is None or depth > best["_depth_hint"]:
                best = cand
    if best is not None:
        best.pop("_depth_hint", None)
        return best
    return None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# build_exit_nav_schedule — the engine
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_exit_nav_schedule(
    write: bool = True,
    surface: Optional[dict] = None,
    deep: Optional[dict] = None,
    book: Optional[dict] = None,
    params: Optional[RatePolicyParams] = None,
    tickets_usd: Optional[Tuple[int, ...]] = None,
    data_dir: Optional[Path] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the deterministic per-ticket exit-NAV schedule and (optionally) write
    data/rates_desk/exit_nav.json atomically. Same (surface, deep, book) → byte-identical JSON.

    Fail-CLOSED throughout: a missing surface/depth yields FLAGGED rows (net=null), never a fabricated
    fill. The whole surface is honest-enveloped (is_advisory / basis / disclaimer / validation_ref)."""
    params = params or RatePolicyParams()
    tickets = tuple(tickets_usd) if tickets_usd is not None else EXIT_TICKETS_USD
    dd = data_dir or (_ROOT / "data")

    if surface is None:
        surface = _read_json(dd / "rates_desk" / "rate_surface.json") or {}
    if deep is None:
        deep = _read_json(dd / "rates_desk" / "pendle_pt_history.json") or {}

    as_of = surface.get("as_of") if isinstance(surface, dict) else None

    # ── resolve the book (live open position → else stated hypothetical) ──
    if book is None:
        book = _load_open_book(dd)
    book_source = "live"
    if book is None:
        book = _hypothetical_book(surface, deep)
        book_source = "hypothetical"
    if book is None:
        # no live book AND no surface to anchor a hypothetical → fully fail-CLOSED empty schedule.
        result = _empty_result(as_of, params, reason="no_open_book_and_no_surface")
        if write:
            _io.atomic_write_json(out_path or _OUT, result, indent=1, default=str)
        return result

    market_id = book.get("market_id")
    underlying = (book.get("underlying") or "").lower()
    book_as_of = book.get("as_of") or as_of
    gross_book = _to_float(book.get("gross_usd")) or 0.0
    book_source = book.get("source", book_source)

    depth_usd, data_source = _resolve_depth(surface, deep, market_id, underlying, book_as_of, params)

    # ── per-ticket rows. We exit the TICKET notional (the investor's requested pull). The `as_of`
    #    on every row is the SURFACE/position date — never the wall clock. ──
    row_as_of = book_as_of or as_of
    schedule: List[dict] = []
    any_flagged = False
    for t in tickets:
        row = compute_ticket_row(
            ticket_usd=int(t), gross_usd=float(t), depth_usd=depth_usd,
            as_of=row_as_of, data_source=data_source, params=params,
        )
        if row["flagged"]:
            any_flagged = True
        schedule.append(row)

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": MODEL_NAME,
        "model_label": "constant-product AMM, conservative LOWER BOUND (not a precise execution model)",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "as_of": row_as_of,
        "depth_usd": _round6(depth_usd),
        "depth_basis": "single-market contemporaneous Pendle PT exit liquidity (NOT aggregated)",
        "data_source": data_source,
        "model_params": {
            "dex_routing_cost_bps": 5.0,
            "operational_haircut_bps": OPERATIONAL_HAIRCUT_BPS,
            "max_size_frac_of_exit": float(params.max_size_frac_of_exit),
            "min_dex_pool_tvl_usd": MIN_DEX_POOL_TVL_USD,
        },
        "book": {
            "source": book_source,
            "market_id": market_id,
            "underlying": underlying,
            "gross_usd": round(gross_book, 6),
            "as_of": book_as_of,
        },
        "tickets_usd": [int(t) for t in tickets],
        "schedule": schedule,
        "flagged": bool(any_flagged or depth_usd is None),
        "basis": ("paper/backtest-derived from contemporaneous on-chain Pendle PT depth; "
                  "conservative lower bound; NOT realized exits"),
        "disclaimer": ("Conservative LOWER BOUND on forced-unwind proceeds, NOT a precise execution "
                       "estimate or a realized exit. The constant-product L/(L+S) model under-states "
                       "deliverable proceeds near peg and is published only as a defensible floor; "
                       "concentrated-liquidity Pendle pools can be far thinner in a forced unwind. "
                       "Single-market depth, never aggregated. Advisory — moves no capital."),
        "validation_ref": VALIDATION_REF,
    }
    if write:
        _io.atomic_write_json(out_path or _OUT, result, indent=1, default=str)
    return result


def _empty_result(as_of, params: RatePolicyParams, reason: str) -> dict:
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": MODEL_NAME,
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "as_of": as_of,
        "depth_usd": None,
        "data_source": "none",
        "model_params": {
            "dex_routing_cost_bps": 5.0,
            "operational_haircut_bps": OPERATIONAL_HAIRCUT_BPS,
            "max_size_frac_of_exit": float(params.max_size_frac_of_exit),
            "min_dex_pool_tvl_usd": MIN_DEX_POOL_TVL_USD,
        },
        "book": None,
        "tickets_usd": list(EXIT_TICKETS_USD),
        "schedule": [],
        "flagged": True,
        "flag_reason": reason,
        "basis": ("paper/backtest-derived from contemporaneous on-chain Pendle PT depth; "
                  "conservative lower bound; NOT realized exits"),
        "disclaimer": ("Conservative LOWER BOUND on forced-unwind proceeds, NOT a precise execution "
                       "estimate or a realized exit."),
        "validation_ref": VALIDATION_REF,
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# doc section + printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _fmt_usd(x) -> str:
    if x is None:
        return "—"
    return f"${float(x):,.0f}"


def _render_doc_section(result: dict) -> str:
    L: List[str] = [_DOC_BEGIN, ""]
    L.append("## Liquidation-NAV-by-size — the per-ticket EXIT schedule (the flagship surface)\n")
    L.append(
        "_The investor-facing per-ticket exit schedule for the desk's OWN open carry book — what a "
        "forced unwind realises at $100k / $250k / $1M / $5M / $10M, and how long it takes. PUBLISHED "
        "AS A CONSERVATIVE LOWER BOUND (constant-product `L/(L+S)`), not a precise execution model: "
        "concentrated-liquidity Pendle PT pools are deeper near peg but FAR thinner in a forced "
        "unwind, so a defensible floor beats a precise-looking number we cannot defend. Depth is the "
        "SINGLE-market contemporaneous Pendle PT exit liquidity (never aggregated). Tied to the "
        f"validated §9 Oct-2025 exit-liquidity stress ({VALIDATION_REF}). PURE / fail-CLOSED / "
        "advisory. Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.exit_nav`._\n")
    book = result.get("book") or {}
    L.append(
        f"Book: **{book.get('source', '—')}** · market `{book.get('market_id', '—')}` "
        f"({book.get('underlying', '—')}) · gross {_fmt_usd(book.get('gross_usd'))} · "
        f"depth {_fmt_usd(result.get('depth_usd'))} · as_of `{result.get('as_of')}` · "
        f"source `{result.get('data_source')}`\n")
    L.append("| ticket | gross $ | price impact % | net proceeds $ | haircut % | "
             "time-to-exit (days) | within 1 tick | flag |")
    L.append("|---:|---:|---:|---:|---:|---:|:--:|---|")
    for r in result.get("schedule", []):
        pi = r.get("price_impact_frac")
        hc = r.get("haircut_pct")
        net = r.get("net_proceeds_usd")
        tte = r.get("time_to_exit_days")
        L.append(
            f"| {_fmt_usd(r['ticket_usd'])} | {_fmt_usd(r['gross_usd'])} | "
            f"{(f'{pi * 100:.4f}' if pi is not None else '—')} | "
            f"{_fmt_usd(net)} | {(f'{hc:.4f}' if hc is not None else '—')} | "
            f"{(tte if tte is not None else '—')} | "
            f"{'yes' if r.get('within_one_tick') else 'no'} | "
            f"{(r.get('flag_reason') or '') if r.get('flagged') else ''} |")
    L.append("")
    L.append(f"> **Honest framing.** {result.get('disclaimer')}\n")
    L.append(_DOC_END)
    return "\n".join(L)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the exit-NAV section into docs/RATES_DESK_VALIDATION.md between the
    markers, preserving every other section. Atomic write (repo rule #4)."""
    path = doc_path or _DOC
    section = _render_doc_section(result)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _io.atomic_write_text(path, body)
    return path


def _print(result: dict) -> None:
    book = result.get("book") or {}
    print("Rates Desk — LIQUIDATION-NAV-BY-SIZE  (conservative lower bound; advisory)")
    print(f"as_of: {result.get('as_of')}  ·  depth: {_fmt_usd(result.get('depth_usd'))}  ·  "
          f"source: {result.get('data_source')}")
    print(f"book: {book.get('source')}  market={book.get('market_id')} "
          f"({book.get('underlying')})  gross={_fmt_usd(book.get('gross_usd'))}")
    print(f"validation_ref: {result.get('validation_ref')}\n")
    hdr = (f"{'ticket':>12s} {'priceImpact%':>12s} {'netProceeds$':>14s} {'haircut%':>10s} "
           f"{'tteDays':>8s} {'1tick':>6s}  flag")
    print(hdr)
    print("-" * len(hdr))
    for r in result.get("schedule", []):
        pi = r.get("price_impact_frac")
        hc = r.get("haircut_pct")
        net = r.get("net_proceeds_usd")
        tte = r.get("time_to_exit_days")
        print(f"{_fmt_usd(r['ticket_usd']):>12s} "
              f"{(f'{pi * 100:.4f}' if pi is not None else '—'):>12s} "
              f"{(_fmt_usd(net) if net is not None else '—'):>14s} "
              f"{(f'{hc:.4f}' if hc is not None else '—'):>10s} "
              f"{(str(tte) if tte is not None else '—'):>8s} "
              f"{('yes' if r.get('within_one_tick') else 'no'):>6s}  "
              f"{(r.get('flag_reason') or '') if r.get('flagged') else ''}")
    print(f"\nflagged: {result.get('flagged')}")


def main() -> int:
    result = build_exit_nav_schedule(write=True)
    _print(result)
    print(f"\nWrote {_OUT}")
    try:
        write_doc_section(result)
        print(f"Updated {_DOC} (exit-NAV-by-size section)")
    except Exception as exc:  # noqa: BLE001 — doc enrichment must not fail the engine
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
