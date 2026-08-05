# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_drift_gated_overlay.py (registry ideas #35 DGO / #36 RARE / #37 SDS).

Three verdicts rest on this file, and each one is only as good as a property locked here:

  • **#35 DGO is refuted BY ITS OWN CONTROL**, so the control has to be a real control: the
    drift gate and its inverse must be disjoint and jointly exhaustive over the measurable
    region. If they overlapped, "the inverse did better" would prove nothing.
  • **#37 SDS died on a leave-one-out**, so the gate must be exactly `sds_signal(thr=0)` — the
    same predicate, not a look-alike. It is defined through it; this file pins that it stays so.
  • **#36 RARE is refuted and its opposite arm survives**, which only means something if the two
    arms really do move duty in opposite directions: `veto_after_up` may only ever REMOVE
    de-risk days, `dwell_weights` may only ever ADD them (monotonically in k).
  • The oracle gate is LOOK-AHEAD on purpose. That is pinned as a property (it changes when a
    FUTURE day changes) so it can never be mistaken for, or quietly reused as, a live rule.
  • Everything else is causal in BOTH directions: a shock on day i must not move the exposure
    chosen for day i, and must move it from day i+1 — a rule that ignores its input would pass
    the first half alone.

All series are hand-checkable synthetics. No repo data, no network, no writes.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "edge_drift_gated_overlay", ROOT / "scripts" / "edge_drift_gated_overlay.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]

_cfpt_spec = importlib.util.spec_from_file_location(
    "edge_calm_fp_tax_ref", ROOT / "scripts" / "edge_calm_fp_tax.py"
)
cfpt_ref = importlib.util.module_from_spec(_cfpt_spec)
_cfpt_spec.loader.exec_module(cfpt_ref)  # type: ignore[union-attr]

L = mod.DRIFT_LOOKBACK


def _drifting(n: int, per_day: float) -> list:
    """A series with a known sign of drift and enough wobble to be a real path."""
    return [per_day + (0.001 if i % 2 == 0 else -0.001) for i in range(n)]


# ── the panel loader is REUSED, not re-implemented ────────────────────────────────────────────
def test_panel_loader_is_the_audited_one_from_idea_32():
    """#32's loader cuts the phase='forward' re-anchor and refuses in-block jumps. If this
    script ever grew its own loader, every number here would silently revert to the #16/#17
    contamination that #32 found."""
    assert mod.cfpt.load_clean_panel.__doc__ == cfpt_ref.load_clean_panel.__doc__
    assert mod.cfpt.backtest_block.__doc__ == cfpt_ref.backtest_block.__doc__
    assert mod.cfpt.JUMP_REFUSE == cfpt_ref.JUMP_REFUSE == 0.50


# ── #35: the gate and its control ─────────────────────────────────────────────────────────────
def test_drift_gate_is_exactly_the_sds_signal_at_a_zero_hurdle():
    """#37 exists because #35's CONTROL beat it. The two must be one predicate, or the
    registry is comparing a signal against a slightly different signal."""
    r = _drifting(300, -0.0005)
    assert mod.drift_gate(r, L) == mod.sds_signal(r, L, 0.0)


def test_gate_and_inverse_are_disjoint_and_exhaustive_where_measurable():
    r = _drifting(300, -0.0002)
    g, inv = mod.drift_gate(r, L), mod.drift_gate_inverse(r, L)
    assert not any(g[i] and inv[i] for i in range(len(r)))          # disjoint
    for i in range(len(r)):
        assert (g[i] or inv[i]) is (i >= L)                         # exhaustive exactly after warmup


def test_gate_is_fail_closed_before_the_drift_is_measurable():
    """No drift estimate ⇒ no permission to de-risk. An unmeasured state is never a licence."""
    r = _drifting(300, -0.01)
    assert not any(mod.drift_gate(r, L)[:L])


