"""Двери живых фидов закрыты для тестов — и ОТКРЫТЫ в проде.

Карточка `agent-tests-reach-live-feed-222`. Сторож живой сети отвечает на вопрос
«ушёл ли вызов наружу» — не ушёл ни разу. Эти тесты держат ДРУГОЙ вопрос: «а
подходил ли тест к двери вообще». Двери закрыты фикстурой conftest на том же шве,
результат которого ТОЖДЕСТВЕН отказу сторожа, поэтому ни один ассерт не ослаблен.

Каждое свойство закреплено с ОБЕИХ сторон. Без прод-стороны правка означала бы
«фиды больше не читаются никогда», и мы разменяли бы герметичность на неработающие
фиды — ровно та ошибка, которую `test_gas_monitor_hermetic.py` уже предотвратил
для оракула газа.
"""
from __future__ import annotations

import unittest
from unittest import mock

import pytest

from spa_core.adapters.defillama_feed import DeFiLlamaFeed
from spa_core.strategy_lab.data import _http


# ── сторона теста: дверь закрыта, сокет не открывается ──────────────────────


class TestTheDoorsAreShutForAnOrdinaryTest(unittest.TestCase):
    """Обычный тест (без метки) исполняется при закрытых дверях."""

    def test_strategy_lab_http_door_is_shut(self):
        self.assertTrue(_http.OFFLINE, "conftest обязан закрыть дверь _http")

    def test_defillama_door_is_shut(self):
        import spa_core.adapters.config as cfg

        self.assertFalse(cfg.DEFILLAMA_ENABLED, "conftest обязан закрыть фид DeFiLlama")

    def test_the_second_defillama_client_door_is_shut(self):
        """Клиентов DeFiLlama ДВА. Закрыть один — не значит закрыть дверь."""
        import spa_core.feeds.defi_llama_feed as feed

        self.assertFalse(feed.ENABLED, "conftest обязан закрыть и feeds/-клиент")

    def test_the_second_client_fetches_nothing(self):
        import spa_core.feeds.defi_llama_feed as feed

        with mock.patch("urllib.request.urlopen") as fake:
            self.assertIsNone(feed.DefiLlamaFeed()._load_pools())
        fake.assert_not_called()

    def test_the_second_client_is_read_at_call_time_not_construction(self):
        """Ключевое свойство: у модуля есть процессный ``_SINGLETON``.

        Решение, принятое в конструкторе, заморозил бы первый же тест, который
        построил фид, — и оно протекло бы на весь прогон, включая тест с меткой.
        """
        import spa_core.feeds.defi_llama_feed as feed

        built_while_shut = feed.DefiLlamaFeed()
        raw = mock.MagicMock()
        raw.read.return_value = b'{"status":"success","data":[]}'
        raw.__enter__.return_value = raw
        with mock.patch.object(feed, "ENABLED", True), \
             mock.patch("urllib.request.urlopen", return_value=raw) as fake:
            built_while_shut._load_pools()
        fake.assert_called_once()

    def test_http_fetch_refuses_a_live_host_without_a_socket(self):
        with mock.patch("urllib.request.urlopen") as fake:
            with self.assertRaises(_http.FetchError):
                _http.http_fetch("https://api.hyperliquid.xyz/info")
        fake.assert_not_called()

    def test_a_defillama_feed_built_now_fetches_nothing(self):
        with mock.patch("urllib.request.urlopen") as fake:
            self.assertIsNone(DeFiLlamaFeed()._fetch_pools())
        fake.assert_not_called()

    def test_loopback_stays_open_even_with_the_door_shut(self):
        """Локальный сервер — не живая сеть; та же линия, что у network_guard.

        Без этого свойства закрытая дверь убила бы фикстуры с локальным HTTP.
        """
        payload = b'{"ok": true}'
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        with mock.patch("urllib.request.urlopen", return_value=resp) as fake:
            got = _http.http_fetch("http://127.0.0.1:8765/health")
        fake.assert_called_once()
        self.assertEqual(got, {"ok": True})


# ── сторона прода: по умолчанию двери ОТКРЫТЫ ───────────────────────────────


