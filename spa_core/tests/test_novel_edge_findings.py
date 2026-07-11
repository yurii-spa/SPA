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

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _ROOT / "scripts" / "refusal_gate_overlay.py"


def _load_overlay():
    spec = importlib.util.spec_from_file_location("_refusal_gate_overlay_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_overlay()


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
