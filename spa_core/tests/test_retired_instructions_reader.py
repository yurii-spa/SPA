"""Снятое владельцем правило, оставшееся лежать в прод-дереве, обязано быть НАЗВАНО.

Карточка `inbox-u-novogo-polya-retired-instructions-net`, цикл #467.

**Предмет.** `git checkout <ref> -- <путь>` НЕ удаляет. Поэтому правило, которое
владелец снял на `origin`, продолжает лежать в прод-дереве и управлять агентами —
они читают `.claude/rules/` ПЕРЕД работой (CLAUDE.md §5). ADR-214 (цикл #458) научил
`code_sync_from_origin.sh` называть такие файлы полем `retired_instructions`
в `data/code_sync_status.json` — и на этом всё: **читателя у поля не было ни одного**.
Обязательный шаг 0-офис артефакт в свой набор не брал; `deployment_drift_monitor`
отвечает на другой вопрос. Писатель без потребителя — зеркало ADR-209.

**Население класса на день заведения читателя — НОЛЬ** (03.09: `CLAUDE.md` и все пять
`.claude/rules/*.md` в прод-дереве побайтово совпадают с origin). Поэтому здесь два
контроля, а не один: прямой (есть снятое ⇒ названо поимённо) и обратный (снятого нет
⇒ тишина). Без обратного «нечего называть» неотличимо от «называть разучились», и
читатель повторил бы ADR-209 с другой стороны.

Времени в тестах нет: `now` передаётся входом, отметки в данных относительны к нему.
"""
import ast
import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_office_under_test", _ROOT / "scripts" / "consume_office_reports.py")
office = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(office)

NAME = "code_sync_status.json"
# FROZEN-DATE-OK: injected-clock — приём #1 `.claude/rules/deployment.md`: часы здесь ВХОД,
# а не окружение. Литерал ровно один — якорь `NOW`, и он передаётся `now=NOW` в КАЖДЫЙ
# вызов, читающий время (`office._summarize_json`, `office._age_line`); все отметки фикстур
# выведены из него относительно (`NOW - timedelta(...)`). Обе стороны закреплены, поэтому
# календарь на вердикт не влияет. Заменить литерал на живые часы здесь НЕЛЬЗЯ: тогда откат
# кода к окружающим часам дал бы примерно те же возрасты и тест перестал бы быть
# положительным контролем на саму инъекцию. Пропущено при доставке #467, дописано #468.
NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def status(**over) -> dict:
    """Отчёт производителя; отметка времени — относительно `NOW`, не литерал."""
    base = {
        "timestamp": (NOW - dt.timedelta(minutes=6)).isoformat(),
        "generated_at": (NOW - dt.timedelta(minutes=6)).isoformat(),
        "result": "SYNCED",
        "detail": "whole-dir checkout + import probe OK",
        "origin_main": "da52d8ec7bd2454076b0f6901c187705e15189d0",
        "files_changed": 13,
        "exec_bits_fixed": 0,
        "retired_instructions": [],
        # Поле цикла #482 — в фикстуре с самого начала намеренно. Отчёт без него
        # производитель СЕГОДНЯ не пишет, и шаг 0-офис справедливо назвал бы такую
        # фикстуру «отчётом старого образца» (класс #248) — тест судил бы о своей
        # собственной устарелости, а не о читателе.
        "retired_code": [],
        "source": "code_sync_from_origin",
    }
    base.update(over)
    return base


def read(data) -> str:
    return "\n".join(office._summarize_json(NAME, data, now=NOW, root=str(_ROOT)))


class RetiredRuleIsNamed(unittest.TestCase):
    """ПРЯМОЙ контроль — ровно та авария, ради которой поле и заведено."""

    def test_a_retired_rule_is_named_by_path(self):
        out = read(status(retired_instructions=[".claude/rules/deployment.md"]))
        self.assertIn(".claude/rules/deployment.md", out)
        self.assertIn("🔴", out)

    def test_every_retired_file_is_named_not_just_counted(self):
        """Число вместо имён — та же слепота: чинить надо адресно."""
        files = [".claude/rules/adapters.md", "CLAUDE.md",
                 ".claude/rules/design-docs.md"]
        out = read(status(retired_instructions=files))
        for f in files:
            self.assertIn(f, out, f"{f} не назван поимённо")

    def test_the_line_says_who_may_remove_it(self):
        """Сторож НАЗЫВАЕТ; удаление из прод-дерева — действие владельца."""
        out = read(status(retired_instructions=["CLAUDE.md"]))
        self.assertIn("владельца", out)


