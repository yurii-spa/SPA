"""
tests/test_aave_v3_improved.py

MP-1548 (v11.64) — 25 tests for AaveV3Adapter improvements:
  - Instance-level APY cache (5-min TTL)
  - Supply / borrow rate separation
  - Utilization rate monitoring (warning at > 90%)

All tests use offline mocks — no live DeFiLlama calls.
"""
import sys
import os
import time
import unittest
from unittest.mock import MagicMock

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.adapters.aave_v3 import AaveV3Adapter, UTILIZATION_WARNING_THRESHOLD, _CACHE_TTL
from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed(apy_decimal=0.035, tvl=5_000_000_000.0,
               apy_base_pct=None, borrow_pct=None):
    """Build a mock DeFiLlamaFeed."""
    feed = MagicMock()
    # get_apy returns decimal (e.g. 0.035)
    feed.get_apy.return_value = apy_decimal
    feed.get_tvl.return_value = tvl
    # get_pool returns a pool dict with apyBase / apyBaseBorrow
    pool = {"apy": (apy_decimal * 100 if apy_decimal else None)}
    if apy_base_pct is not None:
        pool["apyBase"] = apy_base_pct
    if borrow_pct is not None:
        pool["apyBaseBorrow"] = borrow_pct
    feed.get_pool.return_value = pool
    return feed


def _make_adapter(**kwargs):
    feed = _make_feed(**kwargs)
    return AaveV3Adapter(feed=feed)


# ===========================================================================
# 1. Core interface — backwards-compatible with pre-MP-1548
# ===========================================================================

class TestAaveV3CoreInterface(unittest.TestCase):

    def test_inherits_base_adapter(self):
        a = _make_adapter()
        self.assertIsInstance(a, BaseAdapter)

    def test_protocol(self):
        a = _make_adapter()
        self.assertEqual(a.PROTOCOL, "aave_v3")

    def test_tier_t1(self):
        a = _make_adapter()
        self.assertEqual(a.TIER, "T1")
        self.assertEqual(a.tier, "T1")

    def test_get_apy_returns_decimal(self):
        a = _make_adapter(apy_decimal=0.035)
        result = a.get_apy()
        self.assertAlmostEqual(result, 0.035, places=5)

    def test_get_apy_none_on_feed_miss(self):
        feed = MagicMock()
        feed.get_apy.return_value = None
        feed.get_tvl.return_value = None
        feed.get_pool.return_value = None
        a = AaveV3Adapter(feed=feed)
        self.assertIsNone(a.get_apy())

    def test_get_yield_info_type(self):
        a = _make_adapter()
        self.assertIsInstance(a.get_yield_info(), YieldInfo)

    def test_get_yield_info_tier(self):
        a = _make_adapter()
        yi = a.get_yield_info()
        self.assertEqual(yi.tier, "T1")


# ===========================================================================
# 2. Instance-level APY cache (MP-1548)
# ===========================================================================

class TestAaveV3Cache(unittest.TestCase):

    def test_fetch_cached_returns_dict(self):
        a = _make_adapter()
        result = a._fetch_cached()
        self.assertIsInstance(result, dict)

    def test_fetch_cached_same_object_on_hit(self):
        """Within TTL, _fetch_cached must return the exact same dict."""
        a = _make_adapter()
        first = a._fetch_cached()
        second = a._fetch_cached()
        self.assertIs(first, second)

    def test_fetch_called_once_within_ttl(self):
        """live feed fetch() should be called only once within TTL."""
        feed = _make_feed()
        a = AaveV3Adapter(feed=feed)
        a._fetch_cached()
        a._fetch_cached()
        a._fetch_cached()
        # fetch() is wrapped via safe_call → feed.get_apy called once
        self.assertEqual(feed.get_apy.call_count, 1)

    def test_invalidate_cache_clears_data(self):
        a = _make_adapter()
        a._fetch_cached()
        a.invalidate_cache()
        self.assertIsNone(a._cache_data)

    def test_invalidate_cache_resets_ts(self):
        a = _make_adapter()
        a._fetch_cached()
        a.invalidate_cache()
        self.assertEqual(a._cache_ts, 0.0)

    def test_cache_ttl_constant_positive(self):
        self.assertGreater(_CACHE_TTL, 0)

    def test_cache_refreshes_after_expiry(self):
        """After forced timestamp expiry, _fetch_cached should re-fetch."""
        feed = _make_feed()
        a = AaveV3Adapter(feed=feed)
        a._fetch_cached()
        # Expire the cache manually
        a._cache_ts = time.time() - _CACHE_TTL - 1
        a._fetch_cached()
        # Should have called feed twice now
        self.assertGreaterEqual(feed.get_apy.call_count, 2)


