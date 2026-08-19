# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_displacement_budget.py — registry ideas #65 SND / #66 SWG.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Every pin below is a positive control for one load-bearing claim of the entries:

  • **#40 IS A CORNER OF THIS MACHINE, BIT FOR BIT.** `alloc_budgeted` at budget = m(t)/N must
    reproduce `ecr.alloc_recycle` cell for cell. If it drifts, every row of #65/#66 is comparing
    two different programs and the whole comparison is void. Pinned WITH its refuting half: at
    budget = k/N the two must materially DIFFER, or the identity is passing because the budget is
    being ignored.

  • **SND-count is NOT A NEW RULE — it is M=1 re-derived, and that is a theorem.** For every M,
    today's bottom-k is a subset of the flagged set, so the k worst-ranked members OF the flagged
    set are exactly the bottom-k. #65's headline structural result. Asserted on a fixture where
    m > k really happens (checked, not hoped), so the equality is not vacuous.

  • **This is not #47 in disguise.** A CONSTANT depth is an exact convex combination of raw and
    #40 (#47's identity, residual = machine zero — asserted here as the positive control). A
    STATE-DEPENDENT budget must NOT be: its best-fit affine residual must be large. Both halves,
    because only the pair tells a new rule from a renamed one.

  • **cov is a structural zero for a constant-share rule and is NOT for the published sticky one.**
    #63's correction, inherited: the tidy claim holds only where share really is constant. Both
    halves asserted on the same fixture.

  • **The gate never reads the future.** Mutating tomorrow's gap may not move today's multiplier;
    mutating a past one must move a later one. Both halves, for the same reason.

  • **Fail-CLOSED wherever the cross-section is undefined**: no flagged book ⇒ equal weight (not
    cash); nothing eligible ⇒ cash (not an invented destination); an undefined gap or too short a
    history ⇒ the NEUTRAL budget, never a tilt on dust.

  • **The cap is a cap, the residue is cash, and nothing is ever negative.** A weight map that
    silently breached 20 % would put a number in the registry that RiskPolicy v1.0 forbids, even
    in an advisory backtest.

  • **The ladder's two ends land where the machine says they must**: mult → 0 is equal weight,
    a mult large enough to exceed m(t)/N every day is #40.

  • **Read-only.** The module must contain no write path at all, and no execution import.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_displacement_budget.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_displacement_budget.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_displacement_budget_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


edb = _load()
ecr = edb.ecr
xsd = edb.xsd
spw = edb.spw
ets = edb.ets

TOL = 1e-12
K = 2
M = 20


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them, and a literal date
    would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration."""
    n = len(next(iter(rets.values())))
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


REGIMES = (29, 37, 53, 71, 83, 97)
NEUTRAL = 1.0 / len(REGIMES)


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
    flags = xsd.rank_demotion_flags(scores, K, m_days)
    return rets, panel, scores, flags


def _max_dev(a, b, books, n) -> float:
    return max(abs(a[x][i] - b[x][i]) for x in books for i in range(n))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE ANCHOR — #40 is a corner of this machine, and the budget is really the knob
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cap", [None, 0.20, 0.5])
def test_full_budget_reproduces_the_published_allocator_cell_for_cell(cap):
    _, panel, _, flags = _fixture()
    n, books = panel.n, panel.books
    m = edb.demotion_counts(flags, books, n)
    budget = [x / len(books) for x in m]
    got = edb.alloc_budgeted(books, flags, n, budget, cap)
    want = ecr.alloc_recycle(books, flags, n, cap=cap)
    assert _max_dev(got, want, books, n) < 1e-15


def test_the_fixture_really_has_days_with_more_than_k_books_demoted():
    """Without this the identity above and the whole of #65 would be tested on a degenerate case:
    if m(t) never exceeded k there would be no size term to normalise and every row would coincide."""
    _, panel, _, flags = _fixture()
    m = edb.demotion_counts(flags, panel.books, panel.n)
    assert max(m) > K
    assert sum(1 for x in m if x > K) >= panel.n // 20


def test_a_constant_budget_is_NOT_the_published_allocator():
    """The refuting half of the identity: if this also matched, `budget` would be decorative."""
    _, panel, scores, flags = _fixture()
    got = edb.snd_depth_weights(panel, scores, K, M)
    want = ecr.alloc_recycle(panel.books, flags, panel.n, cap=edb.CONC_CAP)
    assert _max_dev(got, want, panel.books, panel.n) > 1e-3


def test_the_ladder_ends_where_the_machine_says_it_must():
    """mult → 0 is equal weight; a mult past every m(t)/N is #40. Neither end is a discovery."""
    _, panel, scores, flags = _fixture()
    nb = len(panel.books)
    flat = edb.snd_depth_weights(panel, scores, K, M, mult=0.0)
    for b in panel.books:
        assert all(abs(w - 1.0 / nb) < TOL for w in flat[b])
    big = edb.snd_depth_weights(panel, scores, K, M, mult=float(nb))
    pub = ecr.alloc_recycle(panel.books, flags, panel.n, cap=edb.CONC_CAP)
    assert _max_dev(big, pub, panel.books, panel.n) < 1e-15


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. #65's STRUCTURAL RESULT — count-normalisation is M=1 re-derived
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("m_days", [2, 5, 20, 45])
def test_worst_k_of_the_flagged_set_is_exactly_the_bottom_k(m_days):
    """The theorem: bottom-k ⊆ flagged for every M, so the k worst INSIDE flagged are the bottom-k.

    Consequence for the registry: "cap the demoted COUNT at k" is not a new rule at all, it is the
    M=1 corner of #40 under another name — which is why the two rows of the report coincide to the
    last basis point rather than merely resembling one another.
    """
    _, panel, scores, flags = _fixture(m_days)
    trimmed = edb.worst_k_of_flagged(scores, flags, K)
    daily = xsd.rank_demotion_flags(scores, K, 1)
    diff = sum(1 for b in panel.books for i in range(panel.n) if trimmed[b][i] != daily[b][i])
    assert diff == 0


