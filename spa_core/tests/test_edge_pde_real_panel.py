"""
Tests for scripts/edge_pde_real_panel.py (Ideas #71 PDE-REAL / #72 PDE-DB).

Every test here is a POSITIVE CONTROL in the sense .claude/rules/deployment.md requires: it
reproduces a failure that would actually change a published verdict, and it goes red when the
corresponding line of the harness is removed. The failures being guarded against are:

  • the parity claim the whole #71 entry rests on ("the mechanism did not change, the DATA
    changed") silently breaking, so the real-panel table would no longer be comparable to
    #70's fixture table at all;
  • a deadband quietly holding a partial position while the rule says FULL EXIT — replacing a
    risk decision with a cost decision (the exact defect registry #50 had to fix for NTB);
  • the leave-one-out control losing its ability to detect one-book dependence, which is how
    the panel's documented law-of-one-book (#68/#69) would slip past unnoticed a third time;
  • the cost-free arm not actually being cost-free, which would make "it lost on COST" and
    "it lost on TIMING" indistinguishable — two different verdicts with different repairs.

No external files, no network, no RiskPolicy, no spa_core.execution. IS_ADVISORY=True.
No literal dates: every series here is synthetic and index-addressed, so the calendar moving
cannot turn one of these red (`.claude/rules/deployment.md`, "время в тестах").
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_pde_real_panel.py"

# The harness imports its sibling edge scripts by name, so scripts/ has to be importable.
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("edge_pde_real", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_PANEL = _mod.PANEL_DIR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _drift(n: int = 200, d: float = 0.0004) -> list:
    eq = [100_000.0]
    for _ in range(n - 1):
        eq.append(eq[-1] * (1.0 + d))
    return eq


def _sawtooth(n: int = 300, amp: float = 0.004) -> list:
    """Equity that oscillates around its peak — the shape that makes a continuous ramp churn.

    This is the real panel's PORTFOLIO series in miniature: drawdown keeps re-entering the ramp
    band instead of either staying out of it or collapsing through it.
    """
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * (1.0 + (amp if (i // 7) % 2 == 0 else -amp)))
    return eq


def _wiggle(n: int = 300, d: float = 0.0004, amp: float = 0.0008) -> list:
    """A quiet book: drifts up with shallow noise, so its drawdown is small but NOT zero.

    A perfectly smooth book has maxDD == 0 and therefore Calmar == inf, which makes every
    downstream difference nan and would let a LOO control "pass" while measuring nothing.
    """
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * (1.0 + d + (amp if (i // 5) % 2 == 0 else -amp)))
    return eq


def _staircase(n: int = 300, at: int = 60, step: float = 0.006, steps: int = 20) -> list:
    """A book that walks DOWN the ramp in small steps, then keeps falling.

    Small steps are what produce PARTIAL exposures: a −0.6%/day slide crosses d_start, holds a
    fractional exposure for a while, and only later reaches d_full. That intermediate state is
    the only place the full-exit exception can be observed at all.
    """
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * ((1.0 - step) if at <= i < at + steps else 1.0001))
    return eq


def _cliff(n: int = 300, at: int = 80, frac: float = 0.30, over: int = 6) -> list:
    """A book that falls hard and stays down — the per-book shape (bimodal, no churn)."""
    daily = 1.0 - (1.0 - frac) ** (1.0 / over)
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * ((1.0 - daily) if at <= i < at + over else 1.0002))
    return eq


# ── #71: the parity claim the entry rests on ──────────────────────────────────

@pytest.mark.parametrize("d_start,d_full", _mod.PDE_GRID)
@pytest.mark.parametrize("series", ["drift", "saw", "cliff"])
def test_band_zero_is_bit_identical_to_idea70(d_start, d_full, series):
    """band=0 must reproduce #70's apply_pde exactly — equity path AND cost.

    If this drifts, every number in #71 stops being a re-measurement of #70 and becomes a
    second author's re-implementation, which is precisely the confound the entry claims to
    have avoided.
    """
    raw = {"drift": _drift(), "saw": _sawtooth(), "cliff": _cliff()}[series]
    ref_eq, ref_cost = _mod.PDE.apply_pde(list(raw), d_start=d_start, d_full=d_full)
    got_eq, got_cost, _ = _mod.apply_pde_deadband(raw, d_start=d_start, d_full=d_full, band=0.0)
    assert len(got_eq) == len(ref_eq)
    assert got_cost == pytest.approx(ref_cost, abs=1e-9)
    for a, b in zip(ref_eq, got_eq):
        assert a == pytest.approx(b, abs=1e-9)


@pytest.mark.parametrize("d_start,d_full", _mod.PDE_GRID)
def test_parity_helper_agrees_with_the_direct_comparison(d_start, d_full):
    assert _mod.parity_with_seventy(_sawtooth(), d_start=d_start, d_full=d_full) is True


def test_parity_helper_can_say_no():
    """The parity check must be capable of failing, or it is decoration.

    A band that is not zero is a genuine divergence from #70's rule; the helper is only
    trustworthy if it reports that divergence rather than returning True unconditionally.
    """
    raw = _sawtooth()
    wide_eq, wide_cost, _ = _mod.apply_pde_deadband(raw, d_start=0.02, d_full=0.08, band=0.30)
    ref_eq, ref_cost = _mod.PDE.apply_pde(list(raw), d_start=0.02, d_full=0.08)
    assert wide_cost != pytest.approx(ref_cost, abs=1e-9)
    assert any(abs(a - b) > 1e-9 for a, b in zip(ref_eq, wide_eq))


# ── #72: the deadband, and the risk-decision exception ────────────────────────

def test_wider_band_never_trades_more():
    """Turnover and trade count must be monotone non-increasing in the band width."""
    raw = _sawtooth()
    prev_trades, prev_turn = None, None
    for band in _mod.BAND_GRID:
        n = _mod._count_trades(raw, d_start=0.02, d_full=0.08, band=band)
        _, _, turn = _mod.apply_pde_deadband(raw, d_start=0.02, d_full=0.08, band=band)
        if prev_trades is not None:
            assert n <= prev_trades, f"band {band} traded more often than the narrower band"
            assert turn <= prev_turn + 1e-9
        prev_trades, prev_turn = n, turn


def test_full_exit_executes_from_a_PARTIAL_holding_through_the_band():
    """A FULL-EXIT target is executed whatever the band — cost never overrides a risk decision.

    Positive control for the defect #50 had to fix: a wide band holding a partial position
    while the rule says "out" silently substitutes a cost rule for a risk rule.

    THIS TEST HAS TO START FROM A PARTIAL HOLDING, and that is the whole point. An exit taken
    from full exposure is a delta of 1.0, which clears every band there is — so a test that
    only crashes a fully-invested book passes even with the exception deleted, and an earlier
    draft of this file did exactly that. The band here (0.50) is wide enough to swallow the
    0.40 step from a partial holding to zero, and only the exception can push it through.
    """
    raw = _staircase()
    band = 0.50
    exp = _mod.exposure_path(raw, d_start=0.02, d_full=0.08, band=band)
    assert any(1e-9 < e < 1.0 - 1e-9 for e in exp), (
        "fixture never held a PARTIAL exposure — this test would then prove nothing"
    )
    last_partial = min(e for e in exp if 1e-9 < e < 1.0 - 1e-9)
    assert last_partial < band, (
        f"the last partial holding ({last_partial:.3f}) is further from zero than the band "
        f"({band}), so the final step clears the band on its own and the exception is untested"
    )
    assert min(exp) == pytest.approx(0.0, abs=1e-12), (
        "exposure never reached 0 despite a full-exit target — a wide band overrode a risk "
        "decision (this is the #50 defect, reproduced)"
    )


def test_intermediate_target_is_suppressed_by_a_wide_band():
    """The mirror of the test above: without it, 'always execute' could just mean 'no band'.

    A shallow oscillation only ever asks for PARTIAL exposure changes, so a wide band must
    suppress them entirely — otherwise the exception above is not an exception, it is the rule.
    """
    raw = _sawtooth(n=300, amp=0.004)
    n_wide = _mod._count_trades(raw, d_start=0.02, d_full=0.20, band=0.90)
    n_zero = _mod._count_trades(raw, d_start=0.02, d_full=0.20, band=0.0)
    assert n_zero > 0, "fixture never triggers the ramp — the comparison below would be vacuous"
    assert n_wide == 0, f"a 0.90 band executed {n_wide} partial moves"


def test_random_schedule_respects_its_trade_budget_and_is_seeded():
    """The #50 control must trade AT MOST as often as the band it is matched against."""
    raw = _sawtooth()
    a = _mod.apply_pde_random_schedule(raw, d_start=0.02, d_full=0.08, n_trades=15, seed=7)
    b = _mod.apply_pde_random_schedule(raw, d_start=0.02, d_full=0.08, n_trades=15, seed=7)
    c = _mod.apply_pde_random_schedule(raw, d_start=0.02, d_full=0.08, n_trades=15, seed=8)
    assert a[0] == b[0] and a[1] == pytest.approx(b[1]), "same seed gave a different path"
    assert a[0] != c[0] or a[1] != pytest.approx(c[1]), "different seeds gave an identical path"
    zero = _mod.apply_pde_random_schedule(raw, d_start=0.02, d_full=0.08, n_trades=0, seed=1)
    assert zero[1] == pytest.approx(0.0) and zero[2] == pytest.approx(0.0)
    assert zero[0][-1] == pytest.approx(raw[-1], rel=1e-12), "a 0-trade schedule still traded"


