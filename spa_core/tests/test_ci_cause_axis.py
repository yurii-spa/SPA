"""Ось ПРИЧИН красного у свода контрольного прогона (ADR-891, заказ G887 п. 3).

Предмет: до 01.11 строка `failures` отчёта свода несла `nodeid`, исход, шард и `msg`, а
`msg` есть первая строка потоковой записи — `файл:строка: in <тест>`, то есть МЕСТО.
ПОЧЕМУ упало лежало в `junit.xml` ТОГО ЖЕ артефакта шарда, который свод уже читает ради
потоковой записи, и выбрасывалось. «79 красных» читается как «79 поломок», и по этому
числу решают, брать ли набор в работу.

Здесь проверяются состояния, которых НЕ ВИДИТ проба приёмки
(`test_ci_cause_axis_probe.py` рвёт звенья проводки, а это — исходы самой оси):
запись нечитаема · запись доигранной попытки лежит отдельным файлом · падение есть в
записи и не числится упавшим в отчёте · прогон зелёный · двери опознания нет вовсе.

Каждый тест — ОДНОРАЗОВАЯ сцена из настоящих файлов шарда; настоящий `aggregate` зовётся
на ней целиком. Живое дерево не трогается, сети не касается ни один тест.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def _producer():
    spec = importlib.util.spec_from_file_location(
        "_t_ci_control", _REPO / "scripts" / "ci_control.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ctl = _producer()

_FAILING = ("spa_core/tests/test_cause_x.py::Box::test_a",
            "spa_core/tests/test_cause_x.py::Box::test_b")
_PASSING = "spa_core/tests/test_cause_x.py::Box::test_c"
_ALL = (*_FAILING, _PASSING)
_FILES = ["spa_core/tests/test_cause_x.py"]


def _manifest() -> dict:
    return {"schema": ctl.MANIFEST_SCHEMA, "sha": "f" * 40,
            "env": {"python": "3.11.17", "pytest": "9.1.1"},
            "collected": list(_ALL), "files": list(_FILES), "collect_errors": [],
            "shards": [{"shard": 0, "files": list(_FILES), "tests": len(_ALL),
                        "est_s": 1.0}]}


def _junit_xml(entries) -> str:
    """Запись сцены. Строка кадра у каждого теста СВОЯ, и это обеспечение предпосылки:
    верхний край вилки есть ключ «причина+МЕСТО», поэтому на общем месте он слипается с
    нижним, и сцена «две причины сливаются в одну» молча вырождалась бы в 1…1 — первая
    редакция этого файла так и мерила (поймано своим прогоном)."""
    rows = []
    for line, nodeid in enumerate(_ALL, start=11):
        name = nodeid.rsplit("::", 1)[1]
        cls = "spa_core.tests.test_cause_x.Box"
        body = ""
        if nodeid in entries:
            kind, msg = entries[nodeid]
            body = (f'<failure message="{kind}: {msg}">'
                    f'spa_core/tests/test_cause_x.py:{line}: in {name}\n'
                    f'E       {kind}: {msg}\n</failure>')
        rows.append(f'<testcase classname="{cls}" name="{name}" time="0.01">'
                    f'{body}</testcase>')
    return f'<testsuite name="pytest" tests="{len(_ALL)}">{"".join(rows)}</testsuite>'


class _Shard:
    """Каталог одного шарда: записи настоящие, их читает настоящий свод."""

    def __init__(self, test: unittest.TestCase, *, failing=_FAILING,
                 junit: str | None = None, junit_name: str = "junit.xml",
                 extra: dict | None = None):
        self.root = Path(test.enterContext(tempfile.TemporaryDirectory(
            prefix="spa_c1005_axis_")))
        d = self.root / f"{ctl.SHARD_DIR_PREFIX}0"
        d.mkdir(parents=True)
        (d / ctl.SHARD_FILE).write_text(json.dumps({"shard": 0}), encoding="utf-8")
        (d / ctl.COLLECTED_FILE).write_text(
            json.dumps({"e": "collected", "count": len(_ALL),
                        "nodeids": list(_ALL)}) + "\n", encoding="utf-8")
        (d / ctl.EXIT_FILE).write_text(
            json.dumps({"exit": 1 if failing else 0,
                        "attempts": [{"attempt": 0, "exit": 1 if failing else 0}],
                        "crashes": []}), encoding="utf-8")
        lines = []
        t = 1_793_514_000.0
        for i, nodeid in enumerate(_ALL):
            lines.append({"e": "start", "n": nodeid, "t": t + i})
            lines.append({"e": "fail" if nodeid in failing else "ok", "n": nodeid,
                          "t": t + i + 0.1, "w": "call", "d": 0.1,
                          "msg": f"spa_core/tests/test_cause_x.py:9: in x"})
        lines.append({"e": "end", "status": 1 if failing else 0,
                      "started": len(_ALL), "finished": len(_ALL), "t": t + 50})
        (d / ctl.STREAM_FILE).write_text(
            "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        if junit is not None:
            (d / junit_name).write_text(junit, encoding="utf-8")
        for name, body in (extra or {}).items():
            (d / name).write_text(body, encoding="utf-8")
        self.dir = d

    def report(self) -> dict:
        return ctl.aggregate(_manifest(), self.root, needs_result="failure",
                             run={"id": "1"})


class TheAxisIsMeasuredWhenTheRecordIsThere(unittest.TestCase):

    def test_every_failure_gets_a_cause_and_the_fork_is_named(self):
        rep = _Shard(self, junit=_junit_xml({
            _FAILING[0]: ("AssertionError", "1 != 2"),
            _FAILING[1]: ("KeyError", "&apos;k&apos;"),
        })).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["status"], "measured", axis)
        self.assertEqual((axis["population"], axis["attributed"]), (2, 2))
        self.assertEqual(axis["kinds"], {"AssertionError": 1, "KeyError": 1})
        self.assertEqual(axis["fork"]["lower"], 2)
        self.assertEqual(axis["fork"]["upper"], 2)
        self.assertTrue(all(axis["identities_hold"].values()), axis["identities_hold"])
        for row in rep["failures"]:
            self.assertIsInstance(row["cause"], dict, row)
            self.assertTrue(row["cause"]["kind"])

    def test_two_failures_of_one_coarse_cause_merge_into_one_defect(self):
        """Нижний край есть КОМПОНЕНТЫ: один грубый скелет на двоих ⇒ 1…2, не 2…2."""
        rep = _Shard(self, junit=_junit_xml({
            _FAILING[0]: ("AssertionError", "1 != 2"),
            _FAILING[1]: ("AssertionError", "3 != 4"),
        })).report()
        fork = rep["cause_axis"]["fork"]
        self.assertEqual((fork["lower"], fork["upper"]), (1, 2), fork)

    def test_a_green_run_is_measured_and_equal_to_zero(self):
        rep = _Shard(self, failing=(), junit=_junit_xml({})).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["status"], "measured")
        self.assertEqual((axis["population"], axis["attributed"]), (0, 0))
        self.assertIn("измерено и равно нулю", ctl.cause_line(axis))

    def test_the_record_of_a_resumed_attempt_is_read_too(self):
        """junit доигранной попытки лежит ОТДЕЛЬНЫМ файлом; прочти одно имя — и
        причины падений доигранного шарда исчезли бы молча."""
        rep = _Shard(self, junit=_junit_xml({_FAILING[0]: ("AssertionError", "1 != 2")}),
                     extra={"junit-resume-1.xml": _junit_xml(
                         {_FAILING[1]: ("KeyError", "&apos;k&apos;")})}).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["attributed"], 2, axis)
        self.assertEqual(axis["unattributed_n"], 0, axis)
        self.assertEqual(axis["records_read"], 2, axis)

    def test_the_order_of_attempts_is_numeric_not_alphabetical(self):
        """ДВЕ доигранные попытки: по алфавиту `resume-2` встал бы РАНЬШЕ `resume-1`.

        Сцена с ОДНОЙ доигранной попыткой этот вопрос не задаёт: алфавит и номер дают
        там один и тот же порядок (`junit.xml` и так старше `junit-resume-1.xml`), и
        подмена порядка на алфавитный ПЕРЕЖИЛА мутационный прогон #1005 как
        эквивалентная. Вопрос появляется ровно со второй попытки.
        """
        rep = _Shard(self, failing=(_FAILING[0],),
                     junit=_junit_xml({_FAILING[0]: ("KeyError", "попытка нулевая")}),
                     extra={"junit-resume-1.xml": _junit_xml(
                                {_FAILING[0]: ("ValueError", "попытка первая")}),
                            "junit-resume-2.xml": _junit_xml(
                                {_FAILING[0]: ("AssertionError", "попытка вторая")})}
                     ).report()
        row = next(r for r in rep["failures"] if r["nodeid"] == _FAILING[0])
        self.assertEqual(row["cause"]["kind"], "AssertionError", row["cause"])
        self.assertIn("вторая", row["cause"]["skeleton"])
        self.assertEqual(rep["cause_axis"]["records_read"], 3)

    def test_the_cause_of_the_LAST_attempt_is_the_one_that_stands(self):
        """Доигранная сессия гоняет тест заново; её причина — та, что стои́т.

        Порядок обязан задаваться НОМЕРОМ попытки, а не алфавитом: по алфавиту
        `junit-resume-1.xml` идёт РАНЬШЕ `junit.xml` (дефис меньше точки), то есть
        правило «кто первый» совпало бы с нужным СЛУЧАЙНО, не будучи им.
        """
        rep = _Shard(self, failing=(_FAILING[0],),
                     junit=_junit_xml({_FAILING[0]: ("KeyError", "первая попытка")}),
                     extra={"junit-resume-1.xml": _junit_xml(
                         {_FAILING[0]: ("AssertionError", "вторая попытка")})}).report()
        row = next(r for r in rep["failures"] if r["nodeid"] == _FAILING[0])
        self.assertEqual(row["cause"]["kind"], "AssertionError", row["cause"])
        self.assertIn("вторая", row["cause"]["skeleton"])


class TheAxisNeverServesAbsenceAsZero(unittest.TestCase):

    def test_no_record_at_all_is_the_third_outcome_with_a_reason(self):
        rep = _Shard(self, junit=None).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["status"], "unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНЫ", axis["why"])
        self.assertEqual(axis["population"], 2,
                         "не измеренная причина не вправе уменьшать число упавших")
        self.assertIn("НЕ ИЗМЕРЕНА", ctl.cause_line(axis))

    def test_an_unreadable_record_is_named_not_counted_as_clean(self):
        rep = _Shard(self, junit="<testsuite><broken").report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["status"], "unmeasured", axis)
        self.assertTrue(axis["shards_unreadable"], axis)

    def test_a_failure_absent_from_the_record_is_named_by_name(self):
        rep = _Shard(self, junit=_junit_xml(
            {_FAILING[0]: ("AssertionError", "1 != 2")})).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["status"], "measured")
        self.assertEqual(axis["unattributed"], [_FAILING[1]], axis)
        self.assertEqual(axis["population"], 2)
        rows = {r["nodeid"]: r for r in rep["failures"]}
        self.assertIsNone(rows[_FAILING[1]]["cause"])
        self.assertIn("БЕЗ причины 1", ctl.cause_line(axis))

    def test_a_failure_only_in_the_record_is_named_too(self):
        """Запись знает упавшего, которого отчёт упавшим не числит — записи СПОРЯТ."""
        rep = _Shard(self, failing=_FAILING, junit=_junit_xml({
            _FAILING[0]: ("AssertionError", "1 != 2"),
            _FAILING[1]: ("AssertionError", "3 != 4"),
            _PASSING: ("AssertionError", "5 != 6"),
        })).report()
        axis = rep["cause_axis"]
        self.assertEqual(axis["record_only_n"], 1, axis)
        self.assertIn("не числит упавшими 1", ctl.cause_line(axis))

    def test_a_door_that_blows_up_on_a_record_names_the_record(self):
        """Дверь упала НА ЗАПИСИ ⇒ запись названа нечитаемой с типом исключения."""
        shard = _Shard(self, junit=_junit_xml({_FAILING[0]: ("AssertionError", "1 != 2")}))
        rows = [{"nodeid": n, "outcome": "failed", "shard": 0, "msg": ""}
                for n in _FAILING]
        axis = ctl.cause_axis(_manifest()["shards"], shard.root, rows,
                              door=_Door(reading=RuntimeError("сцена: дверь упала")))
        self.assertEqual(axis["status"], "unmeasured", axis)
        self.assertEqual(axis["population"], 2)
        self.assertEqual([r[2] for r in axis["shards_unreadable"]],
                         ["RuntimeError: сцена: дверь упала"], axis)
        self._assert_no_cause_keys(rows)

    def test_a_door_that_blows_up_after_reading_cannot_kill_the_report(self):
        """Дверь упала ПОСЛЕ чтения (на вилке) ⇒ третий исход, а не исключение наружу.

        Свод зовут ОДИН раз в конце прогона: павший на добавочной оси свод отдал бы
        пустой отчёт и потерял бы уже измеренные имена упавших. Найдено этим же файлом
        до доставки — охрана ввоза переданную входом дверь не прикрывала.
        """
        shard = _Shard(self, junit=_junit_xml({_FAILING[0]: ("AssertionError", "1 != 2"),
                                               _FAILING[1]: ("KeyError", "&apos;k&apos;")}))
        rows = [{"nodeid": n, "outcome": "failed", "shard": 0, "msg": ""}
                for n in _FAILING]
        axis = ctl.cause_axis(_manifest()["shards"], shard.root, rows,
                              door=_Door(forking=ValueError("сцена: вилка упала")))
        self.assertEqual(axis["status"], "unmeasured", axis)
        self.assertIn("ось причин не снята", axis["why"])
        self.assertIn("ValueError", axis["why"])
        self._assert_no_cause_keys(rows)

    def test_a_kind_outside_the_declared_vocabulary_breaks_the_identity(self):
        """Тождество считается по ОБЪЯВЛЕННОМУ перечню имён, а не суммой счётчика.

        Сумма значений счётчика равна населению ВСЕГДА — такое тождество неопровержимо,
        то есть проверкой не является (урок ADR-675). Опровержимо оно только тогда, когда
        род ВЫПАЛ из перечня, который печатается читателю: именно такой род исчезал бы из
        строки МОЛЧА. Сцена ровно про это — словарь двери разошёлся с населением.
        Мутационный прогон #1005 показал, что без неё подмена «по перечню» → «суммой»
        переживает всю батарею.
        """
        shard = _Shard(self, junit=_junit_xml({_FAILING[0]: ("AssertionError", "1 != 2")}))
        rows = [{"nodeid": _FAILING[0], "outcome": "failed", "shard": 0, "msg": ""}]
        axis = ctl.cause_axis(_manifest()["shards"], shard.root, rows,
                              door=_Door(vocab={"PHASES": ("setup",)}))
        self.assertEqual(axis["status"], "measured", axis)
        self.assertFalse(axis["identities_hold"]["phases"], axis["identities_hold"])
        self.assertTrue(axis["identities_hold"]["cause_classes"],
                        "ломаться обязан РОВНО тот набор, чей перечень разошёлся")
        self.assertIn("ТОЖДЕСТВО УЧЁТА НАРУШЕНО", ctl.cause_line(axis))

    def _assert_no_cause_keys(self, rows):
        self.assertTrue(all("cause" not in r for r in rows),
                        "не измеренная ось не вправе писать в строку «причина = None»: "
                        "это сказало бы «не опознали» там, где НЕ МЕРИЛИ (инв. #17)")

    def test_no_plan_is_the_third_outcome_too(self):
        rep = ctl.aggregate(None, Path(tempfile.mkdtemp()), run={"id": "1"})
        self.assertEqual(rep["cause_axis"]["status"], "unmeasured")
        self.assertTrue(rep["cause_axis"]["why"])


class _Door:
    """НАСТОЯЩАЯ дверь опознания, у которой ОДНО звено подменено исключением.

    Подменять дверь целиком было бы сценой о себе: ось обязана дойти до того места, где
    звено рвётся, а для этого остальные её ответы должны быть настоящими.
    """

    def __init__(self, *, reading=None, forking=None, vocab=None):
        self._reading, self._forking = reading, forking
        from spa_core.monitoring import failure_cause_census as real
        self._real = real
        for name in ("junit_name", "READ_OK", "PHASES", "CAUSE_CLASSES",
                     "SITE_CLASSES"):
            setattr(self, name, getattr(real, name))
        for name, value in (vocab or {}).items():
            setattr(self, name, value)

    def census_from_path(self, path, *, stream=None):
        if self._reading is not None:
            raise self._reading
        return self._real.census_from_path(path, stream=stream)

    def fork_of(self, failures):
        if self._forking is not None:
            raise self._forking
        return self._real.fork_of(failures)


class TheLineIsTheOnlyCopyOfTheRule(unittest.TestCase):

    def test_a_missing_block_is_words_with_a_reason_not_a_zero(self):
        self.assertIn("НЕ ИЗМЕРЕНА", ctl.cause_line(None))
        self.assertIn("старше ADR-891", ctl.cause_line(None))

    def test_a_broken_identity_is_shouted_in_the_line(self):
        axis = {"status": "measured", "population": 2, "attributed": 2,
                "kinds": {"AssertionError": 2}, "fork": {"population": 2, "lower": 1,
                                                         "upper": 2,
                                                         "largest_component": 2},
                "top": [["AssertionError", "# != #", 2]],
                "identities_hold": {"phases": False, "cause_classes": True,
                                    "site_classes": True}}
        self.assertIn("ТОЖДЕСТВО УЧЁТА НАРУШЕНО", ctl.cause_line(axis))


if __name__ == "__main__":
    unittest.main()
