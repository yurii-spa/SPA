"""Tests for registry ideas #58 (OCS, online criterion selection) and #59 (OIB, oracle bound).

Both verdicts are properties before they are numbers, and both die quietly if the properties drift:

  #58 concluded "the family's rule cannot be CHOSEN causally" — a statement that is only worth
  anything if the selector really is causal. One `[i]` written where `[i-1]` belongs would turn
  the entry into a look-ahead backtest that happens to lose, and nothing in the printed table
  would move enough to notice. `test_trailing_mean_never_reads_today` and
  `test_selector_ignores_the_future` are therefore positive controls: they mutate a FUTURE return
  and assert that no earlier decision moves. The oracle gets the mirror-image test — it MUST react
  to the future — so the two objects can never be silently interchanged.

  #59's whole claim is a RATIO, and a ratio is only readable if its two ends are the ends they
  claim to be. The ceiling must run the same machinery as the rule (otherwise it bounds a
  different rule), and the floor must preserve the rule's duty and turnover (otherwise the
  denominator is a different portfolio, not the same portfolio without information). Both are
  pinned: `test_ceiling_uses_the_published_machinery` and `test_chance_floor_preserves_duty`.

  The third property is the one that makes #59 more than a curiosity: `capture` REFUSES to divide
  when the ceiling is not above the floor. That refusal is what stopped this entry from printing
  "the rule captures 267 % of the ceiling" as an achievement instead of reading it as the
  diagnostic it is (M=20 cannot spend one-day foresight, so h≤5 is not a bound at all).

No literal dates. Every structural fixture is synthetic and built in-process, so this file behaves
identically in CI and on the host; only the clearly-marked verdict tests at the end read data/,
and they SKIP (never fail) when the nightly books are absent.
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


occ = _load("edge_criterion_choice")
xsd = _load("edge_cross_sectional_demotion")
ecr = _load("edge_capital_recycling")
erd = _load("edge_redundancy_demotion")

needs_panel = pytest.mark.skipif(
    not PANEL_DIR.exists(),
    reason="nightly aggressive_lab books are runtime-only (data/ is gitignored) — absent in CI")


# ═════════════════════════════ fixtures ═════════════════════════════
class SynthPanel:
    """Enough of a `dgo.Panel` for everything in this file: books, an axis and per-book returns.

    Deliberately NOT the real panel — that one reads nightly artefacts which are absent in CI and
    different every day, and none of the structural properties below need a market to hold.
    """

    def __init__(self, rets: Dict[str, List[float]]) -> None:
        self.rets = {b: list(v) for b, v in rets.items()}
        self.books = sorted(self.rets)
        self.axis = [f"d{i:04d}" for i in range(len(self.rets[self.books[0]]))]

    @property
    def n(self) -> int:
        return len(self.axis)

    def raw_portfolio(self) -> List[float]:
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]


def paths_of(**by_kind: Sequence[float]) -> Dict[str, List[float]]:
    return {k: list(v) for k, v in by_kind.items()}


ALT = ("alpha", "beta")           # two criteria, so "who leads" is readable by eye
N = 12


# ═════════════════════════ causality — the load-bearing property ═════════════════════════
def test_trailing_mean_is_a_half_open_window_ending_yesterday():
    path = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = occ.trailing_mean(path, 2)
    assert out[0] is None and out[1] is None          # window not full yet
    assert out[2] == pytest.approx((1.0 + 2.0) / 2)   # days 0..1, NOT 1..2
    assert out[3] == pytest.approx((2.0 + 3.0) / 2)
    assert out[4] == pytest.approx((3.0 + 4.0) / 2)


def test_trailing_mean_never_reads_today():
    """POSITIVE CONTROL: mutate day i; every trailing value up to and including i must be unmoved."""
    base = [0.1] * 8
    ref = occ.trailing_mean(base, 3)
    for i in range(len(base)):
        mutated = list(base)
        mutated[i] = 99.0
        got = occ.trailing_mean(mutated, 3)
        for j in range(i + 1):
            assert got[j] == ref[j], f"mutating day {i} moved the trailing value at day {j}"


def test_selector_ignores_the_future():
    """POSITIVE CONTROL on the whole selector: a later return may not change an earlier choice."""
    base = paths_of(alpha=[0.01] * N, beta=[0.0] * N)
    ref = occ.leader_path(base, ALT, window=3)
    bumped = paths_of(alpha=[0.01] * N, beta=[0.0] * N)
    bumped["beta"][N - 1] = 10.0
    got = occ.leader_path(bumped, ALT, window=3)
    assert got[:N - 1] == ref[:N - 1]


def test_oracle_leaders_DO_read_the_future():
    """The mirror image: if this ever stopped failing the causal test, the two would be one object."""
    base = paths_of(alpha=[0.01] * N, beta=[0.0] * N)
    ref = occ.oracle_leaders(base, ALT, horizon=3)
    bumped = paths_of(alpha=[0.01] * N, beta=[0.0] * N)
    bumped["beta"][5] = 10.0
    got = occ.oracle_leaders(bumped, ALT, horizon=3)
    assert got != ref
    assert got[3] == "beta" and ref[3] == "alpha"      # day 3 sees day 5 through h=3


def test_forward_scores_include_today_and_nothing_before_it():
    panel = SynthPanel({"a": [1.0, 2.0, 3.0, 4.0], "b": [0.0, 0.0, 0.0, 0.0]})
    sc = occ.forward_scores(panel, 2)
    assert sc["a"][0] == pytest.approx((1.0 + 2.0) / 2)   # [t, t+2) — day t is INSIDE
    assert sc["a"][2] == pytest.approx((3.0 + 4.0) / 2)
    assert sc["a"][3] == pytest.approx(4.0)               # truncated tail, not None

    mutated = SynthPanel({"a": [9.0, 2.0, 3.0, 4.0], "b": [0.0, 0.0, 0.0, 0.0]})
    assert occ.forward_scores(mutated, 2)["a"][2] == pytest.approx(sc["a"][2])


# ═════════════════════════ the selector's state machine ═════════════════════════
def test_hold_1_is_exactly_the_trailing_argmax():
    """The identity that makes every OCS row comparable with the single-criterion rows."""
    alpha = [0.02, 0.02, 0.02, -0.05, -0.05, -0.05, 0.02, 0.02]
    beta = [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]
    paths = paths_of(alpha=alpha, beta=beta)
    led = occ.leader_path(paths, ALT, window=2, hold=1)
    trail = {c: occ.trailing_mean(paths[c], 2) for c in ALT}
    for i in range(len(alpha)):
        ranked = [c for c in ALT if trail[c][i] is not None]
        if not ranked:
            assert led[i] is None
            continue
        assert led[i] == sorted(ranked, key=lambda c: (-float(trail[c][i]), c))[0]


def test_hold_delays_the_switch_by_exactly_hold_days():
    alpha = [0.02] * 4 + [-0.05] * 8
    beta = [0.0] * 12
    paths = paths_of(alpha=alpha, beta=beta)
    fast = occ.leader_path(paths, ALT, window=2, hold=1)
    slow = occ.leader_path(paths, ALT, window=2, hold=3)
    first_fast = next(i for i, c in enumerate(fast) if c == "beta")
    first_slow = next(i for i, c in enumerate(slow) if c == "beta")
    assert first_slow == first_fast + 2, (first_fast, first_slow)   # H=3 needs 3 leading days


def test_warmup_backs_nobody_and_that_means_equal_weight():
    panel = SynthPanel({b: [0.001] * N for b in ("a", "b", "c", "d")})
    paths = paths_of(alpha=[0.01] * N, beta=[0.0] * N)
    led = occ.leader_path(paths, ALT, window=4)
    assert led[:4] == [None] * 4
    by_kind = {c: {b: [0.5] * N for b in panel.books} for c in ALT}
    w = occ.selected_weights(panel, by_kind, led)
    for b in panel.books:
        assert w[b][0] == pytest.approx(1.0 / len(panel.books))   # raw equal weight, not 0.5
        assert w[b][N - 1] == pytest.approx(0.5)                  # backed criterion's weight


def test_anti_selector_is_the_sign_flip():
    paths = paths_of(alpha=[0.02] * N, beta=[0.0] * N)
    assert occ.leader_path(paths, ALT, window=3)[-1] == "alpha"
    assert occ.leader_path(paths, ALT, window=3, best=False)[-1] == "beta"


def test_selected_weights_take_the_backed_criterion_verbatim():
    panel = SynthPanel({b: [0.0] * 3 for b in ("a", "b")})
    by_kind = {"alpha": {"a": [1.0, 1.0, 1.0], "b": [0.0, 0.0, 0.0]},
               "beta": {"a": [0.0, 0.0, 0.0], "b": [1.0, 1.0, 1.0]}}
    w = occ.selected_weights(panel, by_kind, ["alpha", "beta", "alpha"])
    assert [w["a"][i] for i in range(3)] == [1.0, 0.0, 1.0]
    assert [w["b"][i] for i in range(3)] == [0.0, 1.0, 0.0]


def test_a_selector_with_no_evidence_refuses_rather_than_guesses():
    paths = paths_of(alpha=[0.01] * 3, beta=[0.0] * 3)
    assert occ.leader_path(paths, ALT, window=10) == [None, None, None]


# ═════════════════════════ controls keep what they promise to keep ═════════════════════════
def test_permuted_leaders_keep_the_spells_and_destroy_only_the_identity():
    led = ["alpha"] * 5 + ["beta"] * 3 + [None] * 2 + ["alpha"] * 2
    out = occ.permuted_leaders(led, ALT, seed=1)
    assert [c is None for c in out] == [c is None for c in led]
    switches = lambda v: [i for i in range(1, len(v))                       # noqa: E731
                          if v[i] is not None and v[i - 1] is not None and v[i] != v[i - 1]]
    assert switches(out) == switches(led)
    assert len(set(c for c in out if c)) == len(set(c for c in led if c))


def test_rotated_leaders_are_circular_and_keep_the_census():
    led = ["alpha", "alpha", "beta", None]
    out = occ.rotated_leaders(led, 1)
    assert out == ["alpha", "beta", None, "alpha"]
    assert sorted(map(str, out)) == sorted(map(str, led))
    assert occ.rotated_leaders(led, len(led)) == led


def test_chance_floor_preserves_duty():
    """The denominator must be the SAME portfolio minus information, not a different portfolio."""
    flags = {"a": [True, False, False, True], "b": [False, True, False, False],
             "c": [False, False, True, False], "d": [False, False, False, False]}
    books = sorted(flags)
    duty = sum(1 for b in books for x in flags[b] if x)
    for seed in range(5):
        perm = ecr.permuted_flags(flags, books, seed)
        assert sum(1 for b in books for x in perm[b] if x) == duty


# ═════════════════════════ the ratio refuses when it must ═════════════════════════
def test_capture_refuses_a_non_positive_denominator():
    assert occ.capture(rule=2.0, oracle=1.0, floor=1.0) is None      # ceiling == floor
    assert occ.capture(rule=2.0, oracle=0.5, floor=1.0) is None      # ceiling BELOW floor
    assert occ.capture(rule=2.0, oracle=3.0, floor=1.0) == pytest.approx(0.5)


def test_capture_above_one_is_reported_not_clipped():
    """A rule beating its own ceiling is a DIAGNOSTIC (the machine cannot spend the foresight).

    Clipping it to 100% would have hidden exactly the finding #59 is built on, so the function
    must return the honest number and let the report explain it.
    """
    assert occ.capture(rule=5.0, oracle=2.0, floor=1.0) == pytest.approx(4.0)


# ═════════════════════════ refusals (fail-CLOSED, not fail-quiet) ═════════════════════════
@pytest.mark.parametrize("call", [
    lambda: occ.trailing_mean([0.0, 1.0], 0),
    lambda: occ.leader_path(paths_of(alpha=[0.0], beta=[0.0]), ALT, window=1, hold=0),
    lambda: occ.leader_path(paths_of(alpha=[0.0]), (), window=1),
    lambda: occ.oracle_leaders(paths_of(alpha=[0.0]), ("alpha",), horizon=0),
    lambda: occ.forward_scores(SynthPanel({"a": [0.0]}), 0),
])
def test_degenerate_configurations_raise(call):
    with pytest.raises(ValueError):
        call()


# ═════════════════════════ persistence is measured, not asserted ═════════════════════════
def test_majority_null_is_the_honest_baseline():
    """When one criterion wins every forward window, a predictor reading nothing scores 1.0.

    The whole verdict of #58 rests on comparing the selector's hit-rate with THIS number rather
    than with 1/len(kinds); if `majority` ever silently became the coin again, the entry would
    read as "the selector beats chance" — which is true and irrelevant.
    """
    paths = paths_of(alpha=[0.01] * 40, beta=[0.0] * 40)
    p = occ.leadership_persistence(paths, ALT, window=5)
    assert p["chance"] == pytest.approx(0.5)
    assert p["majority"] == pytest.approx(1.0)
    assert p["forward_hit"] <= p["majority"] + 1e-12
    assert p["day_persistence"] == pytest.approx(1.0)


def test_switch_count_is_counted_on_the_backed_state_not_the_ranking():
    """`hold` exists to reduce switching; if the count read the ranking it could never show that."""
    alpha = ([0.02] * 3 + [-0.02] * 3) * 8
    paths = paths_of(alpha=alpha, beta=[0.0] * len(alpha))
    fast = occ.leadership_persistence(paths, ALT, window=2, hold=1)["switches_yr"]
    slow = occ.leadership_persistence(paths, ALT, window=2, hold=5)["switches_yr"]
    assert slow < fast


# ═════════════════════════ the two entries measure the published machine ═════════════════════════
@needs_panel
def test_criterion_weights_reproduce_the_published_single_rules():
    """IDENTITY: every OCS row must choose among the registry's OWN rows, not among lookalikes."""
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    by_kind = occ.criterion_weights(panel, occ.REF_K, occ.REF_M)
    for kind in occ.KINDS:
        want = ecr.alloc_recycle(
            panel.books,
            xsd.rank_demotion_flags(erd.panel_scores(panel, kind, occ.LOOKBACK),
                                    occ.REF_K, occ.REF_M),
            panel.n)
        for b in panel.books:
            assert by_kind[kind][b] == want[b]


