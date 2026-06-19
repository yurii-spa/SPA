"""
spa_core/family_fund/investor_portfolio_view.py

Portfolio view for individual investors.
Shows: position, P&L, current APY, lockup status.

Pure stdlib. No external dependencies.
All data is read-only: never modifies allocator/risk/execution.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spa_core.family_fund.investor_registration import (
    InvestorRecord,
    InvestorRegistry,
    LOCK_UP_DAYS,
)

__all__ = [
    "InvestorPortfolioView",
    "InvestorPortfolioAPI",
]

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "family_fund" / "investor_registry.json"
)
_DEFAULT_PORTFOLIO_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "family_fund" / "portfolio_state.json"
)

# Fallback portfolio_state when the file does not exist yet
_EMPTY_PORTFOLIO_STATE: dict = {
    "total_nav_usd": 0.0,
    "current_apy_estimate": 0.0,
    "strategy_allocation": {"cash": 1.0},
}


@dataclass
class InvestorPortfolioView:
    """Computed portfolio snapshot for a single investor."""

    investor_id: str
    name: str
    invested_usd: float
    current_value_usd: float
    pnl_usd: float
    pnl_pct: float
    current_apy_estimate: float
    lockup_ends: str        # ISO date YYYY-MM-DD
    locked: bool
    days_until_unlock: int
    strategy_allocation: dict  # e.g. {"RS-001": 0.5, "cash": 0.5}


class InvestorPortfolioAPI:
    """
    Read-only portfolio views for Family Fund investors.

    Reads:
      - investor_registry.json  → InvestorRegistry (registration records)
      - portfolio_state.json    → current NAV + APY + strategy allocation

    Never writes to any file.
    """

    def __init__(
        self,
        registry_path: str = str(_DEFAULT_REGISTRY_PATH),
        portfolio_path: str = str(_DEFAULT_PORTFOLIO_PATH),
    ) -> None:
        self._registry_path = str(registry_path)
        self._portfolio_path = str(portfolio_path)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_registry(self) -> InvestorRegistry:
        reg = InvestorRegistry(registry_path=self._registry_path)
        reg.load()
        return reg

    def _load_portfolio_state(self) -> dict:
        p = Path(self._portfolio_path)
        if not p.exists():
            return dict(_EMPTY_PORTFOLIO_STATE)
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        # Ensure required keys with defaults
        return {
            "total_nav_usd": float(raw.get("total_nav_usd", 0.0)),
            "current_apy_estimate": float(raw.get("current_apy_estimate", 0.0)),
            "strategy_allocation": dict(raw.get("strategy_allocation", {"cash": 1.0})),
        }

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def get_view(self, investor_id: str) -> InvestorPortfolioView:
        """
        Compute and return the portfolio view for one investor.

        Raises:
            ValueError: if investor is not found or not APPROVED.
        """
        reg = self._load_registry()
        rec = reg.get(investor_id)
        if rec is None:
            raise ValueError(f"Investor not found: {investor_id!r}")
        if rec.status != "APPROVED":
            raise ValueError(
                f"Portfolio view only available for APPROVED investors; "
                f"investor {investor_id!r} has status {rec.status!r}"
            )

        state = self._load_portfolio_state()
        total_nav = state["total_nav_usd"]
        apy = state["current_apy_estimate"]
        alloc = state["strategy_allocation"]

        total_committed = reg.total_committed_usd()
        share_pct = self._compute_share(rec, total_committed)

        invested = rec.requested_amount_usd
        current_value = share_pct * total_nav if total_nav > 0 else invested
        pnl_usd = current_value - invested
        pnl_pct = pnl_usd / invested if invested > 0 else 0.0

        lock = self._compute_lockup(rec)

        return InvestorPortfolioView(
            investor_id=rec.investor_id,
            name=rec.name,
            invested_usd=invested,
            current_value_usd=round(current_value, 6),
            pnl_usd=round(pnl_usd, 6),
            pnl_pct=round(pnl_pct, 8),
            current_apy_estimate=apy,
            lockup_ends=lock["unlock_date"],
            locked=lock["locked"],
            days_until_unlock=lock["days_remaining"],
            strategy_allocation=alloc,
        )

    def investor_share_pct(self, investor_id: str) -> float:
        """
        Return this investor's fractional share of total committed capital (0.0–1.0).

        Raises:
            ValueError: if investor not found or not APPROVED.
        """
        reg = self._load_registry()
        rec = reg.get(investor_id)
        if rec is None:
            raise ValueError(f"Investor not found: {investor_id!r}")
        if rec.status != "APPROVED":
            raise ValueError(
                f"investor_share_pct only available for APPROVED investors; "
                f"status is {rec.status!r}"
            )
        total_committed = reg.total_committed_usd()
        return self._compute_share(rec, total_committed)

    def lockup_status(self, investor_id: str, today: str = None) -> dict:
        """
        Return lockup information for an investor.

        Returns:
            {locked: bool, days_remaining: int, unlock_date: str}

        Raises:
            ValueError: if investor not found or not APPROVED.
        """
        reg = self._load_registry()
        rec = reg.get(investor_id)
        if rec is None:
            raise ValueError(f"Investor not found: {investor_id!r}")
        if rec.status != "APPROVED":
            raise ValueError(
                f"lockup_status only available for APPROVED investors; "
                f"status is {rec.status!r}"
            )
        return self._compute_lockup(rec, today=today)

    def all_views(self) -> list:
        """Return InvestorPortfolioView for every APPROVED investor."""
        reg = self._load_registry()
        approved = reg.list_by_status("APPROVED")
        views = []
        state = self._load_portfolio_state()
        total_nav = state["total_nav_usd"]
        apy = state["current_apy_estimate"]
        alloc = state["strategy_allocation"]
        total_committed = reg.total_committed_usd()

        for rec in approved:
            share_pct = self._compute_share(rec, total_committed)
            invested = rec.requested_amount_usd
            current_value = share_pct * total_nav if total_nav > 0 else invested
            pnl_usd = current_value - invested
            pnl_pct = pnl_usd / invested if invested > 0 else 0.0
            lock = self._compute_lockup(rec)

            views.append(
                InvestorPortfolioView(
                    investor_id=rec.investor_id,
                    name=rec.name,
                    invested_usd=invested,
                    current_value_usd=round(current_value, 6),
                    pnl_usd=round(pnl_usd, 6),
                    pnl_pct=round(pnl_pct, 8),
                    current_apy_estimate=apy,
                    lockup_ends=lock["unlock_date"],
                    locked=lock["locked"],
                    days_until_unlock=lock["days_remaining"],
                    strategy_allocation=alloc,
                )
            )
        return views

    def fund_summary(self) -> dict:
        """
        Return high-level fund summary.

        Returns:
            {total_aum_usd, investor_count, blended_apy, total_committed_usd}
        """
        reg = self._load_registry()
        state = self._load_portfolio_state()
        approved = reg.list_by_status("APPROVED")
        return {
            "total_aum_usd": state["total_nav_usd"],
            "investor_count": len(approved),
            "blended_apy": state["current_apy_estimate"],
            "total_committed_usd": reg.total_committed_usd(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_share(rec: InvestorRecord, total_committed: float) -> float:
        """Fractional share (0.0–1.0) of the investor within approved pool."""
        if total_committed <= 0:
            return 0.0
        return rec.requested_amount_usd / total_committed

    @staticmethod
    def _compute_lockup(rec: InvestorRecord, today: str = None) -> dict:
        """
        Compute lockup status relative to `today` (YYYY-MM-DD).
        If `today` is None, uses the actual current date.
        """
        if rec.approved_at is None:
            # Not yet approved; treat as fully locked
            return {"locked": True, "days_remaining": LOCK_UP_DAYS, "unlock_date": ""}

        # Parse approved_at (ISO 8601, e.g. "2026-06-10T08:00:00Z")
        approved_date = _parse_iso_date(rec.approved_at)
        unlock_date = approved_date + datetime.timedelta(days=LOCK_UP_DAYS)

        if today is not None:
            today_date = datetime.date.fromisoformat(today)
        else:
            today_date = datetime.date.today()

        delta = (unlock_date - today_date).days
        locked = today_date < unlock_date
        days_remaining = max(0, delta)

        return {
            "locked": locked,
            "days_remaining": days_remaining,
            "unlock_date": unlock_date.isoformat(),
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_iso_date(iso_str: str) -> datetime.date:
    """
    Parse a date or datetime ISO string to datetime.date.
    Handles:
      "2026-06-10"
      "2026-06-10T08:00:00Z"
      "2026-06-10T08:00:00"
    """
    s = iso_str.strip().replace("Z", "")
    # Take only the date part
    date_part = s[:10]
    return datetime.date.fromisoformat(date_part)
