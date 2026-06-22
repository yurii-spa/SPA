"""10 unit / integration tests for scripts/s11_backtest_90d.py

Compatible with both pytest and stdlib unittest:
    python3 -m unittest tests.test_s11_backtest -v
    pytest tests/test_s11_backtest.py -v
"""
import json
import os
import sys
import unittest
import tempfile

# Make the scripts package importable without an __init__.py
REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from s11_backtest_90d import (
    CAPITAL,
    DAYS,
    N_SIMULATIONS,
    RANDOM_SEED,
    run_backtest,
    save_result_atomic,
)


# Run backtest once for the whole module (expensive: 1000 sims × 90 days)
_RESULT = None


def _get_result():
    global _RESULT
    if _RESULT is None:
        _RESULT = run_backtest(n_simulations=N_SIMULATIONS, seed=RANDOM_SEED)
    return _RESULT


# ─────────────────────────────────────────────────────────────────────────────

class TestS11Backtest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = _get_result()

    # ── Test 1 ────────────────────────────────────────────────────────────────
    def test_01_result_is_non_empty_dict(self):
        """run_backtest() returns a non-empty dict."""
        self.assertIsInstance(self.result, dict)
        self.assertTrue(self.result, "result must not be empty")

    # ── Test 2 ────────────────────────────────────────────────────────────────
    def test_02_valid_json_round_trip(self):
        """Result serialises to valid JSON and round-trips cleanly."""
        serialised   = json.dumps(self.result)
        deserialised = json.loads(serialised)
        self.assertEqual(deserialised, self.result,
                         "JSON round-trip must be lossless")

    # ── Test 3 ────────────────────────────────────────────────────────────────
    def test_03_required_top_level_keys(self):
        """All required top-level keys are present."""
        required = {"meta", "apy_pct", "sharpe", "max_drawdown_pct",
                    "probabilities", "adr023_assessment"}
        missing  = required - set(self.result.keys())
        self.assertFalse(missing, f"Missing top-level keys: {missing}")

    # ── Test 4 ────────────────────────────────────────────────────────────────
    def test_04_meta_fields_correct(self):
        """Meta block has correct n_simulations, days, capital, seed, strategy."""
        meta = self.result["meta"]
        self.assertEqual(meta["n_simulations"], N_SIMULATIONS)
        self.assertEqual(meta["days"],          DAYS)
        self.assertEqual(meta["capital"],       CAPITAL)
        self.assertEqual(meta["seed"],          RANDOM_SEED)
        self.assertEqual(meta["strategy"],      "S11 Hybrid Yield Maximizer")
        # Allocation weights must sum to 1.0
        weights_sum = sum(meta["allocation"].values())
        self.assertAlmostEqual(weights_sum, 1.0, places=9,
                               msg=f"Allocation weights sum to {weights_sum}, not 1.0")

    # ── Test 5 ────────────────────────────────────────────────────────────────
    def test_05_median_apy_in_realistic_range(self):
        """Median APY is between 8% and 25%."""
        p50 = self.result["apy_pct"]["p50"]
        self.assertGreaterEqual(p50, 8.0,
            f"Median APY {p50:.2f}% is below 8%")
        self.assertLessEqual(p50, 25.0,
            f"Median APY {p50:.2f}% is above 25%")

    # ── Test 6 ────────────────────────────────────────────────────────────────
    def test_06_median_sharpe_strictly_positive(self):
        """Median Sharpe ratio > 0."""
        p50_sharpe = self.result["sharpe"]["p50"]
        self.assertGreater(p50_sharpe, 0,
            f"Median Sharpe {p50_sharpe:.3f} must be > 0")

    # ── Test 7 ────────────────────────────────────────────────────────────────
    def test_07_probabilities_in_valid_range(self):
        """All probability values are between 0 and 100."""
        for key, val in self.result["probabilities"].items():
            self.assertGreaterEqual(val, 0.0,
                f"Probability {key}={val} is below 0")
            self.assertLessEqual(val, 100.0,
                f"Probability {key}={val} is above 100")

    # ── Test 8 ────────────────────────────────────────────────────────────────
    def test_08_drawdown_sign_and_ordering(self):
        """Drawdown percentiles are ≤ 0 and correctly ordered (p5 ≥ p50 ≥ p95)."""
        dd = self.result["max_drawdown_pct"]
        p5, p50, p95 = dd["p5"], dd["p50"], dd["p95"]
        # Signs
        self.assertLessEqual(p5,  0, f"Drawdown p5={p5} must be <= 0")
        self.assertLessEqual(p50, 0, f"Drawdown p50={p50} must be <= 0")
        self.assertLessEqual(p95, 0, f"Drawdown p95={p95} must be <= 0")
        # Ordering: p5 least severe (closest to 0), p95 most severe
        self.assertGreaterEqual(p5,  p50,
            f"Expected p5 ({p5}) >= p50 ({p50})")
        self.assertGreaterEqual(p50, p95,
            f"Expected p50 ({p50}) >= p95 ({p95})")

    # ── Test 9 ────────────────────────────────────────────────────────────────
    def test_09_atomic_write_no_tmp_leftovers(self):
        """Atomic write creates target file with valid JSON and no leftover tmp files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = save_result_atomic(self.result, tmpdir)

            # Target file must exist
            self.assertTrue(os.path.isfile(saved_path),
                            "Target file was not created")

            # Target must contain valid JSON matching original
            with open(saved_path) as f:
                loaded = json.load(f)
            self.assertEqual(
                loaded["meta"]["strategy"], "S11 Hybrid Yield Maximizer"
            )
            self.assertEqual(loaded["apy_pct"], self.result["apy_pct"])

            # No leftover .s11_backtest_tmp_* files
            leftovers = [
                fn for fn in os.listdir(tmpdir)
                if fn.startswith(".s11_backtest_tmp_")
            ]
            self.assertFalse(leftovers,
                             f"Tmp files not cleaned up: {leftovers}")

    # ── Test 10 ───────────────────────────────────────────────────────────────
    def test_10_deterministic_same_seed(self):
        """Same seed produces byte-identical results on a second run."""
        second = run_backtest(n_simulations=N_SIMULATIONS, seed=RANDOM_SEED)
        self.assertEqual(second["apy_pct"],    self.result["apy_pct"],
                         "APY percentiles differ across runs with same seed")
        self.assertEqual(second["sharpe"],     self.result["sharpe"],
                         "Sharpe percentiles differ across runs with same seed")
        self.assertEqual(second["probabilities"], self.result["probabilities"],
                         "Probabilities differ across runs with same seed")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
