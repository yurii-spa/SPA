"""Controls for scripts/edge_static_guardian_perimeter.py — registry #136 (SGP).

Every test is a POSITIVE CONTROL for a defect that was actually produced, here or earlier in
this series, not a restatement of what the code does:

  * the acceptance adapter was WRONG WHEN FIRST RUN: #129's `three_conditions` reads `maxdd`,
    the portfolio row carried only `maxdd_frac`, and so every denominator verdict printed False
    over a denominator six times the toll — a measurement that looked like a refusal.
    `test_three_conditions_sees_the_measured_denominator` goes red if that mapping is dropped.
  * #124 and #129 both found a choice that does not transfer. A choice that can SEE the test
    half does not transfer either — it cheats. `test_perimeter_choice_cannot_see_the_test_half`
    mutates the TEST returns and demands the chosen perimeter not move.
  * #132's local overlay copies charge NO transaction cost while both registry zeros pay 96 bp.
    `test_toll_is_charged_and_scales_with_weight` keeps the toll countable and weight-scaled.
  * inv. #17: a book that never fell must be refused BY NAME, never admitted on a zero.
    `test_a_book_that_never_fell_is_refused_with_its_own_cause`.
  * #129 made it mandatory that "the rule is worse" and "the denominator vanished" stay apart.
    `test_delta_is_refused_not_zeroed_when_degenerate`.
  * the verdict rule must be able to say BOTH words. `test_verdict_*` drive it in both
    directions, one check at a time, so a rule that always says `negative` goes red.
  * the overlay must keep its warm-up across the seam — restarting it at the seam would hand
    the test half an exposure no operator had. `test_guarded_slice_keeps_its_warm_up`.
  * the whole entry's comparability rests on ONE instrument set: the overlay, the toll, the
    drawdown verdict and the three conditions are IMPORTED from #131/#132's file.
    `test_no_second_copy_of_the_instrument` fails if this script grows its own.

The panel is BUILT HERE, in tmp, and never read from data/: data/aggressive_lab is runtime-only
(gitignored), so a test that reached for it would be green on this Mac and "NOT MEASURED" in CI —
the exact substitution the rules forbid.
"""
# FROZEN-DATE-OK: panel-axis-geometry — the literal dates here ARE the subject, for the same
# measured reason as in test_edge_ase_guardian_zero.py: the harness refuses an axis shorter than
# 200 common days and the train/test seam is the harness's own TRAIN_END literal (2025-06-30), so
# a synthetic panel that wants a seam strictly inside its judged slice has to start before that
# date and run past it. Relative stamps (preference #2) cannot express a fixed seam, and
# injecting a clock (preference #1) would inject something no reader of this code consults —
# `test_no_wall_clock_door_in_the_measured_path` ASSERTS that the whole measured path contains no
# wall-clock door at all, so this claim is measured rather than noted. Preference #3 of
# .claude/rules/deployment.md: the date is the subject.
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_static_guardian_perimeter.py"
GZ_SCRIPT = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"
SFS_SCRIPT = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"
PANEL_SCRIPT = ROOT / "scripts" / "edge_real_panel_ensemble.py"
GUARDIAN_SCRIPT = ROOT / "scripts" / "guardian_backtest.py"

N_DAYS = 700
START = "2024-03-06"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("edge_static_guardian_perimeter", SCRIPT)
    assert spec and spec.loader, f"cannot import {SCRIPT}"
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
    """A panel carrying the three shapes the perimeter has to tell apart.

    quiet    — monotone up, not one day below zero: the `points_farm` shape, the book a downside
               perimeter can never admit and must refuse BY NAME.
    deep     — a book with a genuinely deep drawdown, admitted at every K on the grid.
    shallow  — two-sided but small: measured, and below the threshold at the larger K values.
    noisy_a..c — ordinary two-sided books, so the universe is wide enough for an equal weight
               under the 20 %/name ceiling.
    """
    root = tmp_path_factory.mktemp("panel_sgp")
    n = N_DAYS - 1
    _write_book(root / "quiet", [0.0003 + 0.0002 * ((i % 7) / 7.0) for i in range(n)])
    _write_book(root / "deep", [(-0.03 if 100 <= i < 130 else 0.004) for i in range(n)])
    _write_book(root / "shallow", [(0.002 if i % 3 else -0.0016) for i in range(n)])
    for j, name in enumerate(("noisy_a", "noisy_b", "noisy_c")):
        amp = 0.002 * (j + 1)
        _write_book(root / name, [(amp if i % (j + 2) else -amp * 0.8) for i in range(n)])
    return root


