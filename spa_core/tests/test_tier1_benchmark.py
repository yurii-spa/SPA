"""
test_tier1_benchmark.py — tests for tier1/benchmark.py (benchmark-relative metrics).

Pure stdlib, deterministic, no network. Uses a synthetic in-memory series_map so the
tests do not depend on the live bee cache (and so exact numeric relations are checkable).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from datetime import date, timedelta

from spa_core.backtesting.tier1 import benchmark as bm

_BASE = date(2024, 1, 1)


def _dates(n: int):
    return [(_BASE + timedelta(days=i)).isoformat() for i in range(n)]


def _flat_series(apy_decimal: float, n: int = 60) -> dict:
    """{date_iso: apy_decimal} — flat APY over n consecutive real calendar days."""
    return {d: apy_decimal for d in _dates(n)}


def _make_series_map(aave_apy=0.05, strat_apy=0.06, n=60):
    return {
        "aave_v3": _flat_series(aave_apy, n),
        "compound_v3": _flat_series(strat_apy, n),
    }


# ---------------------------------------------------------------------------
def test_ir_equals_excess_over_tracking_error():
    """Information ratio must equal excess_vs_aave / tracking_error (when TE > 0)."""
    # Strategy with day-to-day variation so tracking error is non-zero.
    ds = _dates(40)
    aave = {d: 0.05 for d in ds}
    comp = {d: (0.06 if i % 2 == 0 else 0.07) for i, d in enumerate(ds)}
    sm = {"aave_v3": aave, "compound_v3": comp}
    out = bm.benchmark_relative({"compound_v3": 1.0}, sm)
    assert out["status"] == "ok"
    te = out["tracking_error_pct"]
    assert te > 0
    # IR is computed from full-precision excess/TE; the reported fields are rounded to
    # 4 dp, so recomputing from them carries compounded rounding error. Allow for it.
    expected_ir = out["excess_vs_aave_pct"] / te
    assert math.isclose(out["information_ratio"], expected_ir, rel_tol=2e-3)


def test_holding_aave_is_neutral():
    """Holding 100% aave_v3 → excess_vs_aave ~ 0, pct_outperform ~ 100 (s >= a always)."""
    sm = _make_series_map(aave_apy=0.05, strat_apy=0.06, n=50)
    out = bm.benchmark_relative({"aave_v3": 1.0}, sm)
    assert out["status"] == "ok"
    assert abs(out["excess_vs_aave_pct"]) < 1e-6
    assert abs(out["tracking_error_pct"]) < 1e-6
    # No active risk and no excess → IR defined as 0.
    assert out["information_ratio"] == 0.0
    # Strategy == benchmark every day → s >= a holds every day → ~100% neutral.
    assert math.isclose(out["pct_days_outperform"], 100.0, abs_tol=1e-9)
    # strategy_apy ~ aave_apy ~ 5%.
    assert math.isclose(out["strategy_apy"], out["aave_apy"], abs_tol=1e-6)


def test_excess_vs_rf_and_aave_directions():
    """A 6% strategy vs 5% aave and 5% rf → positive excess on both."""
    sm = _make_series_map(aave_apy=0.05, strat_apy=0.06, n=50)
    out = bm.benchmark_relative({"compound_v3": 1.0}, sm)
    assert out["status"] == "ok"
    assert out["strategy_apy"] > out["aave_apy"]
    assert out["excess_vs_rf_pct"] > 0
    assert out["excess_vs_aave_pct"] > 0
    # flat 6% strat outperforms flat 5% aave every overlapping day.
    assert math.isclose(out["pct_days_outperform"], 100.0, abs_tol=1e-9)


def test_underperformer():
    """A 4% strategy vs 5% aave → negative excess, 0% outperform days."""
    sm = _make_series_map(aave_apy=0.05, strat_apy=0.04, n=50)
    out = bm.benchmark_relative({"compound_v3": 1.0}, sm)
    assert out["status"] == "ok"
    assert out["excess_vs_aave_pct"] < 0
    assert out["excess_vs_rf_pct"] < 0
    assert math.isclose(out["pct_days_outperform"], 0.0, abs_tol=1e-9)


def test_determinism():
    """Same inputs → identical output."""
    sm = _make_series_map(aave_apy=0.05, strat_apy=0.062, n=55)
    a = bm.benchmark_relative({"compound_v3": 0.7, "aave_v3": 0.3, "cash": 0.0}, sm)
    b = bm.benchmark_relative({"compound_v3": 0.7, "aave_v3": 0.3, "cash": 0.0}, sm)
    assert a == b


def test_insufficient_data_no_protocols():
    """Empty / cash-only / unknown-protocol allocations are handled gracefully."""
    sm = _make_series_map()
    for alloc in ({}, {"cash": 1.0}, {"unknown_proto": 1.0}):
        out = bm.benchmark_relative(alloc, sm)
        assert out["status"] == "insufficient_data"
        assert out["strategy_apy"] is None
        assert out["information_ratio"] is None
        assert out["rf_apy"] == bm.RISK_FREE_APY_PCT


def test_insufficient_history_short_overlap():
    """Fewer than MIN_OVERLAP_DAYS overlapping days → insufficient_history, graceful."""
    sm = _make_series_map(n=5)  # only 5 days
    out = bm.benchmark_relative({"compound_v3": 1.0}, sm)
    assert out["status"] == "insufficient_history"
    assert out["strategy_apy"] is None


def test_no_aave_benchmark():
    """If aave_v3 series absent, report no_aave_benchmark gracefully."""
    sm = {"compound_v3": _flat_series(0.06, 50)}
    out = bm.benchmark_relative({"compound_v3": 1.0}, sm)
    assert out["status"] == "no_aave_benchmark"
    assert out["aave_apy"] is None


def test_build_report_structure():
    """build_report(write=False) returns the documented envelope on real cache data."""
    rep = bm.build_report(write=False)
    for key in ("generated_at", "llm_forbidden", "risk_free_apy_pct",
                "aave_benchmark_protocol", "n_strategies", "results"):
        assert key in rep
    assert rep["llm_forbidden"] is True
    assert rep["risk_free_apy_pct"] == bm.RISK_FREE_APY_PCT
    assert isinstance(rep["results"], list)
    if rep["results"]:
        r = rep["results"][0]
        for key in ("id", "status", "rf_apy", "allocation"):
            assert key in r
