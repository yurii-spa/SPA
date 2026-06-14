"""
Tests for MP-807: TokenPriceVolatilityTracker
≥65 test methods covering all logic paths, edge cases, and regime boundaries.

Run:  python3 -m unittest spa_core/tests/test_token_price_volatility_tracker.py
"""

import json
import math
import os
import tempfile
import unittest

# Allow import both as package and standalone
import sys
_here = os.path.dirname(os.path.abspath(__file__))
_repo = os.path.dirname(os.path.dirname(_here))
if _repo not in sys.path:
    sys.path.insert(0, _repo)

from spa_core.analytics.token_price_volatility_tracker import (
    _RING_BUFFER_CAP,
    _atomic_write,
    _classify_regime,
    _load_log,
    _max_drawdown,
    _stdev,
    _var,
    analyze,
)


# ── Helper factories ──────────────────────────────────────────────────────────

def _flat(n: int, price: float = 100.0):
    """Flat price series (zero returns)."""
    return [price] * n


def _rising(n: int, start: float = 100.0, daily_return: float = 0.01):
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return prices


def _falling(n: int, start: float = 100.0, daily_return: float = -0.01):
    return _rising(n, start, daily_return)


def _prices_with_known_vol(n: int, daily_vol: float = 0.02, start: float = 100.0):
    """Deterministic zigzag that gives non-zero std-dev."""
    prices = [start]
    for i in range(n - 1):
        delta = daily_vol if i % 2 == 0 else -daily_vol
        prices.append(prices[-1] * (1 + delta))
    return prices


# ── Core analyze() tests ─────────────────────────────────────────────────────

