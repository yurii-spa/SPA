"""
spa_core/strategy_lab/rates_desk/opportunity_engine.py — the rates-desk Opportunity scanner.

The desk's "what could we trade?" layer. Given a market SURFACE (every fixed/implied-rate quote it
can see this tick across PT / Boros / lending venues) and the per-underlying risk surface, the engine
enumerates the FOUR trade SHAPES per underlying and emits a ranked list of `Opportunity` candidates
with their gross/net edge and an exit-capacity-bound raw max size.

HARD SEPARATION OF CONCERNS — the engine does NO risk veto. It does not look at depeg, oracle
staleness, funding-flip streaks, or tail haircuts to DROP an underlying. That is exclusively the
gate's job (rate_policy.evaluate_entry, refusal-first). The engine's only job is to find every shape
whose ECONOMICS could plausibly clear, compute the edges, and rank them. A scanned Opportunity is a
*candidate*, never an approval. (The single structural exclusion the engine honours is shape
AVAILABILITY: BASIS_HEDGE only exists for an underlying that actually has a Boros hedge available —
you cannot construct the trade otherwise. That is feasibility, not risk veto.)

The four shapes (brief §4):
  A FIXED_CARRY    — buy PENDLE_PT, hold to maturity. edge = quoted_PT − fair_yield.
  B LEVERED_CARRY  — PENDLE_PT (receive fixed) + LENDING borrow (pay). edge = PT_implied − borrow_rate.
  C BASIS_HEDGE    — PENDLE_PT (receive fixed) + BOROS funding (pay variable). ONLY if hedge_available.
  D RATE_MATRIX    — for one target exposure, the per-venue net_rate matrix; emit ONE opp to hold the
                     argmax-net-rate venue. (earn = sUSDe-PT vs Boros funding; fund = supply vs borrow.)

Every opportunity also carries a fair-value-cleared GROSS edge (quoted − fair_yield) and a NET edge
(gross − costs: pendle/lending fees, gas, hedge cost, expected slippage from config). Opportunities
are returned ranked by net_edge DESC (the desk works the richest economics first; the gate then
refuses any that are tail-comp regardless of rank).

PURE: scan(surface, risks, as_of) → list[Opportunity]. No clock, no IO, no RNG; `as_of` is explicit.
stdlib only. LLM-FORBIDDEN. fail-CLOSED: a malformed/missing input for a shape DROPS that shape's
candidate (it is never silently emitted with a fabricated edge), it does not crash the scan.

All rates are Decimal fractions; all money is Decimal USD. The edge components are surfaced verbatim
on the Opportunity via an attached `OppEdge` (string-exact, for the proof chain) — the Opportunity
contract itself (frozen, owned by contracts.py) is not modified; the engine returns the rich edge
alongside through `scan_detailed`, while `scan` returns the plain ranked `Opportunity` list the
sleeves consume.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import (
    FairValueEngine,
    _safe_decimal,
)


# ── cost model (config-driven, Decimal) ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CostConfig:
    """All execution costs the net-edge subtracts, as annualized Decimal APY-equivalents (per the
    desk convention that edges are quoted as fractions/yr). Frozen + version-pinned: changing a value
    is a research-config change. fail-CLOSED defaults are conservative (costs never under-stated)."""
    pendle_fee: Decimal = Decimal("0.0010")        # Pendle PT round-trip fee amortized over tenor
    lending_fee: Decimal = Decimal("0.0005")       # money-market entry/exit + spread (levered legs)
    hedge_cost: Decimal = Decimal("0.0015")        # Boros forward-funding hedge carrying cost (basis legs)
    gas_cost: Decimal = Decimal("0.0002")          # amortized gas for entry+exit+rolls
    slippage_per_exit_frac: Decimal = Decimal("0.02")  # expected slippage = this * (size / exit_liq)

    def expected_slippage(self, size_usd: Decimal, exit_liq_usd: Decimal) -> Decimal:
        """Expected slippage as an APY-equivalent: scales with how much of one-tick exit liquidity the
        position consumes. fail-CLOSED: unknown/zero exit liquidity → max-ish slippage (full coeff)."""
        s = _safe_decimal(size_usd)
        x = _safe_decimal(exit_liq_usd)
        if s is None or x is None or x <= 0 or s < 0:
            return self.slippage_per_exit_frac  # fail-CLOSED: assume you ARE the book
        ratio = s / x
        if ratio > Decimal("1"):
            ratio = Decimal("1")
        return self.slippage_per_exit_frac * ratio


# ── the market surface the engine scans ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RateSurface:
    """Every fixed/implied-rate market the desk can see this tick, grouped so the engine can pair legs
    per underlying. PURE input (`as_of` explicit). Quotes are partitioned by venue; the engine pairs a
    PENDLE_PT receive leg against a LENDING borrow leg (shape B), a BOROS funding leg (shape C), and
    enumerates venues for the rate matrix (shape D).

      pt_quotes[underlying]      → the PENDLE_PT fixed-rate quote (the receive-fixed leg).
      lending_quotes[underlying] → the LENDING market (utilization/ltv/borrow proxy on quoted_rate).
      boros_quotes[underlying]   → the BOROS forward-funding quote (the pay-variable hedge leg).
      supply_quotes[underlying]  → optional supply-side LENDING leg for the rate matrix (earn via lend).

    The lending quote's `quoted_rate` is read as the BORROW rate; the supply quote's as the SUPPLY
    rate. Missing legs simply make a shape unavailable for that underlying (fail-CLOSED)."""
    as_of: str
    pt_quotes: Dict[str, RateQuote] = field(default_factory=dict)
    lending_quotes: Dict[str, RateQuote] = field(default_factory=dict)
    boros_quotes: Dict[str, RateQuote] = field(default_factory=dict)
    supply_quotes: Dict[str, RateQuote] = field(default_factory=dict)

    def underlyings(self) -> List[str]:
        """Deterministic, sorted union of every underlying that appears on any leg (stable scan order
        → stable Opportunity ordering for the proof chain)."""
        keys = set(self.pt_quotes) | set(self.lending_quotes) | set(self.boros_quotes) | set(self.supply_quotes)
        return sorted(keys)


# ── the rich edge breakdown attached to each scanned opportunity ─────────────────────────────────
@dataclass(frozen=True)
class OppEdge:
    """The economics breakdown for one scanned candidate. gross_edge = quoted/implied − fair_yield;
    net_edge = gross_edge − Σ costs. raw_max_size_usd is the exit-capacity-bound raw size BEFORE the
    gate's own size cap (the gate caps leverage/maturity/concentration later). String-exact via
    proof() for the audit chain. All Decimal."""
    underlying: str
    shape: TradeShape
    as_of: str
    fair_yield: Decimal
    reference_rate: Decimal          # quoted PT (A/C) or PT_implied (B) or argmax net_rate (D)
    gross_edge: Decimal              # reference − fair_yield  (A/C);  implied − borrow (B);  net_rate (D)
    cost_total: Decimal              # Σ amortized costs subtracted to get net
    net_edge: Decimal                # gross_edge − cost_total
    raw_max_size_usd: Decimal        # exit-capacity-bound raw size (pre-gate)
    venue: str = ""                  # for RATE_MATRIX: the chosen argmax venue label
    detail: Dict[str, str] = field(default_factory=dict)

    def proof(self) -> Dict[str, str]:
        out = {
            "underlying": self.underlying,
            "shape": self.shape.value,
            "as_of": self.as_of,
            "fair_yield": str(self.fair_yield),
            "reference_rate": str(self.reference_rate),
            "gross_edge": str(self.gross_edge),
            "cost_total": str(self.cost_total),
            "net_edge": str(self.net_edge),
            "raw_max_size_usd": str(self.raw_max_size_usd),
            "venue": self.venue,
        }
        out.update({f"d_{k}": v for k, v in sorted(self.detail.items())})
        return out


@dataclass(frozen=True)
class ScannedOpportunity:
    """An Opportunity paired with its rich edge (and, for paired shapes, the second leg quote). The
    sleeves consume `opportunity` for the gate; the audit chain consumes `edge`. Frozen/pure."""
    opportunity: Opportunity
    edge: OppEdge
    second_leg: Optional[RateQuote] = None   # B: lending borrow leg; C: boros funding leg; D: chosen venue quote


class OpportunityEngine:
    """Enumerate the four trade shapes over a RateSurface and rank by net_edge. NO risk veto — that is
    the gate's job. Holds a FairValueEngine (the fair-yield reference) + a CostConfig (the net-edge
    cost model) + RatePolicyParams (for sizing fractions only — NOT for vetoing)."""

    def __init__(
        self,
        params: Optional[RatePolicyParams] = None,
        engine: Optional[FairValueEngine] = None,
        costs: Optional[CostConfig] = None,
    ) -> None:
        self.params = params or RatePolicyParams()
        self.engine = engine or FairValueEngine(self.params)
        self.costs = costs or CostConfig()

    # ── public API ───────────────────────────────────────────────────────────────────────────────
    def scan(
        self,
        surface: RateSurface,
        risks: Dict[str, UnderlyingRisk],
        as_of: str,
        requested_size_usd: Optional[Decimal] = None,
    ) -> List[Opportunity]:
        """Return the ranked (net_edge DESC) list of plain `Opportunity` candidates across all four
        shapes. PURE. `requested_size_usd` (if given) is the desk's intended notional; otherwise each
        opp requests its own raw_max_size_usd. fail-CLOSED: a shape with malformed/missing legs is
        simply not emitted."""
        return [s.opportunity for s in self.scan_detailed(surface, risks, as_of, requested_size_usd)]

    def scan_detailed(
        self,
        surface: RateSurface,
        risks: Dict[str, UnderlyingRisk],
        as_of: str,
        requested_size_usd: Optional[Decimal] = None,
    ) -> List[ScannedOpportunity]:
        """Like scan() but returns the rich ScannedOpportunity (opp + edge + second leg) for the audit
        chain and the sleeves' leg bookkeeping. Ranked by net_edge DESC, then by a deterministic tie
        breaker (underlying, shape) so the order is replay-stable."""
        out: List[ScannedOpportunity] = []
        for u in surface.underlyings():
            risk = risks.get(u)
            if risk is None:
                continue  # fail-CLOSED: no risk surface → the fair-value reference is undefined, skip
            for builder in (self._shape_a, self._shape_b, self._shape_c, self._shape_d):
                so = builder(surface, risk, u, as_of, requested_size_usd)
                if so is not None:
                    out.append(so)
        # rank: net_edge DESC, deterministic tie-break (no clock / RNG)
        out.sort(key=lambda s: (-s.edge.net_edge, s.opportunity.quote.underlying, s.edge.shape.value))
        return out

    # ── fair-yield reference (shared by every shape) ───────────────────────────────────────────────
    def _fair_yield(self, pt: RateQuote, risk: UnderlyingRisk, size: Decimal, as_of: str,
                    shape: Optional[TradeShape] = None) -> Decimal:
        """The fair-value yield for this underlying from the decomposition engine (baseline − 5
        haircuts). The engine itself does not VETO on it — it only uses it as the spread reference.

        `shape` drives the SHAPE-CORRECT funding haircut so a FIXED_CARRY (no perp leg) fair-yield
        reference matches the gate's (no funding term), while the levered/basis/matrix shapes keep it.
        Each shape builder passes its own TradeShape; None keeps funding (fail-CLOSED)."""
        dec = self.engine.fair(
            risk=risk, kind=pt.kind, tenor_seconds=pt.tenor_seconds,
            hedge_available=pt.hedge_available, position_size_usd=size,
            exit_liquidity_usd=pt.exit_liquidity_usd, as_of=as_of, shape=shape,
        )
        return dec.fair_yield

    def _raw_max_size(self, exit_liq_usd: Decimal) -> Decimal:
        """Exit-capacity-bound raw max size = max_size_frac_of_exit * one-tick exit liquidity. This is
        the engine's pre-gate ceiling; the gate re-applies the same cap (and leverage/maturity caps)."""
        x = _safe_decimal(exit_liq_usd)
        if x is None or x <= 0:
            return D0
        return self.params.max_size_frac_of_exit * x

    def _size_for(self, raw_max: Decimal, requested: Optional[Decimal]) -> Decimal:
        if requested is None:
            return raw_max
        r = _safe_decimal(requested)
        if r is None or r <= 0:
            return raw_max
        return min(r, raw_max) if raw_max > 0 else r

    # ── A: FIXED_CARRY (PENDLE_PT vs fair) ─────────────────────────────────────────────────────────
    def _shape_a(self, surface, risk, u, as_of, requested) -> Optional[ScannedOpportunity]:
        pt = surface.pt_quotes.get(u)
        if pt is None:
            return None
        quoted = _safe_decimal(pt.quoted_rate)
        if quoted is None:
            return None  # fail-CLOSED: no fabricated edge
        raw_max = self._raw_max_size(pt.exit_liquidity_usd)
        fair = self._fair_yield(pt, risk, raw_max if raw_max > 0 else Decimal("1"), as_of,
                                shape=TradeShape.FIXED_CARRY)
        gross = quoted - fair
        if gross <= D0:
            return None  # economics: no carry above fair → not a candidate (NOT a risk veto)
        slip = self.costs.expected_slippage(raw_max, pt.exit_liquidity_usd)
        cost = self.costs.pendle_fee + self.costs.gas_cost + slip
        net = gross - cost
        edge = OppEdge(
            underlying=u, shape=TradeShape.FIXED_CARRY, as_of=as_of, fair_yield=fair,
            reference_rate=quoted, gross_edge=gross, cost_total=cost, net_edge=net,
            raw_max_size_usd=raw_max,
            detail={"quoted_pt": str(quoted), "slippage": str(slip)},
        )
        size = self._size_for(raw_max, requested)
        opp = Opportunity(quote=pt, shape=TradeShape.FIXED_CARRY, requested_size_usd=size)
        return ScannedOpportunity(opportunity=opp, edge=edge, second_leg=None)

    # ── B: LEVERED_CARRY (PENDLE_PT receive vs LENDING borrow) ─────────────────────────────────────
    def _shape_b(self, surface, risk, u, as_of, requested) -> Optional[ScannedOpportunity]:
        pt = surface.pt_quotes.get(u)
        borrow = surface.lending_quotes.get(u)
        if pt is None or borrow is None:
            return None  # need both legs to lever
        implied = _safe_decimal(pt.quoted_rate)
        borrow_rate = _safe_decimal(borrow.quoted_rate)
        if implied is None or borrow_rate is None:
            return None
        # edge of the levered shape = PT implied receive − borrow pay (the carry the leverage amplifies)
        gross = implied - borrow_rate
        if gross <= D0:
            return None  # borrow >= implied → negative carry, not a candidate
        # raw_max_size from exit capacity of the BINDING (tighter) leg — you can only unwind as fast as
        # the thinner book lets you. The gate caps the actual LEVERAGE/maturity later.
        binding_exit = min(self._raw_max_size(pt.exit_liquidity_usd),
                           self._raw_max_size(borrow.exit_liquidity_usd))
        fair = self._fair_yield(pt, risk, binding_exit if binding_exit > 0 else Decimal("1"), as_of,
                                shape=TradeShape.LEVERED_CARRY)
        slip = (self.costs.expected_slippage(binding_exit, pt.exit_liquidity_usd)
                + self.costs.expected_slippage(binding_exit, borrow.exit_liquidity_usd))
        cost = self.costs.pendle_fee + self.costs.lending_fee + self.costs.gas_cost + slip
        net = gross - cost
        edge = OppEdge(
            underlying=u, shape=TradeShape.LEVERED_CARRY, as_of=as_of, fair_yield=fair,
            reference_rate=implied, gross_edge=gross, cost_total=cost, net_edge=net,
            raw_max_size_usd=binding_exit,
            detail={"pt_implied": str(implied), "borrow_rate": str(borrow_rate),
                    "ltv": str(borrow.ltv), "utilization": str(borrow.utilization),
                    "slippage": str(slip)},
        )
        size = self._size_for(binding_exit, requested)
        opp = Opportunity(quote=pt, shape=TradeShape.LEVERED_CARRY, requested_size_usd=size)
        return ScannedOpportunity(opportunity=opp, edge=edge, second_leg=borrow)

    # ── C: BASIS_HEDGE (PENDLE_PT receive fixed vs BOROS pay variable) ─ ONLY if hedge_available ────
    def _shape_c(self, surface, risk, u, as_of, requested) -> Optional[ScannedOpportunity]:
        pt = surface.pt_quotes.get(u)
        if pt is None:
            return None
        boros = surface.boros_quotes.get(u)
        # FEASIBILITY (not a risk veto): the shape only EXISTS if a Boros hedge is available.
        if not pt.hedge_available or boros is None:
            return None
        fixed = _safe_decimal(pt.quoted_rate)
        variable = _safe_decimal(boros.quoted_rate)
        if fixed is None or variable is None:
            return None
        # basis = receive fixed PT − pay variable Boros funding (the isolated basis the desk harvests)
        gross = fixed - variable
        if gross <= D0:
            return None  # the basis is against us → not a candidate
        binding_exit = min(self._raw_max_size(pt.exit_liquidity_usd),
                           self._raw_max_size(boros.exit_liquidity_usd))
        fair = self._fair_yield(pt, risk, binding_exit if binding_exit > 0 else Decimal("1"), as_of,
                                shape=TradeShape.BASIS_HEDGE)
        slip = (self.costs.expected_slippage(binding_exit, pt.exit_liquidity_usd)
                + self.costs.expected_slippage(binding_exit, boros.exit_liquidity_usd))
        cost = self.costs.pendle_fee + self.costs.hedge_cost + self.costs.gas_cost + slip
        net = gross - cost
        edge = OppEdge(
            underlying=u, shape=TradeShape.BASIS_HEDGE, as_of=as_of, fair_yield=fair,
            reference_rate=fixed, gross_edge=gross, cost_total=cost, net_edge=net,
            raw_max_size_usd=binding_exit,
            detail={"pt_fixed": str(fixed), "boros_variable": str(variable),
                    "hedge_available": "True", "slippage": str(slip)},
        )
        size = self._size_for(binding_exit, requested)
        opp = Opportunity(quote=pt, shape=TradeShape.BASIS_HEDGE, requested_size_usd=size)
        return ScannedOpportunity(opportunity=opp, edge=edge, second_leg=boros)

    # ── D: RATE_MATRIX (cross-venue net_rate; emit argmax venue) ───────────────────────────────────
    def _shape_d(self, surface, risk, u, as_of, requested) -> Optional[ScannedOpportunity]:
        """For one target exposure on `u`, compute net_rate per venue and emit an opp to HOLD the
        argmax-net-rate venue.

          earn funding via sUSDe-PT  → net_rate = PT quoted − pendle/gas/slippage
          earn funding via Boros     → net_rate = Boros quoted − hedge/gas/slippage (needs hedge avail)
          fund via supply (lend)     → net_rate = supply quoted − lending/gas/slippage
          fund via borrow            → net_rate = −(borrow quoted) − lending/gas/slippage  (a cost leg)

        We rank the EARN venues (PT, Boros, supply) by net_rate and pick the argmax; the borrow venue
        is carried only as the comparison/funding reference. fail-CLOSED: a venue with a malformed rate
        is dropped from the matrix, not defaulted."""
        venues: List[Tuple[str, Decimal, RateQuote]] = []  # (venue_label, net_rate, quote)

        pt = surface.pt_quotes.get(u)
        if pt is not None:
            r = _safe_decimal(pt.quoted_rate)
            if r is not None:
                size_ref = self._raw_max_size(pt.exit_liquidity_usd)
                slip = self.costs.expected_slippage(size_ref, pt.exit_liquidity_usd)
                nr = r - (self.costs.pendle_fee + self.costs.gas_cost + slip)
                venues.append((RateVenue.PENDLE_PT.value, nr, pt))

        boros = surface.boros_quotes.get(u)
        if boros is not None and (pt is not None and pt.hedge_available or boros.hedge_available):
            r = _safe_decimal(boros.quoted_rate)
            if r is not None:
                size_ref = self._raw_max_size(boros.exit_liquidity_usd)
                slip = self.costs.expected_slippage(size_ref, boros.exit_liquidity_usd)
                nr = r - (self.costs.hedge_cost + self.costs.gas_cost + slip)
                venues.append((RateVenue.BOROS.value, nr, boros))

        supply = surface.supply_quotes.get(u)
        if supply is not None:
            r = _safe_decimal(supply.quoted_rate)
            if r is not None:
                size_ref = self._raw_max_size(supply.exit_liquidity_usd)
                slip = self.costs.expected_slippage(size_ref, supply.exit_liquidity_usd)
                nr = r - (self.costs.lending_fee + self.costs.gas_cost + slip)
                venues.append((RateVenue.LENDING.value, nr, supply))

        if not venues:
            return None  # no earn venue → no matrix opp

        # argmax net_rate; deterministic tie-break on venue label (no clock / RNG)
        venues.sort(key=lambda v: (-v[1], v[0]))
        best_label, best_nr, best_quote = venues[0]

        # the funding/borrow reference rate for the matrix detail (not an earn venue)
        borrow = surface.lending_quotes.get(u)
        borrow_rate = _safe_decimal(borrow.quoted_rate) if borrow is not None else None

        if best_nr <= D0:
            return None  # even the best venue nets <=0 → not a candidate
        raw_max = self._raw_max_size(best_quote.exit_liquidity_usd)
        fair = self._fair_yield(best_quote, risk, raw_max if raw_max > 0 else Decimal("1"), as_of,
                                shape=TradeShape.RATE_MATRIX)
        edge = OppEdge(
            underlying=u, shape=TradeShape.RATE_MATRIX, as_of=as_of, fair_yield=fair,
            reference_rate=best_nr, gross_edge=best_nr, cost_total=D0, net_edge=best_nr,
            raw_max_size_usd=raw_max, venue=best_label,
            detail={
                "argmax_venue": best_label,
                "argmax_net_rate": str(best_nr),
                "matrix": ";".join(f"{lbl}={nr}" for lbl, nr, _ in venues),
                "borrow_ref": "n/a" if borrow_rate is None else str(borrow_rate),
            },
        )
        size = self._size_for(raw_max, requested)
        opp = Opportunity(quote=best_quote, shape=TradeShape.RATE_MATRIX, requested_size_usd=size)
        return ScannedOpportunity(opportunity=opp, edge=edge, second_leg=borrow)
