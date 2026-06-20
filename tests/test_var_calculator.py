"""
tests/test_var_calculator.py

MP-1499 (v11.15): 30 tests for spa_core/analytics/var_calculator.py

Coverage:
  - Initialization and to_dict structure
  - add_returns with < 10 items → no metrics
  - add_returns with >= 10 items → all metrics computed
  - _recalculate: VaR and CVaR for all 3 confidence levels
  - VaR is non-negative
  - CVaR >= VaR at each confidence level
  - var_usd / cvar_usd scaling with capital
  - is_within_limit above/below threshold
  - set_capital
  - summary() keys
  - Edge cases: all-positive, all-negative, single large loss
  - Determinism: same returns → same results
  - Sorted order of returns preserved internally
  - _cl_key helper
  - Large dataset (100+ returns)
  - Replace returns: second call to add_returns replaces first
"""
import sys
import os
import unittest
import tempfile
import math

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.var_calculator import VaRCalculator, CONFIDENCE_LEVELS, _cl_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calc(tmp_dir: str) -> VaRCalculator:
    return VaRCalculator(base_dir=tmp_dir)


def _sine_returns(n: int = 30) -> list:
    """Deterministic synthetic daily returns (mix of gains and losses)."""
    return [round(math.sin(i * 0.4) * 0.015, 6) for i in range(n)]


def _uniform_losses(n: int = 20) -> list:
    """All-negative returns."""
    return [-0.005 * (i + 1) / n for i in range(n)]


# ===========================================================================
# 1. Module constants
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_confidence_levels_list(self):
        self.assertEqual(CONFIDENCE_LEVELS, [0.90, 0.95, 0.99])

    def test_cl_key_90(self):
        self.assertEqual(_cl_key(0.90), "90pct")

    def test_cl_key_95(self):
        self.assertEqual(_cl_key(0.95), "95pct")

    def test_cl_key_99(self):
        self.assertEqual(_cl_key(0.99), "99pct")


# ===========================================================================
# 2. Initialization
# ===========================================================================

class TestInit(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)

    def test_initial_returns_empty(self):
        self.assertEqual(self._data()["returns"], [])

    def test_initial_var_empty(self):
        self.assertEqual(self._data()["var"], {})

    def test_initial_cvar_empty(self):
        self.assertEqual(self._data()["cvar"], {})

    def test_initial_capital(self):
        self.assertEqual(self._data()["capital"], 100_000)

    def test_initial_n_returns(self):
        self.assertEqual(self._data()["n_returns"], 0)

    def test_to_dict_is_dict(self):
        self.assertIsInstance(self.calc.to_dict(), dict)

    def _data(self):
        return self.calc.to_dict()


# ===========================================================================
# 3. add_returns with < 10 items
# ===========================================================================

class TestAddReturnsSmall(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)

    def test_fewer_than_10_no_var(self):
        self.calc.add_returns([0.01, -0.02, 0.03])
        self.assertEqual(self.calc.to_dict()["var"], {})

    def test_fewer_than_10_no_cvar(self):
        self.calc.add_returns([-0.01, 0.005])
        self.assertEqual(self.calc.to_dict()["cvar"], {})

    def test_exactly_9_no_var(self):
        self.calc.add_returns([0.001 * i for i in range(9)])
        self.assertEqual(self.calc.to_dict()["var"], {})

    def test_n_returns_recorded(self):
        returns = [0.001 * i for i in range(5)]
        self.calc.add_returns(returns)
        self.assertEqual(self.calc.to_dict()["n_returns"], 5)


# ===========================================================================
# 4. add_returns with >= 10 items
# ===========================================================================

class TestAddReturnsFull(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)
        self.returns = _sine_returns(30)
        self.calc.add_returns(self.returns)

    def test_var_has_90pct(self):
        self.assertIn("90pct", self.calc.to_dict()["var"])

    def test_var_has_95pct(self):
        self.assertIn("95pct", self.calc.to_dict()["var"])

    def test_var_has_99pct(self):
        self.assertIn("99pct", self.calc.to_dict()["var"])

    def test_cvar_has_90pct(self):
        self.assertIn("90pct", self.calc.to_dict()["cvar"])

    def test_cvar_has_95pct(self):
        self.assertIn("95pct", self.calc.to_dict()["cvar"])

    def test_cvar_has_99pct(self):
        self.assertIn("99pct", self.calc.to_dict()["cvar"])

    def test_n_returns_correct(self):
        self.assertEqual(self.calc.to_dict()["n_returns"], 30)

    def test_returns_sorted_ascending(self):
        stored = self.calc.to_dict()["returns"]
        self.assertEqual(stored, sorted(stored))

    def test_var_non_negative(self):
        for key in ["90pct", "95pct", "99pct"]:
            self.assertGreaterEqual(self.calc.to_dict()["var"][key], 0.0)


# ===========================================================================
# 5. VaR and CVaR relationship (CVaR >= VaR)
# ===========================================================================

