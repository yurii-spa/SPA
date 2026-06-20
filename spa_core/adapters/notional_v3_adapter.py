"""
Notional Finance V3 Fixed-Rate Lending Adapter (T2) — MP-1547.

Notional V3 provides fixed-rate borrowing and lending via fCash tokens on
Ethereum mainnet. Lenders deposit stablecoins and receive a fixed annualised
yield for the duration of the active lending window (quarterly maturities).

Protocol details:
  - TVL: ~$400M (as of May 2026)
  - Audited by ABDK Consulting + Code4rena (2022, 2023)
  - Ethereum mainnet, USDC/DAI/WBTC/ETH markets
  - Fixed-rate yields typically 4–8% APY on USDC in normal conditions
  - DeFiLlama slug: "notional"

Tier: T2 — established protocol (2020), good security record, fixed-rate
complexity warrants T2 over T1.

RESEARCH_ONLY=True: paper-trading validation required before allocation.

Class attributes (conformance checker compatible):
  PROTOCOL, ASSET, CHAIN, TIER, RESEARCH_ONLY, FALLBACK_APY

Exit note: early exit requires selling fCash on the secondary AMM at a
discount vs holding to maturity.  EXIT_LATENCY_HOURS = 24 reflects typical
secondary market depth (not a withdrawal queue).

Stdlib only — no external dependencies. Read-only / advisory. LLM FORBIDDEN.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: DeFiLlama project slug for Notional Finance
_NOTIONAL_PROJECT = "notional"


class NotionalV3Adapter(BaseAdapter):
    """Notional Finance V3 USDC fixed-rate lending on Ethereum (T2).

    APY sourced from DeFiLlama yields API (best available current-quarter rate).
    Falls back to FALLBACK_APY (5.0%) when the feed is unavailable.

    APY note: fixed-rate yields are time-dependent — the best available
    rate across all active quarterly windows is returned.
    """

    # ── Identity ─────────────────────────────────────────────────────────
    PROTOCOL = "notional_v3"
    PROTOCOL_NAME = "Notional Finance V3"
    ASSET = "USDC"
    CHAIN = "ethereum"
    CHAIN_ID = 1

    # ── Tier / Risk ───────────────────────────────────────────────────────
    TIER = "T2"
    RESEARCH_ONLY = True  # paper-trading validation required
    RISK_SCORE = 0.40     # Moderate: fixed-rate protocol complexity,
    #                       liquidity risk at maturity windows

    # Exit note: not a withdrawal queue — fCash positions can be sold via
    # the on-chain AMM at any time, but at a market discount vs maturity.
    # 24h declared as typical secondary market settlement estimate.
    EXIT_LATENCY_HOURS = 24.0

    # ── APY parameters (all as decimals, e.g. 0.050 = 5.0%) ──────────────
    FALLBACK_APY: float = 0.050   # 5.0% fallback
    MAX_APY: float = 0.20         # 20% spike cap (fixed-rate should be stable)
    MIN_APY: float = 0.005        # 0.5% floor

    # ── TVL ───────────────────────────────────────────────────────────────
    TVL_USD: float = 400_000_000.0

    def __init__(
        self,
        asset: str = "USDC",
        feed: Optional[DeFiLlamaFeed] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    # ── Core API ─────────────────────────────────────────────────────────

    def fetch_apy(self) -> float:
        """Fetch best current fixed-rate APY from DeFiLlama as a decimal.

        Searches for Notional USDC pools on Ethereum; returns the highest
        APY (best available quarter window).
        Returns FALLBACK_APY if the feed is unavailable or no match found.
        Never raises.
        """
        try:
            pool = self.feed.get_pool(
                project=_NOTIONAL_PROJECT,
                symbol=self.ASSET,
                chain="Ethereum",
            )
            if pool is not None:
                raw = pool.get("apy")
                if isinstance(raw, (int, float)) and raw is not None:
                    return float(raw) / 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: DeFiLlama fetch_apy failed: %s", self.PROTOCOL, exc)
        return self.FALLBACK_APY

    def safe_apy(self) -> float:
        """Return fetch_apy() clamped to [MIN_APY, MAX_APY] as a decimal."""
        raw = self.fetch_apy()
        return max(self.MIN_APY, min(raw, self.MAX_APY))

    def get_apy(self) -> Optional[float]:
        """BaseAdapter contract: current APY as decimal, or None if no data."""
        return self.safe_apy()

    def get_yield_info(self) -> YieldInfo:
        """Return normalized YieldInfo for the orchestrator."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.safe_apy(),
            tvl_usd=self.TVL_USD,
            tier=self.TIER,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── Supplementary helpers ─────────────────────────────────────────────

    def is_eligible(self) -> bool:
        """True if APY is within the normal fixed-rate range."""
        apy = self.safe_apy()
        return self.MIN_APY <= apy <= self.MAX_APY

    def to_dict(self) -> dict:
        """Full adapter snapshot for dashboards, logs, and tests."""
        apy = self.safe_apy()
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
            "tvl_usd": self.TVL_USD,
            "apy_decimal": apy,
            "apy_pct": round(apy * 100.0, 4),
            "fallback_apy": self.FALLBACK_APY,
            "eligible": self.is_eligible(),
            "ts": time.time(),
        }
