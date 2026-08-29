"""
Tests for scripts/edge_relative_drawdown_weighting.py (Ideas #86 DDW-REAL / #87 RDW).

Every test here is a POSITIVE CONTROL in the sense `.claude/rules/deployment.md` requires: it
reproduces a failure that would actually change a published verdict, and several of them run a
deliberately BROKEN twin of the mechanism inline and assert the check goes red on it — because a
check that has never seen the real breakage is decoration (registry lesson «положительный
контроль может быть украшением»). The failures guarded against:

  • the parity claim #86 rests on — "the mechanism did not change, only the DATA did" — silently
    breaking, which would make the real-panel table incomparable with #85's fixture table and
    turn a data finding into an unattributable one;
  • the RDW scale peeking at TODAY's drawdown. That is the single defect that would manufacture
    the entire result: a denominator that already knows today's stress makes the ratio look
    stable and the rule look prescient. Guarded by a two-panel identical-prefix test plus a
    look-ahead twin that the same test must reject;
  • the warmup silently tilting before the scale is a measurement, i.e. "not measured" being
    read as "zero" — the fail-OPEN monitor class of this repo;
  • control (A) collapsing: if `per_book` and `shared` ever became the same code path, the
    verdict "the damage comes from the CROSS-SECTIONAL normalisation" would be unfalsifiable;
  • the quiet sub-panel being chosen with TEST data in hand, which would turn control (B) into
    a look-ahead selection and its conclusion into an artefact;
  • the capped baseline not actually respecting its cap, which is the whole reason it exists:
    it is the INVESTABLE benchmark, and an uncapped one is the benchmark this project is not
    allowed to hold.

No network, no RiskPolicy, no spa_core.execution, no live data/ writes. IS_ADVISORY=True.
No literal dates: every series is synthetic and every date is derived from the module's own
SPLIT_DATE constant, so the calendar moving cannot turn one of these red
(`.claude/rules/deployment.md`, «время в тестах — фиксированная дата это бомба замедленного
действия»).
"""
from __future__ import annotations

import datetime
import ast
import importlib.util
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

_ROOT = Path(__file__).parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_relative_drawdown_weighting.py"

