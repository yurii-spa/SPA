"""
spa_core/tests/test_rates_desk_sleeves.py — OpportunityEngine + the 3 Phase-1 sleeves (B/C/D) + the
evaluate_hold continuous kills, all pure synthetic, Decimal end-to-end.

Proves:
  - the OpportunityEngine emits the right SHAPES per underlying (C only when hedge_available; D picks
    argmax net_rate venue; A/B emitted when legs exist), ranked by net_edge, with NO risk veto.
  - evaluate_hold fires EACH kill (depeg / compression / maturity / util / concentration) with the
    refusal-first ordering (structural kills precede the economic compression kill).
  - LeveredCarrySleeve respects max_leverage AND unwinds on carry compression.
  - RateMatrixSleeve rotation hysteresis: no churn on noise, switches when clearly better + gated.
  - PURITY: same (inputs, as_of) → same orders.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal as D

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.opportunity_engine import (
    CostConfig,
    OpportunityEngine,
    RateSurface,
)
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_hold
from spa_core.strategy_lab.rates_desk.sleeves import (
    BasisHedgeSleeve,
    LeveredCarrySleeve,
    RateMatrixSleeve,
)

P = RatePolicyParams()
ENG = FairValueEngine(P)
AS_OF = "2026-06-01"


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────
def _healthy_risk(u: str = "susde", as_of: str = AS_OF, **over) -> UnderlyingRisk:
    base = dict(
        underlying=u, as_of=as_of,
        nav_redemption_value=D("1"), market_price=D("1.0003"), peg_distance=D("0.0003"),
        peg_vol_30d=D("0.001"), redemption_sla_seconds=86400, reserve_fund_ratio=D("0.05"),
        funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=D("0.1"),
    )
    base.update(over)
    return UnderlyingRisk(**base)


def _q(u, venue, rate, hedge=False, ltv="0", util="0.5", exit_liq="2e6",
       tenor=86400 * 60, kind=UnderlyingKind.STABLE_SYNTH, mid=None) -> RateQuote:
    return RateQuote(
        underlying=u, kind=kind, venue=venue, protocol="p",
        market_id=mid or f"{venue.value}-{u}", tenor_seconds=tenor, as_of=AS_OF,
        quoted_rate=D(rate), tvl_usd=D("5e7"), exit_liquidity_usd=D(exit_liq),
        hedge_available=hedge, utilization=D(util), ltv=D(ltv),
    )


def _full_surface() -> RateSurface:
    """susde: PT(hedge)+boros+borrow+supply → all 4 shapes.  usde2: PT(no hedge)+borrow → A,B,D not C."""
    return RateSurface(
        as_of=AS_OF,
        pt_quotes={
            "susde": _q("susde", RateVenue.PENDLE_PT, "0.09", hedge=True, ltv="0.8"),
            "usde2": _q("usde2", RateVenue.PENDLE_PT, "0.08", hedge=False, ltv="0.7"),
        },
        lending_quotes={
            "susde": _q("susde", RateVenue.LENDING, "0.04", util="0.5"),
            "usde2": _q("usde2", RateVenue.LENDING, "0.035"),
        },
        boros_quotes={"susde": _q("susde", RateVenue.BOROS, "0.05", hedge=True)},
        supply_quotes={"susde": _q("susde", RateVenue.LENDING, "0.06")},
    )


def _risks():
    return {"susde": _healthy_risk("susde"), "usde2": _healthy_risk("usde2")}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# OpportunityEngine — the four shapes
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_scan_emits_all_four_shapes_for_full_underlying():
    eng = OpportunityEngine()
    det = eng.scan_detailed(_full_surface(), _risks(), AS_OF)
    shapes = {s.edge.shape for s in det if s.edge.underlying == "susde"}
    assert shapes == {TradeShape.FIXED_CARRY, TradeShape.LEVERED_CARRY,
                      TradeShape.BASIS_HEDGE, TradeShape.RATE_MATRIX}


def test_basis_hedge_only_when_hedge_available():
    eng = OpportunityEngine()
    det = eng.scan_detailed(_full_surface(), _risks(), AS_OF)
    # usde2 has no Boros hedge → NO basis-hedge opp; susde has one → exactly one.
    usde2_basis = [s for s in det if s.edge.underlying == "usde2"
                   and s.edge.shape == TradeShape.BASIS_HEDGE]
    susde_basis = [s for s in det if s.edge.underlying == "susde"
                   and s.edge.shape == TradeShape.BASIS_HEDGE]
    assert usde2_basis == []
    assert len(susde_basis) == 1


def test_rate_matrix_picks_argmax_net_rate_venue():
    # craft venues so SUPPLY clearly wins the matrix (high supply, modest PT, low boros)
    surf = RateSurface(
        as_of=AS_OF,
        pt_quotes={"susde": _q("susde", RateVenue.PENDLE_PT, "0.05", hedge=True)},
        boros_quotes={"susde": _q("susde", RateVenue.BOROS, "0.045", hedge=True)},
        supply_quotes={"susde": _q("susde", RateVenue.LENDING, "0.12")},
        lending_quotes={"susde": _q("susde", RateVenue.LENDING, "0.04")},
    )
    eng = OpportunityEngine()
    det = eng.scan_detailed(surf, {"susde": _healthy_risk("susde")}, AS_OF)
    matrix = [s for s in det if s.edge.shape == TradeShape.RATE_MATRIX]
    assert len(matrix) == 1
    assert matrix[0].edge.venue == RateVenue.LENDING.value  # supply argmax


def test_scan_ranked_by_net_edge_desc():
    eng = OpportunityEngine()
    det = eng.scan_detailed(_full_surface(), _risks(), AS_OF)
    nets = [s.edge.net_edge for s in det]
    assert nets == sorted(nets, reverse=True)


def test_scan_no_risk_veto_engine_emits_even_toxic_underlying():
    """The engine does NOT veto on risk — a toxic LRT still produces candidates (the GATE refuses)."""
    surf = RateSurface(
        as_of=AS_OF,
        pt_quotes={"ezeth": _q("ezeth", RateVenue.PENDLE_PT, "0.40", hedge=False,
                               kind=UnderlyingKind.LRT)},
    )
    toxic = _healthy_risk("ezeth", peg_distance=D("0.05"), funding_neg_frac_90d=D("0.5"),
                          nested_protocol_count=5, top_borrower_share=D("0.6"))
    eng = OpportunityEngine()
    det = eng.scan_detailed(surf, {"ezeth": toxic}, AS_OF)
    # the engine STILL emits the fixed-carry candidate — the risk veto is the gate's job, not scan's
    assert any(s.edge.shape == TradeShape.FIXED_CARRY for s in det)


def test_scan_drops_negative_carry_shape():
    """A LEVERED_CARRY where borrow >= PT implied is not a candidate (negative economics, not a veto)."""
    surf = RateSurface(
        as_of=AS_OF,
        pt_quotes={"susde": _q("susde", RateVenue.PENDLE_PT, "0.03")},
        lending_quotes={"susde": _q("susde", RateVenue.LENDING, "0.05")},  # borrow > implied
    )
    eng = OpportunityEngine()
    det = eng.scan_detailed(surf, {"susde": _healthy_risk("susde")}, AS_OF)
    assert all(s.edge.shape != TradeShape.LEVERED_CARRY for s in det)


def test_scan_purity_same_inputs_same_output():
    eng = OpportunityEngine()
    d1 = eng.scan_detailed(_full_surface(), _risks(), AS_OF)
    d2 = OpportunityEngine().scan_detailed(_full_surface(), _risks(), AS_OF)
    assert [s.edge.proof() for s in d1] == [s.edge.proof() for s in d2]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# evaluate_hold — each kill fires, refusal-first ordering
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _hold_opp(**over) -> Opportunity:
    q = _q("susde", RateVenue.PENDLE_PT, "0.09", hedge=True, **over)
    return Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=D("100000"))


def test_hold_kill_depeg():
    opp = _hold_opp()
    risk = _healthy_risk("susde", peg_distance=D("0.05"))
    res, ns = evaluate_hold(opp, risk, D("1"), opp.quote.exit_liquidity_usd, D("0.05"), P,
                            KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is False and res.reason == KillReason.UNDERLYING_DEPEG and ns.killed


def test_hold_kill_compression():
    opp = _hold_opp()
    res, ns = evaluate_hold(opp, _healthy_risk("susde"), D("1"), opp.quote.exit_liquidity_usd,
                            D("0.01"), P, KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is False and res.reason == KillReason.CARRY_COMPRESSION


def test_hold_kill_maturity():
    opp = _hold_opp(tenor=86400)  # 1 day < 2-day buffer
    res, ns = evaluate_hold(opp, _healthy_risk("susde"), D("1"), opp.quote.exit_liquidity_usd,
                            D("0.05"), P, KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is False and res.reason == KillReason.MATURITY_BUFFER


def test_hold_kill_utilization():
    opp = _hold_opp(util="0.99")  # > max_hold_utilization 0.97
    res, ns = evaluate_hold(opp, _healthy_risk("susde"), D("1"), opp.quote.exit_liquidity_usd,
                            D("0.05"), P, KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is False and res.reason == KillReason.UTILIZATION_TRAP


def test_hold_kill_concentration():
    opp = _hold_opp()
    risk = _healthy_risk("susde", top_borrower_share=D("0.55"))  # > max_hold_concentration 0.40
    res, ns = evaluate_hold(opp, risk, D("1"), opp.quote.exit_liquidity_usd, D("0.05"), P,
                            KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is False and res.reason == KillReason.CONCENTRATION


def test_hold_refusal_before_economics_ordering():
    """A position that is BOTH depegged AND carry-compressed must report the STRUCTURAL kill (depeg),
    never the economic one — refusal-before-economics."""
    opp = _hold_opp()
    risk = _healthy_risk("susde", peg_distance=D("0.05"))   # depeg
    res, ns = evaluate_hold(opp, risk, D("1"), opp.quote.exit_liquidity_usd,
                            D("0.001"), P, KillState(entry_carry=D("0.05")), engine=ENG)  # also compressed
    assert res.reason == KillReason.UNDERLYING_DEPEG  # structural beats economic


def test_hold_keeps_healthy():
    opp = _hold_opp()
    res, ns = evaluate_hold(opp, _healthy_risk("susde"), D("1"), opp.quote.exit_liquidity_usd,
                            D("0.05"), P, KillState(entry_carry=D("0.05")), engine=ENG)
    assert res.approved is True and res.reason == KillReason.NONE and not ns.killed


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# BasisHedgeSleeve (C)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_basis_sleeve_opens_only_hedged_underlyings():
    s = BasisHedgeSleeve()
    s.init(1_000_000.0, {})
    orders = s.step_apply(_full_surface(), _risks(), AS_OF)
    opens = [o for o in orders if o["action"] == "open"]
    assert opens, "basis sleeve should open at least the hedged susde book"
    # only susde (hedge_available) — never usde2
    assert all(o["underlying"] == "susde" for o in opens)
    assert all(o["shape"] == TradeShape.BASIS_HEDGE.value for o in opens)


def test_basis_sleeve_unwinds_on_depeg():
    s = BasisHedgeSleeve()
    s.init(1_000_000.0, {})
    s.step_apply(_full_surface(), _risks(), AS_OF)
    assert s._books, "expected an open basis book"
    # next tick: susde depegs → unwind
    risks = {"susde": _healthy_risk("susde", peg_distance=D("0.05")), "usde2": _healthy_risk("usde2")}
    orders = s.step_apply(_full_surface(), risks, AS_OF)
    unwinds = [o for o in orders if o["action"] == "unwind"]
    assert any(o["reason"] == KillReason.UNDERLYING_DEPEG.value for o in unwinds)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# LeveredCarrySleeve (B)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_levered_respects_max_leverage():
    s = LeveredCarrySleeve(max_leverage=D("2"))
    s.init(1_000_000.0, {})
    orders = s.step_apply(_full_surface(), _risks(), AS_OF)
    opens = [o for o in orders if o["action"] == "open"]
    assert opens
    for o in opens:
        assert D(o["leverage"]) <= D("2"), f"leverage {o['leverage']} exceeds cap"
        # ltv 0.8 → 1/(1-0.8)=5 implied, capped to 2
        assert D(o["leverage"]) == D("2") or D(o["leverage"]) <= D("2")


def test_levered_leverage_is_ltv_bounded_when_below_cap():
    # ltv 0.5 → 1/(1-0.5)=2.0 implied, below cap 3 → leverage exactly 2.0
    surf = RateSurface(
        as_of=AS_OF,
        pt_quotes={"susde": _q("susde", RateVenue.PENDLE_PT, "0.09", hedge=True)},
        lending_quotes={"susde": _q("susde", RateVenue.LENDING, "0.04", ltv="0.5")},
    )
    s = LeveredCarrySleeve(max_leverage=D("3"))
    s.init(1_000_000.0, {})
    orders = s.step_apply(surf, {"susde": _healthy_risk("susde")}, AS_OF)
    opens = [o for o in orders if o["action"] == "open"]
    assert opens and D(opens[0]["leverage"]) == D("2")


def test_levered_unwinds_on_compression():
    s = LeveredCarrySleeve()
    s.init(1_000_000.0, {})
    s.step_apply(_full_surface(), _risks(), AS_OF)
    mid = next(iter(s._books))
    # next tick: carry collapses well below 50% of entry → CARRY_COMPRESSION unwind
    orders = s.step_apply(_full_surface(), _risks(), AS_OF, current_carries={mid: D("0.001")})
    unwinds = [o for o in orders if o["action"] == "unwind"]
    assert any(o["reason"] == KillReason.CARRY_COMPRESSION.value for o in unwinds)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# RateMatrixSleeve (D) — rotation hysteresis
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _matrix_surface(susde_supply="0.06"):
    return RateSurface(
        as_of=AS_OF,
        pt_quotes={"susde": _q("susde", RateVenue.PENDLE_PT, "0.09", hedge=True, mid="PT-susde")},
        boros_quotes={"susde": _q("susde", RateVenue.BOROS, "0.05", hedge=True, mid="BOROS-susde")},
        supply_quotes={"susde": _q("susde", RateVenue.LENDING, susde_supply, mid="SUPPLY-susde")},
        lending_quotes={"susde": _q("susde", RateVenue.LENDING, "0.04", mid="BORROW-susde")},
    )


def test_matrix_opens_argmax_then_no_churn_on_noise():
    s = RateMatrixSleeve()
    s.init(1_000_000.0, {})
    orders = s.step_apply(_matrix_surface(), {"susde": _healthy_risk("susde")}, AS_OF)
    opens = [o for o in orders if o["action"] == "open"]
    assert len(opens) == 1
    held_mid = opens[0]["market_id"]
    held_venue = opens[0]["venue"]
    # next tick: a candidate that is only TRIVIALLY better (within switch_cost+buffer) → NO rotation
    # bump supply by a tiny amount that is < threshold so argmax stays PT and even if supply ticks up
    # it doesn't clear the hysteresis band.
    orders2 = s.step_apply(_matrix_surface(susde_supply="0.061"),
                           {"susde": _healthy_risk("susde")}, AS_OF)
    assert all(o["action"] != "rotate" for o in orders2), "rotated on noise (no hysteresis)"
    assert next(iter(s._books)) == held_mid  # still holding the same venue


def test_matrix_rotates_when_clearly_better_and_gated():
    s = RateMatrixSleeve(switch_cost=D("0.0005"), rotation_buffer=D("0.0030"))
    s.init(1_000_000.0, {})
    s.step_apply(_matrix_surface(), {"susde": _healthy_risk("susde")}, AS_OF)
    before_mid = next(iter(s._books))
    # next tick: supply jumps to 0.20 → its net_rate clears PT by FAR more than switch_cost+buffer
    orders = s.step_apply(_matrix_surface(susde_supply="0.20"),
                          {"susde": _healthy_risk("susde")}, AS_OF)
    rotates = [o for o in orders if o["action"] == "rotate"]
    assert len(rotates) == 1
    assert rotates[0]["to_venue"] == RateVenue.LENDING.value
    assert next(iter(s._books)) != before_mid  # rotated into the supply venue


def test_matrix_rotation_blocked_when_candidate_fails_gate():
    s = RateMatrixSleeve()
    s.init(1_000_000.0, {})
    s.step_apply(_matrix_surface(), {"susde": _healthy_risk("susde")}, AS_OF)
    before_mid = next(iter(s._books))
    # candidate venue would be far better, but the underlying is now DEPEGGED → gate refuses the
    # rotation entry. The held book itself also unwinds (depeg), so no rotate order is emitted.
    risks = {"susde": _healthy_risk("susde", peg_distance=D("0.05"))}
    orders = s.step_apply(_matrix_surface(susde_supply="0.20"), risks, AS_OF)
    assert all(o["action"] != "rotate" for o in orders)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# PURITY across the sleeves
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_sleeve_step_purity():
    s1, s2 = LeveredCarrySleeve(), LeveredCarrySleeve()
    s1.init(1_000_000.0, {}); s2.init(1_000_000.0, {})
    o1 = s1.step_apply(_full_surface(), _risks(), AS_OF)
    o2 = s2.step_apply(_full_surface(), _risks(), AS_OF)
    assert o1 == o2  # same inputs → byte-identical orders
