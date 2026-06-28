"""
spa_core/tests/test_rates_desk_shape_funding.py — wstETH calibration fix (FAIL #2) regression suite.

The bug: the funding_flip_haircut (a PERP/FORWARD-FUNDING-leg risk that SATURATES to its 0.06 cap for
any funding-neg > 10% — i.e. the majority of real days) was applied to EVERY underlying regardless of
the TradeShape. A FIXED_CARRY Pendle PT held to maturity has NO perp/forward-funding leg, so it cannot
bleed on a funding flip — yet the haircut was stacked onto it, pushing a PLAIN clean LST (wstETH:
peg+oracle+protocol ≈ 0.046) over the structural-toxicity cap and refusing it 100% of days. That is a
model-input error, not real risk.

The fix: the funding_flip_haircut is now SHAPE-DRIVEN via TradeShape.has_funding_leg — zero for the
no-funding-leg shape (FIXED_CARRY), kept in full for funding-bearing shapes (LEVERED_CARRY / BASIS_HEDGE
/ RATE_MATRIX). Applied consistently to ALL underlyings of a shape (NOT cherry-picked for wstETH).
fail-CLOSED: an undeclared shape (None) KEEPS the funding haircut.

CRITICAL GUARDRAIL: toxic LRTs are refused on peg+oracle+protocol ALONE (≈ 0.0967 > cap) with NO
funding needed, so zeroing FIXED_CARRY funding does NOT re-open the toxic-LRT hole. These tests assert
the toxic books stay refused at EVERY size under EVERY shape.

Run:
    python3 -m pytest spa_core/tests/test_rates_desk_shape_funding.py -p no:randomly -q
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal as D

from spa_core.strategy_lab.rates_desk import config as rd_config
from spa_core.strategy_lab.rates_desk.contracts import (
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
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry

P = RatePolicyParams()
ENG = FairValueEngine(P)

FUNDING_BEARING = (TradeShape.LEVERED_CARRY, TradeShape.BASIS_HEDGE, TradeShape.RATE_MATRIX)


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────
def _wsteth_risk(funding_neg: str = "0.60") -> UnderlyingRisk:
    """A clean PLAIN-LST (wstETH) risk surface in a HOSTILE funding regime (funding_neg high, so the
    funding haircut would SATURATE if it were applied). Tight peg, healthy oracle, single-protocol."""
    u = "wsteth"
    return UnderlyingRisk(
        underlying=u, as_of="2026-06-26", nav_redemption_value=D("1"), market_price=D("0.997"),
        peg_distance=D("0.003"), peg_vol_30d=D("0.004"),
        redemption_sla_seconds=rd_config.redemption_sla_seconds(u),
        reserve_fund_ratio=D(str(rd_config.reserve_fund_ratio(u))),
        funding_neg_frac_90d=D(funding_neg), oracle_kind=rd_config.oracle_kind(u),
        oracle_staleness_seconds=rd_config.oracle_staleness_seconds(u),
        nested_protocol_count=rd_config.nested_protocol_count(u),
        top_borrower_share=D(str(rd_config.top_borrower_share(u))))


def _toxic_lrt_risk(u: str = "ezeth") -> UnderlyingRisk:
    """The seq=63-style toxic LRT exploit surface: moderate peg UNDER the 1% hard depeg gate + peg vol,
    with the documented restaking constants (nesting/concentration) → structural (peg+oracle+protocol,
    NO funding) ≈ 0.0967 > cap. LOW funding_neg so it's clear the refusal is NOT funding-driven."""
    return UnderlyingRisk(
        underlying=u, as_of="2024-09-01", nav_redemption_value=D("1"), market_price=D("0.992"),
        peg_distance=D("0.008"), peg_vol_30d=D("0.016"),
        redemption_sla_seconds=rd_config.redemption_sla_seconds(u),
        reserve_fund_ratio=D(str(rd_config.reserve_fund_ratio(u))),
        funding_neg_frac_90d=D("0.05"), oracle_kind=rd_config.oracle_kind(u),
        oracle_staleness_seconds=rd_config.oracle_staleness_seconds(u),
        nested_protocol_count=rd_config.nested_protocol_count(u),
        top_borrower_share=D(str(rd_config.top_borrower_share(u))))


