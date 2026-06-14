"""DeclarativeAdapter — a ProtocolAdapter built from a manifest (SPA-V417 / MP-204).

Implements the full :class:`~spa_core.adapter_sdk.contract.ProtocolAdapter`
contract from a validated :class:`~spa_core.adapter_sdk.manifest.AdapterManifest`
on top of the EXISTING DeFiLlama feed client
(:class:`spa_core.adapters.defillama_feed.DeFiLlamaFeed` — reused, not
duplicated: all HTTP/caching/sanity logic stays in one place).

Honesty rules (SPA-V398 / SPA-BL-011):

* a dead/blocked feed (e.g. no egress to ``yields.llama.fi``) degrades to
  ``fetch_pools() == []`` and ``health()["status"] in {"degraded", "error"}`` —
  it never raises and never substitutes mock data;
* quality gates (``min_tvl_usd`` / ``stable_only`` / ``max_apy_pct``) only
  FILTER pools out; they never invent or adjust values;
* strictly read-only: no capital movement, no imports from ``execution/``,
  ``risk/``, ``allocator/`` or feed-health.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .contract import PoolInfo
from .manifest import ILLIQUID_THRESHOLD_HOURS, AdapterManifest, _default_profile

logger = logging.getLogger(__name__)

# Symbols accepted by the ``stable_only`` quality gate. Multi-token DeFiLlama
# symbols ("DAI-USDC-USDT") qualify when EVERY leg is a known stablecoin.
STABLE_SYMBOLS = frozenset(
    {
        "USDC", "USDT", "DAI", "USDS", "SUSDS", "SDAI", "GHO", "FRAX",
        "LUSD", "SUSD", "USDE", "SUSDE", "PYUSD", "TUSD", "USDP", "USDM",
        "USD0", "FDUSD", "BUSD", "CRVUSD", "DOLA", "MIM", "USDA", "USDX",
    }
)


def is_stable_symbol(symbol: str) -> bool:
    """True when every leg of a (possibly multi-token) symbol is a stablecoin."""
    if not isinstance(symbol, str) or not symbol.strip():
        return False
    legs = [leg for leg in symbol.upper().replace("_", "-").split("-") if leg]
    return bool(legs) and all(leg in STABLE_SYMBOLS for leg in legs)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeclarativeAdapter:
    """Manifest-driven ProtocolAdapter over the shared DeFiLlama feed."""

    SOURCE = "defillama"

    def __init__(self, manifest: AdapterManifest, feed=None):
        self.manifest = manifest
        self.name = manifest.name
        self.tier = manifest.tier
        self.cap = manifest.cap
        self._feed = feed  # lazily constructed so tests can inject a fake
        # health bookkeeping
        self._last_fetch_ts: Optional[str] = None
        self._last_status: str = "error"
        self._last_error: Optional[str] = "not_fetched_yet"
        self._last_pool_count: int = 0
        self._expected_pools: int = len(manifest.chains) * len(manifest.symbols)

    # --- feed (reuses the existing client; lazy so injection needs no HTTP) ---

    @property
    def feed(self):
        if self._feed is None:
            from spa_core.adapters.defillama_feed import DeFiLlamaFeed

            self._feed = DeFiLlamaFeed()
        return self._feed

    # --- contract: fetch_pools -------------------------------------------------

    def fetch_pools(self) -> List[PoolInfo]:
        """Live pools passing the manifest quality gates. Never raises, never mocks."""
        m = self.manifest
        gates = m.quality_gates
        fetched_at = _utc_now_iso()
        self._last_fetch_ts = fetched_at

        pools: List[PoolInfo] = []
        errors: List[str] = []

        for chain in m.chains:
            for symbol in m.symbols:
                try:
                    rec = self.feed.fetch_pool(
                        m.defillama_protocol_id,
                        symbol,
                        chain,
                        min_tvl_usd=gates.min_tvl_usd,
                    )
                except Exception as exc:  # noqa: BLE001 - honest degradation
                    logger.warning(
                        "%s: feed raised for %s/%s on %s: %s",
                        self.name, m.defillama_protocol_id, symbol, chain, exc,
                    )
                    errors.append(f"{chain}/{symbol}: {type(exc).__name__}: {exc}")
                    continue
                if not isinstance(rec, dict):
                    continue  # feed unavailable or no qualifying live pool

                apy = rec.get("apy")
                tvl = rec.get("tvl")
                apy = float(apy) if isinstance(apy, (int, float)) else None
                tvl = float(tvl) if isinstance(tvl, (int, float)) else None

                # Quality gates — filter only, never adjust (belt-and-braces:
                # min_tvl is also passed to the feed, but an injected feed may
                # ignore the parameter).
                if tvl is not None and tvl < gates.min_tvl_usd:
                    continue
                if gates.stable_only and not is_stable_symbol(symbol):
                    continue
                if (
                    gates.max_apy_pct is not None
                    and apy is not None
                    and apy > gates.max_apy_pct
                ):
                    continue

                pools.append(
                    PoolInfo(
                        protocol=self.name,
                        pool_id=f"{self.name}-{symbol}-{chain}".lower(),
                        chain=chain,
                        symbol=symbol,
                        apy_pct=apy,
                        tvl_usd=tvl,
                        tier=self.tier,
                        defillama_pool_id=(
                            rec.get("pool_id") if isinstance(rec.get("pool_id"), str) else None
                        ),
                        exit_latency_hours=m.exit_latency_hours,
                        source=self.SOURCE,
                        fetched_at=fetched_at,
                    )
                )

        self._last_pool_count = len(pools)
        if errors:
            self._last_error = "; ".join(errors)
        elif not pools:
            self._last_error = "live_feed_unavailable_or_no_qualifying_pools"
        else:
            self._last_error = None

        if pools and len(pools) >= self._expected_pools:
            self._last_status = "ok"
        elif pools:
            self._last_status = "degraded"
        else:
            self._last_status = "error"
        return pools

    # --- contract: exit_latency ------------------------------------------------

    def exit_latency(self) -> Dict[str, object]:
        """Declarative exit profile (style of ``exit_latency_policy.py``)."""
        hours = self.manifest.exit_latency_hours
        return {
            "protocol": self.name,
            "exit_latency_hours": hours,
            "bucket": _default_profile(hours),
            "profile": self.manifest.exit_latency_profile,
            "threshold_hours": ILLIQUID_THRESHOLD_HOURS,
        }

    # --- contract: health --------------------------------------------------------

    def health(self) -> Dict[str, object]:
        """Health report; performs one lazy fetch if none has happened yet."""
        if self._last_fetch_ts is None:
            self.fetch_pools()
        return {
            "protocol": self.name,
            "status": self._last_status,
            "last_fetch_ts": self._last_fetch_ts,
            "source": self.SOURCE,
            "pools_live": self._last_pool_count,
            "pools_expected": self._expected_pools,
            "tier": self.tier,
            "error": self._last_error,
        }