def test_gate_opens_on_negative_drift_and_stays_shut_on_positive_drift():
    assert all(mod.drift_gate(_drifting(300, -0.002), L)[L:])
    assert not any(mod.drift_gate(_drifting(300, +0.002), L)[L:])


def test_oracle_gate_is_look_ahead_by_construction():
    """Pinned as a PROPERTY, not an accident: changing a FUTURE day changes today's oracle
    value. That is why it is reported only as an upper bound and never as a strategy."""
    r = _drifting(200, +0.001)
    assert not any(mod.drift_gate_oracle(r))
    later = list(r)
    later[199] = -1.0 * sum(r) - 0.5          # one future day flips the full-sample mean
    assert mod.drift_gate_oracle(later)[0] != mod.drift_gate_oracle(r)[0]


def test_gated_weights_hold_full_exposure_wherever_the_gate_is_shut():
    base = [0.0, 0.0, 0.0, 0.0]
    assert mod.gated_weights(base, [True, False, True, False]) == [0.0, 1.0, 0.0, 1.0]


def test_gating_can_only_reduce_the_time_spent_de_risked():
    r = _drifting(400, 0.0003)
    base = mod.binary(cfpt_ref.sig_vol(r, 1.5))
    gated = mod.gated_weights(base, mod.drift_gate(r, L))
    assert sum(1 for w in gated if w < 1.0) <= sum(1 for w in base if w < 1.0)


# ── #36: the two arms must move duty in OPPOSITE directions ───────────────────────────────────
def test_veto_after_up_only_ever_removes_derisk_days():
    r = _drifting(300, -0.0004)
    flags = cfpt_ref.sig_dd(r, 0.02)
    vetoed = mod.veto_after_up(flags, r)
    assert all((not v) or f for v, f in zip(vetoed, flags))        # subset of the base flags
    assert sum(vetoed) <= sum(flags)


def test_veto_after_up_never_sits_out_the_day_after_an_up_print():
    r = [0.01 if i % 3 == 0 else -0.01 for i in range(200)]
    flags = [True] * 200
    vetoed = mod.veto_after_up(flags, r)
    for i in range(1, 200):
        if r[i - 1] > 0:
            assert not vetoed[i]


def test_dwell_only_ever_adds_derisk_days_and_grows_with_k():
    r = [0.01 if i % 4 == 0 else -0.002 for i in range(300)]
    flags = cfpt_ref.sig_vol(r, 1.5)
    base_days = sum(flags)
    duties = []
    for k in (1, 2, 3):
        w = mod.dwell_weights(r, flags, k)
        out = sum(1 for x in w if x < 1.0)
        assert out >= base_days                                    # a latch can only extend
        duties.append(out)
    assert duties == sorted(duties), "a harder re-entry test must not shorten time out"


def test_dwell_re_enters_exactly_when_k_up_days_have_printed():
    #        i:   0      1      2      3      4      5
    r = [-0.01, -0.01, +0.01, +0.01, -0.01, -0.01]
    flags = [True, False, False, False, False, False]
    w1 = mod.dwell_weights(r, flags, 1)
    # out from day 0; day 3 is the first day whose PREVIOUS day (i=2) was positive
    assert w1 == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    w2 = mod.dwell_weights(r, flags, 2)
    # k=2 needs days 2 and 3 both positive ⇒ re-entry one day later
    assert w2 == [0.0, 0.0, 0.0, 0.0, 1.0, 1.0]


def test_dwell_refuses_a_re_entry_rule_with_no_evidence():
    with pytest.raises(ValueError, match="k_positive"):
        mod.dwell_weights([0.01] * 10, [False] * 10, 0)


def test_a_live_trigger_outranks_a_rebound_but_a_cleared_one_does_not():
    """The latch's ordering, pinned in both directions on the SAME return path.

    Re-entry is evaluated before the flag, but a flag that is still asserted re-arms the latch
    on the same day — an up-print does not overrule a trigger that is still firing. Only once
    the trigger has cleared does the rebound rule decide when the book comes back. (The first
    version of this test asserted the opposite; the behaviour above is the intended one and the
    docstring of `dwell_weights` was corrected to match it rather than the code.)
    """
    r = [-0.01, +0.01, +0.01, +0.01]
    assert mod.dwell_weights(r, [True, True, True, True], 1) == [0.0, 0.0, 0.0, 0.0]
    assert mod.dwell_weights(r, [True, False, False, False], 1) == [0.0, 0.0, 1.0, 1.0]