# ===========================================================================
# 3. Supply / borrow rate separation (MP-1548)
# ===========================================================================

class TestAaveV3RateSeparation(unittest.TestCase):

    def test_get_supply_rate_returns_decimal(self):
        a = _make_adapter(apy_base_pct=3.5)
        result = a.get_supply_rate()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.035, places=5)

    def test_get_supply_rate_none_on_missing_field(self):
        feed = MagicMock()
        feed.get_pool.return_value = {"apy": 3.5}  # no apyBase field
        a = AaveV3Adapter(feed=feed)
        self.assertIsNone(a.get_supply_rate())

    def test_get_borrow_rate_returns_decimal(self):
        a = _make_adapter(borrow_pct=5.2)
        result = a.get_borrow_rate()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.052, places=5)

    def test_get_borrow_rate_none_on_missing_field(self):
        feed = MagicMock()
        feed.get_pool.return_value = {"apy": 3.5}  # no apyBaseBorrow
        a = AaveV3Adapter(feed=feed)
        self.assertIsNone(a.get_borrow_rate())

    def test_get_supply_rate_pool_none(self):
        feed = MagicMock()
        feed.get_pool.return_value = None
        a = AaveV3Adapter(feed=feed)
        self.assertIsNone(a.get_supply_rate())

    def test_get_borrow_rate_positive(self):
        """Borrow rate must always be returned as positive (abs value)."""
        a = _make_adapter(borrow_pct=-4.0)  # DeFiLlama sometimes returns negative
        result = a.get_borrow_rate()
        if result is not None:
            self.assertGreaterEqual(result, 0.0)


# ===========================================================================
# 4. Utilization monitoring (MP-1548)
# ===========================================================================

class TestAaveV3Utilization(unittest.TestCase):

    def test_utilization_warning_threshold(self):
        self.assertEqual(UTILIZATION_WARNING_THRESHOLD, 0.90)

    def test_get_utilization_returns_float(self):
        a = _make_adapter(apy_base_pct=3.5, borrow_pct=5.0)
        util = a.get_utilization()
        self.assertIsInstance(util, float)

    def test_get_utilization_in_range(self):
        a = _make_adapter(apy_base_pct=3.5, borrow_pct=5.0)
        util = a.get_utilization()
        self.assertGreaterEqual(util, 0.0)
        self.assertLessEqual(util, 1.0)

    def test_get_utilization_zero_on_missing_data(self):
        feed = MagicMock()
        feed.get_pool.return_value = {}  # no APY fields
        a = AaveV3Adapter(feed=feed)
        self.assertEqual(a.get_utilization(), 0.0)

    def test_is_utilization_safe_true_normal(self):
        # supply=3.5%, borrow=5.0% → utilization ≈ 0.70 < 0.90
        a = _make_adapter(apy_base_pct=3.5, borrow_pct=5.0)
        self.assertTrue(a.is_utilization_safe())

    def test_is_utilization_safe_false_high(self):
        # supply=9.0%, borrow=10.0% → utilization = 0.90 (boundary)
        a = _make_adapter(apy_base_pct=9.5, borrow_pct=10.0)
        # 9.5/10.0 = 0.95 > 0.90 → not safe
        self.assertFalse(a.is_utilization_safe())

    def test_is_utilization_safe_true_on_no_data(self):
        """When feed is unavailable, fail-open → safe."""
        feed = MagicMock()
        feed.get_apy.return_value = None
        feed.get_pool.return_value = None
        a = AaveV3Adapter(feed=feed)
        self.assertTrue(a.is_utilization_safe())

    def test_utilization_status_keys(self):
        a = _make_adapter(apy_base_pct=3.5, borrow_pct=5.0)
        status = a.utilization_status()
        for key in ("utilization", "safe", "threshold", "supply_rate", "borrow_rate"):
            self.assertIn(key, status)

    def test_utilization_status_threshold_value(self):
        a = _make_adapter()
        status = a.utilization_status()
        self.assertEqual(status["threshold"], UTILIZATION_WARNING_THRESHOLD)

    def test_utilization_status_safe_consistent_with_method(self):
        a = _make_adapter(apy_base_pct=3.5, borrow_pct=5.0)
        self.assertEqual(a.utilization_status()["safe"], a.is_utilization_safe())


if __name__ == "__main__":
    unittest.main(verbosity=2)
