"""
tests/test_investment_memo_generator.py

30 unit tests for spa_core/analytics/investment_memo_generator.py

MP-1360 (v9.76) — stdlib only, unittest.
"""
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Ensure repo root on sys.path
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.investment_memo_generator import (
    InvestmentMemoConfig,
    InvestmentMemoGenerator,
)


class TestInvestmentMemoConfig(unittest.TestCase):
    """Tests 1-5: InvestmentMemoConfig defaults and custom values."""

    def test_01_default_mgmt_fee(self):
        """InvestmentMemoConfig has mgmt_fee_pct=1.5 by default."""
        cfg = InvestmentMemoConfig()
        self.assertAlmostEqual(cfg.mgmt_fee_pct, 1.5)

    def test_02_default_perf_fee(self):
        """InvestmentMemoConfig has perf_fee_pct=20.0 by default."""
        cfg = InvestmentMemoConfig()
        self.assertAlmostEqual(cfg.perf_fee_pct, 20.0)

    def test_03_default_min_investment(self):
        """InvestmentMemoConfig has min_investment_usd=10_000.0 by default."""
        cfg = InvestmentMemoConfig()
        self.assertAlmostEqual(cfg.min_investment_usd, 10_000.0)

    def test_04_default_lock_up_days(self):
        """InvestmentMemoConfig has lock_up_days=90 by default."""
        cfg = InvestmentMemoConfig()
        self.assertEqual(cfg.lock_up_days, 90)

    def test_05_custom_mgmt_fee(self):
        """InvestmentMemoConfig accepts custom mgmt_fee_pct."""
        cfg = InvestmentMemoConfig(mgmt_fee_pct=2.0)
        self.assertAlmostEqual(cfg.mgmt_fee_pct, 2.0)


class TestInvestmentMemoGeneratorInit(unittest.TestCase):
    """Tests 6-8: Constructor / instantiation."""

    def test_06_instantiates_default(self):
        """InvestmentMemoGenerator can be created with no args."""
        gen = InvestmentMemoGenerator()
        self.assertIsInstance(gen, InvestmentMemoGenerator)

    def test_07_instantiates_with_config(self):
        """InvestmentMemoGenerator accepts InvestmentMemoConfig."""
        cfg = InvestmentMemoConfig(mgmt_fee_pct=2.0)
        gen = InvestmentMemoGenerator(config=cfg)
        self.assertIsInstance(gen, InvestmentMemoGenerator)

    def test_08_default_config_applied(self):
        """InvestmentMemoGenerator uses default config when none provided."""
        gen = InvestmentMemoGenerator()
        self.assertAlmostEqual(gen._config.mgmt_fee_pct, 1.5)


class TestExecutiveSummary(unittest.TestCase):
    """Tests 9-14: executive_summary()."""

    def setUp(self):
        self.gen = InvestmentMemoGenerator()
        self.summary = self.gen.executive_summary()

    def test_09_returns_string(self):
        """executive_summary() returns a string."""
        self.assertIsInstance(self.summary, str)

    def test_10_word_count_ok_default(self):
        """word_count_ok() returns True for default config."""
        self.assertTrue(self.gen.word_count_ok())

    def test_11_word_count_under_180(self):
        """executive_summary() is at most 180 words."""
        text = self.summary
        lines = text.splitlines()
        body = " ".join(ln for ln in lines if not ln.startswith("#"))
        words = body.split()
        self.assertLessEqual(len(words), 180, f"Word count {len(words)} exceeds 180")

    def test_12_contains_stablecoin(self):
        """executive_summary() contains 'stablecoin' (case-insensitive)."""
        self.assertIn("stablecoin", self.summary.lower())

    def test_13_contains_management_fee(self):
        """executive_summary() references the management fee value."""
        self.assertIn("1.5", self.summary)

    def test_14_contains_executive_summary_header(self):
        """executive_summary() contains '## 1. Executive Summary'."""
        self.assertIn("## 1. Executive Summary", self.summary)


class TestStrategyOverview(unittest.TestCase):
    """Tests 15-17: strategy_overview()."""

    def setUp(self):
        self.gen = InvestmentMemoGenerator()
        self.section = self.gen.strategy_overview()

    def test_15_returns_string(self):
        """strategy_overview() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_16_contains_stablecoin(self):
        """strategy_overview() contains 'stablecoin' (case-insensitive)."""
        self.assertIn("stablecoin", self.section.lower())

    def test_17_contains_strategy_overview_header(self):
        """strategy_overview() contains '## 2. Strategy Overview'."""
        self.assertIn("## 2. Strategy Overview", self.section)


class TestHistoricalPerformance(unittest.TestCase):
    """Tests 18-20: historical_performance()."""

    def setUp(self):
        self.gen = InvestmentMemoGenerator()
        self.section = self.gen.historical_performance()

    def test_18_returns_string(self):
        """historical_performance() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_19_contains_86_cash_drag(self):
        """historical_performance() references 86 (cash drag figure)."""
        self.assertIn("86", self.section)

    def test_20_contains_performance_header(self):
        """historical_performance() contains '## 3. Historical Performance'."""
        self.assertIn("## 3. Historical Performance", self.section)


