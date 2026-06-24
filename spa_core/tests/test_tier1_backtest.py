"""Tests for the Tier-1 parallel backtest-validation layer (deterministic, stdlib)."""
import math

from spa_core.backtesting.tier1 import deflated_sharpe as ds
from spa_core.backtesting.tier1.cost_model import net_of_cost_apy
from spa_core.backtesting.tier1 import evaluator
from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.backtesting.tier1 import gate as gate_mod
from spa_core.backtesting.tier1 import correlation as corr_mod
from spa_core.backtesting.tier1 import packages as pkg_mod


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


def test_oos_insufficient_data_when_no_series():
    # No cached protocols → cannot judge OOS, returns insufficient_data (not a crash).
    r = oos_mod.oos_check({"nonexistent_proto": 1.0}, series_map={})
    assert r["status"] == "insufficient_data"
    assert r["oos_holds"] is None


def test_oos_decay_detection_synthetic():
    # in-sample high yield, out-of-sample collapse → oos_holds False.
    dates = [f"2024-{m:02d}-{d:02d}" for m in range(1, 5) for d in range(1, 26)]
    half = len(dates) // 2
    series = {"p": {dt: (0.08 if i < half else 0.02) for i, dt in enumerate(dates)}}
    r = oos_mod.oos_check({"p": 1.0}, series_map=series, split=0.5, tolerance=0.2)
    assert r["status"] == "ok"
    assert r["oos_holds"] is False           # 8% → 2% is a clear decay
    assert r["in_sample_apy_pct"] > r["out_of_sample_apy_pct"]


def test_oos_holds_when_stable():
    dates = [f"2024-{m:02d}-{d:02d}" for m in range(1, 5) for d in range(1, 26)]
    series = {"p": {dt: 0.05 for dt in dates}}  # flat yield
    r = oos_mod.oos_check({"p": 1.0}, series_map=series, split=0.5)
    assert r["oos_holds"] is True


def test_evaluator_oos_gates_validation():
    """Under LOW_VOL_YIELD, validated strategies must not have a failed OOS or capacity."""
    v = evaluator.evaluate(write=False)
    if v["regime"] == "LOW_VOL_YIELD":
        for s in v["leaderboard_tier1"]:
            if s["validated"]:
                assert s["oos_holds"] is not False  # OOS-failed cannot be validated
                assert s["capacity_ok"] is not False  # capacity-failed cannot be validated


def test_gate_eligible_subset_of_validated():
    """The gate's eligible set must equal the verdict's validated set."""
    v = evaluator.evaluate(write=False)
    g = gate_mod.build_gate(write=False)
    validated_ids = {s["id"] for s in v["leaderboard_tier1"] if s["validated"]}
    assert set(g["eligible_for_paper"]) == validated_ids
    assert g["eligible_count"] + g["blocked_count"] == len(v["leaderboard_tier1"])


def test_gate_blocked_have_reasons():
    g = gate_mod.build_gate(write=False)
    assert all(isinstance(r, str) and r for r in g["blocked"].values())


def test_gate_live_divergence_present():
    g = gate_mod.build_gate(write=False)
    assert g["live_vs_backtest"]["status"] in ("ok", "DIVERGENT", "insufficient_data")


def test_gate_is_eligible_fail_open(tmp_path, monkeypatch):
    # Missing gate file → fail-open True (don't block ops on a missing Tier-1 run).
    monkeypatch.setattr(gate_mod, "_OUT", tmp_path / "nonexistent_gate.json")
    assert gate_mod.is_eligible("anything") is True


def test_pearson_perfect_and_insufficient():
    base = [None] + [float(i % 7) - 3 for i in range(60)]
    assert abs(corr_mod._pearson(base, base) - 1.0) < 1e-9        # identical → +1
    inv = [None] + [-(float(i % 7) - 3) for i in range(60)]
    assert abs(corr_mod._pearson(base, inv) + 1.0) < 1e-9         # mirror → -1
    assert corr_mod._pearson([1.0, 2.0], [1.0, 2.0]) is None       # < MIN_OVERLAP


def test_diversified_subset_drops_redundant():
    # a,b perfectly correlated; c independent → subset keeps the higher-rank of {a,b} + c.
    corr = {"a": {"b": 1.0, "c": 0.0}, "b": {"a": 1.0, "c": 0.0}, "c": {"a": 0.0, "b": 0.0}}
    rank = {"a": 5.0, "b": 4.0, "c": 3.0}
    subset = corr_mod._diversified_subset(["a", "b", "c"], corr, rank)
    assert "a" in subset and "c" in subset and "b" not in subset


def test_packages_build_structure():
    o = pkg_mod.build(write=False)
    assert set(o["packages"].keys()) == {"conservative", "balanced", "aggressive"}
    for key, p in o["packages"].items():
        assert p["status"] in ("available", "no_validated_strategies_yet")
        if p["status"] == "available":
            assert p["n_offered"] >= 1
            # every offered strategy must be net-positive
            assert all((s.get("net_apy_pct") or 0) > 0 for s in p["strategies"])


def test_tail_risk_tiers_and_adjustment():
    from spa_core.backtesting.tier1 import tail_risk as tr
    assert tr.protocol_tail_risk_pct("aave_v3") < tr.protocol_tail_risk_pct("maple")  # T1<T2
    assert tr.protocol_tail_risk_pct("cash") == 0.0
    ra = tr.risk_adjusted_net_apy(5.0, {"aave_v3": 0.8, "cash": 0.2})
    assert ra["risk_adjusted_apy_pct"] < ra["net_apy_pct"]   # tail-risk lowers it
    assert ra["tail_risk_pct"] > 0


def test_packages_carry_risk_adjusted():
    o = pkg_mod.build(write=False)
    for p in o["packages"].values():
        for s in p.get("strategies", []):
            assert "risk_adjusted_apy_pct" in s and "tail_risk_pct" in s
            assert s["risk_adjusted_apy_pct"] <= s["net_apy_pct"]


def test_tier1_digest_builds():
    from spa_core.reporting import tier1_digest
    msg = tier1_digest.build_message()
    assert "Tier-1" in msg and "Пакеты" in msg


def test_correlation_analyze_structure():
    a = corr_mod.analyze(write=False)
    assert set(a["packages"].keys()) == {"conservative", "balanced", "aggressive"}
    cons = a["packages"]["conservative"]
    if cons.get("n", 0) >= 2:
        assert cons["diversified_subset_size"] <= cons["n"]  # core never larger than candidates
        if cons["avg_pairwise_corr"] is not None:
            assert -1.0 <= cons["avg_pairwise_corr"] <= 1.0
