"""
spa_core/strategy_lab/rates_desk/fair_value_engine.py — Decimal fair-value engine for the rates desk.

Promotes the validated fair_value.py REFUSE model (baseline - tail_haircut → CARRY/REFUSE) into the
desk's full DECOMPOSITION engine:

    fair_yield = baseline_yield(kind, tenor, hedge)  -  Σ five_haircuts

The baseline is the honest yield you'd fairly expect absent mispricing; the five haircuts are the
priced-in tail compensations the desk REFUSES to pay for. The quoted rate is harvestable carry only
to the extent it clears `fair_yield + cost`.

This is the SAME thesis as fair_value.py (separate real spread from tail-comp), but:
  • Decimal end-to-end (replay-determinism),
  • the single linear tail_haircut is unpacked into the brief's FIVE structural haircuts,
  • baseline is kind-aware (RWA t-bill / synthetic carry / staking / restaking-staking-only).

PURE: every method is f(inputs, as_of) → result. No clock, no IO, no RNG. fail-CLOSED: a malformed
risk surface produces a MAX-haircut decomposition (fair_yield ≤ 0), never a silent low haircut.
LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    RatePolicyParams,
    UnderlyingKind,
    UnderlyingRisk,
    YieldDecomposition,
)


def _clamp(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    """Clamp a Decimal to [lo, hi] (fail-CLOSED-friendly: callers clamp risk into a bounded haircut)."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _safe_decimal(x) -> Optional[Decimal]:
    """Coerce to Decimal; None on anything malformed (NaN/inf/non-numeric) so callers fail-CLOSED."""
    try:
        d = Decimal(x) if not isinstance(x, Decimal) else x
    except Exception:  # noqa: BLE001
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