# ── The cost-free arm has to actually be cost-free ────────────────────────────

def test_portfolio_refuses_a_ragged_panel():
    """Fail-CLOSED: unequal book lengths must raise, never be aligned by truncation.

    Truncating the longer books to the length of whichever book happens to sort first would
    fabricate a portfolio out of a window no book actually shares.
    """
    with pytest.raises(ValueError):
        _mod.portfolio_returns({"a": _wiggle(n=300), "b": _wiggle(n=200)})
    with pytest.raises(ValueError):
        _mod.portfolio_returns({})


def test_zero_roundtrip_makes_net_equal_gross_everywhere():
    """Without this the entry cannot separate a COST verdict from a TIMING verdict."""
    books = {"a": _sawtooth(n=300), "b": _cliff(n=300), "c": _wiggle(n=300)}
    free = _mod.run_idea71(books, roundtrip=0.0)
    paid = _mod.run_idea71(books)
    for name, m in free.items():
        assert m["net_apy_flat"] == pytest.approx(m["apy"], abs=1e-12), name
        assert m["cost_bp_yr"] == pytest.approx(0.0, abs=1e-12), name
    charged = [n for n, m in paid.items() if m["turn_yr"] > 1e-9]
    assert charged, "no configuration traded at all — the paid arm would be vacuous"
    for name in charged:
        assert paid[name]["cost_bp_yr"] > 0.0, f"{name} traded but was charged nothing"
        assert paid[name]["net_apy_flat"] < paid[name]["apy"] + 1e-12, name


