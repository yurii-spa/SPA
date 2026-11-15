#!/usr/bin/env python3
"""Контроли прибора перемера класса «вывод прежней редакции» (ADR-1022).

Каждый тест — положительный контроль одного звена: он краснеет, если это звено
порвать. Предмет прибора — ЖИВЁТ ли напечатанная находка на сегодняшнем
производителе, и у вопроса ровно три исхода (инв. #17), поэтому у каждого исхода
здесь своя сцена, а у пары «подтвердилась/разошлась» — сцены, отличающиеся
РОВНО набором находок.

Времени и личности процесса в сценах нет: момент замера у прибора — ВХОД
(`--now`), а живость снятого прогона прибор спрашивает у СВОЕГО pid, не у
литерала (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Литеральной даты
в файле нет ни одной.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import tempfile
import textwrap
import unittest
import unittest.mock
from pathlib import Path

from spa_core.monitoring import edition_remeasure as er
from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT

ART = "scene_artifact.json"


def _producer_script(body: str) -> str:
    """Текст одноразового производителя: пишет `data/<ART>` и ничего больше."""
    return textwrap.dedent(f"""\
        import json, sys, pathlib
        data = pathlib.Path(sys.argv[1])
        data.mkdir(parents=True, exist_ok=True)
        findings = {body}
        (data / {ART!r}).write_text(json.dumps({{"findings": findings}}),
                                    encoding="utf-8")
        """)


class Scene:
    """Одноразовая сцена: корень песочницы, каталог прода и производитель."""

    def __init__(self, stack: unittest.TestCase, *, printed, produced, sleep=None):
        tmp = tempfile.TemporaryDirectory()
        stack.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.prod = self.base / "prod_data"
        self.root = self.base / "sandbox"
        (self.root / "data").mkdir(parents=True)
        self.prod.mkdir()
        (self.prod / ART).write_text(json.dumps({"findings": printed}),
                                     encoding="utf-8")
        script = self.root / "producer.py"
        if sleep is None:
            script.write_text(_producer_script(repr(produced)), encoding="utf-8")
        else:
            # Долгий производитель: предмет — БЮДЖЕТ, поэтому он именно спит, а
            # не считает; запись делает ПОСЛЕ сна, чтобы «снят по бюджету» и
            # «записал» не могли случиться оба.
            script.write_text(
                f"import time, sys\ntime.sleep({sleep})\n"
                + _producer_script(repr(produced)), encoding="utf-8")
        self.entry = er.Entry(("{root}/producer.py", "{data}"))


class ProdRootDoor(unittest.TestCase):
    """Перемер, пишущий в прод, уничтожает предмет замера ДО сравнения."""

    def test_the_prod_tree_itself_is_refused(self):
        with self.assertRaises(er.Refused) as ctx:
            er.refuse_prod_root(DEFAULT_LIVE_ROOT)
        self.assertIn(str(DEFAULT_LIVE_ROOT.resolve()), str(ctx.exception))

    def test_a_descendant_of_the_prod_tree_is_refused(self):
        """Умолчание пушера учит: потомок прод-дерева — тот же прод."""
        with self.assertRaises(er.Refused):
            er.refuse_prod_root(DEFAULT_LIVE_ROOT / "data" / "sandbox")

    def test_a_foreign_tree_passes(self):
        """Обратная сторона контроля: правильно собранная песочница проходит."""
        with tempfile.TemporaryDirectory() as tmp:
            er.refuse_prod_root(Path(tmp))  # не поднимает

    def test_run_refuses_before_touching_anything(self):
        with self.assertRaises(er.Refused):
            er.run(prod_data=DEFAULT_LIVE_ROOT / "data",
                   sandbox_root=DEFAULT_LIVE_ROOT, only=[ART])


class FindingKeysForm(unittest.TestCase):
    """Сравнить набор нечем — это ИСХОД с причиной, а не пустой набор."""

    def test_a_normal_findings_list_is_comparable(self):
        keys, why = er.finding_keys(
            {"findings": [{"severity": "CRITICAL", "message": "раз"},
                           {"severity": "WARN", "message": "два"}]})
        self.assertIsNone(why)
        self.assertEqual(len(keys), 2)

    def test_order_of_findings_is_not_a_difference(self):
        """Производитель вправе переставить находки — это не «набор разошёлся»."""
        a, _ = er.finding_keys({"findings": [{"message": "раз"}, {"message": "два"}]})
        b, _ = er.finding_keys({"findings": [{"message": "два"}, {"message": "раз"}]})
        self.assertEqual(a, b)

    def test_text_is_compared_whole_not_truncated(self):
        """Две находки с общим началом — ДВЕ, иначе «ушла одна» стало бы «набор тот же»."""
        head = "ю" * 300
        keys, why = er.finding_keys(
            {"findings": [{"message": head + "раз"}, {"message": head + "два"}]})
        self.assertIsNone(why)
        self.assertEqual(len(set(keys)), 2)

    def test_absent_findings_field_is_a_named_reason(self):
        keys, why = er.finding_keys({"counts": {}})
        self.assertIsNone(keys)
        self.assertIn("findings", why)

    def test_findings_of_the_wrong_shape_is_a_named_reason(self):
        keys, why = er.finding_keys({"findings": {"a": 1}})
        self.assertIsNone(keys)
        self.assertIn("не список", why)

    def test_a_finding_without_any_declared_text_field_is_a_named_reason(self):
        keys, why = er.finding_keys({"findings": [{"severity": "WARN", "где": "тут"}]})
        self.assertIsNone(keys)
        self.assertIn("ни одного из объявленных полей", why)

    def test_a_non_dict_artifact_is_a_named_reason(self):
        keys, why = er.finding_keys([1, 2, 3])
        self.assertIsNone(keys)
        self.assertIn("не словарь", why)


class ThreeOutcomes(unittest.TestCase):
    """Три исхода на сценах, отличающихся РОВНО предметом вопроса."""

    def _measure(self, scene, **kw):
        patched = dict(er.ENTRY)
        patched[ART] = kw.pop("entry", scene.entry)
        self.enterContext(unittest.mock.patch.object(er, "ENTRY", patched))
        return er.remeasure_one(ART, prod_data=scene.prod,
                                sandbox_root=scene.root, **kw)

    def test_the_same_set_confirms_the_printed_finding(self):
        printed = [{"severity": "CRITICAL", "message": "дверь открыта"}]
        scene = Scene(self, printed=printed, produced=printed)
        o = self._measure(scene)
        self.assertEqual(o.kind, er.CONFIRMED, o.reason)
        self.assertEqual((o.before, o.after), (1, 1))
        self.assertEqual((o.gone, o.arrived), ((), ()))

    def test_a_vanished_finding_is_CHANGED_and_named(self):
        """Та же сцена, отличие РОВНО одно: производитель находку больше не выносит."""
        scene = Scene(self, printed=[{"severity": "CRITICAL", "message": "дверь открыта"}],
                      produced=[])
        o = self._measure(scene)
        self.assertEqual(o.kind, er.CHANGED, o.reason)
        self.assertEqual((o.before, o.after), (1, 0))
        self.assertEqual(len(o.gone), 1)
        self.assertIn("дверь открыта", o.gone[0])

    def test_a_new_finding_is_CHANGED_too(self):
        """Расхождение двустороннее: «пришло» — такой же сдвиг, как «ушло»."""
        scene = Scene(self, printed=[], produced=[{"severity": "WARN", "message": "новая"}])
        o = self._measure(scene)
        self.assertEqual(o.kind, er.CHANGED, o.reason)
        self.assertEqual(len(o.arrived), 1)

    def test_a_member_outside_the_table_is_UNMEASURED(self):
        """fail-CLOSED: необъявленный вход — не «подтвердилась», а третий исход."""
        scene = Scene(self, printed=[], produced=[])
        with unittest.mock.patch.object(er, "ENTRY", {}):
            o = er.remeasure_one(ART, prod_data=scene.prod, sandbox_root=scene.root)
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("НЕ ОБЪЯВЛЕНО", o.reason)

    def test_a_declared_refusal_is_UNMEASURED_with_that_reason(self):
        scene = Scene(self, printed=[], produced=[])
        o = self._measure(scene, entry=er.Entry(refusal="внешнее действие, а не замер"))
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("внешнее действие", o.reason)

    def test_a_producer_that_writes_nothing_is_UNMEASURED_not_CONFIRMED(self):
        """Вход, не перенаправивший запись, — ровно то состояние, которого боимся:
        артефакт песочницы не обновился, значит прод МОГ быть тронут."""
        scene = Scene(self, printed=[{"message": "раз"}], produced=[])
        quiet = scene.root / "quiet.py"
        quiet.write_text("import sys\n", encoding="utf-8")
        o = self._measure(scene, entry=er.Entry(("{root}/quiet.py", "{data}")))
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("НЕ ОБНОВИЛСЯ", o.reason)

    def test_an_unreadable_printed_artifact_is_UNMEASURED(self):
        scene = Scene(self, printed=[], produced=[])
        (scene.prod / ART).unlink()
        o = self._measure(scene)
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("не прочитан", o.reason)


class BudgetIsMeasuredNotAssumed(unittest.TestCase):
    """«Прошло больше предела» снятием НЕ является (замер #1159: 8 мин 41 с под `timeout 240`)."""

    def test_an_overlong_run_is_UNMEASURED_and_the_process_is_actually_dead(self):
        scene = Scene(self, printed=[{"message": "раз"}], produced=[], sleep=60)
        patched = dict(er.ENTRY)
        patched[ART] = scene.entry
        with unittest.mock.patch.object(er, "ENTRY", patched):
            o = er.remeasure_one(ART, prod_data=scene.prod,
                                 sandbox_root=scene.root, budget_s=1.0)
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("бюджет", o.reason)
        # Живость спрашивается у СВОЕГО дерева сцены, а не у литерального номера:
        # сцена сама себе положительный контроль — её скрипт уникален по пути.
        alive = subprocess.run(
            ["ps", "-eo", "command="], capture_output=True, text=True).stdout
        self.assertNotIn(str(scene.root / "producer.py"), alive,
                         "снятый по бюджету прогон ПЕРЕЖИЛ снятие — вердикт о "
                         "нём был бы о живом процессе")

    def test_a_run_inside_the_budget_is_judged_normally(self):
        """Обратная сторона: бюджет не должен краснить нормальный прогон."""
        printed = [{"message": "раз"}]
        scene = Scene(self, printed=printed, produced=printed)
        patched = dict(er.ENTRY)
        patched[ART] = scene.entry
        with unittest.mock.patch.object(er, "ENTRY", patched):
            o = er.remeasure_one(ART, prod_data=scene.prod,
                                 sandbox_root=scene.root, budget_s=120.0)
        self.assertEqual(o.kind, er.CONFIRMED, o.reason)


class PrintNamesItsRemainder(unittest.TestCase):
    """Урок ADR-1021: печать, назвавшая меньше, чем содержит замер, обязана
    объявить остаток ЧИСЛОМ, а `--all` обязан называть всех."""

    def _census(self, n):
        c = er.Census(sandbox_root="/tmp/scene")
        for i in range(n):
            c.outcomes.append(er.Outcome(er.CHANGED, f"a{i}.json", before=1, after=0))
        return c

    def test_the_default_limit_declares_the_remainder_as_a_number(self):
        lines = er.report(self._census(20), max_rows=12)
        self.assertTrue(any("ещё 8" in s for s in lines), lines[-3:])

    def test_all_names_everyone(self):
        lines = er.report(self._census(20), max_rows=None)
        named = [s for s in lines if "a19.json" in s]
        self.assertEqual(len(named), 1)
        self.assertFalse(any("ещё" in s for s in lines))

    def test_counts_are_printed_for_every_kind(self):
        c = self._census(1)
        c.outcomes.append(er.Outcome(er.UNMEASURED, "b.json", reason="причина"))
        c.outcomes.append(er.Outcome(er.CONFIRMED, "c.json", before=2, after=2))
        head = "\n".join(er.report(c))
        for label in ("ПОДТВЕРДИЛАСЬ: 1", "РАЗОШЁЛСЯ: 1", "НЕ ИЗМЕРЕНО: 1"):
            self.assertIn(label, head)

    def test_an_unmeasured_census_prints_its_cause_and_nothing_else(self):
        lines = er.report(er.Census(reason="редакция НЕ ИЗМЕРЕНА: клон усечён"))
        self.assertEqual(len(lines), 1)
        self.assertIn("клон усечён", lines[0])


class LongRunIsVisible(unittest.TestCase):
    """Молчащий лог делает «работает» и «умер» НЕРАЗЛИЧИМЫМИ (авария #906).

    Прибор поднимает по подпроцессу на члена, и такт класса идёт десятками
    минут — поэтому ход обязан печататься, и печататься В ``stderr`` без
    буфера, чтобы файл лога РОС.
    """

    def _run(self, **kw):
        printed = [{"message": "раз"}]
        scene = Scene(self, printed=printed, produced=printed)
        patched = dict(er.ENTRY)
        patched[ART] = scene.entry
        import contextlib
        import io
        buf = io.StringIO()
        with unittest.mock.patch.object(er, "ENTRY", patched), \
                contextlib.redirect_stderr(buf):
            c = er.run(prod_data=scene.prod, sandbox_root=scene.root,
                       only=[ART], **kw)
        return c, buf.getvalue()

    def test_progress_names_the_member_before_and_after_its_run(self):
        c, err = self._run(progress=True)
        self.assertEqual(c.outcomes[0].kind, er.CONFIRMED, c.outcomes[0].reason)
        self.assertEqual(err.count("[перемер] 1/1"), 2, err)
        self.assertIn(ART, err)
        self.assertIn(er.CONFIRMED, err)

    def test_a_library_call_writes_nothing_by_default(self):
        """Обратная сторона: библиотека не вправе писать в чужой поток."""
        _, err = self._run()
        self.assertEqual(err, "")


class CliContract(unittest.TestCase):
    """Код возврата различает три исхода, а неразобранный вход — ОТКАЗ, не часы."""

    def test_an_unparsable_now_refuses_with_code_2(self):
        """Сцена подобрана так, что БЕЗ отказа код был бы 0: иначе «2» пришла бы
        от третьего исхода члена, и тест проходил бы по ЧУЖОЙ причине — замер
        отвечал бы на свой вопрос вместо нужного."""
        import contextlib
        import io
        printed = [{"message": "раз"}]
        scene = Scene(self, printed=printed, produced=printed)
        patched = dict(er.ENTRY)
        patched[ART] = scene.entry
        buf = io.StringIO()
        with unittest.mock.patch.object(er, "ENTRY", patched), \
                contextlib.redirect_stderr(buf):
            ok = er.main(["--sandbox-root", str(scene.root), "--only", ART,
                          "--data-dir", str(scene.prod), "--quiet"])
            bad = er.main(["--sandbox-root", str(scene.root), "--only", ART,
                           "--data-dir", str(scene.prod), "--quiet",
                           "--now", "вчера"])
        self.assertEqual(ok, 0, "сцена обязана давать 0 без мутации входа")
        self.assertEqual(bad, 2)
        self.assertIn("--now не разобран", buf.getvalue())

    def test_a_prod_sandbox_root_refuses_with_code_2(self):
        rc = er.main(["--sandbox-root", str(DEFAULT_LIVE_ROOT), "--only", ART])
        self.assertEqual(rc, 2)

    def test_now_is_an_input_and_reaches_the_report(self):
        printed = [{"message": "раз"}]
        scene = Scene(self, printed=printed, produced=printed)
        patched = dict(er.ENTRY)
        patched[ART] = scene.entry
        # Якорь ВЫЧИСЛЕН, а не вписан: литеральная дата в тесте — бомба от
        # календаря (`.claude/rules/deployment.md` § «ВРЕМЯ В ТЕСТАХ»), а здесь
        # она и не нужна — обе стороны сравнения происходят от ОДНОГО объекта,
        # поэтому тест бессмертен и без пометки на протоколе.
        moment = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        with unittest.mock.patch.object(er, "ENTRY", patched):
            c = er.run(prod_data=scene.prod, sandbox_root=scene.root, only=[ART],
                       now=moment)
        self.assertEqual(c.generated_at, moment.isoformat())


class TableIsClosedAndNamesTheClass(unittest.TestCase):
    """Таблица входов — объявление, и её контракт принадлежит ЕЙ, а не вызову."""

    def test_every_entry_either_runs_or_names_its_refusal(self):
        for name, entry in er.ENTRY.items():
            with self.subTest(name):
                self.assertTrue(bool(entry.argv) ^ bool(entry.refusal),
                                f"{name}: вход обязан либо запускаться, либо "
                                f"называть, почему перемер не читающий")

    def test_every_runnable_entry_names_the_sandbox_in_its_argv_or_env(self):
        """Вход, не упомянувший ни {root}, ни {data}, писал бы в дерево вызова."""
        for name, entry in er.ENTRY.items():
            if entry.refusal:
                continue
            with self.subTest(name):
                blob = " ".join(entry.argv) + " " + " ".join(entry.env.values())
                self.assertTrue("{root}" in blob or "{data}" in blob,
                                f"{name}: песочница во входе не названа")

    def test_the_six_members_the_order_called_input_less_do_have_an_input(self):
        """Замер #1160: заказ G1010 п. 1 назвал шесть членов безвходными, спросив
        про ИМЯ входа (`--data-dir`/`--out`), а не про его работу. Вход есть у
        всех шести: пять управляются `--root`, шестой — переменной окружения,
        которой в `--help` нет вовсе."""
        claimed_input_less = (
            "cio_component_map.json", "cio_failure_modes.json",
            "cio_target_producers.json", "cio_architecture_constraints.json",
            "findings_bridge_report.json", "cio_auto_execution_limits.json")
        by_env = []
        for name in claimed_input_less:
            self.assertIn(name, er.ENTRY, f"{name} выпал из таблицы")
            entry = er.ENTRY[name]
            if entry.refusal:
                continue  # findings_bridge: перемер не читающий по ДРУГОЙ причине
            blob = " ".join(entry.argv)
            self.assertTrue("{root}" in blob or "{root}" in " ".join(entry.env.values()),
                            f"{name}: вход объявлен, но песочницу не называет")
            if not entry.argv or "--root" not in entry.argv:
                by_env.append(name)
        self.assertEqual(by_env, ["cio_component_map.json"],
                         "ровно один член управляется окружением, а не флагом — "
                         "именно поэтому форма `--help` о нём молчит")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
