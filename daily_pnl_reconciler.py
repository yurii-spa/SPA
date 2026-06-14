"""
MP-641: DailyPnLReconciler
Reconcile expected vs actual daily PnL for each strategy.

Advisory / read-only module. Pure stdlib. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/daily_pnl_reconciliation.json")
MAX_ENTRIES = 100


@dataclass
class StrategyPnL:
    strategy_id: str
    date_str: str            # "YYYY-MM-DD"
    capital_usd: float       # capital deployed
    expected_apy: float      # expected APY (decimal)
    actual_apy: float        # realized APY for this day (annualized)
    expected_daily_pnl: float    # capital * expected_apy / 365
    actual_daily_pnl: float      # capital * actual_apy / 365
    variance_usd: float          # actual - expected
    variance_pct: float          # variance_usd / expected_daily_pnl (if non-zero)
    status: str                  # ON_TRACK / UNDERPERFORM / OVERPERFORM / DATA_MISSING


@dataclass
class ReconciliationReport:
    date_str: str
    timestamp: float
    strategies: List[StrategyPnL]
    total_capital_usd: float
    total_expected_pnl: float
    total_actual_pnl: float
    total_variance_usd: float
    overall_status: str          # GREEN / YELLOW / RED
    underperformers: List[str]   # strategy_ids
    overperformers: List[str]


class DailyPnLReconciler:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_daily_pnl(self, capital: float, apy: float) -> float:
        """Return capital * apy / 365."""
        return capital * apy / 365

    def _compute_variance_pct(self, variance_usd: float, expected_pnl: float) -> float:
        """Return variance_usd / expected_pnl; 0.0 when expected is near-zero."""
        if abs(expected_pnl) < 0.000001:
            return 0.0
        return variance_usd / expected_pnl

    def _classify_strategy(self, variance_pct: float, actual_apy: float) -> str:
        """Return ON_TRACK / UNDERPERFORM / OVERPERFORM / DATA_MISSING."""
        if actual_apy == 0.0 and variance_pct == 0.0:
            return "DATA_MISSING"
        if abs(variance_pct) <= 0.10:  # within ±10 % of expected (inclusive boundary)
            return "ON_TRACK"
        if variance_pct < -0.10:       # strictly more than 10 % below
            return "UNDERPERFORM"
        return "OVERPERFORM"            # more than 10 % above

    def _overall_status(self, strategies: List[StrategyPnL]) -> str:
        """GREEN if 0 underperformers; YELLOW if ≤ 1/3; RED otherwise."""
        if not strategies:
            return "GREEN"
        statuses = [s.status for s in strategies]
        undercount = statuses.count("UNDERPERFORM")
        if undercount == 0:
            return "GREEN"
        if undercount <= len(strategies) // 3:
            return "YELLOW"
        return "RED"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(self, date_str: str, strategy_data: List[Dict]) -> ReconciliationReport:
        """
        Compute per-strategy and aggregate reconciliation.

        strategy_data: list of dicts with keys:
          strategy_id  : str
          capital_usd  : float  – capital deployed
          expected_apy : float  – annualised expected APY (decimal)
          actual_apy   : float  – annualised realized APY (decimal)
        """
        strategies: List[StrategyPnL] = []

        for d in strategy_data:
            exp_pnl = self._compute_daily_pnl(d["capital_usd"], d["expected_apy"])
            act_pnl = self._compute_daily_pnl(d["capital_usd"], d["actual_apy"])
            variance_usd = act_pnl - exp_pnl
            variance_pct = self._compute_variance_pct(variance_usd, exp_pnl)

            sp = StrategyPnL(
                strategy_id=d["strategy_id"],
                date_str=date_str,
                capital_usd=d["capital_usd"],
                expected_apy=d["expected_apy"],
                actual_apy=d["actual_apy"],
                expected_daily_pnl=round(exp_pnl, 4),
                actual_daily_pnl=round(act_pnl, 4),
                variance_usd=round(variance_usd, 4),
                variance_pct=round(variance_pct, 4),
                status=self._classify_strategy(variance_pct, d["actual_apy"]),
            )
            strategies.append(sp)

        total_cap = sum(s.capital_usd for s in strategies)
        total_exp = sum(s.expected_daily_pnl for s in strategies)
        total_act = sum(s.actual_daily_pnl for s in strategies)
        total_var = total_act - total_exp

        return ReconciliationReport(
            date_str=date_str,
            timestamp=time.time(),
            strategies=strategies,
            total_capital_usd=round(total_cap, 2),
            total_expected_pnl=round(total_exp, 4),
            total_actual_pnl=round(total_act, 4),
            total_variance_usd=round(total_var, 4),
            overall_status=self._overall_status(strategies),
            underperformers=[s.strategy_id for s in strategies if s.status == "UNDERPERFORM"],
            overperformers=[s.strategy_id for s in strategies if s.status == "OVERPERFORM"],
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: ReconciliationReport) -> None:
        """Append summary entry to ring-buffer JSON (atomic write)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        entry = {
            "date_str": report.date_str,
            "timestamp": report.timestamp,
            "total_capital_usd": report.total_capital_usd,
            "total_expected_pnl": report.total_expected_pnl,
            "total_actual_pnl": report.total_actual_pnl,
            "total_variance_usd": report.total_variance_usd,
            "overall_status": report.overall_status,
            "underperformers": report.underperformers,
            "overperformers": report.overperformers,
            "strategy_count": len(report.strategies),
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return list of saved summary entries; [] on missing/corrupt file."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

    def get_streak(self, status: str = "GREEN") -> int:
        """Count consecutive trailing reports that match *status*."""
        history = self.load_history()
        count = 0
        for entry in reversed(history):
            if entry.get("overall_status") == status:
                count += 1
            else:
                break
        return count