class TestRiskFactors(unittest.TestCase):
    """Tests 21-23: risk_factors()."""

    def setUp(self):
        self.gen = InvestmentMemoGenerator()
        self.section = self.gen.risk_factors()

    def test_21_returns_string(self):
        """risk_factors() returns a string."""
        self.assertIsInstance(self.section, str)

    def test_22_contains_smart_contract_or_liquidity(self):
        """risk_factors() contains 'smart contract' or 'liquidit'."""
        lower = self.section.lower()
        self.assertTrue(
            "smart contract" in lower or "liquidit" in lower,
            "Neither 'smart contract' nor 'liquidit' found in risk_factors()"
        )

    def test_23_contains_risk_factors_header(self):
        """risk_factors() contains '## 4. Risk Factors'."""
        self.assertIn("## 4. Risk Factors", self.section)


class TestFeeStructure(unittest.TestCase):
    """Tests 24-26: fee_structure()."""

    def test_24_returns_string(self):
        """fee_structure() returns a string."""
        gen = InvestmentMemoGenerator()
        self.assertIsInstance(gen.fee_structure(), str)

    def test_25_contains_default_mgmt_fee(self):
        """fee_structure() contains '1.5' for default management fee."""
        gen = InvestmentMemoGenerator()
        self.assertIn("1.5", gen.fee_structure())

    def test_26_custom_fee_reflected(self):
        """fee_structure() shows custom mgmt_fee_pct when config overridden."""
        cfg = InvestmentMemoConfig(mgmt_fee_pct=2.0)
        gen = InvestmentMemoGenerator(config=cfg)
        section = gen.fee_structure()
        self.assertIn("2.0", section)


class TestGenerate(unittest.TestCase):
    """Tests 27-29: generate()."""

    def setUp(self):
        self.gen = InvestmentMemoGenerator()
        self.doc = self.gen.generate()

    def test_27_returns_string(self):
        """generate() returns a string."""
        self.assertIsInstance(self.doc, str)

    def test_28_longer_than_800_chars(self):
        """generate() produces a document longer than 800 characters."""
        self.assertGreater(len(self.doc), 800)

    def test_29_contains_all_section_headers(self):
        """generate() includes all 8 section headers."""
        for i in range(1, 9):
            self.assertIn(f"## {i}.", self.doc, f"Section ## {i}. not found in generate()")


class TestSave(unittest.TestCase):
    """Test 30: save()."""

    def test_30_save_creates_investment_memo(self):
        """save() creates docs/INVESTMENT_MEMO.md."""
        with tempfile.TemporaryDirectory() as td:
            gen = InvestmentMemoGenerator(base_dir=td)
            path = gen.save()
            self.assertTrue(Path(path).exists(), f"File not found: {path}")
            self.assertTrue(path.endswith("INVESTMENT_MEMO.md"))

    def test_save_custom_path(self):
        """save() respects a custom output_path argument."""
        with tempfile.TemporaryDirectory() as td:
            custom = os.path.join(td, "memo_custom.md")
            gen = InvestmentMemoGenerator(base_dir=td)
            path = gen.save(output_path=custom)
            self.assertTrue(Path(path).exists())

    def test_save_content_matches_generate(self):
        """save() writes exactly what generate() returns."""
        with tempfile.TemporaryDirectory() as td:
            gen = InvestmentMemoGenerator(base_dir=td)
            expected = gen.generate()
            path = gen.save()
            actual = Path(path).read_text(encoding="utf-8")
            self.assertEqual(actual, expected)

    def test_save_is_atomic(self):
        """save() leaves no leftover .tmp file after writing."""
        with tempfile.TemporaryDirectory() as td:
            gen = InvestmentMemoGenerator(base_dir=td)
            path = gen.save()
            md_tmp = path.replace(".md", ".md.tmp")
            self.assertFalse(Path(md_tmp).exists(), "Leftover .md.tmp file found")

    def test_word_count_ok_custom_config(self):
        """word_count_ok() returns True for custom config too."""
        cfg = InvestmentMemoConfig(mgmt_fee_pct=2.0, perf_fee_pct=25.0, min_investment_usd=20_000.0)
        gen = InvestmentMemoGenerator(config=cfg)
        self.assertTrue(gen.word_count_ok())

    def test_custom_config_fee_in_executive_summary(self):
        """executive_summary() shows custom mgmt_fee_pct."""
        cfg = InvestmentMemoConfig(mgmt_fee_pct=2.0)
        gen = InvestmentMemoGenerator(config=cfg)
        summary = gen.executive_summary()
        self.assertIn("2.0", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
