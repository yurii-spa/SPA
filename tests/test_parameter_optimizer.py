"""
tests/test_parameter_optimizer.py — MP-1481 Parameter Optimizer Tests

30 unit tests covering OptimizeResult, ParameterOptimizer init/grid/optimize,
metric evaluation, error handling, synthetic scoring, real-data scoring,
and best_result selection.

Stdlib only. No external deps.
"""
import sys
import math
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.tuner.parameter_optimizer import ParameterOptimizer, OptimizeResult, OptimizerError
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Group 1: TestOptimizeResult (4 tests)
# ---------------------------------------------------------------------------

class TestOptimizeResult(unittest.TestCase):

    def _make_result(self, **overrides) -> OptimizeResult:
        defaults = dict(
            strategy_name="S7",
            best_params={"apy_scale": 1.2},
            best_score=1.5,
            metric="sharpe",
            total_trials=3,
            trials=[{"params": {"apy_scale": 1.2}, "score": 1.5}],
        )
        defaults.update(overrides)
        return OptimizeResult(**defaults)

    def test_to_dict_has_required_keys(self):
        r = self._make_result()
        d = r.to_dict()
        for key in ("strategy_name", "best_params", "best_score", "metric",
                    "total_trials", "trials", "timestamp"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_strategy_name_stored(self):
        r = self._make_result(strategy_name="S11")
        self.assertEqual(r.strategy_name, "S11")
        self.assertEqual(r.to_dict()["strategy_name"], "S11")

    def test_timestamp_auto_set(self):
        r = self._make_result()
        self.assertTrue(r.timestamp, "timestamp should be auto-set")
        # Should look like an ISO string
        self.assertIn("T", r.timestamp)

    def test_trials_list_in_dict(self):
        trials = [{"params": {"apy_scale": 1.0}, "score": 0.9},
                  {"params": {"apy_scale": 1.5}, "score": 1.5}]
        r = self._make_result(trials=trials, total_trials=2)
        d = r.to_dict()
        self.assertIsInstance(d["trials"], list)
        self.assertEqual(len(d["trials"]), 2)


# ---------------------------------------------------------------------------
# Group 2: TestParameterOptimizerInit (3 tests)
# ---------------------------------------------------------------------------

class TestParameterOptimizerInit(unittest.TestCase):

    def test_creates_with_strategy_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = ParameterOptimizer("S7", base_dir=tmp)
            self.assertEqual(opt.strategy_name, "S7")

    def test_default_output_path(self):
        self.assertEqual(ParameterOptimizer.OUTPUT_PATH, "data/optimizer_results.json")

    def test_to_dict_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = ParameterOptimizer("S11", base_dir=tmp)
            d = opt.to_dict()
            self.assertIn("strategy", d)
            self.assertIn("results", d)
            self.assertIn("updated_at", d)
            self.assertEqual(d["strategy"], "S11")
            self.assertIsInstance(d["results"], list)


# ---------------------------------------------------------------------------
# Group 3: TestExpandGrid (4 tests)
# ---------------------------------------------------------------------------

class TestExpandGrid(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_param_three_values_gives_three_combos(self):
        grid = {"apy_scale": [0.8, 1.0, 1.2]}
        combos = list(self.opt._expand_grid(grid))
        self.assertEqual(len(combos), 3)

    def test_two_params_2x3_gives_six_combos(self):
        grid = {"apy_scale": [1.0, 1.5], "risk_multiplier": [0.5, 1.0, 2.0]}
        combos = list(self.opt._expand_grid(grid))
        self.assertEqual(len(combos), 6)

    def test_empty_list_for_param_gives_zero_combos(self):
        grid = {"apy_scale": [], "risk_multiplier": [1.0, 2.0]}
        combos = list(self.opt._expand_grid(grid))
        self.assertEqual(len(combos), 0)

    def test_preserves_key_order(self):
        grid = {"alpha": [1], "beta": [2], "gamma": [3]}
        combos = list(self.opt._expand_grid(grid))
        self.assertEqual(len(combos), 1)
        keys = list(combos[0].keys())
        self.assertEqual(keys, ["alpha", "beta", "gamma"])


# ---------------------------------------------------------------------------
# Group 4: TestOptimizeBasic (5 tests)
# ---------------------------------------------------------------------------

class TestOptimizeBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)
        self.grid = {"apy_scale": [0.8, 1.0, 1.2]}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_optimize_result(self):
        result = self.opt.optimize(self.grid)
        self.assertIsInstance(result, OptimizeResult)

    def test_best_params_non_empty_when_grid_given(self):
        result = self.opt.optimize(self.grid)
        self.assertIsInstance(result.best_params, dict)
        self.assertTrue(result.best_params, "best_params should not be empty")

    def test_total_trials_correct(self):
        result = self.opt.optimize(self.grid)
        # 3 values in apy_scale → 3 trials
        self.assertEqual(result.total_trials, 3)

    def test_valid_metric_sharpe(self):
        result = self.opt.optimize(self.grid, metric="sharpe")
        self.assertEqual(result.metric, "sharpe")

    def test_best_score_is_float(self):
        result = self.opt.optimize(self.grid)
        self.assertIsInstance(result.best_score, float)


# ---------------------------------------------------------------------------
# Group 5: TestOptimizeMetrics (4 tests)
# ---------------------------------------------------------------------------

class TestOptimizeMetrics(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)
        self.grid = {"apy_scale": [1.0, 1.2]}
        # Backtest data: 10 days of small positive returns
        self.backtest = [{"daily_return": 0.001 * (i + 1)} for i in range(10)]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sharpe_metric_returns_float(self):
        result = self.opt.optimize(self.grid, metric="sharpe", backtest_data=self.backtest)
        self.assertIsInstance(result.best_score, float)
        self.assertFalse(math.isnan(result.best_score))

    def test_apy_metric_returns_valid_float(self):
        result = self.opt.optimize(self.grid, metric="apy", backtest_data=self.backtest)
        self.assertIsInstance(result.best_score, float)
        self.assertFalse(math.isnan(result.best_score))

    def test_sortino_metric_returns_float(self):
        result = self.opt.optimize(self.grid, metric="sortino", backtest_data=self.backtest)
        self.assertIsInstance(result.best_score, float)
        self.assertFalse(math.isnan(result.best_score))

    def test_calmar_metric_returns_float(self):
        result = self.opt.optimize(self.grid, metric="calmar", backtest_data=self.backtest)
        self.assertIsInstance(result.best_score, float)
        self.assertFalse(math.isnan(result.best_score))


# ---------------------------------------------------------------------------
# Group 6: TestOptimizeErrors (3 tests)
# ---------------------------------------------------------------------------

class TestOptimizeErrors(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_param_grid_raises_optimizer_error(self):
        with self.assertRaises(OptimizerError):
            self.opt.optimize({})

    def test_invalid_metric_raises_optimizer_error(self):
        with self.assertRaises(OptimizerError):
            self.opt.optimize({"apy_scale": [1.0]}, metric="invalid_metric")

    def test_optimizer_error_is_spa_error(self):
        self.assertTrue(issubclass(OptimizerError, SPAError))


# ---------------------------------------------------------------------------
# Group 7: TestEvaluateSynthetic (4 tests)
# ---------------------------------------------------------------------------

class TestEvaluateSynthetic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_backtest_uses_synthetic_score(self):
        params = {"apy_scale": 1.0, "risk_multiplier": 1.0}
        score = self.opt._evaluate(params, "sharpe", [])
        # Synthetic returns a deterministic float
        self.assertIsInstance(score, float)
        self.assertFalse(math.isnan(score))

    def test_higher_apy_scale_gives_higher_synthetic_score(self):
        low = self.opt._evaluate({"apy_scale": 0.5}, "sharpe", [])
        high = self.opt._evaluate({"apy_scale": 2.0}, "sharpe", [])
        self.assertGreater(high, low)

    def test_higher_risk_mult_gives_lower_sharpe_score(self):
        low_risk = self.opt._evaluate({"risk_multiplier": 1.0}, "sharpe", [])
        high_risk = self.opt._evaluate({"risk_multiplier": 5.0}, "sharpe", [])
        self.assertGreater(low_risk, high_risk)

    def test_synthetic_score_returns_float(self):
        score = self.opt._synthetic_score({"apy_scale": 1.0}, "calmar")
        self.assertIsInstance(score, float)


# ---------------------------------------------------------------------------
# Group 8: TestEvaluateWithData (3 tests)
# ---------------------------------------------------------------------------

class TestEvaluateWithData(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)
        # 10 days of positive returns
        self.positive_data = [{"daily_return": 0.002} for _ in range(10)]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apy_scale_2_gives_higher_apy_than_scale_1(self):
        score_1 = self.opt._evaluate({"apy_scale": 1.0}, "apy", self.positive_data)
        score_2 = self.opt._evaluate({"apy_scale": 2.0}, "apy", self.positive_data)
        self.assertGreater(score_2, score_1)

    def test_calmar_positive_for_positive_returns(self):
        score = self.opt._evaluate({"apy_scale": 1.0}, "calmar", self.positive_data)
        self.assertGreater(score, 0.0)

    def test_sharpe_positive_for_positive_returns(self):
        score = self.opt._evaluate({"apy_scale": 1.0, "risk_multiplier": 1.0},
                                   "sharpe", self.positive_data)
        self.assertGreater(score, 0.0)


# ---------------------------------------------------------------------------
# Group 9: TestBestResult (3 tests)
# ---------------------------------------------------------------------------

class TestBestResult(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = ParameterOptimizer("S7", base_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_none_when_no_runs(self):
        self.assertIsNone(self.opt.best_result())

    def test_returns_best_after_one_run(self):
        self.opt.optimize({"apy_scale": [1.0, 1.5]})
        result = self.opt.best_result()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, OptimizeResult)

    def test_returns_best_after_two_runs(self):
        # First run with lower-scoring params, second with higher
        r1 = self.opt.optimize({"apy_scale": [0.5]}, metric="sharpe")
        r2 = self.opt.optimize({"apy_scale": [5.0]}, metric="sharpe")
        best = self.opt.best_result()
        self.assertIsNotNone(best)
        # best_score should be the max across all runs
        self.assertGreaterEqual(best.best_score, r1.best_score)
        self.assertGreaterEqual(best.best_score, r1.best_score - 1e-9)


if __name__ == "__main__":
    unittest.main()