class NothingRetiredIsSilence(unittest.TestCase):
    """ОБРАТНЫЙ контроль: без него «нечего называть» = «называть разучились»."""

    def test_empty_list_produces_no_finding(self):
        out = read(status(retired_instructions=[]))
        self.assertNotIn("🔴", out)
        self.assertIn("совпадает с origin", out)

    def test_missing_field_is_unmeasured_not_ok(self):
        """Поля нет ⇒ громкое «не измерено», а НЕ молчаливое «всё в порядке»."""
        data = status()
        del data["retired_instructions"]
        out = read(data)
        self.assertIn(office._UNMEASURED, out)
        self.assertNotIn("совпадает с origin", out)


class RetiredCodeIsNamed(unittest.TestCase):
    """То же самое про КОД — и здесь население класса НЕ ноль (цикл #482).

    Замер 04.09: дрейф прод-дерева = 13 файлов, и ВСЕ 13 на origin удалены
    осознанно (`retire(2/2)`, `cleanup: удалён мёртвый aggressive_lab`,
    `changelog: генератор в attic`). Отличие от инструкций не косметическое:
    снятое правило продолжает УПРАВЛЯТЬ агентами, а снятый код просто лежит —
    но именно он делал дрейф несводимым, и синк каждые 10 минут снимал архив
    всего кода (1300 архивов, 70 ГБ в /tmp при 55 ГБ свободных).
    """

    def test_retired_code_is_named_by_path(self):
        out = read(status(retired_code=["spa_core/strategy_lab/aggressive_lab_runner.py"]))
        self.assertIn("spa_core/strategy_lab/aggressive_lab_runner.py", out)
        self.assertIn("🔴", out)

    def test_every_retired_code_file_is_named_not_just_counted(self):
        files = ["scripts/day30_review.py", "tests/test_weekly_evidence_report.py",
                 "spa_core/alerts/daily_evidence_report.py"]
        out = read(status(retired_code=files))
        for f in files:
            self.assertIn(f, out, f"{f} не назван поимённо")

    def test_the_line_says_who_may_remove_it(self):
        out = read(status(retired_code=["scripts/day30_review.py"]))
        self.assertIn("владельца", out)

    def test_empty_list_produces_no_finding(self):
        """Обратный контроль: «нечего называть» ≠ «называть разучились»."""
        out = read(status(retired_code=[]))
        self.assertNotIn("🔴", out)
        self.assertIn("снятого кода нет", out)

    def test_missing_field_is_unmeasured_not_ok(self):
        """Поля нет ⇒ громкое «не измерено» (при упавшем fetch производитель шлёт `-`)."""
        data = status()
        del data["retired_code"]
        out = read(data)
        self.assertIn(office._UNMEASURED, out)
        self.assertNotIn("снятого кода нет", out)

    def test_the_two_classes_are_named_by_different_lines(self):
        """Одна строка на два предмета увела бы починку не туда."""
        out = read(status(retired_instructions=[".claude/rules/gone.md"],
                          retired_code=["scripts/gone.py"]))
        lines = [l for l in out.splitlines() if "🔴" in l]
        self.assertEqual(len(lines), 2, out)

class FailedSyncIsLoud(unittest.TestCase):
    """Неудавшаяся синхронизация — дерево работает на ПРЕЖНЕМ коде."""

    def test_failed_result_is_called_out(self):
        out = read(status(result="FETCH_FAILED",
                          detail="git fetch origin failed"))
        self.assertIn("НЕ удалась", out)

    def test_in_sync_is_not_a_failure(self):
        self.assertNotIn("НЕ удалась", read(status(result="IN_SYNC")))


