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


# ── reverse premise check: a verdict must not fire on a random draw ──────────────────────────────
# Card `agent-idea21-verdict-data-drift`.  The published run (2026-07-29) said ETH averaged
# -0.077%/d on CORE-A's worst days ⇒ "hedge CANNOT pay"; on 2026-08-01 the same script on the same
# aligned grid (591 points, identical bounds) said -0.810%/d ⇒ "hedge CAN pay".  Neither number was
# a measurement: CORE-A's daily dispersion is 0.0076%/d against ETH's 3.92%/d, so ranking days by
# the core selects ~a random 42-of-427 draw, and a random draw clears the old -0.5%/d bar 32.1% of
# the time (200k-draw permutation, seed 20260801).  These tests pin the refusal.
def _flat_selection_case():
    """The real CORE-A case, reconstructed exactly and by hand.

    n=427 ETH days, drift -0.231%/d, dispersion 3.92%/d; the 42 "selected" days average
    -0.810%/d — the very number that flipped the published verdict on 2026-08-01.  Every value is
    placed explicitly so the arithmetic is checkable without running anything:
        se = 0.0392/sqrt(42) * sqrt(385/426) = 0.005750
        z  = (-0.00810 - (-0.00231)) / 0.005750 = -1.007      → an utterly ordinary draw
    """
    spread, obs_mean, uncond = 0.0392, -0.0081, -0.00231
    # 42 selected days: symmetric around obs_mean, so their mean is EXACTLY obs_mean
    selected_vals = [obs_mean + spread, obs_mean - spread] * 21
    # 385 remaining days, symmetric around whatever makes the population mean exactly `uncond`
    mu_rest = (427 * uncond - 42 * obs_mean) / 385
    rest_vals = [mu_rest + spread, mu_rest - spread] * 192 + [mu_rest]
    eth = selected_vals + rest_vals
    return eth, list(range(42))


def test_conditional_mean_z_matches_the_exact_sampling_distribution():
    # Positive control for the formula, by ENUMERATION: for a small population the sd of every
    # C(n,k) subset mean is computable exactly, and the z the MODULE returns must be the observed
    # deviation measured in exactly those units.  Note this asserts against `mod.…`, not against a
    # second copy of the formula written here — a test that recomputes the implementation and
    # compares it to itself passes no matter what the implementation does.
    import itertools
    import statistics as st
    vals = [0.3, -1.2, 0.7, 2.5, -0.4, 1.1, -2.2, 0.9]
    n, k = len(vals), 3
    subset_means = [st.fmean(c) for c in itertools.combinations(vals, k)]
    exact_se = st.pstdev(subset_means)
    # the sampling distribution is centred on the unconditional mean
    assert math.isclose(st.fmean(subset_means), st.fmean(vals), rel_tol=1e-12)
    selected = [0, 2, 3]            # values 0.3, 0.7, 2.5
    obs, uncond, z, measured = mod.conditional_mean_z(vals, selected)
    assert measured
    assert math.isclose(obs, st.fmean([vals[i] for i in selected]), rel_tol=1e-12)
    assert math.isclose(z, (obs - uncond) / exact_se, rel_tol=1e-12), (
        "z must be scaled by the EXACT finite-population standard error")


def test_conditional_mean_z_uses_the_unconditional_mean_as_the_null_not_zero():
    # A drifting series whose selected days sit exactly ON the drift shows NO co-movement.
    # Measuring against zero instead would report the drift itself as a finding — so the two nulls
    # are made to disagree violently here (z=0 vs z≈-19), otherwise the test cannot tell them apart.
    mu, spread = -0.05, 0.02
    vals = [mu + spread, mu - spread] * 200
    selected = list(range(50))                 # 25 above, 25 below ⇒ mean is EXACTLY mu
    obs, got_uncond, z, measured = mod.conditional_mean_z(vals, selected)
    assert measured
    assert math.isclose(obs, mu, abs_tol=1e-15) and math.isclose(got_uncond, mu, abs_tol=1e-15)
    assert abs(z) < 0.5, f"days sitting on the drift must not read as co-movement, got z={z}"
    # and the drift is big enough that a zero null would scream: |mu/se| ≈ 19
    se = (spread / (len(selected) ** 0.5)) * (((len(vals) - len(selected)) / (len(vals) - 1)) ** 0.5)
    assert abs(mu / se) > 10.0, "fixture must make the wrong null obvious, else it tests nothing"


