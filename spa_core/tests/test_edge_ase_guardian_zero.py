"""Controls for scripts/edge_admitted_set_guardian_zero.py — registry #131 (ASE), #132 (GZ).

Every test is a POSITIVE CONTROL for a defect this registry has actually measured, not a
restatement of what the code does:

  * #129 measured an acceptance criterion satisfied BY DEGENERACY: Calmar beat the base because
    the denominator vanished, not because the numerator grew. `test_three_conditions_*` and
    `test_delta_calmar_refuses_*` go red if either guard is dropped.
  * #128 p.5 measured that under a 20 % ceiling with <= 5 admitted names the 1/sigma denominator
    is INERT — bit-identical float64 across five orders of sigma_floor. `test_k_star_*` and
    `test_sigma_floor_*` keep that threshold measured rather than asserted, AND name the float
    artefact that makes the naive version of the same measurement answer 5 instead of 6.
  * #122 measured that on this panel "moved least" means "NOT MEASURED", never "safe".
    `test_falling_census_*` keeps the three outcomes apart (inv. #17).
  * the whole series' comparability rests on using ONE instrument set: this file's single owned
    loop is checked BITWISE against #128's `run_sizer` for the rule they share
    (`test_rule_loop_reproduces_sfs_bitwise`). Without that, "the expanded set is better" could
    just be "the second copy of the loop computes something else".
  * table #1 was published per-book, on the stress fixture, with NO transaction cost, while both
    registry zeros pay 96 bp. `test_exposure_switches_*` keeps the toll countable, so a free
    overlay can never be compared against a tolled basket by accident.

The panel is BUILT HERE, in tmp, and never read from data/: data/aggressive_lab is runtime-only
(gitignored), so a test that reached for it would be green on this Mac and "NOT MEASURED" in CI —
the exact substitution the rules forbid.
"""
# FROZEN-DATE-OK: panel-axis-geometry — the literal dates here ARE the subject, and the claim is
# verified rather than asserted: neither scripts/edge_admitted_set_guardian_zero.py nor the two
# modules it imports (scripts/edge_sigma_floor_ctac_real.py, scripts/edge_real_panel_ensemble.py)
# nor scripts/guardian_backtest.py contains a single wall-clock door — no datetime.now / utcnow /
# time.time / date.today — so nothing in this file is judged against the calendar and nothing here
# can rot as the calendar moves. That absence is itself asserted below by
# `test_no_wall_clock_door_in_the_measured_path`, so the claim in this comment is MEASURED, not a
# note. What the dates DO carry is geometry: the harness refuses an axis shorter than 200 common
# days and the train/test seam is the harness's own TRAIN_END literal (2025-06-30), so a synthetic
# panel that wants a seam inside its axis has to start before it and run past it, exactly as the
# real panel does. Relative stamps (preference #2) cannot express that, and injecting a clock
# (preference #1) would inject something no reader of this code consults. This is preference #3 of
# .claude/rules/deployment.md: the date is the subject.
from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"
SFS_SCRIPT = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"
PANEL_SCRIPT = ROOT / "scripts" / "edge_real_panel_ensemble.py"
GUARDIAN_SCRIPT = ROOT / "scripts" / "guardian_backtest.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("edge_ase_guardian_zero", SCRIPT)
    assert spec and spec.loader, f"cannot import {SCRIPT}"
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ───────────────────────────── the synthetic panel ─────────────────────────────
#: long enough for plb_load's own refusal (>= 200 common days), the 30-day lookback, AND a
#: train/test seam strictly inside the judged slice.
N_DAYS = 700
START = "2024-03-06"


