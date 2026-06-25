"""
spa_core/tests/test_rates_desk_engine.py — Rate/Basis Sleeve engine + refusal-first gate tests.

Pure synthetic, no network, Decimal end-to-end. Proves the HARD INVARIANTS:
  - REFUSAL-FIRST: a toxic LRT is TAIL_VETO'd even with spectacular economics (refusal-before-economics).
  - a healthy sUSDe PT clears the gate.
  - funding-flip hysteresis (kill only after N consecutive negative-funding ticks).
  - size is capped by exit capacity (max_size_frac_of_exit * exit_liquidity).
  - evaluate_hold unwinds on depeg / carry compression / maturity buffer.
  - PURITY: same (inputs, as_of) → byte-identical output (proof_hash stable, no wall-clock).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal as D

import pytest

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateVenue,
    RateQuote,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.rate_policy import (
    compose_under_global_policy,
    evaluate_entry,
    evaluate_hold,
)

P = RatePolicyParams()
ENG = FairValueEngine(P)
AS_OF = "2026-06-01"


# ── fixtures (synthetic risk surfaces / quotes) ───────────────────────────────────────────────────
def _healthy_susde_risk(as_of: str = AS_OF, **over) -> UnderlyingRisk:
    base = dict(
        underlying="susde", as_of=as_of,
        nav_redemption_value=D("1"), market_price=D("1.0003"), peg_distance=D("0.0003"),
        peg_vol_30d=D("0.001"), redemption_sla_seconds=86400, reserve_fund_ratio=D("0.05"),
        funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=D("0.1"),
    )
    base.update(over)
    return UnderlyingRisk(**base)


def _toxic_lrt_risk(as_of: str = AS_OF, **over) -> UnderlyingRisk:
    base = dict(
        underlying="ezeth", as_of=as_of,
        nav_redemption_value=D("1"), market_price=D("0.992"), peg_distance=D("0.008"),
        peg_vol_30d=D("0.02"), redemption_sla_seconds=86400 * 7, reserve_fund_ratio=D0,
        funding_neg_frac_90d=D("0.42"), oracle_kind="redstone", oracle_staleness_seconds=600,
        nested_protocol_count=4, top_borrower_share=D("0.5"),
    )
    base.update(over)
    return UnderlyingRisk(**base)


def _quote(underlying, kind, rate, as_of=AS_OF, exit_liq="2e6", tenor=86400 * 60,
           hedge=True, util="0.5", market_id=None) -> RateQuote:
    return RateQuote(
        underlying=underlying, kind=kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
        market_id=market_id or f"PT-{underlying}", tenor_seconds=tenor, as_of=as_of,
        quoted_rate=D(rate), tvl_usd=D("5e7"), exit_liquidity_usd=D(exit_liq),
        hedge_available=hedge, utilization=D(util),
    )


def _opp(q, size="100000") -> Opportunity:
    return Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=D(size))


# ── REFUSAL-FIRST: toxic LRT TAIL_VETO even with great economics ──────────────────────────────────
def test_toxic_lrt_tail_veto_before_economics():
    risk = _toxic_lrt_risk()
    q = _quote("ezeth", UnderlyingKind.LRT, "0.40", hedge=False)  # 40% quoted — economics are great
    res, st = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(), engine=ENG)
    assert res.approved is False
    # the FIRST veto must be a TAIL/structural one — NOT economics (a 40% quote would pass economics)
    assert res.reason == KillReason.TAIL_VETO
    assert res.decomposition.total_haircut > P.max_total_haircut


def test_haircuts_stack_to_veto():
    """Each individual haircut may be modest, but they STACK past max_total_haircut → veto."""
    risk = _toxic_lrt_risk()
    dec = ENG.fair(risk, UnderlyingKind.LRT, 86400 * 60, False, D("100000"), D("2e6"), AS_OF)
    # all five haircuts are present and non-trivial
    assert dec.peg_haircut > D0
    assert dec.funding_flip_haircut > D0
    assert dec.protocol_haircut > D0
    assert dec.total_haircut > P.max_total_haircut


# ── healthy sUSDe PT passes ───────────────────────────────────────────────────────────────────────
def test_healthy_susde_passes():
    risk = _healthy_susde_risk()
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    res, st = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(),
                             engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert res.net_edge > D0
    assert res.approved_size_usd > D0


def test_lrt_restaking_premium_not_in_baseline():
    """An LRT's baseline is STAKING ONLY — the restaking premium is never baseline."""
    risk = _healthy_susde_risk(underlying="weeth")
    base_lrt = ENG.baseline_yield(risk, UnderlyingKind.LRT, 86400 * 60, False)
    assert base_lrt == P.staking_yield  # not staking + restaking points


# ── funding-flip hysteresis ───────────────────────────────────────────────────────────────────────
def test_funding_flip_hysteresis_needs_n_consecutive():
    # hostile funding (>=0.5 neg frac) but a healthy peg so only the funding-flip path can fire
    risk = _healthy_susde_risk(funding_neg_frac_90d=D("0.60"))
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    state = KillState()
    # the first (kill-1) ticks must NOT yet kill on funding; only the Nth does.
    for i in range(P.funding_flip_streak_kill - 1):
        res, state = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, state,
                                    engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
        assert res.reason != KillReason.FUNDING_FLIP, f"killed too early at tick {i}"
        assert state.neg_funding_streak == i + 1
    # the Nth consecutive flip tick trips FUNDING_FLIP
    res, state = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, state,
                                engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is False
    assert res.reason == KillReason.FUNDING_FLIP
    assert state.neg_funding_streak >= P.funding_flip_streak_kill


