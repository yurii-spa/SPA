"""
spa_core/strategy_lab/rates_desk/venue_expansion.py — cross-MARKET (A2.2) + cross-CHAIN (A2.3) book
enumeration: the GENUINELY-INDEPENDENT venues that lift the venue-independence curve (Lane A, W2).

WHY THIS EXISTS (the honest reading of A2.4)
═════════════════════════════════════════════
venues.py proved the headline: the CURRENT fundable universe is 22 books that ALL share ONE exit venue
(Pendle AMM + Ethena USDe rail + Ethereum), so the combined-capacity curve PLATEAUS — adding more sUSDe/USDe
maturities barely raises real combined deployable. The count-thesis (Layer-2) does NOT scale on the current
universe; only GENUINELY-INDEPENDENT venues do (Layer-3). This module enumerates exactly those candidate
independent venues so the curve can be shown to CLIMB when (and only when) the books exit through distinct
rails:

  • A2.2 CROSS-MARKET — qualifying NON-Pendle fixed-rate carry venues (a money-market fixed leg, a Boros
    permissionless venue). A lending fixed leg exits by withdrawing supply (the LENDING AMM family), NOT
    through the Pendle PT AMM → an INDEPENDENT exit even when its underlying shares a stablecoin rail. Each
    is a candidate gated book: it must pass the same refusal honesty (LRT excluded; only harvestable
    STABLE_SYNTH / STABLE_RWA kinds) or it is honestly refused.

  • A2.3 CROSS-CHAIN — the SAME stable-synth markets on Arbitrum / Base / OP as DISTINCT books (distinct pool
    depth, distinct exit liquidity). The chain is in the book_id and the VenueKey, so an Arbitrum sUSDe book
    is a DIFFERENT exit cluster than the Ethereum one. Behind the flag SPA_RATES_MULTICHAIN (default OFF for
    LIVE, ON for MEASUREMENT) per the brief.

THE HONESTY BAR (non-negotiable, stated up front)
══════════════════════════════════════════════════
These are MEASUREMENT CANDIDATES, not live carry. The deployable depth credited to each candidate venue is a
DETERMINISTIC, DOCUMENTED, CONSERVATIVE model (a fraction of a pinned reference depth) — NOT a fabricated
live rate and NOT the validated §9 replay (which only the live Pendle PT books in portfolio.py earn). Every
candidate book is `is_advisory=True` / `candidate=True` / `live=False`; it moves no capital and never enters
the live carry track. The point is to answer the SCALE question HONESTLY: "IF these independent venues are
real and gated, how high does the combined-capacity curve climb, and is THAT enough for $10M?" — not to
pretend the desk already trades them. The flag keeps the multichain set OUT of any live path by default.

NO LRT / NO TAIL-COMP SLIPS IN: candidate underlyings are filtered to the harvestable stable kinds exactly
like books.enumerate_books; an LRT candidate is refused (excluded) and recorded as such — the refusal IS the
edge, even for candidate venues.

CONVENTIONS (inherited, enforced): stdlib only; PURE — no clock, no network, no RNG (the candidate set is a
documented static enumeration + the live registry); deterministic — sorted, content-derived ids; fail-CLOSED
— an unmapped exit rail RAISES (never a silently-independent candidate); the flag is read per-call. LLM-
FORBIDDEN. Advisory / research / candidate — never live, never the go-live track.

Run (offline):
    python3 -m spa_core.strategy_lab.rates_desk.venue_expansion                 # live-default (flag OFF)
    SPA_RATES_MULTICHAIN=1 python3 -m spa_core.strategy_lab.rates_desk.venue_expansion   # measurement
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
from decimal import Decimal
from typing import Dict, List, Optional

from spa_core.strategy_lab.rates_desk import books as rd_books
from spa_core.strategy_lab.rates_desk import config as rd_config
from spa_core.strategy_lab.rates_desk import venues as V
from spa_core.strategy_lab.rates_desk.books import make_book_id

# ── the multichain flag (A2.3): default OFF for LIVE, ON for MEASUREMENT ──────────────────────────────
MULTICHAIN_FLAG_ENV = "SPA_RATES_MULTICHAIN"


def multichain_enabled() -> bool:
    """True iff SPA_RATES_MULTICHAIN is set ON. DEFAULT OFF (unset/'0'/''/false → False). Read per-call so
    an owner toggling the env takes effect without a reimport (mirrors rate_floor_recal.flag_enabled)."""
    return os.environ.get(MULTICHAIN_FLAG_ENV, "0") not in ("0", "", "false", "False", "off", "OFF")


# ── candidate cross-chain venues (A2.3) ───────────────────────────────────────────────────────────────
# The L2s where the deep keyless yields/pools surface carries the same stable-synth PT markets at REAL,
# distinct pool depth. DOCUMENTED static set (no clock/feed); each is a DISTINCT exit cluster (distinct
# chain in the VenueKey). Conservative depth = a fraction of the Ethereum book's depth (an L2 PT pool is
# shallower than mainnet) — a deliberately small, pinned MEASUREMENT credit, never a live rate.
_CROSS_CHAINS = ("arbitrum", "base", "optimism")

# An L2 sUSDe/USDe PT pool is materially shallower than the mainnet pool. We credit a conservative fraction
# of the mainnet per-book deployable as the candidate L2 deployable — pinned + documented (widening is a
# research change). This is a MEASUREMENT projection of independent depth, not a §9-replayed live number.
_L2_DEPTH_FRAC_OF_MAINNET = Decimal("0.25")   # an L2 book ≈ 25% of its mainnet sibling's deployable (conservative)

# ── candidate cross-market venues (A2.2) ──────────────────────────────────────────────────────────────
# Non-Pendle fixed-rate carry venues whose EXIT is a DISTINCT AMM family (lending withdraw / Boros book),
# so they are independent of the Pendle PT AMM even on a shared stable rail. DOCUMENTED static set derived
# from the harvestable LENDING_TARGETS (USDC/USDS/GHO money markets) — the SAME selectors the live lending
# surface uses (config.LENDING_TARGETS), so the candidate set never invents a venue the desk does not track.
# Conservative deployable = a fraction of a pinned reference lending depth (a money market is deep but the
# fixed-leg carry depth an underwriter can take is a small, gated slice). MEASUREMENT, not live carry.
_LENDING_REFERENCE_DEPTH_USD = Decimal("8000000")   # pinned reference money-market fixed-leg pool depth
_LENDING_DEPLOYABLE_FRAC = Decimal("0.02")          # gated underwriter slice (2% of reference depth)


def _harvestable_lending_selectors() -> List[dict]:
    """The LENDING_TARGETS selectors whose kind is harvestable (STABLE_SYNTH / STABLE_RWA) — an LRT/tail
    underlying would be refused (none exist in LENDING_TARGETS today, but the filter is the guarantee).
    Deterministic sorted by (project, chain, underlying)."""
    out = []
    for sel in rd_config.LENDING_TARGETS:
        try:
            kind = rd_config.underlying_kind(str(sel["underlying"]))
        except ValueError:
            continue  # unknown underlying → refused (fail-CLOSED, never a silent candidate)
        if kind in rd_books.HARVESTABLE_KINDS:
            out.append(sel)
    out.sort(key=lambda s: (str(s["project"]), str(s["chain"]), str(s["underlying"])))
    return out


def cross_market_candidates() -> List[dict]:
    """A2.2: candidate NON-Pendle fixed-rate carry books (lending fixed legs). Each is an INDEPENDENT exit
    (LENDING AMM family ≠ Pendle PT AMM). Deterministic; fail-CLOSED on an unmapped rail. Returns rows
    shaped for the venue model: {book_id, label, venue, deployable_usd, kind, family, candidate, live}."""
    rows: List[dict] = []
    for sel in _harvestable_lending_selectors():
        underlying = str(sel["underlying"]).lower()
        chain = str(sel["chain"]).lower()
        project = str(sel["project"])
        # a lending fixed leg has no maturity; its identity is (project, underlying, chain) — distinct AMM
        label = f"LEND-{project}-{underlying}-{chain}"
        book_id = make_book_id(f"lend:{project}:{underlying}", "perp", chain)
        venue = V.venue_key_for(V.AMM_LENDING, underlying, chain).as_str()
        deployable = (_LENDING_REFERENCE_DEPTH_USD * _LENDING_DEPLOYABLE_FRAC).quantize(Decimal("0.01"))
        rows.append({
            "book_id": book_id, "label": label, "venue": venue,
            "deployable_usd": round(float(deployable), 2),
            "kind": rd_config.underlying_kind(underlying).value,
            "family": V.AMM_LENDING, "candidate": True, "live": False,
        })
    rows.sort(key=lambda r: (str(r["venue"]), str(r["book_id"])))
    return rows


def cross_chain_candidates(
    live_book_rows: List[dict],
    *,
    enabled: Optional[bool] = None,
) -> List[dict]:
    """A2.3: the SAME stable-synth markets on the cross-chains as DISTINCT candidate books (distinct depth,
    distinct VenueKey via the chain). Behind SPA_RATES_MULTICHAIN — returns [] when the flag is OFF (the
    default LIVE posture). `live_book_rows` are the Ethereum fundable PT rows (each carries deployable_usd +
    underlying); each becomes a conservative-depth candidate on every cross-chain. Deterministic."""
    on = multichain_enabled() if enabled is None else enabled
    if not on:
        return []
    rows: List[dict] = []
    for base in live_book_rows:
        underlying = str(base.get("underlying") or "").lower()
        maturity = str(base.get("maturity") or "")
        base_dep = Decimal(str(base.get("deployable_usd", 0.0)))
        if base_dep <= 0 or not underlying or not maturity:
            continue
        try:
            V.exit_rail_of(underlying)  # fail-CLOSED: an unmapped rail RAISES rather than silent-independent
        except ValueError:
            continue
        for chain in _CROSS_CHAINS:
            dep = (base_dep * _L2_DEPTH_FRAC_OF_MAINNET).quantize(Decimal("0.01"))
            if dep <= 0:
                continue
            book_id = make_book_id(underlying, maturity, chain)
            venue = V.VenueKey(amm_family=V.AMM_PENDLE, exit_rail=V.exit_rail_of(underlying),
                               chain=chain).as_str()
            rows.append({
                "book_id": book_id, "label": f"PT-{underlying}-{maturity}-{chain}",
                "venue": venue, "deployable_usd": round(float(dep), 2),
                "kind": str(base.get("kind") or "stable_synth"),
                "family": V.AMM_PENDLE, "candidate": True, "live": False, "chain": chain,
            })
    rows.sort(key=lambda r: (str(r["venue"]), str(r["book_id"])))
    return rows


# ── the expanded venue set (live ∪ candidates) + the climbing curve ───────────────────────────────────
def build_expanded_rows(
    *,
    enabled: Optional[bool] = None,
    deep: Optional[dict] = None,
    rates_report: Optional[dict] = None,
) -> dict:
    """Assemble the FULL venue-set rows: the LIVE Pendle PT fundable books (full §9 deployable, the only
    LIVE carry) ∪ the A2.2 cross-market candidates ∪ the A2.3 cross-chain candidates (behind the flag).

    Returns {live_rows, candidate_rows, all_rows, multichain_enabled}. Each row carries venue + deployable.
    LIVE rows are `live=True`; candidates `candidate=True/live=False`. Deterministic / fail-CLOSED."""
    from spa_core.strategy_lab.rates_desk import portfolio as PORT

    on = multichain_enabled() if enabled is None else enabled
    if rates_report is None:
        rates_report = PORT.build_report(write=False, deep=deep)
    if deep is None:
        try:
            from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
            deep = pph.load()
        except Exception:  # noqa: BLE001
            deep = None
    book_by_market = {b.market_key: b for b in rd_books.enumerate_books(deep)}

    live_rows: List[dict] = []
    for b in rates_report.get("books", []):
        bk = book_by_market.get(b["market_key"])
        if bk is None:
            continue
        live_rows.append({
            "book_id": bk.book_id, "label": bk.market_key, "venue": V.venue_of(bk).as_str(),
            "deployable_usd": b["deployable_usd"], "underlying": bk.underlying, "maturity": bk.maturity,
            "kind": bk.kind, "family": V.AMM_PENDLE, "candidate": False, "live": True,
        })

    candidate_rows = cross_market_candidates() + cross_chain_candidates(live_rows, enabled=on)
    all_rows = live_rows + candidate_rows
    return {
        "live_rows": live_rows,
        "candidate_rows": candidate_rows,
        "all_rows": all_rows,
        "multichain_enabled": on,
    }


def build_report(*, enabled: Optional[bool] = None, deep: Optional[dict] = None,
                 rates_report: Optional[dict] = None) -> dict:
    """The expanded combined-capacity report: the venue curve over (live ∪ candidate) venues, contrasted
    with the live-only curve, so the lift from genuine venue independence is explicit and HONEST.

    Reports both curves' honest_combined + plateau_frac. The expansion only ADDS independent venues, so the
    expanded honest_combined ≥ the live-only honest_combined (asserted by the red-team property). is_advisory
    / candidate framing preserved. Deterministic / PURE / fail-CLOSED."""
    rows = build_expanded_rows(enabled=enabled, deep=deep, rates_report=rates_report)
    live_curve = V.combined_capacity_curve(rows["live_rows"]) if rows["live_rows"] else \
        {"honest_combined_usd": 0.0, "naive_sum_usd": 0.0, "n_venues": 0, "n_books": 0,
         "n_independent_books": 0, "plateau_frac": 0.0}
    expanded_curve = V.combined_capacity_curve(rows["all_rows"]) if rows["all_rows"] else live_curve

    lift = round(expanded_curve["honest_combined_usd"] - live_curve["honest_combined_usd"], 2)
    return {
        "model": "rates_desk_venue_expansion",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "candidate_measurement_only": True,   # candidates move NO capital, never the live track
        "multichain_enabled": rows["multichain_enabled"],
        "n_live_books": len(rows["live_rows"]),
        "n_candidate_books": len(rows["candidate_rows"]),
        "live_curve": live_curve,
        "expanded_curve": expanded_curve,
        "decorrelation_lift_usd": lift,
        "note": _expansion_note(rows, live_curve, expanded_curve, lift),
    }


def _expansion_note(rows: dict, live_curve: dict, expanded_curve: dict, lift: float) -> str:
    on = rows["multichain_enabled"]
    head = (
        f"LIVE Pendle PT universe: {live_curve.get('n_books')} books / {live_curve.get('n_venues')} venue(s) "
        f"→ HONEST combined ${live_curve.get('honest_combined_usd'):,.0f} (plateau "
        f"{live_curve.get('plateau_frac', 0)*100:.0f}% — all on one Pendle/USDe rail). ")
    flag = (f"SPA_RATES_MULTICHAIN={'ON (measurement)' if on else 'OFF (live default)'}: "
            f"{len(rows['candidate_rows'])} candidate independent-venue books added "
            f"({len(cross_market_candidates())} cross-market lending legs"
            + (f" + cross-chain L2 PT books" if on else "; cross-chain SUPPRESSED by the OFF flag") + "). ")
    expanded = (
        f"EXPANDED venue set: {expanded_curve.get('n_books')} books / {expanded_curve.get('n_venues')} "
        f"venue(s) → HONEST combined ${expanded_curve.get('honest_combined_usd'):,.0f} "
        f"(+${lift:,.0f} lift from genuine venue independence). ")
    verdict = (
        "HONEST VERDICT: the curve CLIMBS only because the added books exit through DISTINCT venues "
        "(lending withdraw ≠ Pendle AMM; L2 pools ≠ mainnet pool) — that is the real Layer-3 scaling lever. "
        "These candidates are MEASUREMENT-ONLY (documented conservative depth, NOT live §9 carry, "
        "is_advisory, behind the flag): they show HOW FAR independent venues would lift combined capacity, "
        "they do NOT claim the desk trades them today. Even expanded, the honest combined remains far below "
        "$10M — the count-thesis needs MANY genuinely-independent venues, deeper pools, AND real AUM; "
        "venue independence is necessary but not sufficient at today's depth.")
    return head + flag + expanded + verdict


def main() -> int:
    rep = build_report()
    print(f"Rates Desk — VENUE EXPANSION (A2.2 cross-market + A2.3 cross-chain)   "
          f"SPA_RATES_MULTICHAIN={'ON' if rep['multichain_enabled'] else 'OFF'}\n")
    lc, ec = rep["live_curve"], rep["expanded_curve"]
    print(f"LIVE     : {lc.get('n_books'):>3d} books / {lc.get('n_venues')} venue(s)  "
          f"honest ${lc.get('honest_combined_usd'):>12,.0f}  plateau {lc.get('plateau_frac',0)*100:5.1f}%")
    print(f"EXPANDED : {ec.get('n_books'):>3d} books / {ec.get('n_venues')} venue(s)  "
          f"honest ${ec.get('honest_combined_usd'):>12,.0f}  plateau {ec.get('plateau_frac',0)*100:5.1f}%  "
          f"({ec.get('n_independent_books')} independent)")
    print(f"LIFT     : +${rep['decorrelation_lift_usd']:,.0f} from genuine venue independence\n")
    print(rep["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
