"""
Pendle PT-sUSDe Fixed-Rate Adapter (T2) — MP-1250.

Pendle **Principal Tokens (PT)** are the *safe* leg of Pendle: a PT is bought at
a discount to par and redeems 1:1 for its underlying at maturity, locking in a
**fixed yield-to-maturity** with no exposure to floating yield speculation. This
is the deliberate opposite of the **YT (Yield Token)** leg — `pendle_yt` /
`s7_pendle_yt_aggressive` — which is the amplified, volatile part of Pendle.

This adapter tracks Pendle **PT-sUSDe** (Ethena staked-USDe principal token),
typically ~8–12% fixed APY.

Tier  : T2  (fixed rate, but Pendle AMM + Ethena smart-contract risk)
Domain: READ-ONLY / advisory — no on-chain execution, no state writes.
Source: DeFiLlama yields API (project "pendle", sUSDe PT pool), with a static
        FALLBACK_APY when the live feed is unavailable. Never invents live data
        beyond the declared fallback.
stdlib: only (urllib via DeFiLlamaFeed). No external deps. LLM FORBIDDEN.

Behavioural rules (per spec):
  * TVL floor — a pool below MIN_TVL_USD ($50M) is not eligible.
  * Maturity awareness — when days-to-maturity < MATURITY_UNWIND_DAYS (30),
    the position is unwinding, so the *effective* APY is reported as 0%.
  * Kill switch — when the live fixed APY drops below ROTATION_APY_FLOOR (5%,
    i.e. below a typical Morpho floor), `should_rotate()` flags the position
    for rotation out of PT.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional, Union

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)

# Underlying symbol candidates DeFiLlama uses for the Pendle sUSDe PT pool.
# get_pool matches symbol case-insensitively; we try the most specific first.
_SUSDE_SYMBOL_CANDIDATES = ("PT-SUSDE", "SUSDE")
_PENDLE_PROJECT = "pendle"


class PendlePTSusdeAdapter(BaseAdapter):
    """Pendle PT-sUSDe fixed-rate principal token on Ethereum (T2).

    Reports a fixed yield-to-maturity sourced from DeFiLlama, with maturity
    awareness (0% when unwinding) and a sub-Morpho kill switch for rotation.
    APY values returned by :meth:`get_apy` are **decimals** (0.10 == 10%).
    """

    # ── Identity ─────────────────────────────────────────────────────────
    PROTOCOL = "pendle_pt_susde"
    PROTOCOL_NAME = "Pendle PT-sUSDe"
    ASSET = "sUSDe"
    CHAIN = "ethereum"
    CHAIN_ID = 1

    # ── Tier / Risk ──────────────────────────────────────────────────────
    TIER = "T2"
    RESEARCH_ONLY = True
    RISK_SCORE = 0.42  # Pendle AMM + Ethena synthetic-dollar risk

    # PT early exit is via the Pendle AMM (secondary market) at a discount, not
    # a withdrawal queue. ~24h declared as typical settlement estimate.
    EXIT_LATENCY_HOURS = 24.0

    # ── APY parameters (decimals, e.g. 0.10 == 10%) ──────────────────────
    FALLBACK_APY: float = 0.10   # ~10% fixed (mid of 8–12% band)
    MIN_APY: float = 0.01        # 1% floor (RiskPolicy lower bound)
    MAX_APY: float = 0.30        # 30% cap (RiskPolicy upper bound)

    # ── TVL floor (spec: > $50M minimum) ─────────────────────────────────
    MIN_TVL_USD: float = 50_000_000.0
    TVL_USD: float = 50_000_000.0  # conservative declared default

    # ── Maturity awareness ───────────────────────────────────────────────
    # Below this many days to maturity the PT is unwinding → effective APY 0%.
    MATURITY_UNWIND_DAYS: int = 30

    # ── Kill switch ──────────────────────────────────────────────────────
    # Below this fixed APY the PT no longer beats a typical Morpho floor →
    # flag for rotation.
    ROTATION_APY_FLOOR: float = 0.05  # 5%

    def __init__(
        self,
        asset: str = "sUSDe",
        feed: Optional[DeFiLlamaFeed] = None,
        maturity_date: Optional[Union[str, datetime.date]] = None,
        today: Optional[datetime.date] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()
        self.maturity_date = self._coerce_date(maturity_date)
        # Injectable reference date keeps maturity logic deterministic in tests.
        self._today = today

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_date(
        value: Optional[Union[str, datetime.date]]
    ) -> Optional[datetime.date]:
        if value is None:
            return None
        if isinstance(value, datetime.date):
            return value
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    def _ref_today(self) -> datetime.date:
        return self._today if self._today is not None else datetime.date.today()

    def days_to_maturity(self) -> Optional[int]:
        """Whole days until maturity, or ``None`` when no maturity is known."""
        if self.maturity_date is None:
            return None
        return (self.maturity_date - self._ref_today()).days

    def is_unwinding(self) -> bool:
        """True when within MATURITY_UNWIND_DAYS of maturity (or past it)."""
        days = self.days_to_maturity()
        return days is not None and days < self.MATURITY_UNWIND_DAYS

    # ── Core APY ─────────────────────────────────────────────────────────

    def _find_pool(self) -> Optional[dict]:
        """Best matching live Pendle sUSDe pool dict, or ``None``."""
        for symbol in _SUSDE_SYMBOL_CANDIDATES:
            try:
                pool = self.feed.get_pool(
                    project=_PENDLE_PROJECT, symbol=symbol, chain="Ethereum"
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: feed.get_pool(%s) failed: %s",
                             self.PROTOCOL, symbol, exc)
                pool = None
            if pool is not None:
                return pool
        return None

    def fetch_apy(self) -> float:
        """Raw fixed APY from DeFiLlama as a decimal; FALLBACK_APY on miss.

        Ignores maturity/rotation logic — that is layered on in
        :meth:`get_apy`. Never raises.
        """
        try:
            pool = self._find_pool()
            if pool is not None:
                raw = pool.get("apy")
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    return float(raw) / 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: fetch_apy failed: %s", self.PROTOCOL, exc)
        return self.FALLBACK_APY

    def safe_apy(self) -> float:
        """fetch_apy() clamped to [MIN_APY, MAX_APY] as a decimal."""
        return max(self.MIN_APY, min(self.fetch_apy(), self.MAX_APY))

    def fetch_tvl(self) -> float:
        """Live TVL in USD for the matched pool, or TVL_USD fallback."""
        try:
            pool = self._find_pool()
            if pool is not None:
                tvl = pool.get("tvlUsd")
                if isinstance(tvl, (int, float)) and not isinstance(tvl, bool):
                    return float(tvl)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: fetch_tvl failed: %s", self.PROTOCOL, exc)
        return self.TVL_USD

    def get_apy(self) -> Optional[float]:
        """Effective APY (decimal) the allocator should use.

        Returns **0.0** when the PT is unwinding (< 30 days to maturity),
        otherwise the clamped fixed APY.
        """
        if self.is_unwinding():
            return 0.0
        return self.safe_apy()

    # ── Eligibility / kill switch ────────────────────────────────────────

    def tvl_ok(self) -> bool:
        """True when live TVL meets the $50M floor."""
        return self.fetch_tvl() >= self.MIN_TVL_USD

    def should_rotate(self) -> bool:
        """Kill switch: rotate out of PT when fixed APY < 5% (sub-Morpho).

        Also rotates when the position is unwinding toward maturity.
        """
        if self.is_unwinding():
            return True
        return self.safe_apy() < self.ROTATION_APY_FLOOR

    def is_eligible(self) -> bool:
        """Allocatable only when TVL clears the floor, APY is in-band, the PT
        is not unwinding, and the kill switch is not tripped."""
        if not self.tvl_ok():
            return False
        if self.is_unwinding():
            return False
        if self.should_rotate():
            return False
        apy = self.safe_apy()
        return self.MIN_APY <= apy <= self.MAX_APY

    # ── Normalized output ────────────────────────────────────────────────

    def get_yield_info(self) -> YieldInfo:
        """Return normalized YieldInfo for the orchestrator (effective APY)."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy(),
            tvl_usd=self.fetch_tvl(),
            tier=self.TIER,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    def to_dict(self) -> dict:
        """Full adapter snapshot for dashboards, logs, and tests."""
        raw = self.safe_apy()
        eff = self.get_apy()
        days = self.days_to_maturity()
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "asset": self.ASSET,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "tier": self.TIER,
            "research_only": self.RESEARCH_ONLY,
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "tvl_usd": self.fetch_tvl(),
            "tvl_ok": self.tvl_ok(),
            "min_tvl_usd": self.MIN_TVL_USD,
            "fixed_apy_decimal": raw,
            "fixed_apy_pct": round(raw * 100.0, 4),
            "effective_apy_decimal": eff,
            "effective_apy_pct": round((eff or 0.0) * 100.0, 4),
            "fallback_apy": self.FALLBACK_APY,
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "days_to_maturity": days,
            "is_unwinding": self.is_unwinding(),
            "should_rotate": self.should_rotate(),
            "rotation_apy_floor": self.ROTATION_APY_FLOOR,
            "eligible": self.is_eligible(),
            "ts": time.time(),
        }
