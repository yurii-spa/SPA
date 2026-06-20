"""
SPA Family Fund — P&L Attribution Engine (Phase 0)
Reads equity data + investor registry, produces per-investor statements.
Pure stdlib. No external dependencies. Strictly read-only advisory; never
modifies allocator/risk/execution.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.family_fund.models import Investor, InvestorStatement
from spa_core.family_fund.registry import InvestorRegistry
from spa_core.utils.atomic import atomic_save

__all__ = ["PnLAttributor"]

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_STATEMENTS_DIR = _DATA_DIR / "statements"


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via atomic_save."""
    atomic_save(data, str(path))


def _annualize_monthly_return(monthly_return: float) -> float:
    """Convert a simple monthly return fraction to annualized APY."""
    return (1.0 + monthly_return) ** 12 - 1.0


class PnLAttributor:
    """
    Compute per-investor P&L statements for a given period (YYYY-MM).

    Data sources:
      - data/equity_curve_daily.json  — daily equity points
      - data/investors.json           — investor registry
      - data/paper_trading_status.json — latest AUM
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        registry: Optional[InvestorRegistry] = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._registry = registry or InvestorRegistry(
            investors_path=self._data_dir / "investors.json"
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_equity_curve(self) -> List[dict]:
        """Load equity_curve_daily.json → list of {date, equity, ...}."""
        path = self._data_dir / "equity_curve_daily.json"
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Support both list and {"curve": [...]} shapes
        if isinstance(data, list):
            return data
        return data.get("curve", data.get("equity_curve", []))

    def _load_paper_status(self) -> dict:
        """Load paper_trading_status.json."""
        path = self._data_dir / "paper_trading_status.json"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _filter_curve_for_period(
        self, curve: List[dict], period: str
    ) -> List[dict]:
        """Return curve points belonging to YYYY-MM period."""
        return [p for p in curve if str(p.get("date", "")).startswith(period)]

    def _opening_equity(self, curve: List[dict], period: str) -> float:
        """
        Equity at the start of the period: last point from the PREVIOUS
        month, or the first point of the period itself.
        """
        year, month = int(period[:4]), int(period[5:7])
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev_prefix = f"{prev_year:04d}-{prev_month:02d}"
        prev_points = [
            p for p in curve if str(p.get("date", "")).startswith(prev_prefix)
        ]
        if prev_points:
            last_prev = sorted(prev_points, key=lambda p: p["date"])[-1]
            return float(last_prev.get("equity", last_prev.get("total_value", 0.0)))

        # Fallback: use first point of the current period
        period_points = self._filter_curve_for_period(curve, period)
        if period_points:
            first = sorted(period_points, key=lambda p: p["date"])[0]
            return float(first.get("equity", first.get("total_value", 0.0)))
        return 0.0

    def _closing_equity(self, curve: List[dict], period: str) -> float:
        """Last equity value within the period."""
        points = self._filter_curve_for_period(curve, period)
        if not points:
            return 0.0
        last = sorted(points, key=lambda p: p["date"])[-1]
        return float(last.get("equity", last.get("total_value", 0.0)))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def compute_period_pnl(self, period: str) -> Dict[str, InvestorStatement]:
        """
        Compute P&L for each investor for the given period.

        Returns {investor_id: InvestorStatement}.
        """
        curve = self._load_equity_curve()
        opening_fund = self._opening_equity(curve, period)
        closing_fund = self._closing_equity(curve, period)
        fund_pnl = closing_fund - opening_fund
        fund_pnl_pct = (fund_pnl / opening_fund) if opening_fund > 0 else 0.0

        investors = self._registry.active_investors()
        generated_at = self._now_iso()
        result: Dict[str, InvestorStatement] = {}

        for inv in investors:
            share = inv.current_share_pct / 100.0
            # Opening / closing balance = investor's proportional slice of fund
            opening_bal = opening_fund * share
            closing_bal = closing_fund * share
            pnl_usd = fund_pnl * share
            pnl_pct = fund_pnl_pct  # same rate for all (pro-rata)
            apy = _annualize_monthly_return(pnl_pct)

            stmt = InvestorStatement(
                investor_id=inv.id,
                period=period,
                opening_balance=round(opening_bal, 2),
                closing_balance=round(closing_bal, 2),
                pnl_usd=round(pnl_usd, 2),
                pnl_pct=round(pnl_pct * 100.0, 4),  # stored as %
                apy_annualized=round(apy * 100.0, 4),  # stored as %
                generated_at=generated_at,
            )
            result[inv.id] = stmt

        return result

    def generate_all_statements(self, period: str) -> List[InvestorStatement]:
        """
        Compute and persist statements for all active investors.
        Saves to {data_dir}/statements/{period}_{investor_id}.json atomically.
        Returns the list of statements.
        """
        statements_map = self.compute_period_pnl(period)
        statements: List[InvestorStatement] = list(statements_map.values())
        stmts_dir = self._data_dir / "statements"

        for stmt in statements:
            filename = f"{period}_{stmt.investor_id}.json"
            out_path = stmts_dir / filename
            _atomic_write(out_path, stmt.to_dict())

        return statements

    def fund_summary(self, period: str) -> dict:
        """
        Return a summary dict for the fund for the given period:
          - total_aum_usd, opening_aum_usd, closing_aum_usd
          - total_pnl_usd, total_pnl_pct
          - nav_per_share (relative to fund start)
          - apy_annualized
          - active_investors
          - best_investor_id, worst_investor_id
        """
        curve = self._load_equity_curve()
        opening = self._opening_equity(curve, period)
        closing = self._closing_equity(curve, period)
        pnl = closing - opening
        pnl_pct = (pnl / opening) if opening > 0 else 0.0
        apy = _annualize_monthly_return(pnl_pct)

        statements_map = self.compute_period_pnl(period)

        best_id: Optional[str] = None
        worst_id: Optional[str] = None
        best_pnl = -math.inf
        worst_pnl = math.inf

        for inv_id, stmt in statements_map.items():
            if stmt.pnl_usd > best_pnl:
                best_pnl = stmt.pnl_usd
                best_id = inv_id
            if stmt.pnl_usd < worst_pnl:
                worst_pnl = stmt.pnl_usd
                worst_id = inv_id

        return {
            "period": period,
            "opening_aum_usd": round(opening, 2),
            "closing_aum_usd": round(closing, 2),
            "total_aum_usd": round(closing, 2),
            "total_pnl_usd": round(pnl, 2),
            "total_pnl_pct": round(pnl_pct * 100.0, 4),
            "apy_annualized": round(apy * 100.0, 4),
            "active_investors": len(statements_map),
            "best_investor_id": best_id,
            "worst_investor_id": worst_id,
            "generated_at": self._now_iso(),
        }
