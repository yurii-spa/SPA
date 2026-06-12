"""Tests for Extra Finance XLend Base USDC Adapter (MP-510).

35+ тестов, 6 групп:
  1. Constants (5)
  2. get_apy (8)
  3. get_status (6)
  4. validate (5)
  5. health_check (5)
  6. get_yield_info (6)
  + Bonus: Registry integration (5)

Запуск: python3 tests/test_extra_finance_base_adapter.py -v
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

from spa_core.adapters.extra_finance_base_adapter import (
    ADAPTER_ID,
    ADAPTER_NAME,
    APY_FALLBACK,
    CHAIN,
    DEFILLAMA_CHAIN,
    DEFILLAMA_PROJECT,
    ExtraFinanceBaseAdapter,
    PROTOCOL_NAME,
    RISK_SCORE,
    T3_CAP_PCT,
    TIER,
    TVL_USD,
    TVL_USDC_LENDING,
    get_apy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_defillama_response(pools: list) -> bytes:
    payload = {"status": "success", "data": pools}
    return json.dumps(payload).encode("utf-8")


def _make_pool(
    project: str = "extra-finance",
    symbol: str = "USDC",
    chain: str = "Base",
    apy: float = 9.0,
    tvl: float = 15_000_000.0,
    pool_id: str = "extra-finance-xlend-usdc-base",
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
        "spa_core.adapters.extra_finance_base_adapter.urllib.request.urlopen",
        return_value=FakeResponse(),
    )


def _patch_urlopen_error(exc: Exception):
    return patch(
        "spa_core.adapters.extra_finance_base_adapter.urllib.request.urlopen",
        side_effect=exc,
    )


# ---------------------------------------------------------------------------
# Group 1: Constants (5 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseConstants(unittest.TestCase):
    """Группа 1: Константы протокола."""

    def test_adapter_id(self):
        """ADAPTER_ID должен быть 'extra_finance_base'."""
        self.assertEqual(ADAPTER_ID, "extra_finance_base")

    def test_tier_is_T3(self):
        """Tier должен быть T3 (growtech, молодой протокол)."""
        self.assertEqual(TIER, "T3")

    def test_chain_is_base(self):
        """Chain должен быть 'base'."""
        self.assertEqual(CHAIN, "base")

    def test_apy_fallback_value(self):
        """APY fallback = 8.0% (середина диапазона 7-12%)."""
        self.assertAlmostEqual(APY_FALLBACK, 8.0, places=5)

    def test_risk_score_value(self):
        """Risk score = 0.55 (T3, 3 аудита, Immunefi, молодой протокол)."""
        self.assertAlmostEqual(RISK_SCORE, 0.55, places=5)

    # --- дополнительные константы ---

    def test_tvl_usd_total(self):
        """Total TVL ~$135M."""
        self.assertEqual(TVL_USD, 135_000_000)

    def test_tvl_usdc_lending(self):
        """USDC lending pool TVL = $15M (>$5M RiskPolicy floor)."""
        self.assertEqual(TVL_USDC_LENDING, 15_000_000)

    def test_tvl_usdc_lending_above_floor(self):
        """TVL_USDC_LENDING должен быть >= 5M (RiskPolicy floor)."""
        self.assertGreaterEqual(TVL_USDC_LENDING, 5_000_000)

    def test_t3_cap_pct(self):
        """T3 cap = 5% портфеля (ADR-026)."""
        self.assertEqual(T3_CAP_PCT, 5)

    def test_defillama_project(self):
        """DeFiLlama project slug = 'extra-finance'."""
        self.assertEqual(DEFILLAMA_PROJECT, "extra-finance")

    def test_defillama_chain(self):
        """DeFiLlama chain = 'Base'."""
        self.assertEqual(DEFILLAMA_CHAIN, "Base")

    def test_protocol_name(self):
        """Protocol name = 'Extra Finance XLend'."""
        self.assertEqual(PROTOCOL_NAME, "Extra Finance XLend")

    def test_adapter_id_attr(self):
        """Атрибут класса ADAPTER_ID."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertEqual(adapter.ADAPTER_ID, "extra_finance_base")

    def test_tier_attr(self):
        """Атрибуты tier на уровне класса и экземпляра."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertEqual(adapter.TIER, "T3")
        self.assertEqual(adapter.tier, "T3")

    def test_chain_attr(self):
        """Атрибут chain на уровне класса."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertEqual(adapter.CHAIN, "base")

    def test_risk_score_attr(self):
        """RISK_SCORE атрибут класса."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertAlmostEqual(adapter.RISK_SCORE, 0.55, places=5)

    def test_exit_latency_instant(self):
        """EXIT_LATENCY_HOURS = 0.0 (same-block lending)."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertEqual(adapter.EXIT_LATENCY_HOURS, 0.0)

    def test_audits_list(self):
        """Три аудита: BlockSec, PeckShield, Sherlock."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertIn("BlockSec", adapter.AUDITS)
        self.assertIn("PeckShield", adapter.AUDITS)
        self.assertIn("Sherlock", adapter.AUDITS)

    def test_bug_bounty(self):
        """Bug bounty = Immunefi."""
        adapter = ExtraFinanceBaseAdapter()
        self.assertEqual(adapter.BUG_BOUNTY, "Immunefi")


# ---------------------------------------------------------------------------
# Group 2: get_apy (8 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseGetApy(unittest.TestCase):
    """Группа 2: get_apy() — live feed и fallback."""

    def setUp(self):
        self.adapter = ExtraFinanceBaseAdapter()

    def test_get_apy_returns_float(self):
        """get_apy() должен возвращать float."""
        with _patch_urlopen([_make_pool(apy=9.0)]):
            result = self.adapter.get_apy()
        self.assertIsInstance(result, float)

    def test_get_apy_in_range(self):
        """get_apy() должен быть в диапазоне [0.01, 100]."""
        with _patch_urlopen([_make_pool(apy=9.0)]):
            result = self.adapter.get_apy()
        self.assertGreaterEqual(result, 0.01)
        self.assertLessEqual(result, 100.0)

    def test_get_apy_live_value(self):
        """Live APY из DeFiLlama возвращается корректно."""
        with _patch_urlopen([_make_pool(apy=10.5)]):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, 10.5, places=5)

    def test_get_apy_live_low_boundary(self):
        """Граничное значение: APY=7%."""
        with _patch_urlopen([_make_pool(apy=7.0)]):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, 7.0, places=5)

    def test_fallback_on_url_error(self):
        """URLError → fallback APY_FALLBACK (8.0%)."""
        with _patch_urlopen_error(urllib.error.URLError("timeout")):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)
        self.assertAlmostEqual(result, 8.0, places=5)

    def test_fallback_on_timeout(self):
        """TimeoutError → fallback APY_FALLBACK."""
        with _patch_urlopen_error(TimeoutError("connection timed out")):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)

    def test_fallback_on_generic_exception(self):
        """Любое исключение → fallback APY_FALLBACK."""
        with _patch_urlopen_error(RuntimeError("unexpected network error")):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)

    def test_fallback_on_wrong_chain(self):
        """Пул на Ethereum (не Base) → не выбирается → fallback."""
        with _patch_urlopen([_make_pool(chain="Ethereum", apy=9.0)]):
            result = self.adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)

    def test_module_get_apy_returns_float(self):
        """Standalone get_apy() из модуля возвращает float."""
        result = get_apy()
        self.assertIsInstance(result, float)

    def test_module_get_apy_fallback_param(self):
        """Standalone get_apy(fallback=5.0) — кастомный fallback."""
        with _patch_urlopen_error(urllib.error.URLError("no network")):
            result = get_apy(fallback=5.0)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# Group 3: get_status (6 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseGetStatus(unittest.TestCase):
    """Группа 3: get_status() — структура и значения."""

    def setUp(self):
        self.adapter = ExtraFinanceBaseAdapter()

    def _status(self) -> dict:
        with _patch_urlopen([_make_pool()]):
            return self.adapter.get_status()

    def test_get_status_returns_dict(self):
        """get_status() возвращает dict."""
        self.assertIsInstance(self._status(), dict)

    def test_get_status_tier_is_T3(self):
        """status['tier'] == 'T3'."""
        self.assertEqual(self._status()["tier"], "T3")

    def test_get_status_chain_is_base(self):
        """status['chain'] == 'base'."""
        self.assertEqual(self._status()["chain"], "base")

    def test_get_status_risk_score(self):
        """status['risk_score'] == 0.55."""
        self.assertAlmostEqual(self._status()["risk_score"], 0.55, places=5)

    def test_get_status_keys_present(self):
        """Все обязательные ключи присутствуют."""
        status = self._status()
        required = {
            "adapter_id", "tier", "chain", "risk_score",
            "apy_pct", "tvl_usd", "tvl_usdc_lending", "phase", "adr",
        }
        for key in required:
            self.assertIn(key, status, f"Ключ '{key}' отсутствует в get_status()")

    def test_get_status_adr_026(self):
        """status['adr'] == 'ADR-026' (Base chain expansion)."""
        self.assertEqual(self._status()["adr"], "ADR-026")

    def test_get_status_phase1(self):
        """status['phase'] == 'phase1_monitoring'."""
        self.assertEqual(self._status()["phase"], "phase1_monitoring")

    def test_get_status_adapter_id(self):
        """status['adapter_id'] == 'extra_finance_base'."""
        self.assertEqual(self._status()["adapter_id"], "extra_finance_base")

    def test_get_apy_with_metadata_alias(self):
        """get_apy_with_metadata() — псевдоним get_status()."""
        with _patch_urlopen([_make_pool()]):
            meta = self.adapter.get_apy_with_metadata()
        self.assertIsInstance(meta, dict)
        self.assertIn("apy_pct", meta)
        self.assertEqual(meta["adapter_id"], "extra_finance_base")


# ---------------------------------------------------------------------------
# Group 4: validate (5 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseValidate(unittest.TestCase):
    """Группа 4: validate() — RiskPolicy TVL floor."""

    def setUp(self):
        self.adapter = ExtraFinanceBaseAdapter()

    def test_validate_returns_tuple(self):
        """validate() возвращает Tuple[bool, str]."""
        result = self.adapter.validate()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_validate_true_with_sufficient_tvl(self):
        """valid=True когда TVL_USDC_LENDING >= 5M (default: 15M)."""
        ok, msg = self.adapter.validate()
        self.assertTrue(ok)
        self.assertEqual(msg, "ok")

    def test_validate_false_with_low_tvl(self):
        """valid=False когда TVL_USDC_LENDING < 5M."""
        self.adapter.TVL_USDC_LENDING = 4_000_000
        ok, msg = self.adapter.validate()
        self.assertFalse(ok)
        self.assertIn("5_000_000", msg)
        # Восстанавливаем
        self.adapter.TVL_USDC_LENDING = TVL_USDC_LENDING

    def test_validate_true_at_exact_floor(self):
        """valid=True при TVL_USDC_LENDING ровно 5M (граничный случай)."""
        self.adapter.TVL_USDC_LENDING = 5_000_000
        ok, _ = self.adapter.validate()
        self.assertTrue(ok)
        self.adapter.TVL_USDC_LENDING = TVL_USDC_LENDING

    def test_validate_false_with_zero_tvl(self):
        """valid=False при TVL_USDC_LENDING = 0."""
        self.adapter.TVL_USDC_LENDING = 0
        ok, msg = self.adapter.validate()
        self.assertFalse(ok)
        self.assertIsInstance(msg, str)
        self.adapter.TVL_USDC_LENDING = TVL_USDC_LENDING


# ---------------------------------------------------------------------------
# Group 5: health_check (5 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseHealthCheck(unittest.TestCase):
    """Группа 5: health_check() — без сетевых вызовов."""

    def setUp(self):
        self.adapter = ExtraFinanceBaseAdapter()

    def test_health_check_returns_bool(self):
        """health_check() возвращает bool."""
        result = self.adapter.health_check()
        self.assertIsInstance(result, bool)

    def test_health_check_true_by_default(self):
        """health_check() == True при дефолтных параметрах."""
        self.assertTrue(self.adapter.health_check())

    def test_health_check_no_network_required(self):
        """health_check() не требует сети — работает офлайн."""
        with _patch_urlopen_error(urllib.error.URLError("no network")):
            # health_check не делает сетевых вызовов
            result = self.adapter.health_check()
        self.assertIsInstance(result, bool)

    def test_health_check_false_with_zero_fallback(self):
        """health_check() == False при APY_FALLBACK = 0."""
        self.adapter.APY_FALLBACK = 0.0
        result = self.adapter.health_check()
        self.assertFalse(result)
        self.adapter.APY_FALLBACK = APY_FALLBACK

    def test_health_check_false_with_low_tvl(self):
        """health_check() == False при TVL_USDC_LENDING < 5M."""
        self.adapter.TVL_USDC_LENDING = 1_000_000
        result = self.adapter.health_check()
        self.assertFalse(result)
        self.adapter.TVL_USDC_LENDING = TVL_USDC_LENDING


# ---------------------------------------------------------------------------
# Group 6: get_yield_info (6 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseYieldInfo(unittest.TestCase):
    """Группа 6: get_yield_info() — структура и значения."""

    def setUp(self):
        self.adapter = ExtraFinanceBaseAdapter()

    def _yield_info(self) -> dict:
        with _patch_urlopen([_make_pool(apy=9.0)]):
            return self.adapter.get_yield_info()

    def test_get_yield_info_returns_dict(self):
        """get_yield_info() возвращает dict."""
        self.assertIsInstance(self._yield_info(), dict)

    def test_get_yield_info_apy_pct(self):
        """apy_pct присутствует и является float."""
        yi = self._yield_info()
        self.assertIn("apy_pct", yi)
        self.assertIsInstance(yi["apy_pct"], float)

    def test_get_yield_info_apy_pct_value(self):
        """apy_pct == 9.0% (из live feed)."""
        yi = self._yield_info()
        self.assertAlmostEqual(yi["apy_pct"], 9.0, places=5)

    def test_get_yield_info_tvl_usd(self):
        """tvl_usd == 135_000_000."""
        yi = self._yield_info()
        self.assertIn("tvl_usd", yi)
        self.assertAlmostEqual(yi["tvl_usd"], 135_000_000.0, places=0)

    def test_get_yield_info_protocol_name(self):
        """protocol_name == 'Extra Finance XLend'."""
        yi = self._yield_info()
        self.assertIn("protocol_name", yi)
        self.assertEqual(yi["protocol_name"], "Extra Finance XLend")

    def test_get_yield_info_keys_present(self):
        """Все обязательные ключи присутствуют."""
        yi = self._yield_info()
        required = {
            "adapter_id", "protocol_name", "apy_pct", "tvl_usd",
            "tvl_usdc_lending", "tier", "risk_score", "chain",
        }
        for key in required:
            self.assertIn(key, yi, f"Ключ '{key}' отсутствует в get_yield_info()")

    def test_get_yield_info_fallback(self):
        """При сетевой ошибке get_yield_info() использует fallback APY."""
        with _patch_urlopen_error(urllib.error.URLError("timeout")):
            yi = self.adapter.get_yield_info()
        self.assertAlmostEqual(yi["apy_pct"], APY_FALLBACK, places=5)

    def test_get_yield_info_audits(self):
        """audits содержит 3 аудита."""
        yi = self._yield_info()
        self.assertIn("audits", yi)
        self.assertEqual(len(yi["audits"]), 3)

    def test_get_yield_info_tvl_usdc_lending(self):
        """tvl_usdc_lending == 15_000_000."""
        yi = self._yield_info()
        self.assertIn("tvl_usdc_lending", yi)
        self.assertAlmostEqual(yi["tvl_usdc_lending"], 15_000_000.0, places=0)


# ---------------------------------------------------------------------------
# Group 7: Registry integration (5 тестов)
# ---------------------------------------------------------------------------

class TestExtraFinanceBaseRegistry(unittest.TestCase):
    """Группа 7: интеграция с ADAPTER_REGISTRY и BASE_CHAIN_ADAPTERS."""

    def test_base_chain_adapters_includes_extra_finance(self):
        """BASE_CHAIN_ADAPTERS должен содержать 'extra-finance-base'."""
        from spa_core.adapters import BASE_CHAIN_ADAPTERS
        self.assertIn("extra-finance-base", BASE_CHAIN_ADAPTERS)

    def test_adapter_registry_includes_extra_finance(self):
        """ADAPTER_REGISTRY должен содержать 'extra_finance_base'."""
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [r[0] for r in ADAPTER_REGISTRY]
        self.assertIn("extra_finance_base", keys)

    def test_adapter_registry_tier_is_T3(self):
        """extra_finance_base в реестре должен иметь tier='T3'."""
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "extra_finance_base":
                self.assertEqual(tier, "T3")
                return
        self.fail("extra_finance_base not found in ADAPTER_REGISTRY")

    def test_base_chain_adapter_instance_type(self):
        """BASE_CHAIN_ADAPTERS['extra-finance-base'] — экземпляр ExtraFinanceBaseAdapter."""
        from spa_core.adapters import BASE_CHAIN_ADAPTERS
        inst = BASE_CHAIN_ADAPTERS["extra-finance-base"]
        self.assertIsInstance(inst, ExtraFinanceBaseAdapter)

    def test_adapter_registry_count_16(self):
        """ADAPTER_REGISTRY должен содержать ровно 16 адаптеров (MP-510)."""
        from spa_core.adapters import ADAPTER_REGISTRY
        self.assertEqual(len(ADAPTER_REGISTRY), 16)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestExtraFinanceBaseConstants,
        TestExtraFinanceBaseGetApy,
        TestExtraFinanceBaseGetStatus,
        TestExtraFinanceBaseValidate,
        TestExtraFinanceBaseHealthCheck,
        TestExtraFinanceBaseYieldInfo,
        TestExtraFinanceBaseRegistry,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
