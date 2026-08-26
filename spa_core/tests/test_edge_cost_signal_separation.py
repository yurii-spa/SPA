"""
Regression guards for idea #80 CSS (scripts/edge_cost_signal_separation.py).

Every test here is a POSITIVE CONTROL: it fails on the un-fixed / mis-specified module
and states which real defect it replays.  A guard that has never seen a real breakage is
an ornament (.claude/rules/deployment.md).

The three load-bearing claims of #80, each pinned by a test below:
  1. the equal-weight baseline is cost-INVARIANT      -> the sweep compares like with like
  2. the relabel control is turnover-MATCHED EXACTLY  -> "same schedule, different book"
  3. bankruptcy is not mistaken for winning           -> the break-even artifact, replayed

No literal dates appear in this file (frozen-date ratchet, .claude/rules/deployment.md).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import edge_cost_signal_separation as css  # noqa: E402
import edge_mhfc_backtest as mh  # noqa: E402


@pytest.fixture(scope="module")
def panel():
    """Fixture panel, aligned exactly the way the script aligns it."""
    raw = mh._load_fixture()
    by_date = {}
    for sid, series in raw.items():
        dts, rets = mh._daily_returns(series)
        by_date[sid] = dict(zip(dts, rets))
    common = sorted(set.intersection(*[set(d.keys()) for d in by_date.values()]))
    book_rets = {sid: [by_date[sid][d] for d in common] for sid in sorted(by_date)}
    return book_rets, common


def test_equal_weight_baseline_is_cost_invariant(panel):
    """
    The baseline must not move when the toll moves, or the whole sweep is meaningless:
    every dCalmar in section 1 would then mix a change in the arm with a change in the
    yardstick.  Equal weight never trades after day 1, so its net series is identical at
    every cost.  Fails if a rebalancing baseline is ever substituted.
    """
    book_rets, dates = panel
    hist = css._weight_history(book_rets, dates, "eq")
    gross, turns = css._gross_and_turnover(hist, book_rets)

    assert sum(turns) == pytest.approx(0.0, abs=1e-12)
    cheap = css._net(gross, turns, 0.0)
    dear = css._net(gross, turns, 384.0)
    assert cheap == pytest.approx(dear, abs=1e-15)
    assert mh._calmar(cheap) == pytest.approx(mh._calmar(dear), abs=1e-12)


def test_relabel_control_preserves_turnover_exactly(panel):
    """
    The relabel control claims to hold the trading SCHEDULE fixed and change only WHICH
    book is flagged.  If relabelling moved turnover, the control would no longer be
    turnover-matched and the p-values in section 3 would compare two different tolls.
    Checked over ALL permutations, not a sample.
    """
    book_rets, dates = panel
    book_ids = sorted(book_rets.keys())
    hist = css._weight_history(book_rets, dates, "h20")
    _, turns = css._gross_and_turnover(hist, book_rets)
    base = sum(turns)
    assert base > 0.0, "h20 must actually trade, else the control proves nothing"

    for perm in itertools.permutations(book_ids):
        _, t2 = css._gross_and_turnover(
            css._relabel(hist, perm, book_ids), book_rets
        )
        assert sum(t2) == pytest.approx(base, abs=1e-9)


def test_relabel_actually_changes_the_portfolio(panel):
    """
    Guard against a vacuous control: if _relabel returned the weights unchanged, the
    turnover test above would still pass and the p-values would silently become 1/120 by
    construction.  At least one permutation must move the gross return series.
    """
    book_rets, dates = panel
    book_ids = sorted(book_rets.keys())
    hist = css._weight_history(book_rets, dates, "h20")
    gross, _ = css._gross_and_turnover(hist, book_rets)

    moved = False
    for perm in itertools.permutations(book_ids):
        if list(perm) == book_ids:
            continue
        g2, _ = css._gross_and_turnover(css._relabel(hist, perm, book_ids), book_rets)
        if any(abs(a - b) > 1e-12 for a, b in zip(gross, g2)):
            moved = True
            break
    assert moved, "relabelling never changed the portfolio — the control is vacuous"


def test_net_is_exactly_linear_in_cost():
    """
    Section 1 computes gross/turnover ONCE and reprices at eight tolls.  That shortcut is
    only sound if net(c) is exactly gross - turnover*c/1e4.  Fails if a cost model with
    memory (or one applied to net equity) is introduced -- the very feedback #10 recorded
    as its methodological finding.
    """
    gross = [0.01, -0.02, 0.003, 0.0]
    turns = [0.0, 0.5, 1.25, 0.1]
    for c in (0.0, 12.0, 96.0, 384.0):
        got = css._net(gross, turns, c)
        want = [g - t * c / 10_000.0 for g, t in zip(gross, turns)]
        assert got == pytest.approx(want, abs=1e-15)


def test_degenerate_guard_flags_paths_through_zero_equity():
    """
    POSITIVE CONTROL — replays the artifact the first run of this script actually printed.

    mh._apy() returns 0.0 when compounded equity is <= 0.  On this fixture the baseline
    Calmar is NEGATIVE (-0.18), so 0.0 scores as BETTER than the baseline: a bankrupt path
    reads as "still winning" and the bisection reported a break-even of ">10000 bps" for
    the single worst arm on the board.  _degenerate() is what closes that.
    """
    survives = [0.001] * 50
    assert not css._degenerate(survives)

    wiped_out = [-1.5] + [0.001] * 49          # one day below -100%: equity crosses zero
    assert css._degenerate(wiped_out)

    # Merely shrinking is NOT degenerate and must not be flagged: 0.5**200 is ~6e-61,
    # still positive, and mh._apy() handles it honestly (no artifact to guard against).
    assert not css._degenerate([-0.5] * 200)

    # ...but shrinking far enough UNDERFLOWS the double to exactly 0.0, which puts
    # mh._apy() back on its compound <= 0 branch and returns 0.0 again.
    assert css._degenerate([-0.5] * 1200)


def test_breakeven_never_reports_a_win_on_a_bankrupt_path():
    """
    POSITIVE CONTROL — the same artifact, seen through the function that published it.

    An arm that is barely positive when free must get a SMALL break-even.  Unguarded, the
    bisection reads the BANKRUPT end of its range as a win, never brings the upper bound
    down, and prints ">2000 bps" for the worst arm on the board.

    Two earlier drafts of this test were ORNAMENTS, and both failure modes are worth
    naming because they generalise:

    - draft 1 asserted on _degenerate() alone.  Deleting the guard's CALL SITE left it
      green: it tested the part, not the wiring.
    - draft 2 wired it up but chose turnover=8.0/day.  That puts the artifact in a
      NON-MONOTONE POCKET in the middle of the range (at 1250 bps equity underflows to
      zero, mh._apy() returns 0.0, and 0.0 beats this negative baseline) -- but bisection
      probes 1000 first, finds a loss, and steps straight over the pocket.  Green by luck
      of the search path, not by correctness.

    The pocket must therefore sit AT THE CEILING, which pins turnover near
    MAX_COST_SEARCH/1e4 = 5.0/day: there net(ceiling) is just above -100%, so 1+r is a
    small positive number that underflows to zero over the series.  The precondition below
    asserts exactly that, so the test can never silently stop exercising the guard again.
    """
    n = 400
    gross = [0.0005] * (n - 1) + [-0.002]  # one down day, so maxDD is non-zero and finite
    turns = [5.0] * n                      # places the underflow pocket at the ceiling
    base_calmar = -0.18                    # negative baseline == the trap's precondition

    ceiling_net = css._net(gross, turns, css.MAX_COST_SEARCH)
    assert css._degenerate(ceiling_net), (
        "precondition: the top of the search range must be a bankrupt path, "
        "otherwise this test does not exercise the guard at all"
    )
    assert mh._calmar(ceiling_net) - base_calmar > 0.0, (
        "precondition: unguarded, that bankrupt ceiling must LOOK like a win"
    )

    verdict, d0 = css._breakeven_cost(gross, turns, base_calmar)
    assert d0 > 0.0, "precondition: the arm must win at zero cost, else the test is moot"
    assert not verdict.startswith(">"), f"bisection escaped to the ceiling: {verdict}"
    assert verdict.endswith(" bps")
    assert float(verdict.split()[0]) < 100.0


def test_arm_that_loses_when_free_has_no_breakeven():
    """The (B) STRUCTURAL branch must be reachable and must be reported as such."""
    gross = [-0.001] * 200
    turns = [0.5] * 200
    verdict, d0 = css._breakeven_cost(gross, turns, 0.0)
    assert d0 <= 0.0
    assert verdict == "none (loses at c=0)"


def test_rotation_preserves_turnover_up_to_one_wrap_day(panel):
    """
    The rotation control destroys WHEN while keeping the schedule's own structure.  Its
    turnover may differ only at the single wrap day; a larger drift would mean rotation
    silently changed the toll as well as the timing.
    """
    book_rets, dates = panel
    hist = css._weight_history(book_rets, dates, "h20")
    _, turns = css._gross_and_turnover(hist, book_rets)
    base = sum(turns)
    max_daily = max(turns)

    for k in range(css.ROTATION_STEP, len(hist), css.ROTATION_STEP * 13):
        _, t2 = css._gross_and_turnover(css._rotate(hist, k), book_rets)
        assert abs(sum(t2) - base) <= 2.0 * max_daily + 1e-9


def test_anchor_reproduces_idea79_published_numbers(panel):
    """
    #80 reuses idea #79's rule verbatim, so at the convention cost it MUST reproduce the
    numbers published in the registry for #79.  If this drifts, #80's cost sweep is
    measuring a different instrument than the six negatives it claims to re-read.
    Published (docs/DYNAMIC_LEVERAGE_GUARDIAN.md, #79): MHFC APY -14.73%, Calmar -0.46.
    """
    book_rets, dates = panel
    hist = css._weight_history(book_rets, dates, "mhfc")
    gross, turns = css._gross_and_turnover(hist, book_rets)
    net = css._net(gross, turns, css.CONVENTION_COST)

    assert mh._apy(net) * 100 == pytest.approx(-14.73, abs=0.01)
    assert mh._calmar(net) == pytest.approx(-0.46, abs=0.01)
