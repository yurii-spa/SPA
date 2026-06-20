"""Aave V3 adapter (T1 tier) — read-only T1 anchor, live DeFiLlama feed only.

SPA-V405: introduced as the **T1 anchor** that closes the structural 20% cash
drag in the allocator. Four T2 adapters capped at 20% each can only deploy 80%
of capital; a T1 protocol capped at 40% gives the allocator headroom to fill the
remainder instead of parking it in 0%-yield cash.

Like the other live adapters (SPA-V398), this reports ``status="error"`` /
``apy=None`` whenever the DeFiLlama feed is unavailable — it **never** returns a
mock value. ``get_yield_info().apy`` is a decimal (e.g. ``0.052`` == 5.2%); the
orchestrator converts it to a percentage.

This module is strictly read-only / advisory: it never touches capital and is
NOT imported by ``execution/``, ``feed_health/`` or the deterministic risk
agents.

MP-1548 (v11.64) improvements:
  - Instance-level APY cache (5-minute TTL) to reduce DeFiLlama calls.
  - Supply-rate / borrow-rate separation via DeFiLlama apyBase / apyReward.
  - Utilization-rate monitoring: is_utilization_safe() warns when pool
    utilization exceeds 90% (APY spike risk at high utilization).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from spa_core.utils.errors import safe_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MP-1548: Utilization monitoring threshold
# ---------------------------------------------------------------------------

#: Pool utilization above this level → APY spike risk; warns operator.
UTILIZATION_WARNING_THRESHOLD: float = 0.90

#: Instance-level APY cache TTL (seconds) — avoids repeated calls within a cycle.
_CACHE_TTL: float = 300.0  # 5 minutes


class AaveV3Adapter(BaseAdapter):
    """Read-only DeFiLlama feed for the Aave V3 USDC market on Ethereum (T1).

    MP-1548 additions:
      - ``_fetch_cached()`` — 5-min instance cache over ``fetch()``.
      - ``get_supply_rate()`` — base supply APY (apyBase) as decimal.
      - ``get_borrow_rate()`` — variable borrow APY (apyBaseBorrow) as decimal.
      - ``get_utilization()`` — estimated utilization rate in [0, 1].
      - ``is_utilization_safe()`` — True when utilization < 90%.
    """

    PROTOCOL = "aave_v3"
    DEFILLAMA_PROJECT = "aave-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Ethereum"
    RISK_SCORE = 0.20  # T1 anchor — lowest-risk whitelisted protocol.

    # SPA-V412: instant exit. Aave V3 USDC is a liquid supply position —
    # withdrawals settle in the same block (subject only to transient pool
    # utilization), so the declared exit latency is 0h.
    EXIT_LATENCY_HOURS = 0.0

    TIER = "T1"
    T1_CAP = 0.40  # max 40% of portfolio in this single T1 protocol.

    # Stable identifier used by downstream consumers / dashboards.
    pool_id = "aave-v3-usdc-ethereum"

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()
        # MP-1548: instance-level cache
        self._cache_data: Optional[dict] = None
        self._cache_ts: float = 0.0

    # ── Live feed (unchanged from SPA-V398) ──────────────────────────────

    def fetch(self) -> dict:
        """Return a flat status dict from the live feed. Never raises, never mocks.

        ``apy`` is a **decimal** (orchestrator converts to a percentage). On any
        failure ``status="error"``, ``apy=None`` and ``live_data=False``.
        """
        record: dict = {
            "pool_id": self.pool_id,
            "protocol": self.PROTOCOL,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "status": "error",
            "error": "live_feed_unavailable",
            "live_data": False,
            "source": "defillama",
            "ts": time.time(),
        }
        apy = safe_call(
            self.feed.get_apy,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=True, logger_name=f"spa.{self.PROTOCOL}",
        )
        tvl = safe_call(
            self.feed.get_tvl,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=False,
        )

        record["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        if not isinstance(apy, (int, float)):
            logger.warning(
                "%s: DeFiLlama APY unavailable — reporting no live data", self.PROTOCOL
            )
            return record

        record["apy"] = float(apy)
        record["status"] = "ok"
        record["error"] = None
        record["live_data"] = True
        return record

    def get_apy(self) -> Optional[float]:
        """Return the live APY as a decimal, or ``None`` if no live data."""
        return self.fetch().get("apy")

    def get_yield_info(self) -> YieldInfo:
        data = self.fetch()
        tvl = data.get("tvl")
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=data.get("apy"),
            tvl_usd=float(tvl) if isinstance(tvl, (int, float)) else None,
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── MP-1548: Instance-level cache ─────────────────────────────────────

    def _fetch_cached(self) -> dict:
        """Return a cached fetch() result, refreshing if older than _CACHE_TTL.

        Reduces redundant DeFiLlama calls when the adapter is polled multiple
        times within a single cycle (e.g., for APY + utilization + supply rate
        in one pass).  Cache is instance-local — isolated per adapter object.
        """
        now = time.time()
        if self._cache_data is None or (now - self._cache_ts) >= _CACHE_TTL:
            self._cache_data = self.fetch()
            self._cache_ts = now
        return self._cache_data

    def invalidate_cache(self) -> None:
        """Force the next _fetch_cached() call to hit the live feed."""
        self._cache_data = None
        self._cache_ts = 0.0

    # ── MP-1548: Supply / borrow rate separation ──────────────────────────

    def get_supply_rate(self) -> Optional[float]:
        """Return the base supply APY (apyBase) as a decimal, or None.

        DeFiLlama ``apyBase`` is the underlying protocol supply rate
        (excluding any token rewards).  For Aave V3, this is the variable
        lending rate paid to depositors before reward overlays.

        Returns a decimal (e.g. 0.035 = 3.5%) or None if unavailable.
        """
        try:
            pool = safe_call(
                self.feed.get_pool,
                self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
                default=None, log_error=False,
            )
            if pool is None:
                return None
            apy_base = pool.get("apyBase")
            if isinstance(apy_base, (int, float)):
                return float(apy_base) / 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: get_supply_rate error: %s", self.PROTOCOL, exc)
        return None

    def get_borrow_rate(self) -> Optional[float]:
        """Return the variable borrow APY (apyBaseBorrow) as a decimal, or None.

        DeFiLlama ``apyBaseBorrow`` is the cost of borrowing from the pool.
        High borrow rate + high utilization → APY spike risk for suppliers.

        Returns a decimal (e.g. 0.052 = 5.2%) or None if unavailable.
        """
        try:
            pool = safe_call(
                self.feed.get_pool,
                self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
                default=None, log_error=False,
            )
            if pool is None:
                return None
            # DeFiLlama field is apyBaseBorrow (negative convention on some pools)
            borrow = pool.get("apyBaseBorrow")
            if isinstance(borrow, (int, float)):
                return abs(float(borrow)) / 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: get_borrow_rate error: %s", self.PROTOCOL, exc)
        return None

    # ── MP-1548: Utilization monitoring ──────────────────────────────────

    def get_utilization(self) -> float:
        """Return current pool utilization rate as a float in [0, 1].

        Estimated from the supply / borrow APY split from DeFiLlama.
        When borrow_rate > 0 and supply_rate > 0, utilization can be
        approximated as supply_rate / borrow_rate (simplified Aave model).

        Falls back to 0.0 when either rate is unavailable — interpreting
        missing data as "not at risk" rather than blocking the cycle.
        """
        try:
            supply = self.get_supply_rate()
            borrow = self.get_borrow_rate()
            if (
                isinstance(supply, float) and isinstance(borrow, float)
                and borrow > 0.0
            ):
                utilization = supply / borrow
                return max(0.0, min(utilization, 1.0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: get_utilization error: %s", self.PROTOCOL, exc)
        return 0.0

    def is_utilization_safe(self) -> bool:
        """True if pool utilization is below the warning threshold (90%).

        Returns True (safe) when utilization data is unavailable — fail-open
        policy prevents false positives from blocking legitimate cycles.
        """
        util = self.get_utilization()
        if util >= UTILIZATION_WARNING_THRESHOLD:
            logger.warning(
                "%s: HIGH utilization %.1f%% ≥ %.0f%% — APY spike risk",
                self.PROTOCOL,
                util * 100.0,
                UTILIZATION_WARNING_THRESHOLD * 100.0,
            )
            return False
        return True

    def utilization_status(self) -> dict:
        """Return a dict summarising current utilization state.

        Returns
        -------
        dict
            ``{utilization, safe, threshold, supply_rate, borrow_rate}``
        """
        supply = self.get_supply_rate()
        borrow = self.get_borrow_rate()
        util = self.get_utilization()
        return {
            "utilization": util,
            "safe": util < UTILIZATION_WARNING_THRESHOLD,
            "threshold": UTILIZATION_WARNING_THRESHOLD,
            "supply_rate": supply,
            "borrow_rate": borrow,
        }

    # end of class