def _dates(n: int = N_DAYS, start: str = START):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_book(root: Path, rets, *, killed_on=None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    dates = _dates(len(rets) + 1)
    eq = 100_000.0
    lines = []
    for i, d in enumerate(dates):
        if i:
            eq *= 1.0 + rets[i - 1]
        lines.append(json.dumps({
            "as_of": d, "date": d, "equity_usd": round(eq, 6), "phase": "backtest",
            "killed": bool(killed_on and d >= killed_on), "is_advisory": True,
            "outside_riskpolicy": True, "net_apy_pct": 0.0, "mtm_today_pct": 0.0,
        }))
    (root / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture(scope="module")
def panel(tmp_path_factory) -> Path:
    """A panel carrying every shape #122-#129 found on the real one, plus the ASE question.

    quiet    — monotone up, NOT ONE day below zero, but the daily step VARIES. This is the real
               points_farm shape (852 moving days, 0 down days): the name a downside rule can
               never admit and a liveness rule can. The variation is deliberate and was found by
               this test: a CONSTANT-step book has sigma = 0 exactly, so the liveness rule refuses
               it too, and a fixture built that way would have proved the opposite of the panel.
    constant — a flat line: moves never, falls never, sigma exactly 0. The shape that separates
               "never falls" from "never moves" — the liveness rule must refuse THIS one.
    frozen   — one move, then dead. The lp_eth_stable shape: cash wearing a book's name.
    noisy_a..e — five two-sided books, so the live arm holds EXACTLY 5 ever-falling names + quiet,
               reproducing the arithmetic that makes the real panel's answer a refusal.
    """
    root = tmp_path_factory.mktemp("panel_ase")
    n = N_DAYS - 1
    _write_book(root / "quiet", [0.0003 + 0.0002 * ((i % 7) / 7.0) for i in range(n)])
    _write_book(root / "constant", [0.0] * n)
    _write_book(root / "frozen", [0.01] + [0.0] * (n - 1), killed_on=_dates()[4])
    for j, name in enumerate(("noisy_a", "noisy_b", "noisy_c", "noisy_d", "noisy_e")):
        amp = 0.002 * (j + 1)
        _write_book(root / name,
                    [(amp if i % (j + 2) else -amp * 0.8) for i in range(n)])
    return root


@pytest.fixture(scope="module")
def loaded(mod, panel):
    H = mod.panel_mod()
    axis, rets, books = H.plb_load(panel)
    return H, axis, rets, books


# ═════════════ the comparability control: one instrument set, not two ═════════════
def test_rule_loop_reproduces_sfs_bitwise(mod, loaded):
    """This file's own loop must equal #128's `run_sizer` BIT FOR BIT on the rule they share.

    Without this, every number of #131 could differ from #128's by a quiet reimplementation
    rather than by the admitted set — the one way the whole entry could be green and meaningless.
    """
    H, axis, rets, books = loaded
    S = mod.sfs_mod()
    lo, hi = 30, len(axis)
    mine = mod.run_sizer_rule(rets, books, lo=lo, hi=hi, rule=mod.rule_down_days(30),
                              lookback=30, sigma_floor=1e-5, cap=mod.POLICY_CAP)
    theirs = S.run_sizer(rets, books, lo=lo, hi=hi, lookback=30, sigma_floor=1e-5,
                         refuse_no_down_days=True, cap=S.POLICY_CAP)
    for key in ("apy_net", "apy_gross", "maxdd", "calmar", "max_name_weight",
                "mean_deployed", "turnover_per_day", "days_over_policy_cap"):
        assert mine[key] == theirs[key], (
            f"{key} differs: {mine[key]!r} vs {theirs[key]!r} — the two loops are not the "
            f"same instrument, so no number of #131 is comparable with #128")
    assert mine["series"] == theirs["series"]


def test_the_shared_rule_is_the_only_thing_they_share(mod, loaded):
    """Control on the control: with a DIFFERENT admission rule the two loops must diverge.

    A bitwise-equality test that passes for every rule would prove the rule argument is ignored.
    """
    H, axis, rets, books = loaded
    S = mod.sfs_mod()
    lo, hi = 30, len(axis)
    mine = mod.run_sizer_rule(rets, books, lo=lo, hi=hi, rule=mod.rule_admit_all,
                              lookback=30, cap=mod.POLICY_CAP)
    theirs = S.run_sizer(rets, books, lo=lo, hi=hi, lookback=30, refuse_no_down_days=True,
                         cap=S.POLICY_CAP)
    assert mine["apy_net"] != theirs["apy_net"], "the admission rule argument does nothing"


# ═════════════════════════ #131 §1: the k* threshold ═════════════════════════
def test_k_star_is_measured_not_asserted(mod):
    """k* = ceil(1/cap) + 1 for every ceiling — and it comes out of the water-fill, not a formula."""
    for cap, expected in ((0.20, 6), (0.25, 5), (0.10, 11), (0.50, 3)):
        a = mod.arithmetic_thresholds(cap=cap, kmax=14)
        assert a["k_flat_threshold"] == expected, (
            f"cap {cap}: k* measured {a['k_flat_threshold']}, arithmetic says {expected}")


def test_k_star_exact_tolerance_is_the_named_float_artefact(mod):
    """The naive (exact-equality) version of the same measurement answers 5, and that is a bug.

    At k = 5 under a 20 % ceiling the water-fill returns 0.2, 0.2, 0.2, 0.2, 0.19999999999999996:
    four names at the ceiling and a fifth carrying the float64 residue of the last renormalising
    division. If this test ever goes green with BOTH thresholds equal, the artefact has either
    been fixed upstream (then update the entry) or silently inherited (then the printed k* is a
    rounding remainder masquerading as a decision).
    """
    a = mod.arithmetic_thresholds(cap=0.20, kmax=12)
    assert a["k_flat_threshold"] == 6
    assert a["k_flat_threshold_exact"] == 5, "the artefact this entry names has disappeared"
    row5 = next(r for r in a["rows"] if r["k"] == 5)
    assert row5["flat_eps"] is True and row5["flat_exact"] is False
    assert 0.0 < row5["spread"] < 1e-12, (
        f"the k=5 spread is {row5['spread']!r} — if it is economically large the entry's claim "
        f"that it is a float residue is wrong")


def test_the_letter_of_the_order_is_satisfied_by_a_degenerate_branch(mod):
    """#129's lesson, reproduced on #129's own order: `bitwise != EW` is true already at k = 1.

    With k < 1/cap the ceiling pins every name and parks the rest in CASH, so the vector differs
    from equal weight (which deploys 1/k > cap per name) while expressing nothing at all. An
    entry that reported the bitwise threshold as the answer would be reporting k = 1.
    """
    a = mod.arithmetic_thresholds(cap=0.20, kmax=12)
    assert a["k_bitwise_threshold"] == 1
    for k in (1, 2, 3, 4):
        row = next(r for r in a["rows"] if r["k"] == k)
        assert row["flat_eps"] is True, "the denominator must be inert below 1/cap"
        assert row["bitwise_ew"] is False
        assert row["cash"] > 0.0 and row["degenerate"], "the cash branch must say so out loud"


def test_is_flat_controls_in_both_directions(mod):
    """A tolerance that accepts everything, or nothing, would make the threshold meaningless."""
    names = ["a", "b"]
    assert mod.is_flat({"a": 0.2, "b": 0.2}, names, tol=0.0) is True
    assert mod.is_flat({"a": 0.2, "b": 0.19999999999999996}, names, tol=0.0) is False
    assert mod.is_flat({"a": 0.2, "b": 0.19999999999999996}, names, tol=mod.EPS) is True
    assert mod.is_flat({"a": 0.2, "b": 0.19}, names, tol=mod.EPS) is False, (
        "a 1 pp difference is a decision, not a residue")
    assert mod.is_flat({}, [], tol=mod.EPS) is True


def test_is_bitwise_ew_controls_in_both_directions(mod):
    assert mod.is_bitwise_ew({"a": 0.5, "b": 0.5}, ["a", "b"]) is True
    assert mod.is_bitwise_ew({"a": 0.2, "b": 0.2}, ["a", "b"]) is False
    assert mod.is_bitwise_ew({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}, ["a", "b", "c"]) is True


# ════════════════ #131 §2: does the set exist — three outcomes (inv. #17) ════════════════
def test_falling_census_keeps_three_outcomes_apart(mod, loaded):
    """`down` / `no_down_day` / `unmeasured_empty` must never collapse into one another."""
    H, axis, rets, books = loaded
    c = mod.falling_census(rets, books, lo=0, hi=len(axis))
    assert c["per_book"]["quiet"]["status"] == "no_down_day"
    assert c["per_book"]["quiet"]["down_days"] == 0, "a measured zero is a number, not None"
    assert c["per_book"]["noisy_a"]["status"] == "down"
    assert c["per_book"]["noisy_a"]["down_days"] > 0
    empty = mod.falling_census(rets, books, lo=5, hi=5)
    assert empty["per_book"]["quiet"]["status"] == "unmeasured_empty"
    assert empty["per_book"]["quiet"]["down_days"] is None, (
        "an empty slice must not report zero down days — that is the substitution inv. #17 forbids")


def test_the_quiet_book_is_the_one_no_downside_rule_can_admit(mod, loaded):
    """The mechanism behind the refusal: a never-falling book is unreachable by any window length."""
    H, axis, rets, books = loaded
    for lookback in (30, 60, 90, 200):
        rule = mod.rule_down_days(lookback)
        assert rule(rets, "quiet", len(axis)) is False, (
            f"a {lookback}-day downside window admitted a book that never falls")
    assert mod.rule_ever_down(rets, "quiet", len(axis)) is False
    assert mod.rule_sigma_positive(30)(rets, "quiet", len(axis)) is True, (
        "a LIVENESS rule must admit it — that difference is the whole finding of #131")
    # and the rule keys on VARIATION, not on "has a positive return": a flat book is refused by
    # both families, so the liveness rule is not simply "admit everything that is not negative".
    assert mod.rule_sigma_positive(30)(rets, "constant", len(axis)) is False
    assert mod.rule_down_days(30)(rets, "constant", len(axis)) is False


def test_admission_rules_are_causal(mod, loaded):
    """No rule may read the day whose weight it decides. Mutate that day; the verdict must hold.

    This is the one defect that would make every positive number of #131 a look-ahead artefact,
    and ADR-212 found exactly this shape (a window ending on the judged day) in a neighbouring
    instrument.
    """
    H, axis, rets, books = loaded
    t = 300
    rules = [("base30", mod.rule_down_days(30)), ("ever_down", mod.rule_ever_down),
             ("sigma_pos", mod.rule_sigma_positive(30))]
    for name, rule in rules:
        before = {b: rule(rets, b, t) for b in books}
        poisoned = {b: list(v) for b, v in rets.items()}
        for b in books:
            poisoned[b][t] = -0.95        # a catastrophe ON the judged day
        after = {b: rule(poisoned, b, t) for b in books}
        assert before == after, f"rule {name} read day {t} — it is not causal"


# ═════════════════ #131 §3: the admission/denominator decomposition ═════════════════
def test_ew_control_is_flat_every_day(mod, loaded):
    """The control must BE a control: equal weight over the admitted set is flat on every day."""
    H, axis, rets, books = loaded
    r = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis), rule=mod.rule_sigma_positive(30),
                           cap=mod.POLICY_CAP, sizer="ew")
    assert r["flat_share"] == 1.0, (
        "the equal-weight control produced a non-flat vector — it is not controlling for the "
        "denominator at all")


