"""ADR-060 — yield-improvement trigger: economics, hysteresis, anti-churn.

Pins the decisions that make the trigger safe to arm later:

* improvement is measured over TOTAL capital (idle cash counts as 0 %), so moving
  cash into a pool registers as the improvement it is;
* an unevidenced position earns nothing in the maths — opacity is expensive;
* a permitted move still has to pay for itself within a horizon;
* every anti-churn gate binds the YIELD channel only — a de-risk is never delayed.

Pure unit tests: no files, no network, no clock.
"""
from __future__ import annotations

import pytest

from spa_core.allocator.rebalance_economics import (
    Decision,
    TriggerParams,
    below_median_cap_violations,
    evaluate,
    explain_cash,
)

CAP = 100_000.0
CHAINS = {"a": "ethereum", "b": "ethereum", "c": "base", "d": "arbitrum"}
APY = {"a": 3.0, "b": 6.0, "c": 5.0, "d": 4.0}
EV = set(APY)


def _ev(current, target, **kw):
    kw.setdefault("apy_pct", APY)
    kw.setdefault("evidenced", EV)
    kw.setdefault("chains", CHAINS)
    kw.setdefault("capital_usd", CAP)
    return evaluate(current_positions=current, target_positions=target, **kw)


# ── L1: what "improvement" means ────────────────────────────────────────────


def test_improvement_is_measured_over_total_capital() -> None:
    """Deploying idle cash MUST register as gain.

    On a deployed-only base this move looks like 6 % → 6 % (no change) and the
    trigger would never fire on the single most valuable action available.
    """
    d = _ev({"b": 20_000.0}, {"b": 50_000.0})
    assert d.apy_now_pp == pytest.approx(1.2)    # 20 % × 6 %
    assert d.apy_opt_pp == pytest.approx(3.0)    # 50 % × 6 %
    assert d.gain_pp == pytest.approx(1.8)


def test_unevidenced_position_earns_nothing_in_the_maths() -> None:
    """A pool we cannot observe must not defend itself against an observable one.

    Crediting its literal APY would make opacity a free advantage — backwards.
    """
    d = _ev({"ghost": 50_000.0}, {"b": 50_000.0}, apy_pct={**APY, "ghost": 99.0},
            chains={**CHAINS, "ghost": "ethereum"})
    assert d.apy_now_pp == pytest.approx(0.0)
    assert d.evidence["unevidenced_held"] == ["ghost"]
    assert d.gain_pp == pytest.approx(3.0)


def test_target_holding_an_unevidenced_pool_never_acts() -> None:
    d = _ev({"b": 50_000.0}, {"b": 20_000.0, "ghost": 30_000.0},
            apy_pct={**APY, "ghost": 99.0}, chains={**CHAINS, "ghost": "ethereum"})
    assert d.decision == "HOLD"
    assert any("target_contains_unevidenced" in r for r in d.reasons)
    assert d.gates["target_fully_evidenced"] is False


# ── L1: cost and payback ────────────────────────────────────────────────────


def test_cost_counts_gas_per_leg_and_slippage_on_turnover() -> None:
    d = _ev({"a": 40_000.0}, {"a": 20_000.0, "b": 20_000.0})
    # two legs on ethereum (2 × $12) + 8 bps of the $20 000 one-sided turnover
    assert d.turnover_usd == pytest.approx(20_000.0)
    assert d.cost_usd == pytest.approx(24.0 + 16.0)


def test_deploying_idle_cash_is_not_half_counted() -> None:
    """A pure deployment has no sell leg — turnover is the full amount deployed.

    A plain gross/2 would halve it, understating both slippage and the turnover
    budget on exactly the move the trigger most wants to make.
    """
    d = _ev({"a": 40_000.0}, {"a": 40_000.0, "b": 15_000.0})
    assert d.turnover_usd == pytest.approx(15_000.0)