def _decomp(risk, kind, shape, fneg_present=True):
    return ENG.fair(risk=risk, kind=kind, tenor_seconds=86400 * 60, hedge_available=False,
                    position_size_usd=D("100000"), exit_liquidity_usd=D("2e6"),
                    as_of=risk.as_of, shape=shape)


def _entry(risk, kind, shape, size="100000", exit_liq=D("2e6"), quoted="0.06", **econ):
    q = RateQuote(underlying=risk.underlying, kind=kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
                  market_id=f"PT-{risk.underlying}", tenor_seconds=86400 * 60, as_of=risk.as_of,
                  quoted_rate=D(quoted), tvl_usd=D("5e7"), exit_liquidity_usd=exit_liq,
                  hedge_available=(shape in (TradeShape.BASIS_HEDGE,)))
    opp = Opportunity(quote=q, shape=shape, requested_size_usd=D(size))
    return evaluate_entry(opp, risk, D("1"), q.exit_liquidity_usd, P, KillState(), engine=ENG, **econ)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. shape DRIVES the funding haircut
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_fixed_carry_zeroes_funding_haircut():
    """A FIXED_CARRY held-to-maturity PT has NO perp/forward-funding leg → funding_flip_haircut == 0,
    EVEN in a hostile funding regime that would otherwise saturate the haircut to its cap."""
    risk = _wsteth_risk(funding_neg="0.95")  # would saturate the funding haircut if it applied
    dec = _decomp(risk, UnderlyingKind.LST, TradeShape.FIXED_CARRY)
    assert dec.funding_flip_haircut == D("0")


def test_funding_bearing_shapes_keep_funding_haircut():
    """LEVERED_CARRY / BASIS_HEDGE / RATE_MATRIX carry a funding/perp leg → the funding haircut is KEPT
    (saturates to its cap in this hostile regime). Same underlying, same risk — only the shape differs."""
    risk = _wsteth_risk(funding_neg="0.95")
    for shape in FUNDING_BEARING:
        dec = _decomp(risk, UnderlyingKind.LST, shape)
        assert dec.funding_flip_haircut == P.cap_funding, f"{shape} must keep the funding haircut"


def test_undeclared_shape_keeps_funding_fail_closed():
    """fail-CLOSED: when no shape is declared (None) the funding leg is ASSUMED PRESENT — an unknown
    shape never silently drops a real risk."""
    risk = _wsteth_risk(funding_neg="0.95")
    dec = ENG.fair(risk=risk, kind=UnderlyingKind.LST, tenor_seconds=86400 * 60, hedge_available=False,
                   position_size_usd=D("100000"), exit_liquidity_usd=D("2e6"), as_of=risk.as_of)
    assert dec.funding_flip_haircut == P.cap_funding


def test_shape_is_the_only_difference_driving_funding():
    """The ONLY thing that changes funding between FIXED_CARRY (0) and a funding-bearing shape (cap) is
    the TradeShape — same risk surface, same kind. The fix is shape-driven, not token-driven."""
    risk = _wsteth_risk(funding_neg="0.95")
    fixed = _decomp(risk, UnderlyingKind.LST, TradeShape.FIXED_CARRY).funding_flip_haircut
    levered = _decomp(risk, UnderlyingKind.LST, TradeShape.LEVERED_CARRY).funding_flip_haircut
    assert fixed == D("0") and levered == P.cap_funding


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. wstETH now APPROVES as FIXED_CARRY (it was genuinely clean — model-input error fixed)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_wsteth_fixed_carry_structural_below_cap():
    """wstETH's GENUINE structural tail (peg+oracle+protocol, funding correctly 0 for FIXED_CARRY) is
    below the cap — it is genuinely clean carry once the model is shape-correct."""
    risk = _wsteth_risk()
    dec = _decomp(risk, UnderlyingKind.LST, TradeShape.FIXED_CARRY)
    assert dec.funding_flip_haircut == D("0")
    assert dec.structural_haircut < P.max_structural_haircut


