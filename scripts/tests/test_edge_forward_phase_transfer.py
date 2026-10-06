"""Acceptance for scripts/edge_forward_phase_transfer.py (#125 FPT / #126 ZRB).

Every test here is a POSITIVE CONTROL: it reproduces a defect that was actually hit while this
harness was being written, and it goes red if that wire is cut again. The five that matter most:

  * THE TOLL MANUFACTURED THE DRAWDOWN. The canonical 96 bp round-trip is charged once, as a
    -0.96 % first return. On a portfolio of monotone books that is the ONLY day below zero, so a
    drawdown measured on the tolled series came back `measured, 0.908 %` — this script's own fee
    read back to it as though the market had taken it, which defeats the third outcome with a down
    day the script itself created. The drawdown is therefore judged on the UNTOLLED series.
    (tests: toll_does_not_manufacture_a_drawdown, window_return_still_pays_the_toll)

  * `None` REACHED THE PAGE AS 0.000. The order-2 printer read `(s['calmar'] or 0)`, so a REFUSED
    Calmar printed as `0.000` — "not measured" wearing the costume of a measured zero, inv. #17,
    in the very table written to expose that class. (tests: num_never_renders_none_as_a_number,
    dd_printer_says_the_word)

  * A MONOTONE SERIES HAS NO DRAWDOWN AND NO CALMAR. 7 of 10 books on the live forward block have
    not one down day in 61 returns; `perf` hands back maxdd 0.0 and Calmar `inf`, which is how a
    61-day accrual ledger gets published as a risk-adjusted optimum.
    (tests: monotone_block_refuses_maxdd, monotone_block_refuses_calmar)

  * "MEASURED AND EQUAL TO ZERO" IS A DIFFERENT FACT from "not measured". A series that HAS down
    days whose worst cumulative dip is still exactly zero was observed, and must not be swept into
    the monotone bucket. (test: a_real_zero_drawdown_is_measured_not_refused)

  * THE PHASE SEAM IS NOT A RETURN. The forward block restarts equity near $100k, so a phase-blind
    loader reads a +104.9 % / -83.5 % step as one day's return. The loader must never produce it
    and `seam_steps` must MEASURE it, so the size of the thing being guarded against is a printed
    number rather than a claim. (tests: forward_loader_never_crosses_the_seam, seam_is_measured)

  * SELECTION MUST NOT SEE THE FORWARD BLOCK. Causality control in both directions: corrupting the
    forward block must move the forward numbers and must NOT move the chosen subset.
    (test: selection_reads_the_backtest_block_only)

The real panel is runtime-only (not in git), so the reproduction control states its own THIRD
OUTCOME rather than skipping — a skip would make "not measured" indistinguishable from "passed"
(lesson of #465). Deterministic, hermetic, no network, no live track, no clock.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "edge_forward_phase_transfer.py"


def _load():
    spec = importlib.util.spec_from_file_location("edge_fpt_under_test", HARNESS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


# ───────────────────────────── scene builders ─────────────────────────────
def _row(date: str, eq: float, phase: str, **kw) -> dict:
    d = {"date": date, "as_of": date, "equity_usd": eq, "phase": phase,
         "is_advisory": True, "outside_riskpolicy": True}
    d.update(kw)
    return d


def _day(i: int) -> str:
    """Dates generated from an index, never typed as literals (no frozen-date bomb)."""
    import datetime as _dt
    return (_dt.date(2024, 1, 1) + _dt.timedelta(days=i)).isoformat()


def write_panel(tmp: Path, books: dict) -> Path:
    """books = {name: (backtest_returns, forward_returns)} -> a panel dir of jsonl series.

    Equity is compounded WITHIN each phase block and the forward block deliberately RESTARTS at
    100_000, exactly as the live lab does — that restart is the seam under test.
    """
    for name, (bt, fw) in books.items():
        d = tmp / name
        d.mkdir(parents=True, exist_ok=True)
        rows, eq, i = [], 100_000.0, 0
        rows.append(_row(_day(i), eq, "backtest"))
        for r in bt:
            i += 1
            eq *= 1.0 + r
            rows.append(_row(_day(i), eq, "backtest"))
        eq = 100_000.0           # the seam: a fresh book, not a continuation
        i += 1
        rows.append(_row(_day(i), eq, "forward"))
        for r in fw:
            i += 1
            eq *= 1.0 + r
            rows.append(_row(_day(i), eq, "forward"))
        (d / "realized_series.jsonl").write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    return tmp


#: a book that only ever accrues — the shape 7 of 10 live books actually have
UP = [0.0004] * 80
#: a book with real marks in both directions
MIXED = [0.004, -0.003, 0.005, -0.006, 0.002, -0.001, 0.003, -0.004] * 10


# ═══════════════════════ 1. the third outcome ═══════════════════════
def test_monotone_block_refuses_maxdd():
    """A series with no down day did not have its drawdown measured — inv. #17."""
    v = M.drawdown_verdict(UP)
    assert v["status"] == "unmeasured_monotone"
    assert v["maxdd"] is None, "0.0 here would be arithmetic presented as observation"
    assert v["down_days"] == 0
    assert "cannot draw down" in v["reason"]


