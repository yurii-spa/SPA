"""Tests for registry ideas #56 (XCV, cross-criterion vote) and #57 (SST, signal staleness).

Both verdicts rest on PROPERTIES, and both are worthless if those properties drift:

  #56 concluded "pooling demotion criteria costs return" only because every jury row is
  comparable with #40's own numbers. That comparability is not a convention here, it is an
  IDENTITY: a one-member jury with j=1 must be the same function as `xsd.rank_demotion_flags`.
  If it ever stopped being that, every jury row would be measuring a different machine than the
  single-criterion rows it is scored against, and the entry's conclusion would become
  unfalsifiable without a single number changing. That identity is therefore the first test.

  #57's whole claim is that a lag is IMPLEMENTABLE — one-sided, strictly backward, never touching
  information that did not exist yet. The registry already owns a superficially similar object,
  `ecr.shifted_flags`, which rotates circularly and is deliberately non-causal. Confusing the two
  would turn a deployability map into a look-ahead backtest, so `test_lag_never_reads_the_future`
  is a positive control: it mutates a FUTURE flag and asserts no earlier lagged cell moves.

  The third property is the one that makes #57 useful rather than decorative: on the real panel
  M=10 and M=20 are indistinguishable at d=0 (ΔCalmar +5.06 vs +5.03) and separate sharply once
  the decision is late. That is pinned as a data-dependent test which SKIPS (never fails) when
  data/aggressive_lab is absent, because CI has no nightly books.

No literal dates. Every structural fixture is synthetic and built in-process, so this file behaves
identically in CI and on the host; only the three clearly-marked panel tests read data/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
PANEL_DIR = ROOT / "data" / "aggressive_lab"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


xcv = _load("edge_criterion_consensus")
xsd = _load("edge_cross_sectional_demotion")
ecr = _load("edge_capital_recycling")

needs_panel = pytest.mark.skipif(
    not PANEL_DIR.exists(),
    reason="nightly aggressive_lab books are runtime-only (data/ is gitignored) — absent in CI")


# ═════════════════════════════ fixtures ═════════════════════════════
BOOKS = ["a", "b", "c", "d"]
N = 8


def scores_of(cols: Sequence[Sequence[Optional[float]]]) -> Dict[str, List[Optional[float]]]:
    """`cols[i]` is the cross-section on day i, in BOOKS order."""
    return {b: [cols[i][j] for i in range(len(cols))] for j, b in enumerate(BOOKS)}


class _FakePanelScores:
    """Enough of a `dgo.Panel` for `vote_counts`, carrying pre-computed scores per criterion.

    Deliberately NOT the real panel: that one reads nightly artefacts from data/ which are absent
    in CI and different every day, and none of the structural properties below need a market. The
    criterion dispatcher is redirected here by the autouse fixture and only for this class, so the
    three data-dependent tests at the end still exercise the real dispatcher.
    """

    def __init__(self, **by_kind: Dict[str, List[Optional[float]]]) -> None:
        self.by_kind = dict(by_kind)
        self.books = list(BOOKS)
        self.n = len(next(iter(by_kind.values()))[BOOKS[0]])


_real_panel_scores = xcv.erd.panel_scores


@pytest.fixture(autouse=True)
def _wire_fake_panels(monkeypatch):
    def dispatch(panel, kind, lookback=xcv.LOOKBACK):
        if isinstance(panel, _FakePanelScores):
            return panel.by_kind[kind]
        return _real_panel_scores(panel, kind, lookback)

    monkeypatch.setattr(xcv.erd, "panel_scores", dispatch)
    yield


# a: always worst, b: second worst, c/d: fine — a deterministic, tie-free cross-section
S_MAIN = scores_of([[-3.0, -1.0, 2.0, 5.0]] * N)
# a second criterion that disagrees completely: d is worst, then c
S_OPPOSITE = scores_of([[5.0, 2.0, -1.0, -3.0]] * N)


# ═════════════════ #56 — the jury is the registry's own machine ═════════════════
def test_one_member_jury_is_byte_identical_to_idea40():
    """THE anchor of entry #56.

    A jury of one, convicting on one vote, must be the SAME FUNCTION as #40's rank state machine —
    not similar to it. Every jury row in the entry is scored against single-criterion rows produced
    by `xsd.rank_demotion_flags`; if the two machines diverged anywhere (re-admission counting,
    tie-breaking, the frozen-state branch), the comparison would be between two different rules and
    the verdict "pooling costs return" would be an artefact of the harness.
    """
    for m_days in (1, 2, 5, 20):
        votes, voters, _ = xcv.vote_counts(_FakePanelScores(main=S_MAIN), ("main",), k=2)
        mine = xcv.consensus_flags(votes, voters, 1, m_days)
        theirs = xsd.rank_demotion_flags(S_MAIN, 2, m_days)
        assert mine == theirs, f"jury-of-one diverged from #40 at M={m_days}"


def test_one_member_jury_identity_is_falsifiable():
    """Positive control for the test above: a jury of TWO disagreeing criteria must NOT reproduce
    #40, or the identity test would also pass on a module that ignored its jury entirely."""
    votes, voters, _ = xcv.vote_counts(_FakePanelScores(main=S_MAIN, opp=S_OPPOSITE), ("main", "opp"), k=2)
    mine = xcv.consensus_flags(votes, voters, 1, 1)
    assert mine != xsd.rank_demotion_flags(S_MAIN, 2, 1)


