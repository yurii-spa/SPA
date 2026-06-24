"""
spa_core/tests/test_tier1_monte_carlo.py — tests for the Tier-1 Monte-Carlo module.

Pure stdlib pytest. Asserts determinism (fixed seed), CI ordering (p5<=p50<=p95),
graceful insufficient-data handling, and build_report structure. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.backtesting.tier1 import monte_carlo as mc


# A synthetic per-protocol series with enough autocorrelated days for a real bootstrap.
def _fake_series_map():
    # 120 days, gently varying APY (decimal) — no network, fully deterministic.
    # build proper ISO dates
    import datetime
    base = datetime.date(2024, 1, 1)
    series = {}
    for i in range(120):
        d = (base + datetime.timedelta(days=i)).isoformat()
        series[d] = 0.03 + 0.02 * ((i % 30) / 30.0)
    return {"protoA": series, "protoB": {k: v * 0.9 for k, v in series.items()}}


def test_daily_yield_series_ok():
    sm = _fake_series_map()
    res = mc.daily_yield_series({"protoA": 0.6, "protoB": 0.4}, series_map=sm)
    assert res["status"] == "ok"
    assert res["n_days"] >= mc.MIN_DAYS
    # daily yields are blended_apy/365, so well below the APY decimal level
    assert all(0 < y < 0.05 / 365 * 5 for y in res["yields"])


def test_determinism_same_seed_same_result():
    sm = _fake_series_map()
    alloc = {"protoA": 0.6, "protoB": 0.4}
    a = mc.mc_strategy(alloc, n_paths=300, block=15, series_map=sm)
    b = mc.mc_strategy(alloc, n_paths=300, block=15, series_map=sm)
    assert a["status"] == "ok"
    assert a == b  # bit-for-bit identical → fixed seed is honored


def test_ci_ordering():
    sm = _fake_series_map()
    res = mc.mc_strategy({"protoA": 1.0}, n_paths=500, block=10, series_map=sm)
    assert res["status"] == "ok"
    assert res["apy_p5"] <= res["apy_p50"] <= res["apy_p95"]
    assert res["maxdd_p5"] <= res["maxdd_p50"] <= res["maxdd_p95"]
    # drawdown is a non-negative percent
    assert res["maxdd_p5"] >= 0.0


def test_insufficient_data_unknown_protocol():
    sm = _fake_series_map()
    # protocol with no real series → graceful insufficient_data, no exception
    res = mc.mc_strategy({"spark_susds": 1.0}, n_paths=100, series_map=sm)
    assert res["status"] == "insufficient_data"
    assert res["n_paths"] == 0
    assert res["apy_p50"] is None and res["maxdd_p50"] is None


def test_insufficient_history_short_series():
    short = {"protoA": {"2024-01-%02d" % (i + 1): 0.04 for i in range(5)}}
    res = mc.mc_strategy({"protoA": 1.0}, n_paths=50, series_map=short)
    assert res["status"] == "insufficient_history"
    assert res["n_paths"] == 0


def test_empty_allocation():
    res = mc.mc_strategy({"cash": 1.0}, n_paths=50, series_map=_fake_series_map())
    assert res["status"] == "insufficient_data"


def test_percentile_helper():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mc._percentile(vals, 0.0) == 1.0
    assert mc._percentile(vals, 1.0) == 5.0
    assert mc._percentile(vals, 0.5) == 3.0


def test_build_report_structure_no_write():
    rep = mc.build_report(write=False, n_paths=200, block=15)
    assert rep["model"] == "tier1_monte_carlo"
    assert rep["method"] == "stationary_block_bootstrap"
    assert rep["seed"] == 42
    assert rep["llm_forbidden"] is True
    assert "strategies" in rep and isinstance(rep["strategies"], list)
    assert rep["validated_count"] == len(rep["strategies"])
    for r in rep["strategies"]:
        assert "id" in r and "allocation" in r and "mc" in r
        m = r["mc"]
        assert "status" in m
        if m["status"] == "ok":
            assert m["apy_p5"] <= m["apy_p50"] <= m["apy_p95"]
            assert m["maxdd_p5"] <= m["maxdd_p50"] <= m["maxdd_p95"]


def test_build_report_atomic_write(tmp_path, monkeypatch):
    out = tmp_path / "tier1_monte_carlo.json"
    monkeypatch.setattr(mc, "_OUT", out)
    monkeypatch.setattr(mc, "_DATA", tmp_path)
    rep = mc.build_report(write=True, n_paths=100, block=10)
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["model"] == "tier1_monte_carlo"
    assert on_disk["validated_count"] == rep["validated_count"]
