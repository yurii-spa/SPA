# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_static_tilt_transfer.py — registry ideas #67 STT / #68 FFB.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Every pin below is a positive control for one load-bearing claim of the entries —
and, wherever a claim could pass for the wrong reason, its REFUTING half stands beside it.

  • **THE TILT IS THE REGISTRY'S OWN TWIN, AND THE ONLY DIFFERENCE IS THE FIT WINDOW.** Fitted over
    the whole path, `tilt_from` must equal `ecr.alloc_static_matched` to machine precision — that
    identity is what makes #67 a measurement OF the printed twin rather than a new object being
    compared with it. Pinned with its refuting half: fitted over a strict sub-window on a panel
    where the leadership rotates, it must materially DIFFER, or the window is decorative.

  • **THE FIT NEVER READS THE DAYS IT IS SCORED ON.** Mutating a return AFTER the fit window may
    not move the frozen vector; mutating one INSIDE it must. This is the single property that
    separates #67 from the hindsight twin, so it is asserted in both directions — an "it does not
    look at the future" that only ever checks one side is a hope.

  • **SCORING A FIXED PATH ON A WINDOW IS SLICING, NOT RE-RUNNING.** `segment` over the whole axis
    must reproduce the panel's own metrics cell for cell; over a strict sub-window it must differ.
    Fail-CLOSED on an empty or reversed window: a metric over no days is not a small number.

  • **A CONSTANT TARGET IS NOT A FREE PORTFOLIO (#49).** Target turnover of a frozen tilt is
    exactly zero — and its IMPLEMENTATION turnover is strictly positive as soon as the books drift
    apart, and exactly zero when they do not. All three, because the entry's whole cost claim is
    that the registry charged the first number and owed the second.

  • **THE MIRROR IS A REAL REFUTATION, NOT A DECORATION.** It reverses the book ORDER, preserves
    the deployed total whenever the cap allows, is its own fixed point at equal weight, and
    reports what will not fit under the cap as CASH instead of breaching it.

  • **#68 IS "DROP TWO NAMES AND KEEP EQUAL WEIGHT" — AND IT IS FROZEN.** Exactly k books out, the
    same k on every day, chosen from the fit window alone; at k=0 the rule IS equal weight (the
    corner that makes it continuous with raw); k ≥ N and k < 0 refuse. The invert control takes
    the BEST k, disjointly.

  • **THE CAP IS A CAP** on every allocation this file produces. A row in the registry that
    silently breached 20 % would be a number RiskPolicy v1.0 forbids, even in an advisory backtest.

  • **A RATIO AGAINST A NON-POSITIVE DENOMINATOR IS REFUSED**, not printed: on a segment where the
    published rule has no excess to share, "captured 300 % of it" is arithmetic, not a finding.

  • **Read-only.** No write path at all, no execution import, no re-tuned constants.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_static_tilt_transfer.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_static_tilt_transfer.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_static_tilt_transfer_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stt = _load()
ecr = stt.ecr
xsd = stt.xsd
spw = stt.spw
ets = stt.ets
rdt = stt.rdt

TOL = 1e-12
K = 2
M = 20
REGIMES = (29, 37, 53, 71, 83, 97)


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them here, and a literal
    date would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration. The
    two tests that DO need an orderable date axis build their own, minimal one."""
    n = len(next(iter(rets.values())))
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


def wobbly(n: int = 240) -> Dict[str, List[float]]:
    """Six books that take turns leading, in coprime regimes rather than day-to-day flicker.

    Six and not four: with four books the neutral share 0.25 already breaches the project's 0.20
    cap, so every weight would sit pinned at the cap and half of these tests would pass while
    measuring nothing. The real panels carry 10 and 6 books against that same cap.
    """
    jit = [0.0001 * (i % 7) for i in range(n)]
    return {chr(ord("a") + j): [0.001 * float((i // p) % 4) + jit[i] for i in range(n)]
            for j, p in enumerate(REGIMES)}


def scores_from(rets: Dict[str, List[float]],
                warmup: int = 0) -> Dict[str, List[Optional[float]]]:
    """A trailing-shaped score object: the book's own return, with a `None` warm-up head."""
    return {b: [None if i < warmup else v[i] for i in range(len(v))] for b, v in rets.items()}


def _fixture(m_days: int = M):
    rets = wobbly()
    panel = panel_of(rets)
    scores = scores_from(rets)
    weights = spw.binary_weights(panel, scores, K, m_days, stt.CONC_CAP)
    return rets, panel, scores, weights


def _max_dev(a, b, books, n) -> float:
    return max(abs(a[x][i] - b[x][i]) for x in books for i in range(n))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE ANCHOR — the tilt IS the registry's printed twin; only the fit window differs
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_a_tilt_fitted_over_the_whole_path_is_the_registrys_static_twin():
    """If this drifts, #67 stops being a measurement of the twin the registry keeps citing and
    silently becomes a comparison against some other constant vector."""
    _, panel, _, w = _fixture()
    got = stt.const_weights(stt.tilt_from(w, 0, panel.n), panel.n)
    want = ecr.alloc_static_matched(w)
    assert _max_dev(got, want, panel.books, panel.n) < 1e-15


def test_a_tilt_fitted_on_a_sub_window_really_differs_from_the_whole_sample_one():
    """The refuting half. Without it the identity above could pass because the fit window is
    ignored — which is exactly the bug that would make #67 report the hindsight twin twice."""
    _, panel, _, w = _fixture()
    half = stt.tilt_from(w, 0, panel.n // 2)
    full = stt.tilt_from(w, 0, panel.n)
    assert max(abs(half[b] - full[b]) for b in panel.books) > 1e-3


def test_the_tilt_is_a_full_book_and_never_negative():
    _, panel, _, w = _fixture()
    tilt = stt.tilt_from(w, 0, panel.n // 2)
    assert all(v >= -TOL for v in tilt.values())
    assert sum(tilt.values()) <= 1.0 + TOL


def test_fitting_a_tilt_on_nothing_is_refused():
    _, panel, _, w = _fixture()
    for bad in ((5, 5), (7, 3), (-1, 10), (0, panel.n + 1)):
        with pytest.raises(ValueError):
            stt.tilt_from(w, *bad)
    with pytest.raises(ValueError):
        stt.tilt_from({}, 0, 1)
    with pytest.raises(ValueError):
        stt.const_weights({"a": 0.5}, 0)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. CAUSALITY — the property that separates #67 from the twin it is auditing
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _tilt_of(rets: Dict[str, List[float]], fit_end: int):
    panel = panel_of(rets)
    w = spw.binary_weights(panel, scores_from(rets), K, M, stt.CONC_CAP)
    return stt.tilt_from(w, 0, fit_end), w


def test_a_return_after_the_fit_window_cannot_move_the_frozen_tilt():
    """Both halves in one test on purpose: the mutation must be proved LIVE (it really moves the
    allocation on the days after the window) before "the tilt did not move" means anything. An
    inert mutation would pass the causality claim while testing nothing at all."""
    rets = wobbly()
    fit_end = 120
    before, w_before = _tilt_of(rets, fit_end)
    mutated = {b: list(v) for b, v in rets.items()}
    for i in range(fit_end + 20, fit_end + 60):  # days the tilt is not allowed to have seen
        mutated["a"][i] -= 5.0
    after, w_after = _tilt_of(mutated, fit_end)
    assert _max_dev(w_before, w_after, sorted(rets), len(rets["a"])) > 1e-6, "inert mutation"
    assert max(abs(before[b] - after[b]) for b in before) < 1e-15


def test_a_return_inside_the_fit_window_does_move_it():
    """The positive control. A "does not read the future" test that never sees the vector move at
    all would also pass on a function that returns a constant."""
    rets = wobbly()
    fit_end = 120
    before, _ = _tilt_of(rets, fit_end)
    mutated = {b: list(v) for b, v in rets.items()}
    for i in range(20, 60):                      # drive one book into the bottom-k, in-window
        mutated["a"][i] -= 5.0
    after, _ = _tilt_of(mutated, fit_end)
    assert max(abs(before[b] - after[b]) for b in before) > 1e-6


def test_the_split_index_uses_the_panels_own_strictly_greater_convention():
    """`dgo.Panel(start=...)` keeps days with `d > start`. A split that disagreed by one day would
    leak exactly one day of the scored window into the fit — the smallest possible lookahead, and
    the hardest to see in a table.

    The axis is built AROUND the module's own split constant instead of quoting a literal date, so
    the test moves with `TRAIN_END` and pins no calendar of its own (`.claude/rules/deployment.md`,
    preference #1: the date is an input, not a fixture).
    """
    from datetime import date, timedelta
    split = date.fromisoformat(stt.TRAIN_END)
    axis = [(split + timedelta(days=d)).isoformat() for d in (-120, 0, 1, 200)]
    panel = ets.SynthPanel(axis, {"a": [0.0] * 4, "b": [0.001] * 4})
    assert panel.axis[stt.split_index(panel, stt.TRAIN_END)] == axis[2], "the split day is TRAIN"
    assert stt.split_index(panel, axis[0]) == 1
    assert stt.split_index(panel, (split - timedelta(days=999)).isoformat()) == 0
    assert stt.split_index(panel, (split + timedelta(days=999)).isoformat()) == panel.n


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. SEGMENTS — scoring a fixed path on a window is slicing, not re-running
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _drawdown_fixture():
    """`wobbly` never loses money, so its maxDD is 0 and its Calmar is an infinity — two
    infinities are not "equal cell for cell", they are two absences. Two loss days give the
    identity tests a finite Calmar to actually compare."""
    rets = wobbly()
    for b in rets:
        for i in (60, 61, 150):
            rets[b][i] -= 0.02
    panel = panel_of(rets)
    return panel, spw.binary_weights(panel, scores_from(rets), K, M, stt.CONC_CAP)


def test_a_segment_over_the_whole_axis_reproduces_the_panel_cell_for_cell():
    panel, w = _drawdown_fixture()
    assert ecr.portfolio_metrics(panel, w)["maxdd"] < -1e-6, "fixture has no drawdown to compare"
    whole = stt.segment(panel, 0, panel.n)
    a = ecr.portfolio_metrics(panel, w)
    b = ecr.portfolio_metrics(whole, stt.slice_weights(w, 0, panel.n))
    for key in ("apy", "maxdd", "calmar", "turnover_yr", "net_apy_after_cost"):
        assert abs(a[key] - b[key]) < 1e-15, key


def test_a_strict_sub_window_is_a_different_measurement():
    """The refuting half: if `segment` quietly ignored its bounds, every TEST row in the entry
    would be a FULL row wearing an out-of-sample label — the exact error #67 was written to fix."""
    _, panel, _, w = _fixture()
    half = stt.segment(panel, panel.n // 2, panel.n)
    a = ecr.portfolio_metrics(panel, w)
    b = ecr.portfolio_metrics(half, stt.slice_weights(w, panel.n // 2, panel.n))
    assert abs(a["apy"] - b["apy"]) > 1e-6


def test_an_empty_or_reversed_window_is_refused():
    _, panel, _, _ = _fixture()
    for bad in ((5, 5), (9, 4), (-1, 10), (0, panel.n + 1)):
        with pytest.raises(ValueError):
            stt.segment(panel, *bad)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. BOTH BILLS — the correction #67 owes every static row the registry ever printed
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_a_frozen_tilt_costs_exactly_zero_under_the_registrys_own_bill():
    _, panel, _, w = _fixture()
    const = stt.const_weights(stt.tilt_from(w, 0, panel.n // 2), panel.n)
    assert ecr.portfolio_metrics(panel, const)["turnover_yr"] < 1e-15


def test_and_strictly_more_than_zero_under_the_bill_reality_sends():
    """#49's number, on the row the registry has always charged nothing: a constant TARGET has to
    be pushed back into place every day the books drift apart."""
    _, panel, _, w = _fixture()
    const = stt.const_weights(stt.tilt_from(w, 0, panel.n // 2), panel.n)
    m = stt.evaluate(panel, const)
    assert m["turnover_impl_yr"] > 1e-6
    assert m["net_apy_after_impl"] < m["net_apy_after_cost"] - 1e-9


def test_the_two_bills_agree_exactly_when_there_is_no_drift_to_pay_for():
    """The other half, and the one that proves the number is drift and not an artefact of the
    accounting: books that move together do not move apart, so the honest bill is zero too."""
    n = 120
    rets = {b: [0.001 + 0.0001 * (i % 5) for i in range(n)] for b in "abcdef"}
    panel = panel_of(rets)
    const = stt.const_weights({b: 1.0 / 6 for b in panel.books}, n)
    m = stt.evaluate(panel, const)
    assert m["turnover_impl_yr"] < 1e-9
    assert abs(m["net_apy_after_impl"] - m["net_apy_after_cost"]) < 1e-12


def test_the_implementation_bill_is_the_one_idea49_defines():
    """No second definition of the tax: #49's function is called, not re-derived here."""
    _, panel, _, w = _fixture()
    const = stt.const_weights(stt.tilt_from(w, 0, panel.n // 2), panel.n)
    assert abs(stt.evaluate(panel, const)["turnover_impl_yr"]
               - rdt.implementation_turnover(panel, const)) < 1e-15


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. THE MIRROR — #66's refuting control, reused because it is the one that has killed an idea
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_the_mirror_reverses_the_order_of_the_books():
    _, panel, _, w = _fixture()
    tilt = stt.tilt_from(w, 0, panel.n // 2)
    mir, _ = stt.mirror_tilt(tilt, cap=None)
    by_tilt = sorted(panel.books, key=lambda b: tilt[b])
    by_mirror = sorted(panel.books, key=lambda b: mir[b])
    assert by_tilt == list(reversed(by_mirror))


def test_the_mirror_keeps_the_book_the_same_size_when_the_cap_allows():
    _, panel, _, w = _fixture()
    tilt = stt.tilt_from(w, 0, panel.n // 2)
    mir, unplaced = stt.mirror_tilt(tilt, cap=None)
    assert abs(sum(mir.values()) - sum(tilt.values())) < 1e-12
    assert unplaced < 1e-12


def test_equal_weight_is_its_own_mirror():
    tilt = {b: 1.0 / 6 for b in "abcdef"}
    mir, unplaced = stt.mirror_tilt(tilt, cap=0.20)
    assert max(abs(mir[b] - tilt[b]) for b in tilt) < 1e-12
    assert unplaced < 1e-12


def test_what_will_not_fit_under_the_cap_comes_back_as_cash_and_is_never_a_breach():
    """A cap that bends under pressure is not a cap. The residue is reported, so the caller can
    print it; silently redistributing it would put a 25 % name in an advisory registry table."""
    tilt = {"a": 0.70, "b": 0.10, "c": 0.10, "d": 0.10}
    mir, unplaced = stt.mirror_tilt(tilt, cap=0.20)
    assert all(-TOL <= v <= 0.20 + TOL for v in mir.values())
    assert unplaced > 1e-9
    assert abs(sum(mir.values()) + unplaced - sum(tilt.values())) < 1e-12


def test_mirroring_nothing_is_refused():
    with pytest.raises(ValueError):
        stt.mirror_tilt({})


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 6. #68 FFB — a frozen exclusion list, and it must really be frozen
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_exactly_k_books_are_out_and_they_are_out_on_every_single_day():
    _, panel, _, _ = _fixture()
    flags = stt.frozen_flags(panel, 0, 100, K, panel.n)
    out = [b for b in panel.books if flags[b][0]]
    assert len(out) == K
    for b in panel.books:
        assert len(set(flags[b])) == 1, f"{b} changed its flag — the list is not frozen"


def test_the_excluded_books_are_the_worst_of_the_fit_window_only():
    rets = wobbly()
    panel = panel_of(rets)
    base = stt.frozen_flags(panel, 0, 100, K, panel.n)
    mutated = {b: list(v) for b, v in rets.items()}
    for i in range(100, len(mutated["a"])):
        mutated["a"][i] += 1.0                   # make book 'a' the best book AFTER the window
    after = stt.frozen_flags(panel_of(mutated), 0, 100, K, panel.n)
    assert {b: after[b][0] for b in panel.books} == {b: base[b][0] for b in panel.books}


def test_and_the_fit_window_itself_does_decide_them():
    """The positive control for the test above — otherwise a function that always freezes the same
    two names alphabetically would pass it."""
    rets = wobbly()
    panel = panel_of(rets)
    base = stt.frozen_flags(panel, 0, 100, K, panel.n)
    worst = next(b for b in panel.books if base[b][0])
    mutated = {b: list(v) for b, v in rets.items()}
    for i in range(100):
        mutated[worst][i] += 1.0                 # make the worst book the best one, in-window
    after = stt.frozen_flags(panel_of(mutated), 0, 100, K, panel.n)
    assert after[worst][0] is False


def test_the_invert_control_takes_the_best_books_and_they_are_a_different_set():
    _, panel, _, _ = _fixture()
    lo = stt.frozen_flags(panel, 0, 100, K, panel.n)
    hi = stt.frozen_flags(panel, 0, 100, K, panel.n, invert=True)
    lo_set = {b for b in panel.books if lo[b][0]}
    hi_set = {b for b in panel.books if hi[b][0]}
    assert len(hi_set) == K
    assert lo_set.isdisjoint(hi_set)
    order = [b for b, _ in stt.train_mean_ranking(panel, 0, 100)]
    assert lo_set == set(order[:K]) and hi_set == set(order[-K:])


def test_at_k_zero_the_rule_is_equal_weight_and_that_is_the_corner_it_shares_with_raw():
    _, panel, _, _ = _fixture()
    w = stt.ffb_weights(panel, 0, 100, k=0)
    nb = len(panel.books)
    assert max(abs(w[b][i] - 1.0 / nb) for b in panel.books for i in range(panel.n)) < 1e-15


def test_freezing_out_every_book_or_a_negative_number_of_them_is_refused():
    _, panel, _, _ = _fixture()
    with pytest.raises(ValueError):
        stt.frozen_flags(panel, 0, 100, len(panel.books), panel.n)
    with pytest.raises(ValueError):
        stt.frozen_flags(panel, 0, 100, -1, panel.n)


def test_ffb_is_literally_drop_k_names_and_keep_equal_weight_while_the_cap_is_slack():
    """The identity that makes #68 legible: with the cap not binding, `ecr.alloc_recycle` over a
    frozen flag set is equal weight over the survivors. The entry claims exactly this in words, so
    it is pinned as arithmetic rather than left as prose."""
    _, panel, _, _ = _fixture()
    w = stt.ffb_weights(panel, 0, 100, K, cap=None)
    survivors = [b for b in panel.books if w[b][0] > 0]
    assert len(survivors) == len(panel.books) - K
    for b in survivors:
        assert abs(w[b][0] - 1.0 / len(survivors)) < 1e-15
    assert abs(sum(w[b][0] for b in panel.books) - 1.0) < 1e-12


def test_when_the_cap_binds_the_residue_is_cash_and_not_a_breach():
    """The refuting half of the identity above: the survivors cannot simply absorb everything."""
    _, panel, _, _ = _fixture()
    w = stt.ffb_weights(panel, 0, 100, k=4, cap=0.20)     # 2 survivors, 20 % each ⇒ 60 % cash
    assert max(w[b][0] for b in panel.books) <= 0.20 + TOL
    assert sum(w[b][0] for b in panel.books) < 1.0 - 1e-9


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 7. THE CAP, ON EVERYTHING THIS FILE PRODUCES
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_no_allocation_this_file_builds_ever_breaches_the_cap_or_goes_short():
    _, panel, scores, w = _fixture()
    tilt = stt.tilt_from(w, 0, panel.n // 2)
    mir, _ = stt.mirror_tilt(tilt, stt.CONC_CAP)
    built = [stt.const_weights(tilt, panel.n), stt.const_weights(mir, panel.n),
             stt.ffb_weights(panel, 0, panel.n // 2, K, panel.n, stt.CONC_CAP),
             stt.ffb_weights(panel, 0, panel.n // 2, K, panel.n, stt.CONC_CAP, invert=True)]
    for alloc in built:
        for b in panel.books:
            for x in alloc[b]:
                assert -TOL <= x <= stt.CONC_CAP + TOL


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 8. THE CAPTURE RATIO — refused rather than fabricated
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _res(raw: float, pub: float, rule: float) -> Dict[str, Dict[str, float]]:
    return {"raw equal weight": {"net_apy_after_impl": raw},
            "#40 XSD k=2 M=20 [published]": {"net_apy_after_impl": pub},
            "#67 STT tilt fitted on TRAIN": {"net_apy_after_impl": rule}}


def test_capture_is_the_share_of_the_published_rules_own_excess():
    got = stt._capture(_res(0.05, 0.15, 0.09), "#67 STT tilt fitted on TRAIN")
    assert got is not None and abs(got - 0.4) < 1e-12


def test_capture_refuses_to_divide_by_a_non_positive_excess():
    """On a segment where #40 does not beat raw, "captured 250 %" is arithmetic about a negative
    denominator, and it would read in the registry as a triumph."""
    for pub in (0.05, 0.02):
        assert stt._capture(_res(0.05, pub, 0.09), "#67 STT tilt fitted on TRAIN") is None


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 9. REPORT PLUMBING — a row cannot be read without its baselines
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_selecting_one_idea_drops_the_other_and_keeps_every_baseline():
    rows = [("raw equal weight", {}), ("#40 XSD k=2 M=20 [published]", {}),
            ("#67 STT tilt fitted on TRAIN", {}), ("  CONTROL mirror of the TRAIN tilt", {}),
            ("#68 FFB frozen bottom-k of TRAIN", {}), ("  CONTROL FFB frozen TOP-k (invert)", {}),
            ("  HINDSIGHT twin of #40 (whole sample)", {})]
    names67 = [n.strip() for n, _ in stt._only(rows, 67)]
    names68 = [n.strip() for n, _ in stt._only(rows, 68)]
    assert [n.strip() for n, _ in stt._only(rows, None)] == [n.strip() for n, _ in rows]
    for names in (names67, names68):
        assert "raw equal weight" in names
        assert any(n.startswith("#40 XSD") for n in names)
        assert any(n.startswith("HINDSIGHT") for n in names)
    assert not any(n.startswith(("#68", "CONTROL FFB")) for n in names67)
    assert not any(n.startswith(("#67", "CONTROL mirror")) for n in names68)


def test_a_split_that_leaves_one_side_empty_is_refused_before_anything_is_fitted():
    _, panel, scores, _ = _fixture()
    for split in ("c99999", "d99999"):        # before the first day / after the last one
        with pytest.raises(ValueError):
            stt.rows_for(panel, scores, split, K, stt.CONC_CAP)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 10. HYGIENE — the artefact's own promises
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_module_declares_itself_advisory_and_outside_riskpolicy():
    assert stt.IS_ADVISORY is True
    assert stt.OUTSIDE_RISKPOLICY is True


def test_the_file_contains_no_write_path_at_all():
    src = SCRIPT.read_text()
    for forbidden in ("open(", "write_text", "os.replace", "atomic_save", "mkdir", "json.dump"):
        assert forbidden not in src, f"{forbidden} — this file must stay read-only"


def test_it_imports_no_execution_code():
    src = SCRIPT.read_text()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "execution" not in stripped, f"execution import: {stripped}"


def test_the_reference_constants_are_the_registrys_own_and_not_re_tuned():
    """#67/#68 vary ONE knob — when the tilt is allowed to learn. If k, M, the lookback, the cap,
    the split or the cost drifted here, the comparison with #40 would silently become a comparison
    of two differently-tuned rules, which is the failure this whole family is built to avoid."""
    assert stt.REF_K == 2
    assert stt.REF_M == 20
    assert stt.LOOKBACK == xsd.LOOKBACK == 60
    assert stt.CONC_CAP == ecr.CONC_CAP == 0.20
    assert stt.TRAIN_END == ecr.TRAIN_END
    assert stt.COST_BP_ROUND_TRIP == ecr.COST_BP_ROUND_TRIP
    assert stt.TRAIN_END in stt.SPLITS and len(set(stt.SPLITS)) == len(stt.SPLITS)
