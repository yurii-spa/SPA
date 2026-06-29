"""
spa_core/strategy_lab/rates_desk/sleeves.py — the rates-desk sleeves (Phase 0: FixedCarry).

A thin Strategy-ABC wrapper over the pure engine + refusal-first gate. The sleeve owns NO pricing or
policy logic of its own — it scans quotes, asks rate_policy.evaluate_entry whether to enter, holds to
maturity, and asks rate_policy.evaluate_hold each tick whether to unwind. ALL the edge is in the gate.

Phase 0 ships ONE shape:
  • FIXED_CARRY — buy a PT (Pendle Principal Token), lock a fixed rate, hold to maturity. Enter only
    when the gate approves (refusal-first), size to the gate's exit-capacity-bound size, unwind the
    instant evaluate_hold refuses (depeg / compression / maturity / funding-flip / util / concentration).

NEXT (declared, not built): LeveredCarrySleeve (borrow stable → buy PT), BasisHedgeSleeve (PT vs
forward-funding short), RateMatrixSleeve (cross-venue rate arb).

Conventions: stdlib only, deterministic, LLM-FORBIDDEN, fail-CLOSED (advisory until go-live). The
sleeve is `is_advisory=True` — it simulates a book; it does not move live capital.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import (
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)
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
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.opportunity_engine import (
    CostConfig,
    OpportunityEngine,
    RateSurface,
    ScannedOpportunity,
)
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry, evaluate_hold
from spa_core.strategy_lab.rates_desk import rate_floor_recal
from spa_core.strategy_lab.rates_desk.capacity_sizing import graded_size


class FixedCarrySleeve(Strategy):
    """Buy-PT-hold-to-maturity carry book, gated by the refusal-first RatePolicy.

    The harness drives it via the Strategy ABC. Quotes + risk surfaces are supplied either through
    MarketSnapshot.meta-style channels (live/backtest harness) or directly via scan_and_enter (the
    validation replay / tests use the direct path so the engine is exercised hermetically)."""

    id = "rates_desk_fixed_carry"
    name = "Rates Desk — Fixed Carry (PT to maturity)"
    is_advisory = True
    mandate = "stable"

    def __init__(self, params: Optional[RatePolicyParams] = None) -> None:
        self.params = params or RatePolicyParams()
        self.engine = FairValueEngine(self.params)
        self._capital = D0
        self._cash = D0
        # open books: market_id -> {"opp": Opportunity, "size": Decimal, "state": KillState,
        #                            "entry_rate": Decimal, "carry": Decimal}
        self._books: Dict[str, dict] = {}
        self._closed: List[dict] = []          # audit log of unwound books
        self._accrued = D0                      # realized + accrued carry (Decimal USD)
        self._last_verdicts: List[GateResult] = []  # most recent entry/hold verdicts (proof chain)

    # ── Strategy ABC ───────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = Decimal(str(capital))
        self._cash = self._capital
        # config may override policy params (string-Decimal pairs); never hardcode in logic.
        overrides = (config or {}).get("rate_policy_params")
        if isinstance(overrides, dict) and overrides:
            base = self.params
            kwargs = {f.name: getattr(base, f.name) for f in base.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            for k, v in overrides.items():
                if k in kwargs:
                    cur = kwargs[k]
                    kwargs[k] = Decimal(str(v)) if isinstance(cur, Decimal) else type(cur)(v)
            self.params = RatePolicyParams(**kwargs)
            self.engine = FairValueEngine(self.params)

    def positions(self) -> List[Position]:
        out: List[Position] = []
        for mid, bk in self._books.items():
            out.append(Position(
                asset=bk["opp"].quote.underlying, kind="lending",
                notional_usd=float(bk["size"]),
                meta={"market_id": mid, "shape": TradeShape.FIXED_CARRY.value,
                      "entry_rate": str(bk["entry_rate"]), "carry": str(bk["carry"])},
            ))
        # cash leg keeps equity() honest
        out.append(Position(asset="usdc", kind="cash", notional_usd=float(self._cash)))
        return out

    def step(self, market: MarketSnapshot) -> None:
        """One tick: accrue carry on open books (no rebalance here — entry/exit is gate-driven via
        scan_and_enter / tick_hold which the harness or validation calls with quotes+risk)."""
        # daily carry accrual on each open book at its locked rate (Decimal-exact)
        for bk in self._books.values():
            rate = bk["entry_rate"]
            bk_accrual = bk["size"] * rate / Decimal("365")
            self._accrued += bk_accrual

    def metrics(self) -> StrategyMetrics:
        eq = self.equity_decimal()
        net = (eq - self._capital)
        apy_pct = float(net / self._capital * Decimal("100")) if self._capital > 0 else 0.0
        return StrategyMetrics(
            net_apy_pct=round(apy_pct, 4),
            beats_rwa_floor=None,
            extra={
                "open_books": len(self._books),
                "closed_books": len(self._closed),
                "accrued_usd": str(self._accrued),
                "equity_usd": str(eq),
            },
        )

    def kill_check(self, market: MarketSnapshot) -> KillResult:
        """Sleeve-level kill: fail-CLOSED. The per-book continuous kill lives in tick_hold (which the
        harness/validation calls with the live risk surface). This ABC hook reports a sleeve-wide kill
        if any book has been marked killed."""
        for mid, bk in self._books.items():
            st: KillState = bk["state"]
            if st.killed:
                return KillResult(triggered=True, reason=f"{mid}:{st.kill_reason.value}",
                                  ts=market.date)
        return KillResult(triggered=False, ts=market.date)

    # ── engine-driven entry / hold (the validation replay + tests use these directly) ────────────
    def scan_and_enter(
        self,
        quotes: List[RateQuote],
        risks: Dict[str, UnderlyingRisk],
        as_of: str,
        debt_asset_price: Decimal = Decimal("1"),
        global_approved: bool = True,
        trailing_yields: Optional[Dict[str, Decimal]] = None,
        boros_forwards: Optional[Dict[str, Decimal]] = None,
    ) -> List[GateResult]:
        """Scan PT quotes; for each, ask the refusal-first gate whether to enter. Opens a book only on
        an APPROVED gate AND a True global RiskPolicy approval (composition: AND). Returns every
        verdict (approved + refused) for the proof chain.

        PURE w.r.t. the gate — the sleeve adds only bookkeeping. `risks[underlying]` supplies the risk
        surface; a missing risk surface fail-CLOSES that quote (skipped, no book)."""
        trailing_yields = trailing_yields or {}
        boros_forwards = boros_forwards or {}
        verdicts: List[GateResult] = []
        # WS-3.1: when SPA_RATE_FLOOR_RECAL is ON, recalibrate ONLY min_tradeable_size_usd from the
        # realized exit depth on this scan's quotes (a depth-anchored floor lets a genuinely-fundable
        # thin-pool carry book — e.g. the live USDe 661bps book — pass the SIZE gate instead of an
        # arbitrary $1k floor refusing it). The recalibration is GUARDRAILED in rate_floor_recal: it can
        # ONLY move the size floor; every toxicity veto stays byte-identical, so it cannot re-admit a
        # toxic book (which is TAIL_VETO'd at step 1, before sizing). Flag OFF → params unchanged.
        eff_params, eff_engine = self.params, self.engine
        if rate_floor_recal.flag_enabled():
            scan_surface = {"quotes": [{"underlying": q.underlying, "market_id": q.market_id,
                                        "exit_liquidity_usd": q.exit_liquidity_usd} for q in quotes]}
            eff_params = rate_floor_recal.recalibrated_params(self.params, scan_surface)
            eff_engine = FairValueEngine(eff_params)
        for q in quotes:
            risk = risks.get(q.underlying)
            if risk is None:
                continue  # fail-CLOSED: no risk surface → no entry
            if q.market_id in self._books:
                continue  # already holding this market
            # REQUEST a size BOUNDED BY EXIT CAPACITY, not the full cash book. The gate prices the
            # liquidity haircut on requested_size_usd vs one-tick exit liquidity; throwing the whole
            # $100k cash at a $30k-exit pool maxes that haircut and produces a FALSE tail-veto on an
            # otherwise-healthy carry book. Requesting what the gate would actually approve
            # (max_size_frac_of_exit * exit_liquidity, still capped at available cash) makes the
            # tail-veto reflect REAL structural risk, not an unrealistic over-size. The gate re-applies
            # the exact same exit cap on the SIZE leg, so this never lets us take more than it allows.
            exit_cap = eff_params.max_size_frac_of_exit * q.exit_liquidity_usd
            requested = min(self._cash, exit_cap) if exit_cap > D0 else self._cash
            if requested <= D0:
                requested = self._cash
            opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY,
                              requested_size_usd=requested)
            result, new_state = evaluate_entry(
                opp=opp, risk=risk, debt_asset_price=debt_asset_price,
                exit_liquidity=q.exit_liquidity_usd, params=eff_params, state=KillState(),
                engine=eff_engine,
                trailing_yield=trailing_yields.get(q.underlying),
                boros_forward=boros_forwards.get(q.underlying),
            )
            verdicts.append(result)
            # composition under the global policy: approve ONLY if both say yes.
            if result.approved and global_approved and result.approved_size_usd <= self._cash:
                # WS-3.2: CAPACITY-AWARE GRADED sizing. The gate APPROVED a structurally-clean book at
                # its capacity-bounded size; graded_size now shapes HOW MUCH of that we take = f(realized
                # depth, net_edge), capped at the §9 one-tick capacity AND cash. This turns binary all-in
                # into graded participation (a fat edge ramps toward the cap; a thin edge takes a small
                # slice) WITHOUT ever exceeding realized depth. Bounded by the gate's approved size so we
                # can never take MORE than the gate allowed (sizing only ever shrinks an approved ticket).
                gs = graded_size(realized_depth_usd=q.exit_liquidity_usd, net_edge=result.net_edge,
                                 cash_available_usd=self._cash, params=eff_params)
                book_size = min(result.approved_size_usd, gs.size_usd) if gs.size_usd > D0 \
                    else result.approved_size_usd
                self._books[q.market_id] = {
                    "opp": opp, "size": book_size, "state": new_state,
                    "entry_rate": q.quoted_rate, "carry": result.net_edge,
                    "graded": gs.proof(),
                }
                self._cash -= book_size
        self._last_verdicts = verdicts
        return verdicts

    def tick_hold(
        self,
        risks: Dict[str, UnderlyingRisk],
        current_carries: Dict[str, Decimal],
        as_of: str,
        debt_asset_price: Decimal = Decimal("1"),
        tenors: Optional[Dict[str, int]] = None,
        exit_liquidities: Optional[Dict[str, Decimal]] = None,
        utilizations: Optional[Dict[str, Decimal]] = None,
        peg_distances: Optional[Dict[str, Decimal]] = None,
    ) -> List[GateResult]:
        """Per-book continuous kill. For each open book, rebuild the current quote view (refreshed
        tenor/util/exit) and ask evaluate_hold; unwind any book the gate refuses, returning realized
        size to cash. Returns the hold/unwind verdicts. fail-CLOSED: a missing risk surface unwinds."""
        tenors = tenors or {}
        exit_liquidities = exit_liquidities or {}
        utilizations = utilizations or {}
        peg_distances = peg_distances or {}
        verdicts: List[GateResult] = []
        for mid in list(self._books.keys()):
            bk = self._books[mid]
            q0: RateQuote = bk["opp"].quote
            underlying = q0.underlying
            risk = risks.get(underlying)
            cur_carry = current_carries.get(mid, bk["carry"])
            # refresh the dynamic fields onto a new quote (frozen → rebuild)
            q = RateQuote(
                underlying=underlying, kind=q0.kind, venue=q0.venue, protocol=q0.protocol,
                market_id=mid, tenor_seconds=tenors.get(mid, q0.tenor_seconds), as_of=as_of,
                quoted_rate=bk["entry_rate"], tvl_usd=q0.tvl_usd,
                exit_liquidity_usd=exit_liquidities.get(mid, q0.exit_liquidity_usd),
                hedge_available=q0.hedge_available,
                utilization=utilizations.get(mid, q0.utilization), ltv=q0.ltv,
                cap_headroom_usd=q0.cap_headroom_usd,
            )
            opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=bk["size"])
            if risk is None:
                # fail-CLOSED unwind
                self._unwind(mid, KillReason.UNDERLYING_DEPEG, "no risk surface")
                continue
            # allow per-tick peg override (validation injects the stress-event peg break)
            if underlying in peg_distances:
                risk = self._with_peg(risk, peg_distances[underlying], as_of)
            result, new_state = evaluate_hold(
                opp=opp, risk=risk, debt_asset_price=debt_asset_price,
                exit_liquidity=q.exit_liquidity_usd, current_carry=cur_carry,
                params=self.params, state=bk["state"], engine=self.engine,
            )
            verdicts.append(result)
            bk["state"] = new_state
            bk["carry"] = cur_carry
            if not result.approved:
                self._unwind(mid, result.reason, "; ".join(f"{k}={v}" for k, v in result.detail.items()))
        self._last_verdicts = verdicts
        return verdicts

    # ── helpers ──────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _with_peg(risk: UnderlyingRisk, peg_distance: Decimal, as_of: str) -> UnderlyingRisk:
        """Return a copy of a (frozen) risk surface with an updated peg_distance (validation stress)."""
        return UnderlyingRisk(
            underlying=risk.underlying, as_of=as_of,
            nav_redemption_value=risk.nav_redemption_value, market_price=risk.market_price,
            peg_distance=peg_distance, peg_vol_30d=risk.peg_vol_30d,
            redemption_sla_seconds=risk.redemption_sla_seconds,
            reserve_fund_ratio=risk.reserve_fund_ratio,
            funding_neg_frac_90d=risk.funding_neg_frac_90d, oracle_kind=risk.oracle_kind,
            oracle_staleness_seconds=risk.oracle_staleness_seconds,
            nested_protocol_count=risk.nested_protocol_count,
            top_borrower_share=risk.top_borrower_share,
        )

    def _unwind(self, market_id: str, reason: KillReason, note: str) -> None:
        bk = self._books.pop(market_id, None)
        if bk is None:
            return
        self._cash += bk["size"]  # return notional to cash (carry already accrued in step())
        self._closed.append({
            "market_id": market_id, "reason": reason.value, "note": note,
            "size": str(bk["size"]), "entry_rate": str(bk["entry_rate"]),
        })

    def equity_decimal(self) -> Decimal:
        return self._cash + sum((bk["size"] for bk in self._books.values()), D0) + self._accrued

    def equity(self) -> float:
        return round(float(self.equity_decimal()), 2)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Phase-1 sleeves — the three remaining trade shapes (B / C / D). Each mirrors FixedCarrySleeve: a thin
# Strategy-ABC wrapper that owns NO pricing/policy logic. They scan via the OpportunityEngine (which
# does no risk veto) and gate every entry/hold via the refusal-first rate_policy. ALL the edge is in
# the engine + gate. stdlib only, deterministic, LLM-FORBIDDEN, fail-CLOSED, is_advisory=True.
#
# Common `step(surface, risks, positions, state, as_of) -> (orders, new_state)` PURE interface:
#   • inputs: a RateSurface (the markets), the per-underlying risks, the sleeve's open books
#     (`positions` dict market_id->book), a carry-forward `state` dict, and the explicit as_of.
#   • output: a list of ORDER dicts (the executor applies them — the sleeve never moves capital) +
#     the NEW state. No mutation of the inputs; same (inputs, as_of) → same (orders, new_state).
# Order shape: {"action": "open"|"unwind"|"hold"|"rotate", "market_id","underlying","shape","size",
#               "rate","reason", ...}. Decimal-exact (rates/sizes are str(Decimal) in the order).
# ══════════════════════════════════════════════════════════════════════════════════════════════════


def _order(action: str, so_or_book, **extra) -> dict:
    """Build a deterministic, string-exact order dict (the executor consumes these). Pure."""
    o = {"action": action}
    o.update({k: (str(v) if isinstance(v, Decimal) else v) for k, v in extra.items()})
    return o


class _RatesPureSleeveBase(Strategy):
    """Shared plumbing for the pure-functional Phase-1 sleeves. The ABC hooks (init/positions/step/
    metrics/kill_check) keep the harness happy; the PURE engine-driven core is `step_pure`.

    `step_pure(surface, risks, positions, state, as_of) -> (orders, new_positions, new_state)` is the
    deterministic heart each sleeve implements. `positions` is a dict market_id -> book; `state` is a
    free-form dict the sleeve threads (per-market KillState lives in book["state"])."""

    is_advisory = True
    mandate = "stable"

    def __init__(self, params: Optional[RatePolicyParams] = None,
                 costs: Optional[CostConfig] = None) -> None:
        self.params = params or RatePolicyParams()
        self.costs = costs or CostConfig()
        self.engine = FairValueEngine(self.params)
        self.opp_engine = OpportunityEngine(self.params, self.engine, self.costs)
        self._capital = D0
        self._cash = D0
        self._books: Dict[str, dict] = {}
        self._state: Dict[str, object] = {}
        self._closed: List[dict] = []
        self._accrued = D0
        self._last_orders: List[dict] = []

    # ── Strategy ABC (harness) ─────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = Decimal(str(capital))
        self._cash = self._capital
        overrides = (config or {}).get("rate_policy_params")
        if isinstance(overrides, dict) and overrides:
            base = self.params
            kwargs = {f.name: getattr(base, f.name) for f in base.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            for k, v in overrides.items():
                if k in kwargs:
                    cur = kwargs[k]
                    kwargs[k] = Decimal(str(v)) if isinstance(cur, Decimal) else type(cur)(v)
            self.params = RatePolicyParams(**kwargs)
            self.engine = FairValueEngine(self.params)
            self.opp_engine = OpportunityEngine(self.params, self.engine, self.costs)

    def positions(self) -> List[Position]:
        out: List[Position] = []
        for mid, bk in self._books.items():
            out.append(Position(
                asset=bk["opp"].quote.underlying, kind="lending",
                notional_usd=float(bk["size"]),
                meta={"market_id": mid, "shape": bk["opp"].shape.value,
                      "entry_rate": str(bk["entry_rate"]), "carry": str(bk["carry"])},
            ))
        out.append(Position(asset="usdc", kind="cash", notional_usd=float(self._cash)))
        return out

    def step(self, market: MarketSnapshot) -> None:
        """Harness tick: accrue carry on open books (entry/exit is engine-driven via step_pure)."""
        for bk in self._books.values():
            self._accrued += bk["size"] * bk["entry_rate"] / Decimal("365")

    def metrics(self) -> StrategyMetrics:
        eq = self.equity_decimal()
        net = eq - self._capital
        apy_pct = float(net / self._capital * Decimal("100")) if self._capital > 0 else 0.0
        return StrategyMetrics(
            net_apy_pct=round(apy_pct, 4), beats_rwa_floor=None,
            extra={"open_books": len(self._books), "closed_books": len(self._closed),
                   "accrued_usd": str(self._accrued), "equity_usd": str(eq)},
        )

    def kill_check(self, market: MarketSnapshot) -> KillResult:
        for mid, bk in self._books.items():
            st: KillState = bk["state"]
            if st.killed:
                return KillResult(triggered=True, reason=f"{mid}:{st.kill_reason.value}", ts=market.date)
        return KillResult(triggered=False, ts=market.date)

    def equity_decimal(self) -> Decimal:
        return self._cash + sum((bk["size"] for bk in self._books.values()), D0) + self._accrued

    def equity(self) -> float:
        return round(float(self.equity_decimal()), 2)

    # ── stateful driver over the pure core (tests/validation call this OR step_pure directly) ───────
    def step_apply(
        self,
        surface: RateSurface,
        risks: Dict[str, UnderlyingRisk],
        as_of: str,
        debt_asset_price: Decimal = Decimal("1"),
        global_approved: bool = True,
        current_carries: Optional[Dict[str, Decimal]] = None,
    ) -> List[dict]:
        """Run the pure core against the sleeve's own books and APPLY the resulting orders (cash/book
        bookkeeping). Returns the orders. The pure core itself is side-effect-free; this is the thin
        stateful wrapper the harness/tests use to advance a book."""
        orders, new_books, new_state = self.step_pure(
            surface, risks, self._books, self._state, as_of,
            cash=self._cash, debt_asset_price=debt_asset_price, global_approved=global_approved,
            current_carries=current_carries or {},
        )
        # apply cash deltas from the orders deterministically
        for o in orders:
            if o["action"] == "open":
                self._cash -= Decimal(o["size"])
            elif o["action"] == "unwind":
                self._cash += Decimal(o["size"])
            elif o["action"] == "rotate":
                # rotate = unwind held + open candidate at equal size (size preserved); cash net 0
                pass
        self._books = new_books
        self._state = new_state
        self._last_orders = orders
        return orders


class BasisHedgeSleeve(_RatesPureSleeveBase):
    """Shape C — PT long (receive fixed) hedged on Boros (pay variable): isolate and harvest the BASIS.

    Scans ONLY BASIS_HEDGE opportunities (which the OpportunityEngine emits only where hedge_available
    is true and a Boros leg exists). Gates entry via the refusal-first rate_policy; the funding leg is
    hedged on Boros so the position is funding-neutral by construction. Holds + unwinds via
    evaluate_hold each tick (depeg / compression / maturity / funding-flip / util / concentration).

    PURE step. is_advisory=True."""

    id = "rates_desk_basis_hedge"
    name = "Rates Desk — Basis Hedge (PT vs Boros funding)"

    def step_pure(self, surface, risks, positions, state, as_of, *, cash,
                  debt_asset_price=Decimal("1"), global_approved=True, current_carries=None):
        current_carries = current_carries or {}
        orders: List[dict] = []
        books = dict(positions)  # shallow copy — we never mutate the input dict
        new_state = dict(state)

        # ── HOLD pass: continuous kill on every open basis book ──
        for mid in list(books.keys()):
            bk = books[mid]
            q = bk["opp"].quote
            risk = risks.get(q.underlying)
            cur_carry = current_carries.get(mid, bk["carry"])
            if risk is None:
                orders.append(_order("unwind", bk, market_id=mid, underlying=q.underlying,
                                     shape=TradeShape.BASIS_HEDGE.value, size=bk["size"],
                                     reason=KillReason.UNDERLYING_DEPEG.value, note="no risk surface"))
                del books[mid]
                continue
            res, ns = evaluate_hold(opp=bk["opp"], risk=risk, debt_asset_price=debt_asset_price,
                                    exit_liquidity=q.exit_liquidity_usd, current_carry=cur_carry,
                                    params=self.params, state=bk["state"], engine=self.engine)
            bk = dict(bk); bk["state"] = ns; bk["carry"] = cur_carry; books[mid] = bk
            if not res.approved:
                orders.append(_order("unwind", bk, market_id=mid, underlying=q.underlying,
                                     shape=TradeShape.BASIS_HEDGE.value, size=bk["size"],
                                     reason=res.reason.value, hedge="boros"))
                del books[mid]

        # ── ENTRY pass: scan BASIS_HEDGE candidates, gate each, open the approved ones ──
        for so in self.opp_engine.scan_detailed(surface, risks, as_of):
            if so.opportunity.shape != TradeShape.BASIS_HEDGE:
                continue
            q = so.opportunity.quote
            if q.market_id in books:
                continue
            risk = risks.get(q.underlying)
            if risk is None:
                continue
            res, ent_state = evaluate_entry(
                opp=so.opportunity, risk=risk, debt_asset_price=debt_asset_price,
                exit_liquidity=q.exit_liquidity_usd, params=self.params, state=KillState(),
                engine=self.engine)
            if res.approved and global_approved and res.approved_size_usd <= cash:
                books[q.market_id] = {"opp": so.opportunity, "size": res.approved_size_usd,
                                      "state": ent_state, "entry_rate": q.quoted_rate,
                                      "carry": res.net_edge, "hedge_leg": so.second_leg}
                cash -= res.approved_size_usd
                orders.append(_order("open", None, market_id=q.market_id, underlying=q.underlying,
                                     shape=TradeShape.BASIS_HEDGE.value, size=res.approved_size_usd,
                                     rate=q.quoted_rate, net_edge=res.net_edge, hedge="boros"))
        return orders, books, new_state


class LeveredCarrySleeve(_RatesPureSleeveBase):
    """Shape B — borrow a stable → buy PT: AMPLIFY the carry with GATED leverage.

    Leverage is a HARD function of the kill-rules: the sleeve only levers a position the gate would
    keep, and the applied leverage is capped at `max_leverage` (config). It unwinds the instant
    evaluate_hold fires CARRY_BASIS_COMPRESSION or MATURITY_BUFFER (the two kills the brief names for
    levered carry), or any earlier refusal-first structural kill.

    PURE step. is_advisory=True."""

    id = "rates_desk_levered_carry"
    name = "Rates Desk — Levered Carry (borrow stable, buy PT)"

    DEFAULT_MAX_LEVERAGE = Decimal("3")

    def __init__(self, params=None, costs=None, max_leverage: Optional[Decimal] = None) -> None:
        super().__init__(params, costs)
        self.max_leverage = max_leverage if max_leverage is not None else self.DEFAULT_MAX_LEVERAGE

    def _leverage_for(self, ltv: Decimal) -> Decimal:
        """Leverage as a HARD function of the kill/liquidation rules: the LTV ceiling implies a max
        recursive leverage 1/(1-ltv); we clamp it to the sleeve's max_leverage. fail-CLOSED: a
        malformed/extreme ltv yields leverage 1 (no leverage)."""
        l = _safe_decimal_local(ltv)
        if l is None or l < 0 or l >= Decimal("1"):
            return Decimal("1")
        implied = Decimal("1") / (Decimal("1") - l)
        return implied if implied < self.max_leverage else self.max_leverage

    def step_pure(self, surface, risks, positions, state, as_of, *, cash,
                  debt_asset_price=Decimal("1"), global_approved=True, current_carries=None):
        current_carries = current_carries or {}
        orders: List[dict] = []
        books = dict(positions)
        new_state = dict(state)

        # ── HOLD pass — unwind on compression / maturity (and any earlier structural kill) ──
        for mid in list(books.keys()):
            bk = books[mid]
            q = bk["opp"].quote
            risk = risks.get(q.underlying)
            cur_carry = current_carries.get(mid, bk["carry"])
            if risk is None:
                orders.append(_order("unwind", bk, market_id=mid, underlying=q.underlying,
                                     shape=TradeShape.LEVERED_CARRY.value, size=bk["size"],
                                     reason=KillReason.UNDERLYING_DEPEG.value, note="no risk surface"))
                del books[mid]
                continue
            res, ns = evaluate_hold(opp=bk["opp"], risk=risk, debt_asset_price=debt_asset_price,
                                    exit_liquidity=q.exit_liquidity_usd, current_carry=cur_carry,
                                    params=self.params, state=bk["state"], engine=self.engine)
            bk = dict(bk); bk["state"] = ns; bk["carry"] = cur_carry; books[mid] = bk
            if not res.approved:
                orders.append(_order("unwind", bk, market_id=mid, underlying=q.underlying,
                                     shape=TradeShape.LEVERED_CARRY.value, size=bk["size"],
                                     reason=res.reason.value, leverage=bk.get("leverage", D0)))
                del books[mid]

        # ── ENTRY pass — scan LEVERED_CARRY, gate, lever within max_leverage ──
        for so in self.opp_engine.scan_detailed(surface, risks, as_of):
            if so.opportunity.shape != TradeShape.LEVERED_CARRY:
                continue
            q = so.opportunity.quote
            if q.market_id in books:
                continue
            risk = risks.get(q.underlying)
            if risk is None:
                continue
            res, ent_state = evaluate_entry(
                opp=so.opportunity, risk=risk, debt_asset_price=debt_asset_price,
                exit_liquidity=q.exit_liquidity_usd, params=self.params, state=KillState(),
                engine=self.engine)
            if not (res.approved and global_approved):
                continue
            borrow_leg = so.second_leg
            ltv = borrow_leg.ltv if borrow_leg is not None else D0
            lev = self._leverage_for(ltv)               # HARD-capped leverage
            base_size = min(res.approved_size_usd, cash)
            if base_size <= D0:
                continue
            levered_size = base_size * lev
            books[q.market_id] = {"opp": so.opportunity, "size": base_size, "levered_size": levered_size,
                                  "leverage": lev, "state": ent_state, "entry_rate": q.quoted_rate,
                                  "carry": res.net_edge, "borrow_leg": borrow_leg}
            cash -= base_size
            orders.append(_order("open", None, market_id=q.market_id, underlying=q.underlying,
                                 shape=TradeShape.LEVERED_CARRY.value, size=base_size,
                                 levered_size=levered_size, leverage=lev, rate=q.quoted_rate,
                                 net_edge=res.net_edge))
        return orders, books, new_state


class RateMatrixSleeve(_RatesPureSleeveBase):
    """Shape D — cross-venue rate matrix: hold the argmax-net-rate venue, rotate ONLY when clearly
    better AND the candidate passes the full gate.

    Rotation rule (anti-churn hysteresis): switch from the HELD venue to a CANDIDATE venue ONLY when
        net_rate[candidate] − net_rate[held] > switch_cost + rotation_buffer
    AND the candidate opportunity passes the refusal-first gate. The held venue + its net_rate are
    carried in `state` so noise (a candidate barely better, within the buffer) never triggers a churn.

    PURE step. is_advisory=True."""

    id = "rates_desk_rate_matrix"
    name = "Rates Desk — Rate Matrix (argmax venue rotation)"

    DEFAULT_SWITCH_COST = Decimal("0.0005")
    DEFAULT_ROTATION_BUFFER = Decimal("0.0030")

    def __init__(self, params=None, costs=None, switch_cost: Optional[Decimal] = None,
                 rotation_buffer: Optional[Decimal] = None) -> None:
        super().__init__(params, costs)
        self.switch_cost = switch_cost if switch_cost is not None else self.DEFAULT_SWITCH_COST
        self.rotation_buffer = (rotation_buffer if rotation_buffer is not None
                                else self.DEFAULT_ROTATION_BUFFER)

    def step_pure(self, surface, risks, positions, state, as_of, *, cash,
                  debt_asset_price=Decimal("1"), global_approved=True, current_carries=None):
        current_carries = current_carries or {}
        orders: List[dict] = []
        books = dict(positions)
        new_state = dict(state)

        # candidate RATE_MATRIX opps this tick, keyed by underlying (argmax venue already chosen)
        candidates: Dict[str, ScannedOpportunity] = {}
        for so in self.opp_engine.scan_detailed(surface, risks, as_of):
            if so.opportunity.shape == TradeShape.RATE_MATRIX:
                candidates.setdefault(so.opportunity.quote.underlying, so)

        # ── HOLD / ROTATE pass for every open matrix book ──
        for mid in list(books.keys()):
            bk = books[mid]
            q = bk["opp"].quote
            underlying = q.underlying
            risk = risks.get(underlying)
            cur_carry = current_carries.get(mid, bk["carry"])
            if risk is None:
                orders.append(_order("unwind", bk, market_id=mid, underlying=underlying,
                                     shape=TradeShape.RATE_MATRIX.value, size=bk["size"],
                                     reason=KillReason.UNDERLYING_DEPEG.value, note="no risk surface"))
                del books[mid]
                continue
            # continuous kill on the held venue first (refusal-first)
            res, ns = evaluate_hold(opp=bk["opp"], risk=risk, debt_asset_price=debt_asset_price,
                                    exit_liquidity=q.exit_liquidity_usd, current_carry=cur_carry,
                                    params=self.params, state=bk["state"], engine=self.engine)
            bk = dict(bk); bk["state"] = ns; bk["carry"] = cur_carry; books[mid] = bk
            if not res.approved:
                orders.append(_order("unwind", bk, market_id=mid, underlying=underlying,
                                     shape=TradeShape.RATE_MATRIX.value, size=bk["size"],
                                     reason=res.reason.value, venue=bk.get("venue", "")))
                del books[mid]
                continue

            # ── ROTATION with hysteresis ──
            cand = candidates.get(underlying)
            held_net = bk.get("net_rate", bk["carry"])
            if cand is not None and cand.opportunity.quote.market_id != mid:
                cand_net = cand.edge.net_edge
                threshold = self.switch_cost + self.rotation_buffer
                if (cand_net - held_net) > threshold:
                    # candidate is CLEARLY better — but it must pass the full gate to rotate INTO it
                    cq = cand.opportunity.quote
                    crisk = risks.get(cq.underlying)
                    gres, gstate = evaluate_entry(
                        opp=cand.opportunity, risk=crisk, debt_asset_price=debt_asset_price,
                        exit_liquidity=cq.exit_liquidity_usd, params=self.params, state=KillState(),
                        engine=self.engine)
                    if gres.approved and global_approved:
                        # rotate: unwind held, open candidate at the same size (size-preserving)
                        size = bk["size"]
                        del books[mid]
                        books[cq.market_id] = {
                            "opp": cand.opportunity, "size": size, "state": gstate,
                            "entry_rate": cq.quoted_rate, "carry": cand_net,
                            "net_rate": cand_net, "venue": cand.edge.venue}
                        orders.append(_order(
                            "rotate", None, market_id=cq.market_id, from_market_id=mid,
                            underlying=underlying, shape=TradeShape.RATE_MATRIX.value, size=size,
                            from_venue=bk.get("venue", ""), to_venue=cand.edge.venue,
                            held_net=held_net, cand_net=cand_net, threshold=threshold))
                        continue
                # else: within buffer → HOLD (anti-churn); no order
            orders.append(_order("hold", bk, market_id=mid, underlying=underlying,
                                 shape=TradeShape.RATE_MATRIX.value, size=bk["size"],
                                 venue=bk.get("venue", ""), net_rate=held_net))

        # ── ENTRY pass — open a matrix book for any underlying we don't yet hold ──
        held_underlyings = {books[m]["opp"].quote.underlying for m in books}
        for underlying, cand in sorted(candidates.items()):
            if underlying in held_underlyings:
                continue
            cq = cand.opportunity.quote
            if cq.market_id in books:
                continue
            crisk = risks.get(underlying)
            if crisk is None:
                continue
            res, ent_state = evaluate_entry(
                opp=cand.opportunity, risk=crisk, debt_asset_price=debt_asset_price,
                exit_liquidity=cq.exit_liquidity_usd, params=self.params, state=KillState(),
                engine=self.engine)
            if res.approved and global_approved and res.approved_size_usd <= cash:
                books[cq.market_id] = {
                    "opp": cand.opportunity, "size": res.approved_size_usd, "state": ent_state,
                    "entry_rate": cq.quoted_rate, "carry": cand.edge.net_edge,
                    "net_rate": cand.edge.net_edge, "venue": cand.edge.venue}
                cash -= res.approved_size_usd
                held_underlyings.add(underlying)
                orders.append(_order("open", None, market_id=cq.market_id, underlying=underlying,
                                     shape=TradeShape.RATE_MATRIX.value, size=res.approved_size_usd,
                                     venue=cand.edge.venue, net_rate=cand.edge.net_edge,
                                     rate=cq.quoted_rate))
        return orders, books, new_state


def _safe_decimal_local(x):
    """Local fail-CLOSED Decimal coercion (mirrors fair_value_engine._safe_decimal; kept local so the
    sleeve module has no cross-import beyond the engine)."""
    from spa_core.strategy_lab.rates_desk.fair_value_engine import _safe_decimal as _sd
    return _sd(x)