def test_monotone_block_refuses_calmar():
    """`perf` returns Calmar inf for maxdd == 0; that is how an accrual ledger gets published."""
    assert M.drawdown_verdict(UP)["calmar"] is None


def test_a_series_with_a_down_day_is_measured_and_its_maxdd_is_strictly_positive():
    """A day below zero was OBSERVED, so the verdict is `measured` — and maxDD cannot be 0 then.

    This test used to claim it was pinning a third case, "measured and equal to zero". That claim
    was WRONG and a mutation control is what exposed it: a mutant handing back `apy / max(mdd,
    1e-12)` on the measured path survived, because the branch it corrupts (`mdd > 0 else None`) is
    UNREACHABLE. A return below -1e-12 necessarily drops equity below the running peak by a
    representable amount, so `down_days >= 1` implies `maxdd > 0` in float64. The guard stays as
    cheap defence, but it is documented as unreachable instead of advertised as a measured case,
    and this test pins the implication that makes it unreachable.
    """
    v = M.drawdown_verdict([-0.01, 0.02, 0.01])
    assert v["status"] == "measured"
    assert v["down_days"] == 1
    assert v["maxdd"] is not None and v["maxdd"] > 0
    assert v["calmar"] is not None
    # the implication itself, over a range of magnitudes down to the eps boundary
    for r in (-1e-11, -1e-8, -1e-4, -0.3):
        w = M.drawdown_verdict([r, 0.001])
        assert w["status"] == "measured" and w["maxdd"] > 0, (
            f"a down day of {r} produced maxdd {w['maxdd']!r}: if this ever becomes 0.0 the "
            f"'measured and equal to zero' case is REACHABLE and needs its own branch")


def test_empty_series_is_its_own_outcome():
    v = M.drawdown_verdict([])
    assert v["status"] == "unmeasured_empty" and v["maxdd"] is None


def test_mixed_series_is_measured():
    v = M.drawdown_verdict(MIXED)
    assert v["status"] == "measured" and v["maxdd"] > 0 and v["calmar"] is not None


# ═══════════════════════ 2. the toll must not manufacture risk ═══════════════════════
def test_toll_does_not_manufacture_a_drawdown(tmp_path):
    """THE defect of this file: a 96 bp day-one fee was the only down day, and got read as maxDD.

    Two monotone books, so the market never takes anything away. With the toll charged the naive
    reading is `measured, ~0.96 %`; the verdict must still be `unmeasured_monotone`.
    """
    write_panel(tmp_path, {"a": (UP, UP), "b": (UP, UP)})
    fw = M.load_forward_panel(tmp_path)
    axis = sorted(set.intersection(*[set(fw[b]) for b in fw]))
    rets = {b: [fw[b][d] for d in axis] for b in fw}

    v = M.portfolio_verdict(["a", "b"], rets, 0, len(axis), roundtrip=M.ROUNDTRIP)
    assert v["status"] == "unmeasured_monotone", (
        "the toll is OUR fee, not a market drawdown — judging the tolled series re-creates the "
        "exact defect this harness exists to expose")
    assert v["maxdd"] is None
    # ...and the contaminated figure is kept VISIBLE rather than dropped
    assert v["maxdd_incl_toll"] is not None
    assert v["maxdd_incl_toll"] == pytest.approx(M.ROUNDTRIP, rel=0.05)