def test_union_is_a_superset_and_unanimity_a_subset_of_every_single_criterion():
    """j=1 is the union of the jurors' nominations and j=|jury| is their intersection.

    This is what makes the j axis readable as "how much agreement is required" rather than as an
    unlabelled knob, and it is the reason the entry can say a jury is never *between* the singles
    by accident: at the endpoints it is bounded by them by construction.
    """
    kinds = ("main", "opp")
    panel = _FakePanelScores(main=S_MAIN, opp=S_OPPOSITE)
    votes, voters, _ = xcv.vote_counts(panel, kinds, k=2)
    union = xcv.consensus_flags(votes, voters, 1, 1)
    unanimous = xcv.consensus_flags(votes, voters, 2, 1)
    for src, k_i in ((S_MAIN, "main"), (S_OPPOSITE, "opp")):
        single = xsd.rank_demotion_flags(src, 2, 1)
        for b in BOOKS:
            for i in range(N):
                if single[b][i]:
                    assert union[b][i], f"union missed a nomination by {k_i}"
                if unanimous[b][i]:
                    assert single[b][i], f"unanimity convicted without {k_i}"


@pytest.mark.parametrize("j", [1, 2, 3])
def test_conviction_is_monotone_in_j(j):
    """Raising the bar can only ever demote FEWER book-days (checked at M=1, where the flag is the
    membership itself and stickiness cannot mask a regression)."""
    panel = _FakePanelScores(a1=S_MAIN, a2=S_OPPOSITE, a3=S_MAIN)
    votes, voters, _ = xcv.vote_counts(panel, ("a1", "a2", "a3"), k=2)
    loose = xcv.consensus_flags(votes, voters, j, 1)
    strict = xcv.consensus_flags(votes, voters, j + 1, 1)
    for b in BOOKS:
        for i in range(N):
            if strict[b][i]:
                assert loose[b][i], "a stricter jury convicted where a looser one acquitted"


def test_inquorate_jury_freezes_the_state_instead_of_deciding():
    """Fail-CLOSED, and in BOTH directions.

    When fewer than j criteria can vote there is no evidence either way, so a demoted book stays
    demoted and an eligible book stays eligible. The failure this replays is the tempting one:
    treating "nobody voted to demote" as an acquittal, which silently re-admits a book on exactly
    the days the panel is least measurable.
    """
    votes = {b: [2, 0, 0] for b in BOOKS}
    votes["a"] = [2, 2, 2]
    quorum = [2, 0, 2]          # day 1 is inquorate for j=2
    out = xcv.consensus_flags(votes, quorum, 2, 1)
    assert out["a"] == [True, True, True]
    assert out["b"] == [True, True, False], "an inquorate day must not re-admit"


