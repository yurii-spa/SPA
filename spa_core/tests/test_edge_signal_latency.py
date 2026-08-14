"""Tests for registry ideas #51 (SLT — signal latency tax) and #52 (SFP — stale-feed policy).

Both ideas are claims about BEHAVIOUR UNDER BAD DATA, so every one of them is pinned here in both
directions: a test that would also pass on a broken module is not evidence. The four fail-policies
of #52 are deliberately exercised on ONE fixture that separates all four — with the same scores and
the same single masked cell, `open`, `carry`, `closed_book` and `closed_panel` must each produce a
DIFFERENT demotion set, or the entry is comparing four names for one behaviour.

The load-bearing equivalence — with nothing missing, every policy must reproduce
`xsd.rank_demotion_flags` exactly — is what keeps this module from quietly becoming a different
rule than the one nineteen registry entries measured.

No literal dates: every fixture is a synthetic array, and the tests that need the real panel skip
when its files are absent (nightly artefacts, gitignored, absent in CI).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


slt = _load("edge_signal_latency")
xsd = _load("edge_cross_sectional_demotion")
cfpt = _load("edge_calm_fp_tax")

L = 10  # short lookback keeps fixtures readable; the module's default is 60


# ───────────────────────────── fixtures ─────────────────────────────
def _flat_scores(n: int = 6):
    """Four books whose ranking never changes: `a` is the worst on every single day."""
    return {"a": [0.0] * n, "b": [1.0] * n, "c": [2.0] * n, "d": [3.0] * n}


def _no_mask(scores):
    n = len(next(iter(scores.values())))
    return {b: [False] * n for b in scores}


def _wave(n: int, period: int, amp: float = 0.01, phase: float = 0.0):
    return [amp * math.sin(2 * math.pi * (i + phase) / period) for i in range(n)]


class _FakePanel:
    """Duck-typed `dgo.Panel` — enough for the score/allocator/metric path, no data/ needed."""

    def __init__(self, rets):
        self.books = sorted(rets)
        self.rets = {b: list(rets[b]) for b in self.books}
        self.n = len(self.rets[self.books[0]])
        self.axis = [f"d{i:04d}" for i in range(self.n)]

    def raw_portfolio(self):
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]


# ═════════════════════════════ #51 — lagging a signal ═════════════════════════════
def test_lag_zero_returns_the_signal_unchanged():
    """τ=0 must be the identity, or every ΔCalmar in the entry is measured against a moved base."""
    sc = {"a": [1.0, 2.0, None, 4.0], "b": [None, 1.0, 1.0, 1.0]}
    assert slt.lag_scores(sc, 0) == sc


def test_lag_shifts_by_exactly_tau_and_refuses_to_rank_before_the_value_exists():
    sc = {"a": [1.0, 2.0, 3.0, 4.0, 5.0]}
    out = slt.lag_scores(sc, 2)
    assert out["a"][:2] == [None, None], "a value was invented for days before the feed had one"
    assert out["a"][2:] == [1.0, 2.0, 3.0], "the delay is not exactly τ days"
    # and the wrong shift must NOT satisfy the same assertion — the check above is not vacuous
    assert slt.lag_scores(sc, 3)["a"][3:] == [1.0, 2.0]


def test_negative_lag_reads_the_future_and_runs_out_at_the_end():
    """The LOOK-AHEAD control: τ<0 must genuinely use tomorrow's value, else it controls nothing."""
    sc = {"a": [1.0, 2.0, 3.0]}
    out = slt.lag_scores(sc, -1)
    assert out["a"] == [2.0, 3.0, None]


def test_lag_never_invents_a_value_that_was_not_in_the_signal():
    sc = {"a": [0.5, -1.5, 7.0, None]}
    for tau in (-2, -1, 0, 1, 2, 5):
        seen = [v for v in slt.lag_scores(sc, tau)["a"] if v is not None]
        assert set(seen) <= {0.5, -1.5, 7.0}, f"τ={tau} fabricated a score"


def test_lag_refuses_ragged_series():
    with pytest.raises(ValueError):
        slt.lag_scores({"a": [1.0, 2.0], "b": [1.0]}, 1)


def test_lag_flags_refuses_a_negative_delay():
    """A decision cannot reach the book before it is taken; the look-ahead direction is for
    SCORES only, where it is an explicitly labelled control."""
    with pytest.raises(ValueError):
        slt.lag_flags({"a": [True, False]}, -1)