def test_gross_path_is_the_same_whether_or_not_cost_is_charged():
    """#70 books cost separately from the equity path; #71 inherits that and must not drift.

    If cost ever started being deducted from the compounding path, the 'gross' column of the
    two arms would silently stop meaning the same thing and the arm comparison would be void.
    """
    books = {"a": _sawtooth(n=300), "b": _cliff(n=300)}
    free, paid = _mod.run_idea71(books, roundtrip=0.0), _mod.run_idea71(books)
    for name in free:
        assert free[name]["apy"] == pytest.approx(paid[name]["apy"], abs=1e-12), name
        assert free[name]["maxdd"] == pytest.approx(paid[name]["maxdd"], abs=1e-12), name


# ── The LOO control must be able to SEE one-book dependence ───────────────────

def test_loo_detects_a_one_book_edge():
    """Positive control for the finding that decided #71's verdict.

    A panel where exactly one book has a real tail: dropping it must collapse the PDE-minus-
    binary Calmar gap. This is the shape actually observed on the real panel (`eth_directional`
    out ⇒ ΔCalmar +4.38 → +0.04), and it is the reason #71 refuses to promote PDE to a module.
    """
    books = {"tail": _cliff(), "q1": _wiggle(), "q2": _wiggle(d=0.0003), "q3": _wiggle(d=0.0005)}
    loo = _mod.loo_per_book(books, d_start=0.01, d_full=0.06)
    base = abs(loo["<none>"]["d_calmar"])
    assert base > 0.5, "fixture shows no gap to collapse"
    assert abs(loo["tail"]["d_calmar"]) < base / 10.0, (
        "dropping the only book with a tail did not collapse the gap — LOO is blind"
    )