@pytest.fixture(scope="module")
def loaded(mod, panel):
    H = mod.panel_mod()
    axis, rets, books = H.plb_load(panel)
    guarded = mod.guarded_book_returns(rets, books)
    seam = mod.gz_mod().split_index(axis, H.TRAIN_END)
    return H, axis, rets, books, guarded, seam


# ═══════════ the defect this file actually produced on its first run ═══════════
def test_three_conditions_sees_the_measured_denominator(mod, loaded):
    """#129's acceptance must read a MEASURED drawdown as measured.

    First run of this script printed `denominator_above_toll = False` on every arm while the
    drawdown was six times the toll, because the row carried `maxdd_frac` and the acceptance
    function reads `maxdd`. A verdict that refuses a measurement it holds in its own hand is the
    quietest way for an entry to be wrong: it looks like honesty.
    """
    H, axis, rets, books, guarded, seam = loaded
    row = mod.perimeter_portfolio(rets, guarded, books, set(books), lo=30, hi=len(axis))
    assert row["maxdd"] == row["maxdd_frac"], "the acceptance adapter lost the denominator"
    assert row["maxdd"] is not None and row["maxdd"] > mod.sfs_mod().ROUNDTRIP
    three = mod.gz_mod().three_conditions(row, row)
    assert three["denominator_above_toll"] is True, (
        "a drawdown above the toll was reported as below it — the key mapping is broken again")


def test_three_conditions_still_refuses_a_real_degenerate_denominator(mod, loaded):
    """Control on the control: the fix must not make the acceptance unable to say no."""
    H, axis, rets, books, guarded, seam = loaded
    row = mod.perimeter_portfolio(rets, guarded, ["quiet"], set(), lo=30, hi=len(axis))
    three = mod.gz_mod().three_conditions(row, row)
    assert three["denominator_above_toll"] is False, (
        "a monotone book's absent drawdown was accepted as a denominator")


# ═════════════════════ the geometry: what each arm actually is ═════════════════════
def test_full_perimeter_is_bitwise_equal_weight_of_guarded_books(mod, loaded):
    """The `all` arm must BE equal weight over guarded books, not something near it."""
    H, axis, rets, books, guarded, seam = loaded
    lo, hi = 30, len(axis)
    row = mod.perimeter_portfolio(rets, guarded, books, set(books), lo=lo, hi=hi)
    want = [sum(guarded[b][i] for b in books) / len(books) for i in range(lo, hi)]
    got = mod.gz_mod().returns_of(mod.gz_mod().equity_of(want))
    direct = mod.gz_mod().judge_curve(mod.gz_mod().equity_of(want))
    assert row["apy_frac"] == direct["apy_frac"]
    assert row["maxdd_frac"] == direct["maxdd_frac"]
    assert len(got) == hi - lo


def test_empty_perimeter_is_bitwise_the_raw_zero(mod, loaded):
    """And the base arm must BE raw equal weight — the zero every delta is taken against."""
    H, axis, rets, books, guarded, seam = loaded
    lo, hi = 30, len(axis)
    row = mod.perimeter_portfolio(rets, guarded, books, set(), lo=lo, hi=hi)
    want = [sum(rets[b][i] for b in books) / len(books) for i in range(lo, hi)]
    direct = mod.gz_mod().judge_curve(mod.gz_mod().equity_of(want))
    assert row["apy_frac"] == direct["apy_frac"]
    assert row["maxdd_frac"] == direct["maxdd_frac"]
    assert row["switches_raw_count"] == 0, "a raw arm cannot switch exposure"


def test_k_zero_is_not_the_full_perimeter(mod, loaded):
    """K = 0 drops the THRESHOLD, not the MEASURABILITY requirement — and that is #95's survivor.

    Mistaking one for the other would silently re-admit the books that never fell, i.e. undo the
    only thing the perimeter does.
    """
    H, axis, rets, books, guarded, seam = loaded
    per = mod.train_perimeter(rets, books, lo=30, seam=seam, k=0.0,
                              price_of_round=2 * mod.sfs_mod().ROUNDTRIP)
    assert "quiet" not in per["admitted"], "a book with no down day was admitted at K = 0"
    assert set(per["admitted"]) < set(books), "K = 0 admitted the whole universe"