def test_multichain_move_adds_the_bridge_cost() -> None:
    """Bridge is 5 bps of turnover on top; asserted on the exact composition,
    since a cheaper L2 leg can otherwise mask it in a naive total comparison."""
    cross = _ev({"a": 40_000.0}, {"a": 20_000.0, "c": 20_000.0})
    gas = 12.0 + 0.15                      # ethereum leg + base leg
    slippage = 20_000.0 * 0.0008
    bridge = 20_000.0 * 0.0005
    assert cross.cost_usd == pytest.approx(gas + slippage + bridge)


def test_gain_that_cannot_repay_within_the_horizon_holds() -> None:
    """A real edge is still refused when the move takes too long to pay for itself.

    The band is lowered here so the ONLY failing gate is payback — otherwise the
    gain gate would mask it and the test would prove nothing.
    """
    d = _ev({"a": 40_000.0}, {"a": 31_000.0, "b": 9_000.0},
            params=TriggerParams(min_gain_pp=0.10))
    assert d.gates["gain_above_band"] is True
    assert d.payback_days is not None and d.payback_days > 30
    assert d.decision == "HOLD"
    assert any("payback_too_long" in r for r in d.reasons)


def test_a_clear_gain_within_budget_acts() -> None:
    """Deploy $15k of idle cash into the 6 % pool: +0.9 pp, repays in ~7 days."""
    d = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0})
    assert d.gain_pp == pytest.approx(0.9)
    assert d.turnover_frac == pytest.approx(0.15)
    assert d.decision == "ACT", d.reasons
    assert all(d.gates.values())


# ── L2: dust, hysteresis, anti-churn ────────────────────────────────────────


def test_dust_legs_are_ignored_entirely() -> None:
    """A $200 leg pays full gas and moves nothing worth moving."""
    d = _ev({"a": 40_000.0}, {"a": 39_800.0, "b": 200.0})
    assert d.legs == []
    assert d.decision == "HOLD" and "no_material_legs" in d.reasons


def test_reversing_a_recent_move_must_clear_a_higher_bar() -> None:
    """Hysteresis: the band to undo is wider than the band to do."""
    base = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0})
    assert base.decision == "ACT"
    rev = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0},
              last_move_legs={"b": -30_000.0}, days_since_last_move=2.0)
    assert rev.required_gain_pp == pytest.approx(base.required_gain_pp * 1.5)
    assert any("reversal_of_recent_move" in r for r in rev.reasons)


def test_reversal_outside_the_window_is_not_penalised() -> None:
    d = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0},
            last_move_legs={"b": -30_000.0}, days_since_last_move=30.0)
    assert d.required_gain_pp == pytest.approx(TriggerParams().min_gain_pp)


def test_cooldown_blocks_a_second_move_however_good() -> None:
    d = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0}, days_since_last_act=1.0)
    assert d.decision == "HOLD"
    assert d.gates["cooldown_ok"] is False
    assert d.gates["gain_above_band"] is True   # the edge is real; the timing is not


def test_min_hold_restrains_selling_not_buying() -> None:
    """A fresh position may still be TOPPED UP; it just may not be churned out."""
    sell = _ev({"a": 60_000.0}, {"a": 45_000.0, "b": 15_000.0},
               position_age_days={"a": 1.0})
    assert sell.decision == "HOLD" and sell.gates["min_hold_ok"] is False
    buy = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 0.0}, position_age_days={"b": 1.0})
    assert buy.gates.get("min_hold_ok", True) is True


def test_turnover_budgets_cap_a_single_move_and_the_week() -> None:
    big = _ev({"a": 60_000.0}, {"b": 60_000.0})
    assert big.turnover_frac > TriggerParams().max_turnover_per_move
    assert big.gates["move_turnover_ok"] is False
    small = _ev({"a": 60_000.0}, {"a": 50_000.0, "b": 10_000.0},
                turnover_last_week_usd=24_000.0)
    assert small.gates["week_turnover_ok"] is False


def test_every_gate_must_pass_to_act() -> None:
    d = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0})
    assert d.decision == "ACT"
    for gate, ok in d.gates.items():
        assert ok, gate


