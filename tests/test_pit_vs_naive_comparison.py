"""
MP-1317 (v9.33) — Tests for PITvsNaiveComparison.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_pit_vs_naive_comparison -v
Also compatible with pytest.

35 tests across 7 groups:
  1. Instantiation                       (3 tests)
  2. run_naive() return structure        (8 tests)
  3. run_pit() return structure          (8 tests)
  4. PIT vs Naive ordering invariants    (4 tests)
  5. compare() structure and delta       (7 tests)
  6. to_markdown()                       (3 tests)
  7. save() atomic write                 (2 tests)
"""

import json
import os
import sys
import tempfile
import unittest

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.pit_vs_naive_comparison import PITvsNaiveComparison


# ── helpers ───────────────────────────────────────────────────────────────────

def _quick_cmp(days: int = 400) -> PITvsNaiveComparison:
    """Returns a short-period comparison for fast tests."""
    from datetime import date, timedelta
    start_d = date(2022, 5, 1)
    end_d = start_d + timedelta(days=days - 1)
    return PITvsNaiveComparison(
        start=start_d.isoformat(),
        end=end_d.isoformat(),
        initial_capital=100_000.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — Instantiation (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):

    def test_default_instantiation(self):
        """PITvsNaiveComparison instantiates with default parameters."""
        cmp = PITvsNaiveComparison()
        self.assertIsInstance(cmp, PITvsNaiveComparison)

    def test_custom_dates(self):
        """PITvsNaiveComparison accepts custom start/end dates."""
        cmp = PITvsNaiveComparison(start="2023-01-01", end="2024-01-01")
        self.assertIsInstance(cmp, PITvsNaiveComparison)

    def test_custom_capital(self):
        """PITvsNaiveComparison accepts custom initial_capital."""
        cmp = PITvsNaiveComparison(initial_capital=500_000.0)
        self.assertIsInstance(cmp, PITvsNaiveComparison)


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — run_naive() return structure (8 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunNaive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cmp = _quick_cmp(400)
        cls.result = cls.cmp.run_naive()

    def test_naive_returns_dict(self):
        """run_naive() returns a dict."""
        self.assertIsInstance(self.result, dict)

    def test_naive_has_apy(self):
        """run_naive() result has 'apy' key."""
        self.assertIn("apy", self.result)

    def test_naive_apy_is_numeric(self):
        """run_naive() 'apy' is a float or int."""
        self.assertIsInstance(self.result["apy"], (float, int))

    def test_naive_has_sharpe(self):
        """run_naive() result has 'sharpe' key."""
        self.assertIn("sharpe", self.result)

    def test_naive_has_max_dd(self):
        """run_naive() result has 'max_dd' key."""
        self.assertIn("max_dd", self.result)

    def test_naive_has_cash_days_pct(self):
        """run_naive() result has 'cash_days_pct' key."""
        self.assertIn("cash_days_pct", self.result)

    def test_naive_cash_days_pct_in_range(self):
        """run_naive() cash_days_pct is in [0, 100]."""
        val = self.result["cash_days_pct"]
        self.assertGreaterEqual(val, 0)
        self.assertLessEqual(val, 100)

    def test_naive_has_final_capital(self):
        """run_naive() result has 'final_capital' key."""
        self.assertIn("final_capital", self.result)


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — run_pit() return structure (8 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunPit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cmp = _quick_cmp(400)
        cls.result = cls.cmp.run_pit()

    def test_pit_returns_dict(self):
        """run_pit() returns a dict."""
        self.assertIsInstance(self.result, dict)

    def test_pit_has_apy(self):
        """run_pit() result has 'apy' key."""
        self.assertIn("apy", self.result)

    def test_pit_apy_is_numeric(self):
        """run_pit() 'apy' is a float or int."""
        self.assertIsInstance(self.result["apy"], (float, int))

    def test_pit_has_sharpe(self):
        """run_pit() result has 'sharpe' key."""
        self.assertIn("sharpe", self.result)

    def test_pit_has_max_dd(self):
        """run_pit() result has 'max_dd' key."""
        self.assertIn("max_dd", self.result)

    def test_pit_has_cash_days_pct(self):
        """run_pit() result has 'cash_days_pct' key."""
        self.assertIn("cash_days_pct", self.result)

    def test_pit_cash_days_pct_in_range(self):
        """run_pit() cash_days_pct is in [0, 100]."""
        val = self.result["cash_days_pct"]
        self.assertGreaterEqual(val, 0)
        self.assertLessEqual(val, 100)

    def test_pit_has_days(self):
        """run_pit() result has 'days' key."""
        self.assertIn("days", self.result)


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — PIT vs Naive ordering invariants (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestOrderingInvariants(unittest.TestCase):
    """
    Core invariants the comparison must satisfy:
    1. PIT cash_days_pct > naive cash_days_pct (PIT is more conservative)
    2. naive APY >= pit APY (naive overstates returns)

    Period 2022-05-01 to 2023-12-31 (pure bear market, 609 days):
    - PIT: all protocols fail APY/TVL filter or have not launched → 100% cash
    - Naive: morpho_steakhouse (base_tvl 20M × 0.30 = 6M > 5M, APY 1.95%)
             and sky (20M × 0.30 = 6M, APY 2.1%) are retroactively available
             → 80% deployed, 0% cash days
    """

    @classmethod
    def setUpClass(cls):
        # Use full period that spans bear market for clear separation
        cls.cmp = PITvsNaiveComparison(
            start="2022-05-01",
            end="2024-06-30",
            initial_capital=100_000.0,
        )
        cls.naive = cls.cmp.run_naive()
        cls.pit = cls.cmp.run_pit()

    def test_pit_cash_days_pct_greater_than_naive(self):
        """PIT strict cash_days_pct must be greater than naive cash_days_pct."""
        self.assertGreater(
            self.pit["cash_days_pct"],
            self.naive["cash_days_pct"],
            msg=(
                f"Expected PIT ({self.pit['cash_days_pct']:.2f}%) > "
                f"Naive ({self.naive['cash_days_pct']:.2f}%)"
            ),
        )

    def test_naive_apy_gte_pit_apy(self):
        """Naive APY must be >= PIT APY (naive overstates returns)."""
        self.assertGreaterEqual(
            self.naive["apy"],
            self.pit["apy"],
            msg=(
                f"Expected Naive APY ({self.naive['apy']:.4f}%) >= "
                f"PIT APY ({self.pit['apy']:.4f}%)"
            ),
        )

    def test_pit_cash_days_pct_nonzero_during_bear_market(self):
        """PIT cash_days_pct is > 0 for a period spanning 2022–2023 bear market."""
        self.assertGreater(
            self.pit["cash_days_pct"],
            0.0,
            msg="Expected PIT to have at least some cash days in bear market 2022-2023",
        )

    def test_naive_final_capital_gte_pit(self):
        """Naive final capital should be >= PIT final capital."""
        self.assertGreaterEqual(
            self.naive["final_capital"],
            self.pit["final_capital"],
            msg="Expected Naive final capital >= PIT (naive deploys more capital)",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Group 5 — compare() structure and delta (7 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCompare(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cmp = _quick_cmp(500)
        cls.result = cls.cmp.compare()

    def test_compare_returns_dict(self):
        """compare() returns a dict."""
        self.assertIsInstance(self.result, dict)

    def test_compare_has_naive(self):
        """compare() result has 'naive' key."""
        self.assertIn("naive", self.result)

    def test_compare_has_pit_strict(self):
        """compare() result has 'pit_strict' key."""
        self.assertIn("pit_strict", self.result)

    def test_compare_has_delta(self):
        """compare() result has 'delta' key."""
        self.assertIn("delta", self.result)

    def test_delta_has_apy_delta(self):
        """compare() delta has 'apy_delta' key."""
        self.assertIn("apy_delta", self.result["delta"])

    def test_delta_has_look_ahead_bias_magnitude(self):
        """compare() delta has 'look_ahead_bias_magnitude' key."""
        self.assertIn("look_ahead_bias_magnitude", self.result["delta"])

    def test_look_ahead_bias_magnitude_nonnegative(self):
        """delta['look_ahead_bias_magnitude'] is >= 0."""
        val = self.result["delta"]["look_ahead_bias_magnitude"]
        self.assertGreaterEqual(val, 0.0)

    def test_compare_has_interpretation(self):
        """compare() result has 'interpretation' key."""
        self.assertIn("interpretation", self.result)

    def test_interpretation_contains_look_ahead_bias(self):
        """interpretation text contains 'look-ahead bias'."""
        self.assertIn("look-ahead bias", self.result["interpretation"])

    def test_compare_has_methodology_note(self):
        """compare() result has 'methodology_note' key."""
        self.assertIn("methodology_note", self.result)

    def test_methodology_note_contains_cpa(self):
        """methodology_note mentions 'CPA' standard."""
        self.assertIn("CPA", self.result["methodology_note"])

    def test_apy_delta_equals_naive_minus_pit(self):
        """delta['apy_delta'] == naive_apy - pit_apy (within float tolerance)."""
        naive_apy = self.result["naive"]["apy"]
        pit_apy = self.result["pit_strict"]["apy"]
        expected_delta = round(naive_apy - pit_apy, 4)
        self.assertAlmostEqual(
            self.result["delta"]["apy_delta"],
            expected_delta,
            places=3,
        )

    def test_delta_has_cash_drag_delta(self):
        """compare() delta has 'cash_drag_delta' key."""
        self.assertIn("cash_drag_delta", self.result["delta"])


# ─────────────────────────────────────────────────────────────────────────────
# Group 6 — to_markdown() (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cmp = _quick_cmp(300)
        cls.md = cls.cmp.to_markdown()

    def test_to_markdown_returns_string(self):
        """to_markdown() returns a str."""
        self.assertIsInstance(self.md, str)

    def test_to_markdown_contains_table_separator(self):
        """to_markdown() output contains '|' (markdown table)."""
        self.assertIn("|", self.md)

    def test_to_markdown_contains_pit_and_naive(self):
        """to_markdown() output contains both 'Naive' and 'PIT'."""
        self.assertIn("Naive", self.md)
        self.assertIn("PIT", self.md)

    def test_to_markdown_contains_apy(self):
        """to_markdown() output contains 'APY'."""
        self.assertIn("APY", self.md)


# ─────────────────────────────────────────────────────────────────────────────
# Group 7 — save() atomic write (2 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cmp = _quick_cmp(200)

    def test_save_creates_file(self):
        """save() creates the output JSON file."""
        path = os.path.join(self.tmpdir, "backtest", "pit_vs_naive.json")
        self.cmp.save(path)
        self.assertTrue(os.path.exists(path))

    def test_save_creates_valid_json(self):
        """save() writes a valid JSON file with 'naive' and 'pit_strict' keys."""
        path = os.path.join(self.tmpdir, "backtest", "result.json")
        self.cmp.save(path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("naive", data)
        self.assertIn("pit_strict", data)
        self.assertIn("delta", data)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
