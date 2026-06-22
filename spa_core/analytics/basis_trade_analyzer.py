"""
MP-658: BasisTradeAnalyzer
Analyze basis trade opportunities: spot yield vs perp funding rate spread.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/basis_trade_log.json")
MAX_ENTRIES = 100


@dataclass
class BasisTradeInput:
    asset: str
    spot_yield_annual: float      # e.g. staking APY or lending yield (decimal)
    perp_funding_annual: float    # annualised perp funding rate (positive = longs pay)
    execution_cost_bps: float     # estimated round-trip cost in bps
    capital_usd: float


@dataclass
class BasisTradeResult:
    asset: str
    spot_yield_annual: float
    perp_funding_annual: float
    gross_spread_bps: float       # (spot + perp) * 10000
    net_spread_bps: float         # gross - execution_cost_bps
    annual_pnl_usd: float         # capital * net_spread / 10000
    is_profitable: bool           # net_spread > 0
    edge_quality: str             # EXCELLENT(≥100bps)/GOOD(≥50bps)/MARGINAL(≥10bps)/UNATTRACTIVE(<10bps)
    recommended_action: str       # ENTER / MONITOR / SKIP
    capital_usd: float


class BasisTradeAnalyzer:
    """
    Analyse basis trade opportunities by comparing spot yield + perp funding
    rate spread against execution costs.

    Basis trade structure:
      • Long spot  → earn spot_yield_annual
      • Short perp → earn perp_funding_annual (if > 0; pay if < 0)
      • Gross spread = (spot_yield + perp_funding) * 10000  [bps]
      • Net spread   = gross - execution_cost_bps
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gross_spread_bps(
        self,
        spot_yield: float,
        perp_funding: float,
    ) -> float:
        """
        Gross basis spread in bps.

        Long spot earns spot_yield; short perp earns funding when perp > 0,
        pays funding when perp < 0 → funding is additive (negative funding reduces spread).
        """
        return round((spot_yield + perp_funding) * 10000, 4)

    def _edge_quality(self, net_bps: float) -> str:
        """Classify net spread into edge-quality tier."""
        if net_bps >= 100:
            return "EXCELLENT"
        if net_bps >= 50:
            return "GOOD"
        if net_bps >= 10:
            return "MARGINAL"
        return "UNATTRACTIVE"

    def _action(self, net_bps: float) -> str:
        """Map net spread to recommended action."""
        if net_bps >= 50:
            return "ENTER"
        if net_bps >= 10:
            return "MONITOR"
        return "SKIP"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, inp: BasisTradeInput) -> BasisTradeResult:
        """Analyse a single basis trade opportunity."""
        gross = self._gross_spread_bps(inp.spot_yield_annual, inp.perp_funding_annual)
        net = round(gross - inp.execution_cost_bps, 4)
        annual_pnl = round(inp.capital_usd * net / 10000, 4)
        return BasisTradeResult(
            asset=inp.asset,
            spot_yield_annual=round(inp.spot_yield_annual, 6),
            perp_funding_annual=round(inp.perp_funding_annual, 6),
            gross_spread_bps=gross,
            net_spread_bps=net,
            annual_pnl_usd=annual_pnl,
            is_profitable=net > 0,
            edge_quality=self._edge_quality(net),
            recommended_action=self._action(net),
            capital_usd=round(inp.capital_usd, 2),
        )

    def analyze_batch(
        self,
        inputs: List[BasisTradeInput],
    ) -> List[BasisTradeResult]:
        """Analyse a list of basis trade inputs and return results in order."""
        return [self.analyze(inp) for inp in inputs]

    def top_opportunities(
        self,
        results: List[BasisTradeResult],
        n: int = 3,
    ) -> List[BasisTradeResult]:
        """Return top-N results by net_spread_bps descending."""
        return sorted(results, key=lambda r: r.net_spread_bps, reverse=True)[:n]

    def total_annual_pnl(self, results: List[BasisTradeResult]) -> float:
        """Sum annual_pnl_usd across all results (includes negatives)."""
        return round(sum(r.annual_pnl_usd for r in results), 4)

    def save_results(self, results: List[BasisTradeResult]) -> None:
        """
        Append results to the ring-buffer JSON log (max MAX_ENTRIES).
        Uses atomic write: tmp + os.replace.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append({
                "timestamp": time.time(),
                "asset": r.asset,
                "net_spread_bps": r.net_spread_bps,
                "edge_quality": r.edge_quality,
                "recommended_action": r.recommended_action,
                "annual_pnl_usd": r.annual_pnl_usd,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