@needs_panel
def test_ceiling_uses_the_published_machinery():
    """The oracle differs from #40 in its SCORES and in nothing else — same k, M, allocator."""
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    fs = occ.forward_scores(panel, 20)
    want = ecr.alloc_recycle(panel.books,
                             xsd.rank_demotion_flags(fs, occ.REF_K, occ.REF_M), panel.n)
    rows = dict((name.strip(), w) for name, w, _ in
                occ._oib_rows(panel, occ.REF_K, (occ.REF_M,), (20,)))
    got = rows[f"[LOOK-AHEAD] oracle h=20 M={occ.REF_M}"]
    for b in panel.books:
        assert got[b] == want[b]


@needs_panel
def test_verdict_58_no_causal_selector_beats_the_best_single():
    """VERDICT GUARD for #58. A failure here is a FINDING to re-measure, never a test to relax.

    The panel is regenerated nightly, so this is deliberately qualitative: it asserts the ORDER
    the entry published (best single ≥ best selector cell), not any of its numbers.
    """
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    by_kind = occ.criterion_weights(panel, occ.REF_K, occ.REF_M)
    paths = {c: occ.weights_returns(panel, by_kind[c]) for c in occ.KINDS}
    best_single = max(ecr.portfolio_metrics(panel, by_kind[c])["calmar"] for c in occ.KINDS)
    best_cell = max(
        ecr.portfolio_metrics(panel, occ.selected_weights(
            panel, by_kind, occ.leader_path(paths, occ.KINDS, e, h)))["calmar"]
        for e in occ.EVAL_WINDOWS for h in occ.HOLDS)
    assert best_cell <= best_single, (best_cell, best_single)