def test_a_delay_commutes_with_the_causal_state_machine():
    """#51's structural claim: «the feed is τ late» and «our order is τ late» are ONE number.

    Pinned on a synthetic panel whose ranking genuinely rotates, so the equality is a property of
    the machine and not of a signal that never changes its mind.
    """
    n = 80
    sc = {"a": _wave(n, 7), "b": _wave(n, 11, phase=3.0), "c": _wave(n, 13), "d": _wave(n, 5)}
    for k, m_days in ((1, 1), (2, 5)):
        base = xsd.rank_demotion_flags(sc, k, m_days)
        for tau in (1, 2, 5):
            lag_in = xsd.rank_demotion_flags(slt.lag_scores(sc, tau), k, m_days)
            lag_out = slt.lag_flags(base, tau)
            for b in base:
                assert lag_in[b][tau:] == lag_out[b][tau:], f"k={k} M={m_days} τ={tau} book {b}"


def test_the_commutation_test_would_notice_a_wrong_shift():
    """Positive control for the test above: comparing against τ+1 must FAIL, otherwise the
    equality is being satisfied by a signal too sleepy to distinguish anything."""
    n = 80
    sc = {"a": _wave(n, 7), "b": _wave(n, 11, phase=3.0), "c": _wave(n, 13), "d": _wave(n, 5)}
    base = xsd.rank_demotion_flags(sc, 1, 1)
    lag_in = xsd.rank_demotion_flags(slt.lag_scores(sc, 2), 1, 1)
    wrong = slt.lag_flags(base, 3)
    assert any(lag_in[b][3:] != wrong[b][3:] for b in base)


def test_flag_agreement_ignores_the_warmup_and_counts_every_later_cell():
    a = {"x": [True, True, False, False]}
    b = {"x": [False, True, True, False]}
    assert slt.flag_agreement(a, b, skip=0) == pytest.approx(0.5)
    assert slt.flag_agreement(a, b, skip=1) == pytest.approx(2 / 3)
    assert slt.flag_agreement(a, a, skip=0) == pytest.approx(1.0)


# ═════════════════════════════ #52 — outage process ═════════════════════════════
def test_outage_rate_lands_on_the_requested_steady_state():
    """If the injected outage rate does not match the requested one, the whole rate axis of #52
    is mislabelled and every policy is being compared at the wrong x."""
    n, books = 4000, ["a", "b", "c"]
    for rate in (0.05, 0.20):
        got = []
        for seed in range(8):
            m = slt.outage_mask(books, n, rate, seed=seed, warmup=0)
            got.append(sum(1 for b in books for v in m[b] if v) / (len(books) * n))
        mean = sum(got) / len(got)
        assert abs(mean - rate) < 0.02, f"requested {rate}, injected {mean:.3f}"


def test_outages_arrive_in_runs_not_as_independent_coin_flips():
    """A day-by-day coin flip is a much easier failure than the one production poses; the mean run
    length must be near the requested one, and clearly above 1."""
    m = slt.outage_mask(["a"], 20000, 0.10, seed=3, mean_run=3.0, warmup=0)["a"]
    runs, cur = [], 0
    for v in m:
        if v:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    assert runs, "no outage at all was injected"
    mean_run = sum(runs) / len(runs)
    assert 2.4 < mean_run < 3.6, f"mean run {mean_run:.2f} is not the requested 3 days"


def test_nothing_is_masked_during_the_warmup():
    m = slt.outage_mask(["a", "b"], 200, 0.5, seed=1, warmup=60)
    assert not any(m[b][i] for b in m for i in range(60))
    assert any(m[b][i] for b in m for i in range(60, 200)), "the mask never fires at all"


def test_zero_rate_masks_nothing_and_an_impossible_rate_is_refused():
    m = slt.outage_mask(["a"], 100, 0.0, seed=1, warmup=0)
    assert not any(m["a"])
    with pytest.raises(ValueError):
        slt.outage_mask(["a"], 100, 1.0, seed=1)
    with pytest.raises(ValueError):
        slt.outage_mask(["a"], 100, -0.1, seed=1)
    with pytest.raises(ValueError):
        slt.outage_mask(["a"], 100, 0.1, seed=1, mean_run=0.5)


# ═════════════════════════════ #52 — the four policies ═════════════════════════════
@pytest.mark.parametrize("policy", slt.POLICIES)
def test_every_policy_reduces_to_the_shipped_rule_when_nothing_is_missing(policy):
    """THE equivalence. If this ever fails, #52 is measuring a rule the registry never measured."""
    n = 80
    sc = {"a": _wave(n, 7), "b": _wave(n, 11, phase=3.0), "c": _wave(n, 13), "d": _wave(n, 5)}
    for k, m_days in ((1, 1), (2, 5), (3, 20)):
        expected = xsd.rank_demotion_flags(sc, k, m_days)
        got = slt.policy_flags(sc, _no_mask(sc), k, m_days, policy)
        assert got == expected, f"{policy} diverges from the shipped rule at k={k} M={m_days}"


