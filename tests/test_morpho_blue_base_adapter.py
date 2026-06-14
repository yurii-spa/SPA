#!/usr/bin/env python3
"""
Standalone тесты для MorphoBlueBaseAdapter (MP-450).

Запуск: python3 tests/test_morpho_blue_base_adapter.py
Не требует pytest — использует только stdlib unittest.
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

from spa_core.adapters.morpho_blue_base_adapter import (
    APY_FALLBACK,
    CHAIN,
    GAS_ADVANTAGE_USD,
    GAS_BASE_USD,
    PROTOCOL_ID,
    RISK_SCORE,
    T2_CAP_PCT,
    TIER,
    TVL_USD,
    MorphoBlueBaseAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_defillama_response(pools: list[dict]) -> bytes:
    """Создаёт JSON-ответ DeFiLlama для мока."""
    payload = {"status": "success", "data": pools}
    return json.dumps(payload).encode("utf-8")


def _make_pool(
    project: str = "morpho",
    symbol: str = "USDC",
    chain: str = "Base",
    apy: float = 6.2,
    tvl: float = 180_000_000.0,
    pool_id: str = "morpho-base-usdc-pool",
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
        "spa_core.adapters.morpho_blue_base_adapter.urllib.request.urlopen",
        return_value=FakeResponse(),
    )


def _patch_urlopen_error(exc: Exception):
    """Мокает urlopen, бросающий указанное исключение."""
    return patch(
        "spa_core.adapters.morpho_blue_base_adapter.urllib.request.urlopen",
        side_effect=exc,
    )


# ---------------------------------------------------------------------------
# Тесты — группа 1: константы и идентичность
# ---------------------------------------------------------------------------

class TestMorphoBlueBaseConstants(unittest.TestCase):
    """Тест 01–05: константы модуля и атрибуты класса."""

    def test_01_chain_is_base(self):
        """chain должен быть 'base'."""
        adapter = MorphoBlueBaseAdapter()
        self.assertEqual(adapter.CHAIN, "base")
        self.assertEqual(CHAIN, "base")

    def test_02_tier_is_t2(self):
        """tier должен быть 'T2'."""
        adapter = MorphoBlueBaseAdapter()
        self.assertEqual(adapter.TIER, "T2")
        self.assertEqual(adapter.tier, "T2")
        self.assertEqual(TIER, "T2")

    def test_03_tvl_usd_180m(self):
        """TVL_USD должен быть 180_000_000."""
        adapter = MorphoBlueBaseAdapter()
        self.assertEqual(adapter.TVL_USD, 180_000_000)
        self.assertEqual(TVL_USD, 180_000_000)

    def test_04_risk_score_is_038(self):
        """risk_score должен быть 0.38 (L2 bridge risk premium)."""
        adapter = MorphoBlueBaseAdapter()
        self.assertAlmostEqual(adapter.RISK_SCORE, 0.38, places=5)
        self.assertAlmostEqual(RISK_SCORE, 0.38, places=5)

    def test_05_protocol_id(self):
        """PROTOCOL_ID должен быть 'morpho-blue-base'."""
        adapter = MorphoBlueBaseAdapter()
        self.assertEqual(adapter.PROTOCOL_ID, "morpho-blue-base")
        self.assertEqual(PROTOCOL_ID, "morpho-blue-base")


# ---------------------------------------------------------------------------
# Тесты — группа 2: get_apy()
# ---------------------------------------------------------------------------

class TestMorphoBlueBaseGetApy(unittest.TestCase):
    """Тест 06–10: get_apy() поведение."""

    def test_06_get_apy_returns_float(self):
        """get_apy() должен возвращать float."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.5)]):
            result = adapter.get_apy()
        self.assertIsInstance(result, float)

    def test_07_get_apy_in_valid_range(self):
        """get_apy() должен возвращать значение в диапазоне [0.1, 50.0]."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.5)]):
            result = adapter.get_apy()
        self.assertGreaterEqual(result, 0.1)
        self.assertLessEqual(result, 50.0)

    def test_08_get_apy_live_value(self):
        """get_apy() должен вернуть живое значение из DeFiLlama."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=7.3)]):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, 7.3, places=5)

    def test_09_fallback_on_url_error(self):
        """get_apy() должен использовать fallback=6.2 при URLError."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen_error(urllib.error.URLError("timeout")):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)
        self.assertAlmostEqual(result, 6.2, places=5)

    def test_10_fallback_on_generic_exception(self):
        """get_apy() должен использовать fallback при любом исключении."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen_error(RuntimeError("unexpected")):
            result = adapter.get_apy()
        self.assertAlmostEqual(result, APY_FALLBACK, places=5)


