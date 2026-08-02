"""Цикл #89: artifact_freshness не имеет права трогать боевой Telegram напрямую.

Почему этот файл существует
---------------------------
Агент `com.spa.artifact_freshness` (добавлен 2026-08-02 коммитом `7ebe3e3a2`)
слал предупреждение о протухших артефактах прямым вызовом
`telegram_client.send_message`. Две беды сразу:

1. **Обход единственной инстанции пуша.** CI-сторож
   `spa_core/tests/test_telegram_single_authority.py::test_no_rogue_telegram_senders`
   покраснел на `main` в тот же день.
2. **Уровень, а не фронт.** Протухший артефакт — СОСТОЯНИЕ: пока продюсер не
   починен, каждый плановый прогон агента отправлял бы владельцу ОДИН И ТОТ ЖЕ
   текст. Ровно тот класс потопа, ради которого построен `push_policy`
   (edge-trigger + потолок в день + очередь дайджеста).

**Сам маршрут починен не здесь.** Пока цикл #89 гонял полную батарею, ПАРАЛЛЕЛЬНАЯ
сессия доставила эквивалентную починку (`4f6e806bf`): и перевод на
`push_policy.enqueue_digest`, и возврат снесённой заглушки в
`test_cycle_gap_monitor.py`. Своя (независимо сделанная и такая же по существу)
правка НЕ пушилась поверх — это был бы ровно тот whole-file overwrite, который
цикл #89 в этот же день чинил в `docs/STATE.md`.

**Тестов та починка не принесла** — остался только структурный CI-сторож. Этот
файл закрывает поведение: что именно уходит в очередь, что при здоровых
артефактах не уходит НИЧЕГО, и что N прогонов подряд дают НОЛЬ пушей владельцу
(свойство, ради которого маршрут и менялся, — сторож его не проверяет).

Проверки герметичные: боевой транспорт не импортируется, сеть не нужна,
`data/telegram/` подменяется на временный каталог. Ни один существующий тест
не изменён (инвариант #16).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import artifact_freshness as af

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE = _REPO_ROOT / "spa_core" / "monitoring" / "artifact_freshness.py"


def _stale_report(n: int = 2) -> dict:
    """Отчёт с протухшими артефактами — минимальный, но той же формы, что живой."""
    return {
        "any_stale": True,
        "n_stale": n,
        "stale": [
            {
                "name": f"artifact_{i}",
                "public": i == 0,
                "age_hours": 50.0 + i,
                "status": "STALE",
                "max_age_hours": 24.0,
                "producer": f"producer_{i}",
            }
            for i in range(n)
        ],
    }


class TestNoDirectTransport(unittest.TestCase):
    """Структурная привязка: модуль не тянет транспорт ни под каким именем."""

    def test_module_does_not_import_the_transport(self):
        src = _MODULE.read_text(encoding="utf-8")
        self.assertNotRegex(
            src,
            r"from\s+spa_core\.alerts\.telegram_client\s+import",
            "artifact_freshness снова импортирует боевой транспорт — "
            "маршрут только через push_policy (см. test_telegram_single_authority)",
        )
        self.assertNotIn(
            "api.telegram.org", src,
            "прямой POST в Telegram из монитора запрещён",
        )

    def test_module_routes_through_push_policy(self):
        """Форма вызова не важна — важно, что маршрут ведёт в push_policy.

        Допустимы обе идиомы, которыми это пишут в репозитории:
        ``from spa_core.telegram import push_policy`` + ``push_policy.enqueue_digest(...)``
        и ``from spa_core.telegram.push_policy import enqueue_digest`` + ``enqueue_digest(...)``.
        Привязываться к одной из них — значит краснеть на безобидном рефакторинге.
        """
        src = _MODULE.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r"(push_policy\.enqueue_digest|from\s+spa_core\.telegram\.push_policy\s+import\s+[^\n]*enqueue_digest)",
            "маршрут в push_policy не найден ни в одной из принятых форм",
        )


class TestDigestRoute(unittest.TestCase):
    """Поведение: уведомление УХОДИТ, но в очередь дайджеста, а не в пуш."""

    def test_stale_report_is_queued_to_the_digest(self):
        with TemporaryDirectory() as td:
            tg_dir = Path(td) / "telegram"
            tg_dir.mkdir(parents=True)
            from spa_core.telegram import push_policy

            with patch.object(push_policy, "_tg_dir", return_value=tg_dir):
                queued = af._alert_if_stale(_stale_report(2))

            self.assertTrue(queued, "протухшие артефакты обязаны попасть в дайджест")
            doc = json.loads((tg_dir / push_policy.DIGEST_QUEUE_FILENAME).read_text())
            items = doc["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["event_key"], "artifact_freshness")
            self.assertEqual(items[0]["severity"], "WARNING")
            # тело несёт имена артефактов — иначе дайджест бесполезен
            self.assertIn("artifact_0", items[0]["body"])
            self.assertIn("producer_0", items[0]["body"])

    def test_healthy_report_queues_nothing(self):
        with TemporaryDirectory() as td:
            tg_dir = Path(td) / "telegram"
            tg_dir.mkdir(parents=True)
            from spa_core.telegram import push_policy

            with patch.object(push_policy, "_tg_dir", return_value=tg_dir):
                queued = af._alert_if_stale({"any_stale": False, "n_stale": 0, "stale": []})

            self.assertFalse(queued)
            self.assertFalse(
                (tg_dir / push_policy.DIGEST_QUEUE_FILENAME).exists(),
                "молчание при здоровых артефактах — не должно быть записей вовсе",
            )

    def test_repeated_runs_do_not_interrupt_the_owner(self):
        """Ключевое свойство: 5 прогонов подряд НЕ дают 5 пушей владельцу.

        Именно этим маршрут через дайджест отличается от прямого send_message:
        записи копятся в очереди и сворачиваются в одно daily-сообщение.
        """
        with TemporaryDirectory() as td:
            tg_dir = Path(td) / "telegram"
            tg_dir.mkdir(parents=True)
            from spa_core.telegram import push_policy

            with patch.object(push_policy, "_tg_dir", return_value=tg_dir), \
                 patch.object(push_policy, "_send") as fake_send:
                for _ in range(5):
                    af._alert_if_stale(_stale_report(1))

            fake_send.assert_not_called()  # ноль пушей за пять прогонов
            doc = json.loads((tg_dir / push_policy.DIGEST_QUEUE_FILENAME).read_text())
            self.assertEqual(len(doc["items"]), 5, "события не потеряны — они в очереди")

    def test_never_raises_when_the_route_is_broken(self):
        """Fail-safe: сломанный маршрут не имеет права уронить агента."""
        from spa_core.telegram import push_policy

        with patch.object(push_policy, "enqueue_digest", side_effect=RuntimeError("boom")):
            self.assertFalse(af._alert_if_stale(_stale_report(1)))


class TestAgentEntryPoint(unittest.TestCase):
    """run_agent() продолжает работать и после смены маршрута."""

    def test_run_agent_writes_report_and_routes_alert(self):
        with TemporaryDirectory() as td:
            calls: list = []
            with patch.object(af, "_alert_if_stale", side_effect=lambda r: calls.append(r) or True):
                report = af.run_agent(td)
            self.assertIn("any_stale", report)
            self.assertEqual(len(calls), 1, "агент обязан вызывать маршрут ровно один раз")
            self.assertTrue((Path(td) / af._REPORT_FILENAME).exists())


class TestCycleGapModuleStaysHermetic(unittest.TestCase):
    """Второй фронт того же коммита: заглушка из цикла #55 была снесена.

    `7ebe3e3a2` откатил `spa_core/tests/test_cycle_gap_monitor.py` к копии ДО
    цикла #55 и вместе с ней снёс `setUpModule()`, из-за которого ни один тест
    этого файла не мог достучаться до боевого Telegram. Именно тестовый прогон
    (а не прод-сторож) слал владельцу «🚨 Не удалось проверить, был ли сегодня
    цикл» — карточка `inbox-zadacha-razobratsya-i-popravit-vot-takoe`.

    Пин здесь — второй, независимый от `test_no_live_telegram_in_tests.py`:
    тот проверяет наличие ТЕКСТА, этот — что заглушка реально активна.
    """

    def test_module_level_stub_is_active(self):
        import spa_core.tests.test_cycle_gap_monitor as gapmod

        self.assertTrue(hasattr(gapmod, "setUpModule"))
        self.assertTrue(hasattr(gapmod, "tearDownModule"))
        from unittest.mock import MagicMock

        gapmod.setUpModule()
        try:
            from spa_core.paper_trading import cycle_gap_monitor as cgm
            # оба отправителя подменены ⇒ доставка физически недостижима
            self.assertFalse(
                cgm._send_telegram_alert("текст"),
                "заглушка обязана возвращать False ('ничего не отправлено')",
            )
            self.assertIsInstance(
                cgm._resolve_cycle_gap, MagicMock,
                "edge-triggered 'цикл восстановлен' тоже обязан быть подменён — "
                "именно он уходил владельцу на здоровом пути",
            )
        finally:
            gapmod.tearDownModule()

    def test_stub_is_released_after_teardown(self):
        """Заглушка не протекает на остальную батарею."""
        import spa_core.tests.test_cycle_gap_monitor as gapmod
        from spa_core.paper_trading import cycle_gap_monitor as cgm

        gapmod.setUpModule()
        gapmod.tearDownModule()
        self.assertFalse(
            hasattr(cgm._send_telegram_alert, "called"),
            "после tearDownModule боевая функция должна вернуться на место",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
