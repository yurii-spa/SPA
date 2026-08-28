"""
Acceptance for scripts/edge_periodic_schedule_frontier.py (registry ideas PSF / PLD).

Every test here is a POSITIVE CONTROL: it reddens when a specific, named defect is
reintroduced into the harness. A check that has never seen a real failure is decoration
(.claude/rules/deployment.md), so each test states the mutation it survives.

The panel (data/aggressive_lab/) is NOT git-tracked. Tests that need it SKIP LOUDLY with the
reason named; the tests that do not need it — including the one asserting that the loader
REFUSES rather than substituting the fixture — always run.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

psf = importlib.import_module("edge_periodic_schedule_frontier")
cit = importlib.import_module("edge_cost_internalised_timing")
css = importlib.import_module("edge_cost_signal_separation")
mh = importlib.import_module("edge_mhfc_backtest")


# ── panel availability ───────────────────────────────────────────────────────────
def _real_panel():
    try:
        return cit.load_real_panel()
    except (FileNotFoundError, RuntimeError) as exc:  # pragma: no cover - env dependent
        pytest.skip(
            "real aggressive-lab panel unavailable in this tree (it is NOT git-tracked, so a "
            f"worktree simply has no data/aggressive_lab): {exc}"
        )


@pytest.fixture(scope="module")
def fixture_panel():
    return cit.load_fixture_panel()


# ── advisory invariants ──────────────────────────────────────────────────────────
def test_module_is_advisory_and_outside_riskpolicy():
    """Mutation: someone flips a flag and the harness starts looking like a live rule."""
    assert psf.IS_ADVISORY is True
    assert psf.OUTSIDE_RISKPOLICY is True
    assert psf.EVIDENCE_LEVEL == "L0"


def test_execution_domain_is_never_imported():
    """Invariant #6: read-only research code must not reach the execution package."""
    src = (ROOT / "scripts" / "edge_periodic_schedule_frontier.py").read_text()
    # The prose says the words on purpose ("never imports spa_core.execution"), so the
    # check must look at IMPORT STATEMENTS, not at the file as a blob of text.
    offenders = [
        ln for ln in src.splitlines()
        if ln.lstrip().startswith(("import ", "from ")) and "execution" in ln
    ]
    assert offenders == []
    assert "LLM_FORBIDDEN" in src


# ── the schedule ─────────────────────────────────────────────────────────────────
def test_phases_partition_the_day_axis_exactly():
    """Mutation: an off-by-one in the phase formula leaves some days unreachable by ANY
    phase, which silently biases every band in the file."""
    n_slots = 137
    for k in (1, 2, 3, 5, 20, 90):
        got = []
        for p in range(k):
            got.extend(psf.phase_days(n_slots, k, p))
        assert sorted(got) == list(range(1, n_slots))
        assert len(got) == len(set(got))


def test_phase_zero_starts_at_the_first_movable_day():
    """Mutation: (j-1) % k -> j % k. The partition survives that change, so only this
    anchor catches it: phase 0 must be allowed to move on the FIRST day it could."""
    assert psf.phase_days(50, 5, 0)[0] == 1
    assert psf.phase_days(50, 5, 1)[0] == 2
    assert psf.phase_days(50, 7, 0)[:3] == [1, 8, 15]


def test_phase_days_rejects_impossible_arguments():
    """Mutation: silent clamping instead of refusal. A clamped phase would quietly measure
    a different arm than the table header claims."""
    with pytest.raises(ValueError):
        psf.phase_days(50, 0, 0)
    with pytest.raises(ValueError):
        psf.phase_days(50, 5, 5)
    with pytest.raises(ValueError):
        psf.phase_days(50, 5, -1)


def test_k1_is_the_daily_arm_cell_for_cell(fixture_panel):
    """Mutation: the k=1 arm drops or adds a trading day. k=1 must BE today's arm — the
    same object #81/#82 published — otherwise the whole frontier is anchored to nothing."""
    dates, book_rets = fixture_panel
    n = len(dates)
    for mode in ("h5", "h60", "mhfc"):
        mine = psf.periodic_scored(book_rets, n, mode, 1, 0)
        theirs, _sw = cit.cit_history(book_rets, n, mode, float("inf"), 0.0)
        assert mine.hist == theirs
        assert mine.net(96.0) == pytest.approx(
            cit.score(theirs, book_rets).net(96.0), abs=1e-15
        )


