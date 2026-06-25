"""
Bitcoin lending adapters — tBTC + cbBTC supply yield (T2, READ-ONLY, advisory).

Per ``docs/RESEARCH_EXPANSION_2026-06-25.md`` §1 ("BTC yield — how to add Bitcoin
safely"). The deliverable is a **read-only** monitoring feed for the *conservative*
BTC-lending path only:

  * **tBTC** (Threshold) — decentralized, threshold-ECDSA signer group, no single
    party can move funds. Lowest wrapper SPOF.
  * **cbBTC** (Coinbase) — single US-regulated public company. Regulated, but
    single-entity custody.

HONEST FRAMING (do not inflate):
  Safe BTC lending pays **~0–1.2% APY** because BTC is rarely *borrowed* on-chain
  (utilization ~2–6%). A low number here is **correct, not a bug**. The real risk
  in BTC-DeFi is the **wrapper** (bridge/custody/governance of the wrapped token),
  not the lending APY. We therefore deliberately:
    * prefer tBTC (decentralized) + cbBTC (regulated),
    * **AVOID WBTC** as primary collateral (BitGo→BiT Global governance overhang,
      Coinbase delisting), and
    * **REJECT LBTC-restaking** ("extra" yield is points/airdrop-driven leverage on
      the bridge, not contractual yield).

DOMAIN RULES (CLAUDE.md):
  * READ-ONLY (``spa_core/adapters/`` domain) — never writes execution state,
    never touches ``data/adapter_status.json``. No allocate()/withdraw().
  * stdlib only (urllib via :class:`DeFiLlamaFeed`). No external deps.
  * ``IS_ADVISORY = True`` / ``RESEARCH_ONLY = True`` — simulate/monitor only,
    no live positions, until a canary promotes it.
  * Tier T2 (lending on Aave/Morpho/Compound + wrapped-BTC bridge risk).
  * LLM FORBIDDEN.

Source: DeFiLlama yields API (project aave-v3 / morpho-blue / compound-v3,
symbol TBTC / CBBTC), via :class:`DeFiLlamaFeed`. ``get_apy`` returns a **decimal**
(0.012 == 1.2%), matching :class:`YieldInfo`, the orchestrator, and the sibling
adapters (e.g. ``pendle_pt_usdc_adapter``). No mock fallback — ``None`` on a miss.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)


class BtcLendingAdapter(BaseAdapter):
    """Read-only supply-yield feed for a single wrapped-BTC lending asset (T2).

    Probes a small list of ``(project, chain)`` lending venues for the asset's
    supply APY/TVL on DeFiLlama and returns the highest-TVL live pool. APY from
    :meth:`get_apy` is a **decimal** (0.012 == 1.2%). Read-only / advisory: no
    on-chain execution, no state writes, no allocate/withdraw.
    """

    # ── Tier / Risk / domain flags ───────────────────────────────────────
    TIER = "T2"
    IS_ADVISORY = True      # advisory/monitor only until canary (research doc §1)
    RESEARCH_ONLY = True    # adapter-domain alias of IS_ADVISORY (sibling convention)
    RISK_SCORE = 0.45       # lending risk + wrapped-BTC bridge/custody risk
    EXIT_LATENCY_HOURS = 0.0  # blue-chip lending pools exit same-block

    # ── APY band (decimals) — honest: BTC lending is structurally low ────
    # BTC is rarely borrowed (utilization ~2–6%), so supply APY is ~0–1.2%.
    # We do NOT inflate. The band only rejects clearly anomalous reads.
    MIN_APY: float = 0.0    # 0% is a legitimate, expected reading here.
    MAX_APY: float = 0.05   # >5% on "safe" BTC lending => anomaly, reject.

    # ── TVL floor — RiskPolicy needs ≥ $5M to ever allocate ──────────────
    MIN_TVL_USD: float = 5_000_000.0

    def __init__(
        self,
        protocol: str,
        protocol_name: str,
        symbol: str,
        venues: List[Tuple[str, str]],
        feed: Optional[DeFiLlamaFeed] = None,
        decentralized: bool = False,
        regulated: bool = False,
    ) -> None:
        """Build a wrapped-BTC lending feed.

        Args:
            protocol:       registry key, e.g. ``"tbtc_lending"``.
            protocol_name:  human label, e.g. ``"tBTC Lending"``.
            symbol:         DeFiLlama pool symbol, e.g. ``"TBTC"`` / ``"CBBTC"``.
            venues:         ordered ``(project, chain)`` lending venues to probe,
                            highest-TVL match across all of them wins.
            feed:           injectable :class:`DeFiLlamaFeed` (FakeFeed in tests).
            decentralized:  True for tBTC (Threshold) — no single-custodian SPOF.
            regulated:      True for cbBTC (Coinbase) — single regulated entity.
        """
        super().__init__(asset=symbol)
        self.PROTOCOL = protocol
        self.PROTOCOL_NAME = protocol_name
        self.SYMBOL = symbol
        self.VENUES = list(venues)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()
        self.decentralized = decentralized
        self.regulated = regulated

    # ── pool lookup ──────────────────────────────────────────────────────

    def _best_pool(self) -> Optional[dict]:
        """Highest-TVL live lending pool across the configured venues, or None.

        Iterates every ``(project, chain)`` venue, keeps the largest-TVL match.
        Never raises — feed errors degrade to ``None`` (no live data).
        """
        best: Optional[dict] = None
        best_tvl = float("-inf")
        for project, chain in self.VENUES:
            try:
                pool = self.feed.get_pool(
                    project=project, symbol=self.SYMBOL, chain=chain
                )
            except Exception as exc:  # noqa: BLE001 - graceful, never raise
                logger.debug("%s: feed.get_pool(%s,%s) failed: %s",
                             self.PROTOCOL, project, chain, exc)
                pool = None
            if not isinstance(pool, dict):
                continue
            tvl = pool.get("tvlUsd")
            tvl = float(tvl) if isinstance(tvl, (int, float)) and not isinstance(tvl, bool) else 0.0
            if tvl > best_tvl:
                best_tvl = tvl
                best = pool
        return best

    # ── core read surface (decimal APY, matching siblings) ───────────────

    def get_apy(self) -> Optional[float]:
        """Supply APY as a **decimal** (0.012 == 1.2%), or ``None`` on miss.

        DeFiLlama serves APY as a percentage; we divide by 100 to match the
        ``YieldInfo``/orchestrator decimal convention. Reads outside
        ``[MIN_APY, MAX_APY]`` are rejected as anomalous (returns ``None``) —
        but 0% is a legitimate, expected BTC-lending reading and passes.
        """
        pool = self._best_pool()
        if pool is None:
            return None
        raw = pool.get("apy")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return None
        apy = float(raw) / 100.0
        if apy < self.MIN_APY or apy > self.MAX_APY:
            logger.warning(
                "%s: anomalous BTC-lending APY %.4f%% rejected (safe band 0–5%%)",
                self.PROTOCOL, apy * 100.0,
            )
            return None
        return apy

    def get_tvl(self) -> Optional[float]:
        """Live TVL in USD for the best matching lending pool, or ``None``."""
        pool = self._best_pool()
        if pool is None:
            return None
        tvl = pool.get("tvlUsd")
        if not isinstance(tvl, (int, float)) or isinstance(tvl, bool):
            return None
        return float(tvl)

    # ── eligibility (read-only / advisory) ───────────────────────────────

    def tvl_ok(self) -> bool:
        """True when live TVL meets the RiskPolicy $5M floor."""
        tvl = self.get_tvl()
        return tvl is not None and tvl >= self.MIN_TVL_USD

    def is_eligible(self) -> bool:
        """Advisory eligibility only — IS_ADVISORY means this never allocates.

        Returns True when there is live data clearing the TVL floor with an
        in-band APY; the cycle still treats the adapter as monitor-only.
        """
        apy = self.get_apy()
        if apy is None:
            return False
        return self.tvl_ok() and self.MIN_APY <= apy <= self.MAX_APY

    # ── normalized output ────────────────────────────────────────────────

    def get_yield_info(self) -> YieldInfo:
        """Normalized :class:`YieldInfo` (decimal APY, may be ``None``)."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy(),
            tvl_usd=self.get_tvl(),
            tier=self.TIER,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    def to_dict(self) -> dict:
        """Full adapter snapshot for dashboards, logs, and tests."""
        apy = self.get_apy()
        tvl = self.get_tvl()
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "asset": self.asset,
            "symbol": self.SYMBOL,
            "venues": self.VENUES,
            "tier": self.TIER,
            "is_advisory": self.IS_ADVISORY,
            "research_only": self.RESEARCH_ONLY,
            "decentralized": self.decentralized,
            "regulated": self.regulated,
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "apy_decimal": apy,
            "apy_pct": round(apy * 100.0, 6) if apy is not None else None,
            "tvl_usd": tvl,
            "tvl_ok": self.tvl_ok(),
            "min_tvl_usd": self.MIN_TVL_USD,
            "eligible": self.is_eligible(),
            "ts": time.time(),
        }


