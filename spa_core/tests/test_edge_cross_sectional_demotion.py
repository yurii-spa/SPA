# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_cross_sectional_demotion.py (registry ideas #40 XSD / #41 MRD).

Both verdicts are comparisons, and a comparison is worth exactly as much as the properties that
keep the two sides comparable. Those are the properties pinned here:

  • **#40's whole claim is "same rule as #39, one substitution."** That is only true if the
    re-admission state machine is #39's with "below the hurdle" replaced by "in the bottom-k" —
    so with M=1 the state must be EXACTLY membership of the bottom-k, and raising M may only ever
    ADD demoted days. Both pinned, on a grid.
  • **The duty-matched control is the decisive one**, and it is decisive only if it really matches
    duty. The naive hurdle-only bisection does NOT (the finding that duty is not a knob of the
    absolute rule) — so the search over (L, hurdle, M) is pinned to return the closest attainable
    duty, and the fast path it uses (`_demoted_days_from_mu`, a transcription of #39's state
    machine over a pre-computed trailing mean) is pinned to agree with `ecr.demotion_flags` itself.
    A transcription that quietly drifted would duty-match a rule nobody scored.
  • **A rank is not defined for everybody**, and the three places where it is undefined are
    exactly the places a rule can fabricate a decision: during warm-up, for a book whose score is
    unmeasured, and on a day when k or fewer books are rankable at all. All three are fail-CLOSED
    and pinned; in particular an unmeasured book must never be rankable, which is why the scores
    return None where `cfpt.trailing_mean` returns a fabricated 0.0.
  • **#41's score must read the RAW panel, never the rule's own positions** (self-feeding would
    make two rows incomparable) and must use only days strictly before t. Pinned against a
    hand-computed value, and in both causal directions.
  • Ties break by book name, so a report is reproducible rather than dict-ordered.
  • The sign-flipped control must actually flip the selection, otherwise "the ranking carries
    information" is an unmeasured claim.

All series are hand-checkable synthetics. No repo data, no network, no writes.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mod = _load("edge_cross_sectional_demotion")
ecr = _load("edge_capital_recycling")
cfpt = _load("edge_calm_fp_tax")