def test_inv_sigma_differs_from_ew_only_when_the_set_is_big_enough(mod, loaded):
    """The two sizers must COINCIDE while the ceiling binds everything and diverge after.

    This is #128 p.5 re-derived from the other side: under a narrow admitted set the choice of
    denominator cannot matter, so a measurement claiming it does would be measuring noise.
    """
    H, axis, rets, books = loaded
    narrow = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis),
                                rule=mod.rule_down_days(30), cap=mod.POLICY_CAP)
    wide = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis),
                              rule=mod.rule_sigma_positive(30), cap=mod.POLICY_CAP)
    assert narrow["flat_share"] > wide["flat_share"], (
        "the narrow admitted set must be flat more often than the wide one")
    assert wide["flat_share"] < 1.0, "on the wide set the denominator must be able to speak"


def test_sigma_floor_sweep_is_a_two_way_control(mod, loaded):
    """Inert while <= 1/cap names are admitted, observable once more are. Both directions.

    The narrow side is built from FOUR books on purpose. #128 p.5's inertness is a consequence of
    the ceiling binding every admitted name, i.e. of k <= 1/cap — it is arithmetic, not a habit of
    the real panel. An earlier version of this test asserted inertness over the whole fixture
    universe and went red because that universe admits six names on some days: it was measuring
    the fixture's incidental breadth instead of the claim.
    """
    H, axis, rets, books = loaded
    narrow_universe = ["noisy_a", "noisy_b", "noisy_c", "noisy_d"]
    assert len(narrow_universe) * mod.POLICY_CAP <= 1.0 + 1e-12
    narrow = mod.sigma_floor_sweep(rets, narrow_universe, lo=30, hi=len(axis),
                                   rule=mod.rule_admit_all, cap=mod.POLICY_CAP)
    wide = mod.sigma_floor_sweep(rets, books, lo=30, hi=len(axis),
                                 rule=mod.rule_sigma_positive(30), cap=mod.POLICY_CAP)
    n_narrow = len({(r["apy_net"], r["maxdd"], r["calmar"]) for r in narrow})
    n_wide = len({(r["apy_net"], r["maxdd"], r["calmar"]) for r in wide})
    assert n_narrow == 1, (
        f"{len(narrow_universe)} names under a {mod.POLICY_CAP:.0%} ceiling gave {n_narrow} "
        f"distinct answers across five orders of sigma_floor — the ceiling must bind every name "
        f"there, which is exactly what #128 p.5 measured as bit-identical float64")
    assert n_wide > 1, "the wide set must let sigma_floor move the answer"
    uncapped = mod.sigma_floor_sweep(rets, narrow_universe, lo=30, hi=len(axis),
                                     rule=mod.rule_admit_all, cap=None)
    assert len({(r["apy_net"], r["maxdd"]) for r in uncapped}) > 1, (
        "without the ceiling the SAME narrow set must move — otherwise the inertness above is a "
        "property of the sweep, not of the ceiling")


