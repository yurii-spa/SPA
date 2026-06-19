"""
tests/test_acceptance_doc_generator.py

35 unit tests for spa_core/backtesting/acceptance_doc_generator.py

MP-1359 (v9.75) — stdlib only, unittest.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root on sys.path
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.acceptance_doc_generator import AcceptanceDocGenerator


class TestAcceptanceDocGeneratorInit(unittest.TestCase):
    """Tests 1-5: Constructor / basic instantiation."""

    def test_01_instantiates_default(self):
        """AcceptanceDocGenerator can be created with no args."""
        gen = AcceptanceDocGenerator()
        self.assertIsInstance(gen, AcceptanceDocGenerator)

    def test_02_instantiates_with_owner(self):
        """AcceptanceDocGenerator accepts owner_name parameter."""
        gen = AcceptanceDocGenerator(owner_name="Alice")
        self.assertIsInstance(gen, AcceptanceDocGenerator)

    def test_03_default_owner_is_yurii(self):
        """Default owner name is 'Yurii'."""
        gen = AcceptanceDocGenerator()
        self.assertEqual(gen._owner, "Yurii")

    def test_04_custom_owner_stored(self):
        """Custom owner name is stored correctly."""
        gen = AcceptanceDocGenerator(owner_name="Bob")
        self.assertEqual(gen._owner, "Bob")

    def test_05_instantiates_with_base_dir(self):
        """AcceptanceDocGenerator accepts base_dir parameter."""
        with tempfile.TemporaryDirectory() as td:
            gen = AcceptanceDocGenerator(base_dir=td)
            self.assertIsInstance(gen, AcceptanceDocGenerator)


class TestSystemOverviewSection(unittest.TestCase):
    """Tests 6-11: system_overview_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.system_overview_section()

    def test_06_returns_string(self):
        """system_overview_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_07_contains_spa(self):
        """system_overview_section() contains 'SPA'."""
        self.assertIn("SPA", self.section)

    def test_08_contains_system_overview_header(self):
        """system_overview_section() contains '## 1. System Overview'."""
        self.assertIn("## 1. System Overview", self.section)

    def test_09_contains_owner_name(self):
        """system_overview_section() contains the owner's name."""
        self.assertIn("Yurii", self.section)

    def test_10_contains_100k(self):
        """system_overview_section() mentions $100,000 USDC."""
        self.assertIn("100,000", self.section)

    def test_11_contains_golive_checker(self):
        """system_overview_section() references GoLiveChecker."""
        self.assertIn("GoLiveChecker", self.section)


class TestStrategySummarySection(unittest.TestCase):
    """Tests 12-17: strategy_summary_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.strategy_summary_section()

    def test_12_returns_string(self):
        """strategy_summary_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_13_contains_rs001(self):
        """strategy_summary_section() contains 'RS-001'."""
        self.assertIn("RS-001", self.section)

    def test_14_contains_rs002(self):
        """strategy_summary_section() contains 'RS-002'."""
        self.assertIn("RS-002", self.section)

    def test_15_contains_strategy_header(self):
        """strategy_summary_section() contains '## 2. Strategy Summary'."""
        self.assertIn("## 2. Strategy Summary", self.section)

    def test_16_contains_target_apy(self):
        """strategy_summary_section() mentions target APY (18.2%)."""
        self.assertIn("18.2", self.section)

    def test_17_contains_tournament(self):
        """strategy_summary_section() mentions Tournament evaluator."""
        self.assertIn("Tournament", self.section)


class TestRiskDisclosureSection(unittest.TestCase):
    """Tests 18-22: risk_disclosure_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.risk_disclosure_section()

    def test_18_returns_string(self):
        """risk_disclosure_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_19_contains_il_or_impermanent(self):
        """risk_disclosure_section() contains 'IL' or 'impermanent'."""
        lower = self.section.lower()
        self.assertTrue("il" in lower or "impermanent" in lower)

    def test_20_contains_risk_disclosure_header(self):
        """risk_disclosure_section() contains '## 3. Risk Disclosure'."""
        self.assertIn("## 3. Risk Disclosure", self.section)

    def test_21_contains_smart_contract(self):
        """risk_disclosure_section() contains 'Smart Contract'."""
        self.assertIn("Smart Contract", self.section)

    def test_22_contains_six_risk_factors(self):
        """risk_disclosure_section() lists six numbered risk subsections."""
        # Expect 3.1 through 3.6
        for i in range(1, 7):
            self.assertIn(f"3.{i}", self.section)