class SchemaCheckWorksForAShellProducer(unittest.TestCase):
    """Производитель — скрипт; сверка схемы обязана быть НАСТОЯЩЕЙ, а не «не измерено»."""

    def test_producer_is_declared_and_is_the_shell_script(self):
        self.assertEqual(office._PRODUCER[NAME],
                         "scripts/code_sync_from_origin.sh")

    def test_keys_are_extracted_from_the_embedded_python(self):
        keys = office._source_keys(str(_ROOT / office._PRODUCER[NAME]))
        self.assertIsNotNone(keys, "у shell-производителя ключи не измерены вовсе")
        for declared in office._READ_SCHEMA[NAME]:
            self.assertIn(declared.split(".")[-1], keys,
                          f"объявлено к чтению `{declared}`, а производитель его не пишет")

    def test_a_plain_shell_producer_stays_honestly_unmeasured(self):
        """Граница названа: shell БЕЗ питон-heredoc ⇒ None, а не пустое множество.

        Пустое множество прочиталось бы как «производитель не пишет ни одного
        ключа» ⇒ ложное РАСХОЖДЕНИЕ по всем полям. `None` — «не измерено».
        """
        probe = _ROOT / "spa_core" / "tests" / "_tmp_plain_producer.sh"
        probe.write_text("#!/bin/bash\ncat <<'TXT'\nretired_instructions\nTXT\n",
                         encoding="utf-8")
        try:
            self.assertIsNone(office._source_keys(str(probe)))
        finally:
            probe.unlink()

    def test_python_behind_a_shell_variable_still_counts(self):
        """`"$PYTHON" - <<'PY'` — тот же запуск, что `python3 - <<'PY'`.

        Первая редакция признака искала слово `python` в самой строке запуска и
        объявляла НАСТОЯЩЕГО производителя неизмеримым: `code_sync_from_origin.sh`
        зовёт питон через переменную (`PYTHON=/…/python3`). Различать эти две
        записи значило бы судить о проводке по её орфографии.
        """
        probe = _ROOT / "spa_core" / "tests" / "_tmp_var_producer.sh"
        probe.write_text(
            "#!/bin/bash\nPYTHON=/usr/bin/python3\n"
            "\"$PYTHON\" - <<'PY'\nimport json\n"
            "json.dump({'retired_instructions': []}, open('/dev/null','w'))\nPY\n",
            encoding="utf-8")
        try:
            keys = office._source_keys(str(probe))
            self.assertIsNotNone(keys, "питон за переменной не распознан")
            self.assertIn("retired_instructions", keys)
        finally:
            probe.unlink()

    def test_a_non_python_variable_does_not_open_the_door(self):
        """Обратный контроль признака: переменная, не указывающая на питон, не считается."""
        probe = _ROOT / "spa_core" / "tests" / "_tmp_notpy_producer.sh"
        probe.write_text(
            "#!/bin/bash\nTOOL=/usr/bin/cat\n"
            "\"$TOOL\" <<'TXT'\nretired_instructions\nTXT\n",
            encoding="utf-8")
        try:
            self.assertIsNone(office._source_keys(str(probe)))
        finally:
            probe.unlink()

    def test_a_comment_mentioning_the_key_is_not_wiring(self):
        """Капкан #227: упоминание в комментарии — не запись ключа."""
        probe = _ROOT / "spa_core" / "tests" / "_tmp_comment_producer.sh"
        probe.write_text(
            "#!/bin/bash\n# retired_instructions — тут его как раз НЕТ\n"
            "python3 - <<'PY'\nimport json\njson.dump({'result': 'x'}, open('/dev/null','w'))\nPY\n",
            encoding="utf-8")
        try:
            keys = office._source_keys(str(probe))
            self.assertIsNotNone(keys)
            self.assertNotIn("retired_instructions", keys)
            self.assertIn("result", keys)
        finally:
            probe.unlink()


class DeclaredSchemaCoversWhatTheBranchReads(unittest.TestCase):
    """Объявление, которое можно сузить без единого красного теста, — не сторож.

    Замер мутациями #467: из семи подмен шесть краснели, а «сузить `_READ_SCHEMA`
    до одного поля» проходила ЗЕЛЁНОЙ. Это не мелочь: именно `_READ_SCHEMA` даёт
    шагу 0-офис строку «СХЕМА РАЗОШЛАСЬ» — то есть узкое объявление ослепляет
    проверку дрейфа производителя МОЛЧА, ровно как заниженная база храповика.
    Поэтому объявление сверяется не с самим собой, а с тем, что ветка РЕАЛЬНО
    читает у артефакта; измеряется разбором, а не перечислением руками.
    """

    @staticmethod
    def _fields_read_by_the_branch() -> set:
        src = (_ROOT / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        branch = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name) and test.left.id == "name"
                    and any(isinstance(c, ast.Constant) and c.value == NAME
                            for c in test.comparators)):
                branch = node.body
                break
        assert branch is not None, "ветки для этого артефакта в шаге 0-офис больше нет"
        read: set = set()
        for stmt in branch:
            for call in ast.walk(stmt):
                if not isinstance(call, ast.Call):
                    continue
                # data.get("поле")
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "get"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "data" and call.args
                        and isinstance(call.args[0], ast.Constant)):
                    read.add(call.args[0].value)
                # _num(data, "поле")
                if (isinstance(call.func, ast.Name) and call.func.id == "_num"
                        and len(call.args) == 2
                        and isinstance(call.args[0], ast.Name)
                        and call.args[0].id == "data"
                        and isinstance(call.args[1], ast.Constant)):
                    read.add(call.args[1].value)
        return read

    def test_every_field_the_branch_reads_is_declared(self):
        declared = {f.split(".")[-1] for f in office._READ_SCHEMA[NAME]}
        read = self._fields_read_by_the_branch()
        self.assertTrue(read, "ветка не читает у артефакта НИ ОДНОГО поля — замер сломан")
        undeclared = sorted(read - declared)
        self.assertFalse(
            undeclared,
            f"ветка читает {undeclared}, а `_READ_SCHEMA` о них молчит: дрейф "
            f"производителя по этим полям пройдёт МИМО строки «СХЕМА РАЗОШЛАСЬ»")

    def test_declaration_is_not_padded_with_fields_nobody_reads(self):
        """Обратная сторона: объявленное, но не читаемое — ложная строка расхождения."""
        declared = {f.split(".")[-1] for f in office._READ_SCHEMA[NAME]}
        read = self._fields_read_by_the_branch()
        # `timestamp` объявлен намеренно: это отметка ПРОИЗВОДИТЕЛЯ, её читает
        # общая ветка возраста, а не эта. Остальное обязано быть прочитано здесь.
        self.assertEqual(sorted(declared - read - {"timestamp"}), [])