def test_removing_the_ceiling_breaches_the_policy_cap(mod, loaded):
    """MUTATION control: drop the ceiling and the 20 %/name leak returns, countably.

    #126 measured 86.11 % in one name, #128 measured 82.40 % on 822 days of 822. The counter
    `days_over_policy_cap` is asked of EVERY variant, capped or not, so the leak is a number.
    """
    H, axis, rets, books = loaded
    capped = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis),
                                rule=mod.rule_down_days(30), cap=mod.POLICY_CAP)
    free = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis),
                              rule=mod.rule_down_days(30), cap=None)
    assert capped["days_over_policy_cap"] == 0
    assert free["days_over_policy_cap"] > 0
    assert free["max_name_weight"] > mod.POLICY_CAP
    assert capped["cap_violation_days"] == 0
    assert free["cap_violation_days"] is None, (
        "'no ceiling was applied' and 'the ceiling held' must not both print as 0 (inv. #17)")


def test_mean_weight_sums_to_mean_deployed(mod, loaded):
    """The per-name decomposition the entry publishes has to add up to the deployed capital."""
    H, axis, rets, books = loaded
    r = mod.run_sizer_rule(rets, books, lo=30, hi=len(axis), rule=mod.rule_sigma_positive(30),
                           cap=mod.POLICY_CAP)
    assert math.isclose(sum(r["mean_weight"].values()), r["mean_deployed"], abs_tol=1e-12)


