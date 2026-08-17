# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_decision_hold.py — registry ideas #60 DHD / #61 RPH.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Every pin below is a positive control for one load-bearing claim of the entries:

  • **The published rule is a CORNER of the new machine, not a lookalike.** `decision_hold_flags`
    at (D=1, J=1, R=0, M=m) must equal `xsd.rank_demotion_flags(s, k, m)` cell for cell. This is
    the anchor of both entries: if it drifts, every DHD row is measuring a different rule than the
    one the registry published, and the whole comparison is void. Pinned with a mutation control
    that reddens when any single knob is moved off the corner.

  • **The causal side never reads a future return.** Mutating tomorrow's score must not move
    today's flag; mutating YESTERDAY's must. Both halves are asserted, because a test that only
    checks the first passes on a module that ignores its input entirely.

  • **The term R is a term.** With hold_days=R no completed demotion may be shorter than R days.
    Without this the "decoupling" claim is a parameter name, not a behaviour.

  • **The hold clock counts CALENDAR days, not decisions.** With D>1 a term must still expire on
    schedule; a clock that paused whenever the rule looked away would silently make R and D the
    same knob again — the exact conflation the entry exists to undo.

  • **Fail-CLOSED where a rank is undefined.** Fewer than k+1 rankable books ⇒ nobody changes
    state, and an unmeasured book (score None) can never enter the bottom-k.

  • **`spell_stats` counts the spell still running at the sample end.** Dropping it would shorten
    the mean by exactly the longest spells, which is the direction that flatters a "we hold long"
    claim.

  • **#61's nulls are the honest ones.** `chance` is k/N; `majority` is the best CONSTANT set and
    is bounded by 1; the causal set scores 100 % overlap when trailing and forward agree by
    construction. `majority`/`spread_const` are LOOK-AHEAD and the docstring must say so — a
    reader who mistakes a bound for a strategy is the failure mode this entry can cause.

  • **Read-only.** The module must contain no write path at all: running it may not create,
    truncate or append to a single file.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_decision_hold.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_decision_hold.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_decision_hold_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dh = _load()
xsd = dh.xsd
ecr = dh.ecr
ets = dh.ets


def scores_of(cols: Dict[str, List[Optional[float]]]) -> Dict[str, List[Optional[float]]]:
    return {b: list(v) for b, v in cols.items()}


