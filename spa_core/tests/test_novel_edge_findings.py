"""Regression guard for the load-bearing NOVEL-EDGE findings (docs/DYNAMIC_LEVERAGE_GUARDIAN.md §Реестр).

These findings are the owner's core thesis stated AS NUMBERS ("a stable 15% is a tail you are paid to
hold" → refusal-discipline out-earns naive yield-chasing at realistic crisis severity). They are computed
off the aggressive_lab fixture; if a parallel change to `fixtures.py` ever shifts the calibrated crisis
magnitudes, the finding could silently invert. This test pins the QUALITATIVE direction (not exact
numbers, which may drift) so the registry claim stays honest + verifiable — "don't trust us, check us"
applied to our own research. Deterministic, hermetic (fixture-based), no network, no live track.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _ROOT / "scripts" / "refusal_gate_overlay.py"
_CROSSDESK = _ROOT / "scripts" / "cross_desk_portfolio.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load(_SCRIPT, "_refusal_gate_overlay_under_test")
CD = _load(_CROSSDESK, "_cross_desk_portfolio_under_test")


def test_refused_set_is_exactly_risk_class_C_and_D():
    res = M.compute_books()
    assert res is not None
    refused = {b["id"] for b in res["per_book"] if b["refused"]}
    admitted = {b["id"] for b in res["per_book"] if not b["refused"]}
    # every refused book is class C/D; nothing admitted is C/D (the gate reads risk_class, never guesses)
    assert all(b["class"] in {"C", "D"} for b in res["per_book"] if b["refused"])
    assert all(b["class"] not in {"C", "D"} for b in res["per_book"] if not b["refused"])
    assert refused and refused.isdisjoint(admitted)


def test_refusal_discipline_dominates_naive_at_calibrated_severity():
    # THE owner-thesis-as-a-number: at the fixture's calibrated (1.0x) crisis severity, refusing the
    # C/D toxic universe and banking the floor beats the naive yield-chaser on BOTH axes.
    res = M.compute_books()
    naive, disc = res["naive"], res["disciplined"]
    assert disc["cagr"] > naive["cagr"], (disc, naive)      # higher realized return
    assert disc["maxdd"] < naive["maxdd"], (disc, naive)    # AND lower drawdown → dominance


def test_fat_headline_books_net_poor_realized_return_after_tails():
    # the "tail-comp illusion": the 12-15% headline C/D books do NOT deliver their headline once their
    # depeg/liquidation tail lands — realized CAGR is a small fraction of (often far below) the headline.
    res = M.compute_books()
    for b in res["per_book"]:
        if b["refused"] and b["headline"] >= 12.0 and b["shape"] in {"depeg", "liquidation"}:
            assert b["cagr"] < b["headline"] * 0.5, b   # realized << headline (tail eats it)


def test_severity_breakeven_is_near_calibrated_magnitudes():
    # the honest boundary: discipline wins once crises are >= ~0.8x calibrated. The naive book must
    # out-earn the floor in a MILD world (0.25x) and lose to it at calibrated (1.0x) — i.e. a crossing
    # exists between 0.25x and 1.0x, near reality (not off at an absurd 5x that would make the edge moot).
    res = M.compute_books()
    floor_cagr = res["disciplined"]["cagr"]
    mild = _naive_cagr_at(M, res["toxic_ids"], 0.25)
    calib = _naive_cagr_at(M, res["toxic_ids"], 1.0)
    assert mild > floor_cagr, (mild, floor_cagr)     # in a mild world the headline-chaser out-earns
    assert calib < floor_cagr, (calib, floor_cagr)   # at real severity the floor wins → crossing in (0.25,1.0]


def _naive_cagr_at(mod, toxic_ids, k):
    eqs = [mod._toxic_equity_scaled(sid, k) for sid in toxic_ids]
    m = min(len(e) for e in eqs)
    rets = [mod._returns(e[:m]) for e in eqs]
    eq = [100000.0]
    for t in range(m - 1):
        eq.append(eq[-1] * (1.0 + sum(rb[t] for rb in rets) / len(rets)))
    return mod._metrics(eq)[0]


def test_compute_books_is_deterministic():
    a, b = M.compute_books(), M.compute_books()
    assert a["naive"] == b["naive"] and a["disciplined"] == b["disciplined"]


# ── idea #3: cross-desk blend (the TIER DEFAULT — most load-bearing finding) ─────────────────────────
def _crossdesk_or_skip():
    # The deep Pendle PT history / rates-carry series live under data/ (gitignored, runtime-only), so a
    # clean checkout / CI has them absent — compute() then RAISES FileNotFoundError (not just returns
    # None). Skip in that case: a data-availability gap, not a logic regression (exercised locally).
    try:
        res = CD.compute()
    except FileNotFoundError as exc:
        pytest.skip(f"rates-carry committed data absent (clean checkout / CI) — cross-desk not computable: {exc}")
    if res is None:
        pytest.skip("rates-carry committed data absent (clean checkout) — cross-desk not computable")
    return res


def test_crossdesk_blend_cuts_drawdown_vs_solo_susde_at_comparable_yield():
    # THE tier-default claim (idea #3): a decorrelated blend keeps ~the same yield as solo sUSDe while
    # cutting drawdown hard → higher Calmar. Qualitative direction, not exact numbers.
    res = _crossdesk_or_skip()
    solo, best = res["solo_susde"], res["best"]
    assert best["maxdd"] < solo["maxdd"], (best, solo)          # blend draws down far less
    assert best["calmar"] > solo["calmar"], (best, solo)        # → better risk-adjusted
    # yield is roughly preserved (the whole point: diversification does NOT cost much yield here)
    assert best["apy"] >= solo["apy"] * 0.85, (best, solo)


def test_crossdesk_best_blend_is_the_2550_25_tier_default():
    res = _crossdesk_or_skip()
    assert res["best"]["weights"] == [0.25, 0.5, 0.25], res["best"]
    # and the default entry matches the best (they are the same blend)
    assert res["default_25_50_25"]["calmar"] == res["best"]["calmar"]


def test_crossdesk_susde_and_rates_are_decorrelated():
    # the mechanism: sUSDe and rates-carry are near-uncorrelated (that is WHY the blend cuts DD).
    res = _crossdesk_or_skip()
    assert abs(res["corr_susde_rates"]) < 0.5, res["corr_susde_rates"]


def test_crossdesk_compute_is_deterministic():
    try:
        a, b = CD.compute(), CD.compute()
    except FileNotFoundError as exc:
        pytest.skip(f"rates-carry committed data absent (clean checkout / CI): {exc}")
    if a is None:
        pytest.skip("rates-carry data absent")
    assert a["solo_susde"] == b["solo_susde"] and a["best"]["calmar"] == b["best"]["calmar"]


# ── idea #6: Carry-Preserving Crisis Rotation (CPCR) ──────────────────────────────────────────────
_CPCR = _load(_ROOT / "scripts" / "carry_preserving_rotation.py", "_cpcr_under_test")


def _cpcr_susde_or_skip():
    # sUSDe realized series lives under data/ (gitignored, runtime-only) → absent on a clean checkout /
    # CI, where _load_susde_returns() RAISES FileNotFoundError. Skip there (data-availability, not logic).
    try:
        return _CPCR._load_susde_returns()
    except FileNotFoundError as exc:
        pytest.skip(f"sUSDe realized series absent (clean checkout / CI): {exc}")


def test_cpcr_beats_fixed_blend_on_calmar():
    """The de-risk SIGNAL (any destination) must beat static 25/50/25 blend on risk-adjusted return.
    This is the load-bearing claim of idea #6: signal-triggered rebalancing > passive fixed blend."""
    r_susde = _cpcr_susde_or_skip()
    dates = sorted(r_susde)
    r_rates, _ = _CPCR._load_rates_returns(dates)
    daily_floor = _CPCR.RWA_FLOOR_APY_PCT / 100.0 / 365.0
    r_floor = {d: daily_floor for d in dates}

    eq_fixed = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                                   _CPCR.NORMAL_WEIGHTS, _CPCR.NORMAL_WEIGHTS, 0.0, 999)
    eq_cpcr  = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                                   _CPCR.NORMAL_WEIGHTS, _CPCR.ROTATED_WEIGHTS, 0.002, 3)
    _, _, c_fixed = _CPCR._m(eq_fixed)
    _, _, c_cpcr  = _CPCR._m(eq_cpcr)
    assert isinstance(c_fixed, float) and isinstance(c_cpcr, float)
    assert c_cpcr > c_fixed, f"CPCR Calmar {c_cpcr:.2f} should beat fixed {c_fixed:.2f}"


