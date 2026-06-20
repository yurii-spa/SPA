"""
tests/test_financial_complete.py

MP-1464 (v10.80): 15 tests verifying Financial category reaches 15/15.

Tests cover:
  - capital_config.json has starting_capital >= $100K (+3)
  - paper_trading_status.json has capital >= $100K (+2)
  - spa_core/risk/policy.py exists and is non-trivial (+2)
  - spa_core/analytics/fee_structure.py exists (+2)
  - docs/legal/ONBOARDING_CHECKLIST.md exists (+2)
  - equity_curve_daily.json has >= 7 daily entries (+2)
  - paper_trading_status.json is_demo=False (+2)
  - assess_financial() returns score == 15/15
"""

import json
import os
import sys
import unittest
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport

_DATA = Path(_REPO) / "data"
_DOCS = Path(_REPO) / "docs"
_CORE = Path(_REPO) / "spa_core"


# ---------------------------------------------------------------------------
# 1. capital_config.json
# ---------------------------------------------------------------------------

class TestCapitalConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = json.loads((_DATA / "capital_config.json").read_text())

    def test_file_exists(self):
        self.assertTrue((_DATA / "capital_config.json").exists())

    def test_starting_capital_key(self):
        cap = self.cfg.get("capital", {})
        self.assertIn("starting_capital_usd", cap,
                      "capital_config must have capital.starting_capital_usd")

    def test_starting_capital_gte_100k(self):
        cap = self.cfg.get("capital", {})
        self.assertGreaterEqual(
            cap.get("starting_capital_usd", 0), 100_000,
            "starting_capital_usd must be >= 100000"
        )


# ---------------------------------------------------------------------------
# 2. paper_trading_status.json
# ---------------------------------------------------------------------------

class TestPaperTradingStatus(unittest.TestCase):

    def setUp(self):
        self.pts = json.loads((_DATA / "paper_trading_status.json").read_text())

    def test_is_demo_false(self):
        self.assertFalse(
            self.pts.get("is_demo", True),
            "paper_trading_status.is_demo must be False"
        )

    def test_capital_gte_100k(self):
        capital = float(
            self.pts.get("virtual_capital",
                self.pts.get("total_capital",
                    self.pts.get("capital",
                        self.pts.get("current_equity", 0))))
        )
        self.assertGreaterEqual(capital, 100_000,
                                f"capital {capital} must be >= 100000")


# ---------------------------------------------------------------------------
# 3. Risk policy + fee structure
# ---------------------------------------------------------------------------

class TestInfrastructureFiles(unittest.TestCase):

    def test_risk_policy_exists(self):
        p = _CORE / "risk" / "policy.py"
        self.assertTrue(p.exists(), "spa_core/risk/policy.py must exist")

    def test_risk_policy_non_trivial(self):
        p = _CORE / "risk" / "policy.py"
        self.assertGreater(p.stat().st_size, 100,
                           "risk/policy.py must be > 100 bytes")

    def test_fee_structure_exists(self):
        p = _CORE / "analytics" / "fee_structure.py"
        self.assertTrue(p.exists(), "spa_core/analytics/fee_structure.py must exist")

    def test_fee_structure_non_trivial(self):
        p = _CORE / "analytics" / "fee_structure.py"
        self.assertGreater(p.stat().st_size, 200,
                           "fee_structure.py must be > 200 bytes")

    def test_kyc_checklist_exists(self):
        p = _DOCS / "legal" / "ONBOARDING_CHECKLIST.md"
        self.assertTrue(p.exists(), "docs/legal/ONBOARDING_CHECKLIST.md must exist")

    def test_kyc_checklist_non_trivial(self):
        p = _DOCS / "legal" / "ONBOARDING_CHECKLIST.md"
        self.assertGreaterEqual(p.stat().st_size, 200,
                                "ONBOARDING_CHECKLIST.md must be >= 200 bytes")


# ---------------------------------------------------------------------------
# 4. equity_curve_daily.json — >= 7 days
# ---------------------------------------------------------------------------

class TestEquityCurve(unittest.TestCase):

    def setUp(self):
        self.eq = json.loads((_DATA / "equity_curve_daily.json").read_text())

    def test_file_exists(self):
        self.assertTrue((_DATA / "equity_curve_daily.json").exists())

    def test_has_daily_list(self):
        self.assertIn("daily", self.eq)
        self.assertIsInstance(self.eq["daily"], list)

    def test_daily_entries_gte_7(self):
        entries = self.eq.get("daily", [])
        self.assertGreaterEqual(
            len(entries), 7,
            f"equity_curve_daily must have >= 7 entries, got {len(entries)}"
        )

    def test_summary_num_days_gte_7(self):
        num_days = self.eq.get("summary", {}).get("num_days", 0)
        self.assertGreaterEqual(num_days, 7,
                                f"summary.num_days must be >= 7, got {num_days}")


# ---------------------------------------------------------------------------
# 5. assess_financial() == 15/15
# ---------------------------------------------------------------------------

class TestAssessFinancialScore(unittest.TestCase):

    def setUp(self):
        self.report = GoLiveReadinessReport(base_dir=_REPO)
        self.cat = self.report.assess_financial()

    def test_score_is_15(self):
        self.assertEqual(self.cat.score, 15.0,
                         f"Financial score must be 15, got {self.cat.score}")

    def test_max_score_is_15(self):
        self.assertEqual(self.cat.max_score, 15.0)

    def test_no_pending_items(self):
        self.assertEqual(
            self.cat.items_pending, [],
            f"No items should be pending, got: {self.cat.items_pending}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
