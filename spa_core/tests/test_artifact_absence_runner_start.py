"""Момент, с которым сверяют приход производителя, — СТАРТ ПРОЦЕССА бегуна.

Авария, которую воспроизводит каждый тест файла (замер 2026-10-02, цикл #750).

`com.spa.decision_loop` запустился в **04:46:42Z** (баннер `START ... pid=74604`
в `/tmp/spa_decision_loop.log`), проработал 3 ч 24 мин и записал отчёт с
`generated_at` = **08:10:17Z**: мост есть ПОСЛЕДНЯЯ фаза прогона, а перед ним
идёт ступень переписей, и на живом Маке она занимает часы. Код ступени
`claim_guard_receipt_readers` (ADR-535) лёг в прод-дерево синком в **05:49:42Z**
— на час ПОЗЖЕ старта процесса и на два часа РАНЬШЕ `generated_at`.

Процесс к этому моменту свой `findings_bridge` уже импортировал, ступени в
исполняемом коде не было ПО ПОСТРОЕНИЮ (`.claude/rules/deployment.md`:
«долгоживущий агент держит код с момента старта»), артефакта он оставить не мог
— а шаг 0-офис напечатал про исправную проводку:

    ❌ НЕ ПРОЧИТАН data/claim_guard_receipt_readers.json
       производитель ... в дереве есть, бегун отработал ПОСЛЕ его прихода
       (2026-10-02T08:10:17) и ступень не назвал — объявленный артефакт без
       производящего вызова (форма ADR-259)

Под подписью «красные строки выше = действовать (карточки)». Класс тот же, что
у ADR-478: сторож сверял артефакт с НЕ ТЕМ моментом и указывал не ту дверь.
Направление ошибки `generated_at` названо: он ЗАВЫШАЕТ «успел увидеть», то есть
ошибается в сторону ложной находки на здоровом контуре.

Время здесь — ВХОД (`now=`, отметки собираются от `NOW` и `os.utime`): ни
календарь хоста, ни длительность прогона на вердикт не влияют.
FROZEN-DATE-OK: injected-clock — `aa.verdict(..., now=NOW)`, а отметки отчёта и
mtime модуля производятся от того же `NOW`; литеральной даты в файле нет.
"""

# FROZEN-DATE-OK: injected-clock — якорь `NOW` связан с именем; все отметки сцены
# (отчёт бегуна, mtime производителя через `os.utime`) ПРОИСХОДЯТ от него вычитанием,
# и он же уезжает аргументом `now=` в `aa.verdict`. Обе стороны закреплены, поэтому
# ни календарь хоста, ни длительность прогона на вердикт не влияют.
import datetime as dt
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_absence as aa

NOW = dt.datetime(2026, 10, 2, 9, 0, tzinfo=dt.timezone.utc)

#: Живой зазор замера 02.10 в часах, считая назад от `NOW`.
START_H = 4.22      # 04:46:42Z — старт процесса
BORN_H = 3.17       # 05:49:42Z — приход кода в дерево
GENERATED_H = 0.83  # 08:10:17Z — начало последней фазы (мост)


def _stage_pair():
    """Любая объявленная пара «ступень → артефакт» из реестра самого моста.

    Пара берётся У ОБЪЯВЛЕНИЯ, а не пишется литералом: литерал разошёлся бы с
    реестром молча (ADR-220), и тест начал бы мерить собственную копию.
    """
    from spa_core.monitoring import findings_bridge as fb
    for stage, spec in fb.CENSUS_PRODUCT.items():
        return stage, spec["module"], spec["artifact"]
    raise AssertionError("реестр ступеней моста пуст — предпосылка не обеспечена")