def test_a_book_that_never_fell_is_refused_with_its_own_cause(mod, loaded):
    """inv. #17: three outcomes stay apart — `no down day` is not `below threshold`."""
    H, axis, rets, books, guarded, seam = loaded
    per = mod.train_perimeter(rets, books, lo=30, seam=seam, k=1.0,
                              price_of_round=2 * mod.sfs_mod().ROUNDTRIP)
    quiet = per["detail"]["quiet"]
    assert quiet["maxdd"] is None and quiet["admitted"] is False
    assert quiet["refused_because"] == "unmeasured_monotone", (
        f"refusal cause collapsed to {quiet['refused_because']!r} — a book that never fell is "
        f"now indistinguishable from one that fell a little")
    deep = per["detail"]["deep"]
    assert deep["maxdd"] is not None and deep["admitted"] is True


# ═════════════════════ causality: the choice cannot see the test half ═════════════════════
def test_perimeter_choice_cannot_see_the_test_half(mod, loaded):
    """Mutate every TEST return; the TRAIN-chosen perimeter must not move by one name.

    #124 and #129 each found a choice that failed to transfer. A choice that can see the test
    half would not fail to transfer — it would cheat, and the entry would be worthless in the
    other direction.
    """
    H, axis, rets, books, guarded, seam = loaded
    price = 2 * mod.sfs_mod().ROUNDTRIP
    before = mod.train_perimeter(rets, books, lo=30, seam=seam, k=1.0, price_of_round=price)
    poisoned = {b: list(v) for b, v in rets.items()}
    for b in poisoned:
        for i in range(seam, len(poisoned[b])):
            poisoned[b][i] = -0.5          # a catastrophe that happens only AFTER the seam
    after = mod.train_perimeter(poisoned, books, lo=30, seam=seam, k=1.0, price_of_round=price)
    assert before["admitted"] == after["admitted"], (
        f"the perimeter moved {before['admitted']} -> {after['admitted']} when only the TEST "
        f"half changed: the choice is looking forward")


def test_the_poison_control_is_not_vacuous(mod, loaded):
    """Control on the control: the same poison MUST move a choice made on the test half."""
    H, axis, rets, books, guarded, seam = loaded
    price = 2 * mod.sfs_mod().ROUNDTRIP
    before = mod.train_perimeter(rets, books, lo=seam, seam=len(axis), k=1.0,
                                 price_of_round=price)
    poisoned = {b: list(v) for b, v in rets.items()}
    for b in poisoned:
        for i in range(seam, len(poisoned[b])):
            poisoned[b][i] = -0.5
    after = mod.train_perimeter(poisoned, books, lo=seam, seam=len(axis), k=1.0,
                                price_of_round=price)
    assert before["admitted"] != after["admitted"], (
        "poisoning every return of a window did not change a perimeter chosen ON that window — "
        "the forward-looking test above would pass for a rule that ignores its data")


def test_guarded_slice_keeps_its_warm_up(mod, loaded):
    """The overlay runs on the FULL axis; slicing it is not the same as restarting it at the seam.

    Restarting would give the test half a flat-exposure warm-up nobody had, which is a small,
    invisible gift to the hypothesis.
    """
    H, axis, rets, books, guarded, seam = loaded
    GZ = mod.gz_mod()
    GB = GZ.guardian_mod()
    restarted = GZ.returns_of(GB.apply_guardian_vol(
        GZ.equity_of(list(rets["deep"])[seam:]), **GZ.IDEA1_VOL))
    sliced = list(guarded["deep"])[seam:]
    assert len(restarted) == len(sliced)
    assert restarted != sliced, (
        "slicing the full-axis overlay equals restarting it at the seam — the warm-up claim in "
        "the docstring is then false, or the overlay has no memory at all")


# ═════════════════════════ the toll, countable and weighted ═════════════════════════
def test_toll_is_charged_and_scales_with_weight(mod, loaded):
    """A switching arm must pay, and a switch inside 1/n of the capital must cost 1/n of a round trip."""
    H, axis, rets, books, guarded, seam = loaded
    lo, hi = 30, len(axis)
    row = mod.perimeter_portfolio(rets, guarded, books, {"deep"}, lo=lo, hi=hi)
    assert row["switches_raw_count"] > 0, "the fixture's deep book never switches — no toll to test"
    assert row["apy_frac_after_switch_toll"] < row["apy_frac"], "switches were free"
    assert row["weighted_switches"] == pytest.approx(
        row["switches_raw_count"] / len(books)), "the toll ignores position size"


