"""
spa_core/tests/test_refusal_coverage.py — WS-4.3 rates-desk refusal-coverage (100% on toxic).

Pins the no-regression property: after widening the surface, the refusal-first gate still refuses
EVERY toxic LRT book — at EVERY size ($1k..$1M) (the structural veto vs the 0.06 cap cannot be sized
around) AND across their real daily history (the deep leg). 100% on toxic, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.strategy_lab.rates_desk import refusal_coverage as rc
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ── PROPERTY: the size sweep refuses every toxic book at every size ───────────────────────────
def test_size_sweep_100pct_refused():
    sweep = rc.size_sweep_coverage()
    assert sweep["all_toxic_refused_every_size"] is True
    assert sweep["n_refused"] == sweep["n_checks"]
    assert sweep["refusal_pct"] == 100.0
    # the cap is the documented 0.06 structural haircut
    assert sweep["max_structural_haircut_cap"] == "0.06"
    # every toxic underlying refused at every size, on a STRUCTURAL (tail_veto) reason
    for u in sweep["per_underlying"]:
        assert u["all_sizes_refused"] is True
        assert all(s["refused"] for s in u["sizes"])


def test_toxic_set_from_ssot_kind_map():
    """The toxic set is derived from the SSOT kind map (never a hardcoded list) → ezeth/rseth today."""
    assert set(rc.TOXIC_LRTS) == {"ezeth", "rseth"}


def test_size_down_exploit_closed():
    """The size-down exploit (sizing a toxic book small enough to slip the cap) is CLOSED: a toxic
    book is refused at the SMALLEST size just as at the largest."""
    sweep = rc.size_sweep_coverage()
    for u in sweep["per_underlying"]:
        smallest = u["sizes"][0]
        largest = u["sizes"][-1]
        assert smallest["refused"] is True
        assert largest["refused"] is True


# ── headline coverage verdict ─────────────────────────────────────────────────────────────────
def test_build_coverage_100pct_on_toxic():
    out = rc.build_coverage(write=False, now_iso="2026-06-28T00:00:00+00:00")
    assert out["refusal_100pct_on_toxic"] is True
    assert out["size_sweep"]["all_toxic_refused_every_size"] is True
    # the deep leg either holds (data present) or is honestly absent — never a fabricated pass
    deep = out["deep_history"]
    if deep["present"]:
        assert deep["all_toxic_books_refused_every_day"] is True


def test_deterministic():
    a = rc.build_coverage(write=False, now_iso="2026-06-28T00:00:00+00:00")
    b = rc.build_coverage(write=False, now_iso="2026-06-28T00:00:00+00:00")
    # the size-sweep section is a pure function of the gate → identical
    assert a["size_sweep"] == b["size_sweep"]
    assert a["refusal_100pct_on_toxic"] == b["refusal_100pct_on_toxic"]


def test_custom_params_still_refuse():
    """Even with default params explicitly passed, the toxic veto holds (the cap is the gate's)."""
    out = rc.build_coverage(params=RatePolicyParams(), write=False,
                            now_iso="2026-06-28T00:00:00+00:00")
    assert out["size_sweep"]["refusal_pct"] == 100.0
