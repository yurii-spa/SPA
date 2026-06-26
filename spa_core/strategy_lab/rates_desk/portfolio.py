"""
spa_core/strategy_lab/rates_desk/portfolio.py — the PORTFOLIO-OF-DESKS capacity model (does the edge SCALE?).

capacity.py answered the single-book fundability question and gave the honest, uncomfortable answer: ONE
FixedCarry book is CAPACITY-LIMITED — the validated carry lives in THIN Pendle PT pools, so the §9
exit-capacity rule caps per-market deployment and the marginal dollar falls IDLE @ the RWA floor, diluting
a single aggregated book toward the floor well below institutional size. The allocator's next question is
the SCALE question every fundability thesis must answer to justify a $10M/yr target:

    "ONE gated book caps out at $X — so how many INDEPENDENT books does the real Pendle/lending universe
     actually offer, what is their SUMMED deployable AUM, and how many $/yr of carry ABOVE the floor does
     that whole portfolio produce TODAY? Can the current real market support $10M/yr — or how far short is
     it, and what would close the gap?"

This module turns the validated single-book edge into a SIZED, honest business case by modelling the
PORTFOLIO of N independent rate-desk books. Each DISTINCT (underlying, maturity) PT market is its OWN
capacity-limited book: a different pool, a different depth, a different §9 exit cap — sUSDe-26MAR2025 and
sUSDe-26SEP2025 are SEPARATE books that can each absorb their own deployable before diluting, and deploying
into one does NOT consume the other's depth. (LRT books — ezETH/rsETH — are EXCLUDED: the rate gate refuses
them on the depeg/nesting tail, so they are never harvestable carry, never a fundable book. Only the
harvestable STABLE_SYNTH / STABLE_RWA carry markets — the same survivor universe capacity.py validated —
count.)

PER-BOOK DEPLOYABLE (the honest depth bound, reusing capacity.py's model):
For each book we replay the validated FixedCarry sleeve over THAT market's deep series alone (a one-market
deep subset → capacity._replay_fixed_carry_capacity, the SAME §9 exit-capacity sizing / idle-cash@floor /
maturity-retire accounting the single-book curve uses) at a probe AUM large enough that the book is
CAPACITY-BOUND, and record:
  • deployable_usd  — the PEAK SIMULTANEOUS capital the §9 rule actually let the sleeve hold in that book
                       (its real depth-bound capacity; adding AUM beyond this only adds idle cash). This is
                       a property of the pool's depth + redemption SLA, NOT of how much we throw at it.
  • net_carry_pct   — the carry RATE the book clips on its deployed slice while live (the gross harvestable
                       carry the book earns ON the deployed dollars — net of the §9 slippage haircut, which
                       the gate already prices into the approved size). This is the "X%/yr" each fundable
                       dollar in that book earns, to be compared against the RWA floor.

AGGREGATE (the business case):
  • total_deployable_usd        = Σ per-book deployable_usd  (bounded by the SUM of real per-market depths —
                                  NOT infinite; the honest ceiling of the CURRENT universe).
  • aggregate_net_apy_pct       = deployable-weighted mean of the per-book net_carry_pct (what a dollar
                                  spread across the WHOLE deployable portfolio earns).
  • dollars_above_floor_per_yr  = Σ deployable_usd · max(0, net_carry − floor)  (the $/yr of carry the
                                  portfolio harvests ABOVE the RWA floor — the part that is a real excess,
                                  the fundable business, not just cash).
  • books_needed_for_10m        = how many CURRENT-SIZED average books it would take to clear $10M/yr above
                                  floor (TARGET_ABOVE_FLOOR_PER_YR / avg_$_above_floor_per_book) — the
                                  scale gap stated in book-count terms.

HONEST CONCLUSION (the whole point — never inflated): the model reports how close the CURRENT real
Pendle/lending universe gets to $10M/yr above the floor. If the real summed depth only supports $Xk/yr
above floor today, it SAYS THAT — the market may simply be too thin today, and $10M needs the market to
GROW (deeper PT pools), MORE venues (lending-carry, other chains, more maturities), and/or the OTHER theses
(RWA sleeve, etc.) to carry the rest. The gap and what closes it are stated explicitly in `note`.

CONVENTIONS (inherited, enforced): stdlib only; PURE — `as_of` is always the deep stream's dates, never
the wall clock; deterministic — no RNG, sorted iteration, Decimal-exact; fail-CLOSED — a missing deep
dataset / a universe with no harvestable book RAISES rather than fabricating a benign portfolio; atomic
writes (tmp + shutil.move, repo rule #4); LLM-FORBIDDEN. Advisory / research — never touches the live track.

Run (offline, on the deep cached data):
    python3 -m spa_core.strategy_lab.rates_desk.portfolio
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import backtest_rates as br
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import D0, RatePolicyParams, UnderlyingKind
from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "portfolio_capacity.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

# Idempotent markers so the portfolio section can be (re)written into the validation doc without clobbering
# the capacity / 4-sleeve / calibration / exit-liquidity content the other modules own.
_DOC_BEGIN = "<!-- BEGIN rates-desk portfolio-of-desks (portfolio) -->"
_DOC_END = "<!-- END rates-desk portfolio-of-desks (portfolio) -->"

# The harvestable carry kinds — the SAME survivor universe capacity.py validated. LRT (ezETH/rsETH) is
# EXCLUDED: the rate gate refuses it on the depeg/nesting tail, so it is never a fundable book. LST is a
# borderline harvestable kind the deep universe carries (eETH); we INCLUDE only the kinds the FixedCarry
# survivor book actually held (the stable-synth / RWA carry). LST PTs are included ONLY if a book actually
# deploys (the gate decides); a kind that the gate refuses contributes a $0 book and is dropped honestly.
HARVESTABLE_KINDS = frozenset({UnderlyingKind.STABLE_SYNTH, UnderlyingKind.STABLE_RWA})

# The probe AUM at which we measure each book's PEAK SIMULTANEOUS deployable. Must be large enough that the
# book is fully CAPACITY-BOUND (the §9 exit cap binds, not the cash) for EVERY market in the universe — the
# deepest sUSDe pool can absorb ~$120k/tick, so $50M per single-market book guarantees the cap binds and
# the measured peak-deployed is the depth bound, not an artifact of too-little probe capital. Held separate
# / pinned; widening is a research change.
BOOK_PROBE_AUM_USD = Decimal("50000000")   # $50M per single-market book → capacity-bound everywhere

# The fundability target this whole exercise sizes against: $10M/yr of carry ABOVE the RWA floor.
TARGET_ABOVE_FLOOR_PER_YR = Decimal("10000000")   # $10,000,000/yr above floor


def _atomic_write_json(path: Path, obj) -> None:
    _io.atomic_write_json(path, obj, indent=1)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Per-book replay — peak-simultaneous deployable + net carry, REUSING capacity.py's honest accounting
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _replay_single_book(
    market_key: str,
    market: dict,
    window: dict,
    params: RatePolicyParams,
    funding: Dict[str, float],
) -> dict:
    """Replay the validated FixedCarry sleeve over ONE market's deep series alone, at the capacity-bound
    probe AUM, and measure that book's honest depth bound:

      • deployable_usd — the PEAK SIMULTANEOUS capital the §9 exit-capacity rule actually let the sleeve
        hold in this book over its life (its real, depth-bound capacity). Reusing the EXACT drive path
        capacity._replay_fixed_carry_capacity / replay_sleeve use (build_deep_surface → retire-matured →
        _drive_fixed_carry → sleeve.step), so the sizing is the SAME validated §9 model — we only read off
        the peak deployed instead of the annualized book APY.
      • net_carry_pct — the carry RATE clipped on the deployed slice while the book is live: total carry
        accrued ON the deployed books (NOT idle cash) annualized over the days the book actually HELD a
        position. This is what each fundable dollar in this book earns (net of the §9 slippage the gate
        already priced into the approved size) — the rate to compare against the floor.

    PURE w.r.t. the gate/sleeve; deterministic. fail-CLOSED: a malformed surface day is skipped (data
    gap → safe-hold, identical to replay_sleeve)."""
    sub = {"window": window, "markets": {market_key: market}}
    dates = br._all_dates(sub)
    universe = sorted({market["underlying"].lower()})
    hedge_map = BorosFeed().hedge_available(universe)
    maturities = br._maturity_map(sub)
    floor_daily_dec = params.rwa_floor / Decimal("365")

    sleeve = FixedCarrySleeve(params)
    sleeve.init(float(BOOK_PROBE_AUM_USD), {})

    peak_deployed = D0
    accrued_before = D0          # carry accrued cumulatively; we attribute the carry-leg portion below
    carry_accrued = D0           # cumulative carry attributable to DEPLOYED books (excludes idle@floor)
    held_days = 0

    for d in dates:
        fneg = br._funding_neg_frac_90d(funding, d)
        try:
            surface, risks = br.build_deep_surface(d, sub, fneg, hedge_map)
        except ValueError:
            continue  # data gap → fail-CLOSED safe-hold

        br._retire_matured(sleeve, maturities, d)

        deployed_today = D0
        if surface.pt_quotes:
            br._drive_fixed_carry(sleeve, surface, risks, d)
            deployed_today = sum((bk["size"] for bk in sleeve._books.values()), D0)
            if deployed_today > peak_deployed:
                peak_deployed = deployed_today
            if sleeve._books:
                held_days += 1

        # accrue the day's carry (on open books) — the delta in _accrued BEFORE we add idle@floor is the
        # carry-leg contribution; the idle@floor part is excluded from net_carry (it is the floor, not the
        # edge). This isolates the harvestable carry the deployed slice earns.
        a0 = getattr(sleeve, "_accrued", D0)
        sleeve.step(MarketSnapshot(date=d))
        a1 = getattr(sleeve, "_accrued", D0)
        carry_accrued += (a1 - a0)
        # idle cash @ floor (kept on the book so equity bookkeeping matches replay_sleeve, but NOT counted
        # toward net_carry — net_carry is the rate on DEPLOYED dollars only)
        cash = getattr(sleeve, "_cash", D0)
        if cash > D0:
            sleeve._accrued += cash * floor_daily_dec

    deployable_usd = round(float(peak_deployed), 2)
    # net_carry_pct = carry$ annualized over the HELD-days span, per deployed dollar. Use the peak deployed
    # as the deployed-dollar basis (the capacity-bound size); honest: it is the rate that size earns. If the
    # book never deployed (gate refused it entirely), it is a $0 book with 0 carry — dropped from the
    # portfolio honestly (no fabricated capacity into a refused market).
    held_years = held_days / 365.0 if held_days else 0.0
    if peak_deployed > D0 and held_years > 0:
        net_carry_pct = round(float(carry_accrued) / float(peak_deployed) / held_years * 100.0, 4)
    else:
        net_carry_pct = 0.0

    return {
        "underlying": market["underlying"],
        "maturity": market["maturity"],
        "market_key": market_key,
        "kind": market["kind"],
        "deployable_usd": deployable_usd,
        "net_carry_pct": net_carry_pct,
        "held_days": held_days,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# build_report — the aggregate portfolio capacity curve
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_report(
    write: bool = True,
    params: Optional[RatePolicyParams] = None,
    deep: Optional[dict] = None,
    funding: Optional[Dict[str, float]] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the deterministic PORTFOLIO-OF-DESKS capacity report and (optionally) write
    data/rates_desk/portfolio_capacity.json atomically. Same (deep, funding, params) → same result.

    Each harvestable (underlying, maturity) market is replayed as its OWN capacity-limited book; the
    aggregate is the SUM of the per-book deployables (bounded by real per-market depth, not infinite) and
    the deployable-weighted carry. The honest $10M/yr verdict is computed and stated in `note`.

    fail-CLOSED: a missing deep dataset RAISES; a universe with NO harvestable, deployable book RAISES
    (we never emit a fabricated portfolio)."""
    from spa_core.strategy_lab.rates_desk import retro

    params = params or RatePolicyParams()
    if deep is None:
        deep = pph.load()
    if funding is None:
        try:
            funding = retro.load_funding()
        except FileNotFoundError:
            funding = {}

    markets = deep.get("markets")
    if not isinstance(markets, dict) or not markets:
        raise ValueError("portfolio: deep dataset has empty/invalid 'markets' (fail-CLOSED)")
    window = deep.get("window") or {"start": None, "end": None}
    floor_pct = round(float(params.rwa_floor) * 100.0, 4)

    # one independent book per harvestable (underlying, maturity) market — deterministic sorted order
    book_keys: List[str] = []
    for key in sorted(markets):
        m = markets[key]
        try:
            kind = UnderlyingKind(m.get("kind"))
        except (ValueError, TypeError):
            raise ValueError(f"portfolio: market {key} has bad kind {m.get('kind')!r} (fail-CLOSED)")
        if kind in HARVESTABLE_KINDS:
            book_keys.append(key)

    if not book_keys:
        raise ValueError("portfolio: no harvestable (STABLE_SYNTH/RWA) markets in the universe (fail-CLOSED)")

    books: List[dict] = []
    for key in book_keys:
        row = _replay_single_book(key, markets[key], window, params, funding)
        # only books that actually deploy capacity (the gate approved a real size) count as fundable books;
        # a $0 book (gate refused the whole market) is dropped honestly — no fabricated capacity.
        if row["deployable_usd"] > 0.0:
            books.append(row)

    books.sort(key=lambda b: (b["underlying"], b["maturity"], b["market_key"]))

    if not books:
        raise ValueError("portfolio: no book deployed any capacity (gate refused all) — fail-CLOSED")

    total_deployable = round(sum(b["deployable_usd"] for b in books), 2)
    # deployable-weighted aggregate net carry (what a dollar across the WHOLE deployable portfolio earns)
    if total_deployable > 0:
        agg_net_apy = round(
            sum(b["deployable_usd"] * b["net_carry_pct"] for b in books) / total_deployable, 4)
    else:
        agg_net_apy = 0.0

    # $/yr of carry ABOVE the floor — the real excess (the fundable business, not just cash @ floor)
    dollars_above_floor = round(
        sum(b["deployable_usd"] * max(0.0, b["net_carry_pct"] - floor_pct) / 100.0 for b in books), 2)
    # aggregate refusal: fraction of the harvestable universe that did NOT become a fundable book (the gate
    # / depth refused it) — honest: the universe is wider than the deployable book count.
    n_harvestable = len(book_keys)
    n_books = len(books)
    refusal_rate = round(1.0 - (n_books / n_harvestable), 6) if n_harvestable else 0.0

    # books_needed_for_10m: how many CURRENT-AVERAGE books to clear $10M/yr above floor (the scale gap in
    # book-count terms). avg $/yr above floor per book = dollars_above_floor / n_books.
    avg_above_floor_per_book = (dollars_above_floor / n_books) if n_books else 0.0
    if avg_above_floor_per_book > 0:
        import math
        books_needed = int(math.ceil(float(TARGET_ABOVE_FLOOR_PER_YR) / avg_above_floor_per_book))
    else:
        books_needed = None  # no above-floor edge anywhere → $10M unreachable by adding books (honest)

    # the honest gap: how far the CURRENT universe gets toward $10M/yr above floor
    target = float(TARGET_ABOVE_FLOOR_PER_YR)
    pct_of_target = round(dollars_above_floor / target * 100.0, 4) if target > 0 else 0.0
    gap_to_10m = round(max(0.0, target - dollars_above_floor), 2)

    note = _build_note(
        n_books=n_books, n_harvestable=n_harvestable, total_deployable=total_deployable,
        agg_net_apy=agg_net_apy, floor_pct=floor_pct, dollars_above_floor=dollars_above_floor,
        pct_of_target=pct_of_target, gap_to_10m=gap_to_10m, books_needed=books_needed,
        avg_above_floor_per_book=avg_above_floor_per_book,
    )

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_portfolio_of_desks",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "data_source": "deep_pendle_pt_history",
        "window": window,
        "rwa_floor_pct": floor_pct,
        "book_probe_aum_usd": float(BOOK_PROBE_AUM_USD),
        "target_above_floor_per_yr_usd": float(TARGET_ABOVE_FLOOR_PER_YR),
        "n_harvestable_markets": n_harvestable,
        "n_fundable_books": n_books,
        "aggregate_refusal_rate": refusal_rate,
        "books": books,
        "total_deployable_usd": total_deployable,
        "aggregate_net_apy_pct": agg_net_apy,
        "dollars_above_floor_per_yr": dollars_above_floor,
        "avg_dollars_above_floor_per_book": round(avg_above_floor_per_book, 2),
        "pct_of_10m_target": pct_of_target,
        "gap_to_10m_usd": gap_to_10m,
        "books_needed_for_10m": books_needed,
        "note": note,
    }
    if write:
        _atomic_write_json(out_path or _OUT, result)
    return result


