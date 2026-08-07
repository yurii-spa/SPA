# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_dispersion_gated_demotion.py (registry ideas #42 CSDG / #43 ZSD).

Both entries are NEGATIVE verdicts, and a negative verdict is worth exactly as much as the
guarantee that the thing measured was the thing described. #42 says "gating #40's rule on
dispersion destroys it"; that sentence is only true if the gated rule really is #40's rule on the
days it acts, and really is *nothing* on the days it does not. #43 says "at matched duty the
z-score criterion adds nothing"; that is only true if the z-score is a measurement rather than a
division by a denominator that happened to be near zero. Those are the properties pinned here:

  • **An all-open gate must reproduce #40 byte-for-byte.** If it did not, every row of #42's table
    would compare two different rules and the verdict would be about the difference between them,
    not about the gate. Pinned on a (k × M) grid against `xsd.rank_demotion_flags` itself.
  • **An ungated day must be a day on which nothing was learned.** The re-admission counter must
    NOT advance across it — a book that sat out a closed gate has not earned credit for good
    behaviour nobody checked. This is the single most load-bearing convention in #42, and it is
    the one an ordinary implementation gets wrong by default (the natural loop advances the
    counter every day), so it is pinned directly, not through a portfolio number.
  • **The percentile window must never contain today.** A gate that scored today against a
    distribution including today is the classic quiet look-ahead: it would know today was wide by
    standards of a window it has not lived through. Pinned with a spike large enough that
    including it would flip the answer — a positive control, not an assertion of intent.
  • **Fail-CLOSED means False, and False means "may not act".** Cold start, undefined dispersion,
    too few observations, a degenerate cross-sectional sd, an unmeasured book: five places where
    a decision is not defined, and in every one the rule must decline rather than guess. Pinned
    one by one, because each is a separate line of code that can independently start guessing.
  • **The duty-matched controls must actually match.** A random gate that could fire during the
    warm-up, where the real gate is structurally silent, is not a control — it is an advantaged
    twin, and it would have made #42's decisive p-value meaningless in the rule's favour.
  • **The f-string regression that reddened CI.** `scripts/edge_cross_sectional_demotion.py` — the
    harness this module imports — carried a backslash inside an f-string replacement field, which
    is a SyntaxError before Python 3.12 and therefore a COLLECTION error on the 3.11 CI matrix:
    not one red test but a whole red run. It is checked here as a property of the edge-R&D
    scripts, and the check reddens on the exact pre-fix line.

All series are hand-checkable synthetics. No repo data, no network, no writes.
"""
from __future__ import annotations

import importlib.util
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mod = _load("edge_dispersion_gated_demotion")
xsd = _load("edge_cross_sectional_demotion")


# ─────────────────────────── synthetic material ───────────────────────────
def wave(n: int, period: int = 40, amp: float = 0.004, drift: float = 0.0):
    """Deterministic oscillating series with a drift — no RNG, so a failure is reproducible."""
    return [drift + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


def rets(n: int = 260):
    """Six books whose trailing drifts genuinely differ, so a ranking has something to rank."""
    return {
        "a": wave(n, 40, 0.004, +0.0006),
        "b": wave(n, 55, 0.003, +0.0003),
        "c": wave(n, 30, 0.005, -0.0004),
        "d": wave(n, 70, 0.002, -0.0008),
        "e": wave(n, 45, 0.004, +0.0001),
        "f": wave(n, 33, 0.003, -0.0002),
    }


def scores(n: int = 260, lookback: int = 20):
    return xsd.drift_scores(rets(n), lookback)


def flat(n: int, value=None):
    return [value] * n


# ═══════════════════════ the gate must not change the rule it gates ═══════════════════════
@pytest.mark.parametrize("k", [1, 2, 3])
@pytest.mark.parametrize("m_days", [1, 5, 20])
def test_all_open_gate_reproduces_idea40_exactly(k, m_days):
    """The load-bearing identity: with the gate always open this IS #40, flag for flag."""
    sc = scores()
    n = len(next(iter(sc.values())))
    gated = mod.gated_rank_flags(sc, [True] * n, k, m_days)
    assert gated == xsd.rank_demotion_flags(sc, k, m_days)


def test_a_closed_gate_forever_demotes_nobody_ever():
    """The other end of the identity: a rule that may never act must never act."""
    sc = scores()
    n = len(next(iter(sc.values())))
    gated = mod.gated_rank_flags(sc, [False] * n, 2, 20)
    assert not any(any(v) for v in gated.values())


