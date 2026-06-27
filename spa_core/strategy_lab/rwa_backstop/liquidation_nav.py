"""
spa_core/strategy_lab/rwa_backstop/liquidation_nav.py — the RWA Liquidation-NAV engine.

For each tokenized-RWA collateral asset, MEASURE the *executable exit* — what a forced liquidator
would actually realise per share — from data we can get READ-ONLY, and compare it to the uniform
marketing NAV ($1.00). The thesis ("lend against Liquidation NAV, not marketing NAV") is real iff
this gap is real and measurable.

Two exit legs, per liquidation size S ∈ {$100k, $1M, $10M}:

  (1) ON-CHAIN DEX EXIT — the only leg a permissionless liquidator can execute without the
      issuer's cooperation. We discover the token's public DEX/AMM pools (DeFiLlama /pools, the
      same keyless feed the repo already uses) and estimate the realised price after slippage
      from the aggregate DEX TVL using a constant-product depth model. Transfer-restricted tokens
      have NO public DEX pool an arbitrary liquidator can sell into → on-chain exit ≈ 0. That zero
      is the KEY FINDING for permissioned RWA, not a bug.

  (2) ISSUER REDEMPTION EXIT — redeem the share with the issuer at marketing NAV minus the
      DOCUMENTED redemption fee, discounted for the DOCUMENTED settlement delay at the RWA
      risk-free rate (time-value of being locked up) and an execution-uncertainty haircut. This
      leg requires whitelisting/a subscription agreement we do NOT have read-only — it is a
      DOCUMENTED ASSUMPTION, clearly flagged. Fail-CLOSED: an asset whose redemption terms are not
      documented (redemption_documented=False) gets redemption-exit = 0.

LiqNAV(S) = min(on_chain_exit(S), redemption_exit(S)) − operational/transfer haircuts.
  • min(): a prudent underwriter prices the WORSE of the two paths it can actually rely on at
    that size — a deep DEX is irrelevant if you can't move the token; a redemption right is
    irrelevant intraday if it settles T+2 and you need cash now.
  • For an UNRESTRICTED token with a deep DEX, on-chain ≈ redemption ≈ ~$1 → LiqNAV ≈ NAV.
  • For a RESTRICTED token, on-chain = 0 → min() = 0 regardless of any redemption right, UNLESS
    the redemption right is itself fast+documented enough to count as the executable path within
    the underwriting horizon (we expose BOTH the min and the redemption-only value so the safety
    board can label REDEMPTION_ONLY rather than UNSAFE).

FAIL-CLOSED everywhere: no DEX data → on-chain exit 0 (never assume liquid); no documented
redemption → redemption exit 0; never fabricate a cash-like LiqNAV. Deterministic, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.rwa_backstop.collateral_registry import (
    CollateralAsset,
)

POOLS_URL = "https://yields.llama.fi/pools"

Fetcher = Callable[[str], object]

# Liquidation sizes (USD) we measure the executable exit at.
SIZES_USD: Tuple[float, ...] = (100_000.0, 1_000_000.0, 10_000_000.0)

# DeFiLlama project ids that are genuine public DEX/AMM venues an arbitrary liquidator could sell
# into (NOT lending markets re-listing the token, NOT the issuer's own native fund pool). A pool
# whose project is one of these AND whose symbol contains the RWA token is treated as on-chain
# exit depth. Conservative allowlist — anything unknown does not count as DEX depth (fail-closed).
DEX_PROJECTS: Tuple[str, ...] = (
    "uniswap-v3", "uniswap-v2", "curve-dex", "curve", "balancer-v2", "balancer-v3",
    "aerodrome-v1", "aerodrome-slipstream", "velodrome-v2", "velodrome-v3",
    "pancakeswap-amm-v3", "pancakeswap-amm", "sushiswap", "fluid-dex", "maverick-v2",
)

# Per-pool minimum TVL to count as real DEX depth (dust pools are not an exit). Repo risk floor.
MIN_DEX_POOL_TVL_USD = 250_000.0

# Constant-product slippage model: selling S notional into an AMM with one-sided liquidity L
# (≈ TVL/2 of value on the buy side of a 50/50 pool). For x*y=k, selling dx of the token moves
# price so the AVERAGE realised price = P0 * L/(L+dx)  (dx in value terms ≈ S at P0≈$1). The
# realised value fraction vs marketing NAV is therefore L/(L+S). This is a deliberately SIMPLE,
# conservative depth proxy (real concentrated-liquidity pools can be deeper near peg but also far
# thinner in a forced unwind); it is monotonic decreasing in S, which is the property we test.
# A small fixed taker/route cost is added on top.
DEX_ROUTING_COST_BPS = 5.0          # swap fee + routing/MEV on a forced unwind (conservative)

# Operational / transfer haircut applied to EVERY realised exit (bridge, settlement-op, custody
# move on a forced liquidation). Small but non-zero — nothing is frictionless under stress.
OPERATIONAL_HAIRCUT_BPS = 10.0

# Redemption leg: discount the redeemed NAV for (a) the documented fee, (b) time-value of the
# settlement delay at the RWA risk-free rate, (c) an execution-uncertainty haircut that grows with
# the documented delay (longer lockups = more can go wrong / gate risk before you get paid).
RWA_RISKFREE_APY_PCT = 3.4          # ~tokenized-T-bill blend (rwa_feed live floor; offline literal)
REDEMPTION_UNCERTAINTY_BPS_PER_DAY = 8.0   # execution-uncertainty haircut per documented delay day
REDEMPTION_MAX_UNCERTAINTY_BPS = 200.0     # cap the uncertainty haircut (2%)

# Below this LiqNAV/NAV fraction at the $1M reference size, the on-chain path is "no real exit".
ON_CHAIN_LIQUID_THRESHOLD = 0.97


@dataclass
class SizedExit:
    """The measured executable exit at one liquidation size."""
    size_usd: float
    on_chain_value_frac: Optional[float]      # realised fraction of NAV via DEX, or None if no DEX
    redemption_value_frac: Optional[float]    # realised fraction of NAV via redemption, or None
    liq_nav_frac: float                       # min of the available legs minus op haircut (0..1)
    liq_nav_usd: float                        # liq_nav_frac * marketing_nav_usd
    binding_leg: str                          # "dex" | "redemption" | "none"


@dataclass
class LiquidationNAVResult:
    """Full LiqNAV measurement for one collateral asset."""
    symbol: str
    issuer: str
    marketing_nav_usd: float
    transfer_restricted: bool
    on_chain_dex_tvl_usd: float               # aggregate qualifying DEX depth discovered (0 if none)
    n_dex_pools: int
    redemption_documented: bool
    redemption_delay_days: float
    redemption_fee_bps: float
    sized: Dict[float, SizedExit] = field(default_factory=dict)   # {size_usd: SizedExit}
    data_gaps: List[str] = field(default_factory=list)
    generated_at: str = ""

    def liq_nav_frac(self, size_usd: float) -> Optional[float]:
        se = self.sized.get(size_usd)
        return se.liq_nav_frac if se else None


# ── DeFiLlama pool discovery (the on-chain exit data we CAN get) ───────────────────────────────
def _validate_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"rwa pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise ValueError(f"rwa pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("rwa pools: 'data' missing or not a list")
    return data


def _discover_dex_depth(pools: List[dict], symbol: str) -> Tuple[float, int]:
    """Aggregate public DEX TVL for `symbol` across the DEX_PROJECTS allowlist.

    Returns (total_dex_tvl_usd, n_pools). A pool counts iff its project is a known public DEX AND
    its symbol field references the RWA token AND its TVL ≥ MIN_DEX_POOL_TVL_USD. Conservative:
    anything off-allowlist is NOT counted as an exit (fail-closed)."""
    sym = symbol.upper()
    total = 0.0
    n = 0
    for p in pools:
        if not isinstance(p, dict):
            continue
        proj = (p.get("project") or "").lower()
        if proj not in DEX_PROJECTS:
            continue
        psym = (p.get("symbol") or "").upper()
        # symbol match: the RWA token appears as a leg of the pool's symbol (e.g. "USDY-USDC").
        legs = [s for s in psym.replace("/", "-").split("-") if s]
        if sym not in legs:
            continue
        tvl = p.get("tvlUsd")
        tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
        if tvl < MIN_DEX_POOL_TVL_USD:
            continue
        total += tvl
        n += 1
    return total, n


# ── exit-leg math (deterministic, fail-CLOSED) ────────────────────────────────────────────────
def dex_exit_frac(depth_usd: float, size_usd: float) -> Optional[float]:
    """Realised fraction of NAV from selling `size_usd` into aggregate DEX depth `depth_usd`.

    The repo's ONE constant-product slippage primitive — the conservative lower bound on what a
    forced unwind realises. Promoted from the RWA backstop's `_on_chain_exit_frac` to be REUSED by
    the rates-desk exit-NAV engine (the alias below preserves the old private name so nothing
    breaks). Same body.

    Returns None if there is NO qualifying depth (the permissioned-token / no-pool case — the exit
    does not exist, NOT a 100% fill). One-sided liquidity L ≈ depth/2; constant-product average
    realised price fraction = L/(L+S), minus a fixed routing/taker cost. Monotonic decreasing in
    size_usd. Floored at 0.

    Conservative by construction: real concentrated-liquidity pools (Pendle PT) can be deeper near
    peg but FAR thinner in a forced unwind, so `L/(L+S)` is published only as a LOWER BOUND, never
    as a precise execution model (see the rates-desk exit-NAV engine + the Oct-2025 §9 stress)."""
    if not isinstance(depth_usd, (int, float)) or not isinstance(size_usd, (int, float)):
        return None
    # non-finite (NaN/inf) or non-positive depth/size ⇒ no defensible bound ⇒ fail-CLOSED to None.
    if depth_usd != depth_usd or size_usd != size_usd:  # NaN
        return None
    if depth_usd in (float("inf"), float("-inf")) or size_usd in (float("inf"), float("-inf")):
        return None
    if depth_usd <= 0.0 or size_usd < 0.0:
        return None
    one_sided = depth_usd / 2.0
    slip_frac = one_sided / (one_sided + size_usd)        # < 1, decreasing in size
    routing = DEX_ROUTING_COST_BPS / 10_000.0
    return max(0.0, slip_frac - routing)


# Backward-compatible alias — the RWA backstop engine + its tests call the private name.
_on_chain_exit_frac = dex_exit_frac


def _redemption_exit_frac(asset: CollateralAsset) -> Optional[float]:
    """Realised fraction of NAV from redeeming with the issuer at DOCUMENTED terms.

    Returns None (fail-CLOSED) when redemption terms are NOT documented — we never assume a
    redemption right we cannot cite. Otherwise: NAV * (1 − fee) discounted for the settlement
    delay at the RWA risk-free rate, minus a delay-scaled execution-uncertainty haircut."""
    if not asset.redemption_documented:
        return None
    fee_frac = max(0.0, asset.redemption_fee_bps) / 10_000.0
    # time-value of the lockup: PV factor over the documented delay at the RWA risk-free rate.
    delay_yrs = max(0.0, asset.redemption_delay_days) / 365.0
    tv_factor = 1.0 / (1.0 + (RWA_RISKFREE_APY_PCT / 100.0) * delay_yrs)
    # execution-uncertainty haircut grows with the delay (gate / NAV-move risk before you're paid).
    unc_bps = min(
        REDEMPTION_MAX_UNCERTAINTY_BPS,
        REDEMPTION_UNCERTAINTY_BPS_PER_DAY * max(0.0, asset.redemption_delay_days),
    )
    unc_frac = unc_bps / 10_000.0
    val = (1.0 - fee_frac) * tv_factor - unc_frac
    return max(0.0, val)


def _sized_exit(
    asset: CollateralAsset, dex_tvl_usd: float, size_usd: float, redemption_frac: Optional[float]
) -> SizedExit:
    """Combine the two legs at one size into the LiqNAV, fail-CLOSED."""
    on_chain = _on_chain_exit_frac(dex_tvl_usd, size_usd)
    op_haircut = OPERATIONAL_HAIRCUT_BPS / 10_000.0

    # available legs (None = leg does not exist for this asset)
    legs: List[Tuple[str, float]] = []
    if on_chain is not None:
        legs.append(("dex", on_chain))
    if redemption_frac is not None:
        legs.append(("redemption", redemption_frac))

    if not legs:
        # No executable exit at all → LiqNAV 0 (fail-CLOSED, never cash-like).
        return SizedExit(
            size_usd=size_usd, on_chain_value_frac=on_chain,
            redemption_value_frac=redemption_frac, liq_nav_frac=0.0, liq_nav_usd=0.0,
            binding_leg="none",
        )

    # A prudent underwriter prices the WORSE of the paths it can actually rely on at this size.
    binding_leg, best_of_worst = min(legs, key=lambda kv: kv[1])
    liq_frac = max(0.0, best_of_worst - op_haircut)
    return SizedExit(
        size_usd=size_usd,
        on_chain_value_frac=None if on_chain is None else round(on_chain, 6),
        redemption_value_frac=None if redemption_frac is None else round(redemption_frac, 6),
        liq_nav_frac=round(liq_frac, 6),
        liq_nav_usd=round(liq_frac * asset.marketing_nav_usd, 6),
        binding_leg=binding_leg,
    )


# ── the engine ────────────────────────────────────────────────────────────────────────────────
class LiquidationNAVEngine:
    """Measure LiqNAV per collateral asset. Inject `fetcher` (url->json) in tests; the real one
    hits the keyless DeFiLlama /pools. Fail-CLOSED on every missing leg."""

    def __init__(self, fetcher: Optional[Fetcher] = None, sizes_usd: Tuple[float, ...] = SIZES_USD):
        if fetcher is None:
            from spa_core.strategy_lab.data._http import http_fetch
            fetcher = http_fetch
        self._fetch = fetcher
        self._sizes = tuple(sorted(sizes_usd))

    def _pools(self) -> List[dict]:
        """Fetch + validate /pools. Fail-CLOSED: on any failure return [] (→ no DEX depth for any
        asset → on-chain exit 0). We never fabricate depth."""
        try:
            return _validate_pools(self._fetch(POOLS_URL))
        except Exception:  # noqa: BLE001 — fail-closed: no pools ⇒ zero DEX depth everywhere
            return []

    def measure_asset(self, asset: CollateralAsset, pools: List[dict]) -> LiquidationNAVResult:
        """Measure LiqNAV for one asset given a (possibly empty) pools list."""
        gaps: List[str] = []

        # On-chain leg: a transfer-restricted token CANNOT be sold by an arbitrary liquidator on a
        # public DEX even if a pool nominally exists → exit 0 by construction (the key finding).
        if asset.transfer_restricted:
            dex_tvl, n_pools = 0.0, 0
            gaps.append("transfer_restricted: no public DEX exit for an arbitrary liquidator")
        elif asset.token_contract is None:
            dex_tvl, n_pools = 0.0, 0
            gaps.append("no public token contract → cannot locate/execute an on-chain exit")
        else:
            dex_tvl, n_pools = _discover_dex_depth(pools, asset.symbol)
            if not pools:
                gaps.append("DEX pool data unavailable (fetch failed) → on-chain exit fail-closed to 0")
            elif n_pools == 0:
                gaps.append("no qualifying public DEX pool found → on-chain exit 0")

        # Redemption leg (documented assumption; relationship-gated to actually execute).
        redemption_frac = _redemption_exit_frac(asset)
        if redemption_frac is None:
            gaps.append("redemption terms not documented → redemption exit fail-closed to 0")
        else:
            gaps.append("redemption leg is DOCUMENTED-ONLY (requires whitelist/subscription to execute)")

        sized: Dict[float, SizedExit] = {}
        for size in self._sizes:
            sized[size] = _sized_exit(asset, dex_tvl, size, redemption_frac)

        return LiquidationNAVResult(
            symbol=asset.symbol,
            issuer=asset.issuer,
            marketing_nav_usd=asset.marketing_nav_usd,
            transfer_restricted=asset.transfer_restricted,
            on_chain_dex_tvl_usd=round(dex_tvl, 2),
            n_dex_pools=n_pools,
            redemption_documented=asset.redemption_documented,
            redemption_delay_days=asset.redemption_delay_days,
            redemption_fee_bps=asset.redemption_fee_bps,
            sized=sized,
            data_gaps=gaps,
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    def measure_universe(self, assets: List[CollateralAsset]) -> List[LiquidationNAVResult]:
        """Measure every asset against a SINGLE /pools fetch (one network call for the run)."""
        pools = self._pools()
        return [self.measure_asset(a, pools) for a in assets]
