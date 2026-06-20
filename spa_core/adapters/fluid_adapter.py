"""
Fluid Protocol (Instadapp) USDC and USDT vault adapters (T2) — MP-1547.

Fluid provides automated yield vaults for USDC/USDT via ERC-4626 vaults on
Ethereum mainnet, powered by Instadapp's smart-collateral architecture.

Security: audited by Sigma Prime + Trail of Bits (2024)
TVL: $2B+ (as of May 2026)
Tier: T2 — established protocol with good security record, moderate complexity

Two adapters:
  FluidUSDCAdapter — Fluid USDC lending pool on Ethereum
  FluidUSDTAdapter — Fluid USDT lending pool on Ethereum

Design:
  - fetch_apy() → live APY from DeFiLlama or FALLBACK_APY (decimal)
  - safe_apy()  → fetch_apy() clamped to [MIN_APY, MAX_APY]
  - get_apy()   → BaseAdapter contract (returns safe_apy())
  - get_yield_info() → BaseAdapter contract

Class attributes (conformance checker compatible):
  PROTOCOL, ASSET, CHAIN, TIER, RESEARCH_ONLY, FALLBACK_APY

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

#: DeFiLlama project slug for Fluid Protocol
_FLUID_PROJECT = "fluid"

#: Utilization warning threshold (shared)
UTILIZATION_WARNING_THRESHOLD: float = 0.90


class FluidUSDCAdapter(BaseAdapter):
    """Fluid Protocol USDC vault on Ethereum (T2, RESEARCH_ONLY=True).

    APY sourced from DeFiLlama yields API.
    Falls back to FALLBACK_APY (5.5%) when feed is unavailable.

    RESEARCH_ONLY=True: allocation requires paper-trading validation first.
    """

    # ── Identity ─────────────────────────────────────────────────────────
    PROTOCOL = "fluid_usdc"
    PROTOCOL_NAME = "Fluid Protocol USDC"
    ASSET = "USDC"
    CHAIN = "ethereum"
    CHAIN_ID = 1

    # ── Tier / Risk ───────────────────────────────────────────────────────
    TIER = "T2"
    RESEARCH_ONLY = True  # paper-trading validation required
    RISK_SCORE = 0.35     # T2 moderate — Instadapp, well-audited vault

    # SPA-V412: instant exit from ERC-4626 vault (subject to pool liquidity)
    EXIT_LATENCY_HOURS = 0.0

    # ── APY parameters (all as decimals, e.g. 0.055 = 5.5%) ──────────────
    FALLBACK_APY: float = 0.055   # 5.5% fallback
    MAX_APY: float = 0.30         # 30% spike cap
    MIN_APY: float = 0.005        # 0.5% floor

    # ── TVL ───────────────────────────────────────────────────────────────
    TVL_USD: float = 2_000_000_000.0

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
        """Fetch current APY from DeFiLlama as a decimal.

        Searches for Fluid Protocol USDC pool on Ethereum.
        Returns FALLBACK_APY if the feed is unavailable or no match found.
        Never raises.
        """
        try:
            pool = self.feed.get_pool(
                project=_FLUID_PROJECT,
                symbol=self.ASSET,
                chain="Ethereum",
            )
            if pool is not None:
                raw = pool.get("apy")
                if isinstance(raw, (int, float)) and raw is not None:
                    # DeFiLlama stores APY as percentage (e.g. 5.5 → 0.055)
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
        """True if APY is within reasonable range for allocation."""
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


class FluidUSDTAdapter(FluidUSDCAdapter):
    """Fluid Protocol USDT vault on Ethereum (T2, RESEARCH_ONLY=True).

    Inherits all behaviour from FluidUSDCAdapter but targets the USDT pool.
    Slightly higher risk score due to USDT de-peg tail risk.
    """

    PROTOCOL = "fluid_usdt"
    PROTOCOL_NAME = "Fluid Protocol USDT"
    ASSET = "USDT"
    FALLBACK_APY: float = 0.054   # 5.4% fallback (USDT pool typically slightly lower)
    RISK_SCORE = 0.36             # Marginally higher: USDT counterparty/peg risk

    def __init__(
        self,
        asset: str = "USDT",
        feed: Optional[DeFiLlamaFeed] = None,
    ) -> None:
        super().__init__(asset=asset, feed=feed)
