# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_event_time_scoring.py — registry idea #54 ETS.

Every test below runs on hand-built series, never on data/aggressive_lab/ (which is gitignored,
regenerated nightly, and absent in CI). What is pinned, and why each pin is a positive control —
a property that BREAKS if the corresponding piece of the finding is removed:

  • **A zero return is not a print.** print_stats() must count accrual days, not rows. If someone
    "simplifies" the print test to `r != 0` with a loose epsilon, or counts rows, the dark-book
    finding of #54 evaporates silently. Pinned on a book with an explicit dark tail.

  • **The darkness gate is causal.** dark_flags() at day i may look only at [i−win, i−1]. Checked by
    corrupting day i and asserting the flag at day i is unchanged — the same causality check the
    registry applies to every signal since #9.

  • **Warm-up is not darkness.** A book with a short history must NOT be called dark: that would
    demote every book on day 1 for a reason that has nothing to do with the book.

  • **ETS is event time, CAL is calendar time, and they COINCIDE on a book that prints daily.**
    This is the whole point of pairing N=60 prints with L=60 days; if they diverge on a dense
    book, the comparison in section 3 is comparing two things at once and its verdict is void.

  • **ETS re-animates a dead book (the mechanism behind the ❌).** On a book that earned a positive
    drift and then went dark, CAL decays to exactly 0.00 while ETS keeps quoting the stale positive
    number. This is the measured reason event-time scoring loses; pinned so it cannot be lost.

  • **ETS refuses past the horizon.** Beyond ETS_MAX_BACK with too few prints the score is None —
    UNMEASURED, never a low score. And under the rank machine a None book cannot be demoted
    (fail-OPEN) — pinned explicitly, because that is the behaviour the gate exists to override.

  • **The cash-twin identity (the decisive control).** A frozen book and an explicit 0.0%/day sleeve
    must produce identical portfolio metrics under the same rule. If this ever stops holding, the
    claim "the dead books ARE a cash sleeve" is no longer supported by the code that made it.

  • **The gate demotes a dead book and the criterion alone does not.** The separation of "criterion"
    from "gate" is the entry's central structural claim; pinned on a two-book panel where the
    outcome is unambiguous.

stdlib + pytest only. No network, no disk state, no fixtures from data/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_event_time_scoring.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_event_time_scoring.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_event_time_scoring_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ets_mod = _load()


# ── series builders (explicit, never random) ─────────────────────────────────────────────────────
def dense(n: int, drift: float) -> List[float]:
    """A book that prints every single day."""
    return [drift] * n


def dies(n: int, drift: float, last_print: int) -> List[float]:
    """A book that prints `drift` through `last_print` and is dark (exact 0.0) afterwards."""
    return [drift if i <= last_print else 0.0 for i in range(n)]


def panel_of(rets: Dict[str, List[float]]) -> "ets_mod.SynthPanel":
    """A panel whose axis labels are deliberately NOT dates.

    Nothing under test parses the axis — it is an ordered index and no more. Using `d0000`-style
    labels instead of calendar strings keeps the frozen-date class from growing for no reason
    (.claude/rules/deployment.md): a literal date here would be decoration that the calendar could
    one day break, on a test that has nothing to do with freshness.
    """
    n = len(next(iter(rets.values())))
    return ets_mod.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. A ZERO RETURN IS NOT A PRINT
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_print_stats_counts_accrual_days_not_rows():
    p = panel_of({"live": dense(300, 1e-4), "dead": dies(300, 1e-4, 99)})
    st = ets_mod.print_stats(p)
    assert st["live"]["prints"] == 300
    assert st["dead"]["prints"] == 100            # rows: 300 — the whole point
    assert st["dead"]["longest_dark"] == 200
    assert st["dead"]["dark_tail"] == 200
    assert st["live"]["density"] == pytest.approx(1.0)
    assert st["dead"]["density"] == pytest.approx(100 / 300)


