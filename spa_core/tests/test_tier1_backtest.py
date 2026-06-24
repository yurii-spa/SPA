"""Tests for the Tier-1 parallel backtest-validation layer (deterministic, stdlib)."""
import math

from spa_core.backtesting.tier1 import deflated_sharpe as ds
from spa_core.backtesting.tier1.cost_model import net_of_cost_apy
from spa_core.backtesting.tier1 import evaluator


def test_psr_monotonic_and_bounded():
    p_low = ds.probabilistic_sharpe_ratio(0.05, 365)
    p_high = ds.probabilistic_sharpe_ratio(0.20, 365)
    assert 0.0 <= p_low <= 1.0 and 0.0 <= p_high <= 1.0
    assert p_high > p_low  # higher Sharpe → higher confidence


def test_psr_half_at_benchmark():
    # SR exactly at benchmark → P(true SR > benchmark) == 0.5
    p = ds.probabilistic_sharpe_ratio(0.1, 365, sr_benchmark_per_period=0.1)
    assert abs(p - 0.5) < 1e-6


def test_expected_max_sharpe_grows_with_trials():
    var = 0.01
    assert ds.expected_max_sharpe(var, 100) > ds.expected_max_sharpe(var, 10)
    assert ds.expected_max_sharpe(var, 1) == 0.0  # no multiple-testing with 1 trial


def test_deflation_reduces_confidence():
    sr_pp = ds.deannualize_sharpe(2.0)
    psr0 = ds.probabilistic_sharpe_ratio(sr_pp, 365)
    dsr = ds.deflated_sharpe_ratio(sr_pp, 365, sr_variance_across_trials=0.01, n_trials=64)
    assert dsr["dsr"] <= psr0  # deflation never increases confidence


def test_min_track_record_length():
    assert ds.min_track_record_length(0.1) > 1
    assert ds.min_track_record_length(-0.1) == float("inf")  # no edge → never


def test_cost_model_reduces_apy():
    r = net_of_cost_apy(14.0, 20_000, n_positions=8, rebalances_per_year=52,
                        annual_turnover=4.0, multichain=True)
    assert r["net_apy_pct"] < r["gross_apy_pct"]
    assert r["total_cost_pct"] > 0


def test_moments_normal_ish():
    # symmetric data → skew ~0, kurt ~ near 1.8 for uniform-ish; just assert finite + std>0
    m = ds.moments([0.01, -0.01, 0.02, -0.02, 0.0, 0.015, -0.015])
    assert m["std"] > 0 and math.isfinite(m["skew"]) and math.isfinite(m["kurt"])


def test_evaluator_regime_and_ranking():
    """Evaluator must classify the data regime and rank by the regime-appropriate metric."""
    v = evaluator.evaluate(write=False)
    assert v["regime"] in ("NORMAL", "LOW_VOL_YIELD", "DEGENERATE_MOCK")
    if v["regime"] == "LOW_VOL_YIELD":
        # Real low-vol yield → rank by net-of-cost APY, not Sharpe; validated strategies graded.
        assert v["ranking_metric"] == "net_of_cost_apy"
        board = v["leaderboard_tier1"]
        nets = [s["net_apy_pct"] for s in board if s["validated"]]
        assert nets == sorted(nets, reverse=True)  # validated ranked by net APY desc
        assert all(s["tier1_grade"] in ("A", "B", "C", "D") for s in board)
    elif v["regime"] == "DEGENERATE_MOCK":
        assert v["validated_count"] == 0
        assert all(s["tier1_grade"] == "UNPROVEN" for s in v["leaderboard_tier1"])


def test_evaluator_packages_present():
    v = evaluator.evaluate(write=False)
    assert set(v["packages"].keys()) == {"conservative", "balanced", "aggressive"}
