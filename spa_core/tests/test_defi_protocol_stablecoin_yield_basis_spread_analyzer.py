"""
Tests for MP-1140 DeFiProtocolStablecoinYieldBasisSpreadAnalyzer
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
"""

import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_stablecoin_yield_basis_spread_analyzer import (
    analyze,
    analyze_portfolio,
    _excess_basis_pct,
    _basis_to_risk_ratio,
    _depeg_expected_cost_pct,
    _real_excess_after_depeg_haircut_pct,
    _risk_compensation_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolStablecoinYieldBasisSpreadAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_NEGATIVE_CARRY,
    CLASS_THIN_SPREAD,
    CLASS_FAIR,
    CLASS_GENEROUS,
    CLASS_EXCEPTIONAL,
    FLAG_NEGATIVE_EXCESS_BASIS,
    FLAG_THIN_COMPENSATION,
    FLAG_GENEROUS_CARRY,
    FLAG_HIGH_DEPEG_DRAG,
    FLAG_BELOW_RISK_FREE,
    FLAG_INSUFFICIENT_DATA,
    RATIO_SENTINEL_INF,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "basis_log.json")}


@pytest.fixture
def thin_position():
    # 6% vs 5% risk-free, 4% risk proxy -> ratio 0.25 -> thin.
    return {
        "name": "USDC-vault (thin)",
        "headline_apy_pct": 6.0,
        "risk_free_rate_pct": 5.0,
        "protocol_risk_proxy_pct": 4.0,
        "depeg_probability": 0.01,
        "depeg_severity_pct": 10.0,
        "holding_days": 365.0,
    }


