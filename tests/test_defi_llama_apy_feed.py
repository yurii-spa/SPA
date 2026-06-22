"""tests/test_defi_llama_apy_feed.py

Тесты для spa_core.price_feeds.defi_llama_apy_feed

Группы тестов
-------------
TestProtocolPoolMap       — структура маппинга (4 теста)
TestFetchAllPools         — _fetch_all_pools: сеть / парсинг (4 теста)
TestBestPoolApy           — _best_pool_apy: фильтрация пулов (4 теста)
TestFetchApyMap           — fetch_apy_map: публичный интерфейс (3 теста)
TestGetAdapterApy         — get_adapter_apy: single-adapter (3 теста)

Итого: 18 тестов
"""
from __future__ import annotations

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

# Добавляем корень репо в sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.price_feeds.defi_llama_apy_feed import (
    PROTOCOL_POOL_MAP,
    MIN_TVL_USD,
    fetch_apy_map,
    get_adapter_apy,
    _fetch_all_pools,
    _best_pool_apy,
)


# ── Фабрики ───────────────────────────────────────────────────────────────────

def _make_response(data: list) -> bytes:
    """Сериализовать список пулов в байты DeFiLlama-ответа."""
    return json.dumps({"status": "success", "data": data}).encode()


def _make_pool(
    project: str = "aave-v3",
    chain: str = "Ethereum",
    apy: float = 3.5,
    tvl: float = 10_000_000.0,
    symbol: str = "USDC",
) -> dict:
    return {
        "pool": "test-uuid",
        "project": project,
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
        "symbol": symbol,
    }