def test_larger_k_trades_strictly_less(fixture_panel):
    """Mutation: the schedule stops binding (e.g. `allowed` built from the wrong index),
    in which case every k would trade like k=1 and the frontier would be flat by defect."""
    dates, book_rets = fixture_panel
    n = len(dates)
    tos = []
    for k in (1, 5, 20, 90):
        s = psf.periodic_scored(book_rets, n, "h20", k, 0)
        tos.append(s.turnover_per_year(len(s.gross)))
    assert tos == sorted(tos, reverse=True)
    assert tos[0] > tos[-1] * 3


# ── the ladder ───────────────────────────────────────────────────────────────────
class _FakeScored:
    """A hand-built two-tranche family with KNOWN divergence, so the averaging rule is
    checked against arithmetic rather than against itself."""

    def __init__(self, rets, turns):
        self._rets, self.turns = list(rets), list(turns)
        self.gross, self.hist, self.switches = list(rets), [], -1

    def net(self, c):  # cost already folded in by the caller of this fake
        return list(self._rets)


def test_ladder_is_equity_weighted_not_a_plain_mean_of_returns():
    """Mutation: `sum(nets)/k` instead of the equity-weighted combination.

    The two agree only while the tranches have equal equity. Here tranche A triples and
    tranche B halves, so the plain mean is visibly the wrong number — and the ladder must
    equal the ratio of summed equities, which is what a real book of two sleeves does.
    """
    a = _FakeScored([0.10] * 12, [0.0] * 12)
    b = _FakeScored([-0.05] * 12, [0.0] * 12)
    lad = psf.ladder_at_cost([a, b], 0.0)

    ea = eb = 1.0
    prev = 2.0
    expected = []
    for t in range(12):
        ea *= 1.10
        eb *= 0.95
        expected.append((ea + eb) / prev - 1.0)
        prev = ea + eb
    assert lad.net == pytest.approx(expected, abs=1e-12)

    plain = [(0.10 + -0.05) / 2] * 12
    assert lad.net[-1] != pytest.approx(plain[-1], abs=1e-6)


def test_ladder_turnover_is_measured_equity_weighted_not_assumed():
    """Mutation: report a tranche's turnover, or the flat mean, as the ladder's.

    The ladder's toll is the equity-weighted mean of the tranches', and the weights drift
    as the tranches diverge. Asserting the flat mean would understate a diverged book.
    """
    a = _FakeScored([0.10] * 8, [2.0] * 8)
    b = _FakeScored([-0.05] * 8, [0.0] * 8)
    lad = psf.ladder_at_cost([a, b], 0.0)

    ea = eb = 1.0
    expected = []
    for t in range(8):
        expected.append((ea * 2.0 + eb * 0.0) / (ea + eb))
        ea *= 1.10
        eb *= 0.95
    assert lad.turn_per_day == pytest.approx(expected, abs=1e-12)
    assert lad.turn_per_day[-1] != pytest.approx(1.0, abs=1e-3)  # the flat mean


def test_ladder_of_one_phase_is_that_phase(fixture_panel):
    """Mutation: a stray 1/k or an off-by-one in the tranche loop. k=1 must be identity."""
    dates, book_rets = fixture_panel
    n = len(dates)
    s = psf.periodic_scored(book_rets, n, "h60", 1, 0)
    lad = psf.ladder_at_cost([s], 96.0)
    assert lad.net == pytest.approx(s.net(96.0), abs=1e-12)
    assert lad.turn_per_day == pytest.approx(list(s.turns), abs=1e-12)


def test_ladder_refuses_to_average_different_horizons():
    """Mutation: zip() silently truncating to the shortest tranche. A short tranche would
    make the ladder a different, shorter backtest wearing the same label."""
    a = _FakeScored([0.01] * 10, [0.0] * 10)
    b = _FakeScored([0.01] * 7, [0.0] * 7)
    with pytest.raises(ValueError):
        psf.ladder_at_cost([a, b], 0.0)
    with pytest.raises(ValueError):
        psf.ladder_at_cost([], 0.0)