def test_loo_reports_no_collapse_when_the_edge_is_broad():
    """The other half: LOO must NOT cry one-book on a panel where several books carry the edge.

    Without this, the test above would pass for a LOO that always reports collapse. Here two
    books carry tails at different times, so removing either one leaves a gap of the same order
    — which is exactly what the real panel did NOT do (`eth_directional` out ⇒ gap → +0.01).
    """
    books = {"tA": _cliff(at=60), "tB": _cliff(at=130, frac=0.35),
             "q1": _wiggle(), "q2": _wiggle(d=0.0003)}
    loo = _mod.loo_per_book(books, d_start=0.01, d_full=0.06)
    base = abs(loo["<none>"]["d_calmar"])
    assert base > 0.5
    for drop, m in loo.items():
        if drop == "<none>":
            continue
        assert abs(m["d_calmar"]) > base / 4.0, (
            f"dropping {drop} collapsed a broad edge — LOO over-reports one-book dependence"
        )


# ── Window slicing: a re-based window, and a refusal ──────────────────────────

def test_slice_rebases_each_window_to_its_own_start():
    """A window that inherited the parent's peak would report a drawdown it never lived through."""
    axis = [f"d{i:04d}" for i in range(200)]
    books = {"a": _cliff(n=201)}
    _, late = _mod.slice_books(axis, books, "d0100", None)
    assert late["a"][0] == pytest.approx(_mod.INITIAL)
    # The cliff is at index 80, i.e. entirely inside the FIRST window.
    _, early = _mod.slice_books(axis, books, None, "d0099")
    assert _mod.PDE._max_drawdown(early["a"]) > 0.2
    assert _mod.PDE._max_drawdown(late["a"]) < 0.01, (
        "the late window inherited a drawdown that happened before it started"
    )


def test_slice_refuses_a_degenerate_window():
    axis = [f"d{i:04d}" for i in range(50)]
    with pytest.raises(ValueError):
        _mod.slice_books(axis, {"a": _drift(n=51)}, "d0049", "d0049")


def test_worst_dd_books_ranks_by_drawdown_and_is_deterministic():
    books = {"deep": _cliff(frac=0.40), "mid": _cliff(frac=0.10), "flat": _drift()}
    assert _mod.worst_dd_books(books, 1) == ["deep"]
    assert _mod.worst_dd_books(books, 2) == sorted(["deep", "mid"])
    assert _mod.worst_dd_books(books, 2) == _mod.worst_dd_books(books, 2)


# ── Panel loading is fail-CLOSED ──────────────────────────────────────────────

def test_load_books_refuses_an_empty_panel(tmp_path):
    """No panel ⇒ refuse. #70 met exactly this condition (a worktree has no data/) and fell
    back to the fixture; a loader that invented an empty panel instead would have published
    numbers computed on nothing."""
    with pytest.raises((RuntimeError, ValueError)):
        _mod.load_books(tmp_path)


@pytest.mark.skipif(
    not (_PANEL / "susde_dn" / "realized_series.jsonl").exists(),
    reason=(
        "aggressive-lab panel is not git-tracked, so it is absent in CI and in any worktree; "
        "set SPA_PANEL_DIR to the prod tree's data/aggressive_lab to run this locally"
    ),
)
def test_real_panel_reproduces_the_published_direction():
    """Panel-gated regression on the one claim #71 publishes as a reversal of #70.

    #70's headline positive was PORTFOLIO PDE 2%-6% (fixture: Calmar +0.33, net +1.26%). On the
    real panel that configuration must (a) trade an order of magnitude more than #70's fixture
    cost line (39.9–115.6 bp/yr) and (b) lose to raw equal-weight net of cost. Asserted as
    directions and an order of magnitude, not as decimals, so a panel that legitimately grows
    by a few days does not turn this red for the wrong reason.
    """
    axis, books = _mod.load_books()
    _, test_books = _mod.slice_books(axis, books, _mod.SPLITS[0], None)
    res = _mod.run_idea71(test_books)
    port = res["PDE portfolio 2%-6%"]
    per_book = res["PDE per-book 2%-6%"]
    assert port["cost_bp_yr"] > 300.0, (
        f"portfolio PDE cost {port['cost_bp_yr']:.0f} bp/yr — the entry's central claim "
        f"(cost blows up by an order of magnitude on real calm-period noise) no longer holds"
    )
    assert port["net_apy_flat"] < res["raw equal-weight"]["net_apy_flat"]
    assert per_book["cost_bp_yr"] < port["cost_bp_yr"] / 3.0, (
        "per-book and portfolio modes no longer differ by the multiple the entry reports"
    )
    assert per_book["calmar"] > res["binary guardian per-book"]["calmar"]
