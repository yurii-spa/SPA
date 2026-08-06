# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_capital_recycling.py (registry ideas #38 CBCR / #39 CDR).

Two verdicts rest on this file, and each is only worth as much as the property pinned here:

  • **#39 claims to isolate "where the freed capital goes" from "when the trigger fires."** That
    is only true if its M=1 eligibility state is EXACTLY `sds_signal` — the trigger of #37, not a
    look-alike. Pinned directly against #37's own implementation over a parameter grid.
  • **#39's headline is a PLATEAU over the re-admission delay M**, which presupposes that M is a
    monotone hysteresis knob: raising it may only ever ADD days out, never remove one. Pinned.
  • **#38's number is only meaningful against its controls**, so the controls must destroy exactly
    what they claim to destroy and nothing else: a book-permutation must preserve every flag path
    (and hence duty and switch structure) while changing only WHICH book carries it; a time
    rotation must preserve duty exactly.
  • **The cost model changed** from the registry's switch counter to a turnover integral, because
    recycling moves capital on days no flag flips. The docstring claims the two agree on a plain
    cash overlay (96 bp round-trip per unit of book capital ⇒ 96 bp / N of the portfolio). That
    equality is arithmetic and is pinned, otherwise these numbers are not comparable with
    #32/#35/#36 and the whole registry becomes two incompatible eras.
  • **Recycling must never place capital in a flagged book, must conserve capital, and must go to
    CASH when nothing is eligible** — fail-CLOSED. An allocator that invents a destination on an
    empty eligible set would post a number nobody could interpret.
  • **The oracle rows are LOOK-AHEAD on purpose**; that is pinned as a property (they react to a
    FUTURE day) so they can never be quietly reused as a live rule.
  • Everything causal is causal in BOTH directions: a shock on day i must not move the weight
    chosen for day i, and must move it from day i+1 — a rule that ignored its input entirely
    would pass the first half on its own.

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


mod = _load("edge_capital_recycling")
dgo = _load("edge_drift_gated_overlay")
cfpt = _load("edge_calm_fp_tax")


