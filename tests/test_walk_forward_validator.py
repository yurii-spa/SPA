"""
tests/test_walk_forward_validator.py

MP-1495 (v11.11) — 30 unit tests for WalkForwardValidator.

Covers:
  1. Instantiation & defaults                         (3 tests)
  2. _create_windows: edge cases & correctness        (6 tests)
  3. _sharpe: edge cases & correctness                (5 tests)
  4. run(): window counting & structure               (6 tests)
  5. run(): aggregate metrics & verdict               (6 tests)
  6. Output path & to_dict                            (4 tests)

Compatible with stdlib unittest and pytest.
"""

import os
import sys
import tempfile
import json
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.walk_forward_validator import WalkForwardValidator


# ── helpers ───────────────────────────────────────────────────────────────────

def _flat_series(n: int, daily_return: float = 0.0005) -> list:
    """Constant-return series of length n."""
    return [daily_return] * n


def _volatile_series(n: int, up: float = 0.01, down: float = -0.005) -> list:
    """Alternating up/down series of length n."""
    return [up if i % 2 == 0 else down for i in range(n)]


class TestInstantiation(unittest.TestCase):
    """TC-WFV-01..03: __init__ sets correct defaults."""

    def setUp(self):
        self.wfv = WalkForwardValidator("S0")

    def test_01_strategy_id_stored(self):
        self.assertEqual(self.wfv.strategy_id, "S0")

    def test_02_train_days_default(self):
        self.assertEqual(self.wfv.TRAIN_DAYS, 180)

    def test_03_test_days_default(self):
        self.assertEqual(self.wfv.TEST_DAYS, 30)


class TestCreateWindows(unittest.TestCase):
    """TC-WFV-04..09: _create_windows edge cases."""

    def setUp(self):
        self.wfv = WalkForwardValidator("S0")

    def test_04_no_windows_when_series_too_short(self):
        short = _flat_series(180 + 29)  # 1 day short
        windows = self.wfv._create_windows(short)
        self.assertEqual(len(windows), 0)

    def test_05_exactly_one_window(self):
        exact = _flat_series(180 + 30)
        windows = self.wfv._create_windows(exact)
        self.assertEqual(len(windows), 1)

    def test_06_two_windows(self):
        series = _flat_series(180 + 30 + 30)
        windows = self.wfv._create_windows(series)
        self.assertEqual(len(windows), 2)

    def test_07_train_slice_length(self):
        series = _flat_series(210)
        (train, test) = self.wfv._create_windows(series)[0]
        self.assertEqual(len(train), 180)

    def test_08_test_slice_length(self):
        series = _flat_series(210)
        (train, test) = self.wfv._create_windows(series)[0]
        self.assertEqual(len(test), 30)

    def test_09_windows_are_non_overlapping_in_test(self):
        """Second window's test slice must follow first window's test slice."""
        series = list(range(300))  # use indices as values
        windows = self.wfv._create_windows(series)
        self.assertGreaterEqual(len(windows), 2)
        # First test slice ends at index 180+30=210; second test starts at 210
        _, first_test = windows[0]
        _, second_test = windows[1]
        self.assertEqual(first_test[-1] + 1, second_test[0])


class TestSharpe(unittest.TestCase):
    """TC-WFV-10..14: _sharpe correctness."""

    def setUp(self):
        self.wfv = WalkForwardValidator("S0")

    def test_10_empty_series_returns_zero(self):
        self.assertEqual(self.wfv._sharpe([]), 0.0)

    def test_11_single_element_returns_zero(self):
        self.assertEqual(self.wfv._sharpe([0.001]), 0.0)

    def test_12_constant_series_returns_zero(self):
        # std dev == 0 → Sharpe = 0
        self.assertEqual(self.wfv._sharpe([0.001, 0.001, 0.001]), 0.0)

    def test_13_positive_mean_volatile_series(self):
        # mean > risk_free daily → positive Sharpe
        returns = [0.01] * 100 + [-0.001] * 100
        sharpe = self.wfv._sharpe(returns)
        self.assertGreater(sharpe, 0)

    def test_14_negative_mean_yields_negative_sharpe(self):
        returns = [-0.005] * 200
        # constant → std=0 → 0.0; make it volatile
        import random
        random.seed(42)
        neg_returns = [-0.005 + random.gauss(0, 0.001) for _ in range(200)]
        # override to force mean to be negative enough
        neg_returns = [-0.01 + (i % 2) * 0.005 for i in range(200)]
        sharpe = self.wfv._sharpe(neg_returns)
        self.assertLess(sharpe, 0)