class _Scene(unittest.TestCase):
    """Одноразовое дерево: производитель, отчёт бегуна, артефакта НЕТ."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="spa_absence_start_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.stage, self.module_rel, self.artifact_rel = _stage_pair()
        (self.root / "data").mkdir(parents=True, exist_ok=True)

    def producer(self, *, born_hours_ago: float):
        p = self.root / self.module_rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# производитель\n", encoding="utf-8")
        born = (NOW - dt.timedelta(hours=born_hours_ago)).timestamp()
        os.utime(p, (born, born))

    def runner(self, *, generated_hours_ago: float | None = GENERATED_H,
               started_hours_ago: float | None = None):
        doc: dict = {}
        if generated_hours_ago is not None:
            doc["generated_at"] = (
                NOW - dt.timedelta(hours=generated_hours_ago)).isoformat()
        if started_hours_ago is not None:
            doc["run_started_at"] = (
                NOW - dt.timedelta(hours=started_hours_ago)).isoformat()
        (self.root / aa.RUNNER_REPORT_REL).write_text(
            json.dumps(doc), encoding="utf-8")

    def verdict(self):
        return aa.verdict(self.artifact_rel, root=str(self.root), now=NOW)


class LiveReplayOfTheMomentSubstitution(_Scene):
    """(A) Ровно живой замер 02.10 — и он обязан перестать быть находкой."""

    def test_code_that_arrived_inside_a_running_pass_is_not_a_finding(self):
        self.producer(born_hours_ago=BORN_H)
        self.runner(started_hours_ago=START_H, generated_hours_ago=GENERATED_H)
        v = self.verdict()
        self.assertTrue(
            v.not_yet,
            "код приехал ПОСЛЕ старта процесса ⇒ его там быть не могло; "
            "объявлять это находкой и есть авария 02.10")
        self.assertFalse(v.is_finding)
        self.assertEqual(v.clock_field, "run_started_at")

    def test_the_old_comparator_alone_would_still_accuse(self):
        """Положительный контроль: без правки сцена ДАЁТ ложную находку.

        Проверка, никогда не видевшая настоящей поломки, — украшение
        (`.claude/rules/deployment.md`). Та же сцена без `run_started_at`
        обязана краснеть, иначе тест выше зелен по другой причине.
        """
        self.producer(born_hours_ago=BORN_H)
        self.runner(started_hours_ago=None, generated_hours_ago=GENERATED_H)
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertEqual(v.clock_field, "generated_at")

    def test_two_comparators_disagree_on_one_scene(self):
        """Разница между моментами ИЗМЕРЕНА на одной сцене, а не рассказана."""
        self.producer(born_hours_ago=BORN_H)
        self.runner(started_hours_ago=None, generated_hours_ago=GENERATED_H)
        by_generated = self.verdict()
        self.runner(started_hours_ago=START_H, generated_hours_ago=GENERATED_H)
        by_start = self.verdict()
        self.assertNotEqual(
            by_generated.is_finding, by_start.is_finding,
            "вердикт не зависит от момента сверки ⇒ сцена не воспроизводит "
            "класс, и зелень тестов выше ничего не значит")


class TheGuardMustNotBecomeASilencer(_Scene):
    """(Б) Обратная сторона: настоящая находка обязана остаться находкой."""

    def test_producer_older_than_the_process_start_is_a_finding(self):
        self.producer(born_hours_ago=START_H + 1.0)   # код лежал ДО старта
        self.runner(started_hours_ago=START_H, generated_hours_ago=GENERATED_H)
        v = self.verdict()
        self.assertTrue(v.is_finding, "правка стала глушилкой настоящей находки")
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertIn("ADR-259", v.reason)
        self.assertEqual(v.clock_field, "run_started_at")

    def test_the_finding_names_the_process_start_not_the_bridge_phase(self):
        self.producer(born_hours_ago=START_H + 1.0)
        self.runner(started_hours_ago=START_H, generated_hours_ago=GENERATED_H)
        v = self.verdict()
        self.assertIn("СТАРТОВАЛ", v.reason)
        self.assertEqual(v.runner_ran_at,
                         (NOW - dt.timedelta(hours=START_H)).isoformat())

    def test_declared_attempt_still_beats_both_clocks(self):
        """Названа бегуном ⇒ находка, какой бы момент ни стоял в отчёте."""
        self.producer(born_hours_ago=0.1)
        doc = {"generated_at": (NOW - dt.timedelta(hours=GENERATED_H)).isoformat(),
               "run_started_at": (NOW - dt.timedelta(hours=START_H)).isoformat(),
               "censuses": {"attempted": [self.stage], "skipped": {}}}
        (self.root / aa.RUNNER_REPORT_REL).write_text(
            json.dumps(doc), encoding="utf-8")
        v = self.verdict()
        self.assertEqual(v.kind, aa.ATTEMPTED_AND_ABSENT)
        self.assertTrue(v.is_finding)


class TheThirdOutcomeIsNamedNotAssumed(_Scene):
    """(В) Старта нет в отчёте — это НЕ «старт равен generated_at» (инв. #17)."""

    def test_missing_start_is_said_aloud_in_the_reason(self):
        self.producer(born_hours_ago=START_H + 1.0)
        self.runner(started_hours_ago=None, generated_hours_ago=GENERATED_H)
        v = self.verdict()
        self.assertIn(aa.UNMEASURED, v.reason)
        self.assertIn("run_started_at", v.reason)
        self.assertIn("не доказана", v.reason,
                      "вердикт по приближению обязан признать свою цену")

    def test_proven_and_unproven_findings_are_distinguishable(self):
        """Два вердикта-находки не смеют быть неотличимы: цена у них разная."""
        self.producer(born_hours_ago=START_H + 1.0)
        self.runner(started_hours_ago=None)
        unproven = self.verdict()
        self.runner(started_hours_ago=START_H)
        proven = self.verdict()
        self.assertEqual(unproven.kind, proven.kind)
        self.assertNotEqual(unproven.clock_field, proven.clock_field)
        self.assertNotEqual(unproven.reason, proven.reason)

    def test_no_clock_at_all_stays_the_third_outcome(self):
        self.producer(born_hours_ago=1.0)
        self.runner(started_hours_ago=None, generated_hours_ago=None)
        v = self.verdict()
        self.assertEqual(v.kind, aa.UNMEASURED_REPORT_HAS_NO_CLOCK)
        self.assertTrue(v.is_finding, "«не измерено» обязано остаться находкой")

    def test_unparsable_start_falls_back_and_says_so(self):
        """Поле есть, но разобрать нечем ⇒ приближение, и оно НАЗВАНО."""
        self.producer(born_hours_ago=START_H + 1.0)
        doc = {"generated_at": (NOW - dt.timedelta(hours=GENERATED_H)).isoformat(),
               "run_started_at": "это не отметка времени"}
        (self.root / aa.RUNNER_REPORT_REL).write_text(
            json.dumps(doc), encoding="utf-8")
        v = self.verdict()
        self.assertEqual(v.clock_field, "generated_at")
        self.assertIn(aa.UNMEASURED, v.reason)


class TheWriterActuallyRecordsTheStart(unittest.TestCase):
    """(Г) Проводка — ИСХОДОМ: поле обязано доехать от писателя к читателю.

    Без этой стороны правка читателя была бы вечным третьим исходом: читатель
    умеет спросить `run_started_at`, а писать его никто не стал бы.
    """

    def test_run_bridge_puts_the_given_start_into_its_report(self):
        from spa_core.monitoring import findings_bridge as fb
        started = NOW - dt.timedelta(hours=START_H)
        root = Path(tempfile.mkdtemp(prefix="spa_absence_writer_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        rep = fb.run_bridge(root=str(root), now=NOW, run_started_at=started,
                            create=lambda *a, **k: None,
                            close=lambda *a, **k: None,
                            notify=lambda *a, **k: None,
                            retract=lambda *a, **k: None)
        self.assertEqual(rep.get("run_started_at"), started.isoformat())
        self.assertEqual(rep.get("generated_at"), NOW.isoformat())
        self.assertNotEqual(rep["run_started_at"], rep["generated_at"],
                            "старт процесса и начало моста слились в один "
                            "момент — ровно та подмена, против которой правка")

    def test_absent_start_is_an_absent_KEY_not_a_substituted_value(self):
        from spa_core.monitoring import findings_bridge as fb
        root = Path(tempfile.mkdtemp(prefix="spa_absence_writer2_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        rep = fb.run_bridge(root=str(root), now=NOW,
                            create=lambda *a, **k: None,
                            close=lambda *a, **k: None,
                            notify=lambda *a, **k: None,
                            retract=lambda *a, **k: None)
        self.assertNotIn("run_started_at", rep,
                         "подставленный `generated_at` под именем старта — это "
                         "«не измерено», выданное за замер (инв. #17)")

    def test_the_cli_stamps_the_start_before_the_census_stage(self):
        """Снято ДО переписей, иначе это `generated_at` под новым именем.

        Признак измеряется РАЗБОРОМ `main`, а не чтением глазами: порядок
        строк и есть всё содержание правки (зазор 02.10 — 3 ч 24 мин).
        """
        import ast
        import inspect
        from spa_core.monitoring import findings_bridge as fb
        tree = ast.parse(inspect.getsource(fb.main))
        stamp_line = census_line = bridge_line = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "run_started_at"
                            for t in node.targets)):
                stamp_line = node.lineno
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id == "run_bridge":
                    bridge_line = node.lineno
                if (isinstance(fn, ast.Attribute) and fn.attr == "run"
                        and census_line is None):
                    census_line = node.lineno
        self.assertIsNotNone(stamp_line, "`main` не снимает старт процесса вовсе")
        self.assertIsNotNone(census_line, "ступень переписей в `main` не найдена")
        self.assertIsNotNone(bridge_line, "вызов `run_bridge` в `main` не найден")
        self.assertLess(stamp_line, census_line,
                        "старт снят ПОСЛЕ начала переписей — он уже не старт")
        self.assertLess(stamp_line, bridge_line)

    def test_the_cli_hands_the_stamp_to_run_bridge(self):
        """Снял и не отдал — половина инъекции, то есть та же бомба."""
        import ast
        import inspect
        from spa_core.monitoring import findings_bridge as fb
        tree = ast.parse(inspect.getsource(fb.main))
        handed = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "run_bridge"):
                for kw in node.keywords:
                    if (kw.arg == "run_started_at"
                            and isinstance(kw.value, ast.Name)
                            and kw.value.id == "run_started_at"):
                        handed = True
        self.assertTrue(handed, "снятый старт до `run_bridge` не доходит")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
