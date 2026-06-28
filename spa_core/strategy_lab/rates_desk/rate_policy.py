"""
spa_core/strategy_lab/rates_desk/rate_policy.py — the REFUSAL-FIRST rates-desk gate.

This is where the whole edge lives: a deterministic gate that REFUSES tail-comp BEFORE it ever looks
at the economics. A book can have a spectacular quoted rate and still be vetoed because its tail
haircut says the rate is just risk premium you'll pay back.

HARD INVARIANT — refusal before economics. evaluate_entry runs the checks in this exact order and
SHORT-CIRCUITS on the first failure:

  (1) TAIL_VETO        structural_haircut > max_structural_haircut (the toxicity REFUSE — size-proof:
                       peg+funding+oracle+protocol, EXCLUDING the size-dependent liquidity term, so a
                       tail-toxic book is refused at ANY size) — THEN additionally
                       total_haircut > max_total_haircut (the economics-incl-liquidity REFUSE)
  (2) UNDERLYING_DEPEG peg_distance  > max_peg_distance
  (3) ORACLE_STALE     oracle_staleness > tolerance
  (4) STABLE_DEPEG     debt/quote stable depeg > tolerance
  (5) FUNDING_FLIP     neg-funding streak >= kill (hysteresis via KillState.neg_funding_streak)
  (6) ECONOMICS        net_edge >= hurdle  AND  fair-cleared edge persists
  (7) SIZE             approved = min(requested, max_size_frac_of_exit * exit_liquidity); a size that
                       collapses below min_tradeable_size_usd is a SIZE_FLOOR refuse.

evaluate_hold is the continuous-kill side: each tick re-checks depeg, carry/basis compression,
funding flip, maturity buffer, utilization trap, exit-liquidity collapse, and concentration — and
returns a NEW KillState. The EXIT_CAPACITY kill (§9) unwinds the moment the position's CURRENT one-
tick exit liquidity falls below the open position size: a safe carry book that can no longer be
exited at size is an illiquid bag, so the desk derisks BEFORE the basis even compresses.

COMPOSITION: this RatePolicy composes UNDER the global spa_core.risk.policy.RiskPolicy. It is only
ever MORE restrictive — a RatePolicy approval is necessary but NOT sufficient; the global RiskPolicy
still has to approve the resulting position. (See compose_under_global_policy.)

PURE: every function is f(inputs, as_of, state) → (result, new_state). No clock, no IO, no RNG.
fail-CLOSED: any malformed input refuses. LLM-FORBIDDEN. Every GateResult.detail + the
YieldDecomposition are string-exact / hashable for the proof chain.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional, Tuple

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    GateResult,
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    TradeShape,
    UnderlyingRisk,
    YieldDecomposition,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine, _safe_decimal

# A funding "flip tick" = funding was negative for the MAJORITY of the recent window (a hostile
# carry regime). It is the per-tick event the funding-flip hysteresis streak counts toward
# `params.funding_flip_streak_kill`. The MAJORITY definition (>= 0.5 of the window) is structural —
# it is not a calibrated coefficient — so it lives here as one named constant rather than as a bare
# literal repeated in the entry gate and the hold gate (a duplicated predicate threshold can drift).
FUNDING_FLIP_TICK_FRAC = Decimal("0.5")


def _as_of_epoch(as_of: str) -> Optional[int]:
    """PURE as_of (ISO date / timestamp string) → UTC epoch-seconds. Date-only strings anchor at
    00:00:00 UTC; full timestamps are honored. Never reads the clock. Returns None on a malformed
    as_of (fail-CLOSED: callers treat None as 'cannot measure duration')."""
    if not isinstance(as_of, str) or not as_of:
        return None
    s = as_of.strip()
    try:
        if len(s) <= 10:
            d = datetime.date.fromisoformat(s[:10])
            dt = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
        else:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def _refused(reason: KillReason, opp: Opportunity, decomp: YieldDecomposition,
             net_edge: Decimal, detail: dict) -> GateResult:
    """Build a fail-CLOSED REFUSED GateResult (approved=False, size 0). Centralized so every refusal
    path is byte-identical."""
    return GateResult(
        approved=False,
        reason=reason,
        as_of=opp.quote.as_of,
        underlying=opp.quote.underlying,
        shape=opp.shape,
        net_edge=net_edge,
        approved_size_usd=D0,
        decomposition=decomp,
        detail={k: str(v) for k, v in detail.items()},
    )


def evaluate_entry(
    opp: Opportunity,
    risk: UnderlyingRisk,
    debt_asset_price: Decimal,
    exit_liquidity: Decimal,
    params: RatePolicyParams,
    state: KillState,
    engine: Optional[FairValueEngine] = None,
    trailing_yield: Optional[Decimal] = None,
    boros_forward: Optional[Decimal] = None,
) -> Tuple[GateResult, KillState]:
    """REFUSAL-FIRST entry gate. Returns (GateResult, new KillState).

    `debt_asset_price` is the spot of the debt/quote stable (1.0 == pegged) used by the STABLE_DEPEG
    veto. `exit_liquidity` is the one-tick exit capacity used for both the liquidity haircut and the
    SIZE cap. `state` carries the funding-flip hysteresis streak in.

    PURE / fail-CLOSED. The first failing veto short-circuits — economics are NEVER consulted on a
    book that failed a tail/structural veto."""
    eng = engine or FairValueEngine(params)
    q: RateQuote = opp.quote
    as_of = q.as_of

    # ── update funding-flip hysteresis streak FIRST (so it's threaded out even on early refusals) ──
    fneg = _safe_decimal(risk.funding_neg_frac_90d)
    # a "flip tick" = funding is negative the majority of the recent window (hostile carry regime)
    flip_tick = (fneg is not None and fneg >= FUNDING_FLIP_TICK_FRAC)
    new_streak = (state.neg_funding_streak + 1) if flip_tick else 0
    next_state = KillState(
        neg_funding_streak=new_streak,
        killed=False,
        kill_reason=KillReason.NONE,
        last_as_of=as_of,
        entry_carry=None,
    )

    # ── the fair-value decomposition (needed by veto 1 + economics) ──
    decomp = eng.fair(
        risk=risk,
        kind=q.kind,
        tenor_seconds=q.tenor_seconds,
        hedge_available=q.hedge_available,
        position_size_usd=opp.requested_size_usd,
        exit_liquidity_usd=exit_liquidity,
        as_of=as_of,
        trailing_yield=trailing_yield,
        boros_forward=boros_forward,
    )

    # (1) TAIL_VETO — the fair-value REFUSE. Vetoes EVERYTHING regardless of how good the quote is, OR
    #     of how SMALL the requested size is. Computed in TWO parts (refusal-first):
    #
    #     (1a) STRUCTURAL toxicity veto — the toxicity verdict is on the SIZE-INDEPENDENT structural
    #          haircut (peg + funding + oracle + protocol), EXCLUDING the size-dependent liquidity term.
    #          A tail-toxic book (ezETH/eeth/LRT with a structural tail over the cap) is REFUSED at ANY
    #          size. This closes red-team FAIL #1: previously a toxic book could be sized DOWN until its
    #          liquidity_haircut shrank enough to drop total_haircut under the total cap, "sizing around"
    #          the toxicity. Sizing down must shrink the POSITION, never the TOXICITY verdict — so the
    #          veto that decides toxicity ignores the liquidity term entirely.
    if decomp.structural_haircut > params.max_structural_haircut:
        return _refused(KillReason.TAIL_VETO, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "structural_haircut": decomp.structural_haircut,
            "max_structural_haircut": params.max_structural_haircut,
            "total_haircut": decomp.total_haircut,
            "max_total_haircut": params.max_total_haircut,
            "note": ("structural tail-comp veto: peg+funding+oracle+protocol haircut exceeds the "
                     "size-independent toxicity cap — REFUSED at any size (cannot be sized around)"),
        }), next_state

    #     (1b) TOTAL-haircut economics veto — KEPT ADDITIONALLY. Even a structurally-clean book can be
    #          tail-comp once its OWN exit impact (the size-dependent liquidity haircut) is added: if the
    #          full decomposition still does not clear the total cap the quote is risk premium, not carry.
    #          A book can therefore fail EITHER on structural toxicity (1a, size-proof) OR on total
    #          economics-incl-liquidity (1b). Toxicity can never be sized around; economics can be (that
    #          is correct — a smaller, exit-feasible ticket is genuinely less risk).
    if decomp.total_haircut > params.max_total_haircut:
        return _refused(KillReason.TAIL_VETO, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "total_haircut": decomp.total_haircut,
            "max_total_haircut": params.max_total_haircut,
            "structural_haircut": decomp.structural_haircut,
            "max_structural_haircut": params.max_structural_haircut,
            "note": "tail-comp veto: quoted rate is risk premium, not carry (total incl. liquidity)",
        }), next_state

    # (2) UNDERLYING_DEPEG (a negative peg distance is malformed → fail-CLOSED)
    peg = _safe_decimal(risk.peg_distance)
    if peg is None or peg < 0 or peg > params.max_peg_distance:
        return _refused(KillReason.UNDERLYING_DEPEG, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "peg_distance": "malformed" if peg is None else peg,
            "max_peg_distance": params.max_peg_distance,
        }), next_state

    # (3) ORACLE_STALE
    stale = risk.oracle_staleness_seconds
    if not isinstance(stale, int) or stale < 0 or stale > params.max_oracle_staleness_s:
        return _refused(KillReason.ORACLE_STALE, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "oracle_staleness_seconds": stale,
            "max_oracle_staleness_s": params.max_oracle_staleness_s,
        }), next_state

    # (4) STABLE_DEPEG — the debt/quote stable must hold its peg.
    dp = _safe_decimal(debt_asset_price)
    if dp is None or (Decimal("1") - dp).copy_abs() > params.max_stable_depeg:
        return _refused(KillReason.STABLE_DEPEG, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "debt_asset_price": "malformed" if dp is None else dp,
            "max_stable_depeg": params.max_stable_depeg,
        }), next_state

    # (5) FUNDING_FLIP — hysteresis: only kill after a sustained negative-funding streak.
    if new_streak >= params.funding_flip_streak_kill:
        return _refused(KillReason.FUNDING_FLIP, opp, decomp, decomp.fair_yield - q.quoted_rate, {
            "neg_funding_streak": new_streak,
            "funding_flip_streak_kill": params.funding_flip_streak_kill,
        }), next_state

    # ── only NOW do economics matter (refusal-first invariant satisfied) ──
    # (6) ECONOMICS — net edge = quoted_rate - fair_yield - cost. Must clear the hurdle AND the carry
    #     must persist (edge after cost is positive, i.e. the quote actually beats fair value + cost).
    qr = _safe_decimal(q.quoted_rate)
    if qr is None:
        return _refused(KillReason.ECONOMICS, opp, decomp, D0, {
            "quoted_rate": "malformed",
        }), next_state
    net_edge = qr - decomp.fair_yield - params.cost_buffer
    if net_edge < params.edge_hurdle or net_edge <= D0:
        return _refused(KillReason.ECONOMICS, opp, decomp, net_edge, {
            "net_edge": net_edge,
            "edge_hurdle": params.edge_hurdle,
            "fair_yield": decomp.fair_yield,
            "quoted_rate": qr,
            "cost_buffer": params.cost_buffer,
        }), next_state

    # (7) SIZE — bound by exit capacity. Never take more than a fraction of one-tick exit liquidity.
    exitl = _safe_decimal(exit_liquidity)
    req = _safe_decimal(opp.requested_size_usd)
    if exitl is None or req is None or exitl <= 0 or req <= 0:
        return _refused(KillReason.SIZE_FLOOR, opp, decomp, net_edge, {
            "exit_liquidity": "malformed" if exitl is None else exitl,
            "requested_size_usd": "malformed" if req is None else req,
        }), next_state
    cap = params.max_size_frac_of_exit * exitl
    approved_size = min(req, cap)
    if approved_size < params.min_tradeable_size_usd:
        return _refused(KillReason.SIZE_FLOOR, opp, decomp, net_edge, {
            "approved_size_usd": approved_size,
            "min_tradeable_size_usd": params.min_tradeable_size_usd,
            "exit_cap": cap,
        }), next_state

    # APPROVED. Record the locked carry on the state for compression tracking on the hold side.
    approved_state = KillState(
        neg_funding_streak=new_streak,
        killed=False,
        kill_reason=KillReason.NONE,
        last_as_of=as_of,
        entry_carry=net_edge,
    )
    result = GateResult(
        approved=True,
        reason=KillReason.NONE,
        as_of=as_of,
        underlying=q.underlying,
        shape=opp.shape,
        net_edge=net_edge,
        approved_size_usd=approved_size,
        decomposition=decomp,
        detail={
            "net_edge": str(net_edge),
            "approved_size_usd": str(approved_size),
            "exit_cap": str(cap),
            "fair_yield": str(decomp.fair_yield),
            "quoted_rate": str(qr),
        },
    )
    return result, approved_state


def evaluate_hold(
    opp: Opportunity,
    risk: UnderlyingRisk,
    debt_asset_price: Decimal,
    exit_liquidity: Decimal,
    current_carry: Decimal,
    params: RatePolicyParams,
    state: KillState,
    engine: Optional[FairValueEngine] = None,
) -> Tuple[GateResult, KillState]:
    """Continuous-kill gate for a HELD position. REFUSAL-FIRST again: structural/peg kills precede
    the economic compression kill. Returns (GateResult, new KillState). `current_carry` is the carry
    the position is now realizing (vs state.entry_carry for compression).

    A GateResult here means: approved=True → keep holding; approved=False → UNWIND (reason gives why).
    PURE / fail-CLOSED."""
    eng = engine or FairValueEngine(params)
    q = opp.quote
    as_of = q.as_of

    fneg = _safe_decimal(risk.funding_neg_frac_90d)
    flip_tick = (fneg is not None and fneg >= FUNDING_FLIP_TICK_FRAC)
    new_streak = (state.neg_funding_streak + 1) if flip_tick else 0

    # ── continuous utilization-trap tracking (compute the NEW high_util_since up-front so it threads
    #    out of EVERY return path, kill or hold — pure state in → state out) ──
    now_ts = _as_of_epoch(as_of)
    util = _safe_decimal(q.utilization)
    util_high = (util is not None and util > params.max_hold_utilization)
    if not util_high:
        # utilization has dropped to/below the ceiling → the streak resets.
        next_high_util_since: Optional[int] = None
    elif state.high_util_since is not None:
        # already in a high streak → carry the original crossing timestamp forward.
        next_high_util_since = state.high_util_since
    else:
        # FIRST tick crossing the ceiling → stamp it (None when as_of is unparseable: fail-CLOSED below).
        next_high_util_since = now_ts

    decomp = eng.fair(
        risk=risk, kind=q.kind, tenor_seconds=q.tenor_seconds, hedge_available=q.hedge_available,
        position_size_usd=opp.requested_size_usd, exit_liquidity_usd=exit_liquidity, as_of=as_of,
    )

    def _kill(reason: KillReason, detail: dict) -> Tuple[GateResult, KillState]:
        ns = KillState(neg_funding_streak=new_streak, killed=True, kill_reason=reason,
                       last_as_of=as_of, entry_carry=state.entry_carry,
                       high_util_since=next_high_util_since)
        return _refused(reason, opp, decomp, current_carry, detail), ns

    # (a) UNDERLYING_DEPEG — unwind on a peg break (negative peg = malformed → fail-CLOSED).
    peg = _safe_decimal(risk.peg_distance)
    if peg is None or peg < 0 or peg > params.max_peg_distance:
        return _kill(KillReason.UNDERLYING_DEPEG, {
            "peg_distance": "malformed" if peg is None else peg, "max": params.max_peg_distance})

    # (b) STABLE_DEPEG — debt/quote stable broke peg.
    dp = _safe_decimal(debt_asset_price)
    if dp is None or (Decimal("1") - dp).copy_abs() > params.max_stable_depeg:
        return _kill(KillReason.STABLE_DEPEG, {
            "debt_asset_price": "malformed" if dp is None else dp, "max": params.max_stable_depeg})

    # (c) ORACLE_STALE
    stale = risk.oracle_staleness_seconds
    if not isinstance(stale, int) or stale < 0 or stale > params.max_oracle_staleness_s:
        return _kill(KillReason.ORACLE_STALE, {
            "oracle_staleness_seconds": stale, "max": params.max_oracle_staleness_s})

    # (d) MATURITY_BUFFER — too close to maturity to safely hold/roll.
    if not isinstance(q.tenor_seconds, int) or q.tenor_seconds <= params.maturity_buffer_seconds:
        return _kill(KillReason.MATURITY_BUFFER, {
            "tenor_seconds": q.tenor_seconds, "buffer": params.maturity_buffer_seconds})

    # (e) UTILIZATION_TRAP — pool too utilized to exit (levered/lending legs). HYSTERESIS: a single
    #     high-utilization tick does NOT kill; utilization must stay above max CONTINUOUSLY for at
    #     least params.max_utilization_seconds. next_high_util_since (computed up-front) is the epoch
    #     the streak began; we fire only once (now - since) >= the window. fail-CLOSED: if as_of is
    #     unparseable while utilization is high we cannot measure the duration → kill immediately.
    if util_high:
        if now_ts is None or next_high_util_since is None:
            return _kill(KillReason.UTILIZATION_TRAP, {
                "utilization": util, "max": params.max_hold_utilization,
                "note": "as_of unparseable — cannot measure high-util duration (fail-closed)"})
        elapsed = now_ts - next_high_util_since
        if elapsed >= params.max_utilization_seconds:
            return _kill(KillReason.UTILIZATION_TRAP, {
                "utilization": util, "max": params.max_hold_utilization,
                "high_util_since": next_high_util_since, "elapsed_seconds": elapsed,
                "max_utilization_seconds": params.max_utilization_seconds})

    # (f) EXIT_CAPACITY — the exit-liquidity-COLLAPSE kill (the brief §9's hardest failure mode).
    #     If the position's CURRENT one-tick exit capacity has fallen BELOW the open position size,
    #     the desk literally cannot get out at size — a safe carry book has become an illiquid bag.
    #     This is strictly more severe than the fractional CONCENTRATION breach below (collapse to
    #     < 1.0x size, not merely > max_size_frac_of_exit), so it is checked FIRST and reported with
    #     its own reason. fail-CLOSED: a malformed/non-positive exit_liquidity with a real position is
    #     itself a collapse (you cannot exit into nothing) → kill. A malformed requested size is
    #     malformed input → kill.
    exitl = _safe_decimal(exit_liquidity)
    req = _safe_decimal(opp.requested_size_usd)
    if req is None or req <= 0:
        return _kill(KillReason.EXIT_CAPACITY, {
            "requested_size_usd": "malformed" if req is None else req,
            "note": "position size malformed/non-positive (fail-closed)"})
    if exitl is None or exitl <= 0 or exitl < req:
        return _kill(KillReason.EXIT_CAPACITY, {
            "exit_liquidity_usd": "malformed" if exitl is None else exitl,
            "position_size_usd": req,
            "note": "one-tick exit capacity collapsed below position size — cannot exit at size"})

    # (g) CONCENTRATION — position too large vs current exit liquidity OR borrower concentration.
    #     SHAPE-AWARE fail-CLOSED: for shapes that carry a BORROW/lending leg (LEVERED_CARRY,
    #     RATE_MATRIX) borrower concentration is a real tail — a MISSING/malformed top_borrower_share
    #     means we cannot confirm the pool is not crowded by one borrower → REFUSE (you cannot prove a
    #     position is safe on a risk you cannot see). For shapes with NO borrow leg (FIXED_CARRY held-
    #     to-maturity PT, BASIS_HEDGE) borrower concentration is N/A, so a None share is legitimately
    #     not-applicable and must NOT spuriously refuse.
    topb = _safe_decimal(risk.top_borrower_share)
    has_borrow_leg = opp.shape in (TradeShape.LEVERED_CARRY, TradeShape.RATE_MATRIX)
    over_borrower = (topb is not None and topb > params.max_hold_concentration)
    borrower_unknown = (has_borrow_leg and topb is None)  # fail-CLOSED only where concentration matters
    over_exit = (exitl > 0 and (req / exitl) > params.max_size_frac_of_exit)
    if over_borrower or borrower_unknown or over_exit:
        return _kill(KillReason.CONCENTRATION, {
            "top_borrower_share": "malformed" if topb is None else topb,
            "size_vs_exit": (req / exitl),
            "max_borrower": params.max_hold_concentration,
            "max_size_frac_of_exit": params.max_size_frac_of_exit})

    # (h) FUNDING_FLIP — sustained negative-funding streak.
    if new_streak >= params.funding_flip_streak_kill:
        return _kill(KillReason.FUNDING_FLIP, {
            "neg_funding_streak": new_streak, "kill": params.funding_flip_streak_kill})

    # (i) CARRY_COMPRESSION — the locked carry/basis has compressed away (economic kill, LAST).
    cc = _safe_decimal(current_carry)
    entry = state.entry_carry
    if cc is None:
        return _kill(KillReason.CARRY_COMPRESSION, {"current_carry": "malformed"})
    if entry is not None and entry > D0:
        if cc < entry * params.carry_compression_frac:
            return _kill(KillReason.CARRY_COMPRESSION, {
                "current_carry": cc, "entry_carry": entry,
                "compression_frac": params.carry_compression_frac})

    # HOLD. (high_util_since threaded forward: utilization is still high but has not yet been high
    # long enough to trap — the streak keeps accruing across ticks.)
    keep_state = KillState(neg_funding_streak=new_streak, killed=False, kill_reason=KillReason.NONE,
                           last_as_of=as_of, entry_carry=state.entry_carry,
                           high_util_since=next_high_util_since)
    result = GateResult(
        approved=True, reason=KillReason.NONE, as_of=as_of, underlying=q.underlying, shape=opp.shape,
        net_edge=cc, approved_size_usd=opp.requested_size_usd, decomposition=decomp,
        detail={"action": "hold", "current_carry": str(cc)},
    )
    return result, keep_state


def compose_under_global_policy(rate_result: GateResult, global_approved: bool) -> bool:
    """The composition rule, made explicit: a position may move capital ONLY IF the RatePolicy gate
    approved it AND the global RiskPolicy approved it. The RatePolicy is strictly MORE restrictive —
    it can VETO what the global policy would allow, but can never permit what the global policy
    forbids. (AND, never OR.)"""
    return bool(rate_result.approved and global_approved)