def test_state_is_frozen_while_the_gate_is_closed():
    """Nothing changes on a day the rule was not allowed to look at."""
    sc = scores()
    n = len(next(iter(sc.values())))
    gate = [False] * n
    open_day = 120
    gate[open_day] = True
    fl = mod.gated_rank_flags(sc, gate, 2, readmit_days=3)
    demoted = [b for b in fl if fl[b][open_day]]
    assert len(demoted) == 2, "the one open day must run the ordinary bottom-k rule"
    for b in demoted:
        assert all(fl[b][i] for i in range(open_day, n)), (
            "a demoted book changed state on days the gate was shut")


def test_closed_days_earn_no_readmission_credit():
    """The load-bearing convention, in the one construction that can actually detect a breach.

    A freeze alone does NOT catch a counter that ticks while the gate is shut: nothing is released
    until the gate reopens, so a test that never reopens it passes either way. (Measured — the
    first version of this test did exactly that and survived the mutation it was written to kill.)
    So the gate reopens here, on a day the book is no longer worst:

        day 0      gate OPEN,  `a` is the single worst  → demoted, quiet run 0
        days 1–9   gate SHUT   → nothing observed about anybody
        day 10     gate OPEN,  `d` is now worst         → `a`'s FIRST quiet day, run 1 of 3

      • correct   : `a` needs three OPEN quiet days, so it is still demoted on days 10 and 11 and
                    is released on day 12;
      • ticking on shut days: the run already stands at ten by day 10 and `a` is released there.

    The two behaviours therefore disagree on day 10, which is what the assertion reads.
    """
    n = 14
    sc = {
        "a": [-5.0] + [0.0] * (n - 1),
        "b": [1.0] * n,
        "c": [2.0] * n,
        "d": [3.0] * 10 + [-9.0] * (n - 10),
    }
    gate = [i == 0 or i >= 10 for i in range(n)]
    fl = mod.gated_rank_flags(sc, gate, k=1, readmit_days=3)

    assert fl["a"][0] is True, "the worst book on the one early open day must be demoted"
    assert fl["d"][10] is True, "the new worst book must take over once the gate reopens"
    assert fl["a"][10] is True, (
        "`a` was re-admitted on its FIRST observed quiet day — the re-admission counter ticked "
        "through days on which the gate was shut and nobody checked it")
    assert fl["a"][11] is True
    assert fl["a"][12] is False, "three observed quiet days must re-admit it"


def test_release_variant_clears_every_demotion_on_a_closed_gate():
    """`freeze=False` is the documented alternative and must really be the alternative."""
    sc = scores()
    n = len(next(iter(sc.values())))
    gate = [False] * n
    gate[120] = True
    fl = mod.gated_rank_flags(sc, gate, 2, readmit_days=3, freeze=False)
    assert any(fl[b][120] for b in fl)
    assert not any(fl[b][121] for b in fl)


def test_gated_rule_demotions_are_a_subset_of_the_ungated_rules_opportunities():
    """A gate can only ever REMOVE decision days; it must never manufacture a new demotion day."""
    sc = scores()
    n = len(next(iter(sc.values())))
    gate = [i % 3 == 0 for i in range(n)]
    gated = mod.gated_rank_flags(sc, gate, 2, 1)
    ungated = xsd.rank_demotion_flags(sc, 2, 1)
    for b in gated:
        for i in range(n):
            if gate[i] and gated[b][i]:
                assert ungated[b][i], "the gated rule demoted a book #40 would not have"


@pytest.mark.parametrize("bad", [
    dict(k=0), dict(k=99), dict(readmit_days=0),
])
def test_gated_rule_refuses_undefined_configurations(bad):
    sc = scores()
    n = len(next(iter(sc.values())))
    kw = dict(k=2, readmit_days=1)
    kw.update(bad)
    with pytest.raises(ValueError):
        mod.gated_rank_flags(sc, [True] * n, **kw)


def test_gate_length_mismatch_is_refused_not_silently_truncated():
    """A short gate would silently un-gate the tail — a rule change disguised as an off-by-one."""
    sc = scores()
    n = len(next(iter(sc.values())))
    with pytest.raises(ValueError):
        mod.gated_rank_flags(sc, [True] * (n - 1), 2, 1)


# ═══════════════════════ dispersion and the gate itself ═══════════════════════
def test_dispersion_matches_the_hand_computed_population_stdev():
    sc = {"a": [1.0], "b": [2.0], "c": [3.0]}
    (d,) = mod.dispersion(sc)
    assert d == pytest.approx(math.sqrt(2.0 / 3.0))


