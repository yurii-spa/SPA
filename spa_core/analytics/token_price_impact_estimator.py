"""MP-688 TokenPriceImpactEstimator
====================================
Estimate the price impact of buying or selling a token given pool/market
depth data.  Supports three pool models:

  * **CPAMM** — constant-product AMM (Uniswap-style x*y=k)
  * **CLMM**  — concentrated-liquidity AMM (Uniswap V3-style)
  * **ORDERBOOK** — centralised/off-chain order-book approximation

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas.
* Advisory / read-only — never modifies allocator / risk / execution.
* Atomic writes: tmp-file + os.replace for all JSON persistence.
* LLM_FORBIDDEN domain: not imported from risk / execution / monitoring.
* Ring-buffer cap: MAX_ENTRIES per log file.

Price Impact Models
-------------------
CPAMM::

    impact_bps = (trade_size / pool_liquidity) * 10_000 * 2

CLMM::

    impact_bps = (trade_size / pool_liquidity) * 10_000 * 0.5

ORDERBOOK::

    impact_bps = volatility_24h_pct * (trade_size / pool_liquidity) * 100

All impact values are capped at 10 000 bps (= 100 %).

Total slippage
--------------
total_slippage_bps = price_impact_bps + fee_cost_bps
                     + (spread_bps / 2 if ORDERBOOK else 0)

Half the spread because it is a one-way cost (you pay half on entry,
half on exit; for a single leg we charge one half).

Execution quality thresholds
-----------------------------
EXCELLENT  total_slippage_bps <   5
GOOD                          <  20
FAIR                          <  50
POOR                          < 200
REJECT                        ≥ 200

Public API
----------
``TokenPriceImpactEstimator(data_file=DATA_FILE)``

  estimate(spec)          → PriceImpactEstimate
  estimate_batch(specs)   → List[PriceImpactEstimate]
  save_results(estimates) → None  (atomic ring-buffer write)
  load_history()          → List[dict]
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/price_impact_log.json")
MAX_ENTRIES = 100

# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeSpec:
    """Input specification for a single trade impact estimate."""
    trade_id: str
    token: str
    direction: str               # "BUY" or "SELL"
    trade_size_usd: float
    pool_type: str               # "CPAMM", "CLMM", or "ORDERBOOK"
    pool_liquidity_usd: float    # total liquidity / book depth in USD
    fee_tier_bps: float          # pool fee in basis-points (e.g. 30 = 0.30%)
    volatility_24h_pct: float    # 24-hour price volatility in percent
    spread_bps: Optional[float]  # bid-ask spread bps (ORDERBOOK only; None for AMMs)


@dataclass
class PriceImpactEstimate:
    """Result of a price-impact estimation."""
    trade_id: str
    token: str
    direction: str
    trade_size_usd: float
    price_impact_bps: float       # estimated price impact in bps
    fee_cost_bps: float           # = spec.fee_tier_bps
    total_slippage_bps: float     # price_impact + fee + spread/2 (orderbook)
    execution_quality: str        # EXCELLENT / GOOD / FAIR / POOR / REJECT
    expected_fill_pct: float      # 0–100
    split_recommendation: Optional[int]  # splits advised; None when none
    warnings: List[str]           # advisory warnings


# ──────────────────────────────────────────────────────────────────────────────
# Estimator
# ──────────────────────────────────────────────────────────────────────────────

class TokenPriceImpactEstimator:
    """Estimate price impact for DeFi token trades across pool types."""

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ── private helpers ───────────────────────────────────────────────────────

    def _price_impact_bps(self, spec: TradeSpec) -> float:
        """Return raw price impact in bps, capped at 10 000."""
        liq = spec.pool_liquidity_usd
        size = spec.trade_size_usd
        pool = spec.pool_type.upper()

        if liq <= 0:
            return 10_000.0

        if pool == "CPAMM":
            raw = (size / liq) * 10_000.0 * 2.0
        elif pool == "CLMM":
            raw = (size / liq) * 10_000.0 * 0.5
        elif pool == "ORDERBOOK":
            raw = spec.volatility_24h_pct * (size / liq) * 100.0
        else:
            # Unknown pool type — treat as CPAMM (conservative)
            raw = (size / liq) * 10_000.0 * 2.0

        return min(raw, 10_000.0)

    def _total_slippage(
        self,
        price_impact_bps: float,
        fee_cost_bps: float,
        pool_type: str,
        spread_bps: Optional[float],
    ) -> float:
        """Aggregate slippage (impact + fee + half-spread for orderbooks)."""
        spread_component = 0.0
        if pool_type.upper() == "ORDERBOOK" and spread_bps is not None:
            spread_component = spread_bps / 2.0
        return price_impact_bps + fee_cost_bps + spread_component

    def _execution_quality(self, total_slippage_bps: float) -> str:
        if total_slippage_bps < 5:
            return "EXCELLENT"
        if total_slippage_bps < 20:
            return "GOOD"
        if total_slippage_bps < 50:
            return "FAIR"
        if total_slippage_bps < 200:
            return "POOR"
        return "REJECT"

    def _expected_fill_pct(self, quality: str) -> float:
        return {
            "EXCELLENT": 100.0,
            "GOOD":      100.0,
            "FAIR":       95.0,
            "POOR":       80.0,
            "REJECT":      0.0,
        }[quality]

    def _split_recommendation(self, quality: str) -> Optional[int]:
        return {
            "EXCELLENT": None,
            "GOOD":      None,
            "FAIR":      2,
            "POOR":      4,
            "REJECT":    None,  # don't trade at all
        }[quality]

    def _warnings(self, spec: TradeSpec, quality: str) -> List[str]:
        warns: List[str] = []
        if quality == "REJECT":
            warns.append(
                "🚨 Price impact too high — do not execute this trade"
            )
        if (
            spec.pool_type.upper() == "ORDERBOOK"
            and spec.spread_bps is not None
            and spec.spread_bps > 50
        ):
            warns.append(
                "⚠️ Wide bid-ask spread — market illiquid"
            )
        if spec.volatility_24h_pct > 10:
            warns.append(
                "⚠️ High 24h volatility — impact estimates may be inaccurate"
            )
        if spec.pool_liquidity_usd > 0 and spec.trade_size_usd > spec.pool_liquidity_usd * 0.05:
            warns.append(
                "⚠️ Trade >5% of pool liquidity — significant impact"
            )
        return warns

    # ── public API ────────────────────────────────────────────────────────────

    def estimate(self, spec: TradeSpec) -> PriceImpactEstimate:
        """Estimate price impact for a single trade specification."""
        impact_bps = self._price_impact_bps(spec)
        fee_bps = spec.fee_tier_bps
        total_bps = self._total_slippage(
            impact_bps, fee_bps, spec.pool_type, spec.spread_bps
        )
        quality = self._execution_quality(total_bps)
        return PriceImpactEstimate(
            trade_id=spec.trade_id,
            token=spec.token,
            direction=spec.direction,
            trade_size_usd=spec.trade_size_usd,
            price_impact_bps=impact_bps,
            fee_cost_bps=fee_bps,
            total_slippage_bps=total_bps,
            execution_quality=quality,
            expected_fill_pct=self._expected_fill_pct(quality),
            split_recommendation=self._split_recommendation(quality),
            warnings=self._warnings(spec, quality),
        )

    def estimate_batch(self, specs: List[TradeSpec]) -> List[PriceImpactEstimate]:
        """Estimate price impact for a list of trade specifications."""
        return [self.estimate(s) for s in specs]

    # ── persistence ───────────────────────────────────────────────────────────

    def save_results(self, estimates: List[PriceImpactEstimate]) -> None:
        """Append estimates to the ring-buffer log (capped at MAX_ENTRIES)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: List[dict] = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        for e in estimates:
            existing.append(
                {
                    "timestamp": time.time(),
                    "trade_id": e.trade_id,
                    "token": e.token,
                    "direction": e.direction,
                    "trade_size_usd": e.trade_size_usd,
                    "price_impact_bps": e.price_impact_bps,
                    "fee_cost_bps": e.fee_cost_bps,
                    "total_slippage_bps": e.total_slippage_bps,
                    "execution_quality": e.execution_quality,
                    "expected_fill_pct": e.expected_fill_pct,
                    "split_recommendation": e.split_recommendation,
                    "warnings": e.warnings,
                }
            )

        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return persisted log entries, or [] if file is missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