def test_the_four_policies_genuinely_disagree_on_one_masked_cell():
    """One fixture, one dark cell, four different answers — otherwise #52 compares four names.

    Setup (k=1, M=1). `a` is the worst book on days 0–1 and is demoted. On day 2 `c` dips below it,
    so `c` takes the demotion and `a` comes back. On day 3 `a`'s feed goes dark, its true score
    jumps to the BEST on the panel (invisibly to us), and among the books we CAN see the worst is
    now `b`. Each policy therefore has a different day-3 answer, and each answer is a defensible
    reading of the same missing cell.
    """
    sc = {"a": [0.0, 0.0, 0.0, 9.0, 0.0, 0.0],
          "b": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
          "c": [2.0, 2.0, -1.0, 2.0, 2.0, 2.0],
          "d": [3.0, 3.0, 3.0, 3.0, 3.0, 3.0]}
    mask = _no_mask(sc)
    mask["a"][3] = True
    demoted_on_day2 = {"c"}

    out = {p: slt.policy_flags(sc, mask, 1, 1, p) for p in slt.POLICIES}
    day3 = {p: {b for b in sc if out[p][b][3]} for p in slt.POLICIES}

    # open: unmeasured ⇒ unrankable ⇒ PROTECTED; the worst VISIBLE book takes the demotion
    assert day3["open"] == {"b"}

    # carry: ranks on the last known score (0.0 — still the worst), so `a` is demoted. This is what
    # separates it from `open`, and it is also what makes it WRONG here: the book it demotes is,
    # unknowably, the best one that day.
    assert day3["carry"] == {"a"}

    # closed_book: unmeasured ⇒ not eligible ⇒ `a` demoted, AND the rank rule still runs over the
    # books it can see, so `b` (worst of the visible) is demoted too
    assert day3["closed_book"] == {"a", "b"}

    # closed_panel: the cross-section is incomplete ⇒ abstain ⇒ yesterday's state, verbatim
    assert day3["closed_panel"] == demoted_on_day2
    assert all(out["closed_panel"][b][3] == out["closed_panel"][b][2] for b in sc)

    # and the four answers are not the same object dressed up four ways
    signatures = {p: tuple(tuple(out[p][b]) for b in sorted(sc)) for p in slt.POLICIES}
    assert len(set(signatures.values())) == 4, "two policies produced identical flag paths"


def test_open_policy_walks_a_dark_book_back_to_full_weight():
    """The behaviour the shipped code has today, stated as a test: an outage does not merely fail
    to demote a book — it also accumulates re-admission credit for one that is already demoted."""
    sc = _flat_scores(n=8)
    mask = _no_mask(sc)
    for i in (3, 4):
        mask["a"][i] = True
    out = slt.policy_flags(sc, mask, 1, 2, "open")       # M=2: two clean days to come back
    assert out["a"][:3] == [True, True, True]
    assert out["a"][4] is False, "two dark days did not re-admit the book the feed cannot see"


def test_closed_panel_freezes_the_counters_and_delays_re_admission_by_exactly_the_dark_days():
    """Abstaining must hold the STATE, not merely the output: a dark day may not count as
    evidence of good behaviour, or fail-CLOSED silently becomes fail-open with extra steps."""
    n = 10
    sc = {"a": [0.0] * n, "b": [1.0] * n, "c": [2.0] * n}
    sc["a"] = [0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]   # `a` becomes good from day 3
    clean = slt.policy_flags(sc, _no_mask(sc), 1, 3, "closed_panel")
    first_clean = clean["a"].index(False)

    mask = _no_mask(sc)
    mask["c"][4] = True                                  # one dark day, on ANOTHER book
    dark = slt.policy_flags(sc, mask, 1, 3, "closed_panel")
    assert dark["a"].index(False) == first_clean + 1, "the dark day was counted as a good day"


def test_carry_uses_the_last_known_score_and_never_a_fabricated_zero():
    """A book that has never reported cannot be carried; it must stay unrankable, not rank at 0.0
    — the same fail-CLOSED rule the rank machine already applies to a warming-up book."""
    sc = {"a": [None, None, 1.0, 1.0], "b": [0.5, 0.5, 0.5, 0.5],
          "c": [2.0, 2.0, 2.0, 2.0], "d": [3.0, 3.0, 3.0, 3.0]}
    mask = _no_mask(sc)
    mask["a"][1] = True
    out = slt.policy_flags(sc, mask, 1, 1, "carry")
    assert out["a"][1] is False, "a book with no history at all was ranked on a carried value"
    assert out["b"][1] is True, "the worst measurable book was not demoted"