def wobbly(n: int = 400) -> Dict[str, List[Optional[float]]]:
    """Four books that take turns being worst, in REGIMES rather than day-to-day flicker.

    The regime lengths (29/37/53/71 days) are coprime, so the bottom-2 set genuinely changes and —
    crucially — books are genuinely RE-ADMITTED. A flickering panel is not good enough here: under
    the published machine a book that re-enters the bottom-k every few days can never assemble
    M=20 good days in a row, so it latches demoted forever and every knob below becomes invisible.
    The first draft of this fixture flickered, and two of these tests passed for that reason —
    which is the same failure the machine itself is being tested for.
    """
    jit = [0.001 * (i % 3) for i in range(n)]
    return {
        "a": [float((i // 29) % 4) + jit[i] for i in range(n)],
        "b": [float((i // 37) % 4) + jit[i] for i in range(n)],
        "c": [float((i // 53) % 4) + jit[i] for i in range(n)],
        "d": [float((i // 71) % 4) + jit[i] for i in range(n)],
    }


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them, and a literal date
    would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration."""
    n = len(next(iter(rets.values())))
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


def spells_of(path: List[bool]) -> List[int]:
    out, run = [], 0
    for f in path:
        if f:
            run += 1
        elif run:
            out.append(run)
            run = 0
    return out                        # the open spell at the end is deliberately NOT returned


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE ANCHOR — the published rule is a corner of the new machine
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("m", [1, 2, 5, 20, 45])
def test_corner_is_the_published_machine_cell_for_cell(m):
    s = scores_of(wobbly())
    assert dh.decision_hold_flags(s, 2, 1, 1, 0, m) == xsd.rank_demotion_flags(s, 2, m)


@pytest.mark.parametrize("knob", ["decide", "enter", "hold"])
def test_moving_any_knob_off_the_corner_breaks_the_identity(knob):
    """POSITIVE CONTROL for the test above: it must be capable of failing.

    An identity assertion is worthless unless something can violate it. Each knob is nudged by the
    smallest amount that has meaning, and the result must stop matching the published machine —
    otherwise the knob is decorative and the entry's four-way decomposition is three knobs and a
    comment.
    """
    s = scores_of(wobbly())
    ref = xsd.rank_demotion_flags(s, 2, 20)
    moved = {
        "decide": dh.decision_hold_flags(s, 2, 2, 1, 0, 20),
        "enter": dh.decision_hold_flags(s, 2, 1, 3, 0, 20),
        "hold": dh.decision_hold_flags(s, 2, 1, 1, 40, 20),
    }[knob]
    assert moved != ref


def test_readmit_and_term_are_different_machines_at_the_same_mean_spell():
    """The claim the whole entry rests on: (R=20, M=1) and (R=0, M=20) are not the same rule.

    If these ever coincided, "decoupling" would be a renaming and #60 would have measured nothing.
    """
    s = scores_of(wobbly())
    assert dh.decision_hold_flags(s, 2, 1, 1, 20, 1) != dh.decision_hold_flags(s, 2, 1, 1, 0, 20)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. CAUSALITY — the rule side never reads a future score
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_tomorrow_cannot_change_today_but_yesterday_can():
    s = scores_of(wobbly())
    base = dh.decision_hold_flags(s, 2, 1, 1, 5, 3)
    cut = 100

    future = scores_of(wobbly())
    for b in future:
        for i in range(cut, len(future[b])):
            future[b][i] = -99.0
    after = dh.decision_hold_flags(future, 2, 1, 1, 5, 3)
    for b in base:
        assert base[b][:cut] == after[b][:cut], "a future score moved a past flag — look-ahead"

    past = scores_of(wobbly())
    for b in past:
        past[b][cut - 1] = -99.0 if b == "a" else 99.0
    changed = dh.decision_hold_flags(past, 2, 1, 1, 5, 3)
    assert any(base[b] != changed[b] for b in base), \
        "mutating the past changed nothing — the test above would pass on a constant function"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. THE TERM IS A TERM, AND ITS CLOCK IS THE CALENDAR
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("r", [5, 20, 40])
def test_no_completed_spell_is_shorter_than_the_term(r):
    s = scores_of(wobbly())
    flags = dh.decision_hold_flags(s, 2, 1, 1, r, 1)
    for b, path in flags.items():
        for length in spells_of(path):
            assert length >= r, f"{b}: spell of {length} days under a {r}-day term"


def test_term_still_expires_when_the_rule_only_looks_every_D_days():
    """The hold clock counts CALENDAR days, not decisions. With D=10 and R=5 the term is already
    spent by the very next decision epoch, so the SHORTEST completed spell must be exactly 10 days.

    THIS TEST WAS DECLARED UNFIT AND REWRITTEN. Its first form asserted only that spell lengths
    are multiples of D — which is true of a calendar clock and of an epoch clock alike, so the
    mutation "tick `since` only on epochs" passed it 35/35. An epoch clock would need R=5 EPOCHS
    (50 days) to release, and the entry's whole claim is that R and D are separate knobs; a test
    that cannot tell 10 from 50 was pinning the multiple-of-D property and calling it the clock.
    Both facts are now asserted: the multiple (the epoch grid) and the minimum (the calendar).
    """
    s = scores_of(wobbly())
    flags = dh.decision_hold_flags(s, 2, 10, 1, 5, 1)
    lengths = [x for path in flags.values() for x in spells_of(path)]
    assert lengths, "no spell ever ended — nothing pinned"
    for length in lengths:
        assert length % 10 == 0, f"a spell of {length} days ended off-epoch under D=10"
    assert min(lengths) == 10, (
        f"shortest spell is {min(lengths)} days under D=10, R=5 — the term is being counted in "
        "decisions rather than in calendar days, which re-merges the two knobs")


def test_state_only_changes_on_decision_epochs():
    s = scores_of(wobbly())
    flags = dh.decision_hold_flags(s, 2, 5, 1, 0, 1)
    for b, path in flags.items():
        for i in range(1, len(path)):
            if i % 5:
                assert path[i] == path[i - 1], f"{b}: state moved on day {i}, not a decision epoch"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. FAIL-CLOSED WHERE A RANK IS NOT DEFINED
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_unrankable_day_freezes_every_book():
    n = 40
    s: Dict[str, List[Optional[float]]] = {
        "a": [float(i % 3) for i in range(n)],
        "b": [float((i + 1) % 3) for i in range(n)],
        "c": [float((i + 2) % 3) for i in range(n)],
    }
    for b in s:                                    # days 20..24 are unmeasured for everybody
        for i in range(20, 25):
            s[b][i] = None
    flags = dh.decision_hold_flags(s, 1, 1, 1, 0, 1)
    for b, path in flags.items():
        assert path[19:25] == [path[19]] * 6, f"{b}: state moved on a day with no ranking"


def test_an_unmeasured_book_is_never_demoted_for_being_unmeasured():
    n = 30
    s: Dict[str, List[Optional[float]]] = {
        "a": [1.0] * n,
        "b": [2.0] * n,
        "c": [3.0] * n,
        "dark": [None] * n,
    }
    flags = dh.decision_hold_flags(s, 1, 1, 1, 0, 1)
    assert not any(flags["dark"]), "None was read as a low score — unmeasured is not worst"
    assert all(flags["a"][1:]), "the genuinely worst measured book was not demoted"


def test_the_grid_phase_is_a_real_choice_and_defaults_to_zero():
    """#60's phase control is only meaningful if the phase actually moves the flags.

    The entry's sharpest claim is that the decision grid's PHASE moves the result as much as its
    SPACING — which is a statement about noise, and would be vacuous if `decide_phase` were
    ignored. Pinned in both directions: phase 0 is the default (so every other table in the file
    is the phase-0 draw and says so), and some other phase differs.
    """
    s = scores_of(wobbly())
    assert dh.decision_hold_flags(s, 2, 7, 1, 0, 20, decide_phase=0) == \
        dh.decision_hold_flags(s, 2, 7, 1, 0, 20)
    assert any(dh.decision_hold_flags(s, 2, 7, 1, 0, 20, decide_phase=ph) !=
               dh.decision_hold_flags(s, 2, 7, 1, 0, 20) for ph in range(1, 7))


@pytest.mark.parametrize("kwargs", [
    {"decide_every": 0}, {"enter_days": 0}, {"hold_days": -1}, {"readmit_days": 0},
    {"decide_every": 5, "decide_phase": 5}, {"decide_phase": -1},
])
def test_meaningless_knobs_are_refused(kwargs):
    with pytest.raises(ValueError):
        dh.decision_hold_flags(scores_of(wobbly(60)), 2, **kwargs)


@pytest.mark.parametrize("k", [0, 4, 9])
def test_k_outside_the_panel_is_refused(k):
    with pytest.raises(ValueError):
        dh.decision_hold_flags(scores_of(wobbly(60)), k)


def test_anti_rule_demotes_the_top_not_the_bottom():
    s = {"lo": [1.0] * 30, "hi": [9.0] * 30, "mid": [5.0] * 30}
    worst = dh.decision_hold_flags(s, 1, 1, 1, 0, 1, worst_first=True)
    best = dh.decision_hold_flags(s, 1, 1, 1, 0, 1, worst_first=False)
    assert all(worst["lo"][1:]) and not any(worst["hi"])
    assert all(best["hi"][1:]) and not any(best["lo"])


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. SPELL BOOKKEEPING
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_the_open_spell_at_the_end_is_counted():
    flags = {"a": [False, True, True, False, True, True, True]}
    st = dh.spell_stats(flags, 7)
    assert st["mean_spell"] == pytest.approx((2 + 3) / 2)
    assert st["max_spell"] == 3
    assert st["duty"] == pytest.approx(5 / 7)


def test_dropping_the_open_spell_would_shorten_the_mean():
    """POSITIVE CONTROL for the pin above — proves the two conventions actually differ here."""
    flags = {"a": [False, True] + [True] * 20}
    assert dh.spell_stats(flags, 22)["mean_spell"] > sum(spells_of(flags["a"]) or [0])


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 6. #61 — the nulls, and what they are allowed to claim
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_bottom_set_refuses_when_there_is_no_worst_and_breaks_ties_by_name():
    s: Dict[str, List[Optional[float]]] = {"a": [1.0], "b": [1.0], "c": [None]}
    assert dh.bottom_set(s, ["a", "b", "c"], 0, 2) is None      # only 2 rankable, k=2 ⇒ no ranking
    assert dh.bottom_set(s, ["a", "b", "c"], 0, 1) == frozenset({"a"})


def test_chance_is_k_over_n_and_majority_is_a_share():
    panel = panel_of({
        "a": [4e-4] * 300, "b": [-3e-4] * 300,
        "c": [1e-4 + 1e-5 * (i % 9) for i in range(300)], "d": [-1e-4] * 300,
    })
    m = dh.rank_agreement(panel, k=2, lookback=30, horizon=5)
    assert m["chance"] == pytest.approx(2 / 4)
    assert 0.0 <= m["majority"] <= 1.0
    assert 0.0 <= m["overlap"] <= 1.0
    assert m["days"] > 0


def test_a_panel_with_a_standing_order_is_perfectly_predicted_and_scores_no_edge():
    """Two books that are always the worst: overlap 100 %, majority 100 %, edge exactly zero.

    This is the shape #61 is looking for in the real panel and the reason its null is `majority`
    rather than a coin: a rule can be right every single day and still know nothing, because the
    answer never changed. A test suite that only checked `overlap > chance` would call this an edge.
    """
    panel = panel_of({"a": [5e-4] * 300, "b": [4e-4] * 300, "c": [-2e-4] * 300, "d": [-3e-4] * 300})
    m = dh.rank_agreement(panel, k=2, lookback=30, horizon=5)
    assert m["overlap"] == pytest.approx(1.0)
    assert m["majority"] == pytest.approx(1.0)
    assert m["overlap"] - m["majority"] == pytest.approx(0.0)
    assert m["spread_bp"] > 0.0                      # it does separate; it just never learns


def test_the_look_ahead_nulls_are_declared_as_look_ahead():
    """#61's two nulls are bounds, not strategies. If the docstring stops saying so, a reader can
    quote `majority` as something an allocator could have held — which is exactly the mistake the
    entry warns against, and the only kind of harm a read-only research file can do."""
    doc = dh.rank_agreement.__doc__ or ""
    assert "LOOK-AHEAD" in doc
    assert "majority" in doc and "spread_const" in doc


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 7. SCOPE — advisory, outside RiskPolicy, and physically unable to write
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_module_declares_itself_advisory_and_outside_riskpolicy():
    assert dh.IS_ADVISORY is True
    assert dh.OUTSIDE_RISKPOLICY is True


def test_the_file_contains_no_write_path_at_all():
    src = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("atomic_save", "open(", ".write_text", ".write(", "os.replace", "shutil."):
        assert forbidden not in src, f"a research file acquired a write path: {forbidden}"


def test_it_imports_no_execution_code():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "spa_core.execution" not in src and "from spa_core" not in src


def test_the_static_twin_control_really_has_no_timing():
    """The instrument the entry convicts its own best cell with must be what it claims: constant
    weights, zero turnover. If the twin ever acquired timing, the R→∞ verdict would be unfounded."""
    panel = panel_of({
        "a": [3e-4 + 1e-5 * (i % 5) for i in range(300)],
        "b": [1e-4 - 1e-5 * (i % 7) for i in range(300)],
        "c": [2e-4] * 300, "d": [-1e-4 + 1e-5 * (i % 3) for i in range(300)],
    })
    scores = {b: dh.xsd.drift_scores(panel.rets, 30)[b] for b in panel.books}
    w, _ = dh.dhd_weights(panel, scores, 1, 1, 1, 20, 1)
    twin = ecr.alloc_static_matched(w)
    assert ecr.portfolio_metrics(panel, twin)["turnover_yr"] == pytest.approx(0.0, abs=1e-9)
    for b in panel.books:
        assert len(set(round(x, 12) for x in twin[b])) == 1