class FairValueEngine:
    """Deterministic fair-value decomposition engine. Hold a RatePolicyParams (the k_* / caps /
    baseline parameters); every public method takes the risk surface + an explicit `as_of`."""

    def __init__(self, params: Optional[RatePolicyParams] = None) -> None:
        self.params = params or RatePolicyParams()

    # ── baseline ─────────────────────────────────────────────────────────────────────────────────
    def baseline_yield(
        self,
        risk: UnderlyingRisk,
        kind: UnderlyingKind,
        tenor_seconds: int,
        hedge_available: bool,
        trailing_yield: Optional[Decimal] = None,
        boros_forward: Optional[Decimal] = None,
        staking_yield: Optional[Decimal] = None,
    ) -> Decimal:
        """The honest expected yield absent mispricing, by underlying KIND (the brief's baseline model):

          STABLE_RWA   → the t-bill rate (RWA-backed stable earns the bill it holds).
          STABLE_SYNTH → synthetic-dollar carry (sUSDe/USDe). If a forward hedge is available the
                         baseline is min(trailing_90d_yield, boros_forward) — you can only honestly
                         expect the LOWER of realized carry and the hedgeable forward; if NOT hedged
                         the baseline collapses to a conservative low floor (you carry naked funding).
          LST          → the staking yield (stETH/rETH earn staking).
          LRT          → STAKING ONLY. The restaking ("points"/AVS) premium is explicitly NOT in the
                         baseline — it is exactly the tail-comp the desk refuses to underwrite.

        PURE: tenor is informational here (kept for callers that taper baseline by tenor); the model
        is deterministic in its inputs. fail-CLOSED: a missing required input → conservative floor."""
        p = self.params
        sy = staking_yield if staking_yield is not None else p.staking_yield

        if kind == UnderlyingKind.STABLE_RWA:
            return p.tbill_rate

        if kind == UnderlyingKind.STABLE_SYNTH:
            if hedge_available:
                ty = _safe_decimal(trailing_yield)
                bf = _safe_decimal(boros_forward)
                cands = [c for c in (ty, bf) if c is not None]
                if not cands:
                    return p.synth_conservative_floor  # fail-CLOSED: no hedge reference → floor
                return min(cands)
            # unhedged synthetic carry: conservative — do not bake in funding you cannot lock
            return p.synth_conservative_floor

        if kind == UnderlyingKind.LST:
            return sy

        if kind == UnderlyingKind.LRT:
            # restaking premium is NOT baseline — only the staking floor is honest baseline
            return sy

        # unknown kind → fail-CLOSED conservative
        return p.synth_conservative_floor

    # ── haircuts ─────────────────────────────────────────────────────────────────────────────────
    def haircuts(
        self,
        risk: UnderlyingRisk,
        baseline: Decimal,
        kind: UnderlyingKind,
        position_size_usd: Decimal,
        exit_liquidity_usd: Decimal,
    ) -> dict:
        """The brief's FIVE structural haircuts, each `k_* * normalized_risk` clamped to [0, cap].
        Returns a dict of the five Decimals. fail-CLOSED: a malformed risk field is treated as MAX
        for that haircut (clamped to its cap), never zero.

        REUSES the validated risk_score signals: peg_distance == the depeg-drawdown signal,
        peg_vol_30d == the downside-drift signal, funding_neg_frac_90d == the funding-flip signal."""
        p = self.params

        # 1. PEG haircut — depeg distance + downside drift (the ezETH/rsETH peg-breakdown tail).
        peg = _safe_decimal(risk.peg_distance)
        peg_vol = _safe_decimal(risk.peg_vol_30d)
        if peg is None or peg_vol is None or peg < 0 or peg_vol < 0:
            peg_hc = p.cap_peg  # fail-CLOSED
        else:
            # peg distance dominates; downside-drift vol adds half its weight (grinding decay)
            peg_signal = peg + (peg_vol / Decimal("2"))
            peg_hc = _clamp(p.k_peg * peg_signal, D0, p.cap_peg)

        # 2. FUNDING-FLIP haircut — fraction of last 90d with negative funding (carry-unwind comp).
        fneg = _safe_decimal(risk.funding_neg_frac_90d)
        if fneg is None or fneg < 0:
            fund_hc = p.cap_funding  # fail-CLOSED
        else:
            # k_funding scaled by how far funding-neg-frac exceeds a benign 10% baseline, /full-band
            excess = fneg if fneg > Decimal("0.10") else D0
            fund_hc = _clamp(p.k_funding * (excess / Decimal("0.40")) * Decimal("12"), D0, p.cap_funding)

        # 3. ORACLE haircut — staleness as a fraction of tolerance.
        stale = risk.oracle_staleness_seconds
        if not isinstance(stale, int) or stale < 0 or p.max_oracle_staleness_s <= 0:
            oracle_hc = p.cap_oracle  # fail-CLOSED
        else:
            frac = Decimal(stale) / Decimal(p.max_oracle_staleness_s)
            oracle_hc = _clamp(p.k_oracle * frac, D0, p.cap_oracle)

        # 4. LIQUIDITY haircut — position size vs one-tick exit liquidity (your own exit impact).
        size = _safe_decimal(position_size_usd)
        exitl = _safe_decimal(exit_liquidity_usd)
        if size is None or exitl is None or size < 0 or exitl <= 0:
            liq_hc = p.cap_liquidity  # fail-CLOSED: unknown/zero exit liquidity → max liquidity haircut
        else:
            ratio = size / exitl  # 0 = tiny vs book, >=1 = you ARE the book
            liq_hc = _clamp(p.k_liquidity * ratio, D0, p.cap_liquidity)

        # 5. PROTOCOL haircut — composability nesting + borrower concentration (the structural tail).
        nest = risk.nested_protocol_count
        topb = _safe_decimal(risk.top_borrower_share)
        if not isinstance(nest, int) or nest < 0 or topb is None or topb < 0:
            proto_hc = p.cap_protocol  # fail-CLOSED
        else:
            # each nested protocol adds a fixed risk unit; borrower concentration adds linearly
            nest_signal = Decimal(nest) * Decimal("0.5") + topb
            proto_hc = _clamp(p.k_protocol * nest_signal, D0, p.cap_protocol)

        return {
            "peg_haircut": peg_hc,
            "funding_flip_haircut": fund_hc,
            "oracle_haircut": oracle_hc,
            "liquidity_haircut": liq_hc,
            "protocol_haircut": proto_hc,
        }

    # ── combine ──────────────────────────────────────────────────────────────────────────────────
    def fair(
        self,
        risk: UnderlyingRisk,
        kind: UnderlyingKind,
        tenor_seconds: int,
        hedge_available: bool,
        position_size_usd: Decimal,
        exit_liquidity_usd: Decimal,
        as_of: str,
        trailing_yield: Optional[Decimal] = None,
        boros_forward: Optional[Decimal] = None,
        staking_yield: Optional[Decimal] = None,
    ) -> YieldDecomposition:
        """Full decomposition for one market at `as_of`: baseline minus the five haircuts.

        PURE (f(inputs, as_of)). The returned YieldDecomposition is frozen + hashable for the proof
        chain. fail-CLOSED throughout (max haircuts on malformed inputs)."""
        baseline = self.baseline_yield(
            risk, kind, tenor_seconds, hedge_available,
            trailing_yield=trailing_yield, boros_forward=boros_forward, staking_yield=staking_yield,
        )
        hc = self.haircuts(risk, baseline, kind, position_size_usd, exit_liquidity_usd)
        return YieldDecomposition(
            underlying=risk.underlying,
            as_of=as_of,
            baseline=baseline,
            peg_haircut=hc["peg_haircut"],
            funding_flip_haircut=hc["funding_flip_haircut"],
            oracle_haircut=hc["oracle_haircut"],
            liquidity_haircut=hc["liquidity_haircut"],
            protocol_haircut=hc["protocol_haircut"],
        )
