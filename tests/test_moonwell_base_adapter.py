"""Tests for Moonwell Finance Base USDC Adapter (MP-463).

Запуск: python3 tests/test_moonwell_base_adapter.py -v
Не требует pytest — stdlib unittest.
Выходит с кодом 0 при успехе, 1 при ошибках.
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

# Добавляем корень репо в sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.moonwell_base_adapter import (
    ADAPTER_ID,
    ADAPTER_NAME,
    ADAPTER_STATUS,
    APY_FALLBACK,
    BAD_DEBT_USD,
    CHAIN,
    DEFILLAMA_CHAIN,
    DEFILLAMA_PROJECT,
    HACK_DATE,
    HACK_IMPACT_USD,
    MoonwellBaseAdapter,
    RISK_SCORE,
    TIER,
    TVL_USD,
    get_apy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_defillama_response(pools: list) -> bytes:
    payload = {"status": "success", "data": pools}
    return json.dumps(payload).encode("utf-8")


def _make_pool(
    project: str = "moonwell-finance",
    symbol: str = "USDC",
    chain: str = "Base",
    apy: float = 5.5,
    tvl: float = 500_000_000.0,
    pool_id: str = "moonwell-base-usdc-pool",
) -> dict:
    return {
        "pool": pool_id,
        "project": project,
        "symbol": symbol,
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
    }


def _patch_urlopen(pools: list):
    raw = _make_defillama_response(pools)

    class FakeResponse:
        def __init__(self):
            self._data = raw

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return patch(
        "spa_core.adapters.moonwell_base_adapter.urllib.request.urlopen",
        return_value=FakeResponse(),
    )


def _patch_urlopen_error(exc: Exception):
    return patch(
        "spa_core.adapters.moonwell_base_adapter.urllib.request.urlopen",
        side_effect=exc,
    )


# ---------------------------------------------------------------------------
# Group 1: Constants and identity
# ---------------------------------------------------------------------------

class TestMoonwellBaseConstants(unittest.TestCase):

    def test_adapter_id(self):
        self.assertEqual(ADAPTER_ID, "moonwell-base")

    def test_tier_is_T2(self):
        self.assertEqual(TIER, "T2")

    def test_chain_is_base(self):
        self.assertEqual(CHAIN, "base")

    def test_risk_score_range(self):
        self.assertGreater(RISK_SCORE, 0.0)
        self.assertLess(RISK_SCORE, 1.0)

    def test_risk_score_value(self):
        # Повышен с 0.36 до 0.75 из-за хака Nov 2025 (ADR-026)
        self.assertAlmostEqual(RISK_SCORE, 0.75, places=5)

    def test_tvl_usd_large(self):
        self.assertGreater(TVL_USD, 100_000_000)

    def test_tvl_usd_500m(self):
        self.assertEqual(TVL_USD, 500_000_000)

    def test_fallback_apy_reasonable(self):
        self.assertGreater(APY_FALLBACK, 3.0)
        self.assertLess(APY_FALLBACK, 15.0)

    def test_fallback_apy_value(self):
        self.assertAlmostEqual(APY_FALLBACK, 5.5, places=5)

    def test_defillama_project(self):
        self.assertEqual(DEFILLAMA_PROJECT, "moonwell-finance")

    def test_defillama_chain(self):
        self.assertEqual(DEFILLAMA_CHAIN, "Base")

    def test_adapter_id_attr(self):
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.ADAPTER_ID, "moonwell-base")

    def test_tier_attr(self):
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.TIER, "T2")
        self.assertEqual(adapter.tier, "T2")

    def test_chain_attr(self):
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.CHAIN, "base")

    def test_risk_score_attr(self):
        adapter = MoonwellBaseAdapter()
        self.assertAlmostEqual(adapter.RISK_SCORE, 0.75, places=5)

    def test_tvl_usd_attr(self):
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.TVL_USD, 500_000_000)

    def test_exit_latency_instant(self):
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.EXIT_LATENCY_HOURS, 0.0)


# ---------------------------------------------------------------------------
# Group 2: get_apy()
# ---------------------------------------------------------------------------

class TestMoonwellBaseGetApy(unittest.TestCase):

    def setUp(self):
        self.adapter = MoonwellBaseAdapter()

    def test_get_apy_returns_float(self):
        with _patch_urlopen([_make_pool(apy=6.0)]):
            result = self.adapter.get_apy()
        self.assertIsInstance(result, float)

    def test_get_apy_positive(self):
        with _patch_urlopen([_make_pool(apy=6.0)]):
            result = self.adapter.get_apy()
        self.assertGreater(result, 0)

    def test_get_apy_reasonable_range(self):
        with _patch_urlopen([_make_pool(apy=6.0)]):
            result = self.adapter.get_apy()
        self.assertGreater(result, 1.0)
        self.assertLess(result, 30.0)

    def test_get_apy_live_value(self):
        with _patch_urlopen([_make_pool(apy=7.1)]):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, 7.1, places=5)

    def test_fallback_on_url_error(self):
        with _patch_urlopen_error(urllib.error.URLError("timeout")):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)
        self.assertAlmostEqual(result, 5.5, places=5)

    def test_fallback_on_generic_exception(self):
        with _patch_urlopen_error(RuntimeError("unexpected")):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)

    def test_module_get_apy_returns_float(self):
        """Standalone функция get_apy() из модуля."""
        result = get_apy()
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# Group 3: get_status() / get_apy_with_metadata()
# ---------------------------------------------------------------------------

class TestMoonwellBaseStatus(unittest.TestCase):

    def setUp(self):
        self.adapter = MoonwellBaseAdapter()

    def test_get_status_returns_dict(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertIsInstance(status, dict)

    def test_get_status_has_adapter_id(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertEqual(status["adapter_id"], "moonwell-base")

    def test_get_status_has_chain(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertEqual(status["chain"], "base")

    def test_get_status_has_tier(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertEqual(status["tier"], "T2")

    def test_get_status_has_apy(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertIn("apy_pct", status)
        self.assertIsInstance(status["apy_pct"], float)

    def test_get_status_has_risk_score(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertIn("risk_score", status)
        self.assertAlmostEqual(status["risk_score"], 0.75, places=5)

    def test_get_status_has_tvl(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertIn("tvl_usd", status)
        self.assertEqual(status["tvl_usd"], 500_000_000.0)

    def test_get_status_phase(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertEqual(status["phase"], "phase1_monitoring")

    def test_get_status_adr(self):
        with _patch_urlopen([_make_pool()]):
            status = self.adapter.get_status()
        self.assertEqual(status["adr"], "ADR-025")

    def test_get_apy_with_metadata(self):
        with _patch_urlopen([_make_pool()]):
            meta = self.adapter.get_apy_with_metadata()
        self.assertIsInstance(meta, dict)
        self.assertIn("apy_pct", meta)
        self.assertEqual(meta["adapter_id"], "moonwell-base")


# ---------------------------------------------------------------------------
# Group 4: get_yield_info() — BaseAdapter interface
# ---------------------------------------------------------------------------

class TestMoonwellBaseYieldInfo(unittest.TestCase):

    def setUp(self):
        self.adapter = MoonwellBaseAdapter()

    def test_yield_info_tier_is_t2(self):
        with _patch_urlopen([_make_pool()]):
            yi = self.adapter.get_yield_info()
        self.assertEqual(yi.tier, "T2")

    def test_yield_info_apy_is_decimal(self):
        """get_yield_info().apy должен быть в decimal (0.0–1.0)."""
        with _patch_urlopen([_make_pool(apy=5.5)]):
            yi = self.adapter.get_yield_info()
        self.assertAlmostEqual(yi.apy, 0.055, places=4)
        self.assertLess(yi.apy, 1.0)

    def test_yield_info_tvl_usd(self):
        with _patch_urlopen([_make_pool()]):
            yi = self.adapter.get_yield_info()
        self.assertAlmostEqual(yi.tvl_usd, 500_000_000.0, places=0)

    def test_yield_info_risk_score(self):
        with _patch_urlopen([_make_pool()]):
            yi = self.adapter.get_yield_info()
        self.assertAlmostEqual(yi.risk_score, 0.75, places=5)


# ---------------------------------------------------------------------------
# Group 5: validate() / health_check()
# ---------------------------------------------------------------------------

class TestMoonwellBaseValidate(unittest.TestCase):

    def setUp(self):
        self.adapter = MoonwellBaseAdapter()

    def test_validate_returns_tuple(self):
        """validate() всегда возвращает tuple (bool, str)."""
        with _patch_urlopen([_make_pool(apy=5.5, tvl=500_000_000.0)]):
            result = self.adapter.validate()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_validate_false_when_suspended(self):
        """Адаптер suspended → validate() возвращает (False, ...)."""
        with _patch_urlopen([_make_pool(apy=5.5, tvl=500_000_000.0)]):
            result = self.adapter.validate()
        # ADAPTER_STATUS == "suspended" — allocation blocked regardless of data
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])
        self.assertIn("suspended", result[1].lower())

    def test_validate_false_with_fallback_when_suspended(self):
        """Даже при fallback APY suspended адаптер возвращает (False, ...)."""
        with _patch_urlopen_error(urllib.error.URLError("network error")):
            result = self.adapter.validate()
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])

    def test_health_check_ok(self):
        hc = self.adapter.health_check()
        self.assertEqual(hc["status"], "ok")
        self.assertTrue(hc["tvl_floor_ok"])
        self.assertEqual(hc["chain"], "base")
        self.assertEqual(hc["tier"], "T2")


# ---------------------------------------------------------------------------
# Group 6: Security incident (ADR-026)
# ---------------------------------------------------------------------------

class TestMoonwellBaseSecurityIncident(unittest.TestCase):
    """Тесты для проверки корректности данных об инциденте безопасности (ADR-026)."""

    def test_hack_date_constant(self):
        """HACK_DATE = '2025-11' (ноябрь 2025)."""
        self.assertEqual(HACK_DATE, "2025-11")

    def test_adapter_status_suspended(self):
        """ADAPTER_STATUS = 'suspended' после хака."""
        self.assertEqual(ADAPTER_STATUS, "suspended")

    def test_hack_impact_usd(self):
        """HACK_IMPACT_USD = 1_000_000 (~$1M похищено)."""
        self.assertEqual(HACK_IMPACT_USD, 1_000_000)

    def test_bad_debt_usd(self):
        """BAD_DEBT_USD = 3_700_000 ($3.7M bad debt)."""
        self.assertEqual(BAD_DEBT_USD, 3_700_000)

    def test_risk_score_elevated(self):
        """RISK_SCORE >= 0.7 (повышен из-за хака)."""
        self.assertGreaterEqual(RISK_SCORE, 0.7)

    def test_validate_returns_false_when_suspended(self):
        """validate() возвращает (False, ...) когда ADAPTER_STATUS='suspended'."""
        adapter = MoonwellBaseAdapter()
        result = adapter.validate()
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])

    def test_validate_suspended_message_contains_hack_date(self):
        """Сообщение validate() содержит HACK_DATE."""
        adapter = MoonwellBaseAdapter()
        result = adapter.validate()
        self.assertIn(HACK_DATE, result[1])

    def test_get_status_adapter_status_suspended(self):
        """get_status() содержит 'adapter_status': 'suspended'."""
        adapter = MoonwellBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            status = adapter.get_status()
        self.assertIn("adapter_status", status)
        self.assertEqual(status["adapter_status"], "suspended")

    def test_get_status_hack_date(self):
        """get_status() содержит 'hack_date': '2025-11'."""
        adapter = MoonwellBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            status = adapter.get_status()
        self.assertIn("hack_date", status)
        self.assertEqual(status["hack_date"], "2025-11")

    def test_get_status_bad_debt_usd(self):
        """get_status() содержит 'bad_debt_usd': 3_700_000."""
        adapter = MoonwellBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            status = adapter.get_status()
        self.assertIn("bad_debt_usd", status)
        self.assertEqual(status["bad_debt_usd"], 3_700_000)

    def test_get_status_security_note_present(self):
        """get_status() содержит поле security_note."""
        adapter = MoonwellBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            status = adapter.get_status()
        self.assertIn("security_note", status)
        self.assertIn("SUSPENDED", status["security_note"])

    def test_adapter_instance_status_suspended(self):
        """Экземпляр MoonwellBaseAdapter.ADAPTER_STATUS == 'suspended'."""
        adapter = MoonwellBaseAdapter()
        self.assertEqual(adapter.ADAPTER_STATUS, "suspended")


# ---------------------------------------------------------------------------
# Group 7: Registry integration
# ---------------------------------------------------------------------------

class TestMoonwellBaseRegistry(unittest.TestCase):  # noqa: D101 — Group 7

    def test_base_chain_adapters_includes_moonwell(self):
        from spa_core.adapters import BASE_CHAIN_ADAPTERS
        self.assertIn("moonwell-base", BASE_CHAIN_ADAPTERS)

    def test_adapter_registry_includes_moonwell(self):
        """ADAPTER_REGISTRY — список кортежей; проверяем ключ 'moonwell_base'."""
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [r[0] for r in ADAPTER_REGISTRY]
        self.assertIn("moonwell_base", keys)

    def test_adapter_registry_tier_is_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "moonwell_base":
                self.assertEqual(tier, "T2")
                break
        else:
            self.fail("moonwell_base not found in ADAPTER_REGISTRY")

    def test_base_chain_adapter_instance(self):
        from spa_core.adapters import BASE_CHAIN_ADAPTERS
        inst = BASE_CHAIN_ADAPTERS["moonwell-base"]
        self.assertIsInstance(inst, MoonwellBaseAdapter)

    def test_adapter_count_at_least_13(self):
        """ADAPTER_REGISTRY должен содержать минимум 13 адаптеров (12 ранее + moonwell)."""
        from spa_core.adapters import ADAPTER_REGISTRY
        self.assertGreaterEqual(len(ADAPTER_REGISTRY), 13)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestMoonwellBaseConstants,
        TestMoonwellBaseGetApy,
        TestMoonwellBaseStatus,
        TestMoonwellBaseYieldInfo,
        TestMoonwellBaseValidate,
        TestMoonwellBaseSecurityIncident,
        TestMoonwellBaseRegistry,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