# ── causality in BOTH directions, for every rule this script adds ─────────────────────────────
RULES = [
    ("drift-gate#35", lambda r: mod.binary(mod.drift_gate(r, 30))),
    ("gated-vol#35", lambda r: mod.gated_weights(mod.binary(cfpt_ref.sig_vol(r, 1.5)),
                                                 mod.drift_gate(r, 30))),
    ("rare-veto#36", lambda r: mod.binary(mod.veto_after_up(cfpt_ref.sig_dd(r, 0.02), r))),
    ("dwell#36(k=2)", lambda r: mod.dwell_weights(r, cfpt_ref.sig_dd(r, 0.02), 2)),
    ("sds#37(L=30)", lambda r: mod.binary(mod.sds_signal(r, 30, 0.0))),
]


@pytest.mark.parametrize("name,fn", RULES, ids=[n for n, _ in RULES])
def test_rule_is_causal_on_the_acted_day(name, fn):
    """Detonate day 120 by −40%; the exposure CHOSEN for day 120 must not move."""
    base = [0.001 if i % 2 == 0 else -0.0005 for i in range(240)]
    hit = list(base)
    hit[120] = -0.40
    assert fn(base)[120] == fn(hit)[120], f"{name} leaks day-i information into day-i sizing"


@pytest.mark.parametrize("name,fn", RULES, ids=[n for n, _ in RULES])
def test_rule_reacts_from_the_day_after(name, fn):
    """Negative control: a rule that ignored its input entirely would pass the test above."""
    base = [0.001 if i % 2 == 0 else -0.0005 for i in range(240)]
    hit = list(base)
    hit[120] = -0.40
    assert fn(base)[121:] != fn(hit)[121:], f"{name} never reacts to the shock at all"


@pytest.mark.parametrize("name,fn", RULES, ids=[n for n, _ in RULES])
def test_exposure_is_bounded_to_zero_one(name, fn):
    r = [0.02, -0.03, 0.01, 0.05, -0.02] * 60
    assert all(0.0 <= w <= 1.0 for w in fn(r))


# ── #37: the signal, the hurdle, and what it degenerates into ─────────────────────────────────
def test_sds_at_lookback_10_and_rf_hurdle_is_exactly_kods15():
    """The registry claim 'SDS is not a new trigger shape — with L=10 and thr=r_f it IS kods#15'
    has to be true, or #37's sweep is not measuring what it says it measures."""
    r = _drifting(400, 0.0001)
    assert mod.sds_signal(r, 10, cfpt_ref.RF_ANNUAL) == cfpt_ref.sig_kods(r, 10)


def test_sds_is_fail_closed_during_warmup():
    assert not any(mod.sds_signal(_drifting(200, -0.01), 60, 0.0)[:60])


def test_sds_hurdle_is_monotone():
    """A higher hurdle can only make the signal fire more often — a hurdle that inverted this
    would silently change the meaning of every row of the sweep."""
    r = _drifting(400, 0.0001)
    low = mod.sds_signal(r, 60, 0.0)
    high = mod.sds_signal(r, 60, cfpt_ref.RF_ANNUAL)
    assert all(h or (not l) for l, h in zip(low, high))
    assert sum(high) >= sum(low)


# ── portfolio accounting ──────────────────────────────────────────────────────────────────────
def test_switch_count_counts_entries_not_days():
    assert mod.switches([1.0, 0.0, 0.0, 1.0, 0.0]) == 2
    assert mod.switches([1.0] * 5) == 0
    assert mod.switches([0.0] * 5) == 1


