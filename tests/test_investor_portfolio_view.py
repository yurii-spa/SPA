"""
tests/test_investor_portfolio_view.py

MP-1366 — 35 unit tests for spa_core/family_fund/investor_portfolio_view.py

Run:
    python3 -m unittest tests.test_investor_portfolio_view -v
    python3 -m unittest tests/test_investor_portfolio_view.py -v
"""

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from spa_core.family_fund.investor_registration import InvestorRegistry, LOCK_UP_DAYS
from spa_core.family_fund.investor_portfolio_view import (
    InvestorPortfolioView,
    InvestorPortfolioAPI,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _write_portfolio_state(path: str, total_nav: float = 120_000.0,
                            apy: float = 0.08,
                            alloc: dict = None) -> None:
    if alloc is None:
        alloc = {"RS-001": 0.6, "cash": 0.4}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(
            {"total_nav_usd": total_nav, "current_apy_estimate": apy,
             "strategy_allocation": alloc},
            fh,
        )


def _make_approved_registry(tmp_dir: str, investors: list) -> str:
    """
    investors: list of (name, email, amount_usd)
    Returns path to saved registry.
    """
    path = os.path.join(tmp_dir, "investor_registry.json")
    reg = InvestorRegistry(registry_path=path)
    reg.load()
    for name, email, amount in investors:
        rec = reg.register(name=name, email=email, amount_usd=amount)
        reg.approve(rec.investor_id)
    reg.save()
    return path


def _make_api(tmp_dir: str, investors: list,
              nav: float = 120_000.0, apy: float = 0.08) -> tuple:
    """Returns (api, registry_path, portfolio_path, first_investor_id)."""
    reg_path = _make_approved_registry(tmp_dir, investors)
    port_path = os.path.join(tmp_dir, "portfolio_state.json")
    _write_portfolio_state(port_path, total_nav=nav, apy=apy)
    api = InvestorPortfolioAPI(registry_path=reg_path, portfolio_path=port_path)

    # Get first investor's ID
    reg = InvestorRegistry(registry_path=reg_path)
    reg.load()
    approved = reg.list_by_status("APPROVED")
    first_id = approved[0].investor_id if approved else None
    return api, reg_path, port_path, first_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetView(unittest.TestCase):
    """Tests for get_view()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api, self.reg_path, self.port_path, self.investor_id = _make_api(
            self.tmp,
            [("Alice", "alice@x.com", 40_000.0),
             ("Bob", "bob@x.com", 60_000.0)],
            nav=120_000.0,
        )

    def test_get_view_returns_investor_portfolio_view(self):
        view = self.api.get_view(self.investor_id)
        self.assertIsInstance(view, InvestorPortfolioView)

    def test_get_view_investor_id_matches(self):
        view = self.api.get_view(self.investor_id)
        self.assertEqual(view.investor_id, self.investor_id)

    def test_get_view_name_matches(self):
        view = self.api.get_view(self.investor_id)
        self.assertIn(view.name, ["Alice", "Bob"])

    def test_get_view_invested_usd_correct(self):
        # Alice invested 40k out of 100k → 40% share → 48k current
        view = self.api.get_view(self.investor_id)
        self.assertAlmostEqual(view.invested_usd, 40_000.0, places=2)

    def test_get_view_pnl_usd_computed(self):
        # 40k→48k → pnl = 8k
        view = self.api.get_view(self.investor_id)
        self.assertAlmostEqual(view.pnl_usd, view.current_value_usd - view.invested_usd,
                               places=4)

    def test_get_view_pnl_pct_formula(self):
        view = self.api.get_view(self.investor_id)
        expected = (view.current_value_usd - view.invested_usd) / view.invested_usd
        self.assertAlmostEqual(view.pnl_pct, expected, places=6)

    def test_get_view_apy_from_portfolio_state(self):
        view = self.api.get_view(self.investor_id)
        self.assertAlmostEqual(view.current_apy_estimate, 0.08)

    def test_get_view_strategy_allocation_present(self):
        view = self.api.get_view(self.investor_id)
        self.assertIsInstance(view.strategy_allocation, dict)
        self.assertGreater(len(view.strategy_allocation), 0)

    def test_get_view_raises_for_unknown_investor(self):
        with self.assertRaises(ValueError):
            self.api.get_view("nonexistent-id")

    def test_get_view_raises_for_pending_investor(self):
        # Register but don't approve
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.register("Pending", "pending@x.com", 15_000.0)
        reg.save()
        with self.assertRaises(ValueError):
            self.api.get_view(rec.investor_id)

    def test_get_view_raises_for_rejected_investor(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.register("Rejected", "rejected@x.com", 15_000.0)
        reg.reject(rec.investor_id, reason="Test")
        reg.save()
        with self.assertRaises(ValueError):
            self.api.get_view(rec.investor_id)

    def test_get_view_lockup_ends_is_date_string(self):
        view = self.api.get_view(self.investor_id)
        # Should be YYYY-MM-DD
        parts = view.lockup_ends.split("-")
        self.assertEqual(len(parts), 3)


class TestInvestorSharePct(unittest.TestCase):
    """Tests for investor_share_pct()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api, self.reg_path, _, _ = _make_api(
            self.tmp,
            [("Alice", "alice@x.com", 30_000.0),
             ("Bob", "bob@x.com", 70_000.0)],
        )
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        approved = reg.list_by_status("APPROVED")
        self.ids = {r.name: r.investor_id for r in approved}

    def test_shares_sum_to_one(self):
        total = sum(
            self.api.investor_share_pct(iid) for iid in self.ids.values()
        )
        self.assertAlmostEqual(total, 1.0, places=8)

    def test_alice_share_is_30_pct(self):
        share = self.api.investor_share_pct(self.ids["Alice"])
        self.assertAlmostEqual(share, 0.30, places=8)

    def test_bob_share_is_70_pct(self):
        share = self.api.investor_share_pct(self.ids["Bob"])
        self.assertAlmostEqual(share, 0.70, places=8)

    def test_share_raises_for_unknown(self):
        with self.assertRaises(ValueError):
            self.api.investor_share_pct("ghost")


class TestLockupStatus(unittest.TestCase):
    """Tests for lockup_status()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api, self.reg_path, _, self.investor_id = _make_api(
            self.tmp,
            [("Dave", "dave@x.com", 25_000.0)],
        )

    def test_locked_immediately_after_approval(self):
        status = self.api.lockup_status(self.investor_id, today="2026-06-10")
        # Get the approved_at date from registry and check
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = rec.approved_at[:10]
        # Today is same as approved_at → locked
        status = self.api.lockup_status(self.investor_id, today=approved_date)
        self.assertTrue(status["locked"])

    def test_locked_is_false_after_91_days(self):
        # Override today to 91 days after approval
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = datetime.date.fromisoformat(rec.approved_at[:10])
        future = (approved_date + datetime.timedelta(days=91)).isoformat()
        status = self.api.lockup_status(self.investor_id, today=future)
        self.assertFalse(status["locked"])

    def test_days_remaining_at_day_0(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = rec.approved_at[:10]
        status = self.api.lockup_status(self.investor_id, today=approved_date)
        self.assertEqual(status["days_remaining"], LOCK_UP_DAYS)

    def test_days_remaining_lte_90_at_day_0(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = rec.approved_at[:10]
        status = self.api.lockup_status(self.investor_id, today=approved_date)
        self.assertLessEqual(status["days_remaining"], 90)

    def test_days_remaining_zero_after_unlock(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = datetime.date.fromisoformat(rec.approved_at[:10])
        future = (approved_date + datetime.timedelta(days=100)).isoformat()
        status = self.api.lockup_status(self.investor_id, today=future)
        self.assertEqual(status["days_remaining"], 0)

    def test_unlock_date_is_90_days_after_approval(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.get(self.investor_id)
        approved_date = datetime.date.fromisoformat(rec.approved_at[:10])
        expected_unlock = (approved_date + datetime.timedelta(days=LOCK_UP_DAYS)).isoformat()
        status = self.api.lockup_status(self.investor_id)
        self.assertEqual(status["unlock_date"], expected_unlock)

    def test_lockup_raises_for_non_approved(self):
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        rec = reg.register("Pending2", "p2@x.com", 20_000.0)
        reg.save()
        with self.assertRaises(ValueError):
            self.api.lockup_status(rec.investor_id)

    def test_lockup_raises_for_unknown(self):
        with self.assertRaises(ValueError):
            self.api.lockup_status("nobody")


class TestAllViews(unittest.TestCase):
    """Tests for all_views()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api, self.reg_path, _, _ = _make_api(
            self.tmp,
            [("E1", "e1@x.com", 20_000.0),
             ("E2", "e2@x.com", 30_000.0),
             ("E3", "e3@x.com", 50_000.0)],
        )
        # Add a pending investor (should not appear in all_views)
        reg = InvestorRegistry(registry_path=self.reg_path)
        reg.load()
        reg.register("Pending", "pending@x.com", 10_000.0)
        reg.save()

    def test_all_views_count_equals_approved_count(self):
        views = self.api.all_views()
        self.assertEqual(len(views), 3)

    def test_all_views_returns_only_approved(self):
        views = self.api.all_views()
        names = {v.name for v in views}
        self.assertNotIn("Pending", names)

    def test_all_views_returns_list(self):
        self.assertIsInstance(self.api.all_views(), list)

    def test_all_views_each_is_investor_portfolio_view(self):
        for v in self.api.all_views():
            self.assertIsInstance(v, InvestorPortfolioView)

    def test_all_views_shares_sum_to_invested(self):
        # Total invested_usd across all views = total_committed
        views = self.api.all_views()
        total_invested = sum(v.invested_usd for v in views)
        self.assertAlmostEqual(total_invested, 100_000.0, places=2)


class TestFundSummary(unittest.TestCase):
    """Tests for fund_summary()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api, _, _, _ = _make_api(
            self.tmp,
            [("F1", "f1@x.com", 50_000.0),
             ("F2", "f2@x.com", 50_000.0)],
            nav=115_000.0,
            apy=0.07,
        )

    def test_fund_summary_has_total_aum_usd(self):
        summary = self.api.fund_summary()
        self.assertIn("total_aum_usd", summary)

    def test_fund_summary_has_investor_count(self):
        summary = self.api.fund_summary()
        self.assertIn("investor_count", summary)

    def test_fund_summary_investor_count_correct(self):
        summary = self.api.fund_summary()
        self.assertEqual(summary["investor_count"], 2)

    def test_fund_summary_total_aum_from_portfolio_state(self):
        summary = self.api.fund_summary()
        self.assertAlmostEqual(summary["total_aum_usd"], 115_000.0)

    def test_fund_summary_blended_apy(self):
        summary = self.api.fund_summary()
        self.assertIn("blended_apy", summary)
        self.assertAlmostEqual(summary["blended_apy"], 0.07)

    def test_fund_summary_total_committed_usd(self):
        summary = self.api.fund_summary()
        self.assertIn("total_committed_usd", summary)
        self.assertAlmostEqual(summary["total_committed_usd"], 100_000.0)


class TestNoPortfolioFile(unittest.TestCase):
    """Behaviour when portfolio_state.json is missing."""

    def test_get_view_without_portfolio_file(self):
        tmp = tempfile.mkdtemp()
        reg_path = _make_approved_registry(tmp, [("Solo", "solo@x.com", 10_000.0)])
        port_path = os.path.join(tmp, "nonexistent_portfolio.json")
        api = InvestorPortfolioAPI(registry_path=reg_path, portfolio_path=port_path)

        reg = InvestorRegistry(registry_path=reg_path)
        reg.load()
        rec = reg.list_by_status("APPROVED")[0]

        # Should not raise; falls back to invested_usd as current value
        view = api.get_view(rec.investor_id)
        self.assertIsInstance(view, InvestorPortfolioView)

    def test_fund_summary_without_portfolio_file(self):
        tmp = tempfile.mkdtemp()
        reg_path = _make_approved_registry(tmp, [("Solo", "solo@x.com", 10_000.0)])
        port_path = os.path.join(tmp, "nonexistent_portfolio.json")
        api = InvestorPortfolioAPI(registry_path=reg_path, portfolio_path=port_path)
        summary = api.fund_summary()
        self.assertIn("total_aum_usd", summary)
        self.assertAlmostEqual(summary["total_aum_usd"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