def test_ruin_is_not_reported_as_a_win():
    """Mutation: drop the degeneracy guard. mh._apy() returns 0.0 for a bankrupt path, and
    0.0 BEATS a negative baseline Calmar — the exact trap that made #82's first run print
    '>10000 bps'. A wiped-out ladder must score -inf, never a number."""
    # A path that actually CROSSES zero: -120% on one day. A merely catastrophic path
    # (-90% every day) never does, and would leave the guard untested — the exact way a
    # positive control turns into decoration.
    dead = _FakeScored([-0.5] * 10 + [-1.2] + [0.01] * 10, [0.0] * 21)
    lad = psf.ladder_at_cost([dead], 0.0)
    row = psf.measure(lad.net, lad.turn_per_day, len(lad.net), base_calmar=1.0, switches=-1)
    assert math.isinf(row.dcal) and row.dcal < 0
    assert css._degenerate(lad.net) is True


# ── causality ────────────────────────────────────────────────────────────────────
def test_schedule_cannot_see_the_future(fixture_panel):
    """Mutation: any data-dependent term entering the schedule. The rule is a function of
    the day INDEX only, so perturbing the tail must leave the head bit-identical."""
    dates, book_rets = fixture_panel
    n = len(dates)
    cut = n // 2
    poisoned = {b: list(r) for b, r in book_rets.items()}
    for b in poisoned:
        for i in range(cut, n):
            poisoned[b][i] = 5.0

    clean = cit.scheduled_history(book_rets, n, "h20", psf.phase_days(n - 1, 7, 3))
    cit._CAND_CACHE.clear()
    dirty = cit.scheduled_history(poisoned, n, "h20", psf.phase_days(n - 1, 7, 3))
    cit._CAND_CACHE.clear()

    horizon = min(cut - 60, len(clean), len(dirty))
    assert horizon > 50
    assert clean[:horizon] == dirty[:horizon]


def test_expanding_tilt_is_causal(fixture_panel):
    """Mutation: the harness quietly builds the IN-SAMPLE STATIC twin where it claims the
    CAUSAL one (#67's whole lesson: the first reads as a triumph and is not a rule anybody
    could have run).

    This calls the HARNESS function. An earlier version of this test re-implemented the
    running mean locally and stayed GREEN through exactly that mutation — it was comparing
    its own copy with itself.
    """
    dates, book_rets = fixture_panel
    n = len(dates)
    cand = cit.candidates_for(book_rets, n, "h20")
    books = cand.book_ids

    base = psf.expanding_tilt_history(cand)
    assert len(base) == len(cand.weights)
    # day 1 of a causal running mean is the first candidate itself; the static twin is the
    # full-sample average and cannot be.
    assert base[0] == pytest.approx(cand.weights[0], abs=1e-12)

    class _Poisoned:
        book_ids = books
        mode = "h20"
        weights = [dict(w) for w in cand.weights]
        signals = cand.signals

    head = len(cand.weights) // 2
    for i in range(head, len(_Poisoned.weights)):
        _Poisoned.weights[i] = {books[0]: 1.0, **{b: 0.0 for b in books[1:]}}
    moved = psf.expanding_tilt_history(_Poisoned)

    assert base[:head] == moved[:head], "a LATER candidate moved an EARLIER weight"
    assert base[-1] != moved[-1], "the poison never reached the tail — test is inert"


def test_static_and_expanding_twins_are_different_objects(fixture_panel):
    """Mutation: both twins built from the same branch. If they coincide, every row that
    contrasts 'in-sample upper bound' with 'causal rule' is comparing a thing to itself."""
    dates, book_rets = fixture_panel
    cand = cit.candidates_for(book_rets, len(dates), "h20")
    stat = psf.static_tilt_history(cand)
    exp = psf.expanding_tilt_history(cand)
    assert len(stat) == len(exp)
    assert stat[0] != exp[0]
    assert len(set(tuple(sorted(w.items())) for w in stat)) == 1  # static is constant
    assert len(set(tuple(sorted(w.items())) for w in exp)) > 1    # causal one moves


