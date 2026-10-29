"""Число свободного места обязано доезжать до ФАЙЛОВОЙ поверхности сессии (ADR-858).

Каждый тест здесь — положительный контроль аварии 2026-10-29, а не украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Что произошло в тот день. `com.spa.resource_guard` отработал БЕЗУПРЕЧНО: каждые
пять минут мерил и выходил кодом 2 (его вердикт CRITICAL), называя число —
«disk 4.8 GB free», затем 4.4, 3.4, 2.6 — и запушил владельцу в Telegram
(`push_state.resource_critical.entry_pushed=true`). А в `docs/SYSTEM_BRIEFING.md`,
который `CLAUDE.md` §1 предписывает читать КАЖДОЙ сессии и без которого нельзя
утверждать «всё работает», от этой аварии стояла ровно одна строка:

    - ⚠️ `com.spa.resource_guard` — last_exit=2

неотличимая по форме от соседней `com.spa.site_freshness — last_exit=1`. Числа
не было ВОВСЕ. Сессия читала `Portfolio ✅`, `Resilience ✅ OK` и два одинаковых
предупреждения, пока машине оставалось 2.6 ГБ.

Поэтому проверяется не «есть ли функция», а ИСХОД: несёт ли документ ЧИСЛО.
Отрицательный контроль (`test_the_old_surface_carried_no_number`) воспроизводит
дословную прежнюю строку и обязан показать, что по ней вопрос неразрешим.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "update_system_briefing.py"


def _load():
    spec = importlib.util.spec_from_file_location("ub_adr857", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# FROZEN-DATE-OK: injected-clock — якорь `NOW` подаётся в `resource_state(doc, now=NOW)`
# аргументом, И отметка сцены (`generated_at`) выводится из ТОГО ЖЕ якоря
# (`NOW - timedelta(hours=age_h)`). Закреплены ОБЕ стороны, поэтому вердикт не
# зависит от календаря: сдвиньте дату прогона на год — ни один тест не дрогнет.
#: Сцена аварии. Время — ВХОД, а не окружение. Литерал здесь ЕСТЬ, и он назван
#: выше: прежняя редакция этого комментария утверждала, что литерала «нет вовсе»,
#: и была неверна — храповик замороженных дат поймал её сразу (цикл #975).
NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def scene(*, free_gb=2.6, state="CRITICAL", age_h=0.05) -> dict:
    return {
        "schema": "resource-health/1",
        "generated_at": (NOW - timedelta(hours=age_h)).isoformat().replace(
            "+00:00", "Z"),
        "overall": state,
        "disk": {"state": state, "volume": "/System/Volumes/Data",
                 "free_gb": free_gb, "total_gb": 460.4,
                 "warn_free_gb": 40, "critical_free_gb": 15},
        "memory": {"state": "WARN", "pressure_level": 1,
                   "swap": {"used_pct": 93.3}},
    }


class ResourceNumberReachesTheFileSurface(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    # ── положительные контроли: дословная авария 29.10 ────────────────────────
    def test_the_incident_scene_names_the_number_in_the_header_cell(self):
        """2.6 ГБ обязаны быть ВИДНЫ там, где сессия смотрит первым делом."""
        cell = self.m.resource_header_cell(
            self.m.resource_state(scene(), now=NOW))
        self.assertIn("2.6", cell)
        self.assertIn("🔴", cell)
        self.assertIn("CRITICAL", cell)

    def test_the_incident_scene_names_the_number_in_the_section(self):
        st = self.m.resource_state(scene(), now=NOW)
        # Секция собирается из того же состояния, что и ячейка.
        self.assertTrue(st["measured"])
        self.assertEqual(st["free_gb"], 2.6)
        self.assertEqual(st["state"], "CRITICAL")

    def test_exit_code_two_is_named_a_verdict_not_a_malfunction(self):
        """Суть ADR-858: отличить «агент сломался» от «агент докладывает аварию».

        На КРИТИЧЕСКОЙ сцене документ обязан сказать это вслух — иначе читатель
        вернётся к прежнему прочтению `last_exit=2` как нездоровья агента.
        """
        self.m.DATA_DIR = self._data_dir_with(scene())
        text = self.m.build_resource_section()
        self.assertIn("ВЕРДИКТ", text)
        self.assertIn("2.6", text)

    # ── третий исход ЗНАЧЕНИЕМ (инв. #17), и он НЕ «чисто» ────────────────────
    def test_a_missing_artifact_is_a_named_third_outcome_never_ok(self):
        st = self.m.resource_state({}, now=NOW)
        self.assertFalse(st["measured"])
        self.assertEqual(st["state"], self.m.RESOURCE_UNMEASURED)
        cell = self.m.resource_header_cell(st)
        self.assertIn("НЕ ИЗМЕРЕНО", cell)
        self.assertNotIn("✅", cell)
        self.assertTrue(st["reason"], "причина обязана быть НАЗВАНА")

    def test_absent_number_is_never_substituted_by_zero(self):
        """`free_gb` нет ⇒ НЕ ИЗМЕРЕНО. Ноль здесь означал бы «диск полон» —
        аварию, ПРОТИВОПОЛОЖНУЮ по смыслу молчанию прибора."""
        st = self.m.resource_state({"disk": {"state": "OK"}}, now=NOW)
        self.assertFalse(st["measured"])
        cell = self.m.resource_header_cell(st)
        self.assertNotIn("0.0", cell)
        self.assertIn("инв. #17", cell)

    def test_absent_verdict_is_not_recomputed_from_the_number_here(self):
        """Порог живёт у производителя. Пересчитать его здесь значило бы завести
        ВТОРОЕ место для порога (урок `.claude/rules/site-numbers.md`)."""
        doc = scene()
        del doc["disk"]["state"]
        st = self.m.resource_state(doc, now=NOW)
        self.assertFalse(st["measured"])
        # Число при этом не теряется — оно просто не делает вердикта.
        self.assertEqual(st["free_gb"], 2.6)

    def test_a_false_number_type_is_not_accepted_as_a_measurement(self):
        for bad in (None, "2.6", True, [], {}):
            with self.subTest(bad=bad):
                doc = scene()
                doc["disk"]["free_gb"] = bad
                self.assertFalse(
                    self.m.resource_state(doc, now=NOW)["measured"])

    # ── свежесть: «последнее известное» ≠ «сейчас» ────────────────────────────
    def test_a_stale_measurement_is_labelled_last_known_not_now(self):
        st = self.m.resource_state(
            scene(age_h=self.m.RESOURCE_STALE_H + 2.0), now=NOW)
        self.assertTrue(st["measured"])
        self.assertTrue(st["stale"])
        self.assertIn("последнее известное", self.m.resource_header_cell(st))

    def test_an_unparsable_timestamp_is_stale_with_a_named_reason(self):
        """Возраст НЕ ИЗМЕРЕН — это тоже не «свежо»."""
        doc = scene()
        doc["generated_at"] = "никакая-не-дата"
        st = self.m.resource_state(doc, now=NOW)
        self.assertTrue(st["stale"])
        self.assertTrue(st["stale_reason"])

    def test_a_fresh_measurement_is_not_labelled_stale(self):
        st = self.m.resource_state(scene(age_h=0.05), now=NOW)
        self.assertFalse(st["stale"])
        self.assertNotIn("последнее известное",
                         self.m.resource_header_cell(st))

    def test_a_healthy_scene_is_green_and_still_carries_the_number(self):
        st = self.m.resource_state(
            scene(free_gb=120.5, state="OK"), now=NOW)
        cell = self.m.resource_header_cell(st)
        self.assertIn("✅", cell)
        self.assertIn("120.5", cell)

    # ── две поверхности не могут разойтись (урок F9/#197) ─────────────────────
    def test_cell_and_section_read_the_same_state(self):
        doc = scene(free_gb=7.3, state="CRITICAL")
        self.m.DATA_DIR = self._data_dir_with(doc)
        section = self.m.build_resource_section()
        cell = self.m.resource_header_cell(self.m.resource_state(doc, now=NOW))
        for surface in (section, cell):
            self.assertIn("7.3", surface)
            self.assertIn("CRITICAL", surface)

    # ── ПРОВОДКА: гоняем настоящий main(), а не грепаем имя функции ───────────
    def test_the_generated_document_carries_the_number(self):
        """ADR-835: путь тест-файла проводкой не является — проводку надо ГНАТЬ.

        Снимаем документ целиком настоящим `main()` и спрашиваем ИСХОД: несёт ли
        он число. Снять проводку (убрать секцию или ячейку) ⇒ тест краснеет.
        """
        doc = scene(free_gb=3.4, state="CRITICAL")
        with tempfile.TemporaryDirectory() as tmp:
            self.m.DATA_DIR = self._data_dir_with(doc, root=tmp)
            self.m.DOCS_DIR = tmp
            self.m.OUTPUT = os.path.join(tmp, "SYSTEM_BRIEFING.md")
            self.m.main()
            text = Path(self.m.OUTPUT).read_text(encoding="utf-8")
        self.assertIn("3.4 ГБ", text, "число свободного места не доехало до документа")
        # ДВЕ поверхности — ДВА требования. Замер мутациями 29.10: проверка
        # «число есть в документе» ОДНА пропускала снятие секции, потому что то
        # же число стоит в ячейке сводки. Выживший мутант был настоящей дырой, а
        # не эквивалентным (`survived-mutant-may-be-equivalent-not-a-gap`):
        # ячейка и секция отвечают на РАЗНЫЕ вопросы — «сколько осталось» в
        # сводке и «почему код выхода 2 есть вердикт» в секции.
        self.assertIn("Диск · память", text, "ячейки сводки нет в таблице")
        self.assertIn("## 💽 Ресурсы машины", text,
                      "секции нет в документе: снятие проводки прошло бы молча")
        self.assertIn("пороги производителя", text,
                      "секция есть, но без порогов — читатель не знает, с чем "
                      "сравнивать число")

    # ── ОТРИЦАТЕЛЬНЫЙ контроль: прежняя поверхность ───────────────────────────
    def test_the_old_surface_carried_no_number(self):
        """Дословная строка брифинга ДО ADR-858 — и по ней вопрос неразрешим.

        Это и есть доказательство, что проверка выше ловит НАСТОЯЩУЮ поломку, а
        не свою же формулировку: прежняя форма не отличает аварию диска от
        рядового предупреждения соседа.
        """
        before_incident = "- ⚠️ `com.spa.site_freshness` — last_exit=1"
        during_incident = "- ⚠️ `com.spa.resource_guard` — last_exit=2"
        for line in (before_incident, during_incident):
            self.assertNotIn("2.6", line)
            self.assertNotIn("ГБ", line)
        # Две строки отличаются ТОЛЬКО именем агента и цифрой кода выхода —
        # величины, по которой судят об аварии, в них нет ни в одной.
        self.assertEqual(
            before_incident.replace("site_freshness", "X").replace("1", "N"),
            during_incident.replace("resource_guard", "X").replace("2", "N"))

    # ── вспомогательное ──────────────────────────────────────────────────────
    def _data_dir_with(self, doc: dict, *, root: str | None = None) -> str:
        root = root or tempfile.mkdtemp()
        data = os.path.join(root, "data")
        os.makedirs(data, exist_ok=True)
        with open(os.path.join(data, "resource_health.json"), "w",
                  encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        return data


if __name__ == "__main__":
    unittest.main()