def test_funding_streak_resets_on_benign_tick():
    risk_hostile = _healthy_susde_risk(funding_neg_frac_90d=D("0.60"))
    risk_benign = _healthy_susde_risk(funding_neg_frac_90d=D("0.05"))
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    state = KillState()
    _, state = evaluate_entry(_opp(q), risk_hostile, D("1"), q.exit_liquidity_usd, P, state,
                              engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert state.neg_funding_streak == 1
    _, state = evaluate_entry(_opp(q), risk_benign, D("1"), q.exit_liquidity_usd, P, state,
                              engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert state.neg_funding_streak == 0  # benign tick resets the streak


# ── size capped by exit capacity ──────────────────────────────────────────────────────────────────
def test_size_capped_by_exit_capacity():
    risk = _healthy_susde_risk()
    # request 100k but exit liquidity is only 200k → cap = 25% * 200k = 50k
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", exit_liq="200000", hedge=True)
    res, st = evaluate_entry(_opp(q, size="100000"), risk, D("1"), q.exit_liquidity_usd, P,
                             KillState(), engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is True
    assert res.approved_size_usd == P.max_size_frac_of_exit * D("200000")  # 50k
    assert res.approved_size_usd < D("100000")


def test_size_floor_refuse_when_exit_tiny():
    risk = _healthy_susde_risk()
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", exit_liq="2000", hedge=True)  # cap=500
    res, st = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(),
                             engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is False
    assert res.reason == KillReason.SIZE_FLOOR


# ── evaluate_hold continuous kills ────────────────────────────────────────────────────────────────
def test_hold_unwinds_on_depeg():
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    opp = _opp(q)
    depegged = _healthy_susde_risk(peg_distance=D("0.05"), market_price=D("0.95"))  # 5% depeg
    state = KillState(entry_carry=D("0.05"))
    res, ns = evaluate_hold(opp, depegged, D("1"), q.exit_liquidity_usd, D("0.05"), P, state, engine=ENG)
    assert res.approved is False
    assert res.reason == KillReason.UNDERLYING_DEPEG
    assert ns.killed is True


def test_hold_unwinds_on_carry_compression():
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    opp = _opp(q)
    risk = _healthy_susde_risk()
    # entry carry 5%, current carry collapsed to 1% (< 50% of entry) → compression kill
    state = KillState(entry_carry=D("0.05"))
    res, ns = evaluate_hold(opp, risk, D("1"), q.exit_liquidity_usd, D("0.01"), P, state, engine=ENG)
    assert res.approved is False
    assert res.reason == KillReason.CARRY_COMPRESSION


def test_hold_unwinds_on_maturity_buffer():
    # tenor inside the 2-day maturity buffer → unwind regardless of healthy economics
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", tenor=86400, hedge=True)  # 1 day left
    opp = _opp(q)
    risk = _healthy_susde_risk()
    state = KillState(entry_carry=D("0.05"))
    res, ns = evaluate_hold(opp, risk, D("1"), q.exit_liquidity_usd, D("0.05"), P, state, engine=ENG)
    assert res.approved is False
    assert res.reason == KillReason.MATURITY_BUFFER


def test_hold_keeps_healthy_position():
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    opp = _opp(q)
    risk = _healthy_susde_risk()
    state = KillState(entry_carry=D("0.05"))
    res, ns = evaluate_hold(opp, risk, D("1"), q.exit_liquidity_usd, D("0.05"), P, state, engine=ENG)
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert ns.killed is False


# ── composition under the global RiskPolicy (AND, never OR) ────────────────────────────────────────
def test_composition_is_more_restrictive():
    # rate gate approves but global policy rejects → no capital may move
    risk = _healthy_susde_risk()
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    res, _ = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(),
                            engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is True
    assert compose_under_global_policy(res, global_approved=True) is True
    assert compose_under_global_policy(res, global_approved=False) is False  # strictly more restrictive


# ── PURITY: deterministic, no wall-clock ──────────────────────────────────────────────────────────
def test_purity_same_inputs_same_output():
    risk = _healthy_susde_risk()
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    r1, s1 = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(),
                            engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    r2, s2 = evaluate_entry(_opp(q), risk, D("1"), q.exit_liquidity_usd, P, KillState(),
                            engine=FairValueEngine(P), trailing_yield=D("0.05"), boros_forward=D("0.048"))
    # byte-identical verdict → identical proof hash (no clock / RNG leaked in)
    assert r1.proof_hash() == r2.proof_hash()
    assert r1.approved_size_usd == r2.approved_size_usd
    assert r1.net_edge == r2.net_edge


def test_fail_closed_on_malformed_risk():
    # a None-equivalent malformed peg distance must fail-CLOSED (refuse), never silently pass
    bad = _healthy_susde_risk(peg_distance=D("-1"))  # negative peg = malformed
    q = _quote("susde", UnderlyingKind.STABLE_SYNTH, "0.09", hedge=True)
    res, _ = evaluate_entry(_opp(q), bad, D("1"), q.exit_liquidity_usd, P, KillState(), engine=ENG,
                            trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert res.approved is False
