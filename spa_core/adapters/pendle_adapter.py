"""Pendle Finance adapter (T2/T3 tier) — read-only, live Pendle API feed.

Wraps :class:`spa_core.adapters.pendle_pt.PendlePTAdapter` (the low-level
Pendle V2 REST client) in the :class:`BaseAdapter` interface so Pendle can be
plugged into ``ADAPTER_REGISTRY`` and the adapter orchestrator alongside
Aave, Compound, Morpho, Yearn, Euler and Maple.

Design decisions
================
* **Source**: Pendle V2 REST API (``api-v2.pendle.finance``). No DeFiLlama
  feed — Pendle PT markets are fixed-rate instruments whose implied APY is
  reported directly by the Pendle API; DeFiLlama does not surface per-maturity
  PT APYs with the precision needed.
* **Stablecoin filter**: Only USD-stable underlying assets are eligible.
  ``STABLECOIN_FILTER`` is the canonical keyword set; matching is
  case-insensitive substring.
* **Tier classification** is based on TVL of the *best* market:
  - TVL >= $100 M → T2
  - TVL >= $20 M  → T3
  - TVL < $20 M  → skipped (not eligible for the allocator)
* **Fallback / cache**: The last successful API response is stored in
  ``_cache`` (a list of raw market dicts). On any network failure the cached
  data is used; on the very first call with no cache the adapter returns
  ``apy=None`` and an empty market list — it NEVER returns a synthetic mock.
* **Atomic writes**: this module never writes any files; the feed is read-only.
* **stdlib only**: zero external dependencies (``urllib.request``, ``json``,
  ``datetime``).

MP-201 — Pendle PT read-only APY feed.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .pendle_pt import (
    PENDLE_MIN_TVL_USD,
    PendlePTAdapter as _PendlePTAdapter,
    PendleMarketData,
    _is_stablecoin,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PROTOCOL = "pendle"

# Stablecoin keywords used for market filtering (case-insensitive substring).
STABLECOIN_FILTER: frozenset[str] = frozenset(
    {"sUSDe", "yvUSDC", "USDC", "aUSDC", "USDT", "DAI", "crvUSD", "GHO", "FRAX"}
)

# Tier thresholds (TVL in USD).
_TIER_T2_TVL = 100_000_000.0   # >= $100M → T2
_TIER_T3_TVL = 20_000_000.0    # >= $20M  → T3

# Minimum days to maturity accepted for a new position.
_MIN_DAYS_TO_MATURITY = 7
# Maximum days to maturity accepted for a new position.
_MAX_DAYS_TO_MATURITY = 365

# Default minimum APY (decimal) for get_best_pt.
_DEFAULT_MIN_APY_DECIMAL = 0.05   # 5%
# Default minimum TVL for get_best_pt.
_DEFAULT_MIN_TVL = 500_000.0       # $500K

# Risk score — slightly higher than Morpho/Yearn because PT positions are
# fixed-term instruments with maturity risk and secondary-market liquidity
# risk on early exit.
RISK_SCORE = 0.45

# SPA-V412: exit latency.  A Pendle PT held to maturity redeems 1:1 — but
# an *early* exit requires selling on the AMM at market price (discount
# risk).  The effective latency to a guaranteed full-par exit is the
# remaining days to maturity.  We declare 168h (7 days) as a conservative
# practical floor for the current filtered basket (min 7d to maturity);
# actual latency is days_to_maturity × 24h but that is dynamic.
EXIT_LATENCY_HOURS = 168.0


# ── Tier helper ───────────────────────────────────────────────────────────────

def _classify_tier(tvl_usd: float) -> Optional[str]:
    """Return "T2", "T3", or None (skip) based on TVL."""
    if tvl_usd >= _TIER_T2_TVL:
        return "T2"
    if tvl_usd >= _TIER_T3_TVL:
        return "T3"
    return None  # below minimum TVL — not eligible


# ── Adapter ───────────────────────────────────────────────────────────────────

class PendleAdapter(BaseAdapter):
    """Read-only adapter for Pendle Finance PT markets.

    Compatible with :data:`ADAPTER_REGISTRY` — implements
    :meth:`get_apy` and :meth:`get_yield_info` from :class:`BaseAdapter`.

    Extra methods beyond the base interface:
    * :meth:`get_markets`  — all eligible stablecoin markets as plain dicts.
    * :meth:`get_best_pt`  — single best PT by implied APY.
    * :meth:`maturity_days`— days until maturity for a market dict.
    """

    PROTOCOL = PROTOCOL
    RISK_SCORE = RISK_SCORE
    EXIT_LATENCY_HOURS = EXIT_LATENCY_HOURS

    def __init__(
        self,
        asset: str = "USDC",
        chain_id: int = 1,
        timeout: int = 10,
        max_retries: int = 1,
        *,
        _pendle_pt_adapter: Optional[_PendlePTAdapter] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = "T2"   # default; may be updated after first live fetch
        self._chain_id = chain_id
        self._timeout = timeout
        self._max_retries = max_retries
        # Injected adapter (for tests) or a fresh one.
        self._pt: _PendlePTAdapter = _pendle_pt_adapter or _PendlePTAdapter(
            chain_id=chain_id,
            timeout=timeout,
            max_retries=max_retries,
        )
        # Cache: list of PendleMarketData from the last successful API call.
        self._cache: list[PendleMarketData] = []
        # Timestamp of the last successful fetch (monotonic).
        self._cache_ts: float = 0.0

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_eligible(self) -> list[PendleMarketData]:
        """Fetch & filter eligible stablecoin PT markets.

        Uses the underlying PendlePTAdapter with the standard SPA filters
        (not-expired, TVL >= PENDLE_MIN_TVL_USD, maturity window, stablecoin).
        Populates ``self._cache`` on success; on failure returns the cache.
        Never raises.
        """
        try:
            markets = self._pt.get_top_markets(
                min_tvl_usd=PENDLE_MIN_TVL_USD,
                max_days_to_maturity=_MAX_DAYS_TO_MATURITY,
                min_days_to_maturity=_MIN_DAYS_TO_MATURITY,
                stablecoin_only=True,
            )
            if markets:
                self._cache = markets
                self._cache_ts = time.monotonic()
            return list(self._cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: fetch_eligible raised %s — using cache", self.PROTOCOL, exc)
            return list(self._cache)

    def _market_to_dict(self, m: PendleMarketData) -> dict:
        """Convert a PendleMarketData to the public market dict schema."""
        tvl = m.tvl_usd
        tier = _classify_tier(tvl) or "T3"
        return {
            "market_address": m.market_address,
            "pt_address": "",          # not surfaced by the /markets endpoint
            "symbol": m.name,
            "implied_apy": m.implied_apy,   # % (e.g. 8.9 for 8.9%)
            "maturity": m.maturity_date,
            "tvl_usd": tvl,
            "volume_24h_usd": m.liquidity_usd,  # proxy: AMM liquidity
            "tier": tier,
            "days_to_maturity": m.days_to_maturity,
            "underlying_asset": m.underlying_asset,
            "is_expired": m.is_expired,
        }

    # ── BaseAdapter interface ─────────────────────────────────────────────────

    def get_apy(self, token: str = "") -> Optional[float]:  # type: ignore[override]
        """Return the best eligible implied APY as a **decimal** (e.g. 0.089),
        or ``None`` if no live data is available.

        When ``token`` is supplied, returns the APY for the best market whose
        symbol contains ``token`` (case-insensitive); if no match, returns the
        global best.

        This is the primary BaseAdapter interface method.
        """
        markets = self._fetch_eligible()
        if not markets:
            return None
        if token:
            tl = token.lower()
            candidates = [m for m in markets if tl in m.name.lower()
                          or tl in m.underlying_asset.lower()]
            if candidates:
                pct = candidates[0].implied_apy
                return round(pct / 100.0, 8)
        # Return global best
        pct = markets[0].implied_apy
        return round(pct / 100.0, 8)

    def get_yield_info(self) -> YieldInfo:
        """Return a :class:`YieldInfo` for the best eligible Pendle PT market.

        ``apy`` is a decimal (e.g. 0.089 == 8.9%).
        Returns ``apy=None`` when no live data is available.
        """
        markets = self._fetch_eligible()
        if not markets:
            return YieldInfo(
                protocol=self.PROTOCOL,
                asset=self.asset,
                apy=None,
                tvl_usd=None,
                tier=self.tier,
                risk_score=self.RISK_SCORE,
                exit_latency_hours=self.EXIT_LATENCY_HOURS,
            )

        best = markets[0]
        tvl = best.tvl_usd
        tier = _classify_tier(tvl) or "T3"
        self.tier = tier  # update instance tier based on live data

        apy_decimal = round(best.implied_apy / 100.0, 8)
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=apy_decimal,
            tvl_usd=tvl,
            tier=tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── Extra public methods ──────────────────────────────────────────────────

    def get_markets(self) -> list[dict]:
        """Return all eligible stablecoin PT markets as plain dicts.

        Each dict has the keys:
          market_address, pt_address, symbol, implied_apy (%), maturity,
          tvl_usd, volume_24h_usd, tier, days_to_maturity,
          underlying_asset, is_expired.

        Returns ``[]`` if no markets pass the filters or the API is down.
        Markets are sorted by implied_apy descending.
        """
        markets = self._fetch_eligible()
        result = []
        for m in markets:
            d = self._market_to_dict(m)
            # Only include T2 / T3 (skip below-minimum TVL)
            if _classify_tier(m.tvl_usd) is not None:
                result.append(d)
        return result

    def get_best_pt(
        self,
        min_tvl_usd: float = _DEFAULT_MIN_TVL,
        min_apy: float = _DEFAULT_MIN_APY_DECIMAL,
    ) -> Optional[dict]:
        """Return the best PT market dict by implied_apy, or ``None``.

        Parameters
        ----------
        min_tvl_usd : float
            Minimum TVL in USD (default: $500K).
        min_apy : float
            Minimum implied APY as a **decimal** (default: 0.05 == 5%).
        """
        markets = self._fetch_eligible()
        min_apy_pct = min_apy * 100.0  # convert decimal to percentage
        candidates = [
            m for m in markets
            if m.tvl_usd >= min_tvl_usd and m.implied_apy >= min_apy_pct
        ]
        if not candidates:
            return None
        return self._market_to_dict(candidates[0])

    @staticmethod
    def maturity_days(market: dict) -> int:
        """Return days until maturity for a market dict from :meth:`get_markets`.

        Returns 0 if the maturity date is missing, unparseable, or in the past.
        """
        maturity_str = market.get("maturity") or market.get("maturity_date") or ""
        if not maturity_str:
            return 0
        try:
            date_part = str(maturity_str)[:10]
            maturity_date = datetime.date.fromisoformat(date_part)
            delta = (maturity_date - datetime.date.today()).days
            return max(delta, 0)
        except (ValueError, TypeError):
            return 0

    # end of class