def test_the_trim_really_removes_something():
    """Vacuity guard: on this fixture the trim must actually shrink the flagged set somewhere."""
    _, panel, scores, flags = _fixture()
    before = sum(1 for b in panel.books for i in range(panel.n) if flags[b][i])
    trimmed = edb.worst_k_of_flagged(scores, flags, K)
    after = sum(1 for b in panel.books for i in range(panel.n) if trimmed[b][i])
    assert after < before


def test_count_normalisation_and_the_daily_corner_are_the_same_portfolio():
    _, panel, scores, _ = _fixture()
    a = edb.snd_count_weights(panel, scores, K, M)
    b = spw.binary_weights(panel, scores, K, 1, edb.CONC_CAP)
    assert _max_dev(a, b, panel.books, panel.n) < 1e-15


def test_an_unrankable_flagged_book_is_not_re_admitted_on_an_unmeasured_state():
    """Fail-CLOSED direction: a book we cannot score today keeps the demotion it already has."""
    rets = wobbly()
    panel = panel_of(rets)
    scores = scores_from(rets)
    flags = xsd.rank_demotion_flags(scores, K, M)
    day = next(i for i in range(panel.n)
               if sum(1 for b in panel.books if flags[b][i]) > K)
    victim = next(b for b in panel.books if flags[b][day])
    holed = {b: list(v) for b, v in scores.items()}
    holed[victim][day] = None
    trimmed = edb.worst_k_of_flagged(holed, flags, K)
    assert trimmed[victim][day] is True


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. THIS IS NOT #47 — a state-dependent budget is not an affine combination
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _constant_depth(panel, scores, h: float):
    """#47 PDD by its own definition: (1−h)·raw + h·#40, built without touching this module."""
    nb = len(panel.books)
    pub = spw.binary_weights(panel, scores, K, M, edb.CONC_CAP)
    return {b: [(1.0 - h) / nb + h * v for v in pub[b]] for b in panel.books}


@pytest.mark.parametrize("h", [0.2, 0.5, 0.8])
def test_a_constant_depth_is_an_exact_affine_combination(h):
    """#47's identity, re-derived here as the POSITIVE CONTROL for the residual measurement."""
    _, panel, scores, _ = _fixture()
    r = edb.affine_residual(panel, scores, _constant_depth(panel, scores, h), K)
    assert abs(r["alpha"] - h) < 1e-9
    assert r["max_abs"] < 1e-12