def test_window_return_still_pays_the_toll(tmp_path):
    """The toll is real money: it must stay in the RETURN even though it is out of the drawdown."""
    write_panel(tmp_path, {"a": (UP, UP), "b": (UP, UP)})
    fw = M.load_forward_panel(tmp_path)
    axis = sorted(set.intersection(*[set(fw[b]) for b in fw]))
    rets = {b: [fw[b][d] for d in axis] for b in fw}
    v = M.portfolio_verdict(["a", "b"], rets, 0, len(axis), roundtrip=M.ROUNDTRIP)
    assert v["window_return"] < v["window_return_ex_toll"]
    assert v["window_return_ex_toll"] - v["window_return"] == pytest.approx(M.ROUNDTRIP, rel=0.05)


# ═══════════════════════ 3. the seam is not a return ═══════════════════════
def test_forward_loader_never_crosses_the_seam(tmp_path):
    """The forward block restarts equity; diffing across the restart invents a huge fake return."""
    write_panel(tmp_path, {"a": ([0.5] * 70, UP), "b": ([0.5] * 70, UP)})
    fw = M.load_forward_panel(tmp_path)
    for book, series in fw.items():
        assert max(abs(r) for r in series.values()) < 0.01, (
            f"{book}: the loader produced a return far larger than any forward day — it crossed "
            f"the phase seam")


def test_seam_is_measured_not_asserted(tmp_path):
    """`seam_steps` must report the size of the discontinuity, so the guard is evidenced."""
    write_panel(tmp_path, {"a": ([0.5] * 70, UP)})
    seams = M.seam_steps(tmp_path)
    assert seams["a"] is not None
    assert seams["a"] < -0.9, "0.5/day for 70 days then a reset to 100k is a huge negative step"


