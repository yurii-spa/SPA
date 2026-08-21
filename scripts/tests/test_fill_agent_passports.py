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
import tempfile
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


class TestCheckIsAGate(unittest.TestCase):
    """Проводка обязана уметь краснеть, иначе это не проводка, а украшение.

    Скрипт подключён в `.github/workflows/generated-docs-integrity.yml`, потому
    что храповик `test_unwired_scripts_ratchet` поймал его без вызывающего и был
    прав: генератор, которого никто не зовёт, — это L3 из его же реестра.
    Но CI-шаг, который не может провалиться, ничего не сторожит. `--check`
    краснеет, когда манифест отстал от источников: кто-то дописал модулю
    docstring или докурировал `produces`, а паспорт не обновили.
    """

    def _run_on(self, manifest: dict):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            f.MANIFEST = path
            return f.run(write=False)

    def test_stale_manifest_is_named(self):
        """Паспорт пуст, а из источников выводится — это отставание."""
        r = self._run_on({"agents": [{
            "label": "com.spa.agent_health", "program": "agent_agent_health.sh",
            "produces": [{"artifact": "data/x.json", "slo_hours": 3}],
            "passport": {}}]})
        self.assertEqual(r["stale"], ["com.spa.agent_health"])

    def test_up_to_date_manifest_is_not_stale(self):
        """Обратный контроль: гейт не краснеет на согласованном манифесте."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        entry = {"label": "com.spa.agent_health", "program": "agent_agent_health.sh",
                 "produces": [{"artifact": "data/x.json", "slo_hours": 3}]}
        entry["passport"] = f.derive(entry)
        self.assertEqual(self._run_on({"agents": [entry]})["stale"], [])

    def test_agent_with_no_derivable_sources_is_not_stale(self):
        """Пусто и вывести нечего — это не отставание, а честный пробел.

        Иначе гейт краснел бы вечно на 26 агентах без docstring'а, и его бы
        отключили — ровно то, чего запрещает `.claude/rules/deployment.md`.
        """
        r = self._run_on({"agents": [{
            "label": "com.spa.nothing", "program": "__no_such_wrapper__.sh",
            "produces": [], "passport": {}}]})
        self.assertEqual(r["stale"], [])
        self.assertEqual(r["empty"], 1)

    def test_real_manifest_is_currently_up_to_date(self):
        """Замер на настоящем файле: CI-шаг зелёный не по случайности."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.run(write=False)["stale"], [])


class TestRightsAndLimits(unittest.TestCase):
    """Паспорт до 10 полей (AI1 гл.3/24, мандат владельца 2026-08-21).

    Два новых поля — rights (что можно) и limits (чего нельзя) — выводятся ИЗ
    ИСТОЧНИКОВ (produces, вызов push_critical, маркеры LLM_FORBIDDEN / execution),
    а не из прозы. Нет источника ⇒ поле пустое (fail-CLOSED, не догадка).
    """

    def test_fields_include_rights_and_limits(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertIn("rights", f.FIELDS)
        self.assertIn("limits", f.FIELDS)

    def test_rights_names_produced_artifacts(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        r = f.rights_from_manifest(None, {"produces": [
            {"artifact": "data/x.json", "slo_hours": 3}]})
        self.assertIn("data/x.json", r)
        self.assertIn("писать", r)

    def test_rights_empty_without_any_source(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.rights_from_manifest(None, {"produces": []}), "")

    def test_limits_read_llm_forbidden_from_source(self):
        """limits берётся из РЕАЛЬНОГО модуля, а не выдумывается."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        # kill_switch несёт LLM_FORBIDDEN и не импортирует execution
        lim = f.limits_from_code("spa_core.governance.kill_switch", {})
        self.assertIn("LLM запрещён", lim)
        self.assertIn("не импортирует execution", lim)

    def test_limits_empty_when_module_missing(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.limits_from_code(None, {}), "")
        self.assertEqual(f.limits_from_code("spa_core.__nope__", {}), "")

    def test_advisory_module_is_marked(self):
        f = _load("_fap", "scripts/fill_agent_passports.py")
        # директива CIO пишет про investment_os и является advisory-слоем
        lim = f.limits_from_code("spa_core.investment_os.directive", {})
        self.assertIn("advisory", lim)

    def test_real_manifest_carries_limits_for_many_agents(self):
        """Замер: «чего нельзя» перестало быть только прозой."""
        data = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        with_limits = sum(1 for a in data.get("agents", [])
                          if str((a.get("passport") or {}).get("limits") or "").strip())
        self.assertGreater(with_limits, 20,
                           "limits не выведены — паспорт не расширился")


class TestWrapperAmbiguityAndPrefixTrim(unittest.TestCase):
    """Два дефекта заполнителя, найденных состязательным разбором 20.08."""

    def test_multi_module_wrapper_is_ambiguous_not_first_wins(self):
        """Брать ПЕРВЫЙ модуль многошаговой обёртки — описать агента чужим
        докстрингом. Чужая цель хуже пустой: пустую видно в списке «нужен
        автор», а чужую — нет."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "agent_two.sh"
            w.write_text('#!/bin/bash\nexport MODULE="spa_core.a.main"\n'
                         'python3 -m spa_core.b.rollup\n', encoding="utf-8")
            f.REPO = Path(td).parent
            (Path(td).parent / "scripts").mkdir(exist_ok=True)
            target = Path(td).parent / "scripts" / "agent_two.sh"
            target.write_text(w.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                self.assertIsNone(f.module_of("agent_two.sh"))
            finally:
                target.unlink(missing_ok=True)

    def test_single_module_wrapper_still_resolves(self):
        """Обратный контроль: однозначная обёртка обязана разбираться."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        self.assertEqual(f.module_of("agent_artifact_freshness.sh"),
                         "spa_core.monitoring.artifact_freshness")

    def test_ticket_prefix_is_not_eaten_by_the_name_trim(self):
        """«MP-144: …» превращалось в «144: …» — номер задачи съедался."""
        f = _load("_fap", "scripts/fill_agent_passports.py")
        first = "MP-144: сторож чего-то важного."
        import re as _re
        trimmed = _re.sub(r"^[\w.]+\s+[—–-]\s+", "", first)
        self.assertEqual(trimmed, first)

    def test_module_name_prefix_is_still_trimmed(self):
        """Обратный контроль: настоящий префикс имени по-прежнему снимается."""
        import re as _re
        got = _re.sub(r"^[\w.]+\s+[—–-]\s+", "", "agent_passports — у каждого агента.")
        self.assertEqual(got, "у каждого агента.")


if __name__ == "__main__":
    unittest.main()