@pytest.mark.parametrize("rule", ["snd_depth", "snd_count", "swg"])
def test_a_state_dependent_budget_is_not_an_affine_combination(rule):
    _, panel, scores, _ = _fixture()
    w = {"snd_depth": edb.snd_depth_weights,
         "snd_count": edb.snd_count_weights,
         "swg": edb.swg_weights}[rule](panel, scores, K, M)
    r = edb.affine_residual(panel, scores, w, K)
    assert r["max_abs"] > 1e-3, "if this is machine zero, #65/#66 are #47 under a new name"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE cov TERM — a structural zero where share is constant, and NOT where it is not
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rule", ["snd_depth", "snd_count"])
def test_cov_is_identically_zero_for_a_constant_share_rule(rule):
    _, panel, scores, _ = _fixture()
    w = {"snd_depth": edb.snd_depth_weights,
         "snd_count": edb.snd_count_weights}[rule](panel, scores, K, M)
    d = spw.decompose(panel, w)
    assert abs(d["cov_share_spread"]) < 1e-15
    assert abs(d["share_mean"] - K / len(panel.books)) < 1e-12


def test_the_published_sticky_rule_does_carry_a_sizing_term():
    """The refuting half. A test that only pinned the zeros would pass on a module whose
    decomposition was broken and returned zero for everything."""
    _, panel, scores, _ = _fixture()
    d = spw.decompose(panel, spw.binary_weights(panel, scores, K, M, edb.CONC_CAP))
    assert abs(d["cov_share_spread"]) > 1e-9
    assert d["share_mean"] > K / len(panel.books) + 1e-6


@pytest.mark.parametrize("rule", ["snd_depth", "snd_count", "swg"])
def test_the_decomposition_still_closes_on_the_new_rules(rule):
    _, panel, scores, _ = _fixture()
    w = {"snd_depth": edb.snd_depth_weights,
         "snd_count": edb.snd_count_weights,
         "swg": edb.swg_weights}[rule](panel, scores, K, M)
    d = spw.decompose(panel, w)
    assert abs(d["resid_1"]) < 1e-15
    assert abs(d["resid_2"]) < 1e-15


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. THE GATE — causal, refusable, and invertible into a control
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_tomorrow_cannot_change_todays_multiplier_but_a_past_day_can():
    _, panel, scores, flags = _fixture()
    gap = edb.score_gap(scores, flags)
    base = edb.gate_multipliers(gap)
    cut = panel.n // 2

    future = list(gap)
    for i in range(cut, panel.n):
        future[i] = None if future[i] is None else future[i] * 7.0 + 1.0
    assert edb.gate_multipliers(future)[:cut] == base[:cut]

    past = list(gap)
    for i in range(0, cut):
        past[i] = None if past[i] is None else past[i] * 7.0 + 1.0
    assert edb.gate_multipliers(past)[cut:] != base[cut:]


def test_an_undefined_gap_is_the_neutral_budget_and_never_a_tilt_on_dust():
    assert edb.gate_multipliers([None] * 400) == [1.0] * 400


def test_too_short_a_history_refuses_to_normalise():
    """The head of any series has no trailing median to divide by. Refusal is neutral, not zero."""
    g = edb.gate_multipliers([1.0] * 400, window=edb.GATE_WINDOW)
    assert g[0] == 1.0 and g[5] == 1.0


def test_a_negative_or_zero_gap_is_neutral_not_negative():
    """A ranking that scores the flagged set ABOVE the eligible one has no confidence to spend;
    the budget falls back to the constant, it never goes negative and never inverts by accident."""
    assert all(x == 1.0 for x in edb.gate_multipliers([-3.0] * 400))


def test_the_multiplier_is_bounded_by_gmax():
    gap: List[Optional[float]] = [1.0] * 200 + [1000.0] * 200
    assert max(edb.gate_multipliers(gap)) <= edb.GMAX + TOL


def test_the_anti_gate_really_inverts_the_gate():
    """The control must be the mirror of the rule, not a second rule. Where the gate spends most,
    the anti-gate must spend least — otherwise "the inversion is better" measures nothing."""
    gap: List[Optional[float]] = [1.0] * 200 + [float(1 + i % 5) for i in range(200)]
    g = edb.gate_multipliers(gap)
    a = edb.gate_multipliers(gap, invert=True)
    moved = [i for i in range(len(g)) if abs(g[i] - 1.0) > TOL]
    assert moved, "fixture produced no active gate days — the test would be vacuous"
    assert all(abs(a[i] - (edb.GMAX - g[i])) < TOL for i in moved)


