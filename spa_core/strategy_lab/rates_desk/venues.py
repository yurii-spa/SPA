"""
spa_core/strategy_lab/rates_desk/venues.py — THE VENUE-INDEPENDENCE crux (Lane A, W2: A2.4, the headline).

THE STRATEGIC TRUTH THIS MODULE FORCES INTO THE OPEN
════════════════════════════════════════════════════
The Layer-2 thesis (portfolio.py / books.py) is "scale by COUNT of gated books, NOT by sizing one bigger".
The §9 exit cap binds each book to a thin depth-bound size, so the ONLY way the carry edge reaches the
$10M/yr target is if MANY independent books each add their own deployable. That thesis lives or dies on ONE
question this module refuses to let anyone dodge:

    "Do the books exit through INDEPENDENT venues? Or do they all redeem through the SAME Pendle AMM and the
     SAME stablecoin rail — in which case, under a forced unwind, they COMPETE for one exit and the combined
     capacity does NOT rise with the book count (it PLATEAUS)?"

A sUSDe-26MAR2026 PT and a sUSDe-26SEP2026 PT are DIFFERENT books (different pools, A2.1), but they are BOTH
Pendle AMM markets whose underlying redeems through the SAME sUSDe→USDe→USDC stablecoin rail. They are NOT
independent exits: a stress that drains the USDe redemption queue hits both at once. Naively summing their
deployable OVERSTATES the real combined capacity. The honest model must HAIRCUT the shared-venue overlap so
the combined-capacity-vs-N curve CLIMBS only for genuinely-independent books and PLATEAUS for shared ones.

WHAT THIS COMPUTES (pure, deterministic, fail-CLOSED)
══════════════════════════════════════════════════════
  • `venue_of(book)`           — the book's VenueKey = (amm_family, exit_rail, chain). The addressable
                                 "exit cluster": books sharing a VenueKey compete for the SAME exit liquidity.
  • `shares_exit_venue(book, peers)` — HONEST per-book independence: True iff ANOTHER book shares this book's
                                 VenueKey. A lone book on its own venue is independent (False); one of N books
                                 on a shared Pendle/USDe rail is NOT (True).
  • `combined_capacity_curve(book_rows)` — the crux deliverable: combined deployable vs N books, with the
                                 correlation haircut applied to SHARED-venue books ONLY. Within each venue
                                 cluster the FIRST (deepest) book counts at full deployable; every additional
                                 book in the SAME cluster is haircut by CORRELATION_HAIRCUT_FRAC (it cannot be
                                 assumed to exit alongside its cluster-mates without doubling impact).
                                 Genuinely-independent books (singleton clusters) count at FULL deployable —
                                 the curve climbs for them, plateaus for the shared crowd.

THE HONEST PROPERTY (asserted, never assumed):
  • adding a GENUINELY-INDEPENDENT book NEVER decreases honest combined deployable (it adds its full depth);
  • adding a SHARED-venue book adds only (1 − haircut) of its depth (it cannot double-count one exit);
  • two "different" books that are actually the SAME pool collapse to ~one book under the haircut.

This is the realism Lane B's `shares_exit_venue=True` default approximates conservatively (always haircut).
Lane A emits the per-book TRUTH so the combined-capacity curve is REAL, not flattering — and reports the
honest verdict: at today's universe the books overwhelmingly share the Pendle/USDe rail, so the curve
PLATEAUS and the count-thesis ALONE does not scale to $10M — only cross-venue / cross-chain / cross-protocol
DECORRELATION (A2.2 / A2.3) lifts it.

CONVENTIONS (inherited, enforced): stdlib only; PURE — no clock, no IO, no RNG in the classification/curve;
deterministic — sorted iteration, content-derived keys; fail-CLOSED — a book we cannot classify RAISES
rather than being silently treated as independent (silently-independent is the FLATTERING failure, so it is
forbidden). LLM-FORBIDDEN. Advisory / research — moves no capital, never touches the go-live track.

Run (offline):
    python3 -m spa_core.strategy_lab.rates_desk.venues
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk.books import Book

# ── the correlation haircut on SHARED-venue overlap ──────────────────────────────────────────────────
# Held in LOCK-STEP with strategy_lab.portfolio_capacity.CORRELATION_HAIRCUT_FRAC (the single shared-rail
# non-additivity assumption across the whole stack). The fraction of an ADDITIONAL same-venue book's
# deployable that, under a forced unwind, CANNOT be assumed to exit alongside its cluster-mates without
# doubling exit impact. 0.50 → a second book on a shared rail contributes only HALF its depth; a third
# another half; etc. Conservative + EXPLICIT (the report records the per-book contribution so the
# reduction is auditable). Pinned; widening is a research change.
CORRELATION_HAIRCUT_FRAC = Decimal("0.50")

# ── AMM-family + exit-rail taxonomy (the venue identity) ──────────────────────────────────────────────
# A book's EXIT is characterized by (1) the AMM family it trades on and (2) the stablecoin redemption rail
# its underlying ultimately settles through. Two books that share BOTH (on the same chain) compete for one
# exit. This taxonomy is DOCUMENTED + deterministic — never inferred at runtime from a clock/feed.
#
# AMM family: every Pendle PT market trades on the Pendle AMM (one shared AMM venue). A non-Pendle fixed
# leg (a lending fixed rate, a Boros venue) is a DISTINCT AMM family → an independent exit.
AMM_PENDLE = "pendle_amm"
AMM_LENDING = "lending"          # a money-market fixed/variable leg — redeems by withdrawing supply, not AMM
AMM_BOROS = "boros"              # Pendle Boros funding-rate venue (distinct order book from the PT AMM)

# Exit rail: the stablecoin queue the book's value ultimately redeems through. sUSDe and USDe BOTH settle
# through the Ethena USDe mint/redeem rail (sUSDe just unwraps to USDe first) → SAME rail. A USDC lending
# book redeems through the USDC rail (Circle), a USDS book through Sky's PSM — DISTINCT rails.
_RAIL_BY_UNDERLYING = {
    "susde": "ethena_usde",      # sUSDe unwraps → USDe → Ethena mint/redeem
    "usde": "ethena_usde",       # USDe → Ethena mint/redeem (SAME rail as sUSDe — the honest overlap)
    "usdc": "circle_usdc",       # USDC → Circle
    "usds": "sky_usds",          # USDS → Sky PSM
    "susds": "sky_usds",         # sUSDS unwraps → USDS → Sky PSM (SAME rail as USDS — like sUSDe→usde)
    "gho": "aave_gho",           # GHO → Aave GSM
    "sdai": "maker_dai",         # sDAI → Maker DSR/PSM
    "dai": "maker_dai",
    "usdy": "ondo_usdy",         # Ondo USDY (RWA T-bill) → Ondo redemption
    "ousg": "ondo_ousg",
}


def exit_rail_of(underlying: str) -> str:
    """The stablecoin redemption rail an underlying settles through, fail-CLOSED.

    sUSDe and USDe share the Ethena USDe rail (the honest correlated pair). An underlying we have not mapped
    RAISES — we never silently treat an unknown underlying as its OWN independent rail (that is the
    FLATTERING failure: it would make every unknown book look independent and inflate the curve). Adding a
    new underlying is a deliberate one-line taxonomy edit. PURE / deterministic."""
    u = (underlying or "").strip().lower()
    rail = _RAIL_BY_UNDERLYING.get(u)
    if rail is None:
        raise ValueError(
            f"venues.exit_rail_of: unmapped underlying {underlying!r} — refuse to assume an independent "
            "rail (fail-CLOSED; add it to _RAIL_BY_UNDERLYING deliberately)")
    return rail


@dataclass(frozen=True)
class VenueKey:
    """The addressable EXIT CLUSTER of a book = (amm_family, exit_rail, chain). Books that share a VenueKey
    compete for the SAME exit liquidity under a forced unwind → NOT independent. FROZEN / hashable /
    sortable so cluster grouping is deterministic."""
    amm_family: str
    exit_rail: str
    chain: str

    def as_str(self) -> str:
        return f"{self.amm_family}|{self.exit_rail}|{self.chain}"


def venue_of(book: Book) -> VenueKey:
    """The VenueKey for a Pendle PT Book = (pendle_amm, exit-rail-of-its-underlying, its chain).

    Every PT market trades on the Pendle AMM, so the AMM family is shared across ALL PT books on a chain;
    independence then hinges on the EXIT RAIL (sUSDe/USDe share the Ethena rail) and the CHAIN. fail-CLOSED
    via exit_rail_of (an unmapped underlying RAISES). PURE / deterministic."""
    return VenueKey(amm_family=AMM_PENDLE, exit_rail=exit_rail_of(book.underlying), chain=book.chain)


def venue_key_for(amm_family: str, underlying: str, chain: str) -> VenueKey:
    """VenueKey for a non-PT (cross-market, A2.2) book — a lending fixed leg / Boros venue. The AMM family
    is the DISTINCT venue (lending / boros), so even on a shared stable rail it is a different EXIT than the
    Pendle AMM. fail-CLOSED on an unmapped rail. PURE."""
    return VenueKey(amm_family=amm_family, exit_rail=exit_rail_of(underlying), chain=(chain or "ethereum").lower())


# ── per-book independence over a peer set ─────────────────────────────────────────────────────────────
def cluster_books(book_rows: List[dict]) -> Dict[str, List[dict]]:
    """Group book rows by their VenueKey string. Each row MUST carry 'venue' (the VenueKey.as_str()).
    Returns {venue_str: [rows...]} with rows sorted DESCENDING by deployable (the deepest book first — it
    is the one that counts at full depth in its cluster). Deterministic."""
    clusters: Dict[str, List[dict]] = {}
    for row in book_rows:
        v = row.get("venue")
        if not v:
            raise ValueError(f"venues.cluster_books: row missing 'venue' (fail-CLOSED): {row}")
        clusters.setdefault(v, []).append(row)
    for v in clusters:
        clusters[v].sort(key=lambda r: (-float(r.get("deployable_usd", 0.0)), str(r.get("book_id", ""))))
    return clusters


def annotate_independence(book_rows: List[dict]) -> List[dict]:
    """Return COPIES of `book_rows` with honest independence fields added:
      • shares_exit_venue (bool) — True iff ANOTHER book shares this book's venue cluster,
      • venue_cluster_size (int) — how many books are in its cluster,
      • venue_rank (int)         — 1 = the deepest (full-depth) book in its cluster, 2+ = haircut additions.
    Deterministic; PURE (no mutation of the inputs)."""
    clusters = cluster_books(book_rows)
    out: List[dict] = []
    for v, rows in clusters.items():
        size = len(rows)
        for rank, row in enumerate(rows, start=1):
            r = dict(row)
            r["shares_exit_venue"] = size > 1
            r["venue_cluster_size"] = size
            r["venue_rank"] = rank
            out.append(r)
    # stable global order: by venue, then deepest-first within venue (matches cluster ordering)
    out.sort(key=lambda r: (str(r.get("venue", "")), r.get("venue_rank", 0), str(r.get("book_id", ""))))
    return out


# ── THE combined-capacity-vs-N curve (the crux) ───────────────────────────────────────────────────────
def _honest_contribution(rank: int, deployable: Decimal, haircut_frac: Decimal) -> Decimal:
    """A book's HONEST contribution to combined deployable, given its rank WITHIN its venue cluster.

    rank 1 (the deepest book on a venue) → full deployable (it owns the venue's primary exit).
    rank ≥ 2 (an additional book on the SAME venue) → (1 − haircut)·deployable — it cannot be assumed to
    exit alongside its cluster-mates without doubling impact, so only the un-correlated fraction counts.
    A genuinely-independent book is ALWAYS rank 1 of a singleton cluster → full depth (the curve climbs).
    Deterministic / Decimal-exact / ≥ 0."""
    if rank <= 1:
        return deployable
    frac = Decimal("1") - haircut_frac
    if frac < Decimal("0"):
        frac = Decimal("0")
    return (deployable * frac)


def combined_capacity_curve(
    book_rows: List[dict],
    *,
    haircut_frac: Decimal = CORRELATION_HAIRCUT_FRAC,
) -> dict:
    """THE crux: combined deployable vs N books, haircutting SHARED-venue books only.

    Books are added in a DETERMINISTIC order — by deployable DESCENDING (greedy: the deepest first), ties
    broken by book_id — and each book's honest contribution depends on how many books already added share
    its venue cluster:
      • the FIRST book on a venue contributes its FULL deployable (the curve climbs),
      • each ADDITIONAL book on the SAME venue contributes only (1 − haircut)·deployable (the curve flattens
        toward a plateau — its depth is largely non-additive because it shares the exit),
      • a genuinely-INDEPENDENT book (a new venue) contributes its full deployable (the curve climbs again).

    Returns {curve:[{n, book_id, venue, deployable_usd, independent, contribution_usd, cumulative_usd}],
    naive_sum_usd, honest_combined_usd, n_books, n_venues, n_independent_books, plateau_frac, note}.

    plateau_frac = 1 − honest_combined/naive_sum: the fraction of the naive summed depth the shared-venue
    haircut REMOVES. HIGH plateau_frac (most books share venues) → the count-thesis does NOT scale; LOW
    plateau_frac (books are genuinely independent) → it does. Deterministic / PURE / fail-CLOSED."""
    if not book_rows:
        return {"curve": [], "naive_sum_usd": 0.0, "honest_combined_usd": 0.0, "n_books": 0,
                "n_venues": 0, "n_independent_books": 0, "plateau_frac": 0.0,
                "note": "no books — empty curve."}

    # validate every row carries a venue (fail-CLOSED — a venue-less book would be silently independent)
    for row in book_rows:
        if not row.get("venue"):
            raise ValueError(f"venues.combined_capacity_curve: row missing 'venue' (fail-CLOSED): {row}")

    # deterministic greedy add order: deepest book first, ties by book_id
    ordered = sorted(book_rows, key=lambda r: (-float(r.get("deployable_usd", 0.0)), str(r.get("book_id", ""))))

    seen_per_venue: Dict[str, int] = {}
    cumulative = Decimal("0")
    naive = Decimal("0")
    curve: List[dict] = []
    for n, row in enumerate(ordered, start=1):
        venue = str(row["venue"])
        deployable = Decimal(str(row.get("deployable_usd", 0.0)))
        naive += deployable
        rank = seen_per_venue.get(venue, 0) + 1
        seen_per_venue[venue] = rank
        independent = rank == 1
        contribution = _honest_contribution(rank, deployable, haircut_frac)
        cumulative += contribution
        curve.append({
            "n": n,
            "book_id": row.get("book_id"),
            "venue": venue,
            "deployable_usd": round(float(deployable), 2),
            "independent": independent,          # True = first/only book on its venue (full-depth)
            "contribution_usd": round(float(contribution), 2),
            "cumulative_usd": round(float(cumulative), 2),
        })

    naive_sum = round(float(naive), 2)
    honest_combined = round(float(cumulative), 2)
    n_venues = len(seen_per_venue)
    n_independent = sum(1 for c in curve if c["independent"])
    plateau_frac = round(1.0 - (honest_combined / naive_sum), 6) if naive_sum > 0 else 0.0

    note = _curve_note(n_books=len(curve), n_venues=n_venues, n_independent=n_independent,
                       naive_sum=naive_sum, honest_combined=honest_combined, plateau_frac=plateau_frac,
                       haircut_frac=haircut_frac)
    return {
        "curve": curve,
        "naive_sum_usd": naive_sum,
        "honest_combined_usd": honest_combined,
        "n_books": len(curve),
        "n_venues": n_venues,
        "n_independent_books": n_independent,
        "haircut_frac": float(haircut_frac),
        "plateau_frac": plateau_frac,
        "note": note,
    }


def _curve_note(*, n_books, n_venues, n_independent, naive_sum, honest_combined, plateau_frac,
                haircut_frac) -> str:
    """The HONEST verdict: does adding books raise combined deployable, or do they share venues + plateau?"""
    indep_pct = (n_independent / n_books * 100.0) if n_books else 0.0
    head = (
        f"{n_books} books across {n_venues} venue cluster(s); {n_independent} are genuinely independent "
        f"(first/only on their venue, {indep_pct:.0f}% of books). Naive Σ deployable ${naive_sum:,.0f}; "
        f"HONEST combined (shared-venue books haircut {float(haircut_frac)*100:.0f}%) ${honest_combined:,.0f} "
        f"→ plateau_frac {plateau_frac*100:.1f}% of the naive sum is non-additive.")
    if n_venues <= 1 and n_books > 1:
        verdict = (
            " HONEST VERDICT: ALL books share ONE exit venue (same AMM family + same stablecoin rail + same "
            "chain) — they compete for ONE exit under stress. The combined-capacity curve PLATEAUS: adding "
            "more same-venue maturities does NOT raise real combined deployable. The COUNT-thesis alone does "
            "NOT scale here — only cross-venue / cross-chain / cross-protocol DECORRELATION (A2.2/A2.3) lifts "
            "the curve. At today's universe Layer-2 is capacity-limited by shared exit liquidity; Layer-3 "
            "(more venues) is what actually scales.")
    elif plateau_frac >= 0.4:
        verdict = (
            f" HONEST VERDICT: the books are MOSTLY shared-venue ({plateau_frac*100:.0f}% of naive depth is "
            "non-additive) — the curve largely PLATEAUS. Adding maturities on the same Pendle/stable rail "
            "barely raises combined capacity; the count-thesis is capacity-limited by shared exit liquidity. "
            "Real scaling needs GENUINELY-INDEPENDENT venues (other AMMs/chains/protocols).")
    else:
        verdict = (
            f" HONEST VERDICT: the books are MOSTLY independent ({n_independent}/{n_books} on distinct "
            "venues) — the curve CLIMBS with book count. The count-thesis SCALES here: each independent book "
            "adds (most of) its own deployable because it exits through its own rail.")
    return head + verdict


def main() -> int:
    """Classify the real harvestable book registry, emit per-book independence + the combined-capacity
    curve, and print the HONEST scaling verdict."""
    from spa_core.strategy_lab.rates_desk import books as rd_books
    from spa_core.strategy_lab.rates_desk import portfolio as PORT

    rep = PORT.build_report(write=False)
    # map portfolio fundable books → rows with deployable + venue (PT books only here; cross-market via A2.2)
    deep = None
    try:
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
        deep = pph.load()
    except Exception:  # noqa: BLE001
        pass
    book_by_market = {b.market_key: b for b in rd_books.enumerate_books(deep)}
    rows: List[dict] = []
    for b in rep.get("books", []):
        bk = book_by_market.get(b["market_key"])
        if bk is None:
            continue
        rows.append({
            "book_id": bk.book_id,
            "market_key": bk.market_key,
            "venue": venue_of(bk).as_str(),
            "deployable_usd": b["deployable_usd"],
        })
    annotated = annotate_independence(rows)
    curve = combined_capacity_curve(rows)

    print("Rates Desk — VENUE-INDEPENDENCE + combined-capacity curve  (A2.4, the crux)\n")
    print(f"{'book_id':>19s}  {'venue':>34s}  {'deployable':>12s}  {'indep':>6s}  {'rank':>4s}")
    print("-" * 86)
    for r in annotated:
        print(f"{r['book_id']:>19s}  {r['venue']:>34s}  ${r['deployable_usd']:>10,.0f}  "
              f"{('no' if r['shares_exit_venue'] else 'YES'):>6s}  {r['venue_rank']:>4d}")
    print(f"\nnaive Σ deployable:    ${curve['naive_sum_usd']:,.0f}")
    print(f"HONEST combined:       ${curve['honest_combined_usd']:,.0f}")
    print(f"venues / books:        {curve['n_venues']} venue(s) / {curve['n_books']} books "
          f"({curve['n_independent_books']} independent)")
    print(f"plateau_frac:          {curve['plateau_frac']*100:.1f}% of naive depth is non-additive\n")
    print(curve["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