class TestAnalyzeBasic(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze("ETH", [100.0, 110.0])
        self.assertIsInstance(r, dict)

    def test_required_keys_present(self):
        r = analyze("USDC", _flat(10))
        keys = {
            "token", "price_current", "price_7d_ago", "price_30d_ago",
            "return_7d_pct", "return_30d_pct", "daily_returns",
            "volatility_daily_pct", "volatility_annual_pct",
            "max_drawdown_pct", "var_95_daily_pct", "volatility_regime",
            "sharpe_proxy", "timestamp",
        }
        self.assertEqual(keys, keys & set(r.keys()))

    def test_token_name_preserved(self):
        r = analyze("WBTC", [1.0, 2.0])
        self.assertEqual(r["token"], "WBTC")

    def test_price_current_is_last_price(self):
        r = analyze("ETH", [100.0, 200.0, 300.0])
        self.assertAlmostEqual(r["price_current"], 300.0)

    def test_timestamp_is_float(self):
        r = analyze("ETH", [1.0, 2.0])
        self.assertIsInstance(r["timestamp"], float)
        self.assertGreater(r["timestamp"], 0.0)

    def test_daily_returns_length(self):
        prices = [10.0, 11.0, 12.0, 13.0]
        r = analyze("T", prices)
        self.assertEqual(len(r["daily_returns"]), 3)

    def test_daily_returns_values(self):
        prices = [100.0, 110.0, 99.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["daily_returns"][0], 0.1)
        self.assertAlmostEqual(r["daily_returns"][1], (99 - 110) / 110)

    def test_flat_prices_zero_vol(self):
        r = analyze("USDC", _flat(30))
        self.assertAlmostEqual(r["volatility_daily_pct"], 0.0)
        self.assertAlmostEqual(r["volatility_annual_pct"], 0.0)

    def test_flat_prices_regime_low(self):
        r = analyze("USDC", _flat(30))
        self.assertEqual(r["volatility_regime"], "LOW")

    def test_flat_prices_no_drawdown(self):
        r = analyze("USDC", _flat(30))
        self.assertAlmostEqual(r["max_drawdown_pct"], 0.0)

    def test_flat_prices_sharpe_none(self):
        r = analyze("USDC", _flat(30))
        self.assertIsNone(r["sharpe_proxy"])

    def test_rising_prices_zero_drawdown(self):
        r = analyze("T", _rising(20))
        self.assertAlmostEqual(r["max_drawdown_pct"], 0.0)

    def test_rising_prices_positive_sharpe(self):
        r = analyze("T", _rising(30, daily_return=0.02))
        self.assertIsNotNone(r["sharpe_proxy"])
        self.assertGreater(r["sharpe_proxy"], 0.0)

    def test_falling_prices_drawdown_nonzero(self):
        r = analyze("T", _falling(20))
        self.assertGreater(r["max_drawdown_pct"], 0.0)

    def test_two_prices_one_return(self):
        r = analyze("T", [100.0, 120.0])
        self.assertEqual(len(r["daily_returns"]), 1)
        self.assertAlmostEqual(r["daily_returns"][0], 0.2)

    def test_two_prices_vol_zero(self):
        # Only one return → stdev is 0
        r = analyze("T", [100.0, 120.0])
        self.assertAlmostEqual(r["volatility_daily_pct"], 0.0)


# ── Look-back price tests ─────────────────────────────────────────────────────

class TestLookbackPrices(unittest.TestCase):

    def test_7d_ago_none_when_fewer_than_8_prices(self):
        r = analyze("T", [1.0] * 7)
        self.assertIsNone(r["price_7d_ago"])

    def test_7d_ago_present_with_8_prices(self):
        prices = list(range(1, 9))   # 1..8
        r = analyze("T", prices)
        self.assertAlmostEqual(r["price_7d_ago"], 1.0)  # prices[-8] = prices[0]

    def test_return_7d_pct_none_when_price_7d_none(self):
        r = analyze("T", [1.0] * 5)
        self.assertIsNone(r["return_7d_pct"])

    def test_return_7d_pct_computed(self):
        prices = [100.0] * 7 + [110.0]   # 8 prices; 7d ago = 100, current = 110
        r = analyze("T", prices)
        self.assertAlmostEqual(r["return_7d_pct"], 10.0)

    def test_30d_ago_none_when_fewer_than_31_prices(self):
        r = analyze("T", [1.0] * 30)
        self.assertIsNone(r["price_30d_ago"])

    def test_30d_ago_present_with_31_prices(self):
        prices = [1.0] * 30 + [2.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["price_30d_ago"], 1.0)

    def test_return_30d_pct_computed(self):
        prices = [100.0] * 30 + [150.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["return_30d_pct"], 50.0)

    def test_return_30d_pct_negative(self):
        prices = [200.0] * 30 + [100.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["return_30d_pct"], -50.0)


# ── Volatility regime boundary tests ─────────────────────────────────────────

class TestVolatilityRegimes(unittest.TestCase):

    def test_regime_low_below_30(self):
        self.assertEqual(_classify_regime(0.0), "LOW")
        self.assertEqual(_classify_regime(15.0), "LOW")
        self.assertEqual(_classify_regime(29.99), "LOW")

    def test_regime_medium_30_to_60(self):
        self.assertEqual(_classify_regime(30.0), "MEDIUM")
        self.assertEqual(_classify_regime(45.0), "MEDIUM")
        self.assertEqual(_classify_regime(59.99), "MEDIUM")

    def test_regime_high_60_to_100(self):
        self.assertEqual(_classify_regime(60.0), "HIGH")
        self.assertEqual(_classify_regime(80.0), "HIGH")
        self.assertEqual(_classify_regime(99.99), "HIGH")

    def test_regime_extreme_100_plus(self):
        self.assertEqual(_classify_regime(100.0), "EXTREME")
        self.assertEqual(_classify_regime(200.0), "EXTREME")

    def test_analyze_returns_low_regime(self):
        # daily vol ~0.01 → annual ~0.01*sqrt(365)*100 ≈ 19.1%
        r = analyze("T", _prices_with_known_vol(50, 0.01))
        self.assertEqual(r["volatility_regime"], "LOW")

    def test_analyze_returns_medium_regime(self):
        # daily vol ~0.025 → annual ~0.025*sqrt(365)*100 ≈ 47.8%
        r = analyze("T", _prices_with_known_vol(50, 0.025))
        self.assertEqual(r["volatility_regime"], "MEDIUM")

    def test_analyze_returns_high_regime(self):
        # daily vol ~0.05 → annual ~0.05*sqrt(365)*100 ≈ 95.5%
        r = analyze("T", _prices_with_known_vol(100, 0.05))
        self.assertEqual(r["volatility_regime"], "HIGH")

    def test_analyze_returns_extreme_regime(self):
        # daily vol ~0.06 → annual ~0.06*sqrt(365)*100 ≈ 114.6%
        r = analyze("T", _prices_with_known_vol(200, 0.06))
        self.assertEqual(r["volatility_regime"], "EXTREME")


# ── VaR tests ────────────────────────────────────────────────────────────────

class TestVaR(unittest.TestCase):

    def test_var_empty_returns_zero(self):
        self.assertAlmostEqual(_var([], 0.95), 0.0)

    def test_var_single_return(self):
        # With 1 return, floor(1 * 0.05) = 0, idx=0 → that single value
        result = _var([-0.05], 0.95)
        self.assertAlmostEqual(result, -0.05 * 100)

    def test_var_all_positive_returns_nonnegative(self):
        # If all returns positive, 5th percentile may still be positive
        returns = [0.01 * i for i in range(1, 21)]
        result = _var(returns, 0.95)
        # floor(20 * 0.05) = 1 → sorted[1] = 0.02
        self.assertAlmostEqual(result, 0.02 * 100)

    def test_var_negative_returns_negative(self):
        returns = [-0.05, -0.03, -0.01, 0.01, 0.03]
        # sorted: [-0.05,-0.03,-0.01,0.01,0.03]; floor(5*0.05)=0 → -0.05
        result = _var(returns, 0.95)
        self.assertAlmostEqual(result, -5.0)

    def test_var_analyze_is_pct(self):
        prices = [100.0 * (0.98 ** i) for i in range(30)]
        r = analyze("T", prices)
        # var_95_daily_pct should be a percentage (float)
        self.assertIsInstance(r["var_95_daily_pct"], float)

    def test_var_90_confidence(self):
        returns = list(range(-10, 10))   # -10..9, 20 values
        # Due to floating point: 1-0.90 = 0.09999...998
        # floor(20 * 0.09999...998) = floor(1.9999...) = 1 → sorted[1] = -9
        result = _var(returns, 0.90)
        self.assertAlmostEqual(result, -9 * 100)

    def test_var_confidence_in_config(self):
        prices = [100.0, 95.0, 90.0, 85.0, 80.0]
        r1 = analyze("T", prices, {"var_confidence": 0.95})
        r2 = analyze("T", prices, {"var_confidence": 0.50})
        # Different confidence → different VaR (generally)
        self.assertIsInstance(r1["var_95_daily_pct"], float)
        self.assertIsInstance(r2["var_95_daily_pct"], float)


# ── Max Drawdown tests ───────────────────────────────────────────────────────

class TestMaxDrawdown(unittest.TestCase):

    def test_drawdown_rising_zero(self):
        self.assertAlmostEqual(_max_drawdown(_rising(20)), 0.0)

    def test_drawdown_flat_zero(self):
        self.assertAlmostEqual(_max_drawdown(_flat(10)), 0.0)

    def test_drawdown_single_price(self):
        self.assertAlmostEqual(_max_drawdown([100.0]), 0.0)

    def test_drawdown_known_drop(self):
        # peak=100, then drops to 80 → drawdown = 20%
        prices = [100.0, 80.0]
        self.assertAlmostEqual(_max_drawdown(prices), 20.0)

    def test_drawdown_recovery_after_drop(self):
        # peak=100, drops to 50, recovers to 100 → max dd = 50%
        prices = [100.0, 50.0, 100.0]
        self.assertAlmostEqual(_max_drawdown(prices), 50.0)

    def test_drawdown_multiple_drops(self):
        # 100 → 90 → 80 → 90 → 70 → 100
        prices = [100.0, 90.0, 80.0, 90.0, 70.0, 100.0]
        self.assertAlmostEqual(_max_drawdown(prices), 30.0)

    def test_drawdown_analyze_returns_pct(self):
        prices = [100.0, 50.0, 80.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["max_drawdown_pct"], 50.0)

    def test_drawdown_only_rises(self):
        r = analyze("T", _rising(15))
        self.assertAlmostEqual(r["max_drawdown_pct"], 0.0)


# ── Std-dev helper tests ──────────────────────────────────────────────────────

class TestStdev(unittest.TestCase):

    def test_empty_list(self):
        self.assertAlmostEqual(_stdev([]), 0.0)

    def test_single_element(self):
        self.assertAlmostEqual(_stdev([5.0]), 0.0)

    def test_identical_values(self):
        self.assertAlmostEqual(_stdev([3.0, 3.0, 3.0]), 0.0)

    def test_known_stdev(self):
        # [2, 4, 4, 4, 5, 5, 7, 9] — mean=5, sum_sq_dev=32
        # sample stdev (n-1): sqrt(32/7) ≈ 2.1381
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        expected = math.sqrt(32.0 / 7.0)
        self.assertAlmostEqual(_stdev(vals), expected, places=10)

    def test_two_values(self):
        vals = [0.0, 1.0]
        self.assertAlmostEqual(_stdev(vals), math.sqrt(0.5), places=10)


# ── Config tests ──────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):

    def test_default_annualize_factor(self):
        prices = _rising(20, daily_return=0.01)
        r = analyze("T", prices)
        daily_vol = r["volatility_daily_pct"]
        expected_annual = daily_vol * math.sqrt(365)
        self.assertAlmostEqual(r["volatility_annual_pct"], expected_annual, places=5)

    def test_custom_annualize_factor_252(self):
        prices = _rising(20, daily_return=0.01)
        r = analyze("T", prices, {"annualize_factor": 252})
        daily_vol = r["volatility_daily_pct"]
        expected_annual = daily_vol * math.sqrt(252)
        self.assertAlmostEqual(r["volatility_annual_pct"], expected_annual, places=5)

    def test_none_config_uses_defaults(self):
        r = analyze("T", [100.0, 101.0, 102.0], None)
        self.assertIn("volatility_regime", r)

    def test_empty_config_uses_defaults(self):
        r = analyze("T", [100.0, 101.0, 102.0], {})
        self.assertIn("volatility_annual_pct", r)


# ── Edge-case tests ───────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_empty_prices_returns_dict(self):
        r = analyze("T", [])
        self.assertIsInstance(r, dict)
        self.assertEqual(r["token"], "T")

    def test_empty_prices_zero_vol(self):
        r = analyze("T", [])
        self.assertAlmostEqual(r["volatility_daily_pct"], 0.0)

    def test_single_price_empty_returns(self):
        r = analyze("T", [42.0])
        self.assertEqual(r["daily_returns"], [])

    def test_single_price_current_correct(self):
        r = analyze("T", [42.0])
        self.assertAlmostEqual(r["price_current"], 42.0)

    def test_single_price_no_7d(self):
        r = analyze("T", [42.0])
        self.assertIsNone(r["price_7d_ago"])

    def test_large_price_spike(self):
        prices = [1.0, 1000.0, 1.0]
        r = analyze("T", prices)
        self.assertGreater(r["volatility_daily_pct"], 0.0)
        self.assertGreater(r["max_drawdown_pct"], 0.0)

    def test_zero_denominator_same_price(self):
        # If price stays the same, no division error
        prices = [100.0, 100.0, 100.0]
        r = analyze("T", prices)
        self.assertAlmostEqual(r["volatility_daily_pct"], 0.0)

    def test_volatility_annual_gt_daily(self):
        prices = _prices_with_known_vol(50, 0.02)
        r = analyze("T", prices)
        if r["volatility_daily_pct"] > 0:
            self.assertGreater(r["volatility_annual_pct"], r["volatility_daily_pct"])

    def test_token_with_spaces(self):
        r = analyze("My Token XYZ", [1.0, 2.0])
        self.assertEqual(r["token"], "My Token XYZ")

    def test_integer_prices_accepted(self):
        r = analyze("T", [100, 110, 105])
        self.assertAlmostEqual(r["price_current"], 105.0)

    def test_sharpe_negative_for_falling_prices(self):
        prices = _falling(30, daily_return=-0.01)
        r = analyze("T", prices)
        if r["sharpe_proxy"] is not None:
            self.assertLess(r["sharpe_proxy"], 0.0)

    def test_all_same_prices_regime_low(self):
        r = analyze("T", [50.0] * 100)
        self.assertEqual(r["volatility_regime"], "LOW")

    def test_returns_list_not_tuple(self):
        r = analyze("T", [1.0, 2.0, 3.0])
        self.assertIsInstance(r["daily_returns"], list)


# ── Log persistence tests ─────────────────────────────────────────────────────

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Patch the module-level _LOG_FILE and _DATA_DIR
        import spa_core.analytics.token_price_volatility_tracker as mod
        self._mod = mod
        self._orig_log = mod._LOG_FILE
        self._orig_data = mod._DATA_DIR
        self._tmplog = os.path.join(self._tmpdir, "token_volatility_log.json")
        mod._LOG_FILE = self._tmplog
        mod._DATA_DIR = self._tmpdir

    def tearDown(self):
        self._mod._LOG_FILE = self._orig_log
        self._mod._DATA_DIR = self._orig_data

    def test_log_created_after_analyze(self):
        analyze("T", [1.0, 2.0])
        self.assertTrue(os.path.exists(self._tmplog))

    def test_log_is_list(self):
        analyze("T", [1.0, 2.0])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_token(self):
        analyze("ETH", [1.0, 2.0])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["token"], "ETH")

    def test_log_ring_buffer_cap(self):
        for i in range(_RING_BUFFER_CAP + 10):
            analyze("T", [float(i), float(i + 1)])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _RING_BUFFER_CAP)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            analyze("T", [1.0, 2.0])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_contains_daily_returns_len(self):
        analyze("T", [1.0, 2.0, 3.0])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertIn("daily_returns_len", data[-1])
        self.assertEqual(data[-1]["daily_returns_len"], 2)

    def test_log_no_full_daily_returns_array(self):
        # daily_returns should not be stored in log (only the len)
        analyze("T", [1.0, 2.0, 3.0, 4.0])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertNotIn("daily_returns", data[-1])

    def test_atomic_write_creates_file(self):
        path = os.path.join(self._tmpdir, "test_atomic.json")
        _atomic_write(path, {"ok": True})
        with open(path) as f:
            self.assertEqual(json.load(f), {"ok": True})

    def test_load_log_missing_file_returns_empty(self):
        import spa_core.analytics.token_price_volatility_tracker as mod
        mod._LOG_FILE = os.path.join(self._tmpdir, "nonexistent.json")
        result = _load_log()
        self.assertEqual(result, [])

    def test_load_log_corrupt_json_returns_empty(self):
        bad = os.path.join(self._tmpdir, "bad.json")
        with open(bad, "w") as f:
            f.write("{bad json{{")
        import spa_core.analytics.token_price_volatility_tracker as mod
        mod._LOG_FILE = bad
        result = _load_log()
        self.assertEqual(result, [])


# ── Annualised volatility arithmetic ──────────────────────────────────────────

class TestVolatilityArithmetic(unittest.TestCase):

    def test_annualized_equals_daily_times_sqrt_factor(self):
        prices = _prices_with_known_vol(50, 0.03)
        r = analyze("T", prices)
        daily = r["volatility_daily_pct"]
        annual = r["volatility_annual_pct"]
        self.assertAlmostEqual(annual, daily * math.sqrt(365), places=5)

    def test_custom_annualize_factor_100(self):
        prices = _prices_with_known_vol(50, 0.03)
        r = analyze("T", prices, {"annualize_factor": 100})
        daily = r["volatility_daily_pct"]
        annual = r["volatility_annual_pct"]
        self.assertAlmostEqual(annual, daily * math.sqrt(100), places=5)

    def test_volatility_always_nonnegative(self):
        for daily_vol in [0.0, 0.01, 0.05, 0.10]:
            r = analyze("T", _prices_with_known_vol(30, daily_vol))
            self.assertGreaterEqual(r["volatility_daily_pct"], 0.0)
            self.assertGreaterEqual(r["volatility_annual_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