@needs_panel
def test_verdict_59_stickiness_not_information_binds_the_short_horizon():
    """VERDICT GUARD for #59: with M=20, PERFECT one-day foresight loses to the causal rule.

    This is the structural claim of the entry — the rule shape cannot spend short-horizon
    information — and it is exactly the claim a future refactor of the state machine would break
    without moving anything else. Qualitative on purpose (an inequality, not a number).
    """
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    rule = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books,
        xsd.rank_demotion_flags(erd.panel_scores(panel, "drift", occ.LOOKBACK),
                                occ.REF_K, occ.REF_M), panel.n))
    oracle = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books,
        xsd.rank_demotion_flags(occ.forward_scores(panel, 1), occ.REF_K, occ.REF_M), panel.n))
    assert oracle["apy"] < rule["apy"], (oracle["apy"], rule["apy"])


@needs_panel
def test_anti_oracle_is_worse_than_raw():
    """Direction sanity: demoting the books that are ABOUT to win must hurt. If it ever stops
    hurting, the sign of the whole rank machinery is wrong and every entry #35–#59 is affected."""
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    anti = ecr.portfolio_metrics(panel, ecr.alloc_recycle(
        panel.books,
        xsd.rank_demotion_flags(occ.forward_scores(panel, 60), occ.REF_K, occ.REF_M,
                                worst_first=False), panel.n))
    assert anti["apy"] < base["apy"]
