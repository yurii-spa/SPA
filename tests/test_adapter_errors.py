"""
tests/test_adapter_errors.py

MP-1416 (v10.32) — Error catalog adapter layer: 25 тестов.

Проверяет:
  1. T1 адаптеры при недоступном DeFiLlama → возвращают None/fallback (не бросают)
  2. T2 адаптеры аналогично
  3. safe_call() в адаптерах работает корректно
  4. adapter_registry.py: AdapterError при отсутствии APY
  5. Голый Exception НЕ проникает наружу ни из одного адаптера

Запуск:
    python3 -m unittest tests.test_adapter_errors -v
    python3 tests/test_adapter_errors.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.utils.errors import AdapterError, safe_call, SPAError
from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.adapters.euler_v2 import EulerV2Adapter
from spa_core.adapters.maple import MapleAdapter
from spa_core.adapters.morpho_blue import MorphoBlueAdapter
from spa_core.adapters.yearn_v3 import YearnV3Adapter


# ─── Helper: feed mock that always raises ─────────────────────────────────────

def _failing_feed(exc_class=RuntimeError, msg="DeFiLlama unreachable"):
    """Return a DeFiLlamaFeed mock where get_apy/get_tvl always raise."""
    feed = MagicMock()
    feed.get_apy.side_effect = exc_class(msg)
    feed.get_tvl.side_effect = exc_class(msg)
    return feed


def _ok_feed(apy=5.5, tvl=200_000_000):
    """Return a DeFiLlamaFeed mock that returns apy/tvl successfully."""
    feed = MagicMock()
    feed.get_apy.return_value = apy
    feed.get_tvl.return_value = tvl
    return feed


def _none_feed():
    """Return a DeFiLlamaFeed mock where get_apy/get_tvl return None."""
    feed = MagicMock()
    feed.get_apy.return_value = None
    feed.get_tvl.return_value = None
    return feed


# ─────────────────────────────────────────────────────────────────────────────
# 1. T1: AaveV3Adapter при недоступном DeFiLlama
# ─────────────────────────────────────────────────────────────────────────────

class TestAaveV3AdapterErrors(unittest.TestCase):
    """Tests 01-05: AaveV3 fallback behaviour on DeFiLlama failure."""

    def test_01_aave_fetch_returns_none_apy_on_feed_error(self):
        """AaveV3Adapter.fetch() returns apy=None when DeFiLlama raises."""
        adapter = AaveV3Adapter(feed=_failing_feed())
        result = adapter.fetch()
        self.assertIsNone(result["apy"])

    def test_02_aave_fetch_does_not_raise_on_feed_error(self):
        """AaveV3Adapter.fetch() never raises even when DeFiLlama is down."""
        adapter = AaveV3Adapter(feed=_failing_feed())
        try:
            adapter.fetch()
        except Exception as exc:
            self.fail(f"AaveV3Adapter.fetch() raised: {exc}")

    def test_03_aave_get_apy_returns_none_on_feed_error(self):
        """AaveV3Adapter.get_apy() returns None when DeFiLlama is down."""
        adapter = AaveV3Adapter(feed=_failing_feed())
        result = adapter.get_apy()
        self.assertIsNone(result)

    def test_04_aave_fetch_returns_ok_when_feed_works(self):
        """AaveV3Adapter.fetch() returns correct APY when feed is alive."""
        adapter = AaveV3Adapter(feed=_ok_feed(apy=4.65))
        result = adapter.fetch()
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["apy"], 4.65)

    def test_05_aave_fetch_status_error_when_feed_unavailable(self):
        """AaveV3Adapter.fetch()['status'] == 'error' when DeFiLlama is down."""
        adapter = AaveV3Adapter(feed=_failing_feed())
        result = adapter.fetch()
        self.assertEqual(result["status"], "error")


# ─────────────────────────────────────────────────────────────────────────────
# 2. T2: EulerV2Adapter fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestEulerV2AdapterErrors(unittest.TestCase):
    """Tests 06-09: EulerV2 fallback (safe_call refactored)."""

    def test_06_euler_fetch_returns_none_apy_on_feed_error(self):
        """EulerV2Adapter.fetch() returns apy=None when feed raises."""
        adapter = EulerV2Adapter(feed=_failing_feed())
        result = adapter.fetch()
        self.assertIsNone(result["apy"])

    def test_07_euler_fetch_no_raise_on_feed_error(self):
        """EulerV2Adapter.fetch() never raises."""
        adapter = EulerV2Adapter(feed=_failing_feed())
        try:
            adapter.fetch()
        except Exception as exc:
            self.fail(f"EulerV2Adapter.fetch() raised: {exc}")

    def test_08_euler_get_apy_returns_none_on_feed_error(self):
        """EulerV2Adapter.get_apy() returns None on feed failure."""
        adapter = EulerV2Adapter(feed=_failing_feed())
        self.assertIsNone(adapter.get_apy())

    def test_09_euler_get_apy_returns_value_when_ok(self):
        """EulerV2Adapter.get_apy() returns APY value when feed is alive."""
        adapter = EulerV2Adapter(feed=_ok_feed(apy=6.0))
        self.assertAlmostEqual(adapter.get_apy(), 6.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. T2: Maple, MorphoBlue, YearnV3 fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestT2AdapterErrors(unittest.TestCase):
    """Tests 10-15: Maple/MorphoBlue/YearnV3 graceful fallback."""

    def test_10_maple_no_raise_on_feed_error(self):
        """MapleAdapter.fetch() never raises when DeFiLlama is down."""
        adapter = MapleAdapter(feed=_failing_feed())
        try:
            adapter.fetch()
        except Exception as exc:
            self.fail(f"MapleAdapter.fetch() raised: {exc}")

    def test_11_maple_get_apy_returns_none_on_feed_error(self):
        """MapleAdapter.get_apy() returns None when feed is down."""
        adapter = MapleAdapter(feed=_failing_feed())
        self.assertIsNone(adapter.get_apy())

    def test_12_morpho_blue_no_raise_on_feed_error(self):
        """MorphoBlueAdapter.fetch() never raises when DeFiLlama is down."""
        adapter = MorphoBlueAdapter(feed=_failing_feed())
        try:
            adapter.fetch()
        except Exception as exc:
            self.fail(f"MorphoBlueAdapter.fetch() raised: {exc}")

    def test_13_morpho_blue_get_apy_returns_none_on_feed_error(self):
        """MorphoBlueAdapter.get_apy() returns None when feed is down."""
        adapter = MorphoBlueAdapter(feed=_failing_feed())
        self.assertIsNone(adapter.get_apy())

    def test_14_yearn_v3_no_raise_on_feed_error(self):
        """YearnV3Adapter.fetch() never raises when DeFiLlama is down."""
        adapter = YearnV3Adapter(feed=_failing_feed())
        try:
            adapter.fetch()
        except Exception as exc:
            self.fail(f"YearnV3Adapter.fetch() raised: {exc}")

    def test_15_yearn_v3_get_apy_returns_none_on_feed_error(self):
        """YearnV3Adapter.get_apy() returns None when feed is down."""
        adapter = YearnV3Adapter(feed=_failing_feed())
        self.assertIsNone(adapter.get_apy())


# ─────────────────────────────────────────────────────────────────────────────
# 4. None-feed (DeFiLlama returns None — pool not found)
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterNonePoolNotFound(unittest.TestCase):
    """Tests 16-18: None APY (pool not found) → no raise, apy=None."""

    def test_16_aave_none_apy_when_pool_not_found(self):
        """AaveV3Adapter.get_apy() returns None when DeFiLlama returns None."""
        adapter = AaveV3Adapter(feed=_none_feed())
        self.assertIsNone(adapter.get_apy())

    def test_17_euler_none_apy_when_pool_not_found(self):
        """EulerV2Adapter.get_apy() returns None when DeFiLlama returns None."""
        adapter = EulerV2Adapter(feed=_none_feed())
        self.assertIsNone(adapter.get_apy())

    def test_18_maple_none_apy_when_pool_not_found(self):
        """MapleAdapter.get_apy() returns None when DeFiLlama returns None."""
        adapter = MapleAdapter(feed=_none_feed())
        self.assertIsNone(adapter.get_apy())


# ─────────────────────────────────────────────────────────────────────────────
# 5. safe_call() в контексте адаптеров
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeCallAdapterContext(unittest.TestCase):
    """Tests 19-22: safe_call() used in adapter fetch context."""

    def test_19_safe_call_returns_default_on_source_error(self):
        """safe_call() with SourceError → returns default FALLBACK_APY."""
        from spa_core.utils.errors import SourceError

        def failing_fetch():
            raise SourceError("defillama", "unreachable")

        result = safe_call(failing_fetch, default=5.0)
        self.assertEqual(result, 5.0)

    def test_20_safe_call_returns_result_when_feed_works(self):
        """safe_call() returns feed result when no exception."""
        def ok_fetch():
            return 4.65

        result = safe_call(ok_fetch, default=0.0)
        self.assertAlmostEqual(result, 4.65)

    def test_21_safe_call_adapter_error_returns_default(self):
        """safe_call() with AdapterError → default (no propagation)."""
        def failing_adapter():
            raise AdapterError("test_protocol", "no APY available")

        result = safe_call(failing_adapter, default=None)
        self.assertIsNone(result)

    def test_22_safe_call_bare_exception_returns_default(self):
        """safe_call() with bare RuntimeError → default (no propagation)."""
        def bad_network():
            raise RuntimeError("connection refused")

        result = safe_call(bad_network, default={"apy": None, "status": "error"})
        self.assertEqual(result["status"], "error")


# ─────────────────────────────────────────────────────────────────────────────
# 6. adapter_registry.py: AdapterError при отсутствии APY
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterRegistryErrors(unittest.TestCase):
    """Tests 23-25: adapter_registry.py raises AdapterError (not bare ValueError)."""

    def test_23_refresh_all_records_adapter_error_as_error_dict(self):
        """refresh_all() records AdapterError as error dict, does not propagate."""
        from spa_core.adapters.adapter_registry import refresh_all, REGISTRY

        # Build a registry with one stub adapter that returns None APY
        stub_cls = type("StubNoAPY", (), {
            "__init__": lambda s: None,
            "get_apy": lambda s: None,
        })
        test_protocol = "_test_no_apy_xyz"
        REGISTRY[test_protocol] = stub_cls
        try:
            results = refresh_all(adapter_status_path="/tmp/_test_adapter_status.json")
            # Should not propagate AdapterError — it should be in results as error
            self.assertIn(test_protocol, results)
            self.assertIn("error", results[test_protocol])
        finally:
            REGISTRY.pop(test_protocol, None)

    def test_24_adapter_error_is_spa_error(self):
        """AdapterError is subclass of SPAError (not bare Exception)."""
        err = AdapterError("aave_v3", "no APY")
        self.assertIsInstance(err, SPAError)
        self.assertIsInstance(err, Exception)

    def test_25_adapter_error_details_adapter_id(self):
        """AdapterError.details contains adapter_id and reason."""
        err = AdapterError("compound_v3", "TVL below floor")
        self.assertEqual(err.details["adapter_id"], "compound_v3")
        self.assertEqual(err.details["reason"], "TVL below floor")
        self.assertEqual(err.code, "ADAPTER_ERROR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