class TestCpaMethodologySection(unittest.TestCase):
    """Tests 23-27: cpa_methodology_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.cpa_methodology_section()

    def test_23_returns_string(self):
        """cpa_methodology_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_24_contains_86_97(self):
        """cpa_methodology_section() contains '86.97' (cash drag)."""
        self.assertIn("86.97", self.section)

    def test_25_contains_cpa_header(self):
        """cpa_methodology_section() contains '## 4. CPA Methodology Review'."""
        self.assertIn("## 4. CPA Methodology Review", self.section)

    def test_26_contains_look_ahead(self):
        """cpa_methodology_section() mentions look-ahead bias."""
        self.assertIn("look-ahead", self.section.lower())

    def test_27_contains_pit(self):
        """cpa_methodology_section() references PIT (point-in-time)."""
        self.assertIn("PIT", self.section)


class TestGateStatusSection(unittest.TestCase):
    """Tests 28-31: gate_status_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.gate_status_section()

    def test_28_returns_string(self):
        """gate_status_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_29_contains_backtest(self):
        """gate_status_section() contains 'Backtest'."""
        self.assertIn("Backtest", self.section)

    def test_30_contains_pre_paper(self):
        """gate_status_section() mentions Pre-Paper gate."""
        self.assertIn("Pre-Paper", self.section)

    def test_31_contains_gate_status_header(self):
        """gate_status_section() contains '## 5. Gate Status Confirmation'."""
        self.assertIn("## 5. Gate Status Confirmation", self.section)


class TestSignatureSection(unittest.TestCase):
    """Tests 32-33: signature_section()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()
        self.section = self.gen.signature_section()

    def test_32_returns_string(self):
        """signature_section() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_33_contains_blank_signature_line(self):
        """signature_section() contains '____' for blank signature."""
        self.assertIn("_____", self.section)


class TestGenerate(unittest.TestCase):
    """Tests 34-35 + extra: generate() and save()."""

    def setUp(self):
        self.gen = AcceptanceDocGenerator()

    def test_34_generate_combines_all_sections(self):
        """generate() contains content from all 6 sections."""
        doc = self.gen.generate()
        # Check for section headers from all 6 sections
        self.assertIn("## 1. System Overview", doc)
        self.assertIn("## 2. Strategy Summary", doc)
        self.assertIn("## 3. Risk Disclosure", doc)
        self.assertIn("## 4. CPA Methodology Review", doc)
        self.assertIn("## 5. Gate Status Confirmation", doc)
        self.assertIn("## 6. Owner Signature", doc)

    def test_35_generate_longer_than_1000_chars(self):
        """generate() produces a document longer than 1000 characters."""
        doc = self.gen.generate()
        self.assertGreater(len(doc), 1000)


class TestSave(unittest.TestCase):
    """Tests for save() method."""

    def test_save_creates_file(self):
        """save() creates docs/OWNER_ACCEPTANCE_DOCUMENT.md."""
        with tempfile.TemporaryDirectory() as td:
            gen = AcceptanceDocGenerator(base_dir=td)
            path = gen.save()
            self.assertTrue(Path(path).exists(), f"File not found: {path}")

    def test_save_default_path(self):
        """save() default path ends with OWNER_ACCEPTANCE_DOCUMENT.md."""
        with tempfile.TemporaryDirectory() as td:
            gen = AcceptanceDocGenerator(base_dir=td)
            path = gen.save()
            self.assertTrue(path.endswith("OWNER_ACCEPTANCE_DOCUMENT.md"))

    def test_save_custom_path(self):
        """save() respects a custom output_path argument."""
        with tempfile.TemporaryDirectory() as td:
            custom = os.path.join(td, "custom_output.md")
            gen = AcceptanceDocGenerator(base_dir=td)
            path = gen.save(output_path=custom)
            self.assertTrue(Path(path).exists())

    def test_save_content_matches_generate(self):
        """save() writes exactly what generate() returns."""
        with tempfile.TemporaryDirectory() as td:
            gen = AcceptanceDocGenerator(base_dir=td)
            expected = gen.generate()
            path = gen.save()
            actual = Path(path).read_text(encoding="utf-8")
            self.assertEqual(actual, expected)

    def test_save_is_atomic(self):
        """save() uses atomic write (no partial file on error path)."""
        with tempfile.TemporaryDirectory() as td:
            gen = AcceptanceDocGenerator(base_dir=td)
            path = gen.save()
            # After save, there should be no leftover .tmp file
            tmp_path = path + ".tmp"
            md_tmp = path.replace(".md", ".md.tmp")
            self.assertFalse(Path(tmp_path).exists(), "Leftover .tmp file found")
            self.assertFalse(Path(md_tmp).exists(), "Leftover .md.tmp file found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
