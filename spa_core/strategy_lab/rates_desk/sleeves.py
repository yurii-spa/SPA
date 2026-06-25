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
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry, evaluate_hold


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
        for q in quotes:
            risk = risks.get(q.underlying)
            if risk is None:
                continue  # fail-CLOSED: no risk surface → no entry
            if q.market_id in self._books:
                continue  # already holding this market
            opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY,
                              requested_size_usd=self._cash)
            result, new_state = evaluate_entry(
                opp=opp, risk=risk, debt_asset_price=debt_asset_price,
                exit_liquidity=q.exit_liquidity_usd, params=self.params, state=KillState(),
                engine=self.engine,
                trailing_yield=trailing_yields.get(q.underlying),
                boros_forward=boros_forwards.get(q.underlying),
            )
            verdicts.append(result)
            # composition under the global policy: approve ONLY if both say yes.
            if result.approved and global_approved and result.approved_size_usd <= self._cash:
                self._books[q.market_id] = {
                    "opp": opp, "size": result.approved_size_usd, "state": new_state,
                    "entry_rate": q.quoted_rate, "carry": result.net_edge,
                }
                self._cash -= result.approved_size_usd
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