# The harness imports its sibling edge scripts by path, so scripts/ has to be importable.
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("edge_rdw_87", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["edge_rdw_87"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

DDW = _mod.DDW
INITIAL = _mod.INITIAL


# ── synthetic panels (index-addressed, no literal dates) ──────────────────────

def _dates(n: int) -> List[datetime.date]:
    """`n` consecutive days ending at the registry-canonical split date."""
    end = _mod.SPLIT_DATE
    return [end - datetime.timedelta(days=n - 1 - i) for i in range(n)]


def _panel(spec: Dict[str, Sequence[float]], dates: Sequence[datetime.date]):
    """{book: {date: daily return}} from per-book return lists of equal length."""
    return {b: {d: rets[i] for i, d in enumerate(dates)} for b, rets in spec.items()}


def _flat_then_drop(n: int, drop_at: int, drop: float) -> List[float]:
    out = [0.0005] * n
    out[drop_at] = drop
    return out


def _weights_path(books, dates, rets_map, kappa, **kw) -> List[Dict[str, float]]:
    """Re-derive the weight path the engine holds, day by day, for causality assertions."""
    path: List[Dict[str, float]] = []
    for i in range(1, len(dates) + 1):
        curve, _ = _mod.run_rdw(books, dates[:i], rets_map, kappa, 0, **kw)
        path.append(curve[-1][1])  # terminal equity summarises the whole held path
    return path


# ── #86: parity — the mechanism is #85's, only the data changed ───────────────

def test_unit_mode_reproduces_idea85_ddw_exactly():
    """`scale_mode="unit"` must BE #85's `_run_ddw`, otherwise #86 compares two rules, not two panels."""
    panel = DDW._load_panel()
    dates, rets_map = DDW._align(panel)
    books = list(DDW.BOOKS)
    for kappa in (0.0, 1.0, 5.0, 20.0):
        for cost in (0, 96):
            ours, _ = _mod.run_rdw(books, dates, rets_map, kappa, cost, scale_mode="unit")
            theirs = DDW._run_ddw(dates, rets_map, kappa, cost)
            assert len(ours) == len(theirs)
            for (d_a, eq_a), (d_b, eq_b) in zip(ours, theirs):
                assert d_a == d_b
                assert eq_a == pytest.approx(eq_b, rel=1e-12, abs=1e-6), (kappa, cost, d_a)


def test_parity_check_is_not_vacuous():
    """POSITIVE CONTROL: the parity assertion must FAIL when the mechanism really differs.

    A parity test that passes against anything proves nothing. Here the twin is #85's own engine
    run at a different kappa — a genuine mechanism change — and parity must reject it.
    """
    panel = DDW._load_panel()
    dates, rets_map = DDW._align(panel)
    books = list(DDW.BOOKS)
    ours, _ = _mod.run_rdw(books, dates, rets_map, 5.0, 0, scale_mode="unit")
    wrong = DDW._run_ddw(dates, rets_map, 20.0, 0)
    assert any(abs(a[1] - b[1]) > 1e-6 for a, b in zip(ours, wrong))


def test_books_bound_to_restores_the_universe():
    """#86 rebinds #85's BOOKS global. If it leaked, every later caller would silently mis-run."""
    before = list(DDW.BOOKS)
    with _mod.books_bound_to(["a", "b"]):
        assert DDW.BOOKS == ["a", "b"]
    assert DDW.BOOKS == before
    with pytest.raises(ValueError):
        with _mod.books_bound_to(["a"]):
            raise ValueError("boom")
    assert DDW.BOOKS == before


# ── #87: the scale must be CAUSAL ─────────────────────────────────────────────

def test_scale_never_sees_the_future():
    """Two panels identical up to day t must give the identical equity at day t.

    This is the no-look-ahead law. If the expanding-window scale ever included the current or a
    later day, tomorrow's crash would change today's weights — and the whole #87 table would be
    a measurement of hindsight.
    """
    n = 200
    dates = _dates(n)
    shared_prefix = _flat_then_drop(n, drop_at=150, drop=-0.05)
    calm_tail = list(shared_prefix)
    crash_tail = list(shared_prefix)
    crash_tail[180] = -0.30                     # differs only AFTER the day we compare
    books = ["a", "b"]
    p_calm = _panel({"a": calm_tail, "b": [0.0003] * n}, dates)
    p_crash = _panel({"a": crash_tail, "b": [0.0003] * n}, dates)

    cut = 170
    calm, _ = _mod.run_rdw(books, dates[:cut], p_calm, 10.0, 0)
    crash, _ = _mod.run_rdw(books, dates[:cut], p_crash, 10.0, 0)
    assert calm[-1][1] == pytest.approx(crash[-1][1], rel=1e-12)


def test_lookahead_twin_is_rejected_by_the_causality_check():
    """POSITIVE CONTROL: a scale that includes the FULL-SAMPLE mean fails the test above.

    The twin is the mistake an author actually makes — computing the per-book DD scale once over
    the whole series because it is one line shorter. It is run here on the same two panels; the
    identical-prefix equality must break.
    """
    n = 200
    dates = _dates(n)
    base = _flat_then_drop(n, drop_at=150, drop=-0.05)
    crash = list(base)
    crash[180] = -0.30
    books = ["a", "b"]

    def _run_with_full_sample_scale(rets_map, upto: int) -> float:
        """#87's rule with ONE deliberate defect: the scale is the full-sample mean."""
        scale: Dict[str, float] = {}
        for b in books:
            eq = peak = INITIAL
            acc = 0.0
            for d in dates:                       # ← the defect: the WHOLE series, not the past
                eq *= (1.0 + rets_map[b][d])
                peak = max(peak, eq)
                acc += max(0.0, 1.0 - eq / peak)
            scale[b] = max(_mod.SCALE_FLOOR, acc / len(dates))
        standalone = {b: INITIAL for b in books}
        peaks = {b: INITIAL for b in books}
        w = {b: 0.5 for b in books}
        eq_p = INITIAL
        for d in dates[:upto]:
            for b in books:
                standalone[b] *= (1.0 + rets_map[b][d])
                peaks[b] = max(peaks[b], standalone[b])
            dd = {b: max(0.0, 1.0 - standalone[b] / peaks[b]) for b in books}
            eq_p *= (1.0 + sum(w[b] * rets_map[b][d] for b in books))
            w = _mod._rdw_targets(books, dd, scale, 10.0)
        return eq_p

    p_calm = _panel({"a": base, "b": [0.0003] * n}, dates)
    p_crash = _panel({"a": crash, "b": [0.0003] * n}, dates)
    calm = _run_with_full_sample_scale(p_calm, 170)
    crashed = _run_with_full_sample_scale(p_crash, 170)
    assert abs(calm - crashed) > 1e-6, "look-ahead twin must be detectable, else the check is decoration"


def test_todays_drawdown_is_excluded_from_its_own_denominator():
    """The day's own DD must not be in the mean it is divided by — measured THROUGH the engine.

    This is the mutation that survived the first version of this file: the look-ahead test above
    only forbids FUTURE data, and folding TODAY into the denominator uses no future at all. It is
    still wrong, and it is wrong in the direction that flatters the rule — a denominator that has
    already absorbed today's stress makes the ratio small and the de-risk gentle. So the weight
    the engine actually HOLDS is read back here, not the arithmetic of `_rdw_targets` in
    isolation: a test of the parts cannot see a defect in the wiring.

    Three days, two books, warmup=1:
      day 0  both flat            → the DD history is one observation of zero
      day 1  `a` drops 10%        → causal scale_a = FLOOR (0.5%), ratio = 20
                                    defective scale_a = mean(0, 0.10) = 5%, ratio = 2
      day 2  `a` flat, `b` +10%   → the portfolio return reveals w_b, hence w_a
    """
    dates = _dates(3)
    rets_map = _panel({"a": [0.0, -0.10, 0.0], "b": [0.0, 0.0, 0.10]}, dates)
    kappa = 10.0
    curve, _ = _mod.run_rdw(["a", "b"], dates, rets_map, kappa, 0, warmup=1)

    # w_a held into day 2, recovered from that day's portfolio return (only `b` moved).
    day2_ret = curve[2][1] / curve[1][1] - 1.0
    w_a = 1.0 - day2_ret / 0.10

    ratio_causal = 0.10 / _mod.SCALE_FLOOR                       # scale = FLOOR
    raw_a = 1.0 / (1.0 + kappa * ratio_causal)
    expected_w_a = raw_a / (raw_a + 1.0)
    assert w_a == pytest.approx(expected_w_a, rel=1e-9)

    ratio_defective = 0.10 / ((0.0 + 0.10) / 2.0)                # scale = mean INCLUDING today
    raw_def = 1.0 / (1.0 + kappa * ratio_defective)
    w_a_defective = raw_def / (raw_def + 1.0)
    assert w_a_defective > 8 * expected_w_a, (
        "the two readings must be far apart, otherwise this test could not tell them apart")
    assert w_a < w_a_defective


# ── #87: warmup is fail-CLOSED, not fail-open ─────────────────────────────────

def test_warmup_holds_equal_weights_and_costs_nothing():
    """Before the scale is a measurement the rule must not tilt at all — «не измерено» ≠ «ноль»."""
    n = _mod.WARMUP_DAYS
    dates = _dates(n)
    rets_map = _panel({"a": _flat_then_drop(n, 40, -0.20), "b": [0.001] * n}, dates)
    curve, to = _mod.run_rdw(["a", "b"], dates, rets_map, 20.0, 96)
    assert to == pytest.approx(0.0, abs=1e-9), "any trade during warmup would show up as turnover"
    bh = _mod.ew_baseline(["a", "b"], dates, rets_map)
    assert curve[-1][1] == pytest.approx(bh[-1][1], rel=1e-12), (
        "holding — not rebalancing to equal — is the fail-CLOSED reading of an unmeasured scale")


def test_warmup_control_shows_the_test_can_fail():
    """POSITIVE CONTROL: with warmup=0 the same configuration DOES tilt, so the guard is real."""
    n = _mod.WARMUP_DAYS
    dates = _dates(n)
    rets_map = _panel({"a": _flat_then_drop(n, 40, -0.20), "b": [0.001] * n}, dates)
    _, to = _mod.run_rdw(["a", "b"], dates, rets_map, 20.0, 96, warmup=0)
    assert to > 0.05


def test_kappa_zero_is_equal_weight_rebalancing():
    """kappa=0 must be plain equal-weight rebalancing — the null of the whole family.

    The two scale-aware modes hold on day 0 (there is no history yet, see `run_rdw`), while the
    `unit` null has no warmup concept at all and rebalances immediately. That one day is the
    ONLY difference, and it is asserted here rather than left as a shrug: from day 1 the three
    modes coincide, and `unit` reproduces #85's own kappa=0 curve exactly.
    """
    n = _mod.WARMUP_DAYS + 60
    dates = _dates(n)
    rets_map = _panel({"a": _flat_then_drop(n, 130, -0.20), "b": [0.001] * n}, dates)
    ref, _ = _mod.run_rdw(["a", "b"], dates, rets_map, 0.0, 0, scale_mode="per_book", warmup=0)
    shared, _ = _mod.run_rdw(["a", "b"], dates, rets_map, 0.0, 0, scale_mode="shared", warmup=0)
    assert [eq for _, eq in shared] == pytest.approx([eq for _, eq in ref], rel=1e-12)

    unit, _ = _mod.run_rdw(["a", "b"], dates, rets_map, 0.0, 0, scale_mode="unit")
    with _mod.books_bound_to(["a", "b"]):
        ddw0 = DDW._run_ddw(list(dates), rets_map, 0.0, 0)
    assert [eq for _, eq in unit] == pytest.approx([eq for _, eq in ddw0], rel=1e-12)
    # …and the day-0 hold is the whole of the remaining gap: the curves stay parallel after it.
    ratio = [u[1] / r[1] for u, r in zip(unit[1:], ref[1:])]
    assert max(ratio) - min(ratio) < 1e-9


def test_unknown_scale_mode_refuses():
    dates = _dates(10)
    rets_map = _panel({"a": [0.0] * 10, "b": [0.0] * 10}, dates)
    with pytest.raises(ValueError):
        _mod.run_rdw(["a", "b"], dates, rets_map, 1.0, 0, scale_mode="whatever")


# ── control (A): per_book vs shared must be genuinely different code paths ─────

def test_per_book_and_shared_diverge_when_book_scales_differ():
    """If these two ever coincided, #87's attribution of the damage would be unfalsifiable."""
    n = _mod.WARMUP_DAYS + 200
    dates = _dates(n)
    noisy = [0.02 if i % 2 else -0.02 for i in range(n)]      # large, permanent DD scale
    quiet = [0.0005] * n
    quiet[n - 30] = -0.01                                     # one small, ABNORMAL-for-it dip
    rets_map = _panel({"noisy": noisy, "quiet": quiet}, dates)
    a, _ = _mod.run_rdw(["noisy", "quiet"], dates, rets_map, 10.0, 0, scale_mode="per_book")
    b, _ = _mod.run_rdw(["noisy", "quiet"], dates, rets_map, 10.0, 0, scale_mode="shared")
    assert abs(a[-1][1] - b[-1][1]) > 1.0


def test_per_book_collapses_onto_shared_when_every_scale_is_at_the_floor():
    """The measured reason #87 has no resolution on quiet books — asserted, not asserted-by-prose.

    When no book has enough history of drawdown, every per-book scale is clamped to the same
    FLOOR, so the "relative" rule silently becomes the shared-scale rule. This is why the quiet
    sub-panel (control B) shows per_book ≈ shared instead of the предсказанное расхождение.
    """
    n = _mod.WARMUP_DAYS + 40
    dates = _dates(n)
    rets_map = _panel({"a": [0.0002] * n, "b": [0.0003] * n}, dates)
    rets_map["a"][dates[-1]] = -0.001
    a, _ = _mod.run_rdw(["a", "b"], dates, rets_map, 10.0, 0, scale_mode="per_book")
    b, _ = _mod.run_rdw(["a", "b"], dates, rets_map, 10.0, 0, scale_mode="shared")
    assert a[-1][1] == pytest.approx(b[-1][1], rel=1e-12)


# ── control (B): the quiet sub-panel is selected CAUSALLY ─────────────────────

def test_quiet_selection_ignores_everything_after_the_split():
    """A book that only blows up AFTER the split must still be selected as quiet."""
    n = 400
    dates = [_mod.SPLIT_DATE - datetime.timedelta(days=n // 2 - 1 - i) for i in range(n)]
    calm = [0.0002] * n
    late_blowup = list(calm)
    late_blowup[n - 10] = -0.50                    # strictly after SPLIT_DATE
    rets_map = _panel({"steady": calm, "late": late_blowup,
                       "loud": [-0.02 if i % 3 else 0.03 for i in range(n)]}, dates)
    quiet = _mod.quiet_books_from_train(["steady", "late", "loud"], dates, rets_map)
    assert "steady" in quiet and "late" in quiet
    assert "loud" not in quiet


def test_quiet_selection_refuses_a_train_window_shorter_than_warmup():
    n = 40
    dates = [_mod.SPLIT_DATE - datetime.timedelta(days=n - 1 - i) for i in range(n)]
    rets_map = _panel({"a": [0.0] * n, "b": [0.0] * n}, dates)
    with pytest.raises(RuntimeError):
        _mod.quiet_books_from_train(["a", "b"], dates, rets_map)


# ── the INVESTABLE baseline actually respects its cap ─────────────────────────

def test_capped_baseline_never_exceeds_the_cap():
    """A 'capped' benchmark that drifts past the cap is just buy-and-hold wearing a label."""
    n = 400
    dates = _dates(n)
    winner = [0.01] * n                            # compounds away from everyone else
    rets_map = _panel({"winner": winner, "a": [0.0] * n, "b": [0.0] * n,
                       "c": [0.0] * n, "d": [0.0] * n, "e": [0.0] * n}, dates)
    books = sorted(rets_map)
    curve, to = _mod.run_capped_bh(books, dates, rets_map, 0, cap=0.20)
    assert to > 0.0, "a runaway winner must force the cap to trade"
    w = {b: 1.0 / len(books) for b in books}
    for d in dates:
        port = sum(w[b] * rets_map[b][d] for b in books)
        val = {b: w[b] * (1.0 + rets_map[b][d]) / (1.0 + port) for b in books}
        tot = sum(val.values())
        w = _mod._cap_weights({b: val[b] / tot for b in books}, 0.20)
        assert max(w.values()) <= 0.20 + 1e-9
        assert sum(w.values()) == pytest.approx(1.0)
    assert curve[-1][1] > 0


def test_cap_of_one_is_plain_buy_and_hold():
    """NULL of the capped baseline: cap=100% must reproduce buy-and-hold with zero turnover."""
    n = 300
    dates = _dates(n)
    rets_map = _panel({"a": [0.003] * n, "b": [0.0001] * n, "c": [-0.0005] * n}, dates)
    books = sorted(rets_map)
    capped, to = _mod.run_capped_bh(books, dates, rets_map, 96, cap=1.0)
    bh = _mod.ew_baseline(books, dates, rets_map)
    assert to == pytest.approx(0.0, abs=1e-9)
    assert capped[-1][1] == pytest.approx(bh[-1][1], rel=1e-10)


def test_cap_below_equal_weight_degenerates_to_equal_weight():
    """Fail-CLOSED arithmetic: a cap the universe cannot satisfy must not silently un-normalise."""
    w = _mod._cap_weights({"a": 0.5, "b": 0.3, "c": 0.2}, 0.10)
    assert w == {"a": pytest.approx(1 / 3), "b": pytest.approx(1 / 3), "c": pytest.approx(1 / 3)}


# ── metrics / split arithmetic ────────────────────────────────────────────────

def test_split_metrics_rebase_the_test_half_onto_the_train_close():
    """#85 compared half-sample Calmars against a FULL-sample base and said so. #87 does not."""
    n = 400
    dates = [_mod.SPLIT_DATE - datetime.timedelta(days=n // 2 - 1 - i) for i in range(n)]
    curve = [(d, INITIAL * (1.0 + 0.001 * i)) for i, d in enumerate(dates)]
    sm = _mod.split_metrics(curve)
    train_close = [eq for d, eq in curve if d <= _mod.SPLIT_DATE][-1]
    manual = _mod.metrics([(d, eq) for d, eq in curve if d > _mod.SPLIT_DATE], train_close)
    assert sm["test"] == manual
    assert sm["test"]["max_dd_pct"] == pytest.approx(0.0), (
        "a test half rebased on the train close cannot inherit a drawdown it never lived through")


def test_metrics_report_a_drawdown_that_exists():
    n = 200
    dates = _dates(n)
    curve = [(d, INITIAL * (0.9 if i == 100 else 1.0)) for i, d in enumerate(dates)]
    m = _mod.metrics(curve)
    assert m["max_dd_pct"] == pytest.approx(-10.0, abs=0.01)


# ── advisory / safety invariants ──────────────────────────────────────────────

def test_harness_is_advisory_and_touches_no_execution_path():
    src = _SCRIPT.read_text()
    # Strip comments and string literals, so the module's own prose about what it does NOT do
    # cannot satisfy — or violate — a check about what it DOES. (A grep over raw source read the
    # docstring sentence "never imports spa_core.execution" as an import.)
    code = "".join(
        "" if tok.type in (tokenize.STRING, tokenize.COMMENT) else tok.string
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
    )
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.startswith("spa_core.execution") for m in imported), imported
    assert "spa_core.execution" not in code
    assert "OUTSIDE_RISKPOLICY=True" in src
    assert "IS_ADVISORY=True" in src
    assert not re.search(r"\bopen\(|\.write_text\(|atomic_save", code), (
        "an advisory backtest writes no state at all")


def test_registry_carries_the_verdicts_this_script_produced():
    """A harness delivered without its verdict is an orphan: the registry is the deliverable."""
    reg = (_ROOT / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md")
    if not reg.exists():                       # docs/ is absent in some worktrees BY CONSTRUCTION
        pytest.skip("docs/DYNAMIC_LEVERAGE_GUARDIAN.md not present in this tree")
    text = reg.read_text()
    assert "#86" in text and "#87" in text
    assert "edge_relative_drawdown_weighting.py" in text


# ── the real panel, when this tree has one ────────────────────────────────────

def _panel_available() -> bool:
    return _mod.PANEL_DIR.exists() and any(_mod.PANEL_DIR.glob("*/realized_series.jsonl"))


@pytest.mark.skipif(not _panel_available(),
                    reason="aggressive-lab panel is not git-tracked and is absent in this tree "
                           "BY CONSTRUCTION; point SPA_PANEL_DIR at the prod copy to run it")
def test_real_panel_loads_fail_closed_and_agrees_with_the_published_shape():
    books, dates, rets_map = _mod.load_real_panel()
    assert len(books) >= 5
    assert len(dates) >= 120
    assert dates == sorted(dates)
    for b in books:
        assert set(rets_map[b]) == set(dates), "no book may be carried over a date it lacks"
    quiet = _mod.quiet_books_from_train(books, dates, rets_map)
    assert set(quiet) <= set(books)


@pytest.mark.skipif(not _panel_available(), reason="panel absent in this tree BY CONSTRUCTION")
def test_published_headline_of_86_still_reproduces():
    """The number the registry entry leads with. If the loader or the engine drifts, this goes red."""
    books, dates, rets_map = _mod.load_real_panel()
    base = _mod.metrics(_mod.ew_baseline(books, dates, rets_map))
    with _mod.books_bound_to(books):
        ddw1 = _mod.metrics(DDW._run_ddw(list(dates), rets_map, 1.0, 96))
    assert base["calmar"] > ddw1["calmar"], (
        "#86's verdict is that DDW LOSES to buy-and-hold on the real panel")
    assert base["calmar"] == pytest.approx(8.2776, abs=0.05)
    assert ddw1["calmar"] == pytest.approx(4.1438, abs=0.05)