def test_untolled_column_survives(mod, loaded):
    """Both columns stay: table #1 charges nothing, and dropping its column would end comparison."""
    H, axis, rets, books, guarded, seam = loaded
    row = mod.perimeter_portfolio(rets, guarded, books, {"deep"}, lo=30, hi=len(axis))
    assert row["apy_frac"] is not None and row["apy_frac_after_switch_toll"] is not None
    assert row["apy_frac"] != row["apy_frac_after_switch_toll"]


# ═════════════════════════ refusals stay refusals ═════════════════════════
def test_delta_is_refused_not_zeroed_when_degenerate(mod, loaded):
    """#129: "the rule is worse" and "the denominator vanished" must never be the same cell."""
    H, axis, rets, books, guarded, seam = loaded
    base = mod.arm_row(rets, guarded, ["quiet"], set(), lo=30, hi=len(axis), base=None,
                       label="raw")
    arm = mod.arm_row(rets, guarded, ["quiet"], {"quiet"}, lo=30, hi=len(axis), base=base,
                      label="all")
    assert arm["delta"]["status"] == "refused"
    assert arm["delta"]["delta_calmar"] is None, "a refused delta was printed as a number"


def test_pick_k_refuses_when_every_cell_is_degenerate(mod, loaded):
    """No choosable K is an OUTCOME with a cause, not a quiet fallback to the first row."""
    rows = [{"k": k, "calmar": None, "calmar_degenerate": "below toll"} for k in (0.0, 1.0)]
    out = mod.pick_k(rows)
    assert out["k"] is None and out["status"] == "refused" and out["reason"]


def test_pick_k_refuses_a_degenerate_cell_that_carries_a_HUGE_calmar(mod):
    """The #129 defect in its own shape: the winner is degenerate AND has the largest Calmar.

    This is the cell that actually occurs — a portfolio whose drawdown is below the toll divides
    a real numerator by an artefact and tops the table with 500. A test whose degenerate row also
    carries `calmar = None` cannot see a filter that drops the degeneracy check, and the first
    version of this file had exactly that hole: the mutation "pick_k ranks degenerate cells too"
    SURVIVED the delta mutation run until this case was added.
    """
    rows = [{"k": 0.0, "calmar": 2.0, "calmar_degenerate": None, "apy_frac": 0.2,
             "maxdd_frac": 0.1, "perimeter": ["a"]},
            {"k": 5.0, "calmar": 500.0, "calmar_degenerate": "maxDD below the round-trip toll",
             "apy_frac": 0.05, "maxdd_frac": 0.0001, "perimeter": ["b"]}]
    out = mod.pick_k(rows)
    assert out["k"] == 0.0, (
        f"K* = {out['k']} — the choice ranked a denominator smaller than its own toll above a "
        f"measured one, which is the error #129 made mandatory to refuse")
    assert out["candidates"] == 1


def test_pick_k_chooses_the_best_measured_cell(mod):
    """Control on the control: with measurable cells it must pick, and pick the maximum."""
    rows = [{"k": 0.0, "calmar": 1.0, "calmar_degenerate": None, "apy_frac": 0.1,
             "maxdd_frac": 0.1, "perimeter": ["a"]},
            {"k": 5.0, "calmar": 2.0, "calmar_degenerate": None, "apy_frac": 0.2,
             "maxdd_frac": 0.1, "perimeter": ["b"]},
            {"k": 9.0, "calmar": None, "calmar_degenerate": "below toll"}]
    out = mod.pick_k(rows)
    assert out["k"] == 5.0 and out["status"] == "chosen" and out["candidates"] == 2


# ═════════════════════════ the premise, and the verdict rule ═════════════════════════
def test_benefit_persistence_counts_one_sided_books_in_neither_column(mod, loaded):
    """A book measurable in only one half is the THIRD outcome, never an agreement or a clash."""
    H, axis, rets, books, guarded, seam = loaded
    bp = mod.benefit_persistence(rets, guarded, books, lo=30, seam=seam, hi=len(axis))
    for b, row in bp["per_book"].items():
        if not row["measurable_in_both"]:
            assert row["sign_agrees"] is None, f"{b} voted on persistence without two measurements"
    assert bp["measurable_in_both"] == sum(
        1 for r in bp["per_book"].values() if r["measurable_in_both"])
    assert bp["sign_agreements"] <= bp["measurable_in_both"]