def test_a_gap_between_a_set_and_an_empty_set_is_undefined_not_zero():
    rets = wobbly()
    scores = scores_from(rets)
    books = sorted(scores)
    n = len(rets[books[0]])
    none_flagged = {b: [False] * n for b in books}
    all_flagged = {b: [True] * n for b in books}
    assert edb.score_gap(scores, none_flagged) == [None] * n
    assert edb.score_gap(scores, all_flagged) == [None] * n


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 6. THE ALLOCATION ITSELF — cap, cash, sign, fail-CLOSED
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mult", [0.0, 0.5, 1.0, 2.0, 6.0])
def test_no_weight_ever_breaches_the_cap_or_goes_negative(mult):
    _, panel, scores, _ = _fixture()
    w = edb.snd_depth_weights(panel, scores, K, M, mult=mult)
    for b in panel.books:
        for x in w[b]:
            assert -TOL <= x <= edb.CONC_CAP + TOL


@pytest.mark.parametrize("mult", [0.0, 0.5, 1.0, 2.0, 6.0])
def test_the_book_never_sums_above_one(mult):
    _, panel, scores, _ = _fixture()
    w = edb.snd_depth_weights(panel, scores, K, M, mult=mult)
    for i in range(panel.n):
        assert sum(w[b][i] for b in panel.books) <= 1.0 + 1e-9


def test_capital_that_will_not_fit_inside_the_cap_becomes_cash():
    rets = wobbly()
    panel = panel_of(rets)
    scores = scores_from(rets)
    flags = xsd.rank_demotion_flags(scores, K, M)
    tight = 1.0 / len(panel.books) + 0.005
    w = edb.alloc_budgeted(panel.books, flags, panel.n,
                           [K / len(panel.books)] * panel.n, cap=tight)
    assert any(sum(w[b][i] for b in panel.books) < 1.0 - 1e-6 for i in range(panel.n))
    for b in panel.books:
        assert all(x <= tight + TOL for x in w[b])


def test_a_day_with_nothing_flagged_is_equal_weight_not_cash():
    """Refusing to demote is not a reason to leave a panel we already hold."""
    rets = wobbly()
    panel = panel_of(rets)
    nb = len(panel.books)
    flags = {b: [False] * panel.n for b in panel.books}
    w = edb.alloc_budgeted(panel.books, flags, panel.n, [K / nb] * panel.n)
    for b in panel.books:
        assert all(abs(x - 1.0 / nb) < TOL for x in w[b])


def test_a_day_with_nothing_eligible_is_all_cash_not_an_invented_destination():
    rets = wobbly()
    panel = panel_of(rets)
    flags = {b: [True] * panel.n for b in panel.books}
    w = edb.alloc_budgeted(panel.books, flags, panel.n,
                           [float(len(panel.books))] * panel.n)
    for i in range(panel.n):
        assert sum(w[b][i] for b in panel.books) < TOL


def test_the_budget_clip_is_counted_and_not_absorbed():
    _, panel, _, flags = _fixture()
    n, nb = panel.n, len(panel.books)
    assert edb.clip_days(flags, panel.books, n, [0.0] * n) == 0
    assert edb.clip_days(flags, panel.books, n, [float(nb)] * n) == n


@pytest.mark.parametrize("kwargs", [
    {"budget": [0.1]},                      # one number for a many-day panel
    {"books": []},                          # a rule over no books is not a rule
])
def test_meaningless_settings_are_refused(kwargs):
    _, panel, _, flags = _fixture()
    books = kwargs.get("books", panel.books)
    budget = kwargs.get("budget", [0.1] * panel.n)
    with pytest.raises(ValueError):
        edb.alloc_budgeted(books, flags, panel.n, budget)


def test_a_negative_budget_is_floored_at_zero_and_never_shorts_a_book():
    _, panel, _, flags = _fixture()
    nb = len(panel.books)
    w = edb.alloc_budgeted(panel.books, flags, panel.n, [-5.0] * panel.n)
    for b in panel.books:
        assert all(abs(x - 1.0 / nb) < TOL for x in w[b])


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 7. HYGIENE — the artefact's own promises
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_module_declares_itself_advisory_and_outside_riskpolicy():
    assert edb.IS_ADVISORY is True
    assert edb.OUTSIDE_RISKPOLICY is True


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
    """#65/#66 vary ONE knob. If k, M, the lookback or the cap drifted here, the comparison with
    #40 would silently become a comparison of two re-tuned rules."""
    assert edb.REF_K == 2
    assert edb.REF_M == 20
    assert edb.LOOKBACK == xsd.LOOKBACK
    assert edb.CONC_CAP == ecr.CONC_CAP == 0.20
    assert edb.TRAIN_END == ecr.TRAIN_END
