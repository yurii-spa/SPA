"""
spa_core/strategy_lab/liquidator/opportunity_estimator.py — addressable long-tail liquidation $.

For each isolated market the MarketMonitor found, estimate the ANNUAL addressable liquidation /
penalty / OEV-recapture opportunity the balance-sheet liquidator could capture, and — the crux —
GATE it on the EXIT GAP: can an atomic, single-block MEV liquidation route the seized collateral
through a DEX in one tick? If YES (deep DEX), the MEV bots already capture it → NOT our addressable
edge. If NO (nested/illiquid collateral), that share is the "MEV-bots-can't, balance-sheet-can"
opportunity this thesis is about.

THE ESTIMATE (per market), all from data we can get read-only or document transparently:

  borrowed_usd        ≈ tvl_usd * BORROW_SHARE[kind]
        DeFiLlama /pools does NOT expose per-market borrowed$ for Morpho/Euler, so we proxy it as
        a DOCUMENTED fraction of supply TVL per collateral kind (riskier collateral is borrowed
        against more conservatively → lower borrow share). FLAGGED assumption; the real number is
        a one-call RPC/subgraph read of each market's totalBorrowAssets.

  annual_liquidated   = borrowed_usd * ANNUAL_LIQ_TURNOVER[kind]
        the fraction of borrowed base that gets liquidated in a year. Long-tail / volatile
        collateral liquidates a LARGER share (more depeg/crash events) than vanilla. DOCUMENTED.

  gross_penalty_usd   = annual_liquidated * (liquidation_penalty_bps / 10_000)
        the statutory liquidation incentive $ available on that liquidated flow — the gross pool
        a liquidator competes for (penalty + any OEV recapture).

  EXIT GAP (reuse liquidation_nav._on_chain_exit_frac):
        atomic_fill_frac(S) = realised fraction of NAV selling a reference clip S into the
        collateral's aggregate on-chain DEX depth (constant-product slippage, the SAME model
        liquidation_nav.py uses). If atomic_fill_frac >= ATOMIC_LIQUIDATION_FILL_FLOOR the
        collateral is DEEP enough for an atomic MEV liquidation → atomic-MEV captures the penalty,
        addressable_to_us ≈ 0. Below the floor (illiquid / nested), an atomic unwind would eat the
        penalty in slippage, so MEV bots stand down → the WHOLE penalty is addressable to a
        balance-sheet liquidator that can hold + unwind over hours/days.

        addressable_penalty_usd = gross_penalty_usd * illiquid_share
          illiquid_share = 1 - clamp(atomic_fill_frac / ATOMIC_LIQUIDATION_FILL_FLOOR, 0, 1)
        → deep-DEX collateral ⇒ illiquid_share≈0 (atomic-MEV handles it, not addressable);
          no/thin-DEX collateral ⇒ illiquid_share≈1 (the addressable balance-sheet edge).

We need an aggregate on-chain DEX depth per collateral token. We discover it from the SAME /pools
feed (DEX-project pools whose symbol references the collateral token), reusing liquidation_nav's
DEX allowlist + min-pool floor. A collateral with NO qualifying DEX pool ⇒ atomic_fill_frac for
any non-trivial clip is ~0 ⇒ fully illiquid ⇒ fully addressable (fail-CLOSED toward "MEV can't").

FAIL-CLOSED everywhere: unknown collateral kind ⇒ high penalty + high turnover + illiquid; missing
DEX depth ⇒ illiquid (never assume deep). Deterministic, stdlib only, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.liquidator.market_monitor import (
    CollateralKind,
    IsolatedMarket,
)
# REUSE the validated liquidation-NAV slippage + DEX-discovery primitives (one source of truth).
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    _discover_dex_depth,
    _on_chain_exit_frac,
)

# Reference liquidation clip we test atomic fillability at. A real long-tail liquidation that breaks
# MEV is a chunky one (a whale position in a crash); $1M is the liquidation_nav reference mid-size.
REFERENCE_CLIP_USD = 1_000_000.0

# Above this realised atomic fill fraction at the reference clip, the collateral is "deep enough"
# for a single-block MEV liquidation (the penalty survives the slippage). Below it, an atomic unwind
# eats the penalty → MEV bots stand down → balance-sheet liquidator's tail. 0.985 ≈ a ~1.5% all-in
# atomic round-trip is the rough break-even vs a typical incentive on liquid collateral.
ATOMIC_LIQUIDATION_FILL_FLOOR = 0.985

# DOCUMENTED borrowed$/supply-TVL share per collateral kind (RPC-gated in reality; flagged).
_BORROW_SHARE: Dict[CollateralKind, float] = {
    CollateralKind.VANILLA_STABLE: 0.80,
    CollateralKind.VANILLA_ETH: 0.55,
    CollateralKind.VANILLA_BTC: 0.50,
    CollateralKind.LRT: 0.45,
    CollateralKind.PT: 0.50,
    CollateralKind.LP: 0.35,
    CollateralKind.EXOTIC: 0.30,
    CollateralKind.UNKNOWN: 0.30,
}

# DOCUMENTED annual liquidation turnover (fraction of borrowed base liquidated per year) per kind.
# Vanilla collateral rarely liquidates; long-tail / depeg-prone collateral turns over much more.
_ANNUAL_LIQ_TURNOVER: Dict[CollateralKind, float] = {
    CollateralKind.VANILLA_STABLE: 0.01,
    CollateralKind.VANILLA_ETH: 0.04,
    CollateralKind.VANILLA_BTC: 0.04,
    CollateralKind.LRT: 0.15,
    CollateralKind.PT: 0.10,
    CollateralKind.LP: 0.12,
    CollateralKind.EXOTIC: 0.18,
    CollateralKind.UNKNOWN: 0.18,
}


def _borrow_share(kind: CollateralKind) -> float:
    return _BORROW_SHARE.get(kind, _BORROW_SHARE[CollateralKind.UNKNOWN])


def _annual_turnover(kind: CollateralKind) -> float:
    return _ANNUAL_LIQ_TURNOVER.get(kind, _ANNUAL_LIQ_TURNOVER[CollateralKind.UNKNOWN])


@dataclass
class MarketOpportunity:
    """The addressable opportunity for one market. `addressable_penalty_usd` is the headline: the
    annual gross penalty $ that is NOT atomic-MEV-capturable (the balance-sheet-liquidator share)."""
    protocol: str
    chain: str
    symbol: str
    collateral_kind: str
    tvl_usd: float
    borrowed_usd_est: float
    annual_liquidated_usd_est: float
    liquidation_penalty_bps: float
    gross_penalty_usd_est: float          # annual statutory penalty $ on the liquidated flow
    dex_depth_usd: float                  # aggregate qualifying on-chain DEX depth for the collateral
    atomic_fill_frac: float               # realised fill of REFERENCE_CLIP via DEX (0..~1)
    illiquid_share: float                 # 0 (deep, atomic-MEV) .. 1 (no DEX, fully addressable)
    addressable_penalty_usd: float        # gross_penalty * illiquid_share — OUR edge
    is_long_tail: bool
    atomic_mev_handles_it: bool           # True ⇒ deep DEX ⇒ not our edge
    data_gaps: List[str] = field(default_factory=list)


@dataclass
class UniverseOpportunity:
    """The aggregate verdict-grade numbers across the universe."""
    n_markets: int
    n_long_tail: int
    total_gross_penalty_usd: float
    total_addressable_penalty_usd: float        # the headline vs the $20M/yr Alt-1 kill bar
    long_tail_addressable_penalty_usd: float    # addressable restricted to genuinely long-tail kinds
    top20_addressable_penalty_usd: float        # Alt-1's bar reads the TOP-20 illiquid markets
    by_kind_addressable_usd: Dict[str, float]
    markets: List[MarketOpportunity]
    generated_at: str = ""


class OpportunityEstimator:
    """Estimate the addressable long-tail liquidation opportunity across the monitored markets.

    `dex_pools` is the /pools list used to discover each collateral's on-chain DEX depth — pass the
    SAME list the MarketMonitor fetched (one network call for the whole run). If None, the estimator
    fetches it itself (real DeFiLlama). Fail-CLOSED: no DEX depth for a collateral ⇒ illiquid ⇒ the
    whole penalty is addressable (never assume the collateral is liquid)."""

    def __init__(self, dex_pools: Optional[List[dict]] = None,
                 reference_clip_usd: float = REFERENCE_CLIP_USD,
                 atomic_fill_floor: float = ATOMIC_LIQUIDATION_FILL_FLOOR):
        self._dex_pools = dex_pools
        self._clip = reference_clip_usd
        self._floor = atomic_fill_floor
        self._depth_cache: Dict[str, Tuple[float, int]] = {}

    def _pools(self) -> List[dict]:
        if self._dex_pools is not None:
            return self._dex_pools
        from spa_core.strategy_lab.data._http import http_fetch
        from spa_core.strategy_lab.liquidator.market_monitor import POOLS_URL, _validate_pools
        self._dex_pools = _validate_pools(http_fetch(POOLS_URL))
        return self._dex_pools

    def _collateral_token(self, market: IsolatedMarket) -> str:
        """The collateral token symbol whose DEX depth gates the exit. For a single-asset market
        that is the pool symbol; for an LP/multi market we use the first leg (the dominant token)."""
        sym = market.symbol.upper()
        for sep in ("/", " ", "_"):
            sym = sym.replace(sep, "-")
        legs = [l for l in sym.split("-") if l]
        return legs[0] if legs else market.symbol.upper()

    def _dex_depth(self, token: str, pools: List[dict]) -> float:
        if token not in self._depth_cache:
            self._depth_cache[token] = _discover_dex_depth(pools, token)
        return self._depth_cache[token][0]

    def estimate_market(self, market: IsolatedMarket, pools: List[dict]) -> MarketOpportunity:
        kind = market.collateral_kind
        borrowed = market.tvl_usd * _borrow_share(kind)
        annual_liq = borrowed * _annual_turnover(kind)
        gross_penalty = annual_liq * (market.liquidation_penalty_bps / 10_000.0)

        token = self._collateral_token(market)
        dex_depth = self._dex_depth(token, pools)
        fill = _on_chain_exit_frac(dex_depth, self._clip)
        # fail-CLOSED: no qualifying DEX depth ⇒ fill is None ⇒ treat as fully illiquid.
        atomic_fill = 0.0 if fill is None else fill
        if self._floor <= 0:
            illiquid_share = 0.0
        else:
            ratio = atomic_fill / self._floor
            illiquid_share = 1.0 - (1.0 if ratio > 1.0 else (0.0 if ratio < 0.0 else ratio))
        addressable = gross_penalty * illiquid_share
        atomic_handles = atomic_fill >= self._floor

        gaps = list(market.data_gaps)
        gaps.append("borrowed_usd is a DOCUMENTED share of TVL (RPC-gated real value)")
        gaps.append("annual liquidation turnover is a DOCUMENTED per-kind assumption")
        if dex_depth <= 0.0:
            gaps.append(f"no qualifying public DEX depth for {token} → fail-CLOSED fully illiquid")

        return MarketOpportunity(
            protocol=market.protocol,
            chain=market.chain,
            symbol=market.symbol,
            collateral_kind=kind.value,
            tvl_usd=round(market.tvl_usd, 2),
            borrowed_usd_est=round(borrowed, 2),
            annual_liquidated_usd_est=round(annual_liq, 2),
            liquidation_penalty_bps=market.liquidation_penalty_bps,
            gross_penalty_usd_est=round(gross_penalty, 2),
            dex_depth_usd=round(dex_depth, 2),
            atomic_fill_frac=round(atomic_fill, 6),
            illiquid_share=round(illiquid_share, 6),
            addressable_penalty_usd=round(addressable, 2),
            is_long_tail=market.is_long_tail,
            atomic_mev_handles_it=atomic_handles,
            data_gaps=gaps,
        )

    def estimate_universe(self, markets: List[IsolatedMarket]) -> UniverseOpportunity:
        pools = self._pools()
        opps = [self.estimate_market(m, pools) for m in markets]
        total_gross = sum(o.gross_penalty_usd_est for o in opps)
        total_addr = sum(o.addressable_penalty_usd for o in opps)
        lt_addr = sum(o.addressable_penalty_usd for o in opps if o.is_long_tail)
        by_kind: Dict[str, float] = {}
        for o in opps:
            by_kind[o.collateral_kind] = by_kind.get(o.collateral_kind, 0.0) + o.addressable_penalty_usd
        # Alt-1 reads the TOP-20 unsupported/illiquid markets by addressable penalty.
        top20 = sorted(opps, key=lambda o: o.addressable_penalty_usd, reverse=True)[:20]
        top20_addr = sum(o.addressable_penalty_usd for o in top20)
        return UniverseOpportunity(
            n_markets=len(opps),
            n_long_tail=sum(1 for o in opps if o.is_long_tail),
            total_gross_penalty_usd=round(total_gross, 2),
            total_addressable_penalty_usd=round(total_addr, 2),
            long_tail_addressable_penalty_usd=round(lt_addr, 2),
            top20_addressable_penalty_usd=round(top20_addr, 2),
            by_kind_addressable_usd={k: round(v, 2) for k, v in sorted(by_kind.items())},
            markets=sorted(opps, key=lambda o: o.addressable_penalty_usd, reverse=True),
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