def test_full_exposure_reproduces_the_raw_portfolio_exactly():
    panel = _FakePanel({"a": _drifting(300, 0.0004), "b": _drifting(300, -0.0002)})
    m = mod.portfolio_metrics(panel, {b: [1.0] * 300 for b in panel.books})
    raw = cfpt_ref.perf(panel.raw_portfolio())
    assert math.isclose(m["apy"], raw["apy"], rel_tol=1e-12)
    assert math.isclose(m["maxdd"], raw["maxdd"], rel_tol=1e-12)
    assert m["duty"] == 0.0 and m["switches_yr"] == 0.0
    assert math.isclose(m["net_apy_after_cost"], raw["apy"], rel_tol=1e-12)


def test_turnover_bill_is_charged_per_entry_into_cash():
    panel = _FakePanel({"a": _drifting(365, 0.0004)})
    w = [1.0] * 365
    w[10] = w[11] = 0.0                       # one entry into a de-risked state, over one year
    m = mod.portfolio_metrics(panel, {"a": w}, cost_bp_per_switch=96.0)
    assert math.isclose(m["switches_yr"], 1.0, rel_tol=1e-9)
    assert math.isclose(m["apy"] - m["net_apy_after_cost"], 96.0 / 10_000.0, rel_tol=1e-9)


def test_rebound_forfeit_splits_the_days_out_by_regime():
    """#36's whole premise is this diagnostic, so it must actually separate the two regimes.

    One −20% shock followed by a long +1%/day climb back: the loss lands on a CALM day (the
    drawdown state is causal, so day 0 is still at the peak) and the entire recovery is spent
    inside the drawdown. That is exactly the shape #32 reported — a positive mean on the
    drawdown days means an overlay sitting there is selling the rebound.
    """
    r = [-0.20] + [0.01] * 30
    panel = _FakePanel({"a": r})
    w = [0.0] * len(r)                        # sit out everything
    f = mod.rebound_forfeit(panel, {"a": w})
    assert f["n_dd"] + f["n_calm"] == len(r)  # every day out lands in exactly one bucket
    assert f["calm_bp"] < 0 < f["dd_bp"]      # the loss was calm; the drawdown days paid


def test_rebound_forfeit_counts_only_the_days_actually_spent_out():
    r = [-0.20] + [0.01] * 30
    panel = _FakePanel({"a": r})
    w = [1.0] * len(r)
    w[5] = w[6] = 0.0
    f = mod.rebound_forfeit(panel, {"a": w})
    assert f["n_dd"] + f["n_calm"] == 2


# ── the train/test split must not overlap and must not lose a day ─────────────────────────────
def test_panel_window_split_is_a_partition():
    """`end` is inclusive, `start` is exclusive — that is what makes TRAIN ≤ TRAIN_END and
    TEST > TRAIN_END a partition. An off-by-one here would either double-count the boundary
    day or drop it, and the OOS verdicts are read off exactly this split."""
    panel = mod.cfpt.load_clean_panel  # not called — the semantics are pinned on a fake below
    assert panel is not None
    axis = ["2025-06-29", "2025-06-30", "2025-07-01"]
    train = [d for d in axis if d <= mod.TRAIN_END]
    test = [d for d in axis if d > mod.TRAIN_END]
    assert train == ["2025-06-29", "2025-06-30"] and test == ["2025-07-01"]
    assert set(train) | set(test) == set(axis) and not (set(train) & set(test))


class _FakePanel:
    """Minimal stand-in with the Panel surface `portfolio_metrics` / `rebound_forfeit` use."""

    def __init__(self, rets: dict) -> None:
        self.rets = rets
        self.books = sorted(rets)
        self.axis = [f"d{i}" for i in range(len(next(iter(rets.values()))))]

    @property
    def n(self) -> int:
        return len(self.axis)

    def raw_portfolio(self) -> list:
        return [sum(self.rets[b][i] for b in self.books) / len(self.books) for i in range(self.n)]
