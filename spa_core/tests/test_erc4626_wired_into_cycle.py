"""Производитель ставок обязан ЗАПУСКАТЬСЯ — иначе он не производитель.

Модуль `erc4626_rate_monitor` выводит ставку из ДВУХ собственных наблюдений.
Одно наблюдение не даёт ничего, а второе не появится само: без расписания ряд
никогда не наберётся, и модуль останется красивым кодом, который ничего не
производит.

Система этим уже болела дважды, и оба раза молча: `riskwire` отдавал данные как
живые 840 часов подряд, а `sky_monitor` писал `gsm_hours: null` годами, выходя с
кодом 0 — ни один сторож не сказал ни слова, потому что каждая часть была честна
по отдельности. Поэтому «вызывается ли он вообще» проверяется тестом, а не
надеждой.

Порядок здесь тоже предмет проверки: наблюдение должно сниматься ДО генерации
статуса, иначе сегодняшняя точка попадёт в статус только завтра.
"""
from __future__ import annotations

import inspect
import unittest

from spa_core.paper_trading import cycle_runner


class TestProducerIsWired(unittest.TestCase):

    def test_cycle_calls_the_producer(self):
        """Без этого вызова ряд не наберётся и ставки не будет никогда."""
        src = inspect.getsource(cycle_runner)
        self.assertIn("erc4626_rate_monitor", src,
                      "дневной цикл обязан снимать наблюдение — иначе производитель мёртв")

    def test_observation_happens_before_status_generation(self):
        """Иначе свежая точка попадёт в статус лишь следующим циклом."""
        src = inspect.getsource(cycle_runner)
        erc = src.index("erc4626_rate_monitor")
        gen = src.index("adapter_status_generator import")
        self.assertLess(erc, gen,
                        "наблюдение снимается ДО генерации статуса, а не после")

    def test_producer_failure_cannot_break_the_cycle(self):
        """Сеть падает; трек от этого прерываться не должен.

        Цикл кормит трек go-live — сетевая икота в отчётном слое не имеет права
        его остановить.
        """
        src = inspect.getsource(cycle_runner)
        block = src[src.index("erc4626_rate_monitor"):]
        head = block[:900]
        self.assertIn("except Exception", head,
                      "вызов производителя обязан быть обёрнут — он ходит в сеть")
        self.assertIn("цикл продолжается", head)


class TestProducerContract(unittest.TestCase):
    """То, на что цикл опирается, обязано существовать."""

    def test_observe_is_importable_and_callable(self):
        from spa_core.data_pipeline.erc4626_rate_monitor import observe

        self.assertTrue(callable(observe))
        params = inspect.signature(observe).parameters
        self.assertIn("data_dir", params, "тест обязан уметь подсунуть свой каталог")
        self.assertIn("now", params, "часы — вход, а не окружение")

    def test_observe_returns_the_shape_the_cycle_reads(self):
        """Цикл считает ставки по ``vaults`` — форма ответа часть контракта."""
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest import mock

        from spa_core.data_pipeline import erc4626_rate_monitor as M

        with TemporaryDirectory() as tmp:
            with mock.patch.object(M, "read_share_price", lambda *a, **k: (1.16, ["a", "b"])):
                out = M.observe(data_dir=Path(tmp))
        self.assertIn("vaults", out)
        self.assertTrue(all(isinstance(v, dict) for v in out["vaults"].values()))
        # Первый прогон: точка есть, ставки нет — и это правильный ответ.
        self.assertTrue(all(v.get("apy_pct") is None for v in out["vaults"].values()))


if __name__ == "__main__":
    unittest.main()
