"""Tests for edge_tail_portfolio_frontier.py — deterministic sweep, fixture-based.

IS_ADVISORY=True | OUTSIDE_RISKPOLICY=True | LLM_FORBIDDEN
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def _compute(penalise=False):
    from scripts.edge_tail_portfolio_frontier import compute
    return compute(penalise_class_d=penalise)


def test_compute_returns_expected_keys():
    r = _compute(penalise=False)
    for k in ("n_strategies", "strategies", "n_combos", "series_length_days",
               "best_calmar", "best_tail", "equal_weight", "pareto_frontier"):
        assert k in r, f"missing key: {k}"


def test_five_strategies_loaded():
    r = _compute()
    assert r["n_strategies"] == 5  # thin_new excluded (< 30 days)
    assert "points_farm" in r["strategies"]
    assert "thin_new" not in r["strategies"]


def test_series_length_deterministic():
    r = _compute()
    # 2024-07-01 .. 2026-05-31 = 700 days
    assert r["series_length_days"] == 700


def test_simplex_combos_count():
    r = _compute()
    # C(5+10-1, 5-1) with step=10: should be 1001
    assert r["n_combos"] == 1001


def test_best_calmar_is_positive():
    r = _compute()
    bc = r["best_calmar"]
    assert bc["calmar"] is not None and bc["calmar"] > 0


def test_tail_optimal_max_window_loss_minimal():
    r = _compute()
    bt = r["best_tail"]
    # points_farm dominates: max window loss <= 2.0% (usde_unwind hit 0.02)
    assert bt["max_window_loss_pct"] <= 2.1


def test_class_d_penalty_lowers_apy():
    """50% APY cut to points_farm should visibly lower Calmar-optimal APY."""
    r_full = _compute(penalise=False)
    r_pen = _compute(penalise=True)
    apy_full = r_full["best_calmar"]["apy"]
    apy_pen = r_pen["best_calmar"]["apy"]
    assert apy_pen < apy_full, f"penalty should lower APY: {apy_pen} vs {apy_full}"


def test_equal_weight_worse_than_optimal():
    r = _compute()
    eq = r["equal_weight"]
    bc = r["best_calmar"]
    if eq and eq["calmar"] is not None and bc["calmar"] is not None:
        assert bc["calmar"] > eq["calmar"]


def test_pareto_frontier_monotone_window_loss():
    r = _compute()
    pf = r["pareto_frontier"]
    losses = [row["max_window_loss_pct"] for row in pf]
    assert losses == sorted(losses), "pareto frontier must be sorted by max-window-loss"


def test_calmar_and_tail_optimal_coincide_on_fixture():
    """Key finding: on fixture, the two objectives collapse to the same solution."""
    r = _compute()
    bc_w = r["best_calmar"]["weights"]
    bt_w = r["best_tail"]["weights"]
    # Both should point to 100% points_farm
    assert bc_w == bt_w, (
        f"Expected Calmar-optimal == tail-optimal on fixture; got {bc_w} vs {bt_w}"
    )


def test_penalise_class_d_flag_stored():
    r_full = _compute(penalise=False)
    r_pen = _compute(penalise=True)
    assert r_full["penalise_class_d"] is False
    assert r_pen["penalise_class_d"] is True


def test_deterministic_across_two_calls():
    r1 = _compute()
    r2 = _compute()
    assert r1["best_calmar"]["calmar"] == r2["best_calmar"]["calmar"]
    assert r1["best_tail"]["max_window_loss_pct"] == r2["best_tail"]["max_window_loss_pct"]
