"""
Tests for spa_core/backtesting/tier1/walk_forward_full.py — deepened Tier-1 validation.

Pure stdlib, deterministic. Uses synthetic per-protocol APY series so behaviour is exact
and does not depend on the live DeFiLlama cache.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

from spa_core.backtesting.tier1 import walk_forward_full as wf


# ---------------------------------------------------------------------------
# synthetic series helpers
# ---------------------------------------------------------------------------
def _series(values, start="2020-01-01"):
    """List of decimal APYs → {date_iso: apy} starting at `start`, one per day."""
    d0 = datetime.date.fromisoformat(start)
    return {(d0 + datetime.timedelta(days=i)).isoformat(): float(v)
            for i, v in enumerate(values)}


def _flat(apy, n, start="2020-01-01"):
    return _series([apy] * n, start)


# ===========================================================================
# Part A — window slicing
# ===========================================================================
def test_window_slicing_correct():
    # n=400, train=180, test=60, step=60
    got = list(wf._windows(400, 180, 60, 60))
    assert got[0] == (0, 180, 180, 240)
    assert got[1] == (60, 240, 240, 300)
    # every window has train of 180 and test of 60
    for (tlo, thi, slo, shi) in got:
        assert thi - tlo == 180
        assert shi - slo == 60
        assert slo == thi  # test starts right after train
    # last window must fit inside n
    assert got[-1][3] <= 400


def test_test_windows_non_overlapping_when_step_ge_test():
    # step == test → consecutive non-overlapping test windows
    got = list(wf._windows(600, 180, 60, 60))
    test_ranges = [(slo, shi) for (_, _, slo, shi) in got]
    for a, b in zip(test_ranges, test_ranges[1:]):
        assert a[1] <= b[0], f"overlap between {a} and {b}"


def test_window_slicing_insufficient():
    # not enough days for even one window
    assert list(wf._windows(100, 180, 60, 60)) == []


# ===========================================================================
# Part A — robustness on stable vs decaying series
# ===========================================================================
def test_wf_robust_true_for_stable_series():
    n = 500
    sm = {"p": _flat(0.05, n)}  # constant 5% APY → identical train/test returns
    res = wf.walk_forward({"p": 1.0}, train=180, test=60, step=60, series_map=sm)
    assert res["status"] == "ok"
    assert res["n_windows"] >= 2
    assert res["wf_robust"] is True
    assert res["consistency_pct"] == 100.0
    # every window: positive test return, in band
    for w in res["windows"]:
        assert w["holds"] is True
        assert w["test_return_pct"] > 0


def test_wf_robust_false_for_decaying_series():
    # APY decays steeply (halves every ~60d): each test window's return sits far below the
    # preceding train window's return → outside the +/-50% band → windows fail.
    n = 600
    vals = [0.15 * (0.5 ** (i / 60.0)) for i in range(n)]
    sm = {"p": _series(vals)}
    res = wf.walk_forward({"p": 1.0}, train=180, test=60, step=60, series_map=sm)
    assert res["status"] == "ok"
    assert res["wf_robust"] is False
    assert res["consistency_pct"] < wf.WF_CONSISTENCY_PASS * 100.0


def test_wf_insufficient_history_graceful():
    sm = {"p": _flat(0.05, 100)}  # < train+test
    res = wf.walk_forward({"p": 1.0}, train=180, test=60, step=60, series_map=sm)
    assert res["status"] == "insufficient_history"
    assert res["wf_robust"] is None
    assert res["windows"] == []


def test_wf_insufficient_data_graceful():
    # allocation has no protocol present in the series_map
    res = wf.walk_forward({"unknown_proto": 1.0}, series_map={"p": _flat(0.05, 500)})
    assert res["status"] == "insufficient_data"
    assert res["wf_robust"] is None


def test_wf_deterministic():
    sm = {"p": _flat(0.05, 500), "q": _flat(0.03, 500)}
    a = wf.walk_forward({"p": 0.6, "q": 0.4}, series_map=sm)
    b = wf.walk_forward({"p": 0.6, "q": 0.4}, series_map=sm)
    assert a == b


def test_wf_accepts_usd_amounts():
    # USD-amount allocation should normalize to weights and behave like the weight form
    sm = {"p": _flat(0.05, 500)}
    w_form = wf.walk_forward({"p": 1.0}, series_map=sm)
    usd_form = wf.walk_forward({"p": 50000.0, "cash": 7000.0}, series_map=sm)
    assert usd_form["wf_robust"] == w_form["wf_robust"]
    assert usd_form["consistency_pct"] == w_form["consistency_pct"]


# ===========================================================================
# helpers: return + drawdown math
# ===========================================================================
def test_equity_and_annualized_return():
    eq = wf._equity_curve([0.05] * wf.DAYS_PER_YEAR)  # one year at 5% APY
    # after 365 daily-compounded steps of (1.05)^(1/365), equity ~= 1.05
    assert abs(eq[-1] - 1.05) < 1e-6
    ann = wf._annualized_return_pct(eq)
    assert abs(ann - 5.0) < 0.05


def test_max_drawdown():
    assert wf._max_drawdown_pct([1.0, 1.0, 1.0]) == 0.0  # monotone flat
    dd = wf._max_drawdown_pct([1.0, 1.2, 0.9, 1.1])      # peak 1.2 → trough 0.9
    assert abs(dd - 25.0) < 1e-6


# ===========================================================================
# Part B — capacity at AUM
# ===========================================================================
def _tvl():
    # aave: $200M pool; comp: $40M pool
    return {"aave_v3": 200_000_000.0, "compound_v3": 40_000_000.0}


def test_capacity_monotonic_higher_aum_more_utilization():
    alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
    res = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    assert res["status"] == "ok"
    utils = [res["scenarios"][k]["worst_utilization_pct"] for k, _ in wf.AUM_SCENARIOS]
    # strictly increasing with AUM
    assert utils == sorted(utils)
    assert all(b > a for a, b in zip(utils, utils[1:]))


def test_capacity_fewer_fit_as_aum_grows():
    alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
    res = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    fits = [res["scenarios"][k]["fits"] for k, _ in wf.AUM_SCENARIOS]
    # once it stops fitting it never starts fitting again (monotone non-increasing)
    seen_false = False
    for f in fits:
        if seen_false:
            assert f is False
        if f is False:
            seen_false = True


def test_max_safe_aum_consistent_with_scenarios():
    alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
    res = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    msa = res["max_safe_aum_usd"]
    # binding = compound_v3: 40M * 0.02 / 0.5 = 1.6M
    assert abs(msa - 1_600_000.0) < 1.0
    assert res["binding_protocol"] == "compound_v3"
    # every scenario with aum <= max_safe should fit; above should not
    for k, aum in wf.AUM_SCENARIOS:
        if aum <= msa:
            assert res["scenarios"][k]["fits"] is True
        else:
            assert res["scenarios"][k]["fits"] is False


def test_capacity_binding_protocol_is_worst():
    # aave gets a tiny weight on a huge pool; compound a big weight on a small pool
    alloc = {"aave_v3": 0.9, "compound_v3": 0.1}
    res = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    # compound: 40M pool, even 10% of AUM is binding before aave's 90% of a 200M pool
    # at 100M: aave util = 90M/200M=45%, comp util = 10M/40M=25% → aave worst
    s100 = res["scenarios"]["100M"]
    assert s100["binding_protocol"] == "aave_v3"


def test_capacity_insufficient_data():
    res = wf.capacity_at_aum({"unknown": 1.0}, tvl_map={"aave_v3": 1e8})
    assert res["status"] == "insufficient_data"
    assert res["max_safe_aum_usd"] is None
    # scenarios still present with None fits
    assert set(res["scenarios"].keys()) == {k for k, _ in wf.AUM_SCENARIOS}


def test_capacity_accepts_usd_amounts():
    res = wf.capacity_at_aum({"aave_v3": 50000.0, "compound_v3": 50000.0, "cash": 7000.0},
                             tvl_map=_tvl())
    # normalizes to 0.5/0.5 → same binding capacity
    assert abs(res["max_safe_aum_usd"] - 1_600_000.0) < 1.0


def test_capacity_deterministic():
    alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
    a = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    b = wf.capacity_at_aum(alloc, tvl_map=_tvl())
    assert a == b


# ===========================================================================
# build_report
# ===========================================================================
def test_build_report_structure():
    rep = wf.build_report(write=False)
    assert rep["model"] == "tier1_walk_forward_full"
    assert rep["llm_forbidden"] is True
    assert "part_a" in rep["method"] and "part_b" in rep["method"]
    assert "strategies" in rep
    assert "live_portfolio" in rep
    assert isinstance(rep["n_validated_strategies"], int)
    # each strategy entry has the three sub-blocks
    for sid, blk in rep["strategies"].items():
        assert set(blk.keys()) == {"allocation", "walk_forward", "capacity"}
    # serializable
    json.dumps(rep)


def test_build_report_writes_atomic(tmp_path, monkeypatch):
    out = tmp_path / "tier1_walk_forward.json"
    monkeypatch.setattr(wf, "_OUT", out)
    monkeypatch.setattr(wf, "_DATA", tmp_path)
    rep = wf.build_report(write=True)
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["model"] == rep["model"]
    # no leftover temp files
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tier1wf_")]
    assert leftovers == []