def test_control_runner_wires_the_causal_twin_not_the_static_one(fixture_panel, capsys):
    """Mutation: `s_exp = static_tilt_history(cand)` at the CALL SITE.

    The twin functions can both be correct while the runner reports the wrong one, and
    every earlier test in this file would stay green — the defect lives in the wiring, not
    in the parts. So this one runs the actual control and reads what it published: the
    causal twin MOVES (non-zero turnover) and the static twin does not.
    """
    dates, book_rets = fixture_panel
    psf_res = psf.run_psf(dates, book_rets, "t", (1,))
    pld_res = psf.run_pld(dates, book_rets, psf_res, "t", (1,))
    out = psf.run_static_tilt_control(dates, book_rets, psf_res, pld_res, ["h20"], (1,))
    capsys.readouterr()
    static, expanding = out["h20"]["static"], out["h20"]["expanding"]
    assert static.to == pytest.approx(0.0, abs=1e-12), "a constant vector cannot trade"
    assert expanding.to > 1e-6, "the reported causal twin never trades — it is the static one"
    assert static.dcal != pytest.approx(expanding.dcal, abs=1e-9)


# ── controls must be what they claim ─────────────────────────────────────────────
def test_relabel_preserves_turnover_exactly(fixture_panel):
    """Mutation: a control that also changes turnover is not turnover-matched, and any
    p-value read off it is meaningless. RELABEL must move labels and nothing else."""
    dates, book_rets = fixture_panel
    n = len(dates)
    s = psf.periodic_scored(book_rets, n, "h20", 5, 0)
    books = sorted(book_rets)
    perm = books[1:] + books[:1]
    s2 = cit.score(css._relabel(s.hist, perm, books), book_rets, switches=-1)
    assert list(s2.turns) == pytest.approx(list(s.turns), abs=1e-15)
    assert s2.gross != pytest.approx(list(s.gross), abs=1e-9)


def test_random_ladder_control_uses_distinct_seeds_per_tranche(fixture_panel, capsys):
    """Mutation: `seed` instead of `seed * 1000 + i` in run_random_ladder_control.

    With one seed per outer draw all k tranches get the SAME days, so the 'random ladder'
    collapses to a single random phase and the control silently stops being a ladder. The
    check watches the REAL call site (memory: mutate the wiring, not the parts) — asserting
    the arithmetic alone would stay green while the caller passed the wrong thing.
    """
    dates, book_rets = fixture_panel
    seen = []
    real = cit.random_switch_days

    def spy(n_slots, n_switch, seed):
        seen.append(seed)
        return real(n_slots, n_switch, seed)

    cit.random_switch_days = spy
    try:
        psf.run_random_ladder_control(
            dates, book_rets,
            psf.run_psf(dates, book_rets, "t", (3,)),
            psf.run_pld(dates, book_rets, psf.run_psf(dates, book_rets, "t", (3,)), "t", (3,)),
            ["h20"], (3,), seeds=(0, 1),
        )
    finally:
        cit.random_switch_days = real
    capsys.readouterr()
    assert len(seen) == 2 * 3, seen
    assert len(set(seen[:3])) == 3, f"tranches of one draw share a seed: {seen[:3]}"
    assert len(set(seen)) == 6, seen


def test_panel_loader_refuses_instead_of_falling_back(tmp_path):
    """Mutation: the silent fixture fallback that made #79/#80 publish fixture numbers under
    a real-panel title. Absent panel must RAISE, always — this test needs no panel."""
    missing = tmp_path / "no_such_panel"
    with pytest.raises(FileNotFoundError):
        cit.load_real_panel(missing)