def test_wsteth_fixed_carry_approves():
    """wstETH APPROVES as a FIXED_CARRY entry (clean structural, real edge). The 100%-refusal model-input
    error is fixed without weakening any genuine veto."""
    risk = _wsteth_risk()
    res, _ = _entry(risk, UnderlyingKind.LST, TradeShape.FIXED_CARRY, quoted="0.10")
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert res.approved_size_usd > D("0")


def test_wsteth_with_funding_leg_would_be_refused_on_funding():
    """CONSISTENCY proof: the SAME wstETH risk expressed as a funding-BEARING shape carries the funding
    haircut — its structural haircut rises by the funding term. This shows the fix does not blanket-clear
    wstETH; only the no-funding-leg shape is clean (a funding-leg book on a hostile regime is heavier)."""
    risk = _wsteth_risk(funding_neg="0.95")
    fixed = _decomp(risk, UnderlyingKind.LST, TradeShape.FIXED_CARRY).structural_haircut
    levered = _decomp(risk, UnderlyingKind.LST, TradeShape.LEVERED_CARRY).structural_haircut
    assert levered == fixed + P.cap_funding


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. GUARDRAIL — toxic LRTs STILL refused at EVERY size under EVERY shape (no re-opened hole)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_toxic_lrt_refused_fixed_carry_every_size_on_non_funding_structural():
    """A toxic LRT is REFUSED as FIXED_CARRY at EVERY size — and crucially its funding haircut is 0 here
    (FIXED_CARRY), proving the refusal rests on peg+oracle+protocol (its GENUINE structural tail), NOT on
    funding. The size-down exploit stays closed."""
    for u in ("ezeth", "rseth"):
        risk = _toxic_lrt_risk(u)
        dec = _decomp(risk, UnderlyingKind.LRT, TradeShape.FIXED_CARRY)
        assert dec.funding_flip_haircut == D("0"), "FIXED_CARRY toxic book also gets funding 0"
        assert dec.structural_haircut > P.max_structural_haircut, "toxic on peg+oracle+protocol ALONE"
        for size in ("1000", "4062.5", "50000", "100000"):
            res, _ = _entry(risk, UnderlyingKind.LRT, TradeShape.FIXED_CARRY, size=size,
                            exit_liq=D("65000"), quoted="0.35")
            assert res.approved is False, f"{u} approved at size {size} — toxic hole reopened"
            assert res.reason == KillReason.TAIL_VETO


def test_toxic_lrt_refused_under_every_shape():
    """A toxic LRT is refused under FIXED_CARRY (funding 0) AND under every funding-bearing shape (funding
    kept, even heavier). Shape drives funding; toxicity is refused regardless of shape."""
    for u in ("ezeth", "rseth"):
        risk = _toxic_lrt_risk(u)
        for shape in (TradeShape.FIXED_CARRY,) + FUNDING_BEARING:
            res, _ = _entry(risk, UnderlyingKind.LRT, shape, size="1000", exit_liq=D("65000"),
                            quoted="0.35")
            assert res.approved is False, f"{u} approved under {shape}"
            assert res.reason == KillReason.TAIL_VETO


def test_canonical_toxic_lrt_set_unchanged():
    """Guard: the config LRT (restaking) set is exactly {ezeth, rseth}. If a new restaking token is added
    its toxic structural tail must be re-verified against the cap (revisit this suite)."""
    lrts = {u for u, kind in rd_config.UNDERLYING_KINDS.items() if kind == "lrt"}
    assert lrts == {"ezeth", "rseth"}, "config LRT set changed — re-verify toxic refusal"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. TradeShape.has_funding_leg is the single source of truth
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_has_funding_leg_classification():
    """FIXED_CARRY has no funding leg; the other three do. This property DRIVES the funding haircut."""
    assert TradeShape.FIXED_CARRY.has_funding_leg is False
    for shape in FUNDING_BEARING:
        assert shape.has_funding_leg is True