# ─────────────────────────── synthetic material ───────────────────────────
def wave(n: int, period: int = 40, amp: float = 0.004, drift: float = 0.0):
    """Deterministic oscillating series with a drift — no RNG, so a failure is reproducible."""
    return [drift + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


class FakePanel:
    """The three attributes the module reads off a panel. Keeps the tests off repo data."""

    def __init__(self, rets):
        self.rets = {k: list(v) for k, v in rets.items()}
        self.books = sorted(self.rets)
        self.n = len(next(iter(self.rets.values())))

    def raw_portfolio(self):
        return [sum(self.rets[b][i] for b in self.books) / len(self.books)
                for i in range(self.n)]


def ranked_panel(n: int = 300):
    """Four books with strictly ordered drifts: d < c < b < a. The bottom-k is knowable by hand."""
    return FakePanel({
        "a": [0.0020 + 0.001 * math.sin(i / 7.0) for i in range(n)],
        "b": [0.0010 + 0.001 * math.sin(i / 7.0) for i in range(n)],
        "c": [-0.0005 + 0.001 * math.sin(i / 7.0) for i in range(n)],
        "d": [-0.0020 + 0.001 * math.sin(i / 7.0) for i in range(n)],
    })


def scores_from(panel, lookback=30):
    return mod.drift_scores(panel.rets, lookback)


# ═════════════ #40 — the state machine is #39's, with one substitution ═════════════
@pytest.mark.parametrize("k", [1, 2])
@pytest.mark.parametrize("lookback", [10, 30])
def test_M1_state_is_exactly_membership_of_the_bottom_k(k, lookback):
    """With M=1 the flag must BE "in the bottom-k today". If it merely resembles it, the M column
    of #40 cannot be read the way #39's is, and the two tables stop being comparable."""
    panel = ranked_panel()
    sc = mod.drift_scores(panel.rets, lookback)
    flags = mod.rank_demotion_flags(sc, k, 1)
    for i in range(panel.n):
        rankable = [b for b in panel.books if sc[b][i] is not None]
        if len(rankable) <= k:
            continue
        bottom = set(sorted(rankable, key=lambda b: (sc[b][i], b))[:k])
        for b in panel.books:
            assert flags[b][i] is (b in bottom), f"day {i}, book {b}"


def test_readmission_delay_is_monotone_hysteresis():
    """Raising M may only ADD demoted days — that is what makes the sweep a hysteresis axis."""
    panel = ranked_panel()
    sc = scores_from(panel)
    prev = mod.rank_demotion_flags(sc, 2, 1)
    for m_days in (2, 3, 5, 10, 20, 45):
        cur = mod.rank_demotion_flags(sc, 2, m_days)
        for b in panel.books:
            assert all((not p) or c for p, c in zip(prev[b], cur[b])), (
                f"M={m_days} un-demoted a day a shorter delay demoted ({b}) — not a hysteresis knob")
            assert sum(cur[b]) >= sum(prev[b])
        prev = cur


def test_exactly_k_books_are_demoted_once_the_field_is_rankable():
    """The duty of a rank rule is a constant of the rule, not of the market — #40's entire
    premise. With M=1 exactly k books are out on every rankable day."""
    panel = ranked_panel()
    sc = scores_from(panel, 30)
    flags = mod.rank_demotion_flags(sc, 2, 1)
    for i in range(30, panel.n):
        assert sum(1 for b in panel.books if flags[b][i]) == 2, f"day {i}"


def test_warmup_is_fail_closed_and_scores_are_None_not_zero():
    """An unmeasured drift is not a low drift. `cfpt.trailing_mean` fabricates 0.0 there, which
    would rank a warming-up book mid-field; the score layer must return None instead."""
    panel = ranked_panel()
    sc = mod.drift_scores(panel.rets, 30)
    for b in panel.books:
        assert all(v is None for v in sc[b][:30])
        assert all(v is not None for v in sc[b][30:])
    flags = mod.rank_demotion_flags(sc, 2, 1)
    assert not any(flags[b][i] for b in panel.books for i in range(30))


def test_a_field_with_no_rankable_worst_freezes_state():
    """k or fewer rankable books ⇒ nobody changes state. Demoting k of k would be an EXPOSURE
    decision wearing a selection rule's clothes — the one thing #40 must never do silently."""
    n = 40
    sc = {"a": [None] * n, "b": [None] * n, "c": [None] * n}
    sc["a"][10:] = [0.001] * (n - 10)
    sc["b"][10:] = [-0.001] * (n - 10)          # only two books ever rankable, k=2 ⇒ frozen
    flags = mod.rank_demotion_flags(sc, 2, 1)
    assert not any(flags[b][i] for b in sc for i in range(n))


def test_unmeasured_book_can_never_be_demoted():
    n = 80
    sc = {"a": [0.002] * n, "b": [0.001] * n, "c": [-0.005] * n, "ghost": [None] * n}
    flags = mod.rank_demotion_flags(sc, 2, 1)
    assert not any(flags["ghost"])
    assert all(flags["c"])                       # the genuinely worst book is the one demoted


def test_ties_break_by_book_name_so_reports_are_reproducible():
    """Two mechanisms guarantee this — the books are iterated in sorted order AND the sort key
    carries the name — so either one alone is sufficient and removing just one is a genuinely
    equivalent change. That is why the fixture feeds the scores in REVERSE insertion order: it
    reddens when both are gone, which is the only state that actually makes a report depend on
    dict ordering."""
    n = 30
    sc = {b: [0.0] * n for b in ("d", "c", "b", "a")}
    flags = mod.rank_demotion_flags(sc, 2, 1)
    assert [b for b in sorted(sc) if flags[b][5]] == ["a", "b"]


def test_sign_flipped_control_actually_flips_the_selection():
    """Otherwise "the ranking carries information" is an unmeasured claim."""
    panel = ranked_panel()
    sc = scores_from(panel)
    worst = mod.rank_demotion_flags(sc, 1, 1)
    best = mod.rank_demotion_flags(sc, 1, 1, worst_first=False)
    assert all(worst["d"][i] for i in range(40, panel.n))
    assert all(best["a"][i] for i in range(40, panel.n))
    assert not any(best["d"][i] for i in range(40, panel.n))


def test_positive_control_permanently_worst_book_stays_demoted():
    panel = ranked_panel()
    sc = scores_from(panel, 30)
    flags = mod.rank_demotion_flags(sc, 1, 20)
    assert all(flags["d"][30:])
    assert not any(flags["a"])


@pytest.mark.parametrize("bad", [dict(k=0), dict(k=4), dict(readmit_days=0)])
def test_undefined_rules_are_refused_not_guessed(bad):
    panel = ranked_panel(120)
    sc = scores_from(panel)
    kwargs = dict(k=2, readmit_days=1)
    kwargs.update(bad)
    with pytest.raises(ValueError):
        mod.rank_demotion_flags(sc, **kwargs)


# ═════════════ causality — pinned in BOTH directions ═════════════
def test_drift_score_ignores_today_and_reacts_tomorrow():
    """A rule that ignored its input entirely would pass the first half on its own."""
    base = wave(200, drift=0.0005)
    shocked = list(base)
    shocked[120] = -0.9
    a = mod.drift_scores({"x": base}, 30)["x"]
    b = mod.drift_scores({"x": shocked}, 30)["x"]
    assert a[:121] == b[:121]
    assert a[121] != b[121]


def test_downside_score_matches_the_hand_computed_definition():
    """score(b,t) = mean of r_b over the days in [t−L, t−1] when the RAW panel was negative."""
    n, lkb = 60, 20
    rets = {"x": [0.01 if i % 2 else -0.02 for i in range(n)],
            "y": [-0.005 if i % 3 else 0.004 for i in range(n)]}
    sc = mod.downside_contribution_scores(rets, lkb, min_down_days=1)
    pf = [(rets["x"][i] + rets["y"][i]) / 2 for i in range(n)]
    i = 45
    down = [s for s in range(i - lkb, i) if pf[s] < 0]
    assert down, "fixture must produce down days or it tests nothing"
    for b in ("x", "y"):
        expect = sum(rets[b][s] for s in down) / len(down)
        assert sc[b][i] == pytest.approx(expect)


def test_downside_score_is_fail_closed_when_the_window_has_too_few_bad_days():
    n, lkb = 90, 30
    rets = {"x": [0.001] * n, "y": [0.002] * n}          # no down days at all, ever
    sc = mod.downside_contribution_scores(rets, lkb, min_down_days=5)
    assert all(v is None for v in sc["x"])
    flags = mod.rank_demotion_flags(sc, 1, 1)
    assert not any(flags[b][i] for b in sc for i in range(n))


def test_downside_score_uses_no_future_day():
    """Day 81 is an UP day in the fixture, so shocking book x there genuinely moves the down-day
    SET — which is the only channel through which one book's return may touch another's score.
    (Shocking a day that was already down changes nothing and would make this test vacuous.)"""
    n, lkb = 120, 30
    base = {"x": [(-0.01 if i % 4 == 0 else 0.003) for i in range(n)],
            "y": [(-0.02 if i % 5 == 0 else 0.004) for i in range(n)]}
    pf81 = (base["x"][81] + base["y"][81]) / 2
    assert pf81 > 0, "fixture drifted: day 81 must be an up day or this test proves nothing"
    shocked = {b: list(v) for b, v in base.items()}
    shocked["x"][81] = -0.5
    a = mod.downside_contribution_scores(base, lkb, 1)["y"]
    b = mod.downside_contribution_scores(shocked, lkb, 1)["y"]
    assert a[:82] == b[:82]
    assert a[82] != b[82]


# ═════════════ the duty-matched control ═════════════
@pytest.mark.parametrize("lookback", [10, 30])
@pytest.mark.parametrize("readmit", [1, 5, 20])
@pytest.mark.parametrize("hurdle", [-0.05, 0.0, 0.046])
def test_fast_duty_counter_agrees_with_idea39s_own_state_machine(lookback, readmit, hurdle):
    """The duty search sweeps thousands of configurations through a transcription of #39's rule.
    If the transcription drifted, the control would duty-match a rule nobody ever scored."""
    r = wave(400, period=31, amp=0.006, drift=-0.0002)
    mu = cfpt.trailing_mean(r, lookback)
    fast = mod._demoted_days_from_mu(mu, lookback, hurdle, readmit)
    slow = sum(ecr.demotion_flags(r, lookback, hurdle, readmit))
    assert fast == slow


def test_fast_duty_counter_agrees_on_the_exact_tie_that_floats_normally_hide():
    """`>=` vs `>` at the hurdle is invisible on wavy data — equality is measure-zero, so the
    grid test above passes under either. A constant series makes the trailing mean hit the hurdle
    EXACTLY, which is the only fixture that can tell the two apart, and #39 treats "exactly at the
    hurdle" as ABOVE it (not demoted). If the transcription flipped that, the duty control would
    match a stricter rule than the one it names."""
    r = [0.0] * 200                    # the one case where mu and the hurdle are EXACTLY equal
    mu = cfpt.trailing_mean(r, 30)     # (a non-zero pair does not survive the /365 round-trip)
    assert mu[100] == 0.0
    assert mod._demoted_days_from_mu(mu, 30, 0.0, 1) == sum(ecr.demotion_flags(r, 30, 0.0, 1))
    assert mod._demoted_days_from_mu(mu, 30, 0.0, 1) == 0, "at the hurdle is not below it"


def test_duty_is_non_decreasing_in_the_hurdle():
    """The property the hurdle-only bisection relies on. Its failure to hit an arbitrary target is
    NOT a violation of this — it is a step in a monotone function, which is the finding of #40."""
    panel = ranked_panel(300)
    prev = -1.0
    for h in (-0.5, -0.2, -0.05, 0.0, 0.05, 0.2, 0.5):
        d = mod.duty(mod.absolute_flags(panel, h, 30, 5))
        assert d >= prev - 1e-12, f"duty fell as the hurdle rose at h={h}"
        prev = d


def test_duty_match_search_returns_the_closest_attainable_configuration():
    panel = ranked_panel(300)
    target = mod.duty(mod.rank_demotion_flags(scores_from(panel), 2, 5))
    lkb, h, m_days, achieved = mod.match_duty_absolute(
        panel, target, lookbacks=(10, 30), readmits=(1, 5, 20),
        hurdles=[j * 0.02 for j in range(-10, 11)])
    assert achieved == pytest.approx(mod.duty(mod.absolute_flags(panel, h, lkb, m_days)))
    best = min(abs(mod.duty(mod.absolute_flags(panel, hh, ll, mm)) - target)
               for ll in (10, 30) for mm in (1, 5, 20)
               for hh in [j * 0.02 for j in range(-10, 11)])
    assert abs(achieved - target) == pytest.approx(best)


def test_duty_counts_cells_not_books():
    flags = {"a": [True, False, False, False], "b": [True, True, False, False]}
    assert mod.duty(flags) == pytest.approx(3 / 8)


# ═════════════ composition + scope ═════════════
def test_combined_flags_is_the_or_of_the_two_rules():
    rank = {"a": [True, False, False], "b": [False, False, True]}
    absolute = {"a": [False, True, False], "b": [False, False, False]}
    assert mod.combined_flags(rank, absolute) == {"a": [True, True, False],
                                                  "b": [False, False, True]}


def test_subset_report_counts_the_disagreement_not_the_agreement():
    panel = ranked_panel(200)
    extra, total = mod.absolute_is_subset_of_rank(panel, "drift", k=1, m_days=1,
                                                  hurdle=0.0, readmit_abs=1)
    absolute = mod.absolute_flags(panel, 0.0, mod.LOOKBACK, 1)
    rank = mod.rank_demotion_flags(mod.drift_scores(panel.rets, mod.LOOKBACK), 1, 1)
    assert total == sum(1 for b in panel.books for i in range(panel.n) if absolute[b][i])
    assert extra == sum(1 for b in panel.books for i in range(panel.n)
                        if absolute[b][i] and not rank[b][i])


def test_unknown_score_kind_is_refused():
    with pytest.raises(ValueError):
        mod._panel_scores(ranked_panel(80), "vibes")


def test_module_is_advisory_and_outside_riskpolicy():
    assert mod.IS_ADVISORY is True
    assert mod.OUTSIDE_RISKPOLICY is True
    src = (ROOT / "scripts" / "edge_cross_sectional_demotion.py").read_text()
    assert "spa_core.execution" not in src and "from spa_core" not in src
    assert "atomic_save" not in src and 'open(' not in src