def test_cpcr_carry_destination_not_worse_than_floor_destination():
    """CPCR (route to rates-carry) must be >= de-risk-to-floor on Calmar.
    Even tiny positive edge demonstrates 'carry-preserve direction is correct'."""
    r_susde = _cpcr_susde_or_skip()
    dates = sorted(r_susde)
    r_rates, _ = _CPCR._load_rates_returns(dates)
    daily_floor = _CPCR.RWA_FLOOR_APY_PCT / 100.0 / 365.0
    r_floor = {d: daily_floor for d in dates}

    eq_floor = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                                   _CPCR.NORMAL_WEIGHTS, _CPCR.TO_FLOOR_WEIGHTS, 0.002, 3)
    eq_cpcr  = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                                   _CPCR.NORMAL_WEIGHTS, _CPCR.ROTATED_WEIGHTS, 0.002, 3)
    _, _, c_floor = _CPCR._m(eq_floor)
    _, _, c_cpcr  = _CPCR._m(eq_cpcr)
    assert isinstance(c_floor, float) and isinstance(c_cpcr, float)
    # direction must be correct: carry-preserve >= floor-route
    assert c_cpcr >= c_floor, f"CPCR Calmar {c_cpcr:.3f} should be >= floor-route {c_floor:.3f}"


def test_cpcr_is_deterministic():
    """Two runs produce identical equity curves (deterministic, no randomness)."""
    r_susde = _cpcr_susde_or_skip()
    dates = sorted(r_susde)
    r_rates, _ = _CPCR._load_rates_returns(dates)
    daily_floor = _CPCR.RWA_FLOOR_APY_PCT / 100.0 / 365.0
    r_floor = {d: daily_floor for d in dates}

    eq_a = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                               _CPCR.NORMAL_WEIGHTS, _CPCR.ROTATED_WEIGHTS, 0.002, 3)
    eq_b = _CPCR._run_strategy(dates, r_susde, r_rates, r_floor,
                               _CPCR.NORMAL_WEIGHTS, _CPCR.ROTATED_WEIGHTS, 0.002, 3)
    assert eq_a == eq_b, "CPCR must be deterministic"
