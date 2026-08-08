"""Оракул газа не ходит в сеть из тестов — ни в CI, ни на машине разработчика.

Сторож здесь был и раньше, но смотрел на `SPA_ENV == "ci"`. Значит он защищал
CI и НЕ защищал локальный прогон — то есть ровно ту среду, где тесты пишут и
запускают. Класс дефекта тот же, что у «не измерено ≠ измерено и равно нулю»:
проверка верная, условие слишком узкое, и потому она молчит там, где нужна.

Измерено 2026-08-08 трассировкой сторожа живой сети: **800 отказов** в одном
`test_nav_conservation_property` приходили из `_fetch_gas_gwei`. Семь раундов
перебора подозреваемых этого не нашли; трассировка назвала источник за один прогон.

Тесты держат обе стороны. Без второй правка означала бы «монитор газа больше не
работает никогда», и мы разменяли бы герметичность на неработающий стоп-кран.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from spa_core.monitoring.base_gas_monitor import BaseGasMonitor


class TestNoLiveReachFromTests(unittest.TestCase):

    def test_under_pytest_the_fetch_refuses_without_touching_the_network(self):
        """PYTEST_CURRENT_TEST ставит сам pytest — значит мы всегда под ним."""
        self.assertTrue(os.environ.get("PYTEST_CURRENT_TEST"),
                        "тест обязан выполняться под pytest")
        with mock.patch("urllib.request.urlopen") as fake:
            got = BaseGasMonitor()._fetch_gas_gwei("https://example.invalid/gas")
        self.assertIsNone(got, "из тестов оракул обязан вернуть None")
        fake.assert_not_called()

    def test_the_ci_guard_still_holds(self):
        """Прежнее условие не потеряно — оно расширено, а не заменено."""
        with mock.patch.dict(os.environ, {"SPA_ENV": "ci"}, clear=False), \
             mock.patch("urllib.request.urlopen") as fake:
            got = BaseGasMonitor()._fetch_gas_gwei("https://example.invalid/gas")
        self.assertIsNone(got)
        fake.assert_not_called()


class TestProductionStillFetches(unittest.TestCase):
    """Сторона, без которой правка была бы отключением монитора газа.

    В проде нет ни SPA_ENV=ci, ни PYTEST_CURRENT_TEST — запрос обязан уйти.
    """

    def test_without_both_markers_the_request_goes_out(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("SPA_ENV", "PYTEST_CURRENT_TEST")}
        payload = b'{"blockPrices": [{"estimatedPrices": [{"price": 0.05}]}]}'
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("urllib.request.urlopen", return_value=resp) as fake:
            got = BaseGasMonitor()._fetch_gas_gwei("https://example.invalid/gas")
        fake.assert_called_once()
        self.assertEqual(got, 0.05, "в проде цена газа обязана читаться")


if __name__ == "__main__":
    unittest.main()