def test_dispersion_is_None_not_zero_when_the_field_is_too_thin():
    """Zero would read as 'the books are identical today', which is the one thing it is not known
    to be — and every consumer treats None as 'do not act' and 0.0 as 'perfectly narrow'."""
    assert mod.dispersion({"a": [1.0], "b": [None]}) == [None]
    assert mod.dispersion({"a": [1.0], "b": [2.0]}) == [None]


def test_gate_scores_today_against_history_that_excludes_today():
    """Positive control for the look-ahead, built so that inclusion would FLIP the answer.

    The window is flat at 1.0 and today is 100.0, read through the INVERSE gate at q=1.0 — "is
    today at or below the widest day of the recent past?".

      • reading history through yesterday : threshold = 1.0, and 100.0 <= 1.0 is False  ← correct
      • had today been in its own window  : threshold = 100.0, and 100.0 <= 100.0 is True

    So the two readings disagree here, which is the whole point: a causality assertion that both
    readings satisfy proves nothing. The direction was chosen deliberately — at the high end the
    `>=` comparison is self-satisfying for a record day and cannot discriminate.
    """
    disp = [1.0] * 40 + [100.0]
    assert mod.dispersion_gate(disp, window=40, q=1.0, min_points=30, high=False)[-1] is False
    assert mod.dispersion_gate(disp, window=40, q=1.0, min_points=30, high=True)[-1] is True


def test_gate_reads_no_day_at_or_after_today():
    """The other half of causality: rewriting the FUTURE must not move a past day's gate."""
    disp = [1.0 + 0.5 * math.sin(i / 3.0) for i in range(120)]
    base = mod.dispersion_gate(disp, window=40, q=0.7, min_points=30)
    for t in (60, 90):
        mutated = disp[:t + 1] + [1000.0] * (len(disp) - t - 1)
        assert mod.dispersion_gate(mutated, window=40, q=0.7, min_points=30)[t] == base[t]


def test_gate_is_fail_closed_during_warmup_and_on_undefined_dispersion():
    disp = [None] * 5 + [1.0] * 10
    gate = mod.dispersion_gate(disp, window=40, q=0.5, min_points=30)
    assert gate == [False] * len(disp), "a cold start must not be able to demote anything"

    disp2 = [1.0 + i * 0.01 for i in range(60)] + [None]
    assert mod.dispersion_gate(disp2, window=40, q=0.5, min_points=30)[-1] is False


def test_inverse_gate_selects_the_narrow_days_instead():
    disp = [1.0] * 40 + [0.001]
    assert mod.dispersion_gate(disp, 40, 0.0, 30, high=True)[-1] is False
    assert mod.dispersion_gate(disp, 40, 0.0, 30, high=False)[-1] is True


@pytest.mark.parametrize("bad", [dict(window=0), dict(q=-0.1), dict(q=1.5)])
def test_gate_refuses_undefined_parameters(bad):
    kw = dict(window=10, q=0.5, min_points=1)
    kw.update(bad)
    with pytest.raises(ValueError):
        mod.dispersion_gate([1.0] * 20, **kw)


def test_percentile_is_nearest_rank_and_refuses_an_empty_sample():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mod._percentile(vals, 0.0) == 1.0
    assert mod._percentile(vals, 1.0) == 5.0
    assert mod._percentile(vals, 0.5) == 3.0
    with pytest.raises(ValueError):
        mod._percentile([], 0.5)


def test_causal_rank_reads_only_days_strictly_before_today():
    """Mutating a FUTURE dispersion value must not move today's rank."""
    disp = [float(i) for i in range(80)]
    before = mod.causal_rank(disp, window=40, min_points=30)[60]
    disp[70] = 10_000.0
    after = mod.causal_rank(disp, window=40, min_points=30)[60]
    assert before == after


# ═══════════════════════ the controls must really be matched ═══════════════════════
def test_random_gate_opens_the_exact_count_and_only_where_eligible():
    """An unmatched control is not a control. Both halves of the match are pinned."""
    elig = [i >= 50 for i in range(200)]
    g = mod.random_gate(elig, 30, seed=7)
    assert sum(1 for x in g if x) == 30
    assert all(elig[i] for i, x in enumerate(g) if x), (
        "a random gate fired where the real gate structurally cannot")


def test_random_gate_is_reproducible_and_seed_dependent():
    elig = [True] * 100
    assert mod.random_gate(elig, 20, 3) == mod.random_gate(elig, 20, 3)
    assert mod.random_gate(elig, 20, 3) != mod.random_gate(elig, 20, 4)


def test_random_gate_refuses_to_open_more_days_than_exist():
    with pytest.raises(ValueError):
        mod.random_gate([True] * 10, 11, seed=0)


