"""
Tests for MP-1141 DeFiProtocolYieldAfterTaxDragAnalyzer
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

from spa_core.analytics.defi_protocol_yield_after_tax_drag_analyzer import (
    analyze,
    analyze_portfolio,
    _long_term_income_share,
    _effective_tax_rate_pct,
    _after_tax_apr_pct,
    _tax_drag_pct,
    _after_tax_efficiency_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolYieldAfterTaxDragAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_MINIMAL_DRAG,
    CLASS_LIGHT,
    CLASS_MODERATE,
    CLASS_HEAVY,
    CLASS_SEVERE,
    FLAG_HIGH_MARGINAL_RATE,
    FLAG_FREQUENT_TAXABLE_EVENTS,
    FLAG_QUALIFIES_LONG_TERM,
    FLAG_SEVERE_TAX_DRAG,
    FLAG_NEGATIVE_AFTER_TAX,
    FLAG_INSUFFICIENT_DATA,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "tax_log.json")}


@pytest.fixture
def heavy_drag_position():
    # 12% headline, 37% marginal, frequent harvest, short hold -> heavy/severe.
    return {
        "name": "USDC-farm (heavy)",
        "headline_apr_pct": 12.0,
        "marginal_tax_rate_pct": 37.0,
        "long_term_rate_pct": 20.0,
        "holding_days": 30.0,
        "harvests_per_year": 52.0,
    }


@pytest.fixture
def light_drag_position():
    # long hold, no harvests, low marginal -> long-term, light drag.
    return {
        "name": "stETH (light)",
        "headline_apr_pct": 4.0,
        "marginal_tax_rate_pct": 24.0,
        "long_term_rate_pct": 15.0,
        "holding_days": 730.0,
        "harvests_per_year": 0.0,
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
    assert _clamp(0.5, 0.0, 1.0) == 0.5


# ---------------------------------------------------------------------------
# Long-term income share tests
# ---------------------------------------------------------------------------

def test_lt_share_explicit_used():
    assert _long_term_income_share(30.0, 52.0, 0.8) == pytest.approx(0.8)


def test_lt_share_explicit_clamped_high():
    assert _long_term_income_share(30.0, 52.0, 5.0) == 1.0


def test_lt_share_explicit_clamped_low():
    assert _long_term_income_share(30.0, 52.0, -1.0) == 0.0


def test_lt_share_short_hold_zero():
    # held < 365 days -> 0 long-term
    assert _long_term_income_share(30.0, 0.0, None) == 0.0


def test_lt_share_long_hold_no_harvest_full():
    # held >= 365, no harvests -> full long-term
    assert _long_term_income_share(730.0, 0.0, None) == pytest.approx(1.0)


def test_lt_share_long_hold_frequent_zero():
    # held >= 365 but 12+ harvests/year -> 0
    assert _long_term_income_share(730.0, 12.0, None) == pytest.approx(0.0)


def test_lt_share_long_hold_mid_harvest():
    # held >= 365, 6 harvests/year -> penalty 0.5 -> share 0.5
    assert _long_term_income_share(730.0, 6.0, None) == pytest.approx(0.5)


def test_lt_share_exactly_threshold():
    # held exactly 365 days qualifies
    assert _long_term_income_share(365.0, 0.0, None) == pytest.approx(1.0)


def test_lt_share_just_below_threshold():
    assert _long_term_income_share(364.0, 0.0, None) == 0.0


# ---------------------------------------------------------------------------
# Effective tax rate tests
# ---------------------------------------------------------------------------

def test_effective_rate_all_short_term():
    # 0 long-term share -> full marginal
    assert _effective_tax_rate_pct(37.0, 20.0, 0.0) == pytest.approx(37.0)


def test_effective_rate_all_long_term():
    assert _effective_tax_rate_pct(37.0, 20.0, 1.0) == pytest.approx(20.0)


def test_effective_rate_blended():
    # 0.5 * 20 + 0.5 * 37 = 28.5
    assert _effective_tax_rate_pct(37.0, 20.0, 0.5) == pytest.approx(28.5)


def test_effective_rate_negative_rates_floored():
    assert _effective_tax_rate_pct(-37.0, -20.0, 0.5) == pytest.approx(0.0)


def test_effective_rate_share_clamped():
    # share > 1 clamps to 1 -> lt rate
    assert _effective_tax_rate_pct(37.0, 20.0, 2.0) == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# After-tax APR tests
# ---------------------------------------------------------------------------

def test_after_tax_apr_normal():
    # 12% * (1 - 0.37) = 7.56
    assert _after_tax_apr_pct(12.0, 37.0) == pytest.approx(7.56)


def test_after_tax_apr_zero_tax():
    assert _after_tax_apr_pct(12.0, 0.0) == pytest.approx(12.0)


def test_after_tax_apr_full_tax():
    assert _after_tax_apr_pct(12.0, 100.0) == pytest.approx(0.0)


def test_after_tax_apr_over_100_clamped():
    # >100% tax clamped to 100 -> 0 (cannot fabricate gain)
    assert _after_tax_apr_pct(12.0, 150.0) == pytest.approx(0.0)


def test_after_tax_apr_negative_headline():
    # negative headline stays negative under positive tax
    assert _after_tax_apr_pct(-5.0, 37.0) == pytest.approx(-5.0 * 0.63)


# ---------------------------------------------------------------------------
# Tax drag tests
# ---------------------------------------------------------------------------

def test_tax_drag_normal():
    # headline 12, after-tax 7.56 -> drag = 37%
    assert _tax_drag_pct(12.0, 7.56) == pytest.approx(37.0)


def test_tax_drag_zero_headline():
    assert _tax_drag_pct(0.0, 0.0) == 0.0


def test_tax_drag_negative_headline():
    assert _tax_drag_pct(-5.0, -3.0) == 0.0


def test_tax_drag_no_drag():
    assert _tax_drag_pct(10.0, 10.0) == pytest.approx(0.0)


def test_tax_drag_full():
    assert _tax_drag_pct(10.0, 0.0) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _after_tax_efficiency_score(20.0, 8.0, 0.5, has_data=False) == 0.0


def test_score_range():
    s = _after_tax_efficiency_score(30.0, 7.0, 0.3, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_high_when_low_drag():
    # tiny drag, positive after-tax, full long-term -> high
    s = _after_tax_efficiency_score(5.0, 9.5, 1.0, has_data=True)
    assert s >= 90.0


def test_score_low_when_severe():
    s = _after_tax_efficiency_score(100.0, -1.0, 0.0, has_data=True)
    assert s <= 30.0


def test_score_negative_after_tax_drops():
    s_pos = _after_tax_efficiency_score(30.0, 7.0, 0.0, has_data=True)
    s_neg = _after_tax_efficiency_score(30.0, -1.0, 0.0, has_data=True)
    assert s_pos > s_neg


def test_score_long_term_bonus():
    s_no_lt = _after_tax_efficiency_score(20.0, 8.0, 0.0, has_data=True)
    s_lt = _after_tax_efficiency_score(20.0, 8.0, 1.0, has_data=True)
    assert s_lt > s_no_lt


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data_severe():
    assert _classify(5.0, has_data=False) == CLASS_SEVERE


def test_classify_minimal():
    assert _classify(10.0, has_data=True) == CLASS_MINIMAL_DRAG


def test_classify_light():
    assert _classify(20.0, has_data=True) == CLASS_LIGHT


def test_classify_moderate():
    assert _classify(30.0, has_data=True) == CLASS_MODERATE


def test_classify_heavy():
    assert _classify(40.0, has_data=True) == CLASS_HEAVY


def test_classify_severe():
    assert _classify(50.0, has_data=True) == CLASS_SEVERE


def test_classify_boundary_minimal_light():
    assert _classify(15.0, has_data=True) == CLASS_LIGHT


def test_classify_boundary_light_moderate():
    assert _classify(25.0, has_data=True) == CLASS_MODERATE


def test_classify_boundary_moderate_heavy():
    assert _classify(35.0, has_data=True) == CLASS_HEAVY


def test_classify_boundary_heavy_severe():
    assert _classify(45.0, has_data=True) == CLASS_SEVERE


def test_classify_in_known_set():
    for drag in (0, 15, 25, 35, 45, 100):
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
    f = _flags(0, 0, 0, 0, 0, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_high_marginal_rate():
    f = _flags(37.0, 0.0, 0.0, 20.0, 9.0, has_data=True)
    assert FLAG_HIGH_MARGINAL_RATE in f


def test_flag_high_marginal_boundary():
    # exactly 32 -> high
    f = _flags(32.0, 0.0, 0.0, 20.0, 9.0, has_data=True)
    assert FLAG_HIGH_MARGINAL_RATE in f


def test_flag_no_high_marginal_below():
    f = _flags(24.0, 0.0, 0.0, 20.0, 9.0, has_data=True)
    assert FLAG_HIGH_MARGINAL_RATE not in f


def test_flag_frequent_taxable_events():
    f = _flags(20.0, 52.0, 0.0, 20.0, 9.0, has_data=True)
    assert FLAG_FREQUENT_TAXABLE_EVENTS in f


def test_flag_frequent_boundary():
    # exactly 12 -> frequent
    f = _flags(20.0, 12.0, 0.0, 20.0, 9.0, has_data=True)
    assert FLAG_FREQUENT_TAXABLE_EVENTS in f


def test_flag_qualifies_long_term():
    f = _flags(20.0, 0.0, 0.6, 15.0, 9.0, has_data=True)
    assert FLAG_QUALIFIES_LONG_TERM in f


def test_flag_qualifies_boundary():
    # exactly 0.5 -> qualifies
    f = _flags(20.0, 0.0, 0.5, 15.0, 9.0, has_data=True)
    assert FLAG_QUALIFIES_LONG_TERM in f


def test_flag_severe_tax_drag():
    f = _flags(37.0, 52.0, 0.0, 50.0, 5.0, has_data=True)
    assert FLAG_SEVERE_TAX_DRAG in f


def test_flag_severe_boundary():
    f = _flags(37.0, 52.0, 0.0, 45.0, 5.0, has_data=True)
    assert FLAG_SEVERE_TAX_DRAG in f


def test_flag_negative_after_tax():
    f = _flags(37.0, 52.0, 0.0, 110.0, -1.0, has_data=True)
    assert FLAG_NEGATIVE_AFTER_TAX in f


def test_flags_subset_of_all():
    f = _flags(50.0, 100.0, 1.0, 100.0, -5.0, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_SEVERE, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_severe_nonempty():
    recs = _recommendations(CLASS_SEVERE, [FLAG_HIGH_MARGINAL_RATE],
                            12.0, 37.0, 7.56, 37.0, 52.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_minimal_nonempty():
    recs = _recommendations(CLASS_MINIMAL_DRAG, [],
                            4.0, 10.0, 3.6, 10.0, 0.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_heavy_nonempty():
    recs = _recommendations(CLASS_HEAVY, [], 12.0, 37.0, 7.56, 37.0, 52.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_moderate_nonempty():
    recs = _recommendations(CLASS_MODERATE, [], 10.0, 30.0, 7.0, 30.0, 4.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_light_nonempty():
    recs = _recommendations(CLASS_LIGHT, [], 8.0, 20.0, 6.4, 20.0, 0.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_not_tax_advice_disclaimer():
    recs = _recommendations(CLASS_SEVERE, [], 12.0, 37.0, 7.56, 37.0, 52.0,
                            has_data=True)
    assert any("not tax advice" in r.lower() for r in recs)


def test_recommendations_frequent_string():
    recs = _recommendations(CLASS_HEAVY, [FLAG_FREQUENT_TAXABLE_EVENTS],
                            12.0, 37.0, 7.56, 37.0, 52.0, has_data=True)
    assert any("harvest" in r.lower() for r in recs)


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_heavy_position(heavy_drag_position, tmp_log):
    r = analyze(heavy_drag_position, config=tmp_log)
    assert r["classification"] in (CLASS_HEAVY, CLASS_SEVERE)
    assert r["after_tax_apr_pct"] == pytest.approx(7.56)
    assert FLAG_HIGH_MARGINAL_RATE in r["flags"]
    assert FLAG_FREQUENT_TAXABLE_EVENTS in r["flags"]


def test_analyze_light_position(light_drag_position, tmp_log):
    r = analyze(light_drag_position, config=tmp_log)
    # long hold, no harvest -> full long-term -> 15% effective
    assert r["long_term_income_share"] == pytest.approx(1.0)
    assert r["effective_tax_rate_pct"] == pytest.approx(15.0)
    assert FLAG_QUALIFIES_LONG_TERM in r["flags"]


def test_analyze_after_tax_math(tmp_log):
    r = analyze({"headline_apr_pct": 12.0, "marginal_tax_rate_pct": 37.0,
                 "holding_days": 30.0, "harvests_per_year": 52.0},
                config=tmp_log)
    assert r["effective_tax_rate_pct"] == pytest.approx(37.0)
    assert r["after_tax_apr_pct"] == pytest.approx(7.56)


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["after_tax_efficiency_score"] == 0.0
    assert r["classification"] == CLASS_SEVERE


def test_analyze_poor_data_quality(heavy_drag_position, tmp_log):
    pos = dict(heavy_drag_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_explicit_lt_share(tmp_log):
    r = analyze({"headline_apr_pct": 12.0, "marginal_tax_rate_pct": 37.0,
                 "long_term_rate_pct": 20.0, "holding_days": 30.0,
                 "harvests_per_year": 52.0, "long_term_income_share": 1.0},
                config=tmp_log)
    # explicit share overrides the short-hold model
    assert r["long_term_income_share"] == pytest.approx(1.0)
    assert r["effective_tax_rate_pct"] == pytest.approx(20.0)


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"headline_apr_pct": 6.0, "marginal_tax_rate_pct": 37.0},
                headline_apr_pct=20.0, marginal_tax_rate_pct=24.0,
                config=tmp_log)
    assert r["headline_apr_pct"] == 20.0
    assert r["marginal_tax_rate_pct"] == 24.0


def test_analyze_result_keys(heavy_drag_position, tmp_log):
    r = analyze(heavy_drag_position, config=tmp_log)
    for key in (
        "name", "headline_apr_pct", "marginal_tax_rate_pct",
        "long_term_rate_pct", "holding_days", "harvests_per_year",
        "long_term_income_share", "data_quality_ok", "effective_tax_rate_pct",
        "after_tax_apr_pct", "tax_drag_pct", "after_tax_efficiency_score",
        "classification", "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"headline_apr_pct": "abc", "marginal_tax_rate_pct": None,
                 "harvests_per_year": [], "holding_days": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "after_tax_efficiency_score" in r


def test_analyze_json_serialisable(heavy_drag_position, tmp_log):
    r = analyze(heavy_drag_position, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_drag_matches_classification(heavy_drag_position, tmp_log):
    r = analyze(heavy_drag_position, config=tmp_log)
    # 37% drag -> HEAVY (35..45)
    assert r["tax_drag_pct"] == pytest.approx(37.0)
    assert r["classification"] == CLASS_HEAVY


def test_analyze_writes_log(heavy_drag_position, tmp_log):
    analyze(heavy_drag_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_default_marginal_rate(tmp_log):
    r = analyze({"headline_apr_pct": 10.0, "holding_days": 30.0,
                 "harvests_per_year": 52.0}, config=tmp_log)
    assert r["marginal_tax_rate_pct"] == 37.0


def test_analyze_long_hold_no_harvest_qualifies(tmp_log):
    r = analyze({"headline_apr_pct": 5.0, "marginal_tax_rate_pct": 32.0,
                 "long_term_rate_pct": 15.0, "holding_days": 400.0,
                 "harvests_per_year": 0.0}, config=tmp_log)
    assert FLAG_QUALIFIES_LONG_TERM in r["flags"]
    assert r["effective_tax_rate_pct"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["most_tax_efficient_position"] is None
    assert r["least_tax_efficient_position"] is None
    assert r["avg_after_tax_efficiency_score"] == 0.0
    assert r["severe_drag_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_single(light_drag_position, tmp_log):
    r = analyze_portfolio([light_drag_position], config=tmp_log)
    assert r["total_positions"] == 1
    assert r["most_tax_efficient_position"] == "stETH (light)"
    assert r["least_tax_efficient_position"] == "stETH (light)"


def test_portfolio_basic(heavy_drag_position, light_drag_position, tmp_log):
    r = analyze_portfolio([heavy_drag_position, light_drag_position],
                          config=tmp_log)
    assert r["total_positions"] == 2
    assert r["most_tax_efficient_position"] == "stETH (light)"
    assert r["least_tax_efficient_position"] == "USDC-farm (heavy)"
    assert 0.0 <= r["avg_after_tax_efficiency_score"] <= 100.0


def test_portfolio_severe_count(tmp_log):
    severe = {"headline_apr_pct": 10.0, "marginal_tax_rate_pct": 50.0,
              "long_term_rate_pct": 20.0, "holding_days": 10.0,
              "harvests_per_year": 52.0}
    r = analyze_portfolio([severe, severe], config=tmp_log)
    assert r["severe_drag_count"] == 2


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


def test_portfolio_results_present(heavy_drag_position, light_drag_position, tmp_log):
    r = analyze_portfolio([heavy_drag_position, light_drag_position],
                          config=tmp_log)
    assert len(r["results"]) == 2
    json.dumps(r)


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(heavy_drag_position, tmp_log):
    a = DeFiProtocolYieldAfterTaxDragAnalyzer(config=tmp_log)
    r = a.analyze(heavy_drag_position)
    assert r["name"] == "USDC-farm (heavy)"


def test_class_wrapper_portfolio(heavy_drag_position, light_drag_position, tmp_log):
    a = DeFiProtocolYieldAfterTaxDragAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([heavy_drag_position, light_drag_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolYieldAfterTaxDragAnalyzer(config=tmp_log)
    r = a.analyze(None, headline_apr_pct=10.0, marginal_tax_rate_pct=24.0)
    assert r["headline_apr_pct"] == 10.0


def test_class_wrapper_default_config():
    a = DeFiProtocolYieldAfterTaxDragAnalyzer()
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

def test_zero_tax_no_drag(tmp_log):
    r = analyze({"headline_apr_pct": 10.0, "marginal_tax_rate_pct": 0.0,
                 "long_term_rate_pct": 0.0, "holding_days": 30.0},
                config=tmp_log)
    assert r["after_tax_apr_pct"] == pytest.approx(10.0)
    assert r["tax_drag_pct"] == pytest.approx(0.0)
    assert r["classification"] == CLASS_MINIMAL_DRAG


def test_long_term_lowers_effective(tmp_log):
    short = analyze({"headline_apr_pct": 12.0, "marginal_tax_rate_pct": 37.0,
                     "long_term_rate_pct": 20.0, "holding_days": 30.0,
                     "harvests_per_year": 52.0}, config=tmp_log)
    long_ = analyze({"headline_apr_pct": 12.0, "marginal_tax_rate_pct": 37.0,
                     "long_term_rate_pct": 20.0, "holding_days": 730.0,
                     "harvests_per_year": 0.0}, config=tmp_log)
    assert long_["effective_tax_rate_pct"] < short["effective_tax_rate_pct"]
    assert long_["after_tax_apr_pct"] > short["after_tax_apr_pct"]


def test_severe_drag_serialisable(tmp_log):
    r = analyze({"headline_apr_pct": 5.0, "marginal_tax_rate_pct": 50.0,
                 "holding_days": 10.0, "harvests_per_year": 52.0},
                config=tmp_log)
    assert r["classification"] == CLASS_SEVERE
    json.dumps(r)


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_yield_after_tax_drag_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "after_tax_efficiency_score" in res.stdout
