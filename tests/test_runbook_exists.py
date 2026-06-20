"""
tests/test_runbook_exists.py
MP-1516 (v11.32): 15 tests verifying docs/RUNBOOK.md existence, length, and content.
"""

import os
import unittest

RUNBOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "RUNBOOK.md")


def _read():
    with open(RUNBOOK_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestRunbookExists(unittest.TestCase):
    """Basic existence and size checks."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(RUNBOOK_PATH), "RUNBOOK.md must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(RUNBOOK_PATH), 500)

    def test_word_count_exceeds_600(self):
        words = _read().split()
        self.assertGreater(len(words), 600,
                           f"RUNBOOK must be 600+ words, got {len(words)}")


class TestRunbookDailyOperations(unittest.TestCase):
    """Daily operations section is present and well-formed."""

    def test_has_daily_operations_section(self):
        self.assertIn("Daily Operations", _read())

    def test_mentions_launchd(self):
        self.assertIn("launchd", _read())

    def test_mentions_golive_checker(self):
        self.assertIn("golive_checker", _read())

    def test_mentions_morning_check(self):
        self.assertIn("Morning Check", _read())

    def test_mentions_weekly_review(self):
        self.assertIn("Weekly Review", _read())


class TestRunbookEmergencyProcedures(unittest.TestCase):
    """Emergency procedures section is present."""

    def test_has_emergency_procedures_section(self):
        self.assertIn("Emergency Procedures", _read())

    def test_mentions_circuit_breaker(self):
        self.assertIn("Circuit Breaker", _read())

    def test_mentions_data_source_outage(self):
        self.assertIn("Data Source Outage", _read())

    def test_mentions_live_trading_gate(self):
        self.assertIn("Live Trading Gate", _read())

    def test_mentions_gap_monitor(self):
        self.assertIn("gap_monitor", _read())


class TestRunbookMonitoringSection(unittest.TestCase):
    """Monitoring and push sections."""

    def test_has_monitoring_section(self):
        self.assertIn("Monitoring", _read())

    def test_has_push_section(self):
        self.assertIn("Push to GitHub", _read())

    def test_mentions_telegram(self):
        self.assertIn("Telegram", _read())


if __name__ == "__main__":
    unittest.main()
