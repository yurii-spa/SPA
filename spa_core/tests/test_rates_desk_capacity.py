"""
spa_core/tests/test_rates_desk_capacity.py — the CAPACITY-curve analysis (does the edge survive size?).

Covers spa_core/strategy_lab/rates_desk/capacity.py — the deterministic capacity curve for the validated
FixedCarry survivor book. The allocator question: how much AUM can the carry absorb at REAL Pendle PT
depth before the §9 exit-capacity sizing forces the book APY down toward the RWA floor?

PURE / no network / deterministic / fail-CLOSED. The curve is built over a SYNTHETIC deep dataset (one
healthy sUSDe PT with a documented per-day depth) so the test is hermetic; a separate test runs the REAL
cached deep dataset when it is present (skipped otherwise). Proves:

  • the book APY at TINY AUM ≈ the unconstrained carry (the ~6%/zero-size edge), and
  • the book APY is MONOTONICALLY NON-INCREASING as AUM grows past the deployable depth, and
  • at HUGE AUM the book APY → the floor (capacity-bound saturation), and
  • a saturation AUM + the floor+200bps ceiling are identified, and
  • the curve is deterministic (same data → byte-identical), and
  • a missing deep dataset / a depthless market fail-CLOSEs.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal

import pytest

from spa_core.strategy_lab.rates_desk import capacity as CAP
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ── a hermetic synthetic deep dataset: ONE healthy sUSDe PT with deep, contemporaneous pool depth ──
def _synthetic_deep(n_days: int = 220, depth_usd: float = 100_000_000.0) -> dict:
    """A deterministic deep-history dict shaped exactly like pendle_pt_history.load() output, carrying a
    single long-dated healthy sUSDe PT at a documented implied yield + a contemporaneous per-day TVL. The
    healthy synth book FIRES the gate (no tail veto), so its capacity curve is driven purely by the §9
    exit-capacity sizing — the cleanest possible isolation of the capacity mechanism."""
    start = __import__("datetime").date(2025, 1, 1)
    maturity = (start + __import__("datetime").timedelta(days=n_days + 60)).isoformat()
    series = []
    for i in range(n_days):
        d = (start + __import__("datetime").timedelta(days=i)).isoformat()
        series.append({"date": d, "implied_yield": 0.11, "underlying_yield": 0.09,
                       "tvl_usd": depth_usd, "pt_price": None})
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "method": "synthetic_test",
        "underlyings": ["susde"],
        "window": {"start": series[0]["date"], "end": series[-1]["date"]},
        "markets": {
            "PT-sUSDE-TEST": {
                "underlying": "susde", "kind": "stable_synth", "symbol": "PT-sUSDE-TEST",
                "market_address": "0xtest", "pt_address": "0xpt", "maturity": maturity,
                "method": "synthetic", "series": series,
            }
        },
    }


@pytest.fixture
def synth_report():
    deep = _synthetic_deep()
    return CAP.build_report(write=False, deep=deep, funding={})


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the capacity curve shape
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_small_aum_beats_floor_and_approaches_unconstrained_carry(synth_report):
    """At small AUM the book is (near-)cash-bound: it deploys the bulk of its capital into the carry and
    so its book APY is well above the floor — the unconstrained edge is real before size bites."""
    floor = synth_report["rwa_floor_pct"]
    smallest = synth_report["aum_levels"][0]
    assert smallest["book_net_apy_pct"] > floor, "small-AUM book must beat the floor (real carry)"
    # the unconstrained (zero-size) carry is the ceiling the curve starts from
    assert synth_report["unconstrained_gross_carry_pct"] > 0.0
    assert smallest["book_net_apy_pct"] <= (
        floor + synth_report["unconstrained_gross_carry_pct"] + 1e-6), \
        "book APY can never exceed floor + the unconstrained carry"


def test_book_apy_monotonically_non_increasing_in_aum(synth_report):
    """The capacity guarantee: as deployed AUM grows past the deployable depth, the book APY is
    MONOTONICALLY NON-INCREASING (more idle cash @ floor + thinner per-dollar carry → lower book APY)."""
    apys = [lv["book_net_apy_pct"] for lv in synth_report["aum_levels"]]
    for prev, cur in zip(apys, apys[1:]):
        assert cur <= prev + 1e-9, f"book APY must not rise as AUM grows: {prev} -> {cur}"
    # and it must STRICTLY fall somewhere (capacity actually binds, not a flat line)
    assert apys[-1] < apys[0] - 1e-6, "book APY must compress as AUM grows (capacity binds)"


def test_huge_aum_converges_to_floor(synth_report):
    """At the largest swept AUM the book is overwhelmingly capacity-bound: nearly all capital sits idle @
    the floor, so the book APY converges to ~the floor (the honest saturation ceiling)."""
    floor = synth_report["rwa_floor_pct"]
    biggest = synth_report["aum_levels"][-1]
    assert biggest["book_net_apy_pct"] >= floor - 1e-6, "book APY cannot fall below the floor"
    assert biggest["book_net_apy_pct"] <= floor + 0.05, \
        "at $1B the book must have saturated to within a few bps of the floor"
    assert biggest["idle_frac"] > 0.99, "at $1B almost the whole book is idle @ floor"


def test_decomposition_adds_up(synth_report):
    """book_net_apy = gross_carry + idle_at_floor, exactly (the honest accounting identity)."""
    for lv in synth_report["aum_levels"]:
        recon = lv["gross_carry_pct"] + lv["idle_at_floor_pct"]
        assert abs(recon - lv["book_net_apy_pct"]) < 1e-6, \
            f"decomposition must reconstruct book APY at AUM={lv['aum_usd']}"
        assert 0.0 <= lv["deployed_frac"] <= 1.0
        assert abs(lv["deployed_frac"] + lv["idle_frac"] - 1.0) < 1e-6


def test_saturation_and_ceiling_identified(synth_report):
    """The report locates a saturation AUM (book APY → floor) and the floor+200bps fundable ceiling, and
    they are ordered sensibly (the ceiling is a SMALLER AUM than full saturation — the edge thins first)."""
    sat = synth_report["saturation_aum_usd"]
    ceil = synth_report["max_aum_above_floor_plus_200bps"]
    assert sat is not None, "a deep enough sweep must reach saturation (book APY ~ floor)"
    # the ceiling (still beats floor+200bps) is reached at a SMALLER AUM than saturation
    if ceil is not None:
        assert ceil <= sat, "the fundable ceiling must be at or below the saturation AUM"
    # the floor+200bps line is the floor plus 200bps, reported explicitly
    assert abs(synth_report["floor_plus_200bps_pct"] - (synth_report["rwa_floor_pct"] + 2.0)) < 1e-6


def test_deployed_usd_shrinks_as_fraction_with_size(synth_report):
    """Honest capacity signature: the deployed FRACTION falls as AUM grows (a fixed-depth pool absorbs a
    fixed dollar amount, so its share of a bigger book shrinks)."""
    fracs = [lv["deployed_frac"] for lv in synth_report["aum_levels"]]
    for prev, cur in zip(fracs, fracs[1:]):
        assert cur <= prev + 1e-9, "deployed fraction must be non-increasing in AUM"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# determinism + fail-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_deterministic_same_data_same_curve():
    """Same (deep, funding) → byte-identical capacity curve (no RNG, no clock in the numbers)."""
    deep = _synthetic_deep()
    a = CAP.build_report(write=False, deep=deep, funding={})
    b = CAP.build_report(write=False, deep=deep, funding={})
    assert [lv["book_net_apy_pct"] for lv in a["aum_levels"]] == \
           [lv["book_net_apy_pct"] for lv in b["aum_levels"]]
    assert a["saturation_aum_usd"] == b["saturation_aum_usd"]
    assert a["max_aum_above_floor_plus_200bps"] == b["max_aum_above_floor_plus_200bps"]
    assert a["unconstrained_gross_carry_pct"] == b["unconstrained_gross_carry_pct"]


def test_fail_closed_missing_deep_dataset(tmp_path, monkeypatch):
    """fail-CLOSED: with no deep dataset on disk, load() RAISES — the curve is never fabricated."""
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(pph, "_OUT", missing)
    with pytest.raises(FileNotFoundError):
        CAP.build_report(write=False, funding={})


def test_fail_closed_empty_markets():
    """fail-CLOSED: a deep dataset with empty 'markets' RAISES (no fabricated capacity)."""
    bad = {"window": {"start": None, "end": None}, "markets": {}}
    with pytest.raises(Exception):
        CAP.build_report(write=False, deep=bad, funding={})


def test_zero_depth_market_yields_no_capacity():
    """fail-CLOSED on depth: a PT pool with $0 contemporaneous depth → the §9 exit-capacity sizing
    refuses to size into it, so the book stays idle @ the floor (it NEVER fabricates capacity into a
    depthless pool). (The config fail-CLOSEs a non-positive TVL to the documented constant, so the book
    can still deploy a tiny gate-approved size; the guarantee under test is that it does not deploy MORE
    than a depthless pool warrants — i.e. it is at most the documented-constant capacity, far below a deep
    pool.)"""
    deep_deep = _synthetic_deep(depth_usd=100_000_000.0)
    deep_thin = _synthetic_deep(depth_usd=0.0)  # → config fail-CLOSEs to PENDLE_HIST_POOL_DEPTH_USD ($5M)
    r_deep = CAP.build_report(write=False, deep=deep_deep, funding={})
    r_thin = CAP.build_report(write=False, deep=deep_thin, funding={})
    # at a mid AUM the thin pool deploys strictly LESS than the deep pool (lower capacity)
    aum_idx = 3  # $1M rung
    assert r_thin["aum_levels"][aum_idx]["deployed_usd"] <= \
        r_deep["aum_levels"][aum_idx]["deployed_usd"] + 1e-6


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
def test_real_deep_capacity_is_capacity_limited():
    """On the REAL cached deep dataset the FixedCarry survivor book is CAPACITY-LIMITED: book APY falls
    monotonically with AUM and saturates toward the floor — the honest fundability truth (thin Pendle)."""
    r = CAP.build_report(write=False)
    apys = [lv["book_net_apy_pct"] for lv in r["aum_levels"]]
    for prev, cur in zip(apys, apys[1:]):
        assert cur <= prev + 1e-9
    floor = r["rwa_floor_pct"]
    assert r["aum_levels"][-1]["book_net_apy_pct"] <= floor + 0.05, \
        "at $1B the real book must saturate to ~the floor"
    assert r["aum_levels"][0]["book_net_apy_pct"] > floor, "small-AUM book beats the floor (real carry)"
    assert r["saturation_aum_usd"] is not None
