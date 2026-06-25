"""
Tests for MP-1139 ProtocolDeFiRewardTokenLockupDiscountAnalyzer
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
"""

import json
import math
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

from spa_core.analytics.protocol_defi_reward_token_lockup_discount_analyzer import (
    analyze,
    analyze_portfolio,
    _reward_share_of_apr_pct,
    _time_value_factor,
    _price_risk_factor,
    _early_exit_factor,
    _lockup_discount_factor,
    _realisable_reward_apr_pct,
    _lockup_adjusted_apr_pct,
    _headline_vs_realisable_gap_pct,
    _paper_yield_share_pct,
    _reward_realisability_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    ProtocolDeFiRewardTokenLockupDiscountAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_FULLY_LIQUID,
    CLASS_LIGHTLY_LOCKED,
    CLASS_MODERATELY_LOCKED,
    CLASS_HEAVILY_LOCKED,
    CLASS_DEEPLY_LOCKED,
    FLAG_LONG_LOCKUP,
    FLAG_HIGH_EARLY_EXIT_PENALTY,
    FLAG_REWARD_DOMINATED_APR,
    FLAG_LARGE_PAPER_YIELD,
    FLAG_HIGH_PRICE_RISK,
    FLAG_MOSTLY_LIQUID,
    FLAG_DEEP_DISCOUNT,
    FLAG_INSUFFICIENT_DATA,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "lockup_log.json")}


@pytest.fixture
def deeply_locked():
    return {
        "name": "veCRV farm",
        "total_apr_pct": 40.0,
        "reward_apr_pct": 32.0,
        "lockup_days": 730.0,
        "annual_vol_pct": 90.0,
        "early_exit_penalty_pct": 50.0,
        "liquid_unlock_fraction": 0.0,
    }


@pytest.fixture
def mostly_liquid():
    return {
        "name": "stable LP",
        "total_apr_pct": 8.0,
        "reward_apr_pct": 1.0,
        "lockup_days": 3.0,
        "annual_vol_pct": 10.0,
        "early_exit_penalty_pct": 0.0,
        "liquid_unlock_fraction": 0.8,
    }


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_safe_float():
    assert _safe_float("2.5") == 2.5
    assert _safe_float(None) == 0.0
    assert _safe_float("x", 9.0) == 9.0


def test_clamp():
    assert _clamp(-1) == 0.0
    assert _clamp(101) == 100.0
    assert _clamp(0.5, 0, 1) == 0.5


def test_reward_share_normal():
    assert _reward_share_of_apr_pct(8.0, 40.0) == pytest.approx(20.0)


def test_reward_share_zero_total():
    assert _reward_share_of_apr_pct(5.0, 0.0) == 0.0


def test_reward_share_clamped():
    assert _reward_share_of_apr_pct(50.0, 40.0) == 100.0


def test_time_value_zero_lockup():
    assert _time_value_factor(0.0, 15.0) == 1.0


def test_time_value_decreasing():
    f1 = _time_value_factor(365.0, 15.0)
    f2 = _time_value_factor(730.0, 15.0)
    assert f1 < 1.0
    assert f2 < f1


def test_time_value_one_year():
    # 1 / (1.15)^1
    assert _time_value_factor(365.0, 15.0) == pytest.approx(1 / 1.15, rel=1e-6)


def test_price_risk_zero_lockup_or_vol():
    assert _price_risk_factor(0.0, 80.0) == 1.0
    assert _price_risk_factor(365.0, 0.0) == 1.0


def test_price_risk_decreasing_with_vol():
    f_low = _price_risk_factor(365.0, 20.0)
    f_high = _price_risk_factor(365.0, 90.0)
    assert f_high < f_low < 1.0


def test_price_risk_sqrt_time():
    # sigma_horizon = 0.5 * sqrt(1) = 0.5 -> 1/1.5
    assert _price_risk_factor(365.0, 50.0) == pytest.approx(1 / 1.5, rel=1e-6)


def test_early_exit_factor():
    assert _early_exit_factor(0.0) == 1.0
    assert _early_exit_factor(50.0) == 0.5
    assert _early_exit_factor(100.0) == 0.0