def test_live_books_separates_on_density():
    p = panel_of({"live": dense(300, 1e-4), "dead": dies(300, 1e-4, 99)})
    assert ets_mod.live_books(p, min_density=0.5) == ["live"]
    # the threshold is a choice and is allowed to be moved — but it must actually move something
    assert sorted(ets_mod.live_books(p, min_density=0.3)) == ["dead", "live"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. THE DARKNESS GATE: causal, and warm-up is not darkness
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_dark_flags_fire_only_after_the_window_fills_with_silence():
    n, last = 400, 99
    flags = ets_mod.dark_flags({"b": dies(n, 1e-4, last)}, win=60, min_prints=3)["b"]
    assert not flags[last]                        # still printing
    # the window [i-60, i-1] must contain < 3 prints; the last print is at index 99, so the
    # window is print-free from i-1 > 99, i.e. i >= 161, and 3 prints leave by i >= 163.
    assert not flags[120]                         # window still holds live days
    assert flags[165]                             # long since silent
    assert all(flags[i] for i in range(200, n))


def test_dark_flags_are_strictly_causal():
    """Built so that including day t would FLIP the verdict — otherwise the test proves nothing.

    win=60, min_prints=3. At i=200 the trailing window [140,199] holds exactly two prints, so the
    book is dark. Adding a print ON day 200 would make three and un-dark it — which is precisely
    the leak this test exists to catch.
    """
    n = 260
    base = [0.0] * n
    base[190] = base[191] = 1e-3                  # exactly two prints inside [140, 199]
    flags_a = ets_mod.dark_flags({"b": base}, win=60, min_prints=3)["b"]
    assert flags_a[200], "precondition: with two prints in the window the book must read dark"

    poisoned = list(base)
    poisoned[200] = 1e-3                          # the third print, ON the judged day
    flags_b = ets_mod.dark_flags({"b": poisoned}, win=60, min_prints=3)["b"]
    assert flags_b[200], "day t's own return leaked into day t's darkness verdict"
    assert not flags_b[201], (
        "precondition: from day 201 the third print is legitimately in the window — if this also "
        "stayed dark the test would be passing for the wrong reason"
    )


def test_warmup_is_not_darkness():
    flags = ets_mod.dark_flags({"b": [0.0] * 100}, win=60, min_prints=3)["b"]
    assert not any(flags[:60]), "a book with no history yet was called dark — that is a warm-up bug"
    assert flags[60], "after a full silent window the book must be dark"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. ETS vs CAL — identical on a dense book, divergent on a dying one
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_ets_equals_cal_on_a_book_that_prints_every_day():
    r = [1e-4 + (i % 7) * 1e-5 for i in range(300)]     # dense, non-constant
    cal = ets_mod.cal_scores({"b": r}, lookback=60)["b"]
    ets = ets_mod.ets_scores({"b": r}, n_prints=60, max_back=365, min_prints=10)["b"]
    for i in range(60, 300):
        assert cal[i] is not None and ets[i] is not None
        assert ets[i] == pytest.approx(cal[i], abs=1e-15), (
            f"day {i}: event time and calendar time must coincide when every day is a print — "
            "otherwise section 3 compares two changes at once"
        )


def test_ets_reanimates_a_dead_book_while_cal_retires_it():
    n, last, drift = 400, 99, 5e-4
    r = dies(n, drift, last)
    cal = ets_mod.cal_scores({"b": r}, lookback=60)["b"]
    ets = ets_mod.ets_scores({"b": r}, n_prints=60, max_back=365, min_prints=10)["b"]
    probe = 250                                        # long after the book went silent
    assert cal[probe] == pytest.approx(0.0, abs=1e-15), "CAL should have decayed to a flat zero"
    assert ets[probe] == pytest.approx(drift, rel=1e-9), (
        "ETS must still be quoting the drift the book earned while alive — this stale positive "
        "score is the measured mechanism behind idea #54's negative verdict"
    )
    assert ets[probe] > cal[probe]


def test_ets_refuses_on_too_few_prints_rather_than_averaging_what_it_has():
    """A trickle of prints must read UNMEASURED, not "a mean of three points".

    The book prints once every 150 days, so the 365-day window always holds 2–3 prints: enough for
    an average, nowhere near enough for a judgement. If the min_prints guard is dropped, ETS starts
    quoting a confident number off three observations — the exact failure the None is there to
    prevent, and one a book that has simply gone silent could never trigger.
    """
    n = 800
    r = [1e-3 if i % 150 == 0 else 0.0 for i in range(n)]
    ets = ets_mod.ets_scores({"b": r}, n_prints=60, max_back=365, min_prints=10)["b"]
    assert all(s is None for s in ets), (
        "ETS averaged a handful of prints into a score — an unmeasured book was handed a rank"
    )
    # …and the same series with a dense history IS measurable, so the None above is the guard
    # talking and not a broken function.
    dense_ets = ets_mod.ets_scores({"b": dense(n, 1e-4)}, n_prints=60, max_back=365,
                                   min_prints=10)["b"]
    assert dense_ets[n - 1] is not None


def test_ets_returns_none_past_the_horizon_and_none_is_never_demotable():
    n, last = 600, 20
    r = dies(n, 5e-4, last)
    ets = ets_mod.ets_scores({"b": r}, n_prints=60, max_back=365, min_prints=10)["b"]
    assert ets[n - 1] is None, "past the lookback horizon an unmeasured book must score None"

    # …and None is UNMEASURED, which the rank machine treats as un-demotable (fail-OPEN).
    scores = {"b": ets, "x": ets_mod.cal_scores({"x": dense(n, 1e-4)}, 60)["x"],
              "y": ets_mod.cal_scores({"y": dense(n, 2e-4)}, 60)["y"]}
    flags = ets_mod.xsd.rank_demotion_flags(scores, k=1, readmit_days=1)
    assert not flags["b"][n - 1], (
        "a None-scored book was demoted — if this ever becomes true the dark feed no longer "
        "protects the book and the fail-OPEN half of #54 has silently changed"
    )
    # the explicit gate is what overrides it
    gated = ets_mod.or_flags(flags, ets_mod.unmeasured_flags(scores, ets_mod.LOOKBACK))
    assert gated["b"][n - 1], "the fail-CLOSED leg must demote exactly what the rank machine cannot"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE CASH-TWIN IDENTITY — the decisive control of section 2
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_a_frozen_book_and_an_explicit_cash_sleeve_are_the_same_portfolio():
    n = 300
    rets = {
        "a": [1e-4 + (i % 5) * 2e-5 for i in range(n)],
        "b": [2e-4 - (i % 3) * 3e-5 for i in range(n)],
        "c": [1.5e-4 + (i % 11) * 1e-5 for i in range(n)],
        "frozen": [0.0] * n,
    }
    with_frozen = panel_of(rets)
    twin = ets_mod.with_cash_sleeve(with_frozen, ["a", "b", "c"], 1)

    m1 = ets_mod.ecr.portfolio_metrics(
        with_frozen, ets_mod.arm_weights(with_frozen, "cal", 1, 20))
    m2 = ets_mod.ecr.portfolio_metrics(twin, ets_mod.arm_weights(twin, "cal", 1, 20))
    for key in ("apy", "maxdd", "calmar", "deployed", "turnover_yr", "net_apy_after_cost"):
        assert m1[key] == pytest.approx(m2[key], abs=1e-12), (
            f"{key} differs between a frozen book and a named cash sleeve — the control that "
            "carries idea #54's central claim no longer holds"
        )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. CRITERION vs GATE — the structural separation the entry rests on
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_gate_retires_a_dead_book_that_the_criterion_alone_keeps():
    n = 500
    rets = {
        "winner": dense(n, 3e-4),
        "loser": dense(n, -2e-4),
        "dead": dies(n, 1e-4, 99),
    }
    p = panel_of(rets)
    plain = ets_mod.arm_flags(p, "cal", 1, 20)
    gated = ets_mod.arm_flags(p, "cal_gate", 1, 20)
    late = n - 1
    assert not plain["dead"][late], (
        "CAL alone keeps the dead book: score 0.00 beats the loser's negative drift — this is the "
        "defect #54 measures"
    )
    assert plain["loser"][late], "the loser should be the one demoted by the plain rank rule"
    assert gated["dead"][late], "the darkness gate must retire the dead book"
    assert gated["loser"][late], "the gate must not un-demote what the rank rule already caught"


def test_gate_only_arm_uses_no_cross_sectional_information():
    n = 400
    p = panel_of({"a": dense(n, 3e-4), "b": dense(n, -2e-4), "dead": dies(n, 1e-4, 99)})
    w = ets_mod.arm_weights(p, "dark_only", 1, 20)
    late = n - 1
    assert w["dead"][late] == pytest.approx(0.0)
    assert w["a"][late] == pytest.approx(w["b"][late]), (
        "the gate-only arm must be blind to performance — if it prefers the winner it is not a "
        "gate any more and the decomposition in section 3 is not a decomposition"
    )


def test_arm_weights_rejects_an_unknown_arm():
    p = panel_of({"a": dense(100, 1e-4), "b": dense(100, 2e-4)})
    with pytest.raises(ValueError):
        ets_mod.arm_weights(p, "not_an_arm", 1, 1)


def test_synth_panel_refuses_a_ragged_or_empty_panel():
    with pytest.raises(ValueError):
        ets_mod.SynthPanel([], {"a": []})
    with pytest.raises(ValueError):
        ets_mod.SynthPanel(["d00000", "d00001"], {"a": [0.0]})


def test_sub_panel_refuses_a_book_it_does_not_have():
    p = panel_of({"a": dense(100, 1e-4), "b": dense(100, 2e-4)})
    with pytest.raises(KeyError):
        ets_mod.sub_panel(p, ["a", "ghost"])