# ═══════════════════ #129's three conditions, each independently ═══════════════════
def test_three_conditions_each_fail_independently(mod):
    """Three mutants, three different failures — otherwise the triple is one condition in a coat."""
    base = {"apy_net": 0.10}
    good = {"maxdd": 0.05, "days_over_policy_cap": 0, "apy_net": 0.20}
    assert mod.three_conditions(good, base)["all_three"] is True

    thin = dict(good, maxdd=0.005)          # below the 96 bp toll
    v = mod.three_conditions(thin, base)
    assert v["denominator_above_toll"] is False and v["all_three"] is False

    breached = dict(good, days_over_policy_cap=1)
    v = mod.three_conditions(breached, base)
    assert v["ceiling_held"] is False and v["all_three"] is False

    poor = dict(good, apy_net=0.05)
    v = mod.three_conditions(poor, base)
    assert v["income_above_base"] is False and v["all_three"] is False


def test_three_conditions_refuse_an_unmeasured_denominator(mod):
    """maxDD = None is not 'small' — it is NOT MEASURED, and it cannot pass condition 1."""
    v = mod.three_conditions({"maxdd": None, "days_over_policy_cap": 0, "apy_net": 1.0},
                             {"apy_net": 0.1})
    assert v["denominator_above_toll"] is False and v["all_three"] is False


