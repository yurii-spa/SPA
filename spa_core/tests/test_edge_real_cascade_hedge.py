# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_real_cascade_hedge.py (registry idea #21).

These lock the properties idea #21's honest verdict depends on:
  • gap days are COMPOUNDED, never dropped (the flaw that inflated the first run);
  • metrics annualise on CALENDAR days, not on the number of grid steps;
  • the funding accrued to the short leg sums every calendar day inside a step;
  • the hedge sizing signal is CAUSAL — a funding spike on day t can never size day t;
  • the short leg's sign convention is right: positive funding PAYS the short, and a
    falling ETH price is a GAIN for the short;
  • downside_beta conditions on the worst-decile x days (the premise test's core measure).

Everything runs on hand-checkable synthetic series — no repo data, no network.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "edge_real_cascade_hedge", ROOT / "scripts" / "edge_real_cascade_hedge.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


# ── grid mechanics: gaps must compound, not vanish ───────────────────────────────────────────────
def test_step_returns_compound_across_gap():
    levels = {"2024-01-01": 100.0, "2024-01-05": 90.0}
    grid = ["2024-01-01", "2024-01-05"]
    got = mod.step_returns(levels, grid)
    assert len(got) == 1
    assert math.isclose(got[0], -0.1, rel_tol=1e-12)     # the −10% inside the gap is NOT lost


def test_step_days_counts_calendar_days():
    assert mod.step_days(["2024-01-01", "2024-01-05", "2024-01-06"]) == [4, 1]


def test_metrics_annualise_on_calendar_days_not_steps():
    grid = ["2024-01-01", "2024-07-01", "2025-01-01"]   # 366 calendar days, 2 steps
    m = mod.metrics(grid, [0.05, 0.05])
    assert m["steps"] == 2
    assert m["days"] == 366
    expected = ((1.05 * 1.05) ** (365.0 / 366.0) - 1.0) * 100.0
    assert math.isclose(m["apy_pct"], expected, rel_tol=1e-9)


def test_metrics_maxdd_and_calmar():
    grid = ["2024-01-01", "2024-01-02", "2024-01-03"]
    m = mod.metrics(grid, [0.10, -0.20])                  # peak 1.10 → 0.88
    assert math.isclose(m["maxDD_pct"], 20.0, rel_tol=1e-9)
    assert m["calmar"] < 0                                # losing series → negative Calmar


# ── funding accrual on the short leg ─────────────────────────────────────────────────────────────
def test_step_funding_sums_every_calendar_day_in_the_step():
    funding = {"2024-01-02": 0.0001, "2024-01-03": 0.0002, "2024-01-04": 0.0003}
    got = mod.step_funding(funding, ["2024-01-01", "2024-01-04"])
    assert math.isclose(got[0], 3 * (0.0001 + 0.0002 + 0.0003), rel_tol=1e-12)


def test_step_funding_ignores_the_opening_date_of_the_step():
    funding = {"2024-01-01": 1.0, "2024-01-02": 0.0001}
    got = mod.step_funding(funding, ["2024-01-01", "2024-01-02"])
    assert math.isclose(got[0], 3 * 0.0001, rel_tol=1e-12)   # opening day belongs to prior step


# ── causality of the sizing signal ───────────────────────────────────────────────────────────────
def _daily_grid(n: int, start="2024-01-01"):
    import datetime
    d0 = datetime.date.fromisoformat(start)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def test_gate_uses_only_strictly_past_funding():
    grid = _daily_grid(30)
    negative = {d: -0.001 for d in grid}
    # a huge POSITIVE spike on the last day must not switch that same day's hedge on
    negative[grid[-1]] = +1.0
    w = mod.hedge_weights("gated", grid, negative, h=0.10)
    assert w[-1] == 0.0


def test_gate_reacts_one_step_after_the_signal_flips():
    grid = _daily_grid(30)
    funding = {d: (0.001 if i < 15 else -0.001) for i, d in enumerate(grid)}
    w = mod.hedge_weights("gated", grid, funding, h=0.10)
    assert w[5] == 0.10                       # positive-funding regime → hedge on
    assert w[-1] == 0.0                       # after the flip persists → hedge off


def test_gate_failclosed_before_enough_history():
    grid = _daily_grid(5)
    funding = {grid[0]: 0.001, grid[1]: 0.001}      # only 2 usable days of history
    w = mod.hedge_weights("gated", grid, funding, h=0.10)
    assert w[0] == 0.0                              # no signal → no hedge (fail-closed)


def test_static_mode_is_constant_and_ignores_funding():
    grid = _daily_grid(10)
    funding = {d: -0.05 for d in grid}
    assert mod.hedge_weights("static", grid, funding, h=0.07) == [0.07] * 9


def test_thin_gate_needs_carry_above_the_live_threshold():
    grid = _daily_grid(30)
    thin = 0.9 * mod.THIN_CARRY_ANN / (mod.FUNDING_PERIODS_PER_DAY * 365.0)
    rich = 1.5 * mod.THIN_CARRY_ANN / (mod.FUNDING_PERIODS_PER_DAY * 365.0)
    assert mod.hedge_weights("thin", grid, {d: thin for d in grid}, h=0.10)[-1] == 0.0
    assert mod.hedge_weights("thin", grid, {d: rich for d in grid}, h=0.10)[-1] == 0.10


# ── short-leg sign conventions ───────────────────────────────────────────────────────────────────
def test_short_gains_when_eth_falls_and_is_paid_when_funding_positive():
    grid = _daily_grid(3)
    funding = {d: 0.0 for d in grid}
    core = [0.0, 0.0]
    eth = [-0.10, 0.0]                                   # ETH −10% on the first step
    fund = [0.0, 0.02]                                   # +2% funding accrued on the second
    rets, dec = mod.run_overlay(grid, core, eth, fund, h=0.50, mode="static",
                                funding=funding, fee_bps=0.0)
    assert math.isclose(rets[0], 0.05, rel_tol=1e-12)    # short 50% of a −10% move → +5%
    assert math.isclose(rets[1], 0.01, rel_tol=1e-12)    # short RECEIVES positive funding
    assert dec["hedge_price_pnl_pct"] > 0
    assert dec["hedge_funding_income_pct"] > 0


def test_negative_funding_costs_the_short():
    grid = _daily_grid(2)
    rets, _ = mod.run_overlay(grid, [0.0], [0.0], [-0.01], h=1.0, mode="static",
                              funding={d: 0.0 for d in grid}, fee_bps=0.0)
    assert math.isclose(rets[0], -0.01, rel_tol=1e-12)


def test_costs_reduce_returns_and_scale_with_turnover():
    grid = _daily_grid(2)
    free, _ = mod.run_overlay(grid, [0.0], [0.0], [0.0], h=1.0, mode="static",
                              funding={d: 0.0 for d in grid}, fee_bps=0.0)
    paid, dec = mod.run_overlay(grid, [0.0], [0.0], [0.0], h=1.0, mode="static",
                                funding={d: 0.0 for d in grid}, fee_bps=10.0)
    assert paid[0] < free[0]
    assert dec["hedge_cost_pct"] > 0


def test_zero_hedge_is_exactly_the_core():
    grid = _daily_grid(4)
    core = [0.001, -0.002, 0.003]
    rets, dec = mod.run_overlay(grid, core, [0.05, -0.05, 0.05], [0.01, 0.01, 0.01],
                                h=0.0, mode="static", funding={d: 0.0 for d in grid},
                                fee_bps=10.0)
    assert rets == core
    assert dec["hedge_duty_pct"] == 0.0


# ── core portfolios ──────────────────────────────────────────────────────────────────────────────
def test_core_a_weights_the_real_book_at_25pct_plus_constant_legs():
    steps = {"susde_dn": [0.04]}
    got = mod.core_returns("A", steps, [1])[0]
    expected = 0.25 * 0.04 + 0.50 * (mod.RATES_CARRY_APY / 365.0) + 0.25 * (mod.RWA_FLOOR_APY / 365.0)
    assert math.isclose(got, expected, rel_tol=1e-12)


def test_core_a_constant_legs_accrue_over_gap_days():
    steps = {"susde_dn": [0.0]}
    one = mod.core_returns("A", steps, [1])[0]
    four = mod.core_returns("A", steps, [4])[0]
    assert math.isclose(four, 4 * one, rel_tol=1e-12)


def test_core_b_is_equal_weight_of_three_real_books():
    steps = {"susde_dn": [0.03], "susde_spot": [0.06], "points_farm": [0.0]}
    assert math.isclose(mod.core_returns("B", steps, [1])[0], 0.03, rel_tol=1e-12)


# ── premise diagnostic ───────────────────────────────────────────────────────────────────────────
def test_downside_beta_finds_a_planted_crisis_comovement():
    x = [-0.10 if i < 10 else 0.001 * ((i % 5) - 2) for i in range(100)]
    y = [2.0 * v for v in x]
    beta, mean_y = mod.downside_beta(x, y)
    assert math.isclose(mean_y, -0.20, rel_tol=1e-6)      # co-moves on the worst days
    assert beta == 0.0 or math.isclose(beta, 2.0, rel_tol=1e-6)


def test_downside_beta_is_zero_for_an_uncorrelated_flat_book():
    x = [-0.10 if i < 10 else 0.01 for i in range(100)]
    y = [0.0005] * 100                                    # steady carry, no co-movement
    beta, mean_y = mod.downside_beta(x, y)
    assert math.isclose(beta, 0.0, abs_tol=1e-9)
    assert mean_y > 0                                     # a hedge would have nothing to pay for


def test_downside_beta_failclosed_on_short_series():
    assert mod.downside_beta([0.1, -0.1], [0.1, -0.1]) == (0.0, 0.0)


# ── degenerate variance: a FLAT worst decile has no beta, and must not invent one ────────────────
# Cycle #47, card agent-downside-beta-degenerate-variance.  These are additive — no assert above
# was changed.  The old code guarded with `var > 0`, which cannot tell "the decile is flat" from
# "the decile has dispersion": with a flat decile the mean is not bit-exact, so `var` is the SQUARE
# of that rounding error and `cov / var` is one rounding over another.  How big that noise comes
# out is interpreter-dependent (CPython 3.12 made `sum()` compensated), which is why CI was red on
# Linux/py3.11 and green on py3.12 for the SAME input.  The flat values below (±0.23) are chosen so
# that `sum([v] * 10) / 10 != v` under BOTH naive and compensated summation — the degeneracy
# reproduces on every interpreter, not by luck.


def _flat_decile_series(x_value, y_value, n=100):
    """n-day series whose worst decile is exactly `x_value` on every one of its 10 days."""
    x = [x_value if i < 10 else 0.01 for i in range(n)]
    y = [y_value] * n
    return x, y


def test_downside_beta_refuses_a_flat_decile_instead_of_dividing_two_roundings():
    # Pre-guard this exact input returned beta = -1.000 — a full-strength crisis co-movement
    # conjured out of floating-point dust, on a book that never moved at all.
    x, y = _flat_decile_series(-0.23, 0.23)
    beta, mean_y = mod.downside_beta(x, y)
    assert beta == 0.0
    assert math.isclose(mean_y, 0.23, rel_tol=1e-12)


def test_downside_beta_refuses_a_flat_decile_for_every_flat_book_value():
    # The noise ratio depends on the ulps of x and y, so a single pair proves little: sweep.
    x_flat = -0.23
    for y_flat in (0.0005, 0.01, 0.07, 0.1, 0.123456789, 0.23, 1.0 / 3.0, -0.23):
        x, y = _flat_decile_series(x_flat, y_flat)
        beta, mean_y = mod.downside_beta(x, y)
        assert beta == 0.0, f"invented beta {beta!r} from a flat book y={y_flat!r}"
        assert math.isclose(mean_y, y_flat, rel_tol=1e-12)


def test_downside_beta_refuses_an_all_zero_decile():
    x, y = _flat_decile_series(0.0, 0.0005)
    assert mod.downside_beta(x, y)[0] == 0.0


def test_downside_beta_still_measures_a_decile_that_really_does_disperse():
    # Guard against over-clamping: a planted co-movement with REAL dispersion inside the worst
    # decile must still come back as the true beta, exactly.
    x = [-0.10 - 0.001 * i if i < 10 else 0.01 for i in range(100)]
    y = [2.0 * v for v in x]
    beta, mean_y = mod.downside_beta(x, y)
    assert math.isclose(beta, 2.0, rel_tol=1e-12)
    assert mean_y < 0


def test_downside_beta_does_not_clamp_dispersion_that_is_small_but_real():
    # Relative std here is ~4e-5 of the data scale — six orders above rounding noise and four
    # below the 1e-9 refusal threshold, i.e. squarely inside "real signal".
    x = [-0.10 - 1e-5 * i if i < 10 else 0.01 for i in range(100)]
    y = [2.0 * v for v in x]
    beta, _ = mod.downside_beta(x, y)
    assert math.isclose(beta, 2.0, rel_tol=1e-9)


def test_downside_beta_refusal_threshold_is_relative_not_absolute():
    # Scaling the whole problem down must not turn a real measurement into a refusal: an absolute
    # variance threshold would swallow this, a relative one does not.
    x = [1e-9 * (-0.10 - 0.001 * i) if i < 10 else 1e-9 * 0.01 for i in range(100)]
    y = [2.0 * v for v in x]
    beta, _ = mod.downside_beta(x, y)
    assert math.isclose(beta, 2.0, rel_tol=1e-9)


def test_ols_beta_shares_the_same_refusal():
    # main()'s β(all days) column used to carry its own inline copy of the `var > 0` guard; it is
    # the same helper now, so the same flat sample must refuse there too.
    assert mod.ols_beta([-0.23] * 40, [0.23] * 40)[0] == 0.0
    xs = [-0.10 - 0.001 * i for i in range(40)]
    assert math.isclose(mod.ols_beta(xs, [2.0 * v for v in xs])[0], 2.0, rel_tol=1e-12)


def test_ols_beta_failclosed_on_empty_sample():
    assert mod.ols_beta([], []) == (0.0, 0.0)
