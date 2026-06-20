#!/usr/bin/env python3
"""
Standalone тесты для AaveV3BaseAdapter (MP-448).

Запуск: python3 tests/test_aave_v3_base_adapter.py
Не требует pytest — использует только stdlib unittest.
Выходит с кодом 0 при успехе, 1 при ошибках.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

# Добавляем корень репо в sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.aave_v3_base_adapter import (
    APY_FALLBACK,
    CHAIN,
    GAS_ADVANTAGE_USD,
    GAS_BASE_USD,
    PROTOCOL_ID,
    RISK_SCORE,
    T2_CAP_PCT,
    TIER,
    TVL_USD,
    AaveV3BaseAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_defillama_response(pools: list[dict]) -> bytes:
    """Создаёт JSON-ответ DeFiLlama для мока."""
    payload = {"status": "success", "data": pools}
    return json.dumps(payload).encode("utf-8")


def _make_pool(
    project: str = "aave-v3",
    symbol: str = "USDC",
    chain: str = "Base",
    apy: float = 5.2,
    tvl: float = 400_000_000.0,
    pool_id: str = "test-pool-uuid",
) -> dict:
    return {
        "pool": pool_id,
        "project": project,
        "symbol": symbol,
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
    }


def _patch_urlopen(pools: list[dict]):
    """Контекст-менеджер: мокает urlopen, возвращая указанные пулы."""
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
        "spa_core.adapters.aave_v3_base_adapter.urllib.request.urlopen",
        return_value=FakeResponse(),
    )


def _patch_urlopen_error(exc: Exception):
    """Мокает urlopen, бросающий указанное исключение."""
    return patch(
        "spa_core.adapters.aave_v3_base_adapter.urllib.request.urlopen",
        side_effect=exc,
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestAaveV3BaseAdapterConstants(unittest.TestCase):
    """Тест 1–5: константы и метаданные адаптера."""

    def test_01_chain_is_base(self):
        """chain должен быть 'base'."""
        adapter = AaveV3BaseAdapter()
        self.assertEqual(adapter.CHAIN, "base")
        self.assertEqual(CHAIN, "base")

    def test_02_tier_is_t2(self):
        """tier должен быть 'T2'."""
        adapter = AaveV3BaseAdapter()
        self.assertEqual(adapter.TIER, "T2")
        self.assertEqual(adapter.tier, "T2")
        self.assertEqual(TIER, "T2")

    def test_03_tvl_usd(self):
        """TVL_USD должен быть 400_000_000."""
        adapter = AaveV3BaseAdapter()
        self.assertEqual(adapter.TVL_USD, 400_000_000)
        self.assertEqual(TVL_USD, 400_000_000)

    def test_04_risk_score(self):
        """risk_score должен быть 0.35 (L2 bridge risk)."""
        adapter = AaveV3BaseAdapter()
        self.assertAlmostEqual(adapter.RISK_SCORE, 0.35, places=5)
        self.assertAlmostEqual(RISK_SCORE, 0.35, places=5)

    def test_05_protocol_id(self):
        """PROTOCOL_ID должен быть 'aave-v3-base'."""
        adapter = AaveV3BaseAdapter()
        self.assertEqual(adapter.PROTOCOL_ID, "aave-v3-base")
        self.assertEqual(PROTOCOL_ID, "aave-v3-base")


class TestAaveV3BaseAdapterGetApy(unittest.TestCase):
    """Тест 6–10: get_apy() поведение."""

    def test_06_get_apy_returns_float(self):
        """get_apy() должен возвращать float."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=5.2)]):
            result = adapter.get_apy()
        self.assertIsInstance(result, float)

    def test_07_get_apy_in_valid_range(self):
        """get_apy() должен возвращать значение в диапазоне [0.1, 50.0]."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=5.2)]):
            result = adapter.get_apy()
        self.assertGreaterEqual(result, 0.1)
        self.assertLessEqual(result, 50.0)

    def test_08_get_apy_live_value(self):
        """get_apy() должен вернуть APY из DeFiLlama при успешном ответе."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.7)]):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, 6.7, places=5)

    def test_09_get_apy_fallback_on_network_error(self):
        """get_apy() должен вернуть APY_FALLBACK при URLError."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen_error(urllib.error.URLError("timeout")):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)

    def test_10_get_apy_fallback_on_generic_exception(self):
        """get_apy() должен вернуть APY_FALLBACK при любом исключении."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen_error(RuntimeError("connection refused")):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)


class TestAaveV3BaseAdapterGetWriteState(unittest.TestCase):
    """Тест 11–15: get_write_state() структура."""

    def _get_state(self, apy: float = 4.5) -> dict:
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=apy)]):
            return adapter.get_write_state()

    def test_11_write_state_has_required_keys(self):
        """get_write_state() должен содержать все обязательные ключи."""
        required = {
            "protocol_id", "chain", "tier", "apy_pct",
            "tvl_usd", "risk_score", "write_state", "last_updated",
        }
        state = self._get_state()
        for key in required:
            self.assertIn(key, state, f"Отсутствует ключ: {key}")

    def test_12_write_state_chain(self):
        """get_write_state()['chain'] должен быть 'base'."""
        state = self._get_state()
        self.assertEqual(state["chain"], "base")

    def test_13_write_state_tier(self):
        """get_write_state()['tier'] должен быть 'T2'."""
        state = self._get_state()
        self.assertEqual(state["tier"], "T2")

    def test_14_write_state_tvl_usd(self):
        """get_write_state()['tvl_usd'] должен быть 400_000_000."""
        state = self._get_state()
        self.assertEqual(state["tvl_usd"], 400_000_000.0)

    def test_15_write_state_write_state_field(self):
        """get_write_state()['write_state'] должен быть 'read_only'."""
        state = self._get_state()
        self.assertEqual(state["write_state"], "read_only")