def _arms(delta, inverse_delta, oracle_delta, three_ok):
    def row(d):
        return {"delta": {"status": "measured", "delta_calmar": d},
                "three": {"all_three": three_ok}}
    return {"train": row(delta), "inverse": row(inverse_delta), "oracle": row(oracle_delta)}


def test_verdict_is_positive_only_when_all_four_checks_hold(mod):
    v = mod.sgp_verdict(_arms(0.5, -0.2, 0.3, True))
    assert v["verdict"] == "positive", v


@pytest.mark.parametrize("delta,inv,orc,three,failing", [
    (-0.5, -0.9, 0.3, True, "delta_positive"),
    (0.5, 0.9, 0.3, True, "inverse_worse"),
    (0.5, -0.2, -0.3, True, "oracle_above_base"),
    (0.5, -0.2, 0.3, False, "three_conditions"),
])
def test_verdict_turns_negative_on_each_check_alone(mod, delta, inv, orc, three, failing):
    """One check at a time: a verdict that cannot be flipped by a single check is not a rule."""
    v = mod.sgp_verdict(_arms(delta, inv, orc, three))
    assert v["verdict"] == "negative"
    assert v["checks"][failing] is False
    assert failing in v["reason"]


def test_verdict_refuses_when_no_k_was_choosable(mod):
    v = mod.sgp_verdict({"none": {}})
    assert v["verdict"] == "refused" and v["reason"]


# ═════════════════════════ one instrument set, no wall clock ═════════════════════════
def test_no_second_copy_of_the_instrument(mod):
    """The overlay, the toll and the verdicts must be IMPORTED, never redefined here.

    A second copy would make every number of #136 incomparable with #132 BY CONSTRUCTION — the
    one way this entry could be green and meaningless at the same time.
    """
    tree = ast.parse(SCRIPT.read_text())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    forbidden = {"apply_guardian_vol", "apply_guardian", "_metrics", "equity_of", "returns_of",
                 "exposure_switches", "judge_curve", "delta_calmar", "three_conditions",
                 "drawdown_verdict", "calmar_degenerate", "perf"}
    clash = defined & forbidden
    assert not clash, f"{SCRIPT.name} redefines imported instruments: {sorted(clash)}"


def test_no_wall_clock_door_in_the_measured_path():
    """No datetime.now / utcnow / time.time / date.today anywhere the numbers come from.

    This is what makes the FROZEN-DATE-OK claim at the top of this file a measurement instead of
    a note: nothing in the measured path is judged against the calendar, so nothing here can rot
    as the calendar moves.
    """
    doors = ("datetime.now", "datetime.utcnow", "time.time", "date.today", "utcnow()")
    for path in (SCRIPT, GZ_SCRIPT, SFS_SCRIPT, PANEL_SCRIPT, GUARDIAN_SCRIPT):
        src = path.read_text()
        body = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
        for d in doors:
            assert d not in body, f"{path.name} reads a wall clock ({d})"


def test_the_script_is_advisory_and_never_imports_execution():
    src = SCRIPT.read_text()
    assert "IS_ADVISORY = True" in src and "OUTSIDE_RISKPOLICY = True" in src
    assert "spa_core.execution" not in src
    assert "equity_curve_daily" not in src, "the go-live track must never be opened here"


def test_report_writes_nothing_to_disk(mod, panel, tmp_path):
    """Advisory means advisory: the report prints, and leaves no artefact behind."""
    before = sorted(p.name for p in panel.iterdir())
    rep = mod.sgp_report(panel)
    after = sorted(p.name for p in panel.iterdir())
    assert before == after, "the report wrote into the panel directory"
    assert rep["universes"], "the report produced no universe at all"


def test_report_refuses_a_panel_without_a_seam(mod, tmp_path_factory):
    """No train/test seam inside the judged slice ⇒ a loud refusal, never a silent in-sample claim."""
    root = tmp_path_factory.mktemp("short_panel_sgp")
    n = 250
    for name in ("a", "b", "c"):
        _write_book(root / name, [(0.001 if i % 2 else -0.0008) for i in range(n)],
                    killed_on=None)
    with pytest.raises(RuntimeError, match="out-of-sample"):
        mod.sgp_report(root)