# ── Concrete BTC-lending adapters (the two SAFE wrappers only) ───────────────
# Venues are ordered/probed for the highest-TVL live supply pool. tBTC: Aave V3
# (ETH ~$113M) is the deepest; cbBTC: Aave V3 (ETH ~$960M) and Base (~$130M),
# Compound V3. WBTC and LBTC are deliberately EXCLUDED (wrapper risk).

# tBTC venues — decentralized wrapper (Threshold). Morpho/Compound as fallbacks.
_TBTC_VENUES: List[Tuple[str, str]] = [
    ("aave-v3", "Ethereum"),
    ("aave-v3", "Arbitrum"),
    ("compound-v3", "Ethereum"),
    ("morpho-blue", "Ethereum"),
]

# cbBTC venues — regulated wrapper (Coinbase). Aave/Compound *lending* markets
# (Morpho cbBTC is largely collateral-only at 0% supply APY, but kept as a probe).
_CBBTC_VENUES: List[Tuple[str, str]] = [
    ("aave-v3", "Ethereum"),
    ("aave-v3", "Base"),
    ("compound-v3", "Ethereum"),
    ("morpho-blue", "Ethereum"),
    ("morpho-blue", "Base"),
]


class TbtcLendingAdapter(BtcLendingAdapter):
    """tBTC (Threshold, decentralized) lending supply-yield feed — T2, advisory."""

    def __init__(self, feed: Optional[DeFiLlamaFeed] = None) -> None:
        super().__init__(
            protocol="tbtc_lending",
            protocol_name="tBTC Lending",
            symbol="TBTC",
            venues=_TBTC_VENUES,
            feed=feed,
            decentralized=True,
            regulated=False,
        )


class CbbtcLendingAdapter(BtcLendingAdapter):
    """cbBTC (Coinbase, regulated) lending supply-yield feed — T2, advisory."""

    def __init__(self, feed: Optional[DeFiLlamaFeed] = None) -> None:
        super().__init__(
            protocol="cbbtc_lending",
            protocol_name="cbBTC Lending",
            symbol="CBBTC",
            venues=_CBBTC_VENUES,
            feed=feed,
            decentralized=False,
            regulated=True,
        )