def _mock_urlopen(response_bytes: bytes):
    """Контекстный менеджер-заглушка для urllib.request.urlopen."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read = MagicMock(return_value=response_bytes)
    return ctx


# ── TestProtocolPoolMap ───────────────────────────────────────────────────────

class TestProtocolPoolMap(unittest.TestCase):
    """Структура и полнота PROTOCOL_POOL_MAP."""

    ALL_EXPECTED = [
        "aave_v3", "compound_v3", "morpho_blue", "spark_susds",
        "yearn_v3", "euler_v2", "maple", "pendle",
        "aave_v3_base", "morpho_blue_base", "extra_finance_base",
    ]

    def test_all_expected_adapters_present(self):
        """Все 11 ожидаемых адаптеров должны быть в маппинге."""
        for adapter_id in self.ALL_EXPECTED:
            with self.subTest(adapter_id=adapter_id):
                self.assertIn(adapter_id, PROTOCOL_POOL_MAP)

    def test_extra_finance_base_present(self):
        """extra_finance_base должен быть в маппинге (MP-510 / ADR-026)."""
        self.assertIn("extra_finance_base", PROTOCOL_POOL_MAP)

    def test_all_fallbacks_in_reasonable_range(self):
        """Все fallback APY должны быть между 0.5% и 50%."""
        for adapter_id, (_, _, fallback) in PROTOCOL_POOL_MAP.items():
            with self.subTest(adapter_id=adapter_id):
                self.assertGreater(fallback, 0.5, f"{adapter_id}: fallback слишком мал")
                self.assertLess(fallback, 50.0, f"{adapter_id}: fallback слишком велик")

    def test_map_has_exactly_11_entries(self):
        """Маппинг должен содержать ровно 11 записей."""
        self.assertEqual(len(PROTOCOL_POOL_MAP), 11)


# ── TestFetchAllPools ─────────────────────────────────────────────────────────

class TestFetchAllPools(unittest.TestCase):
    """_fetch_all_pools: парсинг и обработка ошибок."""

    def test_returns_list_on_success(self):
        """При валидном ответе DeFiLlama должен вернуть список пулов."""
        pools = [_make_pool(), _make_pool(project="compound-v3")]
        response_bytes = _make_response(pools)
        ctx = _mock_urlopen(response_bytes)
        with patch("urllib.request.urlopen", return_value=ctx):
            result = _fetch_all_pools()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_returns_none_on_url_error(self):
        """При URLError (сеть недоступна) должен вернуть None, не поднимать."""
        with patch("urllib.request.urlopen", side_effect=URLError("timeout")):
            result = _fetch_all_pools()
        self.assertIsNone(result)

    def test_returns_none_on_bad_json(self):
        """При невалидном JSON должен вернуть None."""
        ctx = _mock_urlopen(b"not-json!!!")
        with patch("urllib.request.urlopen", return_value=ctx):
            result = _fetch_all_pools()
        self.assertIsNone(result)

    def test_returns_none_when_data_missing(self):
        """Если в ответе нет ключа 'data' — вернуть None."""
        ctx = _mock_urlopen(json.dumps({"status": "success"}).encode())
        with patch("urllib.request.urlopen", return_value=ctx):
            result = _fetch_all_pools()
        self.assertIsNone(result)


# ── TestBestPoolApy ───────────────────────────────────────────────────────────

class TestBestPoolApy(unittest.TestCase):
    """_best_pool_apy: правильность фильтрации и выбора пула."""

    def test_returns_apy_for_matching_pool(self):
        """Должен вернуть APY пула совпадающего по project и chain."""
        pools = [_make_pool(project="aave-v3", chain="Ethereum", apy=3.5)]
        result = _best_pool_apy(pools, "aave-v3", "ethereum")
        self.assertAlmostEqual(result, 3.5, places=2)

    def test_returns_none_if_tvl_below_min(self):
        """Пул с TVL ниже порога должен быть отфильтрован."""
        pools = [_make_pool(project="aave-v3", chain="Ethereum", apy=3.5, tvl=100.0)]
        result = _best_pool_apy(pools, "aave-v3", "ethereum", min_tvl=MIN_TVL_USD)
        self.assertIsNone(result)

    def test_selects_highest_tvl_pool(self):
        """Из нескольких совпадающих пулов должен выбрать с максимальным TVL."""
        pools = [
            _make_pool(project="aave-v3", chain="Ethereum", apy=2.0, tvl=5_000_000.0),
            _make_pool(project="aave-v3", chain="Ethereum", apy=4.5, tvl=20_000_000.0),
            _make_pool(project="aave-v3", chain="Ethereum", apy=1.0, tvl=1_000_000.0),
        ]
        result = _best_pool_apy(pools, "aave-v3", "ethereum")
        self.assertAlmostEqual(result, 4.5, places=2)  # пул с TVL 20M

    def test_returns_none_for_wrong_chain(self):
        """Пул на неправильном чейне должен быть пропущен."""
        pools = [_make_pool(project="aave-v3", chain="Polygon", apy=3.5, tvl=10_000_000.0)]
        result = _best_pool_apy(pools, "aave-v3", "ethereum")
        self.assertIsNone(result)


# ── TestFetchApyMap ───────────────────────────────────────────────────────────

class TestFetchApyMap(unittest.TestCase):
    """fetch_apy_map: публичный агрегатор APY."""

    def test_returns_all_adapters(self):
        """Результат должен содержать все ключи PROTOCOL_POOL_MAP."""
        # Сеть недоступна — проверяем что fallback покрывает всё
        with patch("urllib.request.urlopen", side_effect=URLError("no network")):
            result = fetch_apy_map()
        for adapter_id in PROTOCOL_POOL_MAP:
            self.assertIn(adapter_id, result, f"Отсутствует: {adapter_id}")

    def test_fetch_fallback_on_network_error(self):
        """При ошибке сети все значения должны совпадать с fallback из маппинга."""
        with patch("urllib.request.urlopen", side_effect=URLError("refused")):
            result = fetch_apy_map()
        for adapter_id, (_, _, fallback) in PROTOCOL_POOL_MAP.items():
            with self.subTest(adapter_id=adapter_id):
                self.assertAlmostEqual(
                    result[adapter_id], fallback, places=5,
                    msg=f"{adapter_id}: ожидали fallback {fallback}, получили {result[adapter_id]}",
                )

    def test_apy_values_reasonable_range(self):
        """Все APY в результате должны быть в диапазоне 0.5%–50%."""
        # Тест не зависит от сети: fallback-значения уже проверены TestProtocolPoolMap,
        # но здесь проверяем финальный dict fetch_apy_map при недоступной сети.
        with patch("urllib.request.urlopen", side_effect=URLError("offline")):
            result = fetch_apy_map()
        for adapter_id, apy in result.items():
            with self.subTest(adapter_id=adapter_id):
                self.assertGreater(apy, 0.5, f"{adapter_id}: APY слишком мал")
                self.assertLess(apy, 50.0, f"{adapter_id}: APY слишком велик")

    def test_uses_live_apy_when_pool_found(self):
        """Если DeFiLlama вернула пул — использует live APY, не fallback."""
        live_apy = 7.77
        pools = [_make_pool(project="aave-v3", chain="Ethereum", apy=live_apy, tvl=50_000_000.0)]
        ctx = _mock_urlopen(_make_response(pools))
        with patch("urllib.request.urlopen", return_value=ctx):
            result = fetch_apy_map()
        self.assertAlmostEqual(result["aave_v3"], live_apy, places=2)

    def test_fallback_for_missing_pool_with_live_response(self):
        """Если пул не найден в ответе DeFiLlama — использует fallback."""
        # Возвращаем только aave_v3 пул, остальные протоколы отсутствуют
        pools = [_make_pool(project="aave-v3", chain="Ethereum", apy=3.5, tvl=10_000_000.0)]
        ctx = _mock_urlopen(_make_response(pools))
        with patch("urllib.request.urlopen", return_value=ctx):
            result = fetch_apy_map()
        # compound_v3 отсутствует в пулах → fallback
        _, _, compound_fallback = PROTOCOL_POOL_MAP["compound_v3"]
        self.assertAlmostEqual(result["compound_v3"], compound_fallback, places=5)


# ── TestGetAdapterApy ─────────────────────────────────────────────────────────

class TestGetAdapterApy(unittest.TestCase):
    """get_adapter_apy: single-adapter запросы."""

    def test_get_adapter_apy_fallback(self):
        """При недоступной сети должен вернуть fallback-значение."""
        with patch("urllib.request.urlopen", side_effect=URLError("no net")):
            apy = get_adapter_apy("aave_v3")
        _, _, expected_fallback = PROTOCOL_POOL_MAP["aave_v3"]
        self.assertAlmostEqual(apy, expected_fallback, places=5)

    def test_get_adapter_apy_unknown_id_returns_zero(self):
        """Неизвестный adapter_id должен вернуть 0.0, не поднимать."""
        result = get_adapter_apy("nonexistent_protocol_xyz")
        self.assertEqual(result, 0.0)

    def test_extra_finance_base_fallback(self):
        """extra_finance_base fallback должен работать корректно."""
        with patch("urllib.request.urlopen", side_effect=URLError("offline")):
            apy = get_adapter_apy("extra_finance_base")
        _, _, expected = PROTOCOL_POOL_MAP["extra_finance_base"]
        self.assertAlmostEqual(apy, expected, places=5)

    def test_get_adapter_apy_returns_live_when_available(self):
        """Если DeFiLlama возвращает пул — используем live APY."""
        live_apy = 6.55
        pools = [_make_pool(project="morpho-blue", chain="Ethereum", apy=live_apy, tvl=8_000_000.0)]
        ctx = _mock_urlopen(_make_response(pools))
        with patch("urllib.request.urlopen", return_value=ctx):
            apy = get_adapter_apy("morpho_blue")
        self.assertAlmostEqual(apy, live_apy, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
