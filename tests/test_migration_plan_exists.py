"""
test_migration_plan_exists.py — MP-1405

Verifies that the BaseAnalytics migration plan document exists and
contains required structural elements.

Run:
    python3 -m pytest tests/test_migration_plan_exists.py -v
"""
import os
import unittest

PLAN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "BASEANALYTICS_MIGRATION_PLAN.md"
)


class TestMigrationPlanExists(unittest.TestCase):
    def test_plan_file_exists(self):
        """docs/BASEANALYTICS_MIGRATION_PLAN.md must exist."""
        self.assertTrue(
            os.path.exists(PLAN_PATH),
            f"Migration plan not found at: {PLAN_PATH}",
        )

    def test_plan_has_phases(self):
        """Plan must contain Phase 1, Phase 2, and Phase 3 sections."""
        with open(PLAN_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Phase 1", content)
        self.assertIn("Phase 2", content)
        self.assertIn("Phase 3", content)

    def test_plan_has_migration_pattern(self):
        """Plan must describe the migration pattern (Before/After)."""
        with open(PLAN_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("BaseAnalytics", content)
        self.assertIn("OUTPUT_PATH", content)
        self.assertIn("to_dict", content)

    def test_plan_has_priority_modules(self):
        """Plan must list at least 5 priority modules for Phase 1."""
        with open(PLAN_PATH, encoding="utf-8") as f:
            content = f.read()
        # At least the top 5 candidates should be mentioned
        for mod in [
            "apy_milestone_tracker",
            "protocol_risk_scorer",
            "liquidity_stress_simulator",
            "rebalance_trigger_engine",
            "apy_tracker",
        ]:
            self.assertIn(mod, content, f"Priority module not listed: {mod}")

    def test_plan_has_verification_section(self):
        """Plan must include a Verification section."""
        with open(PLAN_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Verification", content)

    def test_plan_not_empty(self):
        """Plan must be substantial (> 1000 chars)."""
        with open(PLAN_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertGreater(len(content), 1000, "Plan file seems too short")


if __name__ == "__main__":
    unittest.main(verbosity=2)
