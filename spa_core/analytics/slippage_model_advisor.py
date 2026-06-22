"""Slippage Model Advisor — MP-650.

Estimates expected slippage cost for large DeFi position entries / exits
based on pool TVL and trade size.  Uses a square-root price-impact model
standard in DeFi liquidity analysis.

Design constraints
------------------
* Stdlib only (no numpy, requests, web3, pandas, …).
* Pure advisory — read-only; no side-effects on allocator / risk / execution.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* All writes are atomic (tmp + os.replace).

Square-root slippage model
--------------------------
  slippage_bps = SLIPPAGE_CONST * sqrt(trade_size / tvl) * 10 000
  where SLIPPAGE_CONST = 0.002 (empirically tuned for DeFi stable pools).
  Result is capped at MAX_SLIPPAGE_BPS = 200 bps.

Usage (CLI)::

    python3 -m spa_core.analytics.slippage_model_advisor --check
    python3 -m spa_core.analytics.slippage_model_advisor --run
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/slippage_advisory_log.json")
MAX_ENTRIES = 100

# Slippage model tuning
SLIPPAGE_CONST    = 0.002   # empirically tuned for DeFi stable pools
MAX_SLIPPAGE_BPS  = 200.0   # hard cap; beyond this trades are essentially unviable
MIN_TVL           = 1.0     # avoid divide-by-zero

# Grade boundaries (basis points)
GRADE_A_MAX = 5.0
GRADE_B_MAX = 15.0
GRADE_C_MAX = 30.0

# Recommendation thresholds (basis points)
PROCEED_MAX = 15.0
SPLIT_MAX   = 50.0

# Tranche sizing limits
SPLIT_MIN_TRANCHES = 2
SPLIT_MAX_TRANCHES = 4


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SlippageEstimate:
    """Result of a single slippage estimate for one adapter / trade pair."""

    adapter_id: str
    protocol: str
    trade_size_usd: float           # USD to deposit or withdraw
    tvl_usd: float                  # current pool TVL in USD
    trade_pct_of_tvl: float         # trade_size / tvl  (0–1+)
    estimated_slippage_bps: float   # basis points (1 bp = 0.01 %)
    slippage_cost_usd: float        # trade_size * (slippage_bps / 10 000)
    grade: str                      # A / B / C / D
    recommendation: str             # PROCEED / SPLIT / AVOID
    split_tranches: Optional[int]   # how many tranches if SPLIT; else None


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

class SlippageModelAdvisor:
    """Advisory slippage estimator — square-root price-impact model."""

    SLIPPAGE_CONST   = SLIPPAGE_CONST
    MAX_SLIPPAGE_BPS = MAX_SLIPPAGE_BPS
    MIN_TVL          = MIN_TVL

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _slippage_bps(self, trade_size: float, tvl: float) -> float:
        """Compute slippage in basis points using the sqrt model.

        Returns 0.0 for non-positive trade_size or tvl below MIN_TVL.
        Result is capped at MAX_SLIPPAGE_BPS.
        """
        if tvl < self.MIN_TVL or trade_size <= 0:
            return 0.0
        pct = trade_size / tvl
        raw = self.SLIPPAGE_CONST * math.sqrt(pct) * 10_000
        return min(raw, self.MAX_SLIPPAGE_BPS)

    def _grade(self, bps: float) -> str:
        """Grade the slippage estimate:
            A → < 5 bps   (excellent)
            B → < 15 bps  (good)
            C → < 30 bps  (acceptable)
            D → ≥ 30 bps  (poor)
        """
        if bps < GRADE_A_MAX:
            return "A"
        if bps < GRADE_B_MAX:
            return "B"
        if bps < GRADE_C_MAX:
            return "C"
        return "D"

    def _recommendation(self, bps: float, trade_pct: float) -> Tuple[str, Optional[int]]:
        """Return (recommendation, split_tranches).

        PROCEED  — bps < 15  (single transaction is fine)
        SPLIT    — 15 ≤ bps < 50  (suggest 2–4 tranches)
        AVOID    — bps ≥ 50  (too expensive; reconsider position sizing)
        """
        if bps < PROCEED_MAX:
            return "PROCEED", None
        if bps < SPLIT_MAX:
            tranches = max(
                SPLIT_MIN_TRANCHES,
                min(SPLIT_MAX_TRANCHES, int(trade_pct * 20) + 2),
            )
            return "SPLIT", tranches
        return "AVOID", None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        adapter_id: str,
        protocol: str,
        trade_size_usd: float,
        tvl_usd: float,
    ) -> SlippageEstimate:
        """Estimate slippage for a single trade."""
        pct  = trade_size_usd / tvl_usd if tvl_usd >= self.MIN_TVL else 0.0
        bps  = self._slippage_bps(trade_size_usd, tvl_usd)
        cost = trade_size_usd * (bps / 10_000)
        rec, tranches = self._recommendation(bps, pct)

        return SlippageEstimate(
            adapter_id=adapter_id,
            protocol=protocol,
            trade_size_usd=round(trade_size_usd, 2),
            tvl_usd=round(tvl_usd, 2),
            trade_pct_of_tvl=round(pct, 6),
            estimated_slippage_bps=round(bps, 4),
            slippage_cost_usd=round(cost, 4),
            grade=self._grade(bps),
            recommendation=rec,
            split_tranches=tranches,
        )

    def estimate_batch(self, adapters_data: List[dict]) -> List[SlippageEstimate]:
        """Batch estimate.  Each dict must contain:
            adapter_id, protocol, trade_size_usd, tvl_usd
        """
        return [
            self.estimate(
                d["adapter_id"],
                d["protocol"],
                d["trade_size_usd"],
                d["tvl_usd"],
            )
            for d in adapters_data
        ]

    def worst_slippage(
        self, estimates: List[SlippageEstimate]
    ) -> Optional[SlippageEstimate]:
        """Return the estimate with the highest slippage_bps, or None if empty."""
        if not estimates:
            return None
        return max(estimates, key=lambda e: e.estimated_slippage_bps)

    def total_cost_usd(self, estimates: List[SlippageEstimate]) -> float:
        """Sum of slippage_cost_usd across all estimates."""
        return round(sum(e.slippage_cost_usd for e in estimates), 4)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_estimates(self, estimates: List[SlippageEstimate]) -> None:
        """Atomically append estimates to the ring-buffer log (max MAX_ENTRIES)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: list = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        for e in estimates:
            existing.append({
                "timestamp": time.time(),
                "adapter_id": e.adapter_id,
                "estimated_slippage_bps": e.estimated_slippage_bps,
                "grade": e.grade,
                "recommendation": e.recommendation,
            })
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return logged history; empty list if file missing / corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_demo_trades() -> List[dict]:
    return [
        {"adapter_id": "aave_v3",     "protocol": "Aave V3",     "trade_size_usd":   1_000, "tvl_usd": 500_000_000},
        {"adapter_id": "compound_v3", "protocol": "Compound V3", "trade_size_usd":  10_000, "tvl_usd": 300_000_000},
        {"adapter_id": "morpho",      "protocol": "Morpho",      "trade_size_usd":  50_000, "tvl_usd":  50_000_000},
        {"adapter_id": "euler_v2",    "protocol": "Euler V2",    "trade_size_usd": 200_000, "tvl_usd":   5_000_000},
    ]


def _run(write: bool) -> None:
    advisor = SlippageModelAdvisor()
    estimates = advisor.estimate_batch(_build_demo_trades())

    for e in estimates:
        print(
            f"  [{e.grade}] {e.adapter_id:<14s}  "
            f"bps={e.estimated_slippage_bps:7.3f}  "
            f"cost=${e.slippage_cost_usd:,.2f}  "
            f"{e.recommendation}"
            + (f" ({e.split_tranches} tranches)" if e.split_tranches else "")
        )

    worst = advisor.worst_slippage(estimates)
    total = advisor.total_cost_usd(estimates)
    if worst:
        print(f"\n  Worst: {worst.adapter_id} @ {worst.estimated_slippage_bps:.2f} bps")
    print(f"  Total slippage cost: ${total:,.4f}")

    if write:
        advisor.save_estimates(estimates)
        print(f"\n✓ Saved {len(estimates)} estimates → {advisor.data_file}")


if __name__ == "__main__":
    mode = "--check"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    if mode == "--run":
        _run(write=True)
    else:
        _run(write=False)