# ── fail-CLOSED ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("capital", [0.0, -5.0])
def test_invalid_capital_holds(capital: float) -> None:
    d = _ev({"a": 1.0}, {"b": 1.0}, capital_usd=capital)
    assert d.decision == "HOLD" and "invalid_capital" in d.reasons


def test_verdict_is_serialisable_for_the_artifact() -> None:
    d = _ev({"a": 60_000.0}, {"b": 60_000.0})
    doc = d.to_dict()
    assert doc["decision"] in ("ACT", "HOLD")
    for key in ("gain_pp", "cost_usd", "payback_days", "gates", "reasons", "legs"):
        assert key in doc


def test_unsound_recommendation_is_flagged_when_target_tvl_is_a_literal() -> None:
    """A target pool that cleared the TVL floor on a literal makes the advice unsound.

    Not a veto — the floor is RiskPolicy's job — but the reader must see it.
    """
    d = _ev({"a": 60_000.0}, {"a": 60_000.0, "b": 15_000.0}, tvl_evidenced={"a"})
    assert d.evidence["tvl_unevidenced_in_target"] == ["b"]
    assert any("tvl_not_evidenced_for" in w for w in d.warnings)


# ── L3: cash attribution and the below-median rule ──────────────────────────


def test_idle_cash_above_the_buffer_must_be_attributed() -> None:
    out = explain_cash(positions={"a": 60_000.0}, capital_usd=CAP, min_cash_frac=0.05)
    assert out["excess_pct"] == pytest.approx(35.0)
    assert out["status"] == "UNEXPLAINED_CASH"


def test_named_binders_explain_the_idle_cash() -> None:
    out = explain_cash(positions={"a": 60_000.0}, capital_usd=CAP, min_cash_frac=0.05,
                       binders=[{"reason": "t3_cap", "pct": 15.0},
                                {"reason": "unevidenced_blocked", "pct": 20.0}])
    assert out["unexplained_pct"] == pytest.approx(0.0)
    assert out["status"] == "explained"


def test_below_median_yield_may_not_max_its_cap() -> None:
    """Concentration follows yield/risk, not the inertia of an old target."""
    rows = below_median_cap_violations(
        positions={"a": 40_000.0, "b": 20_000.0, "c": 20_000.0},
        apy_pct=APY, tier_caps={"a": 0.40, "b": 0.20, "c": 0.20},
        capital_usd=CAP, evidenced=EV)
    assert [r["protocol"] for r in rows] == ["a"]     # 3 % is the lowest, yet holds 40 %
    assert rows[0]["allowed_share"] == pytest.approx(0.20)


def test_median_over_fewer_than_three_pools_is_not_a_signal() -> None:
    assert below_median_cap_violations(
        positions={"a": 40_000.0, "b": 20_000.0}, apy_pct=APY,
        tier_caps={"a": 0.40, "b": 0.20}, capital_usd=CAP, evidenced=EV) == []


def test_named_cause_is_not_reported_as_unexplained() -> None:
    """Naming eleven blocked protocols and then calling the cash unexplained is
    the cry-wolf failure this project keeps paying for: the alarm stops meaning
    anything and the real case — no reason at all — hides inside it.

    ADR-055 requires idle capital to be a LOGGED DECISION, not a numeric split.
    """
    out = explain_cash(positions={"a": 60_000.0}, capital_usd=CAP, min_cash_frac=0.05,
                       binders=[{"reason": "blocked: 11 protocols unevidenced", "pct": 0.0}])
    assert out["status"] == "named_not_quantified"
    assert out["unexplained_pct"] == pytest.approx(35.0)      # still visible


def test_silent_idle_capital_is_still_an_alarm() -> None:
    """The case the invariant actually targets: no reason on record at all."""
    assert explain_cash(positions={"a": 60_000.0}, capital_usd=CAP,
                        min_cash_frac=0.05)["status"] == "UNEXPLAINED_CASH"


def test_cash_at_the_buffer_needs_no_explanation() -> None:
    out = explain_cash(positions={"a": 95_000.0}, capital_usd=CAP, min_cash_frac=0.05)
    assert out["excess_pct"] == pytest.approx(0.0) and out["status"] == "explained"
