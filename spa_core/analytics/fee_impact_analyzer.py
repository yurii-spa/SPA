"""
MP-642: FeeImpactAnalyzer
Analyze how protocol fees affect net yield.

Advisory / read-only module. Pure stdlib. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/fee_impact_analysis.json")
MAX_ENTRIES = 100


@dataclass
class FeeStructure:
    protocol_id: str
    management_fee_pct: float    # annual management fee  (e.g. 0.02 = 2 %)
    performance_fee_pct: float   # fee on profits         (e.g. 0.20 = 20 % of profit)
    withdrawal_fee_pct: float    # one-time withdrawal fee
    entry_fee_pct: float         # one-time entry fee
    gas_cost_usd: float          # estimated gas cost per transaction


@dataclass
class FeeImpact:
    protocol_id: str
    gross_apy: float
    capital_usd: float
    hold_days: int
    # Fees (all in USD)
    management_fee_cost_usd: float
    performance_fee_cost_usd: float
    entry_fee_cost_usd: float
    withdrawal_fee_cost_usd: float
    gas_cost_total_usd: float        # entry + exit gas
    total_fee_cost_usd: float
    # Net results
    net_apy: float
    net_pnl_usd: float
    gross_pnl_usd: float
    fee_drag_bps: float              # annualised fee drag in basis points
    break_even_days: int             # days to cover one-time entry costs
    grade: str                       # A (<10 bps) / B (<25) / C (<50) / D (≥50)
    recommendation: str              # FAVORABLE / ACCEPTABLE / EXPENSIVE / AVOID


class FeeImpactAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _grade(self, fee_drag_bps: float) -> str:
        """A / B / C / D based on annualised fee drag in basis points."""
        if fee_drag_bps < 10:
            return "A"
        if fee_drag_bps < 25:
            return "B"
        if fee_drag_bps < 50:
            return "C"
        return "D"

    def _recommendation(self, grade: str, net_apy: float, gross_apy: float) -> str:
        """AVOID / EXPENSIVE / ACCEPTABLE / FAVORABLE."""
        if net_apy < 0:
            return "AVOID"
        if grade == "D":
            return "EXPENSIVE"
        if grade in ("B", "C"):
            return "ACCEPTABLE"
        return "FAVORABLE"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        fee_structure: FeeStructure,
        gross_apy: float,
        capital_usd: float,
        hold_days: int,
    ) -> FeeImpact:
        """Compute net yield after all fees for the given holding period."""
        hold_years = hold_days / 365.0
        gross_pnl = capital_usd * gross_apy * hold_years

        # Management fee: annual % of capital, pro-rated
        mgmt_cost = capital_usd * fee_structure.management_fee_pct * hold_years

        # Performance fee: % of gross profit (never negative)
        perf_cost = max(0.0, gross_pnl * fee_structure.performance_fee_pct)

        # Entry / withdrawal: one-time % of capital
        entry_cost = capital_usd * fee_structure.entry_fee_pct
        withdrawal_cost = capital_usd * fee_structure.withdrawal_fee_pct

        # Gas: entry transaction + exit transaction = 2
        gas_total = fee_structure.gas_cost_usd * 2

        total_fees = mgmt_cost + perf_cost + entry_cost + withdrawal_cost + gas_total
        net_pnl = gross_pnl - total_fees

        # Net APY (annualised); floor at -100 %
        if hold_years > 0 and capital_usd > 0:
            net_apy = net_pnl / capital_usd / hold_years
        else:
            net_apy = 0.0
        net_apy = max(-1.0, net_apy)

        # Fee drag in bps (annualised)
        if hold_years > 0:
            fee_drag_annual = total_fees / capital_usd / hold_years
        else:
            fee_drag_annual = 0.0
        fee_drag_bps = fee_drag_annual * 10_000

        # Break-even days: days until gross_pnl covers one-time entry costs
        entry_costs = entry_cost + withdrawal_cost + gas_total
        if capital_usd > 0 and gross_apy > 0 and entry_costs > 0:
            break_even_days = int(entry_costs / (capital_usd * gross_apy / 365)) + 1
        else:
            break_even_days = 0

        grade = self._grade(fee_drag_bps)

        return FeeImpact(
            protocol_id=fee_structure.protocol_id,
            gross_apy=round(gross_apy, 6),
            capital_usd=capital_usd,
            hold_days=hold_days,
            management_fee_cost_usd=round(mgmt_cost, 4),
            performance_fee_cost_usd=round(perf_cost, 4),
            entry_fee_cost_usd=round(entry_cost, 4),
            withdrawal_fee_cost_usd=round(withdrawal_cost, 4),
            gas_cost_total_usd=round(gas_total, 4),
            total_fee_cost_usd=round(total_fees, 4),
            net_apy=round(net_apy, 6),
            net_pnl_usd=round(net_pnl, 4),
            gross_pnl_usd=round(gross_pnl, 4),
            fee_drag_bps=round(fee_drag_bps, 2),
            break_even_days=break_even_days,
            grade=grade,
            recommendation=self._recommendation(grade, net_apy, gross_apy),
        )

    def compare_protocols(
        self,
        protocols: List[FeeStructure],
        gross_apy: float,
        capital_usd: float,
        hold_days: int,
    ) -> List[FeeImpact]:
        """Analyze each protocol and return results sorted by net_apy descending."""
        impacts = [self.analyze(p, gross_apy, capital_usd, hold_days) for p in protocols]
        return sorted(impacts, key=lambda x: x.net_apy, reverse=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_analysis(self, impacts: List[FeeImpact]) -> None:
        """Append analysis entry to ring-buffer JSON (atomic write)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        entry = {
            "timestamp": time.time(),
            "analyses": [
                {
                    "protocol_id": i.protocol_id,
                    "gross_apy": i.gross_apy,
                    "net_apy": i.net_apy,
                    "fee_drag_bps": i.fee_drag_bps,
                    "grade": i.grade,
                    "recommendation": i.recommendation,
                    "break_even_days": i.break_even_days,
                    "total_fee_cost_usd": i.total_fee_cost_usd,
                }
                for i in impacts
            ],
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return list of saved analysis entries; [] on missing/corrupt file."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