def test_shrinkage_line_endpoints_are_the_two_known_arms(fixture_panel):
    """Mutation: alpha wired backwards, or the 'equal weight' leg not actually equal.

    The line only means something if its ENDS are objects the registry already published:
    alpha=0 must be exact equal weight and alpha=1 must be today's arm, cell for cell. A
    reversed alpha would still print a smooth table and would compare the tilt against
    nothing.
    """
    dates, book_rets = fixture_panel
    cand = cit.candidates_for(book_rets, len(dates), "h20")
    books = cand.book_ids
    flat = 1.0 / len(books)

    zero = psf.shrinkage_history(cand, 0.0)
    assert all(
        all(w[b] == pytest.approx(flat, abs=1e-12) for b in books) for w in zero
    ), "alpha=0 is not equal weight — the line has no anchor"

    one = psf.shrinkage_history(cand, 1.0)
    for got, want in zip(one, cand.weights):
        assert got == pytest.approx({b: want.get(b, 0.0) for b in books}, abs=1e-12)

    # Pick a day where the arm is NOT already flat: during warm-up every signal is None and
    # the candidate IS equal weight, so on such a day every alpha coincides and the check
    # would pass on a broken implementation.
    half = psf.shrinkage_history(cand, 0.5)
    idx = next(
        i for i, w in enumerate(cand.weights)
        if max(w.get(b, 0.0) for b in books) - min(w.get(b, 0.0) for b in books) > 1e-6
    )
    assert half[idx] != pytest.approx(zero[idx], abs=1e-9)
    assert half[idx] != pytest.approx(one[idx], abs=1e-9)


def test_shrinkage_keeps_daily_turnover_unlike_the_tilt(fixture_panel):
    """The claim the record rests on: shrinkage is a CONCENTRATION knob, not a clock.

    Mutation: shrinkage implemented as a running average (i.e. accidentally re-deriving the
    tilt), which would make the control a copy of the thing it is supposed to falsify — and
    the record would read 'the line reaches the tilt' for a trivial reason.
    """
    dates, book_rets = fixture_panel
    n = len(dates)
    cand = cit.candidates_for(book_rets, n, "h20")
    shrunk = cit.score(psf.shrinkage_history(cand, 0.5), book_rets, switches=-1)
    tilted = cit.score(psf.expanding_tilt_history(cand), book_rets, switches=-1)
    to_shrunk = shrunk.turnover_per_year(len(shrunk.gross))
    to_tilt = tilted.turnover_per_year(len(tilted.gross))
    assert to_shrunk > to_tilt * 3, (
        f"shrinkage trades {to_shrunk:.2f}/yr and the tilt {to_tilt:.2f}/yr — if these are "
        "close, shrinkage has become a time-average and falsifies nothing"
    )


# ── the published anchor (real panel only) ───────────────────────────────────────
def test_real_panel_k1_reproduces_the_published_row():
    """Mutation: any drift in the inherited scoring path. #82 published, on this panel, for
    the lambda=inf arm: h60 netAPY 22.77% / maxDD -6.54% / Calmar 3.48, equal-weight
    17.62% / -5.44% / 3.24. PSF's k=1 IS that arm, so it must reproduce those cells."""
    dates, book_rets = _real_panel()
    n = len(dates)
    eq = psf.equal_weight_reference(book_rets, n, psf.CONVENTION_COST)
    assert eq.apy * 100 == pytest.approx(17.62, abs=0.01)
    assert eq.mdd * 100 == pytest.approx(-5.44, abs=0.01)
    assert eq.calmar == pytest.approx(3.24, abs=0.01)

    s = psf.periodic_scored(book_rets, n, "h60", 1, 0)
    row = psf.measure(s.net(psf.CONVENTION_COST), s.turns, len(s.gross), eq.calmar, s.switches)
    assert row.apy * 100 == pytest.approx(22.77, abs=0.01)
    assert row.mdd * 100 == pytest.approx(-6.54, abs=0.01)
    assert row.calmar == pytest.approx(3.48, abs=0.01)
    assert row.dcal == pytest.approx(0.25, abs=0.01)


def test_real_panel_ladder_turnover_tracks_a_single_phase():
    """The claim printed next to every ladder row: a k-tranche ladder does NOT trade more
    than one of its phases. Mutation: tranches rebalanced against each other (cross-sleeve
    rebalancing), which would multiply the toll while the table still said 'same turnover'.
    """
    dates, book_rets = _real_panel()
    n = len(dates)
    fam = psf.phase_family(book_rets, n, "h60", 20)
    lad = psf.ladder_at_cost(fam, psf.CONVENTION_COST)
    lad_to = lad.turnover_per_year(len(lad.net))
    phase_to = fam[0].turnover_per_year(len(fam[0].gross))
    assert lad_to == pytest.approx(phase_to, rel=0.25)