def test_early_exit_clamped():
    assert _early_exit_factor(150.0) == 0.0
    assert _early_exit_factor(-10.0) == 1.0


def test_lockup_discount_no_lockup_full():
    f = _lockup_discount_factor(0.0, 15.0, 0.0, 0.0, 0.0)
    assert f == pytest.approx(1.0)


def test_lockup_discount_fully_liquid_fraction():
    # 100% liquid on receipt -> factor 1.0 regardless of locked haircuts
    f = _lockup_discount_factor(730.0, 15.0, 90.0, 50.0, 1.0)
    assert f == pytest.approx(1.0)


def test_lockup_discount_deep():
    f = _lockup_discount_factor(730.0, 15.0, 90.0, 50.0, 0.0)
    assert 0.0 <= f <= 0.5


def test_lockup_discount_in_range():
    for d in (0, 100, 365, 730, 1460):
        f = _lockup_discount_factor(d, 15.0, 60.0, 30.0, 0.2)
        assert 0.0 <= f <= 1.0


def test_realisable_reward():
    assert _realisable_reward_apr_pct(32.0, 0.5) == 16.0
    assert _realisable_reward_apr_pct(-5.0, 0.5) == 0.0


def test_lockup_adjusted_apr():
    assert _lockup_adjusted_apr_pct(8.0, 16.0) == 24.0


def test_gap():
    assert _headline_vs_realisable_gap_pct(40.0, 24.0) == 16.0
    # never negative
    assert _headline_vs_realisable_gap_pct(20.0, 25.0) == 0.0