def test_toll_threshold_is_the_canonical_roundtrip(mod):
    """The degeneracy threshold is the project's 96 bp toll, not a number chosen to pass."""
    S = mod.sfs_mod()
    v = mod.three_conditions({"maxdd": S.ROUNDTRIP * 1.01, "days_over_policy_cap": 0,
                              "apy_net": 1.0}, {"apy_net": 0.1})
    assert v["denominator_above_toll"] is True
    v = mod.three_conditions({"maxdd": S.ROUNDTRIP * 0.99, "days_over_policy_cap": 0,
                              "apy_net": 1.0}, {"apy_net": 0.1})
    assert v["denominator_above_toll"] is False
    assert v["toll"] == S.ROUNDTRIP


# ═══════════════════════ #132 GZ: the guardian against both zeros ═══════════════════════
def test_delta_calmar_refuses_when_either_side_is_degenerate(mod):
    """#129's exact requirement: a delta over a vanished denominator is REFUSED, never printed.

    'the overlay does not help' and 'the denominator was below the toll' must not be the same cell.
    """
    good = {"calmar": 2.0, "calmar_degenerate": None}
    degen = {"calmar": 400.0, "calmar_degenerate": "maxdd below the round-trip toll"}
    assert mod.delta_calmar(good, good)["status"] == "measured"
    for a, b in ((degen, good), (good, degen), (degen, degen)):
        d = mod.delta_calmar(a, b)
        assert d["status"] == "refused" and d["delta_calmar"] is None
        assert d["reason"], "a refusal without a named cause is just a missing number"
    none_side = {"calmar": None, "calmar_degenerate": None}
    assert mod.delta_calmar(none_side, good)["status"] == "refused"


def test_delta_calmar_sign_is_the_direction_not_the_magnitude(mod):
    worse = {"calmar": 1.0, "calmar_degenerate": None}
    better = {"calmar": 3.0, "calmar_degenerate": None}
    assert mod.delta_calmar(worse, better)["delta_calmar"] < 0
    assert mod.delta_calmar(better, worse)["delta_calmar"] > 0


def test_exposure_switches_counts_the_toll_the_published_table_never_paid(mod):
    """Table #1's overlay charges NO transaction cost; both registry zeros pay 96 bp.

    Comparing them without counting switches hands the overlay a discount nobody granted it, and
    on the real panel that discount is worth 7-10 pp of income.
    """
    eq = mod.equity_of([0.001] * 40 + [-0.05] * 5 + [0.001] * 40)
    raw_sw = mod.exposure_switches(eq, eq)
    assert raw_sw == 0, "an untouched curve cannot have switched exposure"
    GB = mod.guardian_mod()
    guarded = GB.apply_guardian_vol(eq, **mod.IDEA1_VOL)
    assert mod.exposure_switches(eq, guarded) >= 1, (
        "the overlay demonstrably moved exposure on this curve and the counter saw nothing")


def test_exposure_switches_ignores_flat_days(mod):
    """A day with no market move carries no information about exposure and must not be counted."""
    eq = mod.equity_of([0.0] * 50)
    assert mod.exposure_switches(eq, list(eq)) == 0


def test_judge_curve_reports_both_unit_systems_consistently(mod):
    """`_metrics` returns PERCENT, `perf` returns FRACTIONS; mixing them silently is a 100x error."""
    eq = mod.equity_of([0.001 if i % 7 else -0.004 for i in range(400)])
    j = mod.judge_curve(eq)
    # metrics.net_apy_from_equity / max_drawdown_pct round to 4 decimals — that rounding is the
    # only gap permitted here, and it is asserted rather than absorbed into a loose tolerance.
    assert j["idea1_apy_pct"] == pytest.approx(j["apy_frac"] * 100.0, abs=5e-4)
    assert j["idea1_maxdd_pct"] == pytest.approx(j["maxdd_frac"] * 100.0, abs=5e-4)
    assert j["idea1_apy_pct"] == round(j["idea1_apy_pct"], 4), (
        "if #1's instrument stopped rounding, its published cells and these are no longer the "
        "same numbers")


def test_judge_curve_refuses_a_monotone_curve(mod):
    """A curve that never falls has NO drawdown to divide by — the #128 verdict, reused here."""
    j = mod.judge_curve(mod.equity_of([0.0004] * 300))
    assert j["dd_status"] == "unmeasured_monotone"
    assert j["maxdd_frac"] is None and j["calmar"] is None
    assert j["dd_reason"], "the refusal must name its cause"