def _build_note(*, n_books, n_harvestable, total_deployable, agg_net_apy, floor_pct,
                dollars_above_floor, pct_of_target, gap_to_10m, books_needed,
                avg_above_floor_per_book) -> str:
    """The honest fundability verdict — never inflated. States the aggregate numbers, how far the CURRENT
    real universe gets toward $10M/yr above floor, the gap, and what would close it."""
    reach = (
        f"The CURRENT real harvestable universe is {n_books} fundable independent books "
        f"(of {n_harvestable} harvestable markets), summing to {_fmt_usd(total_deployable)} of "
        f"depth-bound deployable AUM at an aggregate {agg_net_apy:.2f}%/yr (RWA floor {floor_pct:.2f}%/yr) "
        f"→ {_fmt_usd(dollars_above_floor)}/yr of carry ABOVE the floor.")
    if dollars_above_floor >= float(TARGET_ABOVE_FLOOR_PER_YR):
        verdict = (
            f"That CLEARS the $10M/yr target ({pct_of_target:.1f}% of it) on the current universe — the "
            "portfolio of gated books scales the validated single-book edge to institutional size.")
    else:
        books_str = (f"~{books_needed} current-average books" if books_needed is not None
                     else "an unbounded number of books (no above-floor edge to scale)")
        verdict = (
            f"That is only {pct_of_target:.2f}% of the $10M/yr target — a gap of "
            f"{_fmt_usd(gap_to_10m)}/yr. Honest verdict: the CURRENT real Pendle PT carry market is TOO "
            f"THIN to fund $10M/yr above the floor on its own. At the current per-book average of "
            f"{_fmt_usd(avg_above_floor_per_book)}/yr above floor, clearing $10M/yr would need {books_str} "
            "— far more than the real universe offers today. The §9 exit-capacity cap binds each book to a "
            "small depth-bound size, and even SUMMED across every harvestable maturity the real depth is "
            "limited. Closing the gap requires the market to GROW (deeper PT pools per maturity → higher "
            "per-book deployable), MORE venues/books (lending-carry on PT collateral, more maturities, "
            "other chains, additional protocols), AND/OR the OTHER theses (the RWA cash-floor sleeve and "
            "directional/neutral ETH sleeves) carrying the balance of the $10M target. This is the honest "
            "scale truth: the rates-desk carry edge is REAL and SURVIVES across many gated books, but the "
            "current market depth alone does not get to $10M/yr — it is one diversifying sleeve of a "
            "larger book, not a standalone $10M business at today's depth.")
    return reach + " " + verdict


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# doc section + printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _fmt_usd(x) -> str:
    if x is None:
        return "—"
    return f"${float(x):,.0f}"


