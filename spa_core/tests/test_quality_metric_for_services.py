"""Метрика качества для служб: доступность вместо свежести файла (решение владельца 29.08).

У 33 агентов из 95 метрики не было, и это НЕ 33 задачи, а один недостающий признак: чем
меряется служба, у которой продукт не файл. «Файл свежее N часов» подходит агенту, который
раз в такт пишет отчёт; демону, обёртке и headless-сессии — нет: у демона файла может не
быть неделями, и это норма.

Наше же правило это знало: расчёт срока годности для расписания `daemon` возвращает «такта
нет — срока не назначить». Оно честно говорило «свежесть тут не метрика», а замены не имело.

Владелец выбрал вариант 1 — по доступности. Источники уже существуют, строить нечего:
`data/agent_health.json` пишет по каждому агенту `loaded`, `pid`, `last_exit`.

Здесь закреплены обе стороны: метрика появляется там, где артефакта нет, и НЕ ПОДМЕНЯЕТ
метрику там, где артефакт есть.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_fap", _REPO / "scripts" / "fill_agent_passports.py")
fap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fap)


class ServiceWithoutAnArtifactGetsAvailability(unittest.TestCase):
    def test_daemon_is_measured_by_holding_a_process(self):
        m = fap.quality_metric_from_availability({"schedule": "daemon", "produces": []})
        self.assertIn("loaded=true", m)
        self.assertIn("pid≠0", m)

    def test_scheduled_one_shot_is_measured_by_exit_code(self):
        m = fap.quality_metric_from_availability(
            {"schedule": "calendar:08:00", "produces": []})
        self.assertIn("last_exit=0", m)
        self.assertIn("calendar:08:00", m, "метрика обязана называть КОНКРЕТНОЕ расписание")

    def test_it_names_a_source_that_actually_exists(self):
        """Метрика без читаемого источника — пожелание, а не метрика."""
        m = fap.quality_metric_from_availability({"schedule": "daemon", "produces": []})
        self.assertIn("data/agent_health.json", m)

    def test_no_schedule_means_no_metric(self):
        """Нет ни артефакта, ни расписания ⇒ мерить нечем. Пусто честнее выдумки."""
        self.assertEqual(fap.quality_metric_from_availability({"produces": []}), "")
        self.assertEqual(fap.quality_metric_from_availability({"schedule": "", "produces": []}), "")


class ItNeverReplacesTheFreshnessMetric(unittest.TestCase):
    """Обратная сторона, и она здесь главная: у агента с продуктом ничего не меняется."""

    ENTRY = {"schedule": "daemon",
             "produces": [{"artifact": "data/x.json", "slo_hours": 26}]}

    def test_availability_refuses_when_an_artifact_exists(self):
        self.assertEqual(fap.quality_metric_from_availability(self.ENTRY), "")

    def test_derive_keeps_the_freshness_metric_word_for_word(self):
        self.assertEqual(fap.derive(self.ENTRY)["quality_metric"],
                         fap.quality_metric_from_produces(self.ENTRY))
        self.assertIn("свежее 26 ч", fap.derive(self.ENTRY)["quality_metric"])

    def test_derive_falls_back_only_into_silence(self):
        entry = {"schedule": "daemon", "produces": []}
        self.assertEqual(fap.quality_metric_from_produces(entry), "")
        self.assertTrue(fap.derive(entry)["quality_metric"])


class TheProtectionDoesNotDependOnCallOrder(unittest.TestCase):
    """Мутация «перевернуть порядок источников» НЕ покраснела — и это правильно.

    Отказ стоит ВНУТРИ `quality_metric_from_availability`: она сама молчит, если у агента
    есть артефакт. Значит порядок вызова не несущий, и защита держится, даже если кто-то
    поменяет строки местами. Раз так — это надо утверждать, а не оставлять счастливой
    случайностью, которую следующая правка тихо отменит.
    """

    ENTRY = {"schedule": "daemon",
             "produces": [{"artifact": "data/x.json", "slo_hours": 26}]}

    def test_either_order_gives_the_freshness_metric(self):
        direct = (fap.quality_metric_from_produces(self.ENTRY)
                  or fap.quality_metric_from_availability(self.ENTRY))
        reversed_ = (fap.quality_metric_from_availability(self.ENTRY)
                     or fap.quality_metric_from_produces(self.ENTRY))
        self.assertEqual(direct, reversed_)
        self.assertIn("свежее 26 ч", reversed_)


class TheLiveFleetIsActuallyCovered(unittest.TestCase):
    """Замер, а не намерение: пробел по метрике был 33, стал 1."""

    def test_almost_every_agent_now_has_a_quality_metric(self):
        import json
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        without = [a["label"] for a in man["agents"]
                   if not (a.get("passport") or {}).get("quality_metric")]
        self.assertLessEqual(len(without), 2, f"метрики нет у {len(without)}: {without}")


if __name__ == "__main__":
    unittest.main()


class EscalationForServicesIsNamedNotLeftEmpty(unittest.TestCase):
    """У службы без артефакта эскалация не выводилась вовсе — 32 пустых поля (30.08).

    Пустое поле читается как «об отказе никто не узнает». Это неправда: `agent_health`
    проверяет загруженность в launchctl и код выхода и шлёт владельцу в Телеграм. Путь
    существует — значит его надо НАЗВАТЬ.

    Проверено по коду сторожа, а не предположено, и здесь это закреплено отдельным
    тестом: метрика, называющая несуществующий источник, хуже пустой.
    """

    SERVICE = {"schedule": "daemon", "produces": []}

    def test_service_escalation_names_agent_health(self):
        e = fap.escalation_from_code(None, self.SERVICE)
        self.assertIn("agent_health", e)
        self.assertIn("launchctl", e)
        self.assertIn("Телеграм", e)

    def test_the_named_watcher_really_watches_that(self):
        """Контроль самого утверждения: сторож обязан уметь то, что мы ему приписали."""
        src = (_REPO / "spa_core" / "monitoring" / "agent_health_monitor.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("not loaded into launchctl", src)
        self.assertIn("last_exit", src)
        self.assertIn("telegram", src.lower())

    def test_agent_with_an_artifact_keeps_the_freshness_escalation(self):
        """Обратная сторона: у кого есть продукт — прежний текст слово в слово."""
        entry = {"schedule": "daemon",
                 "produces": [{"artifact": "data/x.json", "slo_hours": 26}]}
        self.assertIn("протухший артефакт", fap.escalation_from_code(None, entry))

    def test_no_schedule_and_no_artifact_stays_empty(self):
        """Мерить нечем и звать некому ⇒ пусто честнее выдумки."""
        self.assertEqual(fap.escalation_from_code(None, {"produces": []}), "")

    def test_push_critical_still_wins(self):
        """Прямая эскалация важнее косвенной — и проверяется ТЕКСТОМ, а не «непусто».

        Первая редакция утверждала лишь `assertTrue(e)`, и мутация «перестать замечать
        push_critical» осталась зелёной: запасной источник тоже даёт непустой текст.
        Проверка «что-то вернулось» не отличает прямой путь от косвенного.
        """
        watchdog = _REPO / "spa_core" / "monitoring" / "watchdog.py"
        self.assertIn("push_critical", watchdog.read_text(encoding="utf-8", errors="replace"),
                      "образец сменился — тест стал бы проверять пустоту")
        entry = {"schedule": "daemon", "produces": []}
        real = fap._module_file
        try:
            fap._module_file = lambda _m: watchdog
            e = fap.escalation_from_code("spa_core.monitoring.watchdog", entry)
        finally:
            fap._module_file = real
        self.assertIn("push_policy", e)
        self.assertNotIn("agent_health", e, "прямая эскалация подменена косвенной")