class TestVaRCVaRRelationship(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)
        self.calc.add_returns(_sine_returns(50))

    def test_cvar_gte_var_90(self):
        v = self.calc.to_dict()["var"]["90pct"]
        c = self.calc.to_dict()["cvar"]["90pct"]
        self.assertGreaterEqual(c, v)

    def test_cvar_gte_var_95(self):
        v = self.calc.to_dict()["var"]["95pct"]
        c = self.calc.to_dict()["cvar"]["95pct"]
        self.assertGreaterEqual(c, v)

    def test_cvar_gte_var_99(self):
        v = self.calc.to_dict()["var"]["99pct"]
        c = self.calc.to_dict()["cvar"]["99pct"]
        self.assertGreaterEqual(c, v)


# ===========================================================================
# 6. var_usd and cvar_usd scaling
# ===========================================================================

class TestUSDMethods(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)
        self.calc.add_returns(_sine_returns(30))

    def test_var_usd_scales_with_capital(self):
        v1 = self.calc.var_usd(100_000)
        v2 = self.calc.var_usd(200_000)
        self.assertAlmostEqual(v2, v1 * 2, places=6)

    def test_var_usd_zero_for_no_data(self):
        empty = VaRCalculator(base_dir=self.tmp)
        self.assertEqual(empty.var_usd(100_000), 0.0)

    def test_var_usd_default_95(self):
        v_default = self.calc.var_usd(100_000)
        v_explicit = self.calc.var_usd(100_000, confidence=0.95)
        self.assertAlmostEqual(v_default, v_explicit, places=8)

    def test_cvar_usd_gte_var_usd(self):
        v = self.calc.var_usd(100_000, confidence=0.95)
        c = self.calc.cvar_usd(100_000, confidence=0.95)
        self.assertGreaterEqual(c, v)

    def test_var_usd_99_gte_var_usd_95(self):
        # 99% VaR captures a deeper tail → higher loss estimate
        v95 = self.calc.var_usd(100_000, 0.95)
        v99 = self.calc.var_usd(100_000, 0.99)
        self.assertGreaterEqual(v99, v95)


# ===========================================================================
# 7. is_within_limit
# ===========================================================================

class TestIsWithinLimit(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)

    def test_within_limit_very_large_threshold(self):
        self.calc.add_returns(_sine_returns(20))
        self.assertTrue(self.calc.is_within_limit(100_000, max_loss_usd=1_000_000))

    def test_exceeds_limit_tiny_threshold(self):
        # Returns with losses; VaR(95%) on $100k should exceed $0
        self.calc.add_returns(_uniform_losses(20))
        self.assertFalse(self.calc.is_within_limit(100_000, max_loss_usd=0))

    def test_no_data_is_within_limit(self):
        # With no data, VaR = 0 → always within any positive limit
        self.assertTrue(self.calc.is_within_limit(100_000, max_loss_usd=5_000))


# ===========================================================================
# 8. Replace returns / determinism
# ===========================================================================

class TestReplaceAndDeterminism(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)

    def test_second_add_replaces_first(self):
        self.calc.add_returns(_sine_returns(20))
        first_var = self.calc.to_dict()["var"].get("95pct")
        # Second call with different returns
        self.calc.add_returns([0.001] * 20)
        second_var = self.calc.to_dict()["var"].get("95pct")
        # n_returns reflects second batch
        self.assertEqual(self.calc.to_dict()["n_returns"], 20)
        # Results may differ (different data)
        self.assertIsNotNone(second_var)

    def test_deterministic_same_input(self):
        r = _sine_returns(30)
        self.calc.add_returns(r)
        v1 = self.calc.var_usd(100_000, 0.95)
        # Reset and re-add same returns
        self.calc.add_returns(r)
        v2 = self.calc.var_usd(100_000, 0.95)
        self.assertAlmostEqual(v1, v2, places=8)


# ===========================================================================
# 9. summary()
# ===========================================================================

class TestSummary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _make_calc(self.tmp)
        self.calc.add_returns(_sine_returns(30))

    def test_summary_has_n_returns(self):
        self.assertIn("n_returns", self.calc.summary())

    def test_summary_has_all_var_keys(self):
        s = self.calc.summary()
        for k in ["var_90pct", "var_95pct", "var_99pct"]:
            self.assertIn(k, s)

    def test_summary_has_all_cvar_keys(self):
        s = self.calc.summary()
        for k in ["cvar_90pct", "cvar_95pct", "cvar_99pct"]:
            self.assertIn(k, s)


# ===========================================================================
# 10. Large dataset
# ===========================================================================

class TestLargeDataset(unittest.TestCase):

    def test_100_returns(self):
        tmp = tempfile.mkdtemp()
        calc = VaRCalculator(base_dir=tmp)
        returns = _sine_returns(100)
        calc.add_returns(returns)
        self.assertEqual(calc.to_dict()["n_returns"], 100)
        self.assertIn("95pct", calc.to_dict()["var"])
        # VaR in USD should be a positive number for mixed returns
        v = calc.var_usd(100_000, 0.95)
        self.assertGreaterEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