def test_abstaining_criterion_casts_no_vote_in_either_direction():
    """A day with k or fewer rankable books has no meaningful "worst k", so the criterion abstains
    — it does not nominate everybody, and it does not nominate nobody-but-count-as-present."""
    cols: List[List[Optional[float]]] = [[-3.0, -1.0, 2.0, 5.0], [None, None, None, 1.0]]
    member, ok = xcv.bottom_membership(scores_of(cols), k=2)
    assert ok == [True, False]
    assert [member[b][1] for b in BOOKS] == [False, False, False, False]
    assert [member[b][0] for b in BOOKS] == [True, True, False, False]


def test_jury_flip_control_nominates_the_best_books():
    """The sign-flipped control must select the TOP k, or "the jury carries information" would be
    an assertion rather than a measurement."""
    member, _ = xcv.bottom_membership(S_MAIN, k=2, worst_first=False)
    assert [member[b][0] for b in BOOKS] == [False, False, True, True]


def test_ties_break_by_book_name_so_the_report_is_reproducible():
    all_equal = scores_of([[1.0, 1.0, 1.0, 1.0]] * 2)
    member, _ = xcv.bottom_membership(all_equal, k=2)
    assert [member[b][0] for b in BOOKS] == [True, True, False, False]


@pytest.mark.parametrize("kwargs,msg", [
    (dict(j=0, m=1), "j"),
    (dict(j=1, m=0), "m_days"),
])
def test_degenerate_jury_parameters_are_refused(kwargs, msg):
    votes = {b: [0] * N for b in BOOKS}
    with pytest.raises(ValueError, match=msg):
        xcv.consensus_flags(votes, [1] * N, kwargs["j"], kwargs["m"])


def test_empty_jury_and_oversized_k_are_refused():
    with pytest.raises(ValueError, match="empty jury"):
        xcv.vote_counts(_FakePanelScores(main=S_MAIN), (), k=2)
    with pytest.raises(ValueError, match="whole panel"):
        xcv.bottom_membership(S_MAIN, k=len(BOOKS))
    with pytest.raises(ValueError, match="k must be"):
        xcv.bottom_membership(S_MAIN, k=0)


def test_votes_never_exceed_the_number_of_jurors_that_could_vote():
    panel = _FakePanelScores(main=S_MAIN, opp=S_OPPOSITE)
    votes, voters, _ = xcv.vote_counts(panel, ("main", "opp"), k=2)
    for b in BOOKS:
        for i in range(N):
            assert 0 <= votes[b][i] <= voters[i]


# ═════════════════════════════ #57 — the lag is implementable ═════════════════════════════
FLAGS = {b: [(i % 3 == 0) and b in ("a", "b") for i in range(N)] for b in BOOKS}


def test_zero_lag_is_the_identity():
    assert xcv.lagged_flags(FLAGS, 0) == FLAGS


@pytest.mark.parametrize("d", [1, 2, 3, 5])
def test_lag_shifts_by_exactly_d_days_and_starts_undecided(d):
    """Every cell must be the decision made exactly d days earlier, and the first d days — which
    precede any decision at all — must be reported as NOT demoted (the no-action default named in
    the entry, so the row's one optimistic corner is stated rather than hidden)."""
    out = xcv.lagged_flags(FLAGS, d)
    for b in BOOKS:
        assert out[b][:d] == [False] * d
        for i in range(d, N):
            assert out[b][i] == FLAGS[b][i - d]


def test_lag_never_reads_the_future():
    """POSITIVE CONTROL — the property that separates a latency row from a look-ahead backtest.

    `ecr.shifted_flags` rotates a path circularly and therefore leaks tomorrow into yesterday; a
    lag must not. Mutating the LAST day of the source may change nothing at or before the point
    where that day becomes visible, and nothing at all when the mutation lands past the horizon.
    """
    d = 3
    base = xcv.lagged_flags(FLAGS, d)
    tampered = {b: list(v) for b, v in FLAGS.items()}
    tampered["a"][N - 1] = not tampered["a"][N - 1]
    after = xcv.lagged_flags(tampered, d)
    assert after == base, "a change on the last day leaked backwards through the lag"

    rotated = ecr.shifted_flags(FLAGS, BOOKS, d)
    assert rotated != base, "the circular control must NOT coincide with the causal lag"