class TestProductionKeepsItsFeeds(unittest.TestCase):
    """Значение по умолчанию в исходнике — открыто. Закрывает ТОЛЬКО conftest."""

    def test_the_module_default_is_open(self):
        """Читается из исходника, а не из живого модуля: фикстура его уже меняла."""
        import ast
        import pathlib

        src = pathlib.Path(_http.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        defaults = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "OFFLINE" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(
            defaults, [False],
            "в проде дверь обязана быть открыта — OFFLINE = False в исходнике",
        )

    def test_with_the_door_open_the_request_goes_out(self):
        payload = b'{"venue": "ok"}'
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        with mock.patch.object(_http, "OFFLINE", False), \
             mock.patch("urllib.request.urlopen", return_value=resp) as fake:
            got = _http.http_fetch("https://api.hyperliquid.xyz/info")
        fake.assert_called_once()
        self.assertEqual(got, {"venue": "ok"})

    def test_with_the_feed_enabled_defillama_parses_its_body(self):
        import gzip
        import json

        raw = gzip.compress(
            json.dumps({"status": "success", "data": [{"pool": "p"}]}).encode()
        )
        resp = mock.MagicMock()
        resp.read.return_value = raw
        resp.__enter__.return_value = resp
        with mock.patch("urllib.request.urlopen", return_value=resp) as fake:
            pools = DeFiLlamaFeed(enabled=True)._fetch_pools()
        fake.assert_called_once()
        self.assertEqual(pools, [{"pool": "p"}])


# ── тождество: закрытая дверь даёт РОВНО ТОТ ЖЕ результат, что и отказ ───────


class TestTheClosedDoorChangesNoObservableResult(unittest.TestCase):
    """Главный аргумент против «это ослабление» (инв. #16).

    До правки поход в сеть кончался отказом сторожа (`OSError`), который
    `http_fetch` переоборачивал в `FetchError`, а `_fetch_pools` глотал в `None`.
    Здесь оба пути сравниваются НАПРЯМУЮ, а не на слово.
    """

    def test_http_fetch_raises_the_same_type_both_ways(self):
        with mock.patch.object(_http, "OFFLINE", True):
            with self.assertRaises(_http.FetchError) as shut:
                _http.http_fetch("https://api.hyperliquid.xyz/info")
        # Дверь открыта — но сторож живой сети на месте и отказывает, как раньше.
        with mock.patch.object(_http, "OFFLINE", False):
            with self.assertRaises(_http.FetchError) as refused:
                _http.http_fetch("https://api.hyperliquid.xyz/info")
        self.assertIs(type(shut.exception), type(refused.exception))

    def test_defillama_returns_none_both_ways(self):
        shut = DeFiLlamaFeed(enabled=False)._fetch_pools()
        refused = DeFiLlamaFeed(enabled=True)._fetch_pools()  # сторож откажет
        self.assertIsNone(shut)
        self.assertIsNone(refused)


# ── метка: тест, чей ПРЕДМЕТ — транспорт, оставляет двери открытыми ─────────


@pytest.mark.live_feed_transport
class TestTheMarkerReopensTheDoors(unittest.TestCase):
    """Положительный контроль самой метки.

    Без него «двери закрыты всегда» и «метка работает» были бы неотличимы, а
    отказавшая метка молча превратила бы транспортные тесты в пустышки.
    """

    def test_marked_tests_see_the_doors_open(self):
        import spa_core.adapters.config as cfg
        import spa_core.feeds.defi_llama_feed as feed

        self.assertFalse(_http.OFFLINE, "метка обязана оставить дверь _http открытой")
        self.assertTrue(cfg.DEFILLAMA_ENABLED, "метка обязана оставить фид включённым")
        self.assertTrue(feed.ENABLED, "метка обязана оставить и feeds/-клиент включённым")

    def test_the_network_guard_still_refuses_a_marked_test(self):
        """Метка НЕ выпускает в сеть — она разрешает только попытку."""
        with self.assertRaises(_http.FetchError):
            _http.http_fetch("https://api.hyperliquid.xyz/info")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