def test_count_matched_gate_selects_exactly_n_by_rank_and_nothing_else():
    """The definition, pinned: n eligible days, and no unselected eligible day outranks a selected
    one. Stated as the ordering property rather than as a list of indices, because the quantity
    being ordered is a RECENT-standards rank, not an absolute width (next test)."""
    disp = [1.0 + 0.5 * math.sin(i / 3.0) for i in range(120)]
    elig = mod.gate_eligible(disp, window=40, min_points=30)
    rank = mod.causal_rank(disp, window=40, min_points=30)
    for high in (True, False):
        g = mod.count_matched_gate(rank, elig, 12, high=high)
        chosen = [i for i, x in enumerate(g) if x]
        rest = [i for i, e in enumerate(elig) if e and not g[i]]
        assert len(chosen) == 12
        assert all(elig[i] for i in chosen)
        if high:
            assert min(rank[i] for i in chosen) >= max(rank[i] for i in rest)
        else:
            assert max(rank[i] for i in chosen) <= min(rank[i] for i in rest)


def test_count_matched_gate_ranks_by_recent_standards_not_absolute_width():
    """A 5.0 after forty flat 1.0 days outranks a 7.0 that follows a 9.0 — that is the point.

    Hand-checked: with window=40, day 40 (5.0) has every one of its forty reference days below it
    (rank 1.0), while day 44 (7.0) has a 9.0 behind it (rank 0.975). A rule that ordered by the
    raw dispersion level instead would pick day 44 and this test reddens.
    """
    disp = [1.0] * 40 + [5.0, 1.0, 9.0, 1.0, 7.0]
    elig = mod.gate_eligible(disp, window=40, min_points=30)
    rank = mod.causal_rank(disp, window=40, min_points=30)
    assert rank[40] == pytest.approx(1.0)
    assert rank[44] == pytest.approx(0.975)
    wide = mod.count_matched_gate(rank, elig, 2, high=True)
    assert [i for i, x in enumerate(wide) if x] == [40, 42]


def test_gate_eligible_marks_exactly_where_a_real_gate_could_have_fired():
    disp = [1.0 + i * 0.01 for i in range(50)]
    elig = mod.gate_eligible(disp, window=40, min_points=30)
    for q in (0.0, 0.5, 1.0):
        gate = mod.dispersion_gate(disp, window=40, q=q, min_points=30)
        assert all(elig[i] for i, g in enumerate(gate) if g), (
            "the real gate fired outside the region its random twin is allowed to draw from")


def test_gate_duty_counts_days_not_book_days():
    assert mod.gate_duty([True, False, True, False]) == pytest.approx(0.5)
    assert mod.gate_duty([]) == 0.0


# ═══════════════════════ #43 — the z-score must be a measurement ═══════════════════════
def test_zscore_matches_the_hand_computed_standardisation():
    zs = mod.zscore_scores({"a": [1.0], "b": [2.0], "c": [3.0]})
    sd = math.sqrt(2.0 / 3.0)
    assert zs["a"][0] == pytest.approx(-1.0 / sd)
    assert zs["b"][0] == pytest.approx(0.0)
    assert zs["c"][0] == pytest.approx(+1.0 / sd)


def test_zscore_is_fail_closed_on_a_degenerate_denominator():
    """An identical field has no 'worst'. Dividing by that sd would turn rounding into demotions."""
    zs = mod.zscore_scores({"a": [2.0], "b": [2.0], "c": [2.0]})
    assert all(zs[b][0] is None for b in zs)


def test_zscore_is_fail_closed_when_the_field_is_too_thin():
    zs = mod.zscore_scores({"a": [1.0], "b": [5.0], "c": [None]})
    assert all(zs[b][0] is None for b in zs)


def test_zscore_demotion_matches_the_threshold_it_documents():
    zs = {"a": [-2.0], "b": [0.0], "c": [+2.0]}
    fl = mod.zscore_demotion_flags(zs, z_star=1.0, readmit_days=1)
    assert fl["a"][0] is True
    assert fl["b"][0] is False and fl["c"][0] is False


def test_unmeasured_book_keeps_its_state_and_earns_no_readmission_credit():
    """The asymmetry that matters: unmeasured is NOT the same as cleared.

    A book demoted on day 0 and unmeasurable afterwards must stay demoted — nothing has been
    observed that would clear it — and must not accumulate the quiet days it never proved.
    """
    zs = {"a": [-3.0] + [None] * 10, "b": [0.0] * 11, "c": [3.0] * 11}
    fl = mod.zscore_demotion_flags(zs, z_star=1.0, readmit_days=2)
    assert all(fl["a"]), "an unmeasured book was re-admitted on evidence that does not exist"