@pytest.fixture
def generous_position():
    # 18% vs 5%, proxy 5% -> ratio 2.6 -> exceptional.
    return {
        "name": "Algo-stable (generous)",
        "headline_apy_pct": 18.0,
        "risk_free_rate_pct": 5.0,
        "protocol_risk_proxy_pct": 5.0,
        "depeg_probability": 0.02,
        "depeg_severity_pct": 15.0,
        "holding_days": 365.0,
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
    assert _clamp(0.5, 0.0, 1.0) == 0.5


# ---------------------------------------------------------------------------
# Excess basis tests
# ---------------------------------------------------------------------------

def test_excess_basis_positive():
    assert _excess_basis_pct(8.0, 5.0) == pytest.approx(3.0)


def test_excess_basis_zero():
    assert _excess_basis_pct(5.0, 5.0) == pytest.approx(0.0)


def test_excess_basis_negative():
    assert _excess_basis_pct(3.0, 5.0) == pytest.approx(-2.0)


def test_excess_basis_large():
    assert _excess_basis_pct(50.0, 5.0) == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Basis-to-risk ratio tests
# ---------------------------------------------------------------------------

def test_basis_ratio_normal():
    assert _basis_to_risk_ratio(3.0, 3.0) == pytest.approx(1.0)
    assert _basis_to_risk_ratio(6.0, 3.0) == pytest.approx(2.0)


def test_basis_ratio_thin():
    assert _basis_to_risk_ratio(1.0, 4.0) == pytest.approx(0.25)


def test_basis_ratio_zero_proxy_positive_excess():
    assert _basis_to_risk_ratio(3.0, 0.0) == RATIO_SENTINEL_INF


def test_basis_ratio_zero_proxy_negative_excess():
    assert _basis_to_risk_ratio(-3.0, 0.0) == -RATIO_SENTINEL_INF


def test_basis_ratio_zero_proxy_zero_excess():
    assert _basis_to_risk_ratio(0.0, 0.0) == 0.0


def test_basis_ratio_negative_proxy_floored():
    # negative proxy floored to 0 -> sentinel path
    assert _basis_to_risk_ratio(3.0, -5.0) == RATIO_SENTINEL_INF


def test_basis_ratio_negative_excess_normal():
    assert _basis_to_risk_ratio(-2.0, 4.0) == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# Depeg cost tests
# ---------------------------------------------------------------------------

def test_depeg_cost_normal():
    # 0.02 * 20 * 1 = 0.4
    assert _depeg_expected_cost_pct(0.02, 20.0, 365.0) == pytest.approx(0.4)


def test_depeg_cost_half_year():
    assert _depeg_expected_cost_pct(0.02, 20.0, 182.5) == pytest.approx(0.2)


def test_depeg_cost_zero_probability():
    assert _depeg_expected_cost_pct(0.0, 20.0, 365.0) == 0.0


def test_depeg_cost_zero_severity():
    assert _depeg_expected_cost_pct(0.5, 0.0, 365.0) == 0.0


def test_depeg_cost_probability_clamped():
    # probability > 1 clamps to 1
    assert _depeg_expected_cost_pct(5.0, 20.0, 365.0) == pytest.approx(20.0)


def test_depeg_cost_negative_severity_floored():
    assert _depeg_expected_cost_pct(0.5, -20.0, 365.0) == 0.0


def test_depeg_cost_zero_days():
    assert _depeg_expected_cost_pct(0.5, 20.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Real excess tests
# ---------------------------------------------------------------------------

def test_real_excess_normal():
    assert _real_excess_after_depeg_haircut_pct(3.0, 0.4) == pytest.approx(2.6)


def test_real_excess_negative():
    assert _real_excess_after_depeg_haircut_pct(1.0, 3.0) == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _risk_compensation_score(2.0, 5.0, 4.0, has_data=False) == 0.0


def test_score_range():
    s = _risk_compensation_score(1.0, 3.0, 2.5, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_high_when_generous():
    # ratio 2.0, positive excess, positive real -> full marks
    s = _risk_compensation_score(2.0, 5.0, 4.0, has_data=True)
    assert s >= 90.0


def test_score_low_when_negative():
    s = _risk_compensation_score(-1.0, -2.0, -3.0, has_data=True)
    assert s <= 30.0


def test_score_negative_excess_zero_component():
    s_pos = _risk_compensation_score(1.0, 3.0, 2.0, has_data=True)
    s_neg = _risk_compensation_score(1.0, -3.0, -4.0, has_data=True)
    assert s_pos > s_neg


def test_score_depeg_component_drops():
    # same ratio + positive excess, but real excess negative loses depeg comp
    s_survive = _risk_compensation_score(1.0, 3.0, 2.0, has_data=True)
    s_drown = _risk_compensation_score(1.0, 3.0, -1.0, has_data=True)
    assert s_survive > s_drown


def test_score_ratio_caps_at_two():
    s_two = _risk_compensation_score(2.0, 5.0, 4.0, has_data=True)
    s_five = _risk_compensation_score(5.0, 5.0, 4.0, has_data=True)
    assert s_two == s_five  # ratio capped


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data():
    assert _classify(2.0, 5.0, has_data=False) == CLASS_NEGATIVE_CARRY


def test_classify_negative_carry_zero_excess():
    assert _classify(0.0, 0.0, has_data=True) == CLASS_NEGATIVE_CARRY


def test_classify_negative_carry_negative_excess():
    assert _classify(-1.0, -3.0, has_data=True) == CLASS_NEGATIVE_CARRY


def test_classify_thin():
    assert _classify(0.25, 3.0, has_data=True) == CLASS_THIN_SPREAD


def test_classify_fair():
    assert _classify(0.75, 3.0, has_data=True) == CLASS_FAIR


def test_classify_generous():
    assert _classify(1.5, 3.0, has_data=True) == CLASS_GENEROUS


def test_classify_exceptional():
    assert _classify(2.5, 3.0, has_data=True) == CLASS_EXCEPTIONAL


def test_classify_boundary_thin_fair():
    # ratio exactly 0.5 -> fair (not thin)
    assert _classify(0.5, 3.0, has_data=True) == CLASS_FAIR


def test_classify_boundary_fair_generous():
    assert _classify(1.0, 3.0, has_data=True) == CLASS_GENEROUS


def test_classify_boundary_generous_exceptional():
    assert _classify(2.0, 3.0, has_data=True) == CLASS_EXCEPTIONAL


def test_classify_in_known_set():
    for ratio in (-1, 0.0, 0.25, 0.5, 1.0, 2.0, 5.0):
        assert _classify(ratio, 3.0, has_data=True) in ALL_CLASSIFICATIONS


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
    f = _flags(0, 0, 0, 0, 0, 0, CLASS_NEGATIVE_CARRY, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_negative_excess_basis():
    f = _flags(-2.0, 3.0, 5.0, -0.5, -2.0, 0.4, CLASS_NEGATIVE_CARRY,
               has_data=True)
    assert FLAG_NEGATIVE_EXCESS_BASIS in f


def test_flag_below_risk_free():
    f = _flags(-2.0, 3.0, 5.0, -0.5, -2.0, 0.4, CLASS_NEGATIVE_CARRY,
               has_data=True)
    assert FLAG_BELOW_RISK_FREE in f


def test_flag_thin_compensation():
    f = _flags(1.0, 6.0, 5.0, 0.25, 1.0, 0.1, CLASS_THIN_SPREAD,
               has_data=True)
    assert FLAG_THIN_COMPENSATION in f


def test_flag_generous_carry():
    f = _flags(13.0, 18.0, 5.0, 2.6, 13.0, 0.3, CLASS_EXCEPTIONAL,
               has_data=True)
    assert FLAG_GENEROUS_CARRY in f


def test_flag_high_depeg_drag():
    # depeg cost 2.0 of gross excess 3.0 -> 66% >= 50%
    f = _flags(3.0, 8.0, 5.0, 1.0, 3.0, 2.0, CLASS_GENEROUS, has_data=True)
    assert FLAG_HIGH_DEPEG_DRAG in f


def test_flag_no_thin_when_ratio_high():
    f = _flags(13.0, 18.0, 5.0, 2.6, 13.0, 0.3, CLASS_EXCEPTIONAL,
               has_data=True)
    assert FLAG_THIN_COMPENSATION not in f


def test_flags_subset_of_all():
    f = _flags(-2.0, 3.0, 5.0, -0.5, -2.0, 5.0, CLASS_NEGATIVE_CARRY,
               has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


def test_flag_thin_not_set_on_negative_ratio():
    # ratio negative is not in (0, 0.5) range
    f = _flags(-2.0, 3.0, 5.0, -0.5, -2.0, 0.1, CLASS_NEGATIVE_CARRY,
               has_data=True)
    assert FLAG_THIN_COMPENSATION not in f


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_NEGATIVE_CARRY, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_negative_carry_nonempty():
    recs = _recommendations(CLASS_NEGATIVE_CARRY, [FLAG_BELOW_RISK_FREE],
                            3.0, 5.0, -2.0, -0.5, -2.5, 0.5, has_data=True)
    assert len(recs) >= 1


def test_recommendations_exceptional_nonempty():
    recs = _recommendations(CLASS_EXCEPTIONAL, [FLAG_GENEROUS_CARRY],
                            18.0, 5.0, 13.0, 2.6, 12.7, 0.3, has_data=True)
    assert len(recs) >= 1


def test_recommendations_thin_nonempty():
    recs = _recommendations(CLASS_THIN_SPREAD, [FLAG_THIN_COMPENSATION],
                            6.0, 5.0, 1.0, 0.25, 0.9, 0.1, has_data=True)
    assert len(recs) >= 1


def test_recommendations_fair_nonempty():
    recs = _recommendations(CLASS_FAIR, [], 8.0, 5.0, 3.0, 0.75, 2.6, 0.4,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_generous_nonempty():
    recs = _recommendations(CLASS_GENEROUS, [], 11.0, 5.0, 6.0, 1.5, 5.6, 0.4,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_high_depeg_drag_string():
    recs = _recommendations(CLASS_FAIR, [FLAG_HIGH_DEPEG_DRAG],
                            8.0, 5.0, 3.0, 1.0, 1.0, 2.0, has_data=True)
    assert any("depeg" in r.lower() for r in recs)


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_thin_position(thin_position, tmp_log):
    r = analyze(thin_position, config=tmp_log)
    assert r["classification"] == CLASS_THIN_SPREAD
    assert r["excess_basis_pct"] == pytest.approx(1.0)
    assert FLAG_THIN_COMPENSATION in r["flags"]


def test_analyze_generous_position(generous_position, tmp_log):
    r = analyze(generous_position, config=tmp_log)
    assert r["classification"] == CLASS_EXCEPTIONAL
    assert r["risk_compensation_score"] >= 70.0
    assert r["grade"] in ("A", "B")


def test_analyze_excess_basis_math(tmp_log):
    r = analyze({"headline_apy_pct": 8.0, "risk_free_rate_pct": 5.0},
                config=tmp_log)
    assert r["excess_basis_pct"] == pytest.approx(3.0)


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["risk_compensation_score"] == 0.0
    assert r["classification"] == CLASS_NEGATIVE_CARRY


def test_analyze_poor_data_quality(generous_position, tmp_log):
    pos = dict(generous_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_below_risk_free(tmp_log):
    r = analyze({"headline_apy_pct": 3.0, "risk_free_rate_pct": 5.0},
                config=tmp_log)
    assert FLAG_BELOW_RISK_FREE in r["flags"]
    assert FLAG_NEGATIVE_EXCESS_BASIS in r["flags"]
    assert r["classification"] == CLASS_NEGATIVE_CARRY


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"headline_apy_pct": 6.0, "risk_free_rate_pct": 5.0},
                headline_apy_pct=20.0, risk_free_rate_pct=4.0,
                protocol_risk_proxy_pct=5.0, config=tmp_log)
    assert r["headline_apy_pct"] == 20.0
    assert r["risk_free_rate_pct"] == 4.0


def test_analyze_result_keys(generous_position, tmp_log):
    r = analyze(generous_position, config=tmp_log)
    for key in (
        "name", "headline_apy_pct", "risk_free_rate_pct",
        "protocol_risk_proxy_pct", "depeg_probability", "depeg_severity_pct",
        "holding_days", "data_quality_ok", "excess_basis_pct",
        "basis_to_risk_ratio", "depeg_expected_cost_pct",
        "real_excess_after_depeg_haircut_pct", "risk_compensation_score",
        "classification", "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"headline_apy_pct": "abc", "risk_free_rate_pct": None,
                 "protocol_risk_proxy_pct": [], "depeg_probability": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "risk_compensation_score" in r


def test_analyze_json_serialisable(generous_position, tmp_log):
    r = analyze(generous_position, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_zero_proxy_sentinel_serialisable(tmp_log):
    r = analyze({"headline_apy_pct": 8.0, "risk_free_rate_pct": 5.0,
                 "protocol_risk_proxy_pct": 0.0}, config=tmp_log)
    assert r["basis_to_risk_ratio"] == RATIO_SENTINEL_INF
    json.dumps(r)  # must not raise


def test_analyze_real_excess_after_haircut(tmp_log):
    r = analyze({"headline_apy_pct": 8.0, "risk_free_rate_pct": 5.0,
                 "depeg_probability": 0.02, "depeg_severity_pct": 20.0,
                 "holding_days": 365.0}, config=tmp_log)
    # excess 3.0, depeg cost 0.4 -> 2.6
    assert r["real_excess_after_depeg_haircut_pct"] == pytest.approx(2.6)


def test_analyze_depeg_probability_clamped(tmp_log):
    r = analyze({"headline_apy_pct": 8.0, "depeg_probability": 5.0},
                config=tmp_log)
    assert r["depeg_probability"] == 1.0


def test_analyze_writes_log(generous_position, tmp_log):
    analyze(generous_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_high_depeg_drag_flag(tmp_log):
    # small excess, big depeg cost
    r = analyze({"headline_apy_pct": 6.0, "risk_free_rate_pct": 5.0,
                 "protocol_risk_proxy_pct": 1.0,
                 "depeg_probability": 0.1, "depeg_severity_pct": 30.0,
                 "holding_days": 365.0}, config=tmp_log)
    # excess 1.0, depeg cost 3.0 -> share >= 0.5
    assert FLAG_HIGH_DEPEG_DRAG in r["flags"]


def test_analyze_default_risk_free(tmp_log):
    r = analyze({"headline_apy_pct": 8.0}, config=tmp_log)
    assert r["risk_free_rate_pct"] == 5.0


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["best_compensated_position"] is None
    assert r["worst_compensated_position"] is None
    assert r["avg_risk_compensation_score"] == 0.0
    assert r["negative_excess_basis_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_single(generous_position, tmp_log):
    r = analyze_portfolio([generous_position], config=tmp_log)
    assert r["total_positions"] == 1
    assert r["best_compensated_position"] == "Algo-stable (generous)"
    assert r["worst_compensated_position"] == "Algo-stable (generous)"


def test_portfolio_basic(thin_position, generous_position, tmp_log):
    r = analyze_portfolio([thin_position, generous_position], config=tmp_log)
    assert r["total_positions"] == 2
    assert r["best_compensated_position"] == "Algo-stable (generous)"
    assert r["worst_compensated_position"] == "USDC-vault (thin)"
    assert 0.0 <= r["avg_risk_compensation_score"] <= 100.0


def test_portfolio_negative_count(tmp_log):
    bad = {"headline_apy_pct": 3.0, "risk_free_rate_pct": 5.0}
    r = analyze_portfolio([bad, bad], config=tmp_log)
    assert r["negative_excess_basis_count"] == 2


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


def test_portfolio_results_present(thin_position, generous_position, tmp_log):
    r = analyze_portfolio([thin_position, generous_position], config=tmp_log)
    assert len(r["results"]) == 2
    json.dumps(r)


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(generous_position, tmp_log):
    a = DeFiProtocolStablecoinYieldBasisSpreadAnalyzer(config=tmp_log)
    r = a.analyze(generous_position)
    assert r["name"] == "Algo-stable (generous)"


def test_class_wrapper_portfolio(thin_position, generous_position, tmp_log):
    a = DeFiProtocolStablecoinYieldBasisSpreadAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([thin_position, generous_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolStablecoinYieldBasisSpreadAnalyzer(config=tmp_log)
    r = a.analyze(None, headline_apy_pct=10.0, risk_free_rate_pct=5.0,
                  protocol_risk_proxy_pct=2.5)
    assert r["headline_apy_pct"] == 10.0


def test_class_wrapper_default_config():
    a = DeFiProtocolStablecoinYieldBasisSpreadAnalyzer()
    assert a._config == {}


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


def test_atomic_log_creates_dir(tmp_path):
    log_path = str(tmp_path / "nested" / "deep" / "log.json")
    _atomic_log(log_path, {"x": 1})
    assert os.path.exists(log_path)


def test_atomic_log_no_tmp_leftover(tmp_path):
    log_path = str(tmp_path / "clean.json")
    _atomic_log(log_path, {"x": 1})
    leftovers = [p for p in os.listdir(str(tmp_path)) if p.endswith(".tmp")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_exactly_at_risk_free_negative_carry(tmp_log):
    r = analyze({"headline_apy_pct": 5.0, "risk_free_rate_pct": 5.0},
                config=tmp_log)
    assert r["excess_basis_pct"] == pytest.approx(0.0)
    assert r["classification"] == CLASS_NEGATIVE_CARRY


def test_large_headline_exceptional(tmp_log):
    r = analyze({"headline_apy_pct": 100.0, "risk_free_rate_pct": 5.0,
                 "protocol_risk_proxy_pct": 5.0,
                 "depeg_probability": 0.0}, config=tmp_log)
    assert r["classification"] == CLASS_EXCEPTIONAL
    assert FLAG_GENEROUS_CARRY in r["flags"]


def test_zero_holding_days_no_depeg_cost(tmp_log):
    r = analyze({"headline_apy_pct": 8.0, "risk_free_rate_pct": 5.0,
                 "depeg_probability": 0.5, "depeg_severity_pct": 50.0,
                 "holding_days": 0.0}, config=tmp_log)
    assert r["depeg_expected_cost_pct"] == 0.0


def test_negative_excess_serialisable(tmp_log):
    r = analyze({"headline_apy_pct": 1.0, "risk_free_rate_pct": 5.0,
                 "protocol_risk_proxy_pct": 0.0}, config=tmp_log)
    assert r["basis_to_risk_ratio"] == -RATIO_SENTINEL_INF
    json.dumps(r)


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_stablecoin_yield_basis_spread_analyzer.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "risk_compensation_score" in res.stdout