# ─────────────────────────── synthetic material ───────────────────────────
def wave(n: int, period: int = 40, amp: float = 0.004, drift: float = 0.0):
    """Deterministic oscillating series with a drift — no RNG, so a failure is reproducible."""
    return [drift + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


class FakePanel:
    """The three attributes `portfolio_metrics` reads. Keeps the tests off repo data."""

    def __init__(self, rets):
        self.rets = {k: list(v) for k, v in rets.items()}
        self.books = sorted(self.rets)
        self.n = len(next(iter(self.rets.values())))

    def raw_portfolio(self):
        return [sum(self.rets[b][i] for b in self.books) / len(self.books)
                for i in range(self.n)]


def flat_flags(books, n, value=False):
    return {b: [value] * n for b in books}


# ═════════════════ #39 — the trigger is #37's, unchanged ═════════════════
@pytest.mark.parametrize("lookback", [5, 10, 60])
@pytest.mark.parametrize("hurdle", [0.0, 0.046])
def test_demotion_M1_is_exactly_sds_signal_of_idea37(lookback, hurdle):
    """M=1 must BE #37's signal. If it merely resembles it, #39's whole comparison is void."""
    r = wave(300, period=37, amp=0.006, drift=-0.0002)
    assert mod.demotion_flags(r, lookback, hurdle, 1) == dgo.sds_signal(r, lookback, hurdle)


def test_readmission_delay_is_monotone_hysteresis():
    """Raising M may only ADD demoted days — the plateau in the sweep is read as hysteresis."""
    r = wave(400, period=23, amp=0.005, drift=-0.0001)
    prev = mod.demotion_flags(r, 30, 0.0, 1)
    for m_days in (2, 3, 5, 10, 20, 45):
        cur = mod.demotion_flags(r, 30, 0.0, m_days)
        assert all((not p) or c for p, c in zip(prev, cur)), (
            f"M={m_days} un-demoted a day that a shorter delay demoted — not a hysteresis knob")
        assert sum(cur) >= sum(prev)
        prev = cur


def test_demotion_is_fail_closed_during_warmup():
    """No drift estimate ⇒ no demotion. An unmeasured book is not a demoted book."""
    r = [-0.05] * 100                      # relentlessly negative: demotion the moment it can
    flags = mod.demotion_flags(r, 30, 0.0, 1)
    assert not any(flags[:30])
    assert all(flags[30:])


def test_readmit_days_below_one_is_refused():
    with pytest.raises(ValueError):
        mod.demotion_flags(wave(50), 10, 0.0, 0)


def test_demotion_is_causal_in_both_directions():
    """A shock on day i may not move day i's state, and must move it from day i+1."""
    base = [0.001] * 120
    lookback, i = 20, 60
    shocked = list(base)
    shocked[i] = -0.9
    f_base = mod.demotion_flags(base, lookback, 0.0, 1)
    f_shock = mod.demotion_flags(shocked, lookback, 0.0, 1)
    assert f_base[:i + 1] == f_shock[:i + 1], "a same-day reaction is look-ahead"
    assert f_base[i + 1:] != f_shock[i + 1:], "the rule ignored its own input"


def test_oracle_demotion_is_look_ahead_by_construction():
    """Pinned as look-ahead so it can never be mistaken for, or reused as, a live rule."""
    good = [0.001] * 200
    assert not any(mod.oracle_demotion_flags(good))
    poisoned = list(good)
    poisoned[-1] = -1.0                    # a FUTURE day changes day 0's verdict
    assert all(mod.oracle_demotion_flags(poisoned))


# ═════════════════ allocators: conservation, caps, fail-closed ═════════════════
def test_recycle_conserves_capital_and_never_funds_a_flagged_book():
    books = ["a", "b", "c", "d"]
    n = 6
    flags = {"a": [False] * n, "b": [i % 2 == 0 for i in range(n)],
             "c": [i % 3 == 0 for i in range(n)], "d": [True] * n}
    w = mod.alloc_recycle(books, flags, n)
    for i in range(n):
        assert math.isclose(sum(w[b][i] for b in books), 1.0, abs_tol=1e-12)
        for b in books:
            if flags[b][i]:
                assert w[b][i] == 0.0, "capital was placed in a book the signal flagged"


def test_recycle_goes_all_cash_when_nothing_is_eligible():
    """Fail-CLOSED: an empty eligible set is cash, never an invented destination."""
    books = ["a", "b"]
    w = mod.alloc_recycle(books, flat_flags(books, 4, True), 4)
    assert all(w[b][i] == 0.0 for b in books for i in range(4))


def test_cap_is_respected_and_the_shortfall_becomes_cash():
    """A cap that cannot absorb the capital leaves the rest uninvested — not a silent breach."""
    books = ["a", "b", "c", "d"]
    n = 3
    flags = {"a": [False] * n, "b": [False] * n, "c": [True] * n, "d": [True] * n}
    w = mod.alloc_recycle(books, flags, n, cap=0.2)
    for i in range(n):
        assert all(w[b][i] <= 0.2 + 1e-12 for b in books)
        assert math.isclose(sum(w[b][i] for b in books), 0.4, abs_tol=1e-12)


def test_waterfill_redistributes_up_to_the_cap_when_feasible():
    out = mod._waterfill(["a", "b", "c", "d", "e"], cap=0.25)
    assert math.isclose(sum(out.values()), 1.0, abs_tol=1e-12)
    assert all(v <= 0.25 + 1e-12 for v in out.values())


def test_waterfill_rejects_a_nonpositive_cap():
    with pytest.raises(ValueError):
        mod._waterfill(["a"], cap=0.0)


def test_ranked_recycle_respects_cap_and_separates_best_from_worst():
    books = ["up", "down", "flat"]
    n = 120
    rets = {"up": [0.002] * n, "down": [-0.002] * n, "flat": [0.0] * n}
    flags = flat_flags(books, n, False)
    best = mod.alloc_recycle_ranked(books, flags, n, rets, lookback=30, best_first=True, cap=0.5)
    worst = mod.alloc_recycle_ranked(books, flags, n, rets, lookback=30, best_first=False, cap=0.5)
    assert best != worst, "the destination control is not a control if both arms agree"
    late = n - 1
    assert best["up"][late] >= best["down"][late]
    assert worst["down"][late] >= worst["up"][late]
    for w in (best, worst):
        assert all(w[b][i] <= 0.5 + 1e-12 for b in books for i in range(n))
        assert math.isclose(sum(w[b][late] for b in books), 1.0, abs_tol=1e-12)


def test_static_matched_control_keeps_the_average_and_kills_the_timing():
    books = ["a", "b"]
    n = 8
    flags = {"a": [i < 4 for i in range(n)], "b": [False] * n}
    dyn = mod.alloc_recycle(books, flags, n)
    static = mod.alloc_static_matched(dyn)
    for b in books:
        assert math.isclose(sum(static[b]) / n, sum(dyn[b]) / n, abs_tol=1e-12)
        assert len(set(static[b])) == 1, "a static control that moves is not a static control"


# ═════════════════ cost model: the two registry eras must agree ═════════════════
def test_turnover_cost_reproduces_the_registry_per_switch_bill():
    """One book out and back under a plain cash overlay == 96 bp / N of the portfolio.

    This is the claim that keeps #38/#39 comparable with #32/#35/#36, which priced de-risk by
    counting switches. If it ever breaks, the two eras are being compared in different units.
    """
    books = [f"b{i}" for i in range(10)]
    n = 365
    panel = FakePanel({b: [0.0] * n for b in books})
    flags = flat_flags(books, n, False)
    flags["b0"] = [100 <= i < 200 for i in range(n)]      # exactly one round trip in one year
    m = mod.portfolio_metrics(panel, mod.alloc_cash(books, flags, n))
    assert math.isclose(m["cost_bp_yr"], mod.COST_BP_ROUND_TRIP / len(books), rel_tol=1e-9)


def test_recycling_is_charged_for_moves_no_switch_counter_would_see():
    """Recycling re-splits capital when the eligible set changes — the cost must be non-zero."""
    books = ["a", "b", "c"]
    n = 100
    panel = FakePanel({b: [0.0] * n for b in books})
    flags = flat_flags(books, n, False)
    flags["a"] = [i % 2 == 0 for i in range(n)]
    cash = mod.portfolio_metrics(panel, mod.alloc_cash(books, flags, n))
    recyc = mod.portfolio_metrics(panel, mod.alloc_recycle(books, flags, n))
    assert recyc["turnover_yr"] > cash["turnover_yr"] > 0.0
    assert math.isclose(recyc["deployed"], 1.0, abs_tol=1e-12)


def test_static_control_pays_no_turnover():
    books = ["a", "b"]
    n = 50
    panel = FakePanel({b: [0.0] * n for b in books})
    flags = {"a": [i < 25 for i in range(n)], "b": [False] * n}
    static = mod.alloc_static_matched(mod.alloc_recycle(books, flags, n))
    assert mod.portfolio_metrics(panel, static)["turnover_yr"] == 0.0


def test_uninvested_capital_earns_the_stated_cash_rate():
    """With everything flagged, the portfolio must return exactly the cash rate — no more."""
    books = ["a", "b"]
    n = 365
    panel = FakePanel({b: [0.05] * n for b in books})   # ignored: nothing is deployed
    m = mod.portfolio_metrics(panel, mod.alloc_cash(books, flat_flags(books, n, True), n),
                              cash_annual=mod.RF_ANNUAL)
    assert math.isclose(m["apy"], math.expm1(math.log1p(mod.RF_ANNUAL / 365.0) * 365.0),
                        rel_tol=1e-6)


# ═════════════════ information controls destroy one thing each ═════════════════
def test_permutation_preserves_every_flag_path_and_only_moves_book_identity():
    books = ["a", "b", "c", "d", "e"]
    n = 30
    flags = {b: [(i + j) % 4 == 0 for i in range(n)] for j, b in enumerate(books)}
    perm = mod.permuted_flags(flags, books, seed=7)
    assert sorted(map(tuple, perm.values())) == sorted(map(tuple, flags.values())), (
        "the permutation altered a flag path — it would then be destroying duty, not identity")
    assert sum(sum(v) for v in perm.values()) == sum(sum(v) for v in flags.values())
    assert mod.permuted_flags(flags, books, seed=7) == perm, "control must be reproducible"


def test_time_rotation_preserves_duty_exactly():
    books = ["a", "b"]
    n = 50
    flags = {"a": [i < 13 for i in range(n)], "b": [i % 7 == 0 for i in range(n)]}
    rot = mod.shifted_flags(flags, books, 17)
    for b in books:
        assert len(rot[b]) == n
        assert sum(rot[b]) == sum(flags[b])
    assert rot != flags


# ═════════════════ positive control: the mechanism works when its premise holds ═════════════════
def test_recycling_beats_equal_weight_when_one_book_is_a_persistent_loser():
    """The mechanism's premise, in a hand-built world: a book that trends down is demoted and its
    capital is carried by the others. If this did not hold on a synthetic panel where the premise
    is true by construction, the real-panel number could only be an artifact."""
    n = 600
    rets = {
        "good1": [0.0006] * n,
        "good2": [0.0005] * n,
        "loser": [-0.0015] * n,
    }
    panel = FakePanel(rets)
    dem = {b: mod.demotion_flags(rets[b], 30, 0.0, 5) for b in panel.books}
    raw = cfpt.perf(panel.raw_portfolio())
    cdr = mod.portfolio_metrics(panel, mod.alloc_recycle(panel.books, dem, n))
    assert cdr["apy"] > raw["apy"], "demotion + redistribution failed on a panel built for it"
    assert cdr["max_weight"] <= 0.5 + 1e-12
    assert dem["loser"][-1] is True and dem["good1"][-1] is False


def test_flags_from_weights_reads_a_dwell_path_back_as_flags():
    """#38 feeds #36's dwell latch (an exposure path) into a flag-shaped allocator."""
    assert mod.flags_from_weights([1.0, 0.0, 1.0, 0.0]) == [False, True, False, True]
