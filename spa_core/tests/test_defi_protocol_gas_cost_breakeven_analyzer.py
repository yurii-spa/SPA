"""
Tests for MP-1138 DeFiProtocolGasCostBreakevenAnalyzer
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_gas_cost_breakeven_analyzer import (
    analyze,
    analyze_portfolio,
    _total_gas_cost_usd,
    _gross_yield_usd,
    _net_yield_usd,
    _net_yield_after_gas_apr_pct,
    _gas_drag_pct_of_gross,
    _breakeven_holding_days,
    _breakeven_position_size_usd,
    _gas_efficiency_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolGasCostBreakevenAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_GAS_NEGLIGIBLE,
    CLASS_GAS_MINOR,
    CLASS_GAS_MODERATE,
    CLASS_GAS_HEAVY,
    CLASS_GAS_PROHIBITIVE,
    FLAG_GAS_EXCEEDS_YIELD,
    FLAG_NEVER_BREAKS_EVEN,
    FLAG_BREAKEVEN_AFTER_HORIZON,
    FLAG_POSITION_TOO_SMALL,
    FLAG_HIGH_HARVEST_DRAG,
    FLAG_GAS_NEGLIGIBLE,
    FLAG_NEGATIVE_NET_YIELD,
    FLAG_INSUFFICIENT_DATA,
    BREAKEVEN_SENTINEL_NEVER,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "gas_log.json")}


@pytest.fixture
def good_large_position():
    # Large, cheap, long hold -> negligible gas.
    return {
        "name": "stETH (good)",
        "principal_usd": 250000.0,
        "net_apr_pct": 4.0,
        "holding_days": 180.0,
        "entry_gas_usd": 12.0,
        "exit_gas_usd": 12.0,
        "harvest_gas_usd": 0.0,
        "harvest_count": 0.0,
    }


@pytest.fixture
def bad_small_position():
    # Small, expensive, frequent harvest -> prohibitive gas.
    return {
        "name": "USDC-LP (bad)",
        "principal_usd": 300.0,
        "net_apr_pct": 5.0,
        "holding_days": 30.0,
        "entry_gas_usd": 40.0,
        "exit_gas_usd": 40.0,
        "harvest_gas_usd": 15.0,
        "harvest_count": 4.0,
    }


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_safe_float_valid():
    assert _safe_float("3.5") == 3.5
    assert _safe_float(7) == 7.0


def test_safe_float_invalid():
    assert _safe_float(None) == 0.0
    assert _safe_float("abc") == 0.0
    assert _safe_float([], 1.0) == 1.0


def test_clamp_bounds():
    assert _clamp(-5) == 0.0
    assert _clamp(150) == 100.0
    assert _clamp(50) == 50.0
    assert _clamp(5, 0, 10) == 5


def test_total_gas_cost():
    assert _total_gas_cost_usd(40, 40, 15, 4) == 40 + 40 + 60
    assert _total_gas_cost_usd(0, 0, 0, 0) == 0.0


def test_total_gas_cost_floors_negatives():
    assert _total_gas_cost_usd(-10, -10, -5, -3) == 0.0


def test_gross_yield():
    # 100000 * 0.06 * (365/365) = 6000 for a full year
    assert _gross_yield_usd(100000, 6.0, 365.0) == pytest.approx(6000.0)
    # half year
    assert _gross_yield_usd(100000, 6.0, 182.5) == pytest.approx(3000.0)


def test_gross_yield_zero_principal():
    assert _gross_yield_usd(0, 6.0, 365) == 0.0


def test_net_yield():
    assert _net_yield_usd(6000, 100) == 5900.0
    assert _net_yield_usd(50, 100) == -50.0


def test_net_apr_after_gas():
    # net 5900 on 100000 over a year -> 5.9%
    assert _net_yield_after_gas_apr_pct(5900, 100000, 365) == pytest.approx(5.9)


def test_net_apr_after_gas_zero_principal():
    assert _net_yield_after_gas_apr_pct(100, 0, 365) == 0.0


def test_net_apr_after_gas_zero_days():
    assert _net_yield_after_gas_apr_pct(100, 1000, 0) == 0.0


def test_gas_drag_normal():
    assert _gas_drag_pct_of_gross(100, 1000) == pytest.approx(10.0)


def test_gas_drag_zero_gross_with_gas():
    assert _gas_drag_pct_of_gross(50, 0) == 999.0


def test_gas_drag_zero_gross_no_gas():
    assert _gas_drag_pct_of_gross(0, 0) == 0.0


def test_breakeven_days_normal():
    # daily yield 100000*0.06/365 ~ 16.44; gas 100 -> ~6.08 days
    days = _breakeven_holding_days(100000, 6.0, 100)
    assert days == pytest.approx(100 / (100000 * 0.06 / 365), rel=1e-6)


def test_breakeven_days_zero_gas():
    assert _breakeven_holding_days(100000, 6.0, 0) == 0.0


def test_breakeven_days_never_when_no_apr():
    assert _breakeven_holding_days(100000, 0.0, 100) == BREAKEVEN_SENTINEL_NEVER


def test_breakeven_days_never_when_no_principal():
    assert _breakeven_holding_days(0, 6.0, 100) == BREAKEVEN_SENTINEL_NEVER


def test_breakeven_size_normal():
    # need gross_yield = gas; yield_per_dollar = 0.06 * (30/365)
    size = _breakeven_position_size_usd(6.0, 30.0, 100.0)
    expected = 100.0 / (0.06 * (30.0 / 365.0))
    assert size == pytest.approx(expected, rel=1e-6)


def test_breakeven_size_zero_gas():
    assert _breakeven_position_size_usd(6.0, 30.0, 0.0) == 0.0


def test_breakeven_size_never_when_no_apr():
    assert _breakeven_position_size_usd(0.0, 30.0, 100.0) == BREAKEVEN_SENTINEL_NEVER


def test_breakeven_size_never_when_zero_days():
    assert _breakeven_position_size_usd(6.0, 0.0, 100.0) == BREAKEVEN_SENTINEL_NEVER


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_efficiency_score_no_data():
    assert _gas_efficiency_score(0, 0, 0, 30, has_data=False) == 0.0


def test_efficiency_score_range():
    s = _gas_efficiency_score(10.0, 5000.0, 5.0, 30.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_efficiency_score_good_high():
    # tiny drag, positive net, quick breakeven -> high score
    s = _gas_efficiency_score(2.0, 5000.0, 3.0, 180.0, has_data=True)
    assert s >= 90.0


def test_efficiency_score_bad_low():
    # huge drag, negative net, never breaks even -> low score
    s = _gas_efficiency_score(100.0, -200.0, BREAKEVEN_SENTINEL_NEVER, 30.0,
                              has_data=True)
    assert s <= 30.0


def test_efficiency_score_negative_net_zero_component():
    s_pos = _gas_efficiency_score(20.0, 100.0, 5.0, 30.0, has_data=True)
    s_neg = _gas_efficiency_score(20.0, -100.0, 5.0, 30.0, has_data=True)
    assert s_pos > s_neg


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data_prohibitive():
    assert _classify(0.0, has_data=False) == CLASS_GAS_PROHIBITIVE


def test_classify_negligible():
    assert _classify(2.0, has_data=True) == CLASS_GAS_NEGLIGIBLE


def test_classify_minor():
    assert _classify(10.0, has_data=True) == CLASS_GAS_MINOR


def test_classify_moderate():
    assert _classify(30.0, has_data=True) == CLASS_GAS_MODERATE


def test_classify_heavy():
    assert _classify(70.0, has_data=True) == CLASS_GAS_HEAVY


def test_classify_prohibitive():
    assert _classify(95.0, has_data=True) == CLASS_GAS_PROHIBITIVE


def test_classify_in_known_set():
    for drag in (0, 5, 20, 50, 90, 200):
        assert _classify(drag, has_data=True) in ALL_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# Grade tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,grade", [
    (95, "A"), (90, "A"),
    (80, "B"), (70, "B"),
    (60, "C"), (50, "C"),
    (40, "D"), (30, "D"),
    (10, "F"), (0, "F"),
])
def test_grade_bands(score, grade):
    assert _grade(score) == grade


def test_grade_in_known_set():
    for s in range(0, 101, 7):
        assert _grade(s) in ALL_GRADES


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(0, 0, 0, 0, 0, 30, 0, 0, CLASS_GAS_PROHIBITIVE, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_gas_exceeds_yield():
    f = _flags(120.0, -50.0, 10.0, 1000.0, 500.0, 30.0, 0.0, 0.0,
               CLASS_GAS_PROHIBITIVE, has_data=True)
    assert FLAG_GAS_EXCEEDS_YIELD in f
    assert FLAG_NEGATIVE_NET_YIELD in f


def test_flag_never_breaks_even():
    f = _flags(50.0, 10.0, BREAKEVEN_SENTINEL_NEVER, 100.0, 500.0, 30.0,
               0.0, 0.0, CLASS_GAS_MODERATE, has_data=True)
    assert FLAG_NEVER_BREAKS_EVEN in f


def test_flag_breakeven_after_horizon():
    f = _flags(50.0, 10.0, 60.0, 1000.0, 500.0, 30.0, 0.0, 0.0,
               CLASS_GAS_MODERATE, has_data=True)
    assert FLAG_BREAKEVEN_AFTER_HORIZON in f


def test_flag_position_too_small():
    # breakeven size 1000 > principal 500
    f = _flags(50.0, 10.0, 10.0, 1000.0, 500.0, 30.0, 0.0, 0.0,
               CLASS_GAS_MODERATE, has_data=True)
    assert FLAG_POSITION_TOO_SMALL in f


def test_flag_high_harvest_drag():
    # harvest gas 60 of total 100 -> 60% >= 50%
    f = _flags(20.0, 10.0, 5.0, 10.0, 5000.0, 30.0, 100.0, 60.0,
               CLASS_GAS_MINOR, has_data=True)
    assert FLAG_HIGH_HARVEST_DRAG in f


def test_flag_gas_negligible():
    f = _flags(2.0, 1000.0, 1.0, 10.0, 50000.0, 30.0, 0.0, 0.0,
               CLASS_GAS_NEGLIGIBLE, has_data=True)
    assert FLAG_GAS_NEGLIGIBLE in f


def test_flags_subset_of_all():
    f = _flags(120.0, -50.0, BREAKEVEN_SENTINEL_NEVER, 9999.0, 100.0, 30.0,
               80.0, 80.0, CLASS_GAS_PROHIBITIVE, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_GAS_PROHIBITIVE, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_prohibitive_nonempty():
    recs = _recommendations(CLASS_GAS_PROHIBITIVE, [], 110, 100, -10, 50, 5000,
                            -2.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_negligible_nonempty():
    recs = _recommendations(CLASS_GAS_NEGLIGIBLE, [], 5, 5000, 4995, 1, 0,
                            5.9, has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_good_position(good_large_position, tmp_log):
    r = analyze(good_large_position, config=tmp_log)
    assert r["classification"] in (CLASS_GAS_NEGLIGIBLE, CLASS_GAS_MINOR)
    assert r["net_yield_usd"] > 0.0
    assert r["gas_efficiency_score"] >= 70.0
    assert r["grade"] in ("A", "B")


def test_analyze_bad_position(bad_small_position, tmp_log):
    r = analyze(bad_small_position, config=tmp_log)
    assert r["classification"] in (CLASS_GAS_HEAVY, CLASS_GAS_PROHIBITIVE,
                                   CLASS_GAS_MODERATE)
    assert r["gas_efficiency_score"] <= 70.0


def test_analyze_total_gas_correct(bad_small_position, tmp_log):
    r = analyze(bad_small_position, config=tmp_log)
    assert r["total_gas_cost_usd"] == pytest.approx(40 + 40 + 15 * 4)
    assert r["harvest_gas_total_usd"] == pytest.approx(60.0)


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["gas_efficiency_score"] == 0.0
    assert r["classification"] == CLASS_GAS_PROHIBITIVE


def test_analyze_poor_data_quality(good_large_position, tmp_log):
    pos = dict(good_large_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"principal_usd": 100.0, "net_apr_pct": 1.0},
                principal_usd=100000.0, net_apr_pct=10.0, entry_gas_usd=5.0,
                exit_gas_usd=5.0, config=tmp_log)
    assert r["principal_usd"] == 100000.0
    assert r["net_apr_pct"] == 10.0


def test_analyze_result_keys(good_large_position, tmp_log):
    r = analyze(good_large_position, config=tmp_log)
    for key in (
        "name", "principal_usd", "net_apr_pct", "holding_days",
        "total_gas_cost_usd", "gross_yield_usd", "net_yield_usd",
        "net_yield_after_gas_apr_pct", "gas_drag_pct_of_gross",
        "breakeven_holding_days", "breakeven_position_size_usd",
        "gas_efficiency_score", "classification", "grade", "flags",
        "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"principal_usd": "abc", "net_apr_pct": None,
                 "entry_gas_usd": [], "harvest_count": {}}, config=tmp_log)
    assert isinstance(r, dict)
    assert "gas_efficiency_score" in r


def test_analyze_json_serialisable(bad_small_position, tmp_log):
    r = analyze(bad_small_position, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    # no inf / nan leaked
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_negative_net_yield_flag(tmp_log):
    r = analyze({"principal_usd": 100.0, "net_apr_pct": 2.0,
                 "holding_days": 30.0, "entry_gas_usd": 50.0,
                 "exit_gas_usd": 50.0}, config=tmp_log)
    assert r["net_yield_usd"] < 0.0
    assert FLAG_NEGATIVE_NET_YIELD in r["flags"]


def test_analyze_writes_log(good_large_position, tmp_log):
    analyze(good_large_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["most_gas_efficient_position"] is None
    assert r["avg_gas_efficiency_score"] == 0.0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_basic(good_large_position, bad_small_position, tmp_log):
    r = analyze_portfolio([good_large_position, bad_small_position],
                          config=tmp_log)
    assert r["total_positions"] == 2
    assert r["most_gas_efficient_position"] == "stETH (good)"
    assert r["least_gas_efficient_position"] == "USDC-LP (bad)"
    assert 0.0 <= r["avg_gas_efficiency_score"] <= 100.0


def test_portfolio_negative_count(tmp_log):
    bad = {"principal_usd": 100.0, "net_apr_pct": 1.0, "holding_days": 30.0,
           "entry_gas_usd": 50.0, "exit_gas_usd": 50.0}
    r = analyze_portfolio([bad, bad], config=tmp_log)
    assert r["negative_net_yield_count"] == 2


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(good_large_position, tmp_log):
    a = DeFiProtocolGasCostBreakevenAnalyzer(config=tmp_log)
    r = a.analyze(good_large_position)
    assert r["name"] == "stETH (good)"


def test_class_wrapper_portfolio(good_large_position, bad_small_position, tmp_log):
    a = DeFiProtocolGasCostBreakevenAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([good_large_position, bad_small_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolGasCostBreakevenAnalyzer(config=tmp_log)
    r = a.analyze(None, principal_usd=10000.0, net_apr_pct=5.0,
                  entry_gas_usd=10.0, exit_gas_usd=10.0)
    assert r["principal_usd"] == 10000.0


# ---------------------------------------------------------------------------
# Atomic log tests
# ---------------------------------------------------------------------------

def test_atomic_log_ring_buffer(tmp_path):
    log_path = str(tmp_path / "ring.json")
    for i in range(120):
        _atomic_log(log_path, {"i": i})
    with open(log_path) as fh:
        data = json.load(fh)
    assert len(data) == 100
    assert data[0]["i"] == 20
    assert data[-1]["i"] == 119


def test_atomic_log_corrupt_recovers(tmp_path):
    log_path = str(tmp_path / "corrupt.json")
    with open(log_path, "w") as fh:
        fh.write("{not json")
    _atomic_log(log_path, {"ok": True})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"ok": True}]


def test_atomic_log_non_list_recovers(tmp_path):
    log_path = str(tmp_path / "obj.json")
    with open(log_path, "w") as fh:
        json.dump({"some": "object"}, fh)
    _atomic_log(log_path, {"ok": 1})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"ok": 1}]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_gas_immediate_breakeven(tmp_log):
    r = analyze({"principal_usd": 10000.0, "net_apr_pct": 5.0,
                 "holding_days": 30.0}, config=tmp_log)
    assert r["total_gas_cost_usd"] == 0.0
    assert r["breakeven_holding_days"] == 0.0
    assert r["breakeven_position_size_usd"] == 0.0


def test_never_breakeven_serialisable(tmp_log):
    r = analyze({"principal_usd": 1000.0, "net_apr_pct": 0.0,
                 "entry_gas_usd": 50.0}, config=tmp_log)
    assert r["breakeven_holding_days"] == BREAKEVEN_SENTINEL_NEVER
    json.dumps(r)  # must not raise


def test_large_principal_negligible(tmp_log):
    r = analyze({"principal_usd": 10000000.0, "net_apr_pct": 5.0,
                 "holding_days": 365.0, "entry_gas_usd": 20.0,
                 "exit_gas_usd": 20.0}, config=tmp_log)
    assert r["classification"] == CLASS_GAS_NEGLIGIBLE
    assert FLAG_GAS_NEGLIGIBLE in r["flags"]


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_gas_cost_breakeven_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "gas_efficiency_score" in res.stdout