def test_negative_lag_is_refused_because_it_is_look_ahead():
    with pytest.raises(ValueError, match="negative lag"):
        xcv.lagged_flags(FLAGS, -1)
    with pytest.raises(ValueError, match="negative lag"):
        xcv.lagged_scores(S_MAIN, -1)


def test_stale_data_and_a_late_agent_are_the_same_portfolio_after_the_boundary():
    """"Our feed is d days old" and "our agent acts d days late" must not be two different numbers.

    Running the state machine on lagged SCORES and lagging the resulting FLAGS agree from the day
    the delayed machine has seen as much history as the prompt one — before that the delayed
    machine is still warming up, which is a boundary effect, not a modelling choice. Pinning it
    here is what lets the entry quote one latency budget instead of two.
    """
    d = 2
    late_flags = xcv.lagged_flags(xsd.rank_demotion_flags(S_MAIN, 2, 3), d)
    stale_flags = xsd.rank_demotion_flags(xcv.lagged_scores(S_MAIN, d), 2, 3)
    for b in BOOKS:
        assert late_flags[b][d:] == stale_flags[b][d:], f"{b}: stale data ≠ late action"


def test_lagged_scores_blank_the_warm_up_rather_than_inventing_it():
    out = xcv.lagged_scores(S_MAIN, 2)
    for b in BOOKS:
        assert out[b][:2] == [None, None]
        assert out[b][2:] == S_MAIN[b][:-2]


# ═════════════════════════ the two findings, pinned against the real panel ═════════════════════════
@needs_panel
def test_no_jury_beats_the_best_single_criterion_on_the_real_panel():
    """VERDICT OF #56, as an assertion rather than as prose.

    If some jury ever did clear the best single criterion, this test would go red and the registry
    entry would have to be rewritten — which is the point. It is scored on ΔCalmar AND on netAPY,
    because a jury that buys Calmar with turnover has not beaten anything.
    """
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)

    def score(flags):
        m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, flags, panel.n))
        return m["calmar"] - base["calmar"], m["net_apy_after_cost"]

    best = max(score(xsd.rank_demotion_flags(_real_panel_scores(panel, kind, xcv.LOOKBACK), 2, 20))
               for kind in xcv.KINDS)
    for k in (1, 2, 3):
        votes, voters, _ = xcv.vote_counts(panel, xcv.KINDS, k)
        for j in range(1, len(xcv.KINDS) + 1):
            for m_days in (1, 20):
                got = score(xcv.consensus_flags(votes, voters, j, m_days))
                assert got[0] < best[0] or got[1] < best[1], (
                    f"jury k={k} j={j} M={m_days} beat the best single criterion on BOTH axes "
                    f"({got} vs {best}) — entry #56's verdict no longer holds")


@needs_panel
def test_latency_separates_configurations_that_calmar_cannot():
    """VERDICT OF #57's most useful half.

    M=10 and M=20 are within 0.1 of each other at d=0. Along the lag axis — which is not a knob of
    the rule and cannot be tuned — M=20 holds its edge and M=10 does not. If that separation ever
    vanished, the entry's claim that a jagged d-axis detects overfit would be unsupported.
    """
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    stab = xcv.latency_stability(panel, k=2, ms=(10, 20))
    assert abs(stab[10]["d0"] - stab[20]["d0"]) < 0.5, "premise gone: d=0 no longer a near-tie"
    assert stab[20]["mean"] > stab[10]["mean"] + 1.0
    assert stab[20]["mean_step"] < stab[10]["mean_step"]


@needs_panel
def test_the_four_criteria_are_not_collinear_on_the_real_panel():
    """Why the jury cannot help: pooling averages ERRORS only when the jurors estimate one truth.

    Here they do not — pairwise Jaccard of the bottom-k spans 0.1% to 63%. The entry's mechanism
    section rests on that, so it is measured rather than asserted.
    """
    dgo = _load("edge_drift_gated_overlay")
    rows = xcv.criterion_agreement(dgo.Panel(), k=2)
    jaccards = [j for _, _, j, _ in rows]
    assert min(jaccards) < 0.05 and max(jaccards) < 0.90, (
        "the criteria have become near-duplicates — #56's mechanism section must be re-derived")