def test_guardian_settings_are_the_published_ones(mod):
    """Regression lock: the order says 'the same settings that produced table #1' (UPD5, OOS)."""
    assert mod.IDEA1_VOL == {"lookback": 10, "vol_mult": 2.0, "derisk_frac": 0.0,
                             "calm_mult": 1.2}
    assert mod.IDEA1_REACTIVE == {"derisk_dd": 0.04, "derisk_frac": 0.25, "reenter_frac": 0.5}


def test_raw_variant_is_the_untouched_curve(mod, loaded):
    """The base of every delta must be the panel itself, with no overlay and no toll."""
    H, axis, rets, books = loaded
    r = mod.guardian_on(rets["noisy_a"], kind="raw")
    direct = mod.judge_curve(mod.equity_of(rets["noisy_a"]))
    assert r["idea1_apy_pct"] == direct["idea1_apy_pct"]
    assert r["switches"] == 0


def test_guardian_on_rejects_an_unknown_overlay(mod, loaded):
    H, axis, rets, books = loaded
    with pytest.raises(ValueError):
        mod.guardian_on(rets["noisy_a"], kind="hopeful")


def test_run_sizer_rule_rejects_an_unknown_sizer(mod, loaded):
    H, axis, rets, books = loaded
    with pytest.raises(ValueError):
        mod.run_sizer_rule(rets, books, lo=30, hi=100, rule=mod.rule_admit_all, sizer="vibes")


def test_run_sizer_rule_refuses_a_window_that_does_not_exist(mod, loaded):
    """A first weight decided on a window shorter than the lookback is not an estimate."""
    H, axis, rets, books = loaded
    with pytest.raises(ValueError):
        mod.run_sizer_rule(rets, books, lo=5, hi=200, rule=mod.rule_admit_all, lookback=30)
    with pytest.raises(ValueError):
        mod.run_sizer_rule(rets, books, lo=30, hi=30, rule=mod.rule_admit_all, lookback=30)


# ═══════════════════════════ the reports themselves ═══════════════════════════
def test_ase_report_answers_the_order_or_refuses_with_a_cause(mod, panel):
    """The order's acceptance: print k*, and either the set exists or say WHY it cannot."""
    rep = mod.ase_report(panel)
    assert rep["k_star"] == 6
    assert isinstance(rep["admitted_set_exists"], bool)
    if rep["admitted_set_exists"]:
        assert rep["refusal"] is None
    else:
        assert rep["refusal"] and "does NOT exist" in rep["refusal"]
        assert rep["falling_census_live"]["never_falling"], (
            "a refusal has to name which book is unreachable")
    for name, _rule, _why in mod.ADMISSION_LADDER:
        row = rep["rungs"][name]
        assert set(row) >= {"inv_sigma", "ew", "denominator_gap"}
        for sizer in ("inv_sigma", "ew"):
            assert "series" not in row[sizer], "the report must not carry raw series"
            assert row[sizer]["three_vs_ew_live"]["toll"] == mod.sfs_mod().ROUNDTRIP


def test_ase_report_judges_out_of_sample_on_the_harness_seam(mod, panel):
    """The train/test seam is the harness's own TRAIN_END, not a number chosen in this file."""
    rep = mod.ase_report(panel)
    H = mod.panel_mod()
    assert rep["train_end"] == H.TRAIN_END
    assert rep["train_days"] > 0 and rep["test_days"] > 0
    for name, _rule, _why in mod.ADMISSION_LADDER:
        for sizer in ("inv_sigma", "ew"):
            d = rep["oos"][name][sizer]
            assert set(d) == {"train", "test"}
            assert d["train"]["n_days"] + d["test"]["n_days"] == rep["judged_days"]


def test_ase_report_refuses_a_panel_without_a_seam(mod, tmp_path_factory):
    """A panel whose axis ends before TRAIN_END cannot support an out-of-sample claim at all."""
    root = tmp_path_factory.mktemp("short_panel")
    n = 240
    for name in ("a", "b", "c"):
        _write_book(root / name, [0.001 if i % 3 else -0.002 for i in range(n)])
    with pytest.raises(RuntimeError, match="seam"):
        mod.ase_report(root)