def test_paper_share():
    assert _paper_yield_share_pct(16.0, 40.0) == pytest.approx(40.0)
    assert _paper_yield_share_pct(5.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _reward_realisability_score(0.5, 50, 50, has_data=False) == 0.0


def test_score_range():
    s = _reward_realisability_score(0.6, 50.0, 30.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_liquid_high():
    s = _reward_realisability_score(1.0, 10.0, 2.0, has_data=True)
    assert s >= 90.0


def test_score_locked_low():
    s = _reward_realisability_score(0.2, 90.0, 80.0, has_data=True)
    assert s <= 35.0


def test_score_factor_monotonic():
    s_lo = _reward_realisability_score(0.3, 50.0, 50.0, has_data=True)
    s_hi = _reward_realisability_score(0.9, 50.0, 50.0, has_data=True)
    assert s_hi > s_lo


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data_deep():
    assert _classify(1.0, has_data=False) == CLASS_DEEPLY_LOCKED


def test_classify_fully_liquid():
    assert _classify(0.97, has_data=True) == CLASS_FULLY_LIQUID


def test_classify_lightly():
    assert _classify(0.85, has_data=True) == CLASS_LIGHTLY_LOCKED


def test_classify_moderately():
    assert _classify(0.70, has_data=True) == CLASS_MODERATELY_LOCKED


def test_classify_heavily():
    assert _classify(0.50, has_data=True) == CLASS_HEAVILY_LOCKED


def test_classify_deeply():
    assert _classify(0.30, has_data=True) == CLASS_DEEPLY_LOCKED


def test_classify_in_known_set():
    for f in (0.0, 0.3, 0.5, 0.7, 0.85, 0.97, 1.0):
        assert _classify(f, has_data=True) in ALL_CLASSIFICATIONS


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
    for s in range(0, 101, 9):
        assert _grade(s) in ALL_GRADES


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(0, 0, 0, 0, 0, 1.0, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_long_lockup():
    f = _flags(400.0, 0.0, 0.0, 0.0, 0.0, 0.8, has_data=True)
    assert FLAG_LONG_LOCKUP in f


def test_flag_high_early_exit():
    f = _flags(100.0, 40.0, 0.0, 0.0, 0.0, 0.8, has_data=True)
    assert FLAG_HIGH_EARLY_EXIT_PENALTY in f


def test_flag_reward_dominated():
    f = _flags(10.0, 0.0, 70.0, 0.0, 0.0, 0.8, has_data=True)
    assert FLAG_REWARD_DOMINATED_APR in f


def test_flag_large_paper_yield():
    f = _flags(10.0, 0.0, 0.0, 50.0, 0.0, 0.5, has_data=True)
    assert FLAG_LARGE_PAPER_YIELD in f


def test_flag_high_price_risk():
    f = _flags(100.0, 0.0, 0.0, 0.0, 90.0, 0.5, has_data=True)
    assert FLAG_HIGH_PRICE_RISK in f


def test_flag_mostly_liquid():
    f = _flags(5.0, 0.0, 5.0, 2.0, 0.0, 0.95, has_data=True)
    assert FLAG_MOSTLY_LIQUID in f


def test_flag_deep_discount():
    f = _flags(730.0, 50.0, 80.0, 80.0, 90.0, 0.30, has_data=True)
    assert FLAG_DEEP_DISCOUNT in f


def test_flags_subset_of_all():
    f = _flags(730.0, 50.0, 80.0, 80.0, 90.0, 0.30, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_DEEPLY_LOCKED, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_deeply_locked():
    recs = _recommendations(CLASS_DEEPLY_LOCKED,
                            [FLAG_LONG_LOCKUP, FLAG_HIGH_EARLY_EXIT_PENALTY],
                            40, 12, 28, 730, 50, has_data=True)
    assert len(recs) >= 2


def test_recommendations_fully_liquid():
    recs = _recommendations(CLASS_FULLY_LIQUID, [FLAG_MOSTLY_LIQUID],
                            8, 7.8, 0.2, 3, 0, has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_deeply_locked(deeply_locked, tmp_log):
    r = analyze(deeply_locked, config=tmp_log)
    assert r["classification"] in (CLASS_DEEPLY_LOCKED, CLASS_HEAVILY_LOCKED)
    assert r["lockup_adjusted_apr_pct"] < r["total_apr_pct"]
    assert r["lockup_discount_factor"] < 0.6
    assert r["reward_realisability_score"] <= 60.0


def test_analyze_mostly_liquid(mostly_liquid, tmp_log):
    r = analyze(mostly_liquid, config=tmp_log)
    assert r["classification"] in (CLASS_FULLY_LIQUID, CLASS_LIGHTLY_LOCKED)
    assert r["lockup_discount_factor"] >= 0.8
    assert r["reward_realisability_score"] >= 70.0


def test_analyze_apr_decomposition_total_reward(tmp_log):
    # total + reward given -> liquid = total - reward
    r = analyze({"total_apr_pct": 40.0, "reward_apr_pct": 32.0,
                 "lockup_days": 30.0}, config=tmp_log)
    assert r["liquid_apr_pct"] == pytest.approx(8.0)
    assert r["total_apr_pct"] == pytest.approx(40.0)


def test_analyze_apr_decomposition_liquid_reward(tmp_log):
    # liquid + reward -> total
    r = analyze({"liquid_apr_pct": 5.0, "reward_apr_pct": 15.0,
                 "lockup_days": 30.0}, config=tmp_log)
    assert r["total_apr_pct"] == pytest.approx(20.0)


def test_analyze_only_total_assumes_reward(tmp_log):
    # only total -> worst case all reward
    r = analyze({"total_apr_pct": 25.0, "lockup_days": 30.0}, config=tmp_log)
    assert r["reward_apr_pct"] == pytest.approx(25.0)
    assert r["liquid_apr_pct"] == 0.0


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["reward_realisability_score"] == 0.0
    assert r["classification"] == CLASS_DEEPLY_LOCKED


def test_analyze_poor_data_quality(deeply_locked, tmp_log):
    pos = dict(deeply_locked)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"total_apr_pct": 5.0, "reward_apr_pct": 1.0},
                total_apr_pct=40.0, reward_apr_pct=30.0, lockup_days=365.0,
                config=tmp_log)
    assert r["total_apr_pct"] == pytest.approx(40.0)
    assert r["reward_apr_pct"] == pytest.approx(30.0)


def test_analyze_result_keys(deeply_locked, tmp_log):
    r = analyze(deeply_locked, config=tmp_log)
    for key in (
        "name", "total_apr_pct", "liquid_apr_pct", "reward_apr_pct",
        "lockup_days", "reward_share_of_apr_pct", "lockup_discount_factor",
        "realisable_reward_apr_pct", "lockup_adjusted_apr_pct",
        "headline_vs_realisable_gap_pct", "paper_yield_share_pct",
        "reward_realisability_score", "classification", "grade", "flags",
        "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"total_apr_pct": "abc", "reward_apr_pct": None,
                 "lockup_days": [], "early_exit_penalty_pct": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "reward_realisability_score" in r


def test_analyze_json_serialisable(deeply_locked, tmp_log):
    r = analyze(deeply_locked, config=tmp_log)
    s = json.dumps(r)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_realisable_le_reward(deeply_locked, tmp_log):
    r = analyze(deeply_locked, config=tmp_log)
    assert r["realisable_reward_apr_pct"] <= r["reward_apr_pct"] + _EPS


def test_analyze_writes_log(deeply_locked, tmp_log):
    analyze(deeply_locked, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["most_realisable_position"] is None
    assert r["avg_reward_realisability_score"] == 0.0


def test_portfolio_not_a_list():
    r = analyze_portfolio(42)
    assert r["total_positions"] == 0


def test_portfolio_basic(deeply_locked, mostly_liquid, tmp_log):
    r = analyze_portfolio([deeply_locked, mostly_liquid], config=tmp_log)
    assert r["total_positions"] == 2
    assert r["most_realisable_position"] == "stable LP"
    assert r["least_realisable_position"] == "veCRV farm"
    assert 0.0 <= r["avg_reward_realisability_score"] <= 100.0


def test_portfolio_deeply_locked_count(deeply_locked, tmp_log):
    r = analyze_portfolio([deeply_locked, deeply_locked], config=tmp_log)
    assert r["deeply_locked_count"] >= 0


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 1, "x"], config=tmp_log)
    assert r["total_positions"] == 3


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(deeply_locked, tmp_log):
    a = ProtocolDeFiRewardTokenLockupDiscountAnalyzer(config=tmp_log)
    r = a.analyze(deeply_locked)
    assert r["name"] == "veCRV farm"


def test_class_wrapper_portfolio(deeply_locked, mostly_liquid, tmp_log):
    a = ProtocolDeFiRewardTokenLockupDiscountAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([deeply_locked, mostly_liquid])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = ProtocolDeFiRewardTokenLockupDiscountAnalyzer(config=tmp_log)
    r = a.analyze(None, total_apr_pct=20.0, reward_apr_pct=10.0,
                  lockup_days=90.0)
    assert r["total_apr_pct"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Atomic log tests
# ---------------------------------------------------------------------------

def test_atomic_log_ring_buffer(tmp_path):
    log_path = str(tmp_path / "ring.json")
    for i in range(115):
        _atomic_log(log_path, {"i": i})
    with open(log_path) as fh:
        data = json.load(fh)
    assert len(data) == 100
    assert data[0]["i"] == 15
    assert data[-1]["i"] == 114


def test_atomic_log_corrupt_recovers(tmp_path):
    log_path = str(tmp_path / "corrupt.json")
    with open(log_path, "w") as fh:
        fh.write("garbage{")
    _atomic_log(log_path, {"ok": True})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"ok": True}]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_no_lockup_high_realisability(tmp_log):
    r = analyze({"total_apr_pct": 10.0, "reward_apr_pct": 5.0,
                 "lockup_days": 0.0}, config=tmp_log)
    assert r["lockup_discount_factor"] == pytest.approx(1.0)
    assert r["classification"] == CLASS_FULLY_LIQUID


def test_full_liquid_unlock_no_discount(tmp_log):
    r = analyze({"total_apr_pct": 40.0, "reward_apr_pct": 30.0,
                 "lockup_days": 730.0, "early_exit_penalty_pct": 50.0,
                 "liquid_unlock_fraction": 1.0}, config=tmp_log)
    assert r["lockup_discount_factor"] == pytest.approx(1.0)


def test_paper_yield_bounded(deeply_locked, tmp_log):
    r = analyze(deeply_locked, config=tmp_log)
    assert 0.0 <= r["paper_yield_share_pct"] <= 100.0


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "protocol_defi_reward_token_lockup_discount_analyzer.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "reward_realisability_score" in res.stdout
