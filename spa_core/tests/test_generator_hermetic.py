"""Генератор снимка адаптеров не ходит в сеть из тестов — результат тот же.

Второй экземпляр того же дефекта, что в `base_gas_monitor` (закрыт 2026-08-08):
сторож смотрел на `SPA_ENV == "ci"`, то есть защищал CI и не защищал машину
разработчика, где тесты пишут и запускают. Трассировка сторожа живой сети дала
`adapter_status_generator.py:212` — 400 отказов на один прогон
`test_nav_conservation_property`.

Здесь важна особенность, которой не было у оракула газа: правка **строго сохраняет
поведение**. Поход в сеть из тестов и так завершался `OSError`, который ловится
ниже по функции и возвращает ровно этот же `None`. Менялось только потраченное
время. Это не ослабление проверки — наблюдаемый результат тождественен, и первый
тест ниже закрепляет именно тождество, а не просто «вернул None».

Fallback остаётся честным: без живых данных APY помечается non-live, а не
выдумывается (`.claude/rules/adapters.md`).
"""
from __future__ import annotations

import os
import unittest
import urllib.error
from unittest import mock

from spa_core.monitoring import adapter_status_generator as gen


class TestNoLiveReachFromTests(unittest.TestCase):

    def test_result_is_IDENTICAL_to_what_the_network_path_produced(self):
        """Тождество, а не просто None: до правки отказ давал тот же результат.

        Слева — что возвращается теперь (без похода). Справа — что возвращал
        прежний путь: реальный `OSError` из сторожа, пойманный обработчиком.
        """
        with mock.patch("urllib.request.urlopen") as fake:
            now = gen._fetch_defillama()
        fake.assert_not_called()

        env = {k: v for k, v in os.environ.items()
               if k not in ("SPA_ENV", "PYTEST_CURRENT_TEST")}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("urllib.request.urlopen",
                        side_effect=OSError("сторож живой сети: отказ")):
            before = gen._fetch_defillama()

        self.assertEqual(now, before,
                         "правка обязана быть тождественной по результату")
        self.assertIsNone(now)

    def test_the_ci_guard_still_holds(self):
        """Прежнее условие расширено, а не заменено."""
        with mock.patch.dict(os.environ, {"SPA_ENV": "ci"}, clear=False), \
             mock.patch("urllib.request.urlopen") as fake:
            self.assertIsNone(gen._fetch_defillama())
        fake.assert_not_called()


class TestProductionStillFetches(unittest.TestCase):
    """Сторона, без которой правка была бы отключением живого фида."""

    def test_without_both_markers_the_feed_is_read(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("SPA_ENV", "PYTEST_CURRENT_TEST")}
        resp = mock.MagicMock()
        resp.read.return_value = b'{"data": [{"pool": "x", "apy": 4.2}]}'
        resp.__enter__.return_value = resp
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("urllib.request.urlopen", return_value=resp) as fake:
            pools = gen._fetch_defillama()
        fake.assert_called_once()
        self.assertEqual(pools, [{"pool": "x", "apy": 4.2}],
                         "в проде пулы обязаны читаться из фида")

    def test_a_network_failure_in_production_is_still_a_honest_None(self):
        """Fail-CLOSED сохраняется: нет данных — None, а не выдуманное значение."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("SPA_ENV", "PYTEST_CURRENT_TEST")}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("сеть недоступна")):
            self.assertIsNone(gen._fetch_defillama())


if __name__ == "__main__":
    unittest.main()