def test_conditional_mean_z_refuses_a_perfectly_flat_series():
    # points_farm is EXACTLY this on the real panel (daily sd 0.0000%): no sampling spread exists,
    # so no z exists.  Refuse instead of dividing by zero.
    obs, uncond, z, measured = mod.conditional_mean_z([0.004] * 100, list(range(10)))
    assert measured is False
    assert z == 0.0


def test_conditional_mean_z_refuses_degenerate_selections():
    vals = [0.1 * i for i in range(50)]
    assert mod.conditional_mean_z(vals, [])[3] is False          # nothing selected
    assert mod.conditional_mean_z(vals, list(range(50)))[3] is False   # everything selected
    assert mod.conditional_mean_z([1.0], [0])[3] is False         # no population


def test_hedge_can_pay_refuses_a_verdict_that_a_random_draw_would_also_produce():
    # THE regression: observed is well past the -0.5%/d economic bar, yet the draw is ordinary.
    # The old code printed "hedge CAN pay" here; the honest answer is "NOT MEASURED".
    eth, selected = _flat_selection_case()
    obs, _, z, measured = mod.conditional_mean_z(eth, selected)
    assert measured and obs < -0.005, "fixture must clear the OLD bar, else it tests nothing"
    assert abs(z) < 2.0, f"fixture must be an ordinary draw, got z={z}"
    verdict, detail = mod.hedge_can_pay(eth, selected)
    assert verdict is None, f"expected NOT MEASURED, got {verdict} ({detail})"
    assert "random draw" in detail["reason"]


def test_hedge_can_pay_none_is_not_the_same_claim_as_false():
    # Conflating "cannot tell" with "no co-movement" is the fail-OPEN class this repo keeps
    # finding.  They must be distinguishable by the caller.
    eth, selected = _flat_selection_case()
    assert mod.hedge_can_pay(eth, selected)[0] is not False


def test_hedge_can_pay_confirms_a_planted_real_comovement():
    # Positive control: ETH really does crash on exactly the selected days.
    eth = [0.001] * 200
    selected = list(range(20))
    for i in selected:
        eth[i] = -0.09
    verdict, detail = mod.hedge_can_pay(eth, selected)
    assert verdict is True, detail
    assert detail["z"] < -2.0


def test_hedge_can_pay_rejects_a_real_but_immaterial_concentration():
    # Statistically unmistakable, economically pointless: -0.2%/d does not justify a hedge.
    eth = [0.0] * 400
    selected = list(range(40))
    for i in selected:
        eth[i] = -0.002
    verdict, detail = mod.hedge_can_pay(eth, selected)
    assert verdict is False, detail
    assert detail["z"] < -2.0 and detail["observed_pct"] / 100.0 >= -0.005


def test_hedge_can_pay_refuses_when_the_selecting_series_is_flat():
    verdict, detail = mod.hedge_can_pay([0.004] * 100, list(range(10)))
    assert verdict is None
    assert detail["z"] is None


def test_hedge_can_pay_both_bars_must_clear_independently():
    # material but not significant → None;  significant but not material → False;  both → True.
    eth, selected = _flat_selection_case()
    assert mod.hedge_can_pay(eth, selected)[0] is None
    small = [0.0] * 400
    for i in range(40):
        small[i] = -0.002
    assert mod.hedge_can_pay(small, list(range(40)))[0] is False
    big = [0.0] * 400
    for i in range(40):
        big[i] = -0.06
    assert mod.hedge_can_pay(big, list(range(40)))[0] is True


# ── provenance: bounds and row counts are blind to a rewritten history ───────────────────────────
def test_series_fingerprint_catches_a_rewritten_history_that_bounds_cannot_see():
    # Measured on the real repo: susde_dn's 853 historical rows were REGENERATED between the
    # 2026-07-25 backup and 2026-08-01 (up to -9.70%), with the row count and both date bounds
    # unchanged.  That is precisely what defeated the card's "the books just grew" hypothesis.
    old = {f"2024-01-{d:02d}": 100.0 + d for d in range(1, 21)}
    new = dict(old)
    new["2024-01-05"] = 999.0            # same rows, same first/last date, different history
    assert len(old) == len(new) and min(old) == min(new) and max(old) == max(new)
    assert mod.series_fingerprint(old) != mod.series_fingerprint(new)


def test_series_fingerprint_is_stable_and_order_independent():
    a = {"2024-01-02": 2.0, "2024-01-01": 1.0}
    b = {"2024-01-01": 1.0, "2024-01-02": 2.0}
    assert mod.series_fingerprint(a) == mod.series_fingerprint(b)
    assert mod.series_fingerprint(a) == mod.series_fingerprint(dict(a))
