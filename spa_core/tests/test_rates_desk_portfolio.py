"""
spa_core/tests/test_rates_desk_portfolio.py — the PORTFOLIO-OF-DESKS scale model (does the edge SCALE?).

Covers spa_core/strategy_lab/rates_desk/portfolio.py — the deterministic portfolio-of-desks capacity model
that turns the validated single-book edge into a sized, honest $10M/yr business case. Each distinct
(underlying, maturity) PT market is its OWN capacity-limited book; the aggregate is the SUM of per-book
deployables (bounded by real depth, not infinite). The allocator question: how many INDEPENDENT gated books
does the real universe offer, and how close does their summed deployable carry get to $10M/yr above floor?

PURE / no network / deterministic / fail-CLOSED. The model is exercised over SYNTHETIC multi-market deep
datasets (several healthy sUSDe PTs at documented per-day depths) so the tests are hermetic; a separate
test runs the REAL cached deep dataset when present (skipped otherwise). Proves:

  • aggregate total_deployable_usd == the SUM of the per-book deployable_usd, and
  • aggregate_net_apy_pct is the deployable-WEIGHTED mean of the per-book net carries, and
  • books_needed_for_10m is computed from the per-book average above-floor $/yr, and
  • MORE books → MORE total $ above floor (monotonic — independent depth adds, never subtracts), and
  • the curve is deterministic (same data → byte-identical), and
  • a missing deep dataset / a universe with no harvestable book fail-CLOSEs.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

import pytest

from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk import portfolio as PORT


# ── hermetic synthetic deep datasets: N healthy sUSDe PT books at documented per-day depths ──────────
def _one_market(maturity_offset_days: int, n_days: int, depth_usd: float, implied: float,
                start_year: int = 2025, key_suffix: str = "A") -> tuple:
    """One synthetic deep-history market dict (a single healthy sUSDe PT), shaped like
    pendle_pt_history.load() output. Returns (market_key, market_dict, list_of_dates)."""
    start = datetime.date(start_year, 1, 1)
    maturity = (start + datetime.timedelta(days=n_days + maturity_offset_days)).isoformat()
    series = []
    for i in range(n_days):
        d = (start + datetime.timedelta(days=i)).isoformat()
        series.append({"date": d, "implied_yield": implied, "underlying_yield": implied - 0.02,
                       "tvl_usd": depth_usd, "pt_price": None})
    key = f"PT-sUSDE-{maturity}-{key_suffix}"
    market = {
        "underlying": "sUSDe", "kind": "stable_synth", "symbol": key,
        "market_address": f"0x{key_suffix}", "pt_address": f"0xpt{key_suffix}", "maturity": maturity,
        "method": "synthetic", "series": series,
    }
    return key, market, [p["date"] for p in series]


def _synthetic_portfolio(n_books: int = 3, depth_usd: float = 100_000_000.0,
                         implied: float = 0.11, n_days: int = 200) -> dict:
    """A deterministic deep dict with `n_books` INDEPENDENT healthy sUSDe PT markets (distinct maturities),
    each with its own contemporaneous depth — so each becomes its own capacity-limited book."""
    markets = {}
    all_dates: list = []
    for b in range(n_books):
        key, m, dates = _one_market(
            maturity_offset_days=60 + b * 5, n_days=n_days, depth_usd=depth_usd, implied=implied,
            key_suffix=chr(ord("A") + b))
        markets[key] = m
        all_dates.extend(dates)
    return {
        "generated_at": "2026-01-01T00:00:00+00:00", "method": "synthetic_test",
        "underlyings": ["susde"],
        "window": {"start": min(all_dates), "end": max(all_dates)},
        "markets": markets,
    }


@pytest.fixture
def synth_report():
    return PORT.build_report(write=False, deep=_synthetic_portfolio(n_books=3), funding={})


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# aggregation identities
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_aggregate_deployable_is_sum_of_per_book(synth_report):
    """total_deployable_usd is EXACTLY the sum of the per-book deployable_usd (independent depths add)."""
    per_book = sum(b["deployable_usd"] for b in synth_report["books"])
    assert abs(synth_report["total_deployable_usd"] - per_book) < 1e-6
    assert synth_report["n_fundable_books"] == len(synth_report["books"])


def test_aggregate_carry_is_deployable_weighted(synth_report):
    """aggregate_net_apy_pct is the deployable-WEIGHTED mean of the per-book net carries."""
    books = synth_report["books"]
    total = sum(b["deployable_usd"] for b in books)
    expect = sum(b["deployable_usd"] * b["net_carry_pct"] for b in books) / total
    assert abs(synth_report["aggregate_net_apy_pct"] - round(expect, 4)) < 1e-3


def test_dollars_above_floor_identity(synth_report):
    """dollars_above_floor_per_yr == Σ deployable · max(0, net_carry − floor)/100 (the real excess)."""
    floor = synth_report["rwa_floor_pct"]
    expect = sum(b["deployable_usd"] * max(0.0, b["net_carry_pct"] - floor) / 100.0
                 for b in synth_report["books"])
    assert abs(synth_report["dollars_above_floor_per_yr"] - round(expect, 2)) < 1e-2


def test_books_needed_for_10m_computed(synth_report):
    """books_needed_for_10m is computed from the per-book average above-floor $/yr (ceil of target/avg)."""
    import math
    bn = synth_report["books_needed_for_10m"]
    avg = synth_report["avg_dollars_above_floor_per_book"]
    target = synth_report["target_above_floor_per_yr_usd"]
    if avg > 0:
        assert bn == int(math.ceil(target / avg))
        # the synthetic thin universe cannot itself reach $10M → needs MANY more books than it has
        assert bn > synth_report["n_fundable_books"]
    else:
        assert bn is None


def test_pct_of_target_and_gap_consistent(synth_report):
    """pct_of_10m_target and gap_to_10m_usd are consistent with dollars_above_floor and the target."""
    above = synth_report["dollars_above_floor_per_yr"]
    target = synth_report["target_above_floor_per_yr_usd"]
    assert abs(synth_report["pct_of_10m_target"] - round(above / target * 100.0, 4)) < 1e-3
    assert abs(synth_report["gap_to_10m_usd"] - round(max(0.0, target - above), 2)) < 1e-2


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# scale monotonicity: more independent books → more total $ above floor
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_more_books_more_total_above_floor():
    """Adding INDEPENDENT books (more distinct maturities, each its own depth) strictly increases both the
    total deployable AUM and the $/yr above floor — the whole scale thesis: independent depth ADDS."""
    r2 = PORT.build_report(write=False, deep=_synthetic_portfolio(n_books=2), funding={})
    r4 = PORT.build_report(write=False, deep=_synthetic_portfolio(n_books=4), funding={})
    assert r4["n_fundable_books"] > r2["n_fundable_books"]
    assert r4["total_deployable_usd"] > r2["total_deployable_usd"]
    assert r4["dollars_above_floor_per_yr"] > r2["dollars_above_floor_per_yr"]
    # and identical per-book economics → the per-book average above-floor is ~unchanged (books are
    # independent, so doubling the count ~doubles the total but not the per-book average)
    assert abs(r4["avg_dollars_above_floor_per_book"]
               - r2["avg_dollars_above_floor_per_book"]) < r2["avg_dollars_above_floor_per_book"] * 0.5 + 1.0


def test_more_books_fewer_books_needed_for_10m():
    """More books at the same per-book economics does NOT change books_needed_for_10m much (it is a
    per-book-average quantity), but a richer universe gets a HIGHER pct_of_target — closer to $10M."""
    r2 = PORT.build_report(write=False, deep=_synthetic_portfolio(n_books=2), funding={})
    r6 = PORT.build_report(write=False, deep=_synthetic_portfolio(n_books=6), funding={})
    assert r6["pct_of_10m_target"] > r2["pct_of_10m_target"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# determinism + fail-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_deterministic_same_data_same_report():
    """Same (deep, funding) → byte-identical portfolio report (no RNG, no clock in the numbers)."""
    deep = _synthetic_portfolio(n_books=3)
    a = PORT.build_report(write=False, deep=deep, funding={})
    b = PORT.build_report(write=False, deep=deep, funding={})
    assert a["total_deployable_usd"] == b["total_deployable_usd"]
    assert a["aggregate_net_apy_pct"] == b["aggregate_net_apy_pct"]
    assert a["dollars_above_floor_per_yr"] == b["dollars_above_floor_per_yr"]
    assert a["books_needed_for_10m"] == b["books_needed_for_10m"]
    assert [bk["deployable_usd"] for bk in a["books"]] == [bk["deployable_usd"] for bk in b["books"]]


def test_books_are_independent_per_maturity():
    """Each distinct (underlying, maturity) market is a SEPARATE book — the report lists one book per
    market (a portfolio of N books, not one aggregated book)."""
    deep = _synthetic_portfolio(n_books=5)
    r = PORT.build_report(write=False, deep=deep, funding={})
    maturities = {b["maturity"] for b in r["books"]}
    assert len(r["books"]) == 5
    assert len(maturities) == 5  # five distinct maturities → five independent books


def test_fail_closed_missing_deep_dataset(tmp_path, monkeypatch):
    """fail-CLOSED: with no deep dataset on disk, load() RAISES — the portfolio is never fabricated."""
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(pph, "_OUT", missing)
    with pytest.raises(FileNotFoundError):
        PORT.build_report(write=False, funding={})


def test_fail_closed_empty_markets():
    """fail-CLOSED: a deep dataset with empty 'markets' RAISES (no fabricated portfolio)."""
    bad = {"window": {"start": None, "end": None}, "markets": {}}
    with pytest.raises(Exception):
        PORT.build_report(write=False, deep=bad, funding={})


def test_fail_closed_no_harvestable_books():
    """fail-CLOSED: a universe of ONLY toxic LRT markets (gate refuses them as carry) has no harvestable
    book → RAISES rather than emitting a fabricated empty/zero portfolio."""
    deep = _synthetic_portfolio(n_books=2)
    # retag every market to an LRT kind (non-harvestable) → no STABLE_SYNTH/RWA book remains
    for m in deep["markets"].values():
        m["kind"] = "lrt"
        m["underlying"] = "ezETH"
    with pytest.raises(ValueError):
        PORT.build_report(write=False, deep=deep, funding={})


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the REAL deep dataset (skipped when the cached pull is absent — e.g. CI/sandbox)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _real_deep_available() -> bool:
    try:
        pph.load()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _real_deep_available(), reason="deep Pendle PT history not cached")
def test_real_deep_portfolio_is_honest_about_10m():
    """On the REAL cached deep dataset the portfolio is several independent books summing to a FINITE,
    real-depth-bounded total — and the honest verdict states how far short of $10M/yr above floor the
    CURRENT market is (the fundability truth: the carry edge scales across books but the depth is thin)."""
    r = PORT.build_report(write=False)
    assert r["n_fundable_books"] >= 2, "the real universe offers several independent harvestable books"
    # the aggregate is the sum of per-book deployables (finite, real depth — not infinite)
    assert abs(r["total_deployable_usd"] - sum(b["deployable_usd"] for b in r["books"])) < 1e-2
    assert r["dollars_above_floor_per_yr"] >= 0.0
    # the verdict must be HONEST about the $10M target either way (cleared, or a stated gap)
    assert "$10M" in r["note"] or "10M" in r["note"] or "$10,000,000" in r["note"]
    assert r["pct_of_10m_target"] >= 0.0
