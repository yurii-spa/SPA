#!/usr/bin/env python3
"""Тесты заполнения паспортов агентов (scripts/fill_agent_passports.py).

Каждый тест воспроизводит реальную поломку, найденную 2026-08-20 при первом
заполнении — проверка, не видевшая настоящей аварии, украшение
(`.claude/rules/deployment.md`).

  1. **Паспорт не переживал пересборку.** `scripts/build_architecture_manifest.py`
     копирует в новый манифест ТОЛЬКО поля из `MECHANICAL_FIELDS` и
     `CURATED_DEFAULTS`. `passport` там отсутствовал, поэтому 89 заполненных
     паспортов исчезли бы при первой же пересборке — молча, и следующая сессия
     решила бы, что «паспорта опять никто не заполнил».
  2. **Комментарий выдавался за модуль.** Почти каждая обёртка содержит строку
     «Generated from scripts/agent_template.sh (canonical bash-wrapper pattern)»,
     и наивный поиск возвращал модуль `(canonical bash` для сорока агентов.
     Цель тогда выводится из несуществующего файла — то есть пустая, но по
     неверной причине, и это невозможно было бы заметить.
  3. **Выдумывание.** Нет источника — поле обязано остаться ПУСТЫМ. Паспорт из
     правдоподобных фраз хуже пустого: он выглядит как знание.
  4. **Затирание человека.** Заполненное человеком поле ценнее выведенного.

Только stdlib, оффлайн: реальный `architecture/manifest.json` не изменяется.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPassportSurvivesRebuild(unittest.TestCase):
    """Авария 1 — самая дорогая: работа исчезает молча."""

    def test_curated_defaults_contain_passport(self):
        b = _load("_bam", "scripts/build_architecture_manifest.py")
        self.assertIn("passport", b.CURATED_DEFAULTS,
                      "passport вне CURATED_DEFAULTS — пересборка сотрёт паспорта")

    def test_filled_passport_survives_a_rebuild(self):
        """Мутация: убрать passport из CURATED_DEFAULTS — тест краснеет."""
        b = _load("_bam", "scripts/build_architecture_manifest.py")
        passport = {"goal": "цель", "quality_metric": "метрика", "escalation": "эскалация"}
        old = {"agents": [{"label": "com.spa.x", "curation": "complete",
                           "passport": passport}]}
        rebuilt = b.build(old, {}, {})
        entry = next(a for a in rebuilt["agents"] if a["label"] == "com.spa.x")
        self.assertEqual(entry.get("passport"), passport)

    def test_agent_without_passport_gets_empty_not_missing_key(self):
        b = _load("_bam", "scripts/build_architecture_manifest.py")
        rebuilt = b.build({"agents": [{"label": "com.spa.y"}]}, {}, {})
        entry = next(a for a in rebuilt["agents"] if a["label"] == "com.spa.y")
        self.assertEqual(entry.get("passport"), {})


class TestModuleExtraction(unittest.TestCase):
    """Авария 2: комментарий обёртки выдавался за имя модуля."""

    def test_comment_line_is_not_a_module(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        # Дословная строка из настоящих обёрток, на которой ломался наивный поиск
        wrapper = _REPO / "scripts" / "agent_agent_health.sh"
        if not wrapper.is_file():
            self.skipTest("обёртка отсутствует в этом дереве")
        mod = f.module_of("agent_agent_health.sh")
        self.assertIsNotNone(mod)
        self.assertNotIn("canonical", mod)
        self.assertTrue(mod.startswith("spa_core."), mod)

    def test_export_module_form_is_understood(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        mod = f.module_of("agent_artifact_freshness.sh")
        if mod is None:
            self.skipTest("обёртка отсутствует в этом дереве")
        self.assertEqual(mod, "spa_core.monitoring.artifact_freshness")


class TestNeverInvents(unittest.TestCase):
    """Авария 3: нет источника ⇒ поле ПУСТОЕ, а не правдоподобное."""

    def test_no_wrapper_means_no_goal(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.goal_from_docstring(None), "")
        self.assertEqual(f.goal_from_docstring("spa_core.__never_exists__"), "")

    def test_no_produces_means_no_metric(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.quality_metric_from_produces({"produces": []}), "")
        self.assertEqual(
            f.quality_metric_from_produces({"produces": [{"artifact": "data/a.json"}]}),
            "", "артефакт без SLO — не метрика качества")

    def test_metric_is_measurable_when_slo_present(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        got = f.quality_metric_from_produces(
            {"produces": [{"artifact": "data/a.json", "slo_hours": 3}]})
        self.assertIn("data/a.json", got)
        self.assertIn("3", got)

    def test_escalation_empty_without_any_evidence(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.escalation_from_code(None, {"produces": []}), "")


class TestDoesNotOverwriteHumans(unittest.TestCase):
    """Авария 4: выведенное затирало написанное человеком."""

    def test_existing_field_wins_over_derivation(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        entry = {"label": "com.spa.agent_health", "program": "agent_agent_health.sh",
                 "produces": [{"artifact": "data/x.json", "slo_hours": 3}],
                 "passport": {"goal": "НАПИСАНО ВЛАДЕЛЬЦЕМ"}}
        derived = f.derive(entry)
        existing = entry["passport"]
        merged = {k: (str(existing.get(k) or "").strip() or derived[k]) for k in f.FIELDS}
        self.assertEqual(merged["goal"], "НАПИСАНО ВЛАДЕЛЬЦЕМ")
        self.assertTrue(merged["quality_metric"], "остальные поля всё равно выводятся")


class TestRealManifestState(unittest.TestCase):
    """Замер на настоящем манифесте — чтобы прогресс был виден, а не заявлен."""

    def test_manifest_has_passports_and_reports_honestly(self):
        data = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        agents = data.get("agents", [])
        self.assertTrue(agents)
        full = sum(1 for a in agents
                   if all(str((a.get("passport") or {}).get(k) or "").strip()
                          for k in ("goal", "quality_metric", "escalation")))
        with_goal = sum(1 for a in agents
                        if str((a.get("passport") or {}).get("goal") or "").strip())
        # Было 0/89. Полностью заполнить механически нельзя — метрику качества
        # даёт только докурированный produces, и это работа куратора, не скрипта.
        self.assertGreater(full, 0, "паспортов не прибавилось")
        self.assertGreater(with_goal, full,
                           "частично заполненные обязаны существовать: "
                           "иначе кто-то дописал недостающее руками, выдумав")


class TestManifestFormatIsPreserved(unittest.TestCase):
    """Авария 5: запись переписывала ВЕСЬ манифест и калечила кириллицу.

    `atomic_save` по умолчанию пишет `indent=2` и `ensure_ascii=True`. Структура
    JSON при этом остаётся верной, поэтому НИ ОДИН существующий тест не краснел —
    а на диске 1946 строк превращались в 2391, дифф разрастался с ~270 строк до
    4331, и вся кириллица становилась `\\uXXXX` (96 строк там, где на origin ноль).
    Ревьюер такой дифф прочитать не может, а экранированный текст не читает никто.

    Формат задан РОВНО в одном месте — `dumps()` генератора манифеста. Эти тесты
    держат оба конца: сериализатор берётся оттуда, и результат на диске ему
    соответствует.
    """

    def _builder(self):
        return _load("_bam", "scripts/build_architecture_manifest.py")

    def test_fill_uses_the_canonical_serializer(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        sample = {"schema_version": 1, "agents": [
            {"label": "com.spa.x", "passport": {"goal": "цель по-русски"}}]}
        self.assertEqual(f._dumps(sample), self._builder().dumps(sample),
                         "формат манифеста определён дважды — он обязан быть один")

    def test_serializer_does_not_escape_cyrillic(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        out = f._dumps({"notes": "свежее 3 ч"})
        self.assertIn("свежее 3 ч", out)
        self.assertNotIn("\\u04", out)

    def test_serializer_keeps_one_space_indent(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        out = f._dumps({"schema_version": 1})
        self.assertTrue(out.splitlines()[1].startswith(' "schema_version"'),
                        f"отступ манифеста не канонический: {out.splitlines()[1]!r}")

    def test_manifest_on_disk_carries_no_escaped_cyrillic(self):
        """Замер на настоящем файле — регрессия видна сразу, а не в ревью."""
        text = (_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("\\u04", text,
                         "кириллица в манифесте экранирована — писали не тем сериализатором")

    def test_manifest_on_disk_is_byte_identical_to_a_reserialization(self):
        """Файл на диске обязан совпадать с тем, что даст канонический сериализатор."""
        path = _REPO / "architecture" / "manifest.json"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text, self._builder().dumps(json.loads(text)),
                         "манифест на диске записан не каноническим сериализатором")


if __name__ == "__main__":
    unittest.main()