def test_policy_flags_refuses_nonsense_arguments():
    sc = _flat_scores()
    mask = _no_mask(sc)
    with pytest.raises(ValueError):
        slt.policy_flags(sc, mask, 1, 1, "whatever_the_curator_felt_like")
    with pytest.raises(ValueError):
        slt.policy_flags(sc, mask, 0, 1, "open")
    with pytest.raises(ValueError):
        slt.policy_flags(sc, mask, 1, 0, "open")
    with pytest.raises(ValueError):
        slt.policy_flags(sc, mask, len(sc), 1, "open")


# ═════════════════════════════ the duty-matched control ═════════════════════════════
def test_duty_matched_clean_finds_the_closest_M_and_reports_the_duty_it_achieved():
    """#52 cannot be read without this control, and the control cannot be read without the gap it
    reports: where duty does not respond to M, the match FAILED and the row must say so."""
    n = 200
    panel = _FakePanel({"a": _wave(n, 7, amp=0.03), "b": _wave(n, 11, amp=0.01, phase=2.0),
                        "c": _wave(n, 13, amp=0.02), "d": _wave(n, 5, amp=0.005)})
    grid = tuple(range(1, 21))
    sc = slt.rcd.panel_scores(panel, "drift", slt.LOOKBACK)
    duties = {m: xsd.duty(xsd.rank_demotion_flags(sc, 1, m)) for m in grid}
    assert len(set(round(d, 9) for d in duties.values())) > 1, (
        "duty does not respond to M on this fixture — the assertions below would be vacuous")

    target = max(duties.values())
    assert duties[grid[0]] != target, "the first M already hits the target — nothing is being chosen"

    m_days, achieved, metrics = slt.duty_matched_clean(panel, "drift", 1, target, ms=grid)
    assert achieved == pytest.approx(target, abs=1e-12), "not the closest M"
    assert achieved == pytest.approx(duties[m_days], abs=1e-12), "reported duty is not M's duty"
    assert "calmar" in metrics and "turnover_yr" in metrics


# ═════════════════════════════ scope / hygiene ═════════════════════════════
def test_module_is_advisory_read_only_research_code():
    assert slt.IS_ADVISORY is True and slt.OUTSIDE_RISKPOLICY is True
    src = (SCRIPTS / "edge_signal_latency.py").read_text(encoding="utf-8")
    assert "spa_core.execution" not in src and "from spa_core import execution" not in src
    for forbidden in ("atomic_save", "open(", ".write_text(", "json.dump"):
        assert forbidden not in src, f"a research script must not persist state ({forbidden})"


def test_the_rules_under_test_are_the_ones_the_registry_published():
    """#51/#52 re-use published cells and re-tune nothing: #40's reference (k=2, M=20) and #45's
    best (k=1, M=1). A silently re-tuned cell would turn a robustness check into a new sweep."""
    assert ("drift", "#40 XSD k=2 M=20", 2, 20) in slt.RULES
    assert ("volatility", "#45 XVD k=1 M=1", 1, 1) in slt.RULES
    assert slt.LOOKBACK == xsd.LOOKBACK == 60
    assert 0 in slt.TAUS and any(t < 0 for t in slt.TAUS), "the look-ahead control was dropped"


@pytest.mark.skipif(not (ROOT / "data" / "aggressive_lab").exists(),
                    reason="nightly panel artefacts are gitignored and absent in CI")
def test_real_panel_latency_pass_is_read_only_and_keeps_the_persistence_ladder():
    """On the real panel: τ=0 must be the untouched rule, one day of staleness must move FEWER
    book-days for the volatility criterion than for the drift criterion (the persistence ladder
    of #44/#45), and the whole pass must leave data/ exactly as it found it.

    Property-based on purpose — the books are regenerated nightly, so a pinned number here would
    be a time bomb; the numbers live in the registry entry, dated to their run.
    """
    before = sorted(p.name for p in (ROOT / "data").glob("*"))
    panel = slt.dgo.Panel()
    moved = {}
    for kind, name, k, m_days in slt.RULES:
        sc = slt.rcd.panel_scores(panel, kind, slt.LOOKBACK)
        fresh = xsd.rank_demotion_flags(sc, k, m_days)
        assert xsd.rank_demotion_flags(slt.lag_scores(sc, 0), k, m_days) == fresh
        late = xsd.rank_demotion_flags(slt.lag_scores(sc, 1), k, m_days)
        moved[name] = sum(1 for b in fresh for i in range(panel.n) if fresh[b][i] != late[b][i])
    assert moved["#45 XVD k=1 M=1"] < moved["#40 XSD k=1 M=1"], (
        "the volatility rank is supposed to be the more persistent criterion")
    assert sorted(p.name for p in (ROOT / "data").glob("*")) == before, "the pass wrote into data/"