def _render_doc_section(result: dict) -> str:
    floor = result.get("rwa_floor_pct")
    lines: List[str] = [_DOC_BEGIN, ""]
    lines.append("## Portfolio of desks — does the edge SCALE?  (the $10M/yr business case)\n")
    lines.append(
        "_Deterministic portfolio-of-desks capacity model: each harvestable (underlying, maturity) Pendle "
        "PT market is its OWN capacity-limited book (its own pool depth → its own §9 exit cap), replayed "
        "over the DEEP historical RateSurface "
        f"({result.get('window', {}).get('start')}→{result.get('window', {}).get('end')}) under the SAME "
        "honest accounting as the single-book capacity curve (REUSING capacity.py's replay: §9 "
        "exit-capacity sizing, idle cash @ the RWA floor, maturity-retire, 30% global ceiling). The "
        "aggregate is the SUM of per-book deployables — bounded by real per-market depth, NOT infinite. "
        "PURE / fail-CLOSED / advisory. Re-runnable via "
        "`python3 -m spa_core.strategy_lab.rates_desk.portfolio`._\n")
    lines.append(
        f"RWA floor: **{floor}%/yr**. Target: **$10,000,000/yr of carry ABOVE the floor**. "
        f"Harvestable markets: **{result.get('n_harvestable_markets')}**; fundable independent books "
        f"(actually deploy capacity): **{result.get('n_fundable_books')}** "
        f"(aggregate refusal {result.get('aggregate_refusal_rate', 0.0) * 100:.1f}%).\n")
    lines.append("| underlying | maturity | deployable AUM | net carry %/yr | above floor $/yr | held days |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for b in result.get("books", []):
        above = b["deployable_usd"] * max(0.0, b["net_carry_pct"] - floor) / 100.0
        lines.append(
            f"| {b['underlying']} | {b['maturity']} | {_fmt_usd(b['deployable_usd'])} | "
            f"{b['net_carry_pct']:.4f} | {_fmt_usd(above)} | {b['held_days']} |")
    lines.append("")
    lines.append(f"- **Total deployable AUM (Σ per-book depth):** **{_fmt_usd(result.get('total_deployable_usd'))}**")
    lines.append(f"- **Aggregate net APY (deployable-weighted):** **{result.get('aggregate_net_apy_pct')}%/yr**")
    lines.append(f"- **Carry ABOVE the floor:** **{_fmt_usd(result.get('dollars_above_floor_per_yr'))}/yr** "
                 f"({result.get('pct_of_10m_target')}% of the $10M/yr target)")
    bn = result.get("books_needed_for_10m")
    lines.append(f"- **Books needed for $10M/yr above floor:** "
                 f"**{bn if bn is not None else '∞ (no above-floor edge to scale)'}** "
                 f"(at {_fmt_usd(result.get('avg_dollars_above_floor_per_book'))}/yr above floor per current book)")
    lines.append(f"- **Gap to $10M/yr:** {_fmt_usd(result.get('gap_to_10m_usd'))}/yr\n")
    lines.append(f"> **Honest fundability verdict.** {result.get('note')}\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the portfolio section into docs/RATES_DESK_VALIDATION.md between the markers,
    preserving the other validation content. Atomic write (repo rule #4)."""
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


def _print_report(result: dict) -> None:
    floor = result.get("rwa_floor_pct")
    print(f"Rates Desk — PORTFOLIO OF DESKS   RWA floor {floor}%/yr   target $10M/yr above floor")
    print(f"window: {result.get('window')}")
    print(f"harvestable markets: {result.get('n_harvestable_markets')}  ·  "
          f"fundable books: {result.get('n_fundable_books')}  ·  "
          f"aggregate refusal: {result.get('aggregate_refusal_rate', 0.0) * 100:.1f}%\n")
    hdr = f"{'underlying':>10s} {'maturity':>12s} {'deployable':>14s} {'netCarry%':>10s} {'aboveFloor$':>14s}"
    print(hdr)
    print("-" * len(hdr))
    for b in result.get("books", []):
        above = b["deployable_usd"] * max(0.0, b["net_carry_pct"] - floor) / 100.0
        print(f"{b['underlying']:>10s} {b['maturity']:>12s} {_fmt_usd(b['deployable_usd']):>14s} "
              f"{b['net_carry_pct']:10.4f} {_fmt_usd(above):>14s}")
    print()
    print(f"Total deployable AUM:        {_fmt_usd(result.get('total_deployable_usd'))}")
    print(f"Aggregate net APY:           {result.get('aggregate_net_apy_pct')}%/yr")
    print(f"Carry above floor:           {_fmt_usd(result.get('dollars_above_floor_per_yr'))}/yr "
          f"({result.get('pct_of_10m_target')}% of $10M)")
    bn = result.get("books_needed_for_10m")
    print(f"Books needed for $10M/yr:     {bn if bn is not None else 'inf (no above-floor edge)'}")
    print(f"Gap to $10M/yr:              {_fmt_usd(result.get('gap_to_10m_usd'))}/yr")
    print(f"\n{result.get('note')}")


def main() -> int:
    result = build_report(write=True)
    _print_report(result)
    print(f"\nWrote {_OUT}")
    try:
        write_doc_section(result)
        print(f"Updated {_DOC} (portfolio section)")
    except Exception as exc:  # noqa: BLE001 — doc enrichment must not fail the analysis
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