def test_zscore_readmission_requires_consecutive_quiet_days():
    zs = {"a": [-3.0, 0.0, -3.0, 0.0, 0.0, 0.0], "b": [0.0] * 6, "c": [3.0] * 6}
    fl = mod.zscore_demotion_flags(zs, z_star=1.0, readmit_days=2)
    assert fl["a"] == [True, True, True, True, False, False], (
        "a broken run of quiet days must not count toward re-admission")


def test_zscore_sign_flip_control_actually_flips_the_selection():
    zs = {"a": [-2.0], "b": [0.0], "c": [+2.0]}
    worst = mod.zscore_demotion_flags(zs, 1.0, 1, worst_first=True)
    best = mod.zscore_demotion_flags(zs, 1.0, 1, worst_first=False)
    assert worst["a"][0] and not worst["c"][0]
    assert best["c"][0] and not best["a"][0]


@pytest.mark.parametrize("bad", [dict(z_star=0.0), dict(z_star=-1.0), dict(readmit_days=0)])
def test_zscore_rule_refuses_undefined_configurations(bad):
    kw = dict(z_star=1.0, readmit_days=1)
    kw.update(bad)
    with pytest.raises(ValueError):
        mod.zscore_demotion_flags({"a": [0.0], "b": [1.0], "c": [2.0]}, **kw)


def test_duty_match_rank_reports_the_closest_attainable_k():
    """k moves duty in ~10-point steps, so this control is honest only if it returns the closest
    attainable configuration AND its achieved duty — which the caller prints beside the target."""
    sc = scores()
    k, achieved = mod._match_duty_rank(sc, target=0.30, ks=(1, 2, 3, 4, 5))
    duties = {kk: xsd.duty(xsd.rank_demotion_flags(sc, kk, mod.REF_M)) for kk in (1, 2, 3, 4, 5)}
    assert achieved == pytest.approx(duties[k])
    assert min(duties, key=lambda kk: abs(duties[kk] - 0.30)) == k


# ═══════════════════════ regressions and scope ═══════════════════════
BACKSLASH_IN_FSTRING_FIELD = re.compile(r'f"[^"]*\{[^{}]*\\[^{}]*\}')


@pytest.mark.parametrize("script", sorted(p.name for p in (ROOT / "scripts").glob("edge_*.py")))
def test_no_backslash_inside_an_fstring_field_py311_syntaxerror(script):
    """CI runs Python 3.11, where this is a SyntaxError — i.e. a COLLECTION error, not a red test.

    Positive control: this is the exact pattern that reddened the whole suite on main from
    2026-08-07 02:21Z, from one line of `edge_cross_sectional_demotion.py`. Backslashes inside
    f-string replacement fields only became legal in 3.12, and the repo's runtime floor is lower,
    so the fix is to bind the literal to a name — not to raise the floor.
    """
    src = (ROOT / "scripts" / script).read_text()
    offenders = [(i, line.strip()) for i, line in enumerate(src.split("\n"), 1)
                 if BACKSLASH_IN_FSTRING_FIELD.search(line)]
    assert not offenders, (
        f"{script}: backslash inside an f-string replacement field is a SyntaxError before "
        f"Python 3.12 and the CI matrix runs 3.11 — bind the literal to a name first: {offenders}")


def test_the_regression_detector_itself_reddens_on_the_offending_line():
    """A detector that has never seen the real failure is decoration (deployment rule)."""
    assert BACKSLASH_IN_FSTRING_FIELD.search(
        """    print(f"{'k \\\\ M':>8s}" + "".join(f"{m:>8d}" for m in ms))""")
    assert not BACKSLASH_IN_FSTRING_FIELD.search(
        '''    corner = "k \\\\ M"\n    print(f"{corner:>8s}")''')


def test_module_is_advisory_and_outside_riskpolicy():
    """The scope invariant, asserted rather than promised in a docstring."""
    assert mod.IS_ADVISORY is True
    assert mod.OUTSIDE_RISKPOLICY is True


def test_module_inherits_idea40s_lookback_rather_than_retuning_it():
    """#42/#43's honesty rests on only the NEW axis moving. A drifted L would silently make the
    comparison with #39/#40 a comparison between two different statistics."""
    assert mod.LOOKBACK == xsd.LOOKBACK == 60
    assert (mod.REF_K, mod.REF_M) == (2, 20)


def test_module_writes_nothing_and_imports_no_execution_code():
    src = (ROOT / "scripts" / "edge_dispersion_gated_demotion.py").read_text()
    assert "spa_core.execution" not in src
    assert "atomic_save" not in src and "open(" not in src
