"""
Pendle PT-USDC / PT-crvUSD Fixed-Rate Adapter (T2) — MP-1250.

The plain-stablecoin sibling of :mod:`pendle_pt_susde_adapter`. Tracks a Pendle
**Principal Token** backed by a USD stablecoin (PT-USDC, or PT-crvUSD as a
fallback market), locking in a **fixed yield-to-maturity** — the safe leg of
Pendle, distinct from the speculative YT leg (`pendle_yt`).

Target band: ~6–10% fixed APY.

Tier  : T2  (fixed rate, but Pendle AMM + underlying protocol smart-contract risk)
Domain: READ-ONLY / advisory — no on-chain execution, no state writes.
Source: DeFiLlama yields API (project "pendle", USDC/crvUSD PT pool), with a
        static FALLBACK_APY when the live feed is unavailable.
stdlib: only (urllib via DeFiLlamaFeed). No external deps. LLM FORBIDDEN.

Behavioural rules (same family contract as the sUSDe adapter):
  * TVL floor — a pool below MIN_TVL_USD ($50M) is not eligible.
  * Maturity awareness — within MATURITY_UNWIND_DAYS (30) of maturity the
    effective APY is reported as 0% (position unwinding).
  * Kill switch — fixed APY below ROTATION_APY_FLOOR (5%) flags for rotation.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional, Union

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)

# Underlying symbol candidates DeFiLlama uses for the Pendle USDC/crvUSD PT
# pools. Tried most-specific first; get_pool matches case-insensitively.
_USDC_SYMBOL_CANDIDATES = ("PT-USDC", "USDC", "PT-CRVUSD", "CRVUSD")
_PENDLE_PROJECT = "pendle"


class PendlePTUsdcAdapter(BaseAdapter):
    """Pendle PT-USDC / PT-crvUSD fixed-rate principal token on Ethereum (T2).

    Reports a fixed yield-to-maturity sourced from DeFiLlama, with maturity
    awareness (0% when unwinding) and a sub-Morpho kill switch for rotation.
    APY values returned by :meth:`get_apy` are **decimals** (0.08 == 8%).
    """

    # ── Identity ─────────────────────────────────────────────────────────
    PROTOCOL = "pendle_pt_usdc"
    PROTOCOL_NAME = "Pendle PT-USDC"
    ASSET = "USDC"
    CHAIN = "ethereum"
    CHAIN_ID = 1

    # ── Tier / Risk ──────────────────────────────────────────────────────
    TIER = "T2"
    RESEARCH_ONLY = True
    RISK_SCORE = 0.38  # Pendle AMM + underlying lending protocol risk

    EXIT_LATENCY_HOURS = 24.0  # secondary-market exit via Pendle AMM

    # ── APY parameters (decimals, e.g. 0.08 == 8%) ───────────────────────
    FALLBACK_APY: float = 0.08   # ~8% fixed (mid of 6–10% band)
    MIN_APY: float = 0.01        # 1% floor
    MAX_APY: float = 0.30        # 30% cap

    # ── TVL floor (spec: > $50M minimum) ─────────────────────────────────
    MIN_TVL_USD: float = 50_000_000.0
    TVL_USD: float = 50_000_000.0

    # ── Maturity awareness ───────────────────────────────────────────────
    MATURITY_UNWIND_DAYS: int = 30

    # ── Kill switch ──────────────────────────────────────────────────────
    ROTATION_APY_FLOOR: float = 0.05  # 5%

    def __init__(
        self,
        asset: str = "USDC",
        feed: Optional[DeFiLlamaFeed] = None,
        maturity_date: Optional[Union[str, datetime.date]] = None,
        today: Optional[datetime.date] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()
        self.maturity_date = self._coerce_date(maturity_date)
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
        """Best matching live Pendle USDC/crvUSD pool dict, or ``None``."""
        for symbol in _USDC_SYMBOL_CANDIDATES:
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
        """Raw fixed APY from DeFiLlama as a decimal; FALLBACK_APY on miss."""
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
        """Effective APY (decimal); 0.0 when unwinding (< 30 days to maturity)."""
        if self.is_unwinding():
            return 0.0
        return self.safe_apy()

    # ── Eligibility / kill switch ────────────────────────────────────────

    def tvl_ok(self) -> bool:
        """True when live TVL meets the $50M floor."""
        return self.fetch_tvl() >= self.MIN_TVL_USD

    def should_rotate(self) -> bool:
        """Kill switch: rotate when fixed APY < 5% (sub-Morpho) or unwinding."""
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
