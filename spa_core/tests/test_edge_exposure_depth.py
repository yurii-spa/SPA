"""Tests for registry ideas #47 (PDD, partial demotion depth) and #48 (PKP, portfolio kill path).

Both entries rest on PROPERTIES rather than on numbers, and both verdicts are only worth as much
as those properties are pinned:

  #47's whole verdict is an identity — a partially demoted portfolio is EXACTLY the convex
  combination of the raw panel and the fully demoted one, day by day and cell by cell. If that
  identity ever stopped holding, the entry's conclusion ("the depth axis is a blend knob, not a
  new rule") would become false without a single number changing, so it is the first test here
  and it is checked to machine precision, not to two decimals.

  #48's verdict rests on the ladder's state machine behaving the way ADR-034/048 says: HARD is
  absorbing, SOFT is *no INCREASE* rather than a liquidation, and every tier decision is causal.
  The auto-re-arm counterfactual gets its own positive control because the first implementation of
  it silently could not re-arm at all (the realised drawdown is frozen while the kill is on, so a
  latch checked against the realised path can only ever latch) and reported the absorbing rule
  under the counterfactual's name. That failure is replayed by
  `test_auto_rearm_actually_rearms_after_shadow_recovery`.

No literal dates and no dependency on data/: every fixture is a synthetic panel built in-process,
so this file is identical in CI and on the host.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Dict, List, Sequence

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


exd = _load("edge_exposure_depth")
ecr = _load("edge_capital_recycling")


class FakePanel:
    """The minimum a panel has to be for these two mechanisms: books, an axis and returns.

    Deliberately NOT the real `dgo.Panel` — that one reads nightly artefacts from data/, which are
    absent in CI and different every day, and neither property under test needs a real market.
    """

    def __init__(self, rets: Dict[str, Sequence[float]]) -> None:
        self.books = sorted(rets)
        self.rets = {b: list(rets[b]) for b in self.books}
        self.n_days = len(self.rets[self.books[0]])
        self.axis = [f"d{i:04d}" for i in range(self.n_days)]

    @property
    def n(self) -> int:
        return self.n_days


def _flags(books: Sequence[str], n: int, demoted_of: Dict[int, Sequence[str]]
           ) -> Dict[str, List[bool]]:
    return {b: [b in demoted_of.get(i, ()) for i in range(n)] for b in books}


BOOKS = ["a", "b", "c", "d"]
N = 6
FLAGS = _flags(BOOKS, N, {0: (), 1: ("a",), 2: ("a", "b"), 3: ("c",), 4: (), 5: ("d",)})


# ═════════════════════════════ #47 — PDD: depth is a blend knob ═════════════════════════════
def test_depth_zero_is_exactly_equal_weight():
    """h=0 must not merely *resemble* the raw panel — it must BE it, or the table's left edge is
    not the baseline it claims to be."""
    w = exd.alloc_partial(BOOKS, FLAGS, N, 0.0)
    for b in BOOKS:
        for i in range(N):
            assert w[b][i] == pytest.approx(0.25, abs=1e-15)


def test_depth_one_is_exactly_the_registry_allocator():
    """h=1 must reproduce `ecr.alloc_recycle` cell for cell — the right edge of the table IS #40,
    so the whole entry can be read as one continuous knob rather than as a menu of rules."""
    mine = exd.alloc_partial(BOOKS, FLAGS, N, 1.0)
    theirs = ecr.alloc_recycle(BOOKS, FLAGS, N)
    for b in BOOKS:
        for i in range(N):
            assert mine[b][i] == pytest.approx(theirs[b][i], abs=1e-15)


@pytest.mark.parametrize("h", [0.1, 0.25, 0.5, 0.73, 0.9])
def test_partial_depth_is_the_exact_convex_combination(h):
    """THE claim of entry #47: PDD(h) = (1−h)·raw + h·#40, exactly.

    This is why the depth axis carries no new information: every intermediate row is a fixed-weight
    blend of two portfolios the registry already owns. Machine precision, because the verdict is
    "identity", not "approximately".
    """
    raw = exd.alloc_partial(BOOKS, FLAGS, N, 0.0)
    full = exd.alloc_partial(BOOKS, FLAGS, N, 1.0)
    mix = exd.alloc_partial(BOOKS, FLAGS, N, h)
    for b in BOOKS:
        for i in range(N):
            assert mix[b][i] == pytest.approx((1 - h) * raw[b][i] + h * full[b][i], abs=1e-15)


def test_convex_combination_claim_is_falsifiable():
    """Positive control for the test above: a non-linear depth rule must BREAK the identity.

    Without this, `test_partial_depth_is_the_exact_convex_combination` would also pass on a module
    that had quietly become linear-only by accident, and the entry's central claim would rest on a
    test that cannot fail.
    """
    raw = exd.alloc_partial(BOOKS, FLAGS, N, 0.0)
    full = exd.alloc_partial(BOOKS, FLAGS, N, 1.0)
    h = 0.5
    squashed = exd.alloc_partial(BOOKS, FLAGS, N, math.sqrt(h))   # a plausible non-linear dial
    deviations = [abs(squashed[b][i] - ((1 - h) * raw[b][i] + h * full[b][i]))
                  for b in BOOKS for i in range(N)]
    assert max(deviations) > 1e-6


def test_weights_sum_to_one_when_no_cap_binds():
    for h in (0.0, 0.3, 1.0):
        w = exd.alloc_partial(BOOKS, FLAGS, N, h)
        for i in range(N):
            assert sum(w[b][i] for b in BOOKS) == pytest.approx(1.0, abs=1e-12)


def test_cap_is_never_breached_and_the_remainder_becomes_cash():
    """An over-capped panel must leave capital uninvested rather than quietly exceed the limit —
    the same treatment `ecr._waterfill` gives, so a cap can never be a suggestion."""
    flags = _flags(BOOKS, 1, {0: ("a", "b")})       # two eligible names, cap 0.20 ⇒ 40% placeable
    w = exd.alloc_partial(BOOKS, flags, 1, 1.0, cap=0.20)
    assert max(w[b][0] for b in BOOKS) <= 0.20 + 1e-12
    assert sum(w[b][0] for b in BOOKS) == pytest.approx(0.40, abs=1e-12)


def test_no_eligible_book_is_fail_closed():
    """When the rule demotes everything, the freed slice waits in cash. Pushing it back into the
    books the rule just cut would be the silent fabrication this family refuses."""
    flags = _flags(BOOKS, 1, {0: tuple(BOOKS)})
    w = exd.alloc_partial(BOOKS, flags, 1, 0.6)
    for b in BOOKS:
        assert w[b][0] == pytest.approx(0.4 * 0.25, abs=1e-15)
    assert sum(w[b][0] for b in BOOKS) < 1.0


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_depth_outside_the_unit_interval_is_refused(bad):
    with pytest.raises(ValueError):
        exd.alloc_partial(BOOKS, FLAGS, N, bad)


def test_zero_cap_is_refused():
    with pytest.raises(ValueError):
        exd.alloc_partial(BOOKS, FLAGS, N, 0.5, cap=0.0)


def test_depth_allocator_reads_only_today_flags():
    """Weights for day i must not move when a LATER day's flag changes — the depth dial adds no
    look-ahead of its own on top of the (already causal) rank machinery."""
    base = exd.alloc_partial(BOOKS, FLAGS, N, 0.5)
    tampered = {b: list(FLAGS[b]) for b in BOOKS}
    tampered["a"][N - 1] = not tampered["a"][N - 1]
    after = exd.alloc_partial(BOOKS, tampered, N, 0.5)
    for b in BOOKS:
        for i in range(N - 1):
            assert after[b][i] == pytest.approx(base[b][i], abs=1e-15)


# ═════════════════════════════ #48 — PKP: the two-tier ladder ═════════════════════════════
def _target(panel: "FakePanel") -> Dict[str, List[float]]:
    return {b: [1.0 / len(panel.books)] * panel.n for b in panel.books}


def _crash_panel(down_days: int = 20, up_days: int = 60, step: float = -0.01) -> FakePanel:
    """One book that falls steadily and then recovers — deep enough to cross both tiers."""
    path = [step] * down_days + [0.004] * up_days
    return FakePanel({"a": path, "b": path})


def test_green_regime_leaves_the_target_untouched():
    """If the drawdown never reaches the SOFT tier, the ladder must be a byte-for-byte no-op.
    An arm that perturbs a portfolio it was never triggered on is a cost with no mandate."""
    panel = FakePanel({"a": [0.001] * 40, "b": [0.002] * 40})
    target = _target(panel)
    w, diag = exd.apply_kill_path(panel, target)
    assert diag["soft_days"] == 0 and diag["hard_days"] == 0
    for b in panel.books:
        for i in range(panel.n):
            assert w[b][i] == pytest.approx(target[b][i], abs=1e-15)


def test_hard_kill_is_absorbing_without_rearm():
    """ADR-034's HARD_KILL needs an owner to clear. A backtest that re-armed itself would be
    reporting a rule nobody sanctioned, so absorption is pinned rather than assumed."""
    panel = _crash_panel()
    w, diag = exd.apply_kill_path(panel, _target(panel))
    assert diag["hard_days"] > 0
    first_dead = min(i for i in range(panel.n) if all(w[b][i] == 0.0 for b in panel.books))
    for i in range(first_dead, panel.n):
        assert all(w[b][i] == 0.0 for b in panel.books)


def test_auto_rearm_actually_rearms_after_shadow_recovery():
    """POSITIVE CONTROL replaying a real defect (2026-08-10, this module's first draft).

    While the kill is on, live equity is flat, so the REALISED drawdown never moves. The first
    implementation evaluated the kill test before the re-arm test and against that frozen path, so
    the latch could never clear: the counterfactual produced numbers identical to the absorbing
    rule and looked like a finding ("re-arm changes nothing") instead of a bug. This test fails on
    that implementation and passes on the one that checks the SHADOW path first.
    """
    panel = _crash_panel()
    absorbing, diag_a = exd.apply_kill_path(panel, _target(panel))
    rearmed, diag_r = exd.apply_kill_path(panel, _target(panel), hard_rearm_days=5)
    assert diag_a["hard_days"] > diag_r["hard_days"] > 0
    assert any(rearmed[b][i] > 0.0 for b in panel.books
               for i in range(panel.n) if absorbing[b][i] == 0.0)


def test_rearm_needs_the_full_dwell_of_clean_shadow_days():
    """A longer re-arm dwell can only keep the book dead longer — a monotonicity the counterfactual
    would be meaningless without."""
    panel = _crash_panel()
    _, short = exd.apply_kill_path(panel, _target(panel), hard_rearm_days=5)
    _, long_ = exd.apply_kill_path(panel, _target(panel), hard_rearm_days=20)
    assert long_["hard_days"] >= short["hard_days"]


def test_soft_freeze_never_increases_a_weight():
    """SOFT_DERISK is *halt new / no INCREASE (hold+reduce OK)*. Pinned as an inequality, because
    the tier's whole meaning is the direction weights are allowed to move."""
    panel = FakePanel({"a": [-0.004] * 30 + [0.002] * 30,
                       "b": [-0.006] * 30 + [0.003] * 30})
    # a target that WANTS to raise weights on the days the tier is active
    target = {"a": [0.2 + 0.01 * i for i in range(panel.n)],
              "b": [0.2 + 0.01 * i for i in range(panel.n)]}
    w, diag = exd.apply_kill_path(panel, target, soft_dd=0.02, hard_dd=0.50, mode="freeze")
    assert diag["soft_days"] > 0
    for b in panel.books:
        for i in range(1, panel.n):
            assert w[b][i] <= w[b][i - 1] + 1e-12 or w[b][i] <= target[b][i] + 1e-12
    assert any(w[b][i] < target[b][i] - 1e-9 for b in panel.books for i in range(panel.n))


def test_soft_freeze_is_a_no_op_on_a_constant_weight_portfolio():
    """The structural finding of entry #48, pinned so it cannot quietly stop being true: on a book
    whose weights never rise, "no INCREASE" has nothing to forbid — the tier fires and changes
    nothing. It is the reason the ladder's SOFT leg costs exactly zero on the raw panel."""
    panel = FakePanel({"a": [-0.004] * 30 + [0.002] * 30,
                       "b": [-0.006] * 30 + [0.003] * 30})
    target = _target(panel)
    w, diag = exd.apply_kill_path(panel, target, soft_dd=0.02, hard_dd=0.50, mode="freeze")
    assert diag["soft_days"] > 0
    for b in panel.books:
        for i in range(panel.n):
            assert w[b][i] == pytest.approx(target[b][i], abs=1e-15)


def test_soft_haircut_scales_the_target():
    """The haircut mode is the labelled sensitivity, and it must be a strictly stronger action than
    the tier — otherwise the table would be comparing the ladder against itself."""
    panel = FakePanel({"a": [-0.004] * 30 + [0.002] * 30,
                       "b": [-0.006] * 30 + [0.003] * 30})
    target = _target(panel)
    w, diag = exd.apply_kill_path(panel, target, soft_dd=0.02, hard_dd=0.50,
                                  mode="haircut", soft_gross=0.5)
    assert diag["soft_days"] > 0
    soft_cells = [(b, i) for b in panel.books for i in range(panel.n)
                  if w[b][i] < target[b][i] - 1e-12]
    assert soft_cells
    for b, i in soft_cells:
        assert w[b][i] == pytest.approx(0.5 * target[b][i], abs=1e-12)


J_SHOCK = 10          # the single day the causality pair perturbs


def _flat_panel_with_shock(shock: float = 0.0, n: int = 30) -> FakePanel:
    """A perfectly flat panel with one day's return replaced by `shock`.

    Flat means the ladder is green everywhere and every weight equals its target — so ANY change
    the perturbation causes is attributable to that one day and to nothing else. A shock of −30%
    is far past both tiers, which is what makes the direction of the effect readable: a causal
    ladder cuts the day AFTER it, a look-ahead one cuts the day ITSELF.
    """
    path = [0.0] * n
    path[J_SHOCK] = shock
    return FakePanel({"a": list(path), "b": list(path)})


def test_kill_path_is_causal_in_the_returns():
    """The tier for day i is decided from the equity path through i−1 — so a −30% day cannot cut
    its OWN exposure, only the exposure of the days that follow it."""
    target = _target(_flat_panel_with_shock())
    before, _ = exd.apply_kill_path(_flat_panel_with_shock(), target)
    after, diag = exd.apply_kill_path(_flat_panel_with_shock(-0.30), target)
    for b in ("a", "b"):
        for i in range(J_SHOCK + 1):
            assert after[b][i] == pytest.approx(before[b][i], abs=1e-15), (b, i)
    assert diag["hard_days"] > 0                    # the arm DID react — just not retroactively


def test_causality_check_is_falsifiable():
    """POSITIVE CONTROL for the pair: on the flat panel the ladder is green everywhere, so a rule
    that looked at day i's own return would have to cut day `J_SHOCK` itself. This asserts the
    exposure of the very NEXT day moves — without it, a ladder that ignored the equity path
    entirely (never firing at all) would sail through the causality test above.
    """
    target = _target(_flat_panel_with_shock())
    before, _ = exd.apply_kill_path(_flat_panel_with_shock(), target)
    after, _ = exd.apply_kill_path(_flat_panel_with_shock(-0.30), target)
    assert any(abs(after[b][J_SHOCK + 1] - before[b][J_SHOCK + 1]) > 1e-9 for b in ("a", "b"))


@pytest.mark.parametrize("kwargs", [
    {"mode": "scale"},                       # unknown SOFT semantics
    {"soft_dd": 0.0},                        # a tier that fires on no drawdown at all
    {"soft_dd": 0.2, "hard_dd": 0.1},        # SOFT deeper than HARD
    {"hard_rearm_days": 0},                  # re-arm on no evidence
])
def test_ladder_refuses_incoherent_configuration(kwargs):
    panel = _crash_panel(down_days=3, up_days=3)
    with pytest.raises(ValueError):
        exd.apply_kill_path(panel, _target(panel), **kwargs)


def test_amplification_preserves_sign_and_ordering():
    """The positive control of entry #48 amplifies returns to reach the tiers. It is only a control
    if it changes the SCALE and nothing else — same days, same signs, same relative ordering."""
    panel = _crash_panel(down_days=5, up_days=5)
    scaled = exd._ScaledPanel(panel, 3.0)
    assert scaled.axis == panel.axis and scaled.books == panel.books
    for b in panel.books:
        for i in range(panel.n):
            assert scaled.rets[b][i] == pytest.approx(3.0 * panel.rets[b][i], abs=1e-15)


def test_amplification_refuses_a_non_positive_scale():
    panel = _crash_panel(down_days=3, up_days=3)
    with pytest.raises(ValueError):
        exd._ScaledPanel(panel, 0.0)


def test_module_declares_itself_advisory_and_outside_riskpolicy():
    """Every R&D module of this family carries the two flags that keep it out of the money path."""
    assert exd.IS_ADVISORY is True
    assert exd.OUTSIDE_RISKPOLICY is True
    assert (exd.SOFT_DD, exd.HARD_DD) == (0.05, 0.10)     # ADR-034/048, read here, never written