def test_gz_report_prints_deltas_against_both_zeros(mod, panel):
    """#129 order 2's literal acceptance: BOTH zeros, each delta carrying its verdict."""
    rep = mod.guardian_zero_report(panel)
    assert set(rep["zeros"]) == {"ew10", "ew_live"}
    for z in rep["zeros"].values():
        for key in ("delta_vol", "delta_reactive"):
            d = z[key]
            assert d["status"] in ("measured", "refused")
            if d["status"] == "refused":
                assert d["reason"]
            else:
                assert d["delta_calmar"] is not None
        assert z["raw"]["switches"] == 0
    assert rep["books_total"] == len(rep["books"])
    assert 0 <= rep["books_with_measurable_delta"] <= rep["books_total"]


def test_gz_live_arm_excludes_the_dead_book(mod, panel):
    """Both zeros must be the registry's own two universes, measured from the census."""
    rep = mod.guardian_zero_report(panel)
    assert "frozen" in rep["frozen"], "the killed book must be censused as frozen"
    assert "frozen" not in rep["live_arm"]
    assert rep["last_kill"], "a panel with a kill must report its date, not None"


def test_reports_print_without_raising(mod, panel, capsys):
    """A report nobody can print is a report nobody reads."""
    mod.print_ase(mod.ase_report(panel))
    mod.print_gz(mod.guardian_zero_report(panel))
    out = capsys.readouterr().out
    assert "#131 ASE" in out and "#132 GZ" in out
    assert "НЕ ИЗМЕРЕН" in out or "ОТКАЗАН" in out, (
        "a report with no refusal column cannot express a third outcome")


def test_cli_runs_both_sections(mod, panel):
    assert mod.main(["--panel", str(panel), "--section", "both", "--json"]) == 0


# ═══════════════════════════ invariants of the domain ═══════════════════════════
def test_module_is_advisory_and_outside_riskpolicy(mod):
    assert mod.IS_ADVISORY is True
    assert mod.OUTSIDE_RISKPOLICY is True


def test_the_live_track_is_never_opened(mod):
    """Checked by AST over the whole import closure, not by eye and not by grep on one file."""
    forbidden = ("equity_curve_daily", "golive_status", "paper_state")
    for path in (SCRIPT, SFS_SCRIPT, PANEL_SCRIPT):
        tree = ast.parse(path.read_text())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                for bad in forbidden:
                    assert bad not in node.value, f"{path.name} opens {bad!r}"
        # control on the exclusion: a path whose docstring names the track must still be caught
        # if the name appears in EXECUTABLE code, so the skip cannot hide a real access.
        assert docstrings, f"{path.name} has no docstring — the exclusion above is then untested"


def test_nothing_is_written_to_disk_by_the_measured_path(mod):
    """A read-only measurement must contain no writer at all — AST, not a promise in the docstring."""
    tree = ast.parse(SCRIPT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", "the report opens a file for writing somewhere"
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("write_text", "write_bytes", "atomic_save", "mkdir"), (
                f"a writer ({node.attr}) appeared in a read-only measurement")


def test_no_wall_clock_door_in_the_measured_path(mod):
    """Proves the FROZEN-DATE-OK claim at the top of this file instead of asserting it in prose."""
    doors = ("now", "utcnow", "today", "time")
    for path in (SCRIPT, SFS_SCRIPT, PANEL_SCRIPT, GUARDIAN_SCRIPT):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in doors:
                    owner = getattr(node.func.value, "id", None)
                    assert owner not in ("datetime", "date", "time"), (
                        f"{path.name} reads the wall clock via {owner}.{node.func.attr}() — the "
                        f"FROZEN-DATE-OK claim of this file is then false")


def test_the_policy_cap_is_not_redefined_here(mod):
    """The 20 %/name ceiling is a RiskPolicy v1.0 number; this file must agree with the harness."""
    S = mod.sfs_mod()
    H = mod.panel_mod()
    assert mod.POLICY_CAP == S.POLICY_CAP == H.POLICY_CAP == 0.20
    assert mod.ROUNDTRIP == S.ROUNDTRIP == 0.0096


def test_cap_counterfactual_is_a_measurement_not_a_change(mod, loaded):
    """Sweeping the ceiling must not leave the module's own constant moved."""
    H, axis, rets, books = loaded
    before = mod.POLICY_CAP
    mod.cap_counterfactual(rets, books, lo=30, hi=200, rule=mod.rule_ever_down,
                           caps=(0.20, 0.40))
    assert mod.POLICY_CAP == before == 0.20
