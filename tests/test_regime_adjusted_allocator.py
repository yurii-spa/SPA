"""
tests/test_regime_adjusted_allocator.py

40 unit tests for spa_core/analytics/regime_adjusted_allocator.py

Coverage:
  TestInstantiation           (3 tests)  — default + custom capital
  TestAllocateBull            (5 tests)  — rs001/rs002/cash pct, suspended, capital USD
  TestAllocateBear            (6 tests)  — rs001/rs002/cash pct, suspended, capital USD
  TestAllocateNeutral         (5 tests)  — rs001/rs002/cash pct, suspended, capital USD
  TestAllocationSumInvariant  (3 tests)  — rs001+rs002+cash == 1.0 in all regimes
  TestExpectedApy             (5 tests)  — bear < neutral < bull; values; returns float
  TestAllocateNoneUsesCurrentRegime (2 tests) — no regime arg → current_regime()
  TestCurrentRegime           (2 tests)  — returns str in valid set
  TestAllocateAllRegimes      (4 tests)  — dict, all keys, all AllocationResult
  TestSave                    (3 tests)  — file created, valid JSON, returns path str
  TestToMarkdown              (5 tests)  — str; contains bull / neutral / bear; header
  TestCustomCapital           (2 tests)  — capital propagates to USD fields

Sprint v9.78 — MP-1362
Date: 2026-06-19
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.analytics.regime_adjusted_allocator import (
    AllocationResult,
    RegimeAdjustedAllocator,
    RS001_APY,
    RS002_APY,
    VALID_REGIMES,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _alloc(capital: float = 100_000.0, base_dir: str = ".") -> RegimeAdjustedAllocator:
    return RegimeAdjustedAllocator(total_capital=capital, base_dir=base_dir)


# ── Tests ────────────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):

    def test_instantiates_with_defaults(self):
        alloc = RegimeAdjustedAllocator()
        self.assertIsInstance(alloc, RegimeAdjustedAllocator)

    def test_default_capital(self):
        alloc = RegimeAdjustedAllocator()
        self.assertEqual(alloc.total_capital, 100_000.0)

    def test_custom_capital(self):
        alloc = RegimeAdjustedAllocator(total_capital=250_000.0)
        self.assertEqual(alloc.total_capital, 250_000.0)


class TestAllocateBull(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()
        self.result = self.alloc.allocate("bull")

    def test_bull_rs001_pct(self):
        self.assertAlmostEqual(self.result.rs001_pct, 0.40, places=9)

    def test_bull_rs002_pct(self):
        self.assertAlmostEqual(self.result.rs002_pct, 0.30, places=9)

    def test_bull_cash_pct(self):
        self.assertAlmostEqual(self.result.cash_pct, 0.30, places=9)

    def test_bull_rs002_not_suspended(self):
        self.assertFalse(self.result.rs002_suspended)

    def test_bull_rs001_capital_usd(self):
        self.assertAlmostEqual(self.result.rs001_capital_usd, 40_000.0, places=1)


class TestAllocateBear(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()
        self.result = self.alloc.allocate("bear")

    def test_bear_rs001_pct(self):
        self.assertAlmostEqual(self.result.rs001_pct, 0.30, places=9)

    def test_bear_rs002_pct_zero(self):
        self.assertAlmostEqual(self.result.rs002_pct, 0.00, places=9)

    def test_bear_cash_pct(self):
        self.assertAlmostEqual(self.result.cash_pct, 0.70, places=9)

    def test_bear_rs002_suspended_true(self):
        self.assertTrue(self.result.rs002_suspended)

    def test_bear_rs002_capital_usd_zero(self):
        self.assertAlmostEqual(self.result.rs002_capital_usd, 0.0, places=1)

    def test_bear_cash_capital_usd(self):
        self.assertAlmostEqual(self.result.cash_capital_usd, 70_000.0, places=1)


class TestAllocateNeutral(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()
        self.result = self.alloc.allocate("neutral")

    def test_neutral_rs001_pct(self):
        self.assertAlmostEqual(self.result.rs001_pct, 0.50, places=9)

    def test_neutral_rs002_pct(self):
        self.assertAlmostEqual(self.result.rs002_pct, 0.20, places=9)

    def test_neutral_cash_pct(self):
        self.assertAlmostEqual(self.result.cash_pct, 0.30, places=9)

    def test_neutral_rs002_not_suspended(self):
        self.assertFalse(self.result.rs002_suspended)

    def test_neutral_rs001_capital_usd(self):
        self.assertAlmostEqual(self.result.rs001_capital_usd, 50_000.0, places=1)


class TestAllocationSumInvariant(unittest.TestCase):
    """rs001_pct + rs002_pct + cash_pct == 1.0 in all regimes."""

    def setUp(self):
        self.alloc = _alloc()

    def test_sum_bull(self):
        r = self.alloc.allocate("bull")
        self.assertAlmostEqual(r.rs001_pct + r.rs002_pct + r.cash_pct, 1.0, places=9)

    def test_sum_neutral(self):
        r = self.alloc.allocate("neutral")
        self.assertAlmostEqual(r.rs001_pct + r.rs002_pct + r.cash_pct, 1.0, places=9)

    def test_sum_bear(self):
        r = self.alloc.allocate("bear")
        self.assertAlmostEqual(r.rs001_pct + r.rs002_pct + r.cash_pct, 1.0, places=9)


class TestExpectedApy(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()

    def test_expected_apy_returns_float(self):
        val = self.alloc.expected_apy("bull")
        self.assertIsInstance(val, float)

    def test_expected_apy_bear_lt_bull(self):
        bear_apy = self.alloc.expected_apy("bear")
        bull_apy = self.alloc.expected_apy("bull")
        self.assertLess(bear_apy, bull_apy)

    def test_expected_apy_bear_lt_neutral(self):
        bear_apy = self.alloc.expected_apy("bear")
        neutral_apy = self.alloc.expected_apy("neutral")
        self.assertLess(bear_apy, neutral_apy)

    def test_expected_apy_bull_value(self):
        # bull: 0.40*22.0 + 0.30*20.0 = 8.8 + 6.0 = 14.8
        expected = 0.40 * RS001_APY["bull"] + 0.30 * RS002_APY["bull"]
        self.assertAlmostEqual(self.alloc.expected_apy("bull"), expected, places=4)

    def test_expected_apy_bear_value(self):
        # bear: 0.30*8.0 + 0.00*0.0 = 2.4
        expected = 0.30 * RS001_APY["bear"] + 0.00 * RS002_APY["bear"]
        self.assertAlmostEqual(self.alloc.expected_apy("bear"), expected, places=4)


class TestAllocateNoneUsesCurrentRegime(unittest.TestCase):

    def test_allocate_no_regime_returns_allocation_result(self):
        alloc = _alloc(base_dir=str(_PROJECT_ROOT))
        result = alloc.allocate()
        self.assertIsInstance(result, AllocationResult)

    def test_allocate_none_regime_is_valid(self):
        alloc = _alloc(base_dir=str(_PROJECT_ROOT))
        result = alloc.allocate()
        self.assertIn(result.regime, VALID_REGIMES)


class TestCurrentRegime(unittest.TestCase):

    def test_current_regime_returns_string(self):
        alloc = _alloc(base_dir=str(_PROJECT_ROOT))
        regime = alloc.current_regime()
        self.assertIsInstance(regime, str)

    def test_current_regime_valid_value(self):
        alloc = _alloc(base_dir=str(_PROJECT_ROOT))
        regime = alloc.current_regime()
        self.assertIn(regime, VALID_REGIMES)


class TestAllocateAllRegimes(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()
        self.results = self.alloc.allocate_all_regimes()

    def test_allocate_all_returns_dict(self):
        self.assertIsInstance(self.results, dict)

    def test_allocate_all_has_all_regime_keys(self):
        for regime in VALID_REGIMES:
            with self.subTest(regime=regime):
                self.assertIn(regime, self.results)

    def test_allocate_all_values_are_allocation_results(self):
        for regime, result in self.results.items():
            with self.subTest(regime=regime):
                self.assertIsInstance(result, AllocationResult)

    def test_allocate_all_regimes_count(self):
        self.assertEqual(len(self.results), 3)


class TestSave(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Create a data/market_regime.json so current_regime() works
        data_dir = Path(self._tmpdir) / "data"
        data_dir.mkdir()
        regime_file = data_dir / "market_regime.json"
        regime_file.write_text(json.dumps({"regime": "neutral"}))
        self.alloc = RegimeAdjustedAllocator(
            total_capital=100_000.0,
            base_dir=self._tmpdir,
        )

    def test_save_returns_string_path(self):
        path = self.alloc.save("neutral")
        self.assertIsInstance(path, str)

    def test_save_creates_file(self):
        path = self.alloc.save("neutral")
        self.assertTrue(os.path.exists(path))

    def test_save_content_is_valid_json(self):
        path = self.alloc.save("bull")
        with open(path, "r") as fh:
            data = json.load(fh)
        self.assertIn("current_regime", data)
        self.assertIn("current", data)
        self.assertIn("all_regimes", data)


class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.alloc = _alloc()
        self.md = self.alloc.to_markdown()

    def test_to_markdown_is_string(self):
        self.assertIsInstance(self.md, str)

    def test_to_markdown_contains_bull(self):
        self.assertIn("bull", self.md)

    def test_to_markdown_contains_bear(self):
        self.assertIn("bear", self.md)

    def test_to_markdown_contains_neutral(self):
        self.assertIn("neutral", self.md)

    def test_to_markdown_contains_suspended(self):
        self.assertIn("SUSPENDED", self.md)


class TestCustomCapital(unittest.TestCase):

    def test_custom_capital_rs001_usd_bull(self):
        alloc = RegimeAdjustedAllocator(total_capital=200_000.0)
        result = alloc.allocate("bull")
        self.assertAlmostEqual(result.rs001_capital_usd, 80_000.0, places=1)  # 40% of 200k

    def test_custom_capital_cash_usd_bear(self):
        alloc = RegimeAdjustedAllocator(total_capital=50_000.0)
        result = alloc.allocate("bear")
        self.assertAlmostEqual(result.cash_capital_usd, 35_000.0, places=1)  # 70% of 50k


if __name__ == "__main__":
    unittest.main(verbosity=2)
