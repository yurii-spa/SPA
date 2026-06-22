"""
tests/test_adr_documents.py
MP-1515 (v11.31): 25 tests verifying ADR-037/038/039/040 existence and format.
"""

import os
import unittest

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "adr")

ADR_FILES = {
    "ADR-037": "ADR-037-walk-forward-validation.md",
    "ADR-038": "ADR-038-monte-carlo-robustness.md",
    "ADR-039": "ADR-039-drawdown-circuit-breaker.md",
    "ADR-040": "ADR-040-strategy-demotion-policy.md",
}

REQUIRED_SECTIONS = ["## Status", "## Context", "## Decision", "## Consequences"]


def _path(filename):
    return os.path.join(DOCS_DIR, filename)


def _read(filename):
    with open(_path(filename), "r", encoding="utf-8") as f:
        return f.read()


class TestADR037Exists(unittest.TestCase):
    """ADR-037 Walk-Forward Validation — file existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_path(ADR_FILES["ADR-037"])),
                        "ADR-037 file must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(_path(ADR_FILES["ADR-037"])), 100)

    def test_has_status_section(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("## Status", content)

    def test_status_accepted(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("Accepted", content)

    def test_has_decision_section(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("## Decision", content)

    def test_mentions_training_window(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("Training window", content)

    def test_mentions_oos_sharpe(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("OOS Sharpe", content)

    def test_mentions_degradation_ratio(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("degradation ratio", content)

    def test_mentions_implementation(self):
        content = _read(ADR_FILES["ADR-037"])
        self.assertIn("walk_forward_validator", content)


class TestADR038Exists(unittest.TestCase):
    """ADR-038 Monte Carlo Robustness — file existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_path(ADR_FILES["ADR-038"])),
                        "ADR-038 file must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(_path(ADR_FILES["ADR-038"])), 100)

    def test_status_accepted(self):
        content = _read(ADR_FILES["ADR-038"])
        self.assertIn("Accepted", content)

    def test_has_context_section(self):
        content = _read(ADR_FILES["ADR-038"])
        self.assertIn("## Context", content)

    def test_mentions_simulations(self):
        content = _read(ADR_FILES["ADR-038"])
        self.assertIn("1,000", content)

    def test_mentions_implementation(self):
        content = _read(ADR_FILES["ADR-038"])
        self.assertIn("monte_carlo_robustness", content)


class TestADR039Exists(unittest.TestCase):
    """ADR-039 Drawdown Circuit Breaker — file existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_path(ADR_FILES["ADR-039"])),
                        "ADR-039 file must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(_path(ADR_FILES["ADR-039"])), 100)

    def test_status_accepted(self):
        content = _read(ADR_FILES["ADR-039"])
        self.assertIn("Accepted", content)

    def test_mentions_yellow_level(self):
        content = _read(ADR_FILES["ADR-039"])
        self.assertIn("YELLOW", content)

    def test_mentions_black_level(self):
        content = _read(ADR_FILES["ADR-039"])
        self.assertIn("BLACK", content)

    def test_mentions_circuit_breaker_module(self):
        content = _read(ADR_FILES["ADR-039"])
        self.assertIn("circuit_breaker", content)


class TestADR040Exists(unittest.TestCase):
    """ADR-040 Strategy Demotion Policy — file existence and structure."""

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(_path(ADR_FILES["ADR-040"])),
                        "ADR-040 file must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(_path(ADR_FILES["ADR-040"])), 100)

    def test_status_accepted(self):
        content = _read(ADR_FILES["ADR-040"])
        self.assertIn("Accepted", content)

    def test_mentions_probation(self):
        content = _read(ADR_FILES["ADR-040"])
        self.assertIn("PROBATION", content)

    def test_mentions_archived(self):
        content = _read(ADR_FILES["ADR-040"])
        self.assertIn("ARCHIVED", content)

    def test_mentions_demotion_engine(self):
        content = _read(ADR_FILES["ADR-040"])
        self.assertIn("demotion_engine", content)

    def test_extends_adr023(self):
        content = _read(ADR_FILES["ADR-040"])
        self.assertIn("ADR-023", content)


class TestAllADRsHaveRequiredSections(unittest.TestCase):
    """All four ADRs must have the 4 mandatory sections."""

    def test_all_adr_files_have_status(self):
        for key, fname in ADR_FILES.items():
            with self.subTest(adr=key):
                content = _read(fname)
                self.assertIn("## Status", content, f"{key} missing ## Status")

    def test_all_adr_files_have_context(self):
        for key, fname in ADR_FILES.items():
            with self.subTest(adr=key):
                content = _read(fname)
                self.assertIn("## Context", content, f"{key} missing ## Context")

    def test_all_adr_files_have_decision(self):
        for key, fname in ADR_FILES.items():
            with self.subTest(adr=key):
                content = _read(fname)
                self.assertIn("## Decision", content, f"{key} missing ## Decision")

    def test_all_adr_files_have_consequences(self):
        for key, fname in ADR_FILES.items():
            with self.subTest(adr=key):
                content = _read(fname)
                self.assertIn("## Consequences", content,
                              f"{key} missing ## Consequences")


if __name__ == "__main__":
    unittest.main()