# ---------------------------------------------------------------------------
# Тесты — группа 3: get_write_state()
# ---------------------------------------------------------------------------

class TestMorphoBlueBaseWriteState(unittest.TestCase):
    """Тест 11–13: get_write_state() структура и значения."""

    def test_11_get_write_state_required_keys(self):
        """get_write_state() должен содержать все обязательные ключи."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            state = adapter.get_write_state()
        required_keys = {
            "protocol_id", "chain", "tier", "apy_pct",
            "tvl_usd", "risk_score", "last_updated",
        }
        for key in required_keys:
            self.assertIn(key, state, f"Missing key: {key}")

    def test_12_get_write_state_values(self):
        """get_write_state() должен вернуть корректные статические значения."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.5)]):
            state = adapter.get_write_state()
        self.assertEqual(state["protocol_id"], "morpho-blue-base")
        self.assertEqual(state["chain"], "base")
        self.assertEqual(state["tier"], "T2")
        self.assertEqual(state["tvl_usd"], 180_000_000.0)
        self.assertAlmostEqual(state["risk_score"], 0.38, places=5)

    def test_13_get_write_state_apy_is_float(self):
        """get_write_state()['apy_pct'] должен быть float."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            state = adapter.get_write_state()
        self.assertIsInstance(state["apy_pct"], float)


# ---------------------------------------------------------------------------
# Тесты — группа 4: validate()
# ---------------------------------------------------------------------------

class TestMorphoBlueBaseValidate(unittest.TestCase):
    """Тест 14–15: validate() корректность."""

    def test_14_validate_true_with_valid_data(self):
        """validate() должен вернуть True при корректных данных."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.2, tvl=180_000_000.0)]):
            result = adapter.validate()
        self.assertTrue(result)

    def test_15_validate_true_with_fallback(self):
        """validate() должен вернуть True даже при использовании fallback APY."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen_error(urllib.error.URLError("network error")):
            result = adapter.validate()
        # fallback APY = 6.2 > 0, TVL_USD = 180M > 0
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# Тесты — группа 5: get_yield_info()
# ---------------------------------------------------------------------------

class TestMorphoBlueBaseYieldInfo(unittest.TestCase):
    """Тест 16–17: get_yield_info() структура."""

    def test_16_yield_info_tier_is_t2(self):
        """get_yield_info().tier должен быть 'T2'."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool()]):
            yi = adapter.get_yield_info()
        self.assertEqual(yi.tier, "T2")

    def test_17_yield_info_apy_is_decimal(self):
        """get_yield_info().apy должен быть в формате decimal (0.0–1.0)."""
        adapter = MorphoBlueBaseAdapter()
        with _patch_urlopen([_make_pool(apy=6.2)]):
            yi = adapter.get_yield_info()
        # 6.2% / 100 = 0.062
        self.assertAlmostEqual(yi.apy, 0.062, places=4)
        self.assertLess(yi.apy, 1.0)


# ---------------------------------------------------------------------------
# Главная точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestMorphoBlueBaseConstants,
        TestMorphoBlueBaseGetApy,
        TestMorphoBlueBaseWriteState,
        TestMorphoBlueBaseValidate,
        TestMorphoBlueBaseYieldInfo,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