class AgeIsMeasurableAtAll(unittest.TestCase):
    """`slo_hours` без измеримого возраста — украшение (класс необратимого «не измерено», #267).

    Первая печать ветки дала «возраст НЕ ИЗМЕРЕН: производитель не пишет
    generated_at» на отчёте, которому шесть минут: производитель называет своё
    время `timestamp`. Строка не могла стать измеренной НИ ПРИ КАКОМ состоянии
    системы, а объявленный в манифесте срок годности не работал бы вовсе —
    протухший артефакт был бы неотличим от свежего.
    """

    def test_the_age_line_uses_the_producers_own_field(self):
        line = office._age_line(
            (NOW - dt.timedelta(hours=3)).isoformat(), NOW,
            field=office._TS_FIELD[NAME])
        self.assertIn("возраст 3.0ч", line)
        self.assertNotIn(office._UNMEASURED.lower(), line.lower())

    def test_live_artifact_age_is_measured_not_refused(self):
        head = office._summarize_json(NAME, status(), now=NOW, root=str(_ROOT))[0]
        self.assertIn("возраст", head)
        self.assertNotIn("НЕ ИЗМЕРЕН", head)

    def test_ts_field_matches_producer(self):
        """Поле объявлено не на глаз: производитель обязан его писать."""
        keys = office._source_keys(str(_ROOT / office._PRODUCER[NAME]))
        self.assertIsNotNone(keys)
        self.assertIn(office._TS_FIELD[NAME], keys)

    def test_a_missing_timestamp_is_still_refused_loudly(self):
        """Обратный контроль: объявление не должно ПРЯТАТЬ настоящее отсутствие."""
        data = status()
        del data["timestamp"]
        head = office._summarize_json(NAME, data, now=NOW, root=str(_ROOT))[0]
        self.assertIn("НЕ ИЗМЕРЕН", head)
        self.assertIn("timestamp", head)

    def test_default_is_unchanged_for_everyone_else(self):
        """Артефакты без объявления продолжают читать `generated_at`."""
        self.assertEqual(office._produced_at("loop_health.json",
                                             {"generated_at": "x"}), "x")
        self.assertIsNone(office._produced_at("loop_health.json",
                                              {"timestamp": "x"}))


class TheReaderIsActuallyWiredIn(unittest.TestCase):
    """Ветка без места в наборе шага 0-офис не исполнится ни разу."""

    def test_manifest_declares_the_artifact_for_this_consumer(self):
        manifest = json.loads((_ROOT / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next((a for a in manifest["artifacts"]
                      if a["path"] == "data/code_sync_status.json"), None)
        self.assertIsNotNone(entry, "артефакта нет в манифесте — шаг его не возьмёт")
        self.assertEqual(entry["status"], "active")
        self.assertIn(office.CONSUMER, entry["consumers"])

    def test_the_artifact_has_a_shelf_life(self):
        """Без срока годности вносить нельзя: «давно не писали» стало бы невидимым."""
        manifest = json.loads((_ROOT / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next(a for a in manifest["artifacts"]
                     if a["path"] == "data/code_sync_status.json")
        self.assertIsInstance(entry.get("slo_hours"), (int, float))
        self.assertGreater(entry["slo_hours"], 0)


if __name__ == "__main__":
    unittest.main()