class TestRunStructure(unittest.TestCase):
    """TC-WFV-15..20: run() returns correct structure."""

    def setUp(self):
        self.wfv = WalkForwardValidator("S0", base_dir=tempfile.mkdtemp())

    def test_15_run_returns_dict(self):
        result = self.wfv.run(_flat_series(50))
        self.assertIsInstance(result, dict)

    def test_16_run_insufficient_data_verdict(self):
        result = self.wfv.run(_flat_series(50))
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_17_run_n_windows_zero_for_short_series(self):
        result = self.wfv.run(_flat_series(100))
        self.assertEqual(result["n_windows"], 0)

    def test_18_run_one_window_on_exact_data(self):
        result = self.wfv.run(_flat_series(210))
        self.assertEqual(result["n_windows"], 1)

    def test_19_run_window_entry_has_required_keys(self):
        result = self.wfv.run(_flat_series(210))
        w = result["windows"][0]
        for key in ("window", "train_days", "test_days", "is_sharpe", "oos_sharpe", "degradation"):
            self.assertIn(key, w)

    def test_20_run_train_days_matches_constant(self):
        result = self.wfv.run(_flat_series(210))
        self.assertEqual(result["windows"][0]["train_days"], 180)


class TestRunMetrics(unittest.TestCase):
    """TC-WFV-21..26: aggregate metrics & verdict."""

    def setUp(self):
        self.wfv = WalkForwardValidator("S2", base_dir=tempfile.mkdtemp())
        # Enough data for 4 windows: 180 + 4*30 = 300
        self.series = _volatile_series(300, up=0.008, down=-0.001)

    def test_21_is_sharpe_avg_is_float(self):
        result = self.wfv.run(self.series)
        self.assertIsInstance(result["is_sharpe_avg"], float)

    def test_22_oos_sharpe_avg_is_float(self):
        result = self.wfv.run(self.series)
        self.assertIsInstance(result["oos_sharpe_avg"], float)

    def test_23_degradation_ratio_is_float(self):
        result = self.wfv.run(self.series)
        self.assertIsInstance(result["degradation_ratio"], float)

    def test_24_verdict_is_string(self):
        result = self.wfv.run(self.series)
        self.assertIsInstance(result["verdict"], str)

    def test_25_verdict_one_of_valid_values(self):
        result = self.wfv.run(self.series)
        valid = {"STRONG", "MODERATE", "WEAK", "NEGATIVE_OOS", "INSUFFICIENT_DATA"}
        self.assertIn(result["verdict"], valid)

    def test_26_degradation_zero_when_is_sharpe_zero(self):
        """When IS Sharpe = 0, degradation = 0.0 (not div-by-zero)."""
        # constant series → IS Sharpe = 0 (std=0), OOS Sharpe = 0
        const = _flat_series(210, daily_return=0.05 / 252)  # exactly at risk_free
        wfv2 = WalkForwardValidator("S99", base_dir=tempfile.mkdtemp())
        result = wfv2.run(const)
        # degradation should be 0.0, not an error
        self.assertEqual(result["degradation_ratio"], 0.0)


class TestOutputAndToDict(unittest.TestCase):
    """TC-WFV-27..30: output path, to_dict, save."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.wfv = WalkForwardValidator("S5", base_dir=self.tmpdir)

    def test_27_output_path_contains_strategy_id(self):
        self.assertIn("S5", self.wfv.OUTPUT_PATH)

    def test_28_to_dict_returns_dict(self):
        self.assertIsInstance(self.wfv.to_dict(), dict)

    def test_29_to_dict_has_strategy_key(self):
        d = self.wfv.to_dict()
        self.assertEqual(d["strategy"], "S5")

    def test_30_run_writes_json_file(self):
        series = _volatile_series(210)
        self.wfv.run(series)
        out_path = os.path.join(self.tmpdir, self.wfv.OUTPUT_PATH)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path) as f:
            data = json.load(f)
        self.assertIn("n_windows", data)


if __name__ == "__main__":
    unittest.main()