class TestAaveV3BaseAdapterGetYieldInfo(unittest.TestCase):
    """Тест 16–19: get_yield_info() нормализация."""

    def test_16_get_yield_info_apy_is_decimal(self):
        """YieldInfo.apy должен быть decimal (apy% / 100)."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=5.0)]):
            info = adapter.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.05, places=5)

    def test_17_get_yield_info_tvl_usd(self):
        """YieldInfo.tvl_usd должен быть 400_000_000."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=4.5)]):
            info = adapter.get_yield_info()
        self.assertEqual(info.tvl_usd, 400_000_000.0)

    def test_18_get_yield_info_tier(self):
        """YieldInfo.tier должен быть 'T2'."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=4.5)]):
            info = adapter.get_yield_info()
        self.assertEqual(info.tier, "T2")

    def test_19_get_yield_info_protocol(self):
        """YieldInfo.protocol должен быть 'aave-v3-base'."""
        adapter = AaveV3BaseAdapter()
        with _patch_urlopen([_make_pool(apy=4.5)]):
            info = adapter.get_yield_info()
        self.assertEqual(info.protocol, "aave-v3-base")


class TestAaveV3BaseAdapterPoolFiltering(unittest.TestCase):
    """Тест 20–22: фильтрация пулов DeFiLlama."""

    def test_20_ignores_wrong_chain(self):
        """Пул на Ethereum не должен матчиться при поиске для Base."""
        adapter = AaveV3BaseAdapter()
        mainnet_pool = _make_pool(chain="Ethereum", apy=3.5, tvl=1_000_000_000.0)
        base_pool = _make_pool(chain="Base", apy=5.1)
        with _patch_urlopen([mainnet_pool, base_pool]):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, 5.1, places=5)

    def test_21_ignores_non_usdc_symbols(self):
        """Пулы не-USDC символов должны игнорироваться."""
        adapter = AaveV3BaseAdapter()
        weth_pool = _make_pool(symbol="WETH", chain="Base", apy=10.0, tvl=500_000_000.0)
        usdc_pool = _make_pool(symbol="USDC", chain="Base", apy=4.8)
        with _patch_urlopen([weth_pool, usdc_pool]):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, 4.8, places=5)

    def test_22_fallback_when_no_matching_pool(self):
        """Если нет подходящего пула — возвращаем APY_FALLBACK."""
        adapter = AaveV3BaseAdapter()
        # Пул на Base но с DAI — не USDC
        dai_pool = _make_pool(symbol="DAI", chain="Base", apy=3.0, tvl=100_000_000.0)
        with _patch_urlopen([dai_pool]):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)


class TestAaveV3BaseAdapterRegistry(unittest.TestCase):
    """Тест 23: проверка ADAPTER_REGISTRY."""

    def test_23_adapter_in_registry(self):
        """ADAPTER_REGISTRY должен содержать 'aave_v3_base'."""
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [entry[0] for entry in ADAPTER_REGISTRY]
        self.assertIn("aave_v3_base", keys, (
            "aave_v3_base не найден в ADAPTER_REGISTRY. "
            f"Найдены: {keys}"
        ))

    def test_24_registry_entry_tier(self):
        """Запись 'aave_v3_base' в ADAPTER_REGISTRY должна иметь tier='T2'."""
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "aave_v3_base":
                self.assertEqual(tier, "T2")
                return
        self.fail("aave_v3_base не найден в ADAPTER_REGISTRY")

    def test_25_registry_entry_class(self):
        """Запись в ADAPTER_REGISTRY должна ссылаться на AaveV3BaseAdapter."""
        from spa_core.adapters import ADAPTER_REGISTRY, AaveV3BaseAdapter
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "aave_v3_base":
                self.assertIs(cls, AaveV3BaseAdapter)
                return
        self.fail("aave_v3_base не найден в ADAPTER_REGISTRY")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Собираем все тест-классы в порядке определения
    test_classes = [
        TestAaveV3BaseAdapterConstants,
        TestAaveV3BaseAdapterGetApy,
        TestAaveV3BaseAdapterGetWriteState,
        TestAaveV3BaseAdapterGetYieldInfo,
        TestAaveV3BaseAdapterPoolFiltering,
        TestAaveV3BaseAdapterRegistry,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*60}")
    print(f"MP-448 AaveV3BaseAdapter: {passed}/{total} тестов прошло")
    if result.failures or result.errors:
        print("FAILED")
        sys.exit(1)
    else:
        print("ALL PASSED")
        sys.exit(0)