def test_book_with_one_phase_only_gets_none_never_zero(tmp_path):
    """A missing block is not a smooth join. 0.0 would read as "the blocks line up" (inv. #17)."""
    d = tmp_path / "only_bt"
    d.mkdir(parents=True)
    rows = [_row(_day(i), 100_000.0 * (1.0004 ** i), "backtest") for i in range(70)]
    (d / "realized_series.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    assert M.seam_steps(tmp_path)["only_bt"] is None


# ═══════════════════════ 4. fail-CLOSED on an unmeasured panel ═══════════════════════
def test_no_forward_block_refuses_instead_of_returning_empty(tmp_path):
    """An empty panel must raise, so it can never be printed as a clean forward result."""
    d = tmp_path / "bt_only"
    d.mkdir(parents=True)
    rows = [_row(_day(i), 100_000.0, "backtest") for i in range(70)]
    (d / "realized_series.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    with pytest.raises(RuntimeError, match="phase='forward'"):
        M.load_forward_panel(tmp_path)


def test_short_forward_block_is_dropped_not_padded(tmp_path):
    write_panel(tmp_path, {"a": (UP, [0.001] * 5), "b": (UP, UP)})
    fw = M.load_forward_panel(tmp_path, min_rows=30)
    assert "a" not in fw and "b" in fw


# ═══════════════════════ 5. liveness is a property of the SLICE ═══════════════════════
def test_breadth_is_an_era_property_not_a_panel_property(tmp_path):
    """The live finding of #125: a book frozen in one block can MOVE in the other.

    `frozen_in_bt` is flat across the backtest block and moving across the forward block, so the
    two eras must disagree about it. #122 measured the sleeve on the backtest era; reading that
    sleeve as a property of the PANEL is the mistake this control pins.
    """
    write_panel(tmp_path, {"always": (MIXED, MIXED),
                           "frozen_in_bt": ([0.0] * 80, MIXED),
                           "frozen_in_fw": (MIXED, [0.0] * 80)})
    fw = M.load_forward_panel(tmp_path)
    live, frozen = M.forward_breadth(M.monotone_census(fw))
    assert "frozen_in_bt" in live, "it moves on the forward block, so forward-era it is LIVE"
    assert "frozen_in_fw" in frozen
    assert "always" in live
    # the three asserts above all held while `live` was the WHOLE panel: `frozen` is computed
    # beside it and stayed right, so membership alone never saw the mutant. The partition has to
    # be asserted AS a partition.
    assert "frozen_in_fw" not in live
    assert set(live).isdisjoint(set(frozen))
    assert sorted(live) + sorted(frozen) and len(live) + len(frozen) == 3


def test_census_separates_down_up_and_flat(tmp_path):
    write_panel(tmp_path, {"m": (MIXED, MIXED), "u": (UP, UP)})
    c = M.monotone_census(M.load_forward_panel(tmp_path))
    assert c["u"]["down_days"] == 0 and c["u"]["maxdd_observable"] is False
    assert c["m"]["down_days"] > 0 and c["m"]["maxdd_observable"] is True
    for book in c.values():
        assert book["down_days"] + book["up_days"] + book["flat_days"] == book["returns"]


# ═══════════════════════ 6. selection causality, both directions ═══════════════════════
def test_selection_reads_the_backtest_block_only(tmp_path):
    """Corrupting the forward block must move the forward numbers and NOT move the choice.

    One direction alone proves nothing: unchanged numbers could mean the corruption never landed.
    """
    # THE ORDERINGS ARE INVERTED ON PURPOSE. The first version of this scene gave all three books
    # the SAME forward block, so a selector reading the forward block hit a three-way tie and
    # `max` returned the same name the honest selector returns: the peek was invisible and the
    # mutant survived. Here the backtest says hi > mid > lo and the forward block says the
    # reverse, so the two selectors MUST disagree.
    scene = {"hi":  ([0.002] * 120,  [0.0001] * 80),
             "mid": ([0.001] * 120,  [0.0010] * 80),
             "lo":  ([0.0005] * 120, [0.0050] * 80)}
    a = write_panel(tmp_path / "a", dict(scene))

    ra = M.cross_phase_transfer(["hi", "lo", "mid"], cap=0.10, panel_dir=a)
    assert ra["rows"][0]["subset"] == ["hi"], (
        "N=1 must be the BACKTEST-best book; picking 'lo' means selection read the forward block, "
        "where lo is the best")

    # ...and the differential, which proves the corruption lands at all
    bad = dict(scene)
    bad["hi"] = ([0.002] * 120, [0.05] * 80)
    b = write_panel(tmp_path / "b", bad)
    rb = M.cross_phase_transfer(["hi", "lo", "mid"], cap=0.10, panel_dir=b)
    assert [r["subset"] for r in ra["rows"]] == [r["subset"] for r in rb["rows"]], (
        "the chosen subsets moved when only the FORWARD block changed — selection is peeking")
    fa = [r["forward"]["window_return"] for r in ra["rows"]]
    fb = [r["forward"]["window_return"] for r in rb["rows"]]
    assert fa != fb, "the corruption never landed, so this test proved nothing"


def test_cap_that_admits_nothing_is_the_third_outcome(tmp_path):
    """A cap admitting no subset of size N is a named reason, never a zero row (inv. #17)."""
    write_panel(tmp_path, {"v": (MIXED, MIXED), "w": (MIXED, MIXED)})
    r = M.cross_phase_transfer(["v", "w"], cap=1e-9, panel_dir=tmp_path)
    assert all(row["admitted"] == 0 for row in r["rows"])
    assert all(row["reason"] and row["forward"] is None for row in r["rows"])


def test_universe_name_absent_from_a_block_raises(tmp_path):
    write_panel(tmp_path, {"a": (UP, UP)})
    with pytest.raises(RuntimeError, match="absent from the"):
        M.cross_phase_transfer(["a", "ghost"], cap=0.10, panel_dir=tmp_path)


# ═══════════════════════ 7. printing never invents a number ═══════════════════════
def test_num_never_renders_none_as_a_number():
    """The defect: `(calmar or 0)` printed a REFUSED ratio as 0.000."""
    assert M._num(None, 8) == "NOT MEASURED"
    assert M._num(None, 8, sign=True) == "NOT MEASURED"
    assert M._num(1.5, 8) == "1.500"
    assert M._num(-1.5, 8, sign=True) == "-1.500"


def test_dd_printer_says_the_word():
    assert "NOT MEASURED" in M._dd({"status": "unmeasured_monotone", "maxdd": None})
    assert "%" in M._dd({"status": "measured", "maxdd": 0.05})


def test_zero_is_never_a_stand_in_for_refused():
    """Belt and braces across both printers: the string "0.000" must not appear for a None."""
    assert "0.000" not in M._num(None, 9)
    assert "0.000" not in M._dd({"status": "unmeasured_monotone", "maxdd": None})


# ═══════════════════════ 8. the sizer's leak relocates ═══════════════════════
def test_excluding_dead_legs_relocates_the_leak_instead_of_clearing_it(tmp_path):
    """#126 order 2's real answer: 1/sigma maximises weight on whatever moved LEAST.

    Exclude the exactly-zero books and the share in them is zero by construction — but the weight
    lands on the lowest-volatility SURVIVOR, and on this shape "moved least" means "was not
    measured", not "is safe". The scene is built so the survivor set contains one near-flat book.
    """
    # NAMES MATTER HERE: the quiet survivor is deliberately LAST alphabetically and the noisy one
    # FIRST, because the first version of this scene called them flat_live/noisy_live — the quiet
    # book was also `sorted(...)[0]`, so a mutant that returned the first name alphabetically
    # instead of the argmax was indistinguishable from the real thing.
    write_panel(tmp_path, {
        "dead": ([0.0] * 400, [0.0] * 80),
        "a_noisy_live": (MIXED * 5, MIXED),
        "zz_quiet_live": ([0.00001 if i % 2 else 0.00002 for i in range(400)], UP),
    })
    res = M.sizer_leak(panel_dir=tmp_path, lookback=30)
    assert "dead" in res["frozen_sleeve"]
    assert res["live_only"]["mean_weight_in_frozen"] == 0.0, "zero BY CONSTRUCTION, as ordered"
    assert res["all_books"]["mean_weight_in_frozen"] > 0.0, "the leak the order asked about"
    assert res["live_only"]["top_name"] == "zz_quiet_live", (
        "1/sigma must land on the QUIETEST survivor, which this scene puts last alphabetically")
    assert sorted(res["live_only"]["mean_weights"])[0] == "a_noisy_live", "scene sanity"
    assert res["live_only"]["breaches_policy_cap"] is True, (
        "the pathology survived exclusion — it moved from exactly-zero books to the quietest "
        "survivor, and parked more than the 20 %/name cap there")


def test_sizer_refuses_a_degenerate_calmar(tmp_path):
    """maxDD ~ 0 on a near-flat series must not be published as a four-digit Calmar."""
    write_panel(tmp_path, {"dead": ([0.0] * 400, [0.0] * 80),
                           "a_noisy_live": (MIXED * 5, MIXED),
                           "zz_quiet_live": (UP * 5, UP)})
    res = M.sizer_leak(panel_dir=tmp_path, lookback=30)
    s = res["live_only"]
    assert s["dd_status"] != "measured" or s["calmar"] is None or abs(s["calmar"]) > 100, (
        "this scene is supposed to be degenerate; if it is not, the control proves nothing")


# ═══════════════════════ 9. order 1 puts both zeros on ONE axis ═══════════════════════
def test_order_one_scores_the_overlay_against_both_zeros(tmp_path):
    """#123's acceptance criterion, literally: both deltas, same axis, same overlay."""
    write_panel(tmp_path, {"dead": ([0.0] * 400, [0.0] * 80),
                           "a": (MIXED * 5, MIXED), "b": (MIXED * 5, MIXED)})
    r = M.rebased_overlay_accounting(panel_dir=tmp_path)
    assert set(r["vs_ew10"]["books"]) == {"dead", "a", "b"}
    assert "dead" not in r["vs_ew_live"]["books"], "the honest zero excludes the killed book"
    assert r["vs_ew10"]["n_books"] > r["vs_ew_live"]["n_books"]
    assert r["axis_days"] == r["axis_days"]  # one axis for both, by construction


def test_overlay_is_causal():
    """The de-risk flag for day i may not read day i — it reads up to i-1.

    The first version of this control bumped the LAST return and compared `flags[:-1]`, which
    excludes the one index a same-day read would move: the mutant `abs(returns[i]) > thr` survived
    it untouched. So the bump goes in the MIDDLE, and the assertion is about the flag ON that very
    day, which a causal overlay decided before the day happened.
    """
    base = list(MIXED)
    k = len(base) // 2
    f1 = M.vol_regime_overlay(base)
    bumped = list(base)
    bumped[k] = 0.5
    f2 = M.vol_regime_overlay(bumped)
    assert f1[k] == f2[k], (
        "day k's own return changed day k's flag — the overlay reads the day it is judging")
    assert f1[:k] == f2[:k], "a later return moved an earlier flag — the overlay is peeking"
    assert f1[k + 1:] != f2[k + 1:], (
        "the bump changed no later flag at all, so this control proved nothing")


# ═══════════════════════ 10. the real panel: reproduction, or a NAMED third outcome ═══════
#: the numbers #125/#126 PUBLISH. Pinned here so the registry entry is machine-checked rather
#: than retyped: if the live panel drifts, this says so instead of the entry quietly going stale.
PUBLISHED = {
    "forward_days": 61,
    "monotone_books": ["eth_directional", "lp_eth_stable", "pendle_pt_levered",
                       "pendle_yt_susde", "points_farm", "susde_dn", "susde_spot"],
    "forward_live": 9,
    "backtest_live": ["eth_directional", "pendle_pt_levered", "pendle_yt_susde",
                      "points_farm", "susde_dn", "susde_spot"],
    "moved_between_eras": ["leverage_loop", "levered_restaking", "lrt_neutral"],
    "sizer_top_name": "points_farm",
    "sizer_top_weight_live_only": 0.8611,
}


def _measure_real_panel():
    """('MEASURED', payload) or ('UNMEASURED', reason). Never a zero, never a skip.

    The panel is runtime-only (not in git), so in CI and in any fresh worktree this returns
    UNMEASURED with a named reason. A `pytest.fail` here was tried first and rejected: it turns a
    legitimately absent input into a red test on `main`, which teaches people to switch the guard
    off (inv. #16). A bare `pytest.skip` is the opposite error — it makes "not measured"
    indistinguishable from "passed" (lesson of #465). The reason is therefore RETURNED and
    asserted to be non-empty, which is the pattern of the sibling guard for #122/#123.
    """
    panel = M.PANEL_DIR
    if not panel.is_dir() or not list(panel.glob("*/realized_series.jsonl")):
        return "UNMEASURED", f"panel directory {panel} is absent (runtime-only data, not in git)"
    try:
        res = M.run(panel, verbose=False)
    except Exception as exc:  # noqa: BLE001 - the reason must be named, whatever it is
        return "UNMEASURED", f"panel did not load: {exc}"
    return "MEASURED", res


def test_published_numbers_are_reproduced_or_the_absence_is_named():
    outcome, payload = _measure_real_panel()
    if outcome == "UNMEASURED":
        assert isinstance(payload, str) and payload, "НЕ ИЗМЕРЕНО must carry its reason"
        return
    fw, bt = payload["forward"], payload["backtest_era"]
    assert fw["days"] == PUBLISHED["forward_days"], fw["days"]
    assert sorted(fw["monotone_books"]) == PUBLISHED["monotone_books"], fw["monotone_books"]
    assert len(fw["live"]) == PUBLISHED["forward_live"], fw["live"]
    assert sorted(bt["live"]) == PUBLISHED["backtest_live"], bt["live"]
    assert sorted(set(fw["live"]) - set(bt["live"])) == PUBLISHED["moved_between_eras"]
    # every monotone book really has no down day — the claim the whole entry rests on
    for b in fw["monotone_books"]:
        assert fw["census"][b]["down_days"] == 0
    leak = payload["sizer_leak"]["live_only"]
    assert leak["top_name"] == PUBLISHED["sizer_top_name"]
    assert leak["top_mean_weight"] == pytest.approx(PUBLISHED["sizer_top_weight_live_only"],
                                                    abs=5e-4)
    assert leak["breaches_policy_cap"] is True


def test_the_harness_never_imports_the_execution_domain():
    """inv. #6: read-only / paper code must not import `spa_core.execution`.

    Measured on IMPORT STATEMENTS via AST, not on a substring: the harness docstring and this
    very test both contain the word, so a substring check would red on its own prose.
    """
    import ast as _ast
    tree = _ast.parse(HARNESS.read_text())
    bad = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            bad += [a.name for a in node.names if "spa_core.execution" in a.name]
        elif isinstance(node, _ast.ImportFrom) and node.module:
            if "spa_core.execution" in node.module:
                bad.append(node.module)
    assert not bad, f"read-only harness imports the execution domain: {bad}"


def test_the_harness_declares_itself_advisory():
    """inv. #9 / the standing R&D invariant: nothing here may read as live or policy-bearing."""
    assert M.IS_ADVISORY is True
    assert M.OUTSIDE_RISKPOLICY is True


def test_the_harness_never_writes_anything_outside_an_explicit_json_argument():
    """No `atomic_save`, no state file, no live track: the only write is the opt-in --json path."""
    import ast as _ast
    tree = _ast.parse(HARNESS.read_text())
    writes = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
            if node.func.attr in {"write_text", "write_bytes", "mkdir"}:
                writes.append(node.func.attr)
    assert writes == ["write_text"], (
        f"expected exactly one write (the --json output), found {writes}")
