"""Tests for spa_core/backtesting/tier1/attribution.py (PARALLEL, stdlib, deterministic)."""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.backtesting.tier1 import attribution as attr_mod


def _fake_series():
    """Two protocols with constant APY (decimal) over a 50-day axis, different tiers.
    aave_v3 -> T1, morpho_steakhouse -> T2 (per tail_risk.PROTOCOL_TIER)."""
    dates = [f"2025-01-{d:02d}" for d in range(1, 26)] + [f"2025-02-{d:02d}" for d in range(1, 26)]
    return {
        "aave_v3": {d: 0.04 for d in dates},            # 4% APY, T1
        "morpho_steakhouse": {d: 0.06 for d in dates},  # 6% APY, T2
    }


def test_contributions_sum_to_total():
    sm = _fake_series()
    res = attr_mod.attribute({"aave_v3": 0.5, "morpho_steakhouse": 0.5}, sm)
    assert res["status"] == "ok"
    s = sum(p["contribution_pct"] for p in res["by_protocol"])
    assert res["total_apy_pct"] == pytest.approx(s, abs=1e-3)
    # 0.5*4 + 0.5*6 = 5.0
    assert res["total_apy_pct"] == pytest.approx(5.0, abs=1e-3)


def test_shares_sum_to_100():
    sm = _fake_series()
    res = attr_mod.attribute({"aave_v3": 0.5, "morpho_steakhouse": 0.5}, sm)
    total_share = sum(p["share_pct"] for p in res["by_protocol"])
    assert total_share == pytest.approx(100.0, abs=0.1)


def test_single_protocol_attributes_100():
    sm = _fake_series()
    res = attr_mod.attribute({"aave_v3": 1.0}, sm)
    assert len(res["by_protocol"]) == 1
    p = res["by_protocol"][0]
    assert p["protocol"] == "aave_v3"
    assert p["share_pct"] == pytest.approx(100.0, abs=0.1)
    assert p["contribution_pct"] == pytest.approx(res["total_apy_pct"], abs=1e-3)
    assert res["top_contributor"] == "aave_v3"
    assert res["total_apy_pct"] == pytest.approx(4.0, abs=1e-3)


def test_by_tier_sums_correct():
    sm = _fake_series()
    res = attr_mod.attribute({"aave_v3": 0.5, "morpho_steakhouse": 0.5}, sm)
    bt = res["by_tier"]
    # tier contributions sum to total
    assert sum(bt.values()) == pytest.approx(res["total_apy_pct"], abs=1e-3)
    # 0.5*4 in T1, 0.5*6 in T2
    assert bt["T1"] == pytest.approx(2.0, abs=1e-3)
    assert bt["T2"] == pytest.approx(3.0, abs=1e-3)


def test_top_contributor_is_largest():
    sm = _fake_series()
    # higher weight on the higher-APY protocol -> it dominates
    res = attr_mod.attribute({"aave_v3": 0.2, "morpho_steakhouse": 0.8}, sm)
    assert res["top_contributor"] == "morpho_steakhouse"
    contribs = {p["protocol"]: p["contribution_pct"] for p in res["by_protocol"]}
    assert contribs["morpho_steakhouse"] > contribs["aave_v3"]


def test_renormalises_over_covered_weight():
    sm = _fake_series()
    # cash + an uncovered protocol are dropped; weights renormalise over covered.
    res = attr_mod.attribute(
        {"aave_v3": 0.25, "morpho_steakhouse": 0.25, "cash": 0.3, "unknown_proto": 0.2}, sm)
    # both covered protocols had weight 0.25 -> renormalise to 0.5 each
    weights = {p["protocol"]: p["weight"] for p in res["by_protocol"]}
    assert weights["aave_v3"] == pytest.approx(0.5, abs=1e-3)
    assert weights["morpho_steakhouse"] == pytest.approx(0.5, abs=1e-3)
    # blended APY = 0.5*4 + 0.5*6 = 5.0
    assert res["total_apy_pct"] == pytest.approx(5.0, abs=1e-3)


def test_insufficient_data():
    sm = _fake_series()
    res = attr_mod.attribute({"cash": 1.0}, sm)
    assert res["status"] == "insufficient_data"
    assert res["total_apy_pct"] == 0.0
    assert res["by_protocol"] == []
    assert res["top_contributor"] is None


def test_empty_allocation():
    res = attr_mod.attribute({}, _fake_series())
    assert res["status"] == "insufficient_data"


def test_determinism():
    sm = _fake_series()
    alloc = {"aave_v3": 0.4, "morpho_steakhouse": 0.6}
    a = attr_mod.attribute(alloc, sm)
    b = attr_mod.attribute(alloc, sm)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_oos_window_present():
    sm = _fake_series()
    res = attr_mod.attribute({"aave_v3": 0.5, "morpho_steakhouse": 0.5}, sm)
    assert "oos" in res
    # constant series -> OOS total equals full total
    assert res["oos"]["total_apy_pct"] == pytest.approx(res["total_apy_pct"], abs=1e-3)
    oos_shares = sum(p["share_pct"] for p in res["oos"]["by_protocol"])
    assert oos_shares == pytest.approx(100.0, abs=0.1)


def test_build_report_structure(tmp_path, monkeypatch):
    out_file = tmp_path / "tier1_attribution.json"
    monkeypatch.setattr(attr_mod, "_OUT", out_file)
    monkeypatch.setattr(attr_mod, "_DATA", tmp_path)
    rep = attr_mod.build_report(write=True)
    assert rep["model"] == "tier1_attribution"
    assert rep["llm_forbidden"] is True
    assert "strategies" in rep
    assert rep["n_validated"] == len(rep["strategies"])
    # written atomically and reloadable
    assert out_file.exists()
    reloaded = json.loads(out_file.read_text())
    assert reloaded["model"] == "tier1_attribution"
    # each strategy entry has the expected shape
    for sid, info in rep["strategies"].items():
        assert "allocation" in info
        assert "attribution" in info
        a = info["attribution"]
        assert "total_apy_pct" in a and "by_protocol" in a and "by_tier" in a


def test_build_report_no_write_does_not_touch_real_file(monkeypatch, tmp_path):
    # write=False must not create the output file
    out_file = tmp_path / "nope.json"
    monkeypatch.setattr(attr_mod, "_OUT", out_file)
    monkeypatch.setattr(attr_mod, "_DATA", tmp_path)
    rep = attr_mod.build_report(write=False)
    assert "strategies" in rep
    assert not out_file.exists()


def test_real_data_attribute_runs():
    # smoke test against the real cached series + a known multi-protocol allocation
    sm = oos_mod_series = attr_mod.oos_mod.load_protocol_series()
    if not sm:
        pytest.skip("no real series cache available")
    res = attr_mod.attribute({"aave_v3": 0.6, "compound_v3": 0.4}, sm)
    if res["status"] == "ok":
        s = sum(p["contribution_pct"] for p in res["by_protocol"])
        assert res["total_apy_pct"] == pytest.approx(s, abs=1e-2)
        shares = sum(p["share_pct"] for p in res["by_protocol"])
        assert shares == pytest.approx(100.0, abs=0.5)
