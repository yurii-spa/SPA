"""
spa_core/strategy_lab/liquidator/market_monitor.py — read-only index of isolated lending markets.

Builds a deterministic snapshot of every Morpho Blue + Euler V2 market from the keyless DeFiLlama
/pools surface (the same feed the repo's adapters + liquidation_nav.py already use), and CLASSIFIES
each market's collateral kind. The thesis lives or dies on the LONG TAIL — markets whose collateral
is esoteric (LRTs, PTs, LP tokens, exotic BTC wrappers, synthetic dollars) where an atomic, single-
block MEV liquidation cannot route the seized collateral through a deep DEX in one tick. Vanilla
collateral (ETH/BTC/USDC) is where MEV bots already win; we want the opposite tail.

WHAT IS / ISN'T MEASURABLE (honest, surfaced in every IsolatedMarket.data_gaps):
  - DeFiLlama /pools gives, PER MARKET: protocol, chain, symbol (the collateral / supplied token),
    tvlUsd, apyBase (supply APY), exposure (single/multi), underlyingTokens. This is REAL and live.
  - DeFiLlama /pools does NOT reliably give, at the pool level for Morpho/Euler isolated markets:
    the LLTV / liquidation incentive, apyBaseBorrow, or the borrowed amount per collateral market
    (those fields come back null for ~all morpho-blue/euler-v2 pools). So the per-market borrowed$,
    the statutory liquidation penalty, and — critically — the at-risk (near-liquidation) position
    set are NOT in the aggregate feed. They require RPC / subgraph reads of each market's params +
    each borrower's health factor. We use DOCUMENTED penalty/turnover/borrow-share constants
    (clearly flagged) and fail-CLOSED where a value is genuinely unknown.

A note on Morpho/Euler /pools semantics: each pool row is a SUPPLY vault / market keyed by the
supplied (collateral-or-loan) asset. `exposure="single"` is a single-asset market; `multi` is an
LP-style multi-asset pool. We classify off the symbol + underlyingTokens, not off an LLTV we don't
have. The collateral KIND is what gates the exit-gap, and the kind IS legible from the symbol.

stdlib only, deterministic, fail-CLOSED, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

POOLS_URL = "https://yields.llama.fi/pools"

# The isolated-lending protocols this de-risk targets (DeFiLlama project ids).
TARGET_PROJECTS: Tuple[str, ...] = ("morpho-blue", "euler-v2")

Fetcher = Callable[[str], object]


class CollateralKind(enum.Enum):
    """The collateral archetype of an isolated market — drives the exit-gap (atomic-MEV vs not)."""
    VANILLA_STABLE = "vanilla_stable"  # USDC/USDT/DAI/PYUSD… deep DEX, atomic-MEV trivially handles it
    VANILLA_ETH = "vanilla_eth"        # WETH/stETH/wstETH/rETH/cbETH — deep, atomic-MEV handles it
    VANILLA_BTC = "vanilla_btc"        # WBTC/cbBTC/tBTC/LBTC — deep enough; mostly atomic-MEV
    LRT = "lrt"                        # weETH/ezETH/rsETH/pufETH/… restaking — THIN, depeg-prone (TAIL)
    PT = "pt"                          # Pendle PT (fixed-rate) — maturity/oracle-gated, thin DEX (TAIL)
    LP = "lp"                          # LP / multi-asset position — must be UNWOUND, not sold (TAIL)
    EXOTIC = "exotic"                  # everything else esoteric (HYPE LSTs, niche wrappers) (TAIL)
    UNKNOWN = "unknown"               # unclassifiable symbol → fail-CLOSED treated as TAIL (illiquid)

    @property
    def is_long_tail(self) -> bool:
        """True iff this kind is where atomic, single-block MEV liquidation tends to BREAK (the
        addressable balance-sheet-liquidator tail). Vanilla kinds are NOT long-tail."""
        return self in (
            CollateralKind.LRT, CollateralKind.PT, CollateralKind.LP,
            CollateralKind.EXOTIC, CollateralKind.UNKNOWN,
        )


# ── symbol classification tables (deterministic, documented) ──────────────────────────────────
# Matched as whole tokens against the pool symbol's legs (split on '-'/'/'), case-insensitive.
# Order matters: the FIRST table that matches a leg wins, tail kinds checked before vanilla so a
# paired "WEETH-USDC" classifies as LRT (the risky leg), not stable.
_LRT_TOKENS = frozenset({
    "WEETH", "EZETH", "RSETH", "PUFETH", "RSWETH", "WEETHS", "AMPHRETH", "EETH",
    "WEETHK", "LSETH", "UNIETH", "INETH", "RSTETH", "MSETH", "AGETH", "PZETH", "RSWETH",
})
_PT_PREFIX = "PT"           # Pendle principal tokens are symboled "PT-...".
_PT_TOKENS = frozenset({"PTUSDE", "PTWEETH", "PTSUSDE"})  # occasional collapsed forms
_LP_TOKENS = frozenset({  # explicit LP / pool tokens that must be unwound, not spot-sold
    "UNI-V2", "UNIV2", "SLP", "CRV", "CRVLP", "BPT", "AERO-LP", "VELO-LP",
})
_BTC_TOKENS = frozenset({"WBTC", "CBBTC", "TBTC", "LBTC", "UBTC", "EBTC", "SOLVBTC", "PUMPBTC", "FBTC"})
_ETH_TOKENS = frozenset({"WETH", "ETH", "STETH", "WSTETH", "RETH", "CBETH", "OSETH", "METH", "ANKRETH"})
_STABLE_TOKENS = frozenset({
    "USDC", "USDT", "USDT0", "USD₮0", "DAI", "PYUSD", "USDE", "SUSDE", "SUSDS", "SDAI", "USDS",
    "USD0", "USD0++", "FRAX", "SFRAX", "CRVUSD", "GHO", "USDM", "USDY", "RLUSD", "AUSD", "DEUSD",
    "USR", "WSRUSD", "RUSD", "USDF", "FDUSD", "LUSD", "BOLD", "USDL", "SRUSD",
})
# Esoteric LSTs / niche wrappers that are NOT a deep-DEX vanilla asset (HYPE ecosystem etc.)
_EXOTIC_HINTS = frozenset({
    "HYPE", "KHYPE", "WHYPE", "WSTHYPE", "HYPERUSDCA", "MON", "WMON", "XAUT", "XAUT0", "PAXG",
    "SYRUPUSDC", "BBQ", "STEAK", "GT", "RE7", "MEV", "HYPER",
})


def _legs(symbol: str) -> List[str]:
    """Split a pool symbol into its token legs, upper-cased. 'WEETH-USDC' → ['WEETH','USDC']."""
    s = (symbol or "").upper().strip()
    if not s:
        return []
    for sep in ("/", " ", "_"):
        s = s.replace(sep, "-")
    return [leg for leg in s.split("-") if leg]


def _classify_leg(leg: str) -> CollateralKind:
    if leg.startswith(_PT_PREFIX) and (leg == _PT_PREFIX or leg[2:3].isalpha() or leg in _PT_TOKENS):
        # 'PT', 'PTUSDE', 'PTWEETH' — Pendle principal token forms.
        if leg in _LRT_TOKENS or leg in _STABLE_TOKENS:
            pass  # not actually a PT (defensive); fall through
        else:
            return CollateralKind.PT
    if leg in _LRT_TOKENS:
        return CollateralKind.LRT
    if leg in _LP_TOKENS:
        return CollateralKind.LP
    if leg in _BTC_TOKENS:
        return CollateralKind.VANILLA_BTC
    if leg in _ETH_TOKENS:
        return CollateralKind.VANILLA_ETH
    if leg in _STABLE_TOKENS:
        return CollateralKind.VANILLA_STABLE
    if any(h in leg for h in _EXOTIC_HINTS):
        return CollateralKind.EXOTIC
    return CollateralKind.UNKNOWN


# Precedence: a market is as RISKY as its riskiest leg (the collateral that an MEV bot must offload).
_KIND_PRECEDENCE: Tuple[CollateralKind, ...] = (
    CollateralKind.LP, CollateralKind.LRT, CollateralKind.PT, CollateralKind.EXOTIC,
    CollateralKind.UNKNOWN, CollateralKind.VANILLA_BTC, CollateralKind.VANILLA_ETH,
    CollateralKind.VANILLA_STABLE,
)


def classify_collateral(
    symbol: str, exposure: Optional[str] = None, stablecoin: Optional[bool] = None
) -> CollateralKind:
    """Classify a market's collateral kind from its DeFiLlama symbol (+ exposure / stablecoin hints).

    A `multi` exposure (LP-style) is LP regardless of legs (it must be unwound, not spot-sold).
    A `stablecoin=True` SINGLE-asset row is a stable-denominated position (almost always a
    MetaMorpho/curator SUPPLY VAULT — STEAKUSDC, GTUSDCP, SENPYUSD… — NOT volatile collateral); we
    classify it VANILLA_STABLE so these vault wrappers do NOT masquerade as 'exotic long-tail'
    collateral (the single biggest honesty trap in the /pools data — see the de-risk doc).
    Otherwise the market takes its RISKIEST leg's kind (precedence above). An empty/garbage symbol
    fails CLOSED to UNKNOWN (treated as long-tail / illiquid — never silently 'vanilla')."""
    legs = _legs(symbol)
    if not legs:
        return CollateralKind.UNKNOWN
    if (exposure or "").lower() == "multi":
        return CollateralKind.LP
    # A Pendle PT is a PT wrapper REGARDLESS of its underlying: "PT-weETH-…" is a PT (maturity/
    # oracle-gated, thin Pendle DEX) — that PT structure is what gates the exit, not the LRT inside.
    # So a leading "PT" leg classifies the whole market as PT before per-leg risk precedence.
    if legs[0] == _PT_PREFIX or legs[0] in _PT_TOKENS:
        return CollateralKind.PT
    # DeFiLlama's stablecoin flag: a stable-denominated single-asset row is a stable position
    # (a curator supply-vault share, not volatile collateral) → NOT long-tail. Only when the symbol
    # ISN'T already an LRT/BTC/ETH leg (a stable-pegged LST should still classify by its leg).
    if stablecoin is True:
        kinds_chk = {_classify_leg(leg) for leg in legs}
        if not (kinds_chk & {CollateralKind.LRT, CollateralKind.VANILLA_BTC,
                             CollateralKind.VANILLA_ETH}):
            return CollateralKind.VANILLA_STABLE
    kinds = {_classify_leg(leg) for leg in legs}
    for k in _KIND_PRECEDENCE:
        if k in kinds:
            return k
    return CollateralKind.UNKNOWN


@dataclass
class IsolatedMarket:
    """One isolated lending market, read-only from DeFiLlama /pools. The borrow-side fields
    (LLTV / liquidation_penalty / borrowed_usd / at-risk debt) are NOT in /pools for Morpho/Euler;
    they are RPC/subgraph-gated and surfaced as data_gaps. `liquidation_penalty_bps` here is the
    DOCUMENTED per-protocol/kind incentive constant (flagged), not a live read."""
    protocol: str
    chain: str
    symbol: str
    collateral_kind: CollateralKind
    tvl_usd: float
    supply_apy_pct: Optional[float]
    exposure: str                       # "single" | "multi"
    pool_id: str
    liquidation_penalty_bps: float      # DOCUMENTED incentive (bps), per protocol/kind — not live
    underlying_tokens: Tuple[str, ...] = ()
    data_gaps: List[str] = field(default_factory=list)

    @property
    def is_long_tail(self) -> bool:
        return self.collateral_kind.is_long_tail


# ── documented liquidation-incentive constants (NOT a live read — flagged everywhere) ──────────
# Morpho Blue's liquidation incentive factor (LIF) is a deterministic function of the market LLTV:
#   LIF = min(M, 1/(BETA*LLTV + (1-BETA)))   with M=1.15, BETA=0.3 (Morpho Blue whitepaper).
# Without per-market LLTV from /pools we cannot compute the exact LIF, so we use DOCUMENTED
# representative penalties per collateral kind (lower LLTV / riskier collateral → larger incentive).
# These are transparent assumptions for an OPPORTUNITY-SIZING estimate, not executable parameters.
_DOC_PENALTY_BPS: Dict[CollateralKind, float] = {
    CollateralKind.VANILLA_STABLE: 50.0,    # tight LLTV, ~0.5% incentive
    CollateralKind.VANILLA_ETH: 100.0,      # ~1%
    CollateralKind.VANILLA_BTC: 100.0,      # ~1%
    CollateralKind.LRT: 500.0,              # ~5% — lower LLTV, larger incentive (depeg-prone)
    CollateralKind.PT: 400.0,               # ~4%
    CollateralKind.LP: 600.0,               # ~6% — must be unwound
    CollateralKind.EXOTIC: 700.0,           # ~7%
    CollateralKind.UNKNOWN: 700.0,          # fail-CLOSED to a high (uncertain) penalty
}


def documented_penalty_bps(kind: CollateralKind) -> float:
    """Documented representative liquidation incentive (bps) for a collateral kind. Flagged as an
    assumption — the live per-market LIF needs the market LLTV (RPC/subgraph)."""
    return _DOC_PENALTY_BPS.get(kind, _DOC_PENALTY_BPS[CollateralKind.UNKNOWN])


# ── /pools fetch + validate (fail-CLOSED) ─────────────────────────────────────────────────────
def _validate_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"liquidator pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise ValueError(f"liquidator pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("liquidator pools: 'data' missing or not a list")
    return data


class MarketMonitor:
    """Read-only index of Morpho Blue + Euler V2 isolated markets. Inject `fetcher` (url->json) in
    tests; the real one hits the keyless DeFiLlama /pools. Fail-CLOSED: a fetch/parse failure
    RAISES (we never fabricate a market list); a single malformed pool row is SKIPPED."""

    def __init__(self, fetcher: Optional[Fetcher] = None, projects: Tuple[str, ...] = TARGET_PROJECTS):
        if fetcher is None:
            from spa_core.strategy_lab.data._http import http_fetch
            fetcher = http_fetch
        self._fetch = fetcher
        self._projects = tuple(projects)

    def _pools(self) -> List[dict]:
        return _validate_pools(self._fetch(POOLS_URL))

    def build_market(self, pool: dict) -> Optional[IsolatedMarket]:
        """One /pools row → IsolatedMarket, or None if it is not a target-protocol market / is
        malformed. Fail-CLOSED on the classification (UNKNOWN → treated long-tail)."""
        if not isinstance(pool, dict):
            return None
        proj = pool.get("project")
        if proj not in self._projects:
            return None
        symbol = pool.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return None  # cannot classify a market with no symbol — skip (don't fabricate)
        tvl = pool.get("tvlUsd")
        tvl = float(tvl) if isinstance(tvl, (int, float)) and tvl >= 0 else 0.0
        exposure = pool.get("exposure") if isinstance(pool.get("exposure"), str) else "single"
        stablecoin = pool.get("stablecoin") if isinstance(pool.get("stablecoin"), bool) else None
        kind = classify_collateral(symbol, exposure, stablecoin)
        apy = pool.get("apyBase")
        supply_apy = float(apy) if isinstance(apy, (int, float)) else None
        underlying = tuple(
            str(t) for t in (pool.get("underlyingTokens") or []) if isinstance(t, str)
        )

        gaps: List[str] = [
            "LLTV / liquidation_penalty not in /pools for Morpho/Euler → DOCUMENTED constant used",
            "borrowed_usd / utilization not in /pools at market level → RPC/subgraph-gated",
            "at-risk (near-liquidation) positions need per-borrower health factors → RPC-gated",
            "DeFiLlama /pools mixes MetaMorpho curator SUPPLY VAULTS with collateral markets; the "
            "stablecoin flag is used to keep stable-vault shares out of the long-tail",
        ]
        if kind == CollateralKind.UNKNOWN:
            gaps.append(f"collateral symbol {symbol!r} unclassified → fail-CLOSED to long-tail")

        return IsolatedMarket(
            protocol=str(proj),
            chain=str(pool.get("chain") or "unknown"),
            symbol=symbol.strip(),
            collateral_kind=kind,
            tvl_usd=round(tvl, 2),
            supply_apy_pct=supply_apy,
            exposure=exposure,
            pool_id=str(pool.get("pool") or f"{proj}:{symbol}"),
            liquidation_penalty_bps=documented_penalty_bps(kind),
            underlying_tokens=underlying,
            data_gaps=gaps,
        )

    def build_markets(self, pools: Optional[List[dict]] = None) -> List[IsolatedMarket]:
        """All target-protocol markets, deterministically sorted by (protocol, chain, -tvl, symbol).
        One /pools fetch unless `pools` is injected. Fail-CLOSED: a fetch failure propagates."""
        rows = pools if pools is not None else self._pools()
        markets: List[IsolatedMarket] = []
        for row in rows:
            m = self.build_market(row)
            if m is not None:
                markets.append(m)
        markets.sort(key=lambda m: (m.protocol, m.chain, -m.tvl_usd, m.symbol))
        return markets

    def summary(self, markets: List[IsolatedMarket]) -> Dict[str, object]:
        """Aggregate counts / TVL for the report header."""
        by_kind: Dict[str, Dict[str, float]] = {}
        long_tail_tvl = 0.0
        total_tvl = 0.0
        for m in markets:
            k = m.collateral_kind.value
            slot = by_kind.setdefault(k, {"count": 0, "tvl_usd": 0.0})
            slot["count"] += 1
            slot["tvl_usd"] += m.tvl_usd
            total_tvl += m.tvl_usd
            if m.is_long_tail:
                long_tail_tvl += m.tvl_usd
        return {
            "n_markets": len(markets),
            "n_long_tail": sum(1 for m in markets if m.is_long_tail),
            "total_tvl_usd": round(total_tvl, 2),
            "long_tail_tvl_usd": round(long_tail_tvl, 2),
            "long_tail_tvl_share": round(long_tail_tvl / total_tvl, 4) if total_tvl > 0 else 0.0,
            "by_kind": {k: {"count": int(v["count"]), "tvl_usd": round(v["tvl_usd"], 2)}
                        for k, v in sorted(by_kind.items())},
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
