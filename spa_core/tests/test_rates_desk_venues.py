"""
spa_core/tests/test_rates_desk_venues.py — LANE A W2 (A2.1–A2.5): venue-independence + the combined-
capacity curve (THE CRUX) + cross-market/cross-chain expansion + the red-team.

Covers:
  • venues.py            — VenueKey / venue_of / exit_rail_of (A2.4): sUSDe+USDe share the Ethena rail,
                           fail-CLOSED on an unmapped underlying (never silently independent).
  • annotate_independence / combined_capacity_curve (A2.4): per-book shares_exit_venue HONESTLY; the
                           curve CLIMBS for genuinely-independent books and PLATEAUS for shared ones.
  • venue_expansion.py   — cross-market lending legs (A2.2) + cross-chain L2 books (A2.3) behind
                           SPA_RATES_MULTICHAIN (default OFF live / ON measurement); the curve lift is
                           HONEST and candidate/advisory only; LRT never slips in.
  • A2.1                 — the live registry IS the full maturity ladder (each maturity an independent
                           depth pool / distinct book).
  • RED-TEAM (A2.5)      — two "different" books that are the SAME pool collapse to ~1 book under the
                           haircut (NOT 2); adding a genuinely-INDEPENDENT book NEVER decreases honest
                           combined deployable; same-venue books do NOT double-count.

PURE / no network / deterministic / fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal

import pytest

from spa_core.strategy_lab.rates_desk import books as B
from spa_core.strategy_lab.rates_desk import venues as V
from spa_core.strategy_lab.rates_desk import venue_expansion as VE


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────
def _row(book_id: str, venue: str, deployable: float) -> dict:
    return {"book_id": book_id, "venue": venue, "deployable_usd": deployable}


def _pt_book(underlying: str, maturity: str, chain: str = "ethereum", key=None) -> B.Book:
    return B.Book(book_id=B.make_book_id(underlying, maturity, chain), underlying=underlying,
                  maturity=maturity, chain=chain, market_key=key or f"PT-{underlying}-{maturity}",
                  kind="stable_synth")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A2.4 — venue identity + exit rail (fail-CLOSED, no silently-independent unknowns)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_susde_and_usde_share_the_ethena_rail():
    """sUSDe and USDe BOTH redeem through the Ethena USDe rail — the honest correlated pair. So two PT
    books, one sUSDe one USDe, on Pendle/Ethereum, share ONE venue cluster (NOT independent)."""
    assert V.exit_rail_of("sUSDe") == V.exit_rail_of("USDe") == "ethena_usde"
    a = V.venue_of(_pt_book("sUSDe", "2025-09-25"))
    b = V.venue_of(_pt_book("USDe", "2025-12-26"))
    assert a == b  # same (pendle_amm, ethena_usde, ethereum) cluster


def test_distinct_rails_are_distinct_venues():
    """A USDC lending leg, a USDS lending leg, a Pendle sUSDe PT → three DISTINCT venue clusters."""
    usdc = V.venue_key_for(V.AMM_LENDING, "usdc", "ethereum")
    usds = V.venue_key_for(V.AMM_LENDING, "usds", "ethereum")
    susde = V.venue_of(_pt_book("sUSDe", "2025-09-25"))
    assert len({usdc.as_str(), usds.as_str(), susde.as_str()}) == 3


def test_lending_family_independent_of_pendle_even_on_shared_rail():
    """A lending fixed leg has a DISTINCT AMM family (lending withdraw ≠ Pendle AMM), so even sharing a
    stable rail it is an INDEPENDENT exit from the Pendle PT AMM."""
    # GHO lending vs a (hypothetical) GHO PT — different AMM family → different venue
    lend = V.venue_key_for(V.AMM_LENDING, "gho", "ethereum")
    pt = V.VenueKey(amm_family=V.AMM_PENDLE, exit_rail=V.exit_rail_of("gho"), chain="ethereum")
    assert lend != pt
    assert lend.amm_family != pt.amm_family


def test_cross_chain_is_a_distinct_venue():
    """The SAME sUSDe market on Arbitrum is a DIFFERENT venue cluster than on Ethereum (distinct depth)."""
    eth = V.venue_of(_pt_book("sUSDe", "2025-09-25", "ethereum"))
    arb = V.venue_of(_pt_book("sUSDe", "2025-09-25", "arbitrum"))
    assert eth != arb


def test_exit_rail_fail_closed_on_unmapped_underlying():
    """fail-CLOSED: an unmapped underlying RAISES — we NEVER silently treat it as its own independent rail
    (the flattering failure that would inflate the curve)."""
    with pytest.raises(ValueError):
        V.exit_rail_of("mystery_token_xyz")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A2.4 — per-book independence + the combined-capacity curve (CLIMBS / PLATEAUS honestly)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_all_same_venue_books_marked_not_independent():
    """N books on ONE shared venue → all shares_exit_venue=True; exactly ONE is rank 1 (full depth)."""
    rows = [_row("b1", "pendle_amm|ethena_usde|ethereum", 100_000.0),
            _row("b2", "pendle_amm|ethena_usde|ethereum", 50_000.0),
            _row("b3", "pendle_amm|ethena_usde|ethereum", 25_000.0)]
    ann = V.annotate_independence(rows)
    assert all(r["shares_exit_venue"] for r in ann)
    assert sum(1 for r in ann if r["venue_rank"] == 1) == 1
    assert all(r["venue_cluster_size"] == 3 for r in ann)


def test_curve_plateaus_for_shared_venue_books():
    """THE CRUX (plateau): 3 books on ONE venue → honest combined = deepest + (1-haircut)·(rest), well
    below the naive sum. The curve flattens after the first book."""
    rows = [_row("b1", "v|shared", 100_000.0),
            _row("b2", "v|shared", 100_000.0),
            _row("b3", "v|shared", 100_000.0)]
    c = V.combined_capacity_curve(rows, haircut_frac=Decimal("0.5"))
    # naive = 300k; honest = 100k + 0.5*100k + 0.5*100k = 200k
    assert c["naive_sum_usd"] == 300_000.0
    assert c["honest_combined_usd"] == 200_000.0
    assert c["n_venues"] == 1
    assert c["n_independent_books"] == 1
    assert c["plateau_frac"] == pytest.approx(1.0 - 200_000.0 / 300_000.0, abs=1e-6)


def test_curve_climbs_for_independent_books():
    """THE CRUX (climb): 3 books on 3 DISTINCT venues → honest combined == naive sum (full additivity);
    every book is independent; plateau_frac == 0 (nothing non-additive)."""
    rows = [_row("b1", "v|a", 100_000.0),
            _row("b2", "v|b", 100_000.0),
            _row("b3", "v|c", 100_000.0)]
    c = V.combined_capacity_curve(rows, haircut_frac=Decimal("0.5"))
    assert c["honest_combined_usd"] == c["naive_sum_usd"] == 300_000.0
    assert c["n_venues"] == 3
    assert c["n_independent_books"] == 3
    assert c["plateau_frac"] == 0.0


def test_curve_cumulative_is_monotone_nondecreasing():
    """PROPERTY: cumulative_usd along the curve never decreases (each book adds ≥ 0)."""
    rows = [_row(f"b{i}", "v|shared", 10_000.0) for i in range(6)]
    c = V.combined_capacity_curve(rows)
    cums = [pt["cumulative_usd"] for pt in c["curve"]]
    assert cums == sorted(cums)


def test_curve_missing_venue_fail_closed():
    """fail-CLOSED: a row with no venue RAISES (a venue-less book would be silently independent)."""
    with pytest.raises(ValueError):
        V.combined_capacity_curve([{"book_id": "x", "deployable_usd": 1.0}])


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A2.5 — RED-TEAM
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_redteam_same_pool_two_books_collapse_to_one():
    """ADVERSARIAL: two "different" books that are actually the SAME pool (same venue, same depth) must
    COLLAPSE under the haircut to ~1 book — NOT count as 2 full independent books."""
    rows = [_row("dupe_a", "pendle_amm|ethena_usde|ethereum", 100_000.0),
            _row("dupe_b", "pendle_amm|ethena_usde|ethereum", 100_000.0)]
    c = V.combined_capacity_curve(rows, haircut_frac=Decimal("0.5"))
    # naive would double-count to 200k; honest collapses the second to half → 150k, and at a 1.0 haircut
    # it would be EXACTLY one book (100k). The second pool does NOT add a second full 100k.
    assert c["honest_combined_usd"] < c["naive_sum_usd"]
    full = V.combined_capacity_curve(rows, haircut_frac=Decimal("1.0"))
    assert full["honest_combined_usd"] == 100_000.0  # collapses to exactly ONE book
    assert full["n_independent_books"] == 1


def test_redteam_adding_independent_book_never_decreases_combined():
    """PROPERTY (the crux invariant): adding a GENUINELY-INDEPENDENT book NEVER decreases honest combined
    deployable — it adds its full depth. (An impossible "book that lowers combined deployable" is flagged
    by this monotonicity holding.)"""
    base = [_row("b1", "v|a", 100_000.0), _row("b2", "v|a", 80_000.0)]
    c_base = V.combined_capacity_curve(base)["honest_combined_usd"]
    extended = base + [_row("b3", "v|independent", 70_000.0)]
    c_ext = V.combined_capacity_curve(extended)["honest_combined_usd"]
    assert c_ext >= c_base
    assert c_ext == round(c_base + 70_000.0, 2)  # the independent book adds its FULL depth


def test_redteam_adding_shared_book_does_not_double_count():
    """PROPERTY: adding a SAME-VENUE book adds only (1-haircut)·depth — never its full depth (no
    double-counting one exit)."""
    base = [_row("b1", "v|shared", 100_000.0)]
    c_base = V.combined_capacity_curve(base, haircut_frac=Decimal("0.5"))["honest_combined_usd"]
    extended = base + [_row("b2", "v|shared", 100_000.0)]
    c_ext = V.combined_capacity_curve(extended, haircut_frac=Decimal("0.5"))["honest_combined_usd"]
    # the second same-venue book adds 0.5*100k = 50k, NOT 100k
    assert c_ext == round(c_base + 50_000.0, 2)
    assert c_ext < c_base + 100_000.0


def test_redteam_independent_always_ge_shared_for_same_depth():
    """PROPERTY: an independent book of depth D contributes MORE than a same-venue book of the same depth
    (independence is strictly more valuable — the model can never reward sharing a venue)."""
    indep = V.combined_capacity_curve(
        [_row("a", "v|x", 100_000.0), _row("b", "v|y", 100_000.0)])["honest_combined_usd"]
    shared = V.combined_capacity_curve(
        [_row("a", "v|x", 100_000.0), _row("b", "v|x", 100_000.0)])["honest_combined_usd"]
    assert indep > shared


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A2.2 / A2.3 — cross-market + cross-chain expansion (behind the flag, candidate-only, no LRT)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_cross_market_candidates_are_independent_lending_venues():
    """A2.2: lending candidates are distinct AMM-family (lending) venues; none is the Pendle PT AMM; all
    are harvestable kinds (no LRT/tail) and flagged candidate/not-live."""
    rows = VE.cross_market_candidates()
    assert rows  # LENDING_TARGETS has harvestable USDC/USDS/GHO legs
    assert all(r["family"] == V.AMM_LENDING for r in rows)
    assert all(r["candidate"] is True and r["live"] is False for r in rows)
    assert all(r["kind"] in ("stable_synth", "stable_rwa") for r in rows)
    assert all(V.AMM_PENDLE not in r["venue"] for r in rows)


def test_multichain_flag_default_off(monkeypatch):
    """A2.3: SPA_RATES_MULTICHAIN defaults OFF → cross-chain candidates are SUPPRESSED for the live path."""
    monkeypatch.delenv(VE.MULTICHAIN_FLAG_ENV, raising=False)
    assert VE.multichain_enabled() is False
    live = [{"book_id": "x", "underlying": "sUSDe", "maturity": "2025-09-25", "deployable_usd": 100_000.0,
             "kind": "stable_synth"}]
    assert VE.cross_chain_candidates(live) == []


def test_multichain_flag_on_enumerates_distinct_chains(monkeypatch):
    """A2.3: flag ON → the same market becomes DISTINCT candidate books on each cross-chain (distinct
    VenueKey via the chain). Each carries a conservative L2 depth < the mainnet depth."""
    monkeypatch.setenv(VE.MULTICHAIN_FLAG_ENV, "1")
    assert VE.multichain_enabled() is True
    live = [{"book_id": "x", "underlying": "sUSDe", "maturity": "2025-09-25", "deployable_usd": 100_000.0,
             "kind": "stable_synth"}]
    cands = VE.cross_chain_candidates(live)
    assert len(cands) == len(VE._CROSS_CHAINS)
    venues = {c["venue"] for c in cands}
    assert len(venues) == len(VE._CROSS_CHAINS)  # each chain its own venue cluster
    assert all(c["deployable_usd"] < 100_000.0 for c in cands)  # conservative L2 depth credit


def test_cross_chain_candidate_fail_closed_unmapped_rail(monkeypatch):
    """fail-CLOSED: an unmapped underlying yields NO candidate (never a silently-independent L2 book)."""
    monkeypatch.setenv(VE.MULTICHAIN_FLAG_ENV, "1")
    live = [{"book_id": "x", "underlying": "mystery", "maturity": "2025-09-25",
             "deployable_usd": 100_000.0, "kind": "stable_synth"}]
    assert VE.cross_chain_candidates(live) == []


def test_expansion_lift_is_nonnegative_and_from_distinct_venues(monkeypatch):
    """PROPERTY: the expanded curve's honest combined ≥ the live-only curve's (the expansion only ADDS
    independent venues) — the lift is ≥ 0 and the venue count strictly rises."""
    monkeypatch.setenv(VE.MULTICHAIN_FLAG_ENV, "1")
    # hermetic rates report: 2 sUSDe PT books (one shared venue)
    rates_report = {"books": [
        {"market_key": "PT-sUSDE-A", "deployable_usd": 100_000.0},
        {"market_key": "PT-sUSDE-B", "deployable_usd": 50_000.0}]}
    deep = {"window": {"end": "2025-09-25"}, "markets": {
        "PT-sUSDE-A": {"underlying": "sUSDe", "maturity": "2025-09-25", "kind": "stable_synth"},
        "PT-sUSDE-B": {"underlying": "sUSDe", "maturity": "2025-12-26", "kind": "stable_synth"}}}
    rep = VE.build_report(enabled=True, deep=deep, rates_report=rates_report)
    assert rep["decorrelation_lift_usd"] >= 0.0
    assert rep["expanded_curve"]["honest_combined_usd"] >= rep["live_curve"]["honest_combined_usd"]
    assert rep["expanded_curve"]["n_venues"] > rep["live_curve"]["n_venues"]
    assert rep["candidate_measurement_only"] is True
    assert rep["is_advisory"] is True


def test_expansion_no_lrt_ever(monkeypatch):
    """A toxic LRT underlying never produces a candidate book (refusal honesty preserved across expansion).
    cross_chain_candidates only takes live (already LRT-excluded) rows; an LRT row with no mapped rail is
    fail-closed-dropped anyway."""
    monkeypatch.setenv(VE.MULTICHAIN_FLAG_ENV, "1")
    live = [{"book_id": "x", "underlying": "ezETH", "maturity": "2025-09-25",
             "deployable_usd": 100_000.0, "kind": "lrt"}]
    # ezETH has no mapped stable rail → fail-closed dropped (no LRT candidate)
    assert VE.cross_chain_candidates(live) == []
    assert not any(r["kind"] == "lrt" for r in VE.cross_market_candidates())


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A2.1 — the live registry IS the maturity ladder (smoke against real cache when present)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _have_deep() -> bool:
    try:
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
        pph.load()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _have_deep(), reason="deep Pendle PT history not cached")
def test_a21_registry_is_full_maturity_ladder():
    """A2.1: the registry enumerates EACH maturity as its own book (an independent depth pool). The real
    universe has MANY maturities per underlying → many books, all on the shared Pendle/USDe venue."""
    books = B.enumerate_books()
    by_underlying = {}
    for bk in books:
        by_underlying.setdefault(bk.underlying.lower(), set()).add(bk.maturity)
    # at least one underlying has a multi-rung maturity ladder
    assert any(len(mats) >= 3 for mats in by_underlying.values())


@pytest.mark.skipif(not _have_deep(), reason="deep Pendle PT history not cached")
def test_portfolio_venue_report_naive_sum_equals_total_deployable():
    """INTEGRATION: portfolio.venue_independence_report().naive_sum_deployable_usd EQUALS
    build_report().total_deployable_usd (same per-book §9 sizing) — the delta to honest_combined is
    exactly the shared-venue non-additivity, nothing else."""
    from spa_core.strategy_lab.rates_desk import portfolio as P
    vr = P.venue_independence_report()
    br = P.build_report(write=False)
    assert abs(vr["naive_sum_deployable_usd"] - br["total_deployable_usd"]) < 0.01
    assert vr["honest_combined_deployable_usd"] <= vr["naive_sum_deployable_usd"]
    assert vr["n_fundable_books"] == br["n_fundable_books"]


@pytest.mark.skipif(not _have_deep(), reason="deep Pendle PT history not cached")
def test_a24_live_universe_shares_one_venue_smoke():
    """A2.4 smoke on the REAL universe: the live fundable PT books overwhelmingly share ONE venue cluster
    (Pendle/USDe/ethereum) → the curve plateaus (honest < naive). This is the headline finding."""
    rep = VE.build_report(enabled=False)  # live default
    lc = rep["live_curve"]
    assert lc["n_venues"] == 1  # all sUSDe+USDe PT share the Ethena rail
    assert lc["honest_combined_usd"] < lc["naive_sum_usd"]  # plateaus
    assert lc["n_independent_books"] == 1  # only the deepest counts at full depth
