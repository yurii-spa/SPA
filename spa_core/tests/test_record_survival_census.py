# LLM_FORBIDDEN
"""Приёмка прибора «переживает ли запись прогона ОТМЕНУ» (заказ G109 п. 1, ADR-534).

Каждый тест — утверждение о ПОВЕДЕНИИ, и у каждого класса есть контроль в обе
стороны: сцена, где прибор обязан НАЙТИ, и сцена, где он обязан ПРОМОЛЧАТЬ.

**Времени в фикстурах нет ни одной литеральной датой.** Все отметки строятся от
инъектированного ``NOW`` через ``timedelta``: календарь сдвинется, вердикт — нет.
Часы прибора — его вход (``now=``).

**Сети в фикстурах нет вовсе.** ``fetch`` инъектируется словарём ответов, а
читатель воркфлоу по sha — словарём текстов. Прибор, у которого обе двери к
внешнему миру открыты параметром, проверяется на ЛЮБОЙ машине одинаково.

# FROZEN-DATE-OK: injected-clock — часы прибора приняты параметром
# (`build_report(..., now=NOW)`, `measure(..., now=NOW)`), и ВТОРАЯ сторона
# закреплена тем же якорем: все отметки сцены строятся от `NOW` через
# `timedelta`, литеральных дат в фикстурах нет ни одной. Обе стороны пришпилены,
# календарь на вердикт не влияет. Претензия сверяется AST
# (`spa_core/tests/_injected_clock.py`), а не принимается на слово.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.monitoring import record_survival_census as rsc

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)  # якорь сцены, не дата календаря
WF_ID = 777

_WF_HEAD = """\
name: SPA Tests
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - name: Run spa_core unit tests
        run: python -m pytest spa_core/tests/
"""


def workflow(condition: Optional[str] = "!cancelled()", *,
             upload: bool = True, path: str = "reports/",
             retention: Any = 14) -> str:
    """Текст воркфлоу со шагом выгрузки под заданным условием и сроком."""
    if not upload:
        return _WF_HEAD
    cond_line = "" if condition is None else f"        if: ${{{{ {condition} }}}}\n"
    term_line = ("" if retention is None
                 else f"          retention-days: {retention}\n")
    return _WF_HEAD + (
        "      - name: Upload test records (junit + stream)\n"
        + cond_line
        + "        uses: actions/upload-artifact@v4\n"
        "        with:\n"
        "          name: test-records-x\n"
        f"          path: {path}\n"
        + term_line)


def ts(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


class Scene:
    """Одноразовая сцена: население прогонов, строки записей, тексты воркфлоу."""

    def __init__(self) -> None:
        self.runs: List[Dict[str, Any]] = []
        self.artifacts: List[Dict[str, Any]] = []
        self.sources: Dict[str, Optional[str]] = {}
        self.jobs: Dict[int, List[Dict[str, Any]]] = {}
        self.fetched: List[str] = []
        self.fail_on: Optional[str] = None

    def add_run(self, run_id: int, *, conclusion: Optional[str], sha: str,
                minutes_ago: int = 10, event: str = "push",
                records: int = 0, expired: bool = False,
                size: int = 2_600_000, bad_row: bool = False,
                upload_seconds: Optional[float] = None) -> "Scene":
        self.runs.append({"id": run_id, "head_sha": sha, "event": event,
                          "conclusion": conclusion,
                          "status": "completed" if conclusion else "in_progress",
                          "created_at": ts(minutes_ago)})
        for leg in range(records):
            row: Dict[str, Any] = {
                "name": f"{rsc.RECORD_PREFIX}3.1{leg}-{run_id}",
                "size_in_bytes": size,
                "workflow_run": {"id": run_id}}
            if not bad_row:
                row["expired"] = expired
            self.artifacts.append(row)
        if upload_seconds is not None:
            self.jobs[run_id] = [{
                "name": "test (3.11)",
                "steps": [
                    {"name": "Run spa_core unit tests",
                     "started_at": ts(minutes_ago), "completed_at": ts(minutes_ago - 5)},
                    {"name": "Upload test records (junit + stream)",
                     "started_at": ts(minutes_ago - 5),
                     "completed_at": (NOW - timedelta(minutes=minutes_ago - 5)
                                      + timedelta(seconds=upload_seconds)
                                      ).isoformat().replace("+00:00", "Z")},
                ]}]
        return self

    def source(self, sha: str, text: Optional[str]) -> "Scene":
        self.sources[sha] = text
        return self

    # ── двери к внешнему миру, обе инъектируемые ──────────────────────────

    def fetch(self, path: str) -> Any:
        self.fetched.append(path)
        if self.fail_on and self.fail_on in path:
            raise OSError(f"сцена закрыла дверь: {path}")
        if path.startswith("/repos/") and "/actions/workflows?" in path:
            return {"workflows": [{"id": WF_ID, "path": rsc.WORKFLOW_FILE}]}
        if f"/actions/workflows/{WF_ID}/runs" in path:
            return {"workflow_runs": self.runs}
        if "/actions/artifacts?" in path:
            return {"artifacts": self.artifacts}
        if "/jobs?" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": self.jobs.get(run_id, [])}
        raise AssertionError(f"сцена не знает пути {path}")

    def workflow_source_at(self, sha: str) -> Tuple[Optional[str], Optional[str]]:
        if sha not in self.sources:
            return None, f"sha {sha} в этой сцене отсутствует"
        text = self.sources[sha]
        if text is None:
            return None, f"sha {sha} объявлен отсутствующим в клоне"
        return text, None

    def run(self, **kw: Any) -> Dict[str, Any]:
        return rsc.run_census(fetch=self.fetch,
                              workflow_source_at=self.workflow_source_at,
                              now=NOW, **kw)


# ───────────────────────── ось A: класс ВОРОТ ────────────────────────────

class DoorClassTests(unittest.TestCase):
    """Условие шага выгрузки читается как ВЫРАЖЕНИЕ, и покрытие — отдельно."""

    def test_not_cancelled_does_not_cover_cancellation(self):
        cls, detail = rsc.door_class_of_source(workflow("!cancelled()"))
        self.assertEqual(cls, rsc.DOOR_NOT_CANCELLED)
        self.assertEqual(detail["condition"], "!cancelled()")
        self.assertIs(rsc.DOOR_COVERS_CANCELLATION[cls], False)

    def test_always_covers_cancellation(self):
        """Обратная сторона того же утверждения: один токен меняет вердикт."""
        cls, _ = rsc.door_class_of_source(workflow("always()"))
        self.assertEqual(cls, rsc.DOOR_ALWAYS)
        self.assertIs(rsc.DOOR_COVERS_CANCELLATION[cls], True)

    def test_condition_is_read_through_the_expression_wrapper(self):
        """``${{ }}`` — обёртка, а не часть условия."""
        self.assertEqual(rsc._normalise_condition("${{ always() }}"), "always()")
        self.assertEqual(rsc._normalise_condition("  !cancelled() "), "!cancelled()")
        self.assertIsNone(rsc._normalise_condition(None))

    def test_step_without_if_is_its_own_class_not_always(self):
        cls, _ = rsc.door_class_of_source(workflow(None))
        self.assertEqual(cls, rsc.DOOR_UNCONDITIONAL)
        self.assertIs(rsc.DOOR_COVERS_CANCELLATION[cls], False)

    def test_unknown_condition_is_the_third_outcome_not_a_guess(self):
        """`fail-CLOSED`: незнакомое выражение значит «не знаю», не «покрывает»."""
        cls, _ = rsc.door_class_of_source(workflow("success() || failure()"))
        self.assertEqual(cls, rsc.DOOR_OTHER_CONDITION)
        self.assertIsNone(rsc.DOOR_COVERS_CANCELLATION[cls])

    def test_no_upload_step_at_all(self):
        cls, _ = rsc.door_class_of_source(workflow(upload=False))
        self.assertEqual(cls, rsc.DOOR_NO_STEP)

    def test_upload_that_does_not_cover_the_writer_path_is_not_a_door(self):
        """Имя шага доказательством не является — решает `with.path`."""
        cls, detail = rsc.door_class_of_source(workflow("always()", path="logs/"))
        self.assertEqual(cls, rsc.DOOR_STEP_NOT_COVERING)
        self.assertEqual(detail["path"], "logs/")

    def test_multiline_path_covering_the_writer_counts(self):
        text = workflow("always()", path="|\n            logs/\n            reports/")
        cls, _ = rsc.door_class_of_source(text)
        self.assertEqual(cls, rsc.DOOR_ALWAYS)

    def test_unparsed_workflow_is_unmeasured_with_a_named_reason(self):
        cls, detail = rsc.door_class_of_source("jobs: [this is: not: valid")
        self.assertEqual(cls, rsc.DOOR_UNMEASURED)
        self.assertIn("не разобран", detail["reason"])

    def test_workflow_without_the_test_job_is_unmeasured_not_no_step(self):
        cls, detail = rsc.door_class_of_source("name: x\njobs:\n  lint:\n    steps: []\n")
        self.assertEqual(cls, rsc.DOOR_UNMEASURED)
        self.assertIn(rsc.WORKFLOW_JOB, detail["reason"])

    def test_every_door_class_has_a_declared_coverage_verdict(self):
        """Перечень ЗАКРЫТ: новый класс без объявленного покрытия — красный тест."""
        self.assertEqual(set(rsc.DOOR_CLASSES),
                         set(rsc.DOOR_COVERS_CANCELLATION))


# ───────────────────────── ось B: класс ИСХОДА ───────────────────────────

class OutcomeTests(unittest.TestCase):

    def test_live_row_is_survival(self):
        self.assertEqual(rsc.classify_outcome([{"expired": False}]), rsc.OUT_SURVIVED)

    def test_expired_row_is_not_absence(self):
        """Срок хранения — ОТДЕЛЬНЫЙ исход: механизм сработал, запись унёс срок."""
        self.assertEqual(rsc.classify_outcome([{"expired": True}]), rsc.OUT_EXPIRED)

    def test_no_rows_is_absence(self):
        self.assertEqual(rsc.classify_outcome([]), rsc.OUT_ABSENT)

    def test_live_wins_over_expired_in_the_same_run(self):
        self.assertEqual(rsc.classify_outcome([{"expired": True}, {"expired": False}]),
                         rsc.OUT_SURVIVED)

    def test_row_without_the_expired_field_is_unmeasured(self):
        """Строка без поля не есть уцелевшая запись (инв. #17)."""
        self.assertEqual(rsc.classify_outcome([{"name": "x"}]), rsc.OUT_UNMEASURED)

    def test_unfinished_run_is_not_success(self):
        self.assertEqual(rsc.path_of(None), rsc.PATH_UNFINISHED)
        self.assertEqual(rsc.path_of("cancelled"), "cancelled")


# ───────────────────── доля: знаменатель есть утверждение ────────────────

class ShareTests(unittest.TestCase):

    def test_cancellation_and_failure_paths_are_not_merged(self):
        """Главное утверждение прибора: доли двух путей отличаются на порядки, и
        склеивание их спрятало бы весь предмет заказа."""
        sc = Scene().source("sha1", workflow("!cancelled()"))
        for i in range(10):
            sc.add_run(100 + i, conclusion="cancelled", sha="sha1", records=0)
        for i in range(4):
            sc.add_run(200 + i, conclusion="failure", sha="sha1", records=2,
                       upload_seconds=2)
        rep = sc.run()
        self.assertTrue(rep["measured"])
        self.assertEqual(rep["survival"]["cancellation_path"]["share_pct"], 0.0)
        self.assertEqual(rep["survival"]["failure_path"]["share_pct"], 100.0)
        self.assertEqual(rep["status"], rsc.STATUS_OPEN)

    def test_runs_without_the_step_leave_the_denominator(self):
        """Положительный контроль ЗНАМЕНАТЕЛЯ: та же сцена, но половина прогонов
        шла на воркфлоу БЕЗ шага — доля обязана ИЗМЕНИТЬСЯ, а не размазаться."""
        base = Scene().source("sha1", workflow("!cancelled()"))
        for i in range(4):
            base.add_run(300 + i, conclusion="cancelled", sha="sha1", records=0)
        base.add_run(400, conclusion="cancelled", sha="sha1", records=2)
        before = base.run()["survival"]["cancellation_path"]

        wide = Scene().source("sha1", workflow("!cancelled()"))
        wide.source("old", workflow(upload=False))
        for i in range(4):
            wide.add_run(300 + i, conclusion="cancelled", sha="sha1", records=0)
        wide.add_run(400, conclusion="cancelled", sha="sha1", records=2)
        for i in range(20):
            wide.add_run(500 + i, conclusion="cancelled", sha="old", records=0)
        after = wide.run()
        self.assertEqual(before["runs"], 5)
        self.assertEqual(before["share_pct"], 20.0)
        # Население выросло в пять раз, а доля НЕ сдвинулась: прогоны без
        # лекарства в знаменатель не попали.
        self.assertEqual(after["survival"]["cancellation_path"]["runs"], 5)
        self.assertEqual(after["survival"]["cancellation_path"]["share_pct"], 20.0)
        self.assertEqual(after["survival"]["no_upload_step_runs"], 20)

    def test_a_step_that_does_not_cover_the_writer_also_leaves_the_denominator(self):
        sc = Scene().source("sha1", workflow("always()", path="logs/"))
        sc.add_run(601, conclusion="cancelled", sha="sha1", records=0)
        rep = sc.run()
        self.assertEqual(rep["survival"]["step_not_covering_runs"], 1)
        self.assertEqual(rep["survival"]["cancellation_path"]["runs"], 0)
        self.assertIsNone(rep["survival"]["cancellation_path"]["share_pct"])

    def test_empty_denominator_is_none_not_zero(self):
        self.assertIsNone(rsc._share(0, 0))
        self.assertEqual(rsc._share(0, 4), 0.0)

    def test_expired_rows_do_not_become_absent(self):
        """Доля, которая считала бы `expired` отсутствием, зависела бы от того,
        когда её мерили."""
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(701, conclusion="failure", sha="sha1", records=2, expired=True)
        sc.add_run(702, conclusion="failure", sha="sha1", records=0)
        branch = sc.run()["survival"]["failure_path"]
        self.assertEqual(branch["expired"], 1)
        self.assertEqual(branch["absent"], 1)
        self.assertEqual(branch["survived"], 0)

    def test_one_surviving_leg_of_two_is_counted_apart(self):
        """Именно этим объясняются уцелевшие на пути ОТМЕНЫ: одна нога матрицы
        успела выгрузиться до топора. Склеить с «уцелели обе» нельзя."""
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(801, conclusion="cancelled", sha="sha1", records=1)
        sc.add_run(802, conclusion="failure", sha="sha1", records=2)
        rep = sc.run()
        self.assertEqual(rep["survival"]["cancellation_path"]["artifacts_per_survived_run"],
                         {"1": 1})
        self.assertEqual(rep["survival"]["failure_path"]["artifacts_per_survived_run"],
                         {"2": 1})

    def test_always_everywhere_closes_the_class(self):
        """Обратная сторона: ворота путь отмены ПОКРЫВАЮТ ⇒ класс закрыт. Доля
        при этом остаётся какой угодно — она ПОСЛЕДСТВИЕ ворот, а не предмет."""
        sc = Scene().source("sha1", workflow("always()"))
        sc.add_run(901, conclusion="cancelled", sha="sha1", records=0)
        rep = sc.run()
        self.assertIs(rep["survival"]["cancellation_path"]["door_covers"], True)
        self.assertEqual(rep["status"], rsc.STATUS_CLOSED)
        self.assertEqual(rep["survival"]["cancellation_path"]["share_pct"], 0.0)

    def test_mixed_doors_on_one_path_are_unmeasured_not_a_majority_vote(self):
        sc = Scene().source("new", workflow("always()")).source("old", workflow("!cancelled()"))
        sc.add_run(1001, conclusion="cancelled", sha="new", records=0)
        sc.add_run(1002, conclusion="cancelled", sha="old", records=0)
        rep = sc.run()
        self.assertIsNone(rep["survival"]["cancellation_path"]["door_covers"])
        self.assertEqual(rep["status"], rsc.STATUS_OPEN)


# ───────────────────── ось C: цена и третьи исходы ───────────────────────

class PriceTests(unittest.TestCase):

    def test_price_is_measured_in_seconds_from_the_real_step(self):
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(1101, conclusion="failure", sha="sha1", records=2,
                   upload_seconds=2, size=2_600_000)
        sc.add_run(1102, conclusion="failure", sha="sha1", records=2,
                   upload_seconds=7, size=5_300_000)
        price = sc.run()["price"]
        self.assertEqual(price["step_seconds"]["min"], 2.0)
        self.assertEqual(price["step_seconds"]["max"], 7.0)
        self.assertEqual(price["artifact_bytes"]["max"], 5_300_000)

    def test_no_surviving_run_means_the_price_is_unmeasured_not_zero(self):
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(1201, conclusion="cancelled", sha="sha1", records=0)
        price = sc.run()["price"]
        self.assertIsNone(price["step_seconds"])
        self.assertIn("НЕ ИЗМЕРЕНА", price["reason"])
        self.assertEqual(price["sampled_runs"], 0)

    def test_upload_step_is_matched_by_the_declared_name_not_by_a_substring(self):
        """Подстрока «upload» приняла бы чужой шаг (ADR-333)."""
        self.assertTrue(rsc._is_upload_step_name("Upload test records (junit + stream)"))
        self.assertFalse(rsc._is_upload_step_name("Upload coverage"))
        self.assertFalse(rsc._is_upload_step_name("upload test records"))
        self.assertFalse(rsc._is_upload_step_name(None))

    def test_unreadable_job_is_counted_not_dropped(self):
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(1301, conclusion="failure", sha="sha1", records=2)  # джоб нет
        price = sc.run()["price"]
        self.assertIsNone(price["step_seconds"])
        self.assertEqual(price["sampled_runs"], 1)


class ThirdOutcomeTests(unittest.TestCase):

    def test_closed_network_door_is_unmeasured_with_a_nonzero_code(self):
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(1401, conclusion="cancelled", sha="sha1", records=0)
        sc.fail_on = "/runs"
        rep = sc.run()
        self.assertFalse(rep["measured"])
        self.assertEqual(rep["status"], rsc.STATUS_UNMEASURED)
        self.assertIn("население не прочитано", rep["reason"])
        self.assertIsNone(rep["population"])

    def test_missing_workflow_is_named_not_empty(self):
        sc = Scene()

        def fetch(path: str) -> Any:
            if "/actions/workflows?" in path:
                return {"workflows": []}
            raise AssertionError(path)

        rep = rsc.run_census(fetch=fetch, workflow_source_at=sc.workflow_source_at,
                             now=NOW)
        self.assertFalse(rep["measured"])
        self.assertIn(rsc.WORKFLOW_FILE, rep["reason"])

    def test_a_never_ending_page_sequence_is_refused_not_looped_forever(self):
        """НАЙДЕНО МУТАЦИОННЫМ ЗАМЕРОМ, и находка настоящая.

        Пагинация выходила только по «страница короче полной». Мутант, снявший
        это условие, не покраснил батарею и не прошёл её — он её ПОВЕСИЛ, то
        есть в дифференциальном замере тест ИСЧЕЗ (урок #465: мерить надо и
        переход в `skipped`/зависание, а не только `passed↔failed`). Тот же
        дефект исполнился бы на ответе, который всегда полон. Потолок страниц —
        объявленный ВХОД, а его достижение — ТРЕТИЙ ИСХОД с названной причиной:
        обрезанное население не вправе выдать себя за полное.
        """
        sc = Scene().source("sha1", workflow("!cancelled()"))
        for i in range(rsc._PAGE):          # ровно полная страница, всегда
            sc.add_run(3000 + i, conclusion="cancelled", sha="sha1", records=0)
        rep = sc.run(window_runs=10 ** 6)
        self.assertFalse(rep["measured"])
        self.assertIn("не кончился", rep["reason"])
        self.assertIn("население НЕ полно", rep["reason"])
        # Потолок объявлен и ограничивает ОБА перечня, а не один.
        self.assertIsInstance(rsc.MAX_PAGES, int)
        self.assertEqual(2, Path(rsc.__file__).read_text(encoding="utf-8")
                         .count("raise PageCeilingReached("))

    def test_the_artifact_page_sequence_is_bounded_too(self):
        """Второй перечень — своя дверь: у него выхода по окну нет вовсе."""
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(3500, conclusion="cancelled", sha="sha1", records=0)
        full = [{"name": f"{rsc.RECORD_PREFIX}x-{i}", "size_in_bytes": 1,
                 "expired": False, "workflow_run": {"id": 3500}}
                for i in range(rsc._PAGE)]
        sc.artifacts = full
        rep = sc.run()
        self.assertFalse(rep["measured"])
        self.assertIn("перечень записей не кончился", rep["reason"])

    def test_blind_pass_is_refused_rather_than_called_clean(self):
        """Ноль прогонов не есть «ничего не терялось»."""
        rep = Scene().run()
        self.assertFalse(rep["measured"])
        self.assertIn("не измерено, а не равно нулю", rep["reason"])

    def test_sha_absent_from_the_clone_is_door_unmeasured_not_no_step(self):
        """Обрезанный клон обязан отвечать «не знаю», а не «шага нет»: второе
        выкинуло бы прогон из знаменателя МОЛЧА."""
        sc = Scene().source("sha1", workflow("!cancelled()")).source("gone", None)
        sc.add_run(1501, conclusion="cancelled", sha="sha1", records=0)
        sc.add_run(1502, conclusion="cancelled", sha="gone", records=0)
        rep = sc.run()
        self.assertEqual(rep["door"]["by_class"][rsc.DOOR_UNMEASURED], 1)
        self.assertEqual(rep["survival"]["door_unmeasured_runs"], 1)
        self.assertEqual(rep["survival"]["no_upload_step_runs"], 0)
        self.assertEqual(rep["survival"]["cancellation_path"]["runs"], 1)

    def test_accounting_identity_is_refutable(self):
        """Сумма считается по ОБЪЯВЛЕННОМУ перечню имён: `sum(values())` держался
        бы всегда и мутанта бы пережил."""
        sc = Scene().source("sha1", workflow("!cancelled()")).source("old", workflow(upload=False))
        sc.add_run(1601, conclusion="cancelled", sha="sha1", records=0)
        sc.add_run(1602, conclusion="failure", sha="sha1", records=2)
        sc.add_run(1603, conclusion="cancelled", sha="old", records=0)
        rep = sc.run()
        self.assertEqual(rep["accounting"]["runs"], 3)
        self.assertEqual(rep["accounting"]["outcomes_sum"], 3)
        self.assertEqual(rep["accounting"]["doors_sum"], 3)
        self.assertEqual(set(rep["outcomes"]), set(rsc.OUTCOMES))

    def test_absence_past_the_retention_term_is_not_an_absence(self):
        """После срока хранения GitHub удаляет САМУ СТРОКУ об артефакте, поэтому
        «не выгружали» и «унёс срок» в API неотличимы. Склеить их значило бы
        сделать долю зависящей от того, когда её мерили."""
        sc = Scene().source("sha1", workflow("!cancelled()", retention=14))
        sc.add_run(1901, conclusion="cancelled", sha="sha1", records=0,
                   minutes_ago=5)                      # внутри срока
        sc.add_run(1902, conclusion="cancelled", sha="sha1", records=0,
                   minutes_ago=15 * 24 * 60)           # старше срока
        branch = sc.run()["survival"]["cancellation_path"]
        self.assertEqual(branch["absent"], 1)
        self.assertEqual(branch["beyond_term"], 1)
        self.assertEqual(branch["runs"], 2)
        self.assertEqual(branch["decided"], 1)
        self.assertEqual(branch["survived"], 0)
        # 0 из 1 — это ИЗМЕРЕННЫЙ ноль; знаменателем стал только тот прогон, об
        # исходе которого есть наблюдение. Прогон старше срока из знаменателя
        # вышел — иначе доля падала бы сама от хода календаря.
        self.assertEqual(branch["share_pct"], 0.0)

    def test_the_term_is_read_only_as_a_literal(self):
        """`${{ … }}` даёт «срок не измерен», а не число и не умолчание сервиса."""
        cls, detail = rsc.door_class_of_source(
            workflow("!cancelled()", retention="${{ env.TERM }}"))
        self.assertEqual(cls, rsc.DOOR_NOT_CANCELLED)
        self.assertIsNone(detail["retention_days"])

    def test_absence_with_an_unmeasured_term_is_unmeasured_not_absence(self):
        """`fail-CLOSED`: границы нет ⇒ об исходе сказать нечего."""
        sc = Scene().source("sha1", workflow("!cancelled()", retention=None))
        sc.add_run(2001, conclusion="cancelled", sha="sha1", records=0)
        branch = sc.run()["survival"]["cancellation_path"]
        self.assertEqual(branch["unmeasured"], 1)
        self.assertEqual(branch["absent"], 0)
        self.assertIsNone(branch["share_pct"])

    def test_a_run_without_the_step_is_not_blamed_on_the_term(self):
        """Отсутствие записи у прогона без шага объяснено ВОРОТАМИ: поминать срок
        значило бы объяснить одно и то же дважды."""
        sc = Scene().source("old", workflow(upload=False))
        sc.add_run(2101, conclusion="cancelled", sha="old", records=0,
                   minutes_ago=99 * 24 * 60)
        rep = sc.run()
        self.assertEqual(rep["outcomes"][rsc.OUT_ABSENT], 1)
        self.assertEqual(rep["outcomes"][rsc.OUT_BEYOND_TERM], 0)

    def test_survival_is_not_reclassified_by_the_term(self):
        """Обратная сторона: у уцелевшей записи срок ничего не меняет."""
        sc = Scene().source("sha1", workflow("!cancelled()", retention=14))
        sc.add_run(2201, conclusion="failure", sha="sha1", records=2,
                   minutes_ago=99 * 24 * 60)
        self.assertEqual(sc.run()["survival"]["failure_path"]["survived"], 1)

    def test_window_is_an_input_and_is_printed(self):
        sc = Scene().source("sha1", workflow("!cancelled()"))
        for i in range(5):
            sc.add_run(1700 + i, conclusion="cancelled", sha="sha1", records=0)
        rep = sc.run(window_runs=2)
        self.assertEqual(rep["window_runs"], 2)
        self.assertEqual(rep["population"]["runs"], 2)


# ─────────────── сосед не правится и отвечает на свой вопрос ─────────────

class NeighbourTests(unittest.TestCase):

    def test_the_neighbour_has_no_cancellation_outcome_at_all(self):
        """Предмет РАЗНЫЙ: у соседа (ADR-528) путь отмены не назван ни одним
        исходом, поэтому его зелёный ответ верен и поправки не требует (инв. #16).
        """
        from spa_core.monitoring import failed_name_survival_census as fns

        names = [v for k, v in vars(fns).items()
                 if k.isupper() and isinstance(v, str)]
        joined = " ".join(names)
        self.assertNotIn("cancel", joined.lower())
        self.assertIn("cancel", " ".join(rsc.DOOR_CLASSES))

    def test_this_census_writes_nothing_but_its_own_artifact(self):
        """ADVISORY: ни воркфлоу, ни базы храповика прибор не трогает."""
        src = Path(rsc.__file__).read_text(encoding="utf-8")
        # Запрещена ЗАПИСЬ: прямая запись мимо `atomic_save` (инв. #5) и любое
        # касание порогов и баз храповиков. `open(` в этот перечень не входит
        # намеренно — его содержит `urlopen`, то есть ЧТЕНИЕ сети.
        for forbidden in ("timeout-minutes", "baseline.json", "shutil",
                          "write_text", "writelines", "os.replace"):
            self.assertNotIn(forbidden, src, f"прибор не вправе касаться {forbidden}")
        # Единственный писатель — `atomic_save`, и он зовётся ровно для своего
        # артефакта.
        self.assertIn("atomic_save(report, str(path))", src)
        self.assertEqual(src.count("atomic_save("), 1)  # ровно один зов


class ContractLiteralTests(unittest.TestCase):
    """Имена контракта сверяются с ЛИТЕРАЛАМИ, а не сами с собой.

    Найдено мутационным замером (тот же класс, что у ADR-676: 160 выживших из
    210 были именами, сверяемыми через свою же константу). Проверка вида
    ``self.assertEqual(cls, rsc.DOOR_ALWAYS)`` мутанта ИМЕНИ переживает по
    построению: мутация правит обе стороны сразу. Поэтому значения, которые
    уезжают в артефакт и читаются ЧУЖИМ кодом (шаг 0-офис, манифест), пришпилены
    здесь дословно: переименование любого из них обязано быть РЕШЕНИЕМ, а не
    опечаткой, уехавшей молча.
    """

    def test_artifact_name_and_order_are_pinned(self):
        self.assertEqual(rsc.ARTIFACT_NAME, "record_survival_census.json")
        self.assertIn("G109 п. 1", rsc.ORDER)

    def test_status_names_are_pinned(self):
        self.assertEqual(rsc.STATUS_OPEN, "CLASS_OPEN")
        self.assertEqual(rsc.STATUS_CLOSED, "CLASS_CLOSED")
        self.assertEqual(rsc.STATUS_UNMEASURED, "UNMEASURED")

    def test_door_class_names_are_pinned_and_closed(self):
        self.assertEqual(
            list(rsc.DOOR_CLASSES),
            ["always", "not_cancelled", "unconditional", "other_condition",
             "step_does_not_cover_writer", "no_upload_step", "door_unmeasured"])

    def test_outcome_names_are_pinned_and_closed(self):
        self.assertEqual(
            list(rsc.OUTCOMES),
            ["survived", "expired", "absent", "absent_beyond_retention_term",
             "unmeasured"])

    def test_inputs_of_the_subject_are_pinned(self):
        self.assertEqual(rsc.DEFAULT_REPO, "yurii-spa/SPA")
        self.assertEqual(rsc.WORKFLOW_FILE, ".github/workflows/test.yml")
        self.assertEqual(rsc.WORKFLOW_JOB, "test")
        self.assertEqual(rsc.RECORD_PREFIX, "test-records-")
        self.assertEqual(rsc.WRITER_DIR, "reports")
        self.assertEqual(rsc.UPLOAD_STEP_NAMES,
                         ("Upload test records (junit + stream)",))

    def test_declared_window_and_page_are_pinned(self):
        """Окно и размер страницы — ВХОДЫ, и их молчаливый сдвиг менял бы
        население, то есть знаменатель каждой доли."""
        self.assertEqual(rsc.DEFAULT_WINDOW_RUNS, 300)
        self.assertEqual(rsc._PAGE, 100)
        self.assertEqual(rsc.MAX_PAGES, 50)

    def test_api_paths_are_pinned_by_the_scene_it_answers(self):
        """Путь API — контракт с чужим сервисом: опечатка в нём дала бы
        «не измерено», а не находку, и сцена обязана это ловить."""
        sc = Scene().source("sha1", workflow("!cancelled()"))
        sc.add_run(4001, conclusion="failure", sha="sha1", records=2,
                   upload_seconds=2)
        sc.run()
        asked = sc.fetched
        self.assertIn("/repos/yurii-spa/SPA/actions/workflows?per_page=100", asked)
        self.assertTrue(any("/actions/workflows/777/runs?branch=main" in a
                            for a in asked))
        self.assertTrue(any("/actions/artifacts?per_page=100&page=1" == a.split("/repos/yurii-spa/SPA")[-1]
                            for a in asked))
        self.assertTrue(any("/actions/runs/4001/jobs?per_page=100" in a
                            for a in asked))
        self.assertEqual(rsc.API_ROOT, "https://api.github.com")


class ArtifactTests(unittest.TestCase):

    def test_third_outcome_still_reaches_the_reader(self):
        """«Не измерено» обязано доехать артефактом: иначе шаг 0-офис не отличит
        его от «ступень не запускалась»."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            rep = {"generated_at": "x", "measured": False, "reason": "сцена"}
            path = rsc.save_artifact(rep, data)
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["reason"],
                             "сцена")

    def test_report_prints_the_price_and_the_denominator_caveat(self):
        sc = Scene().source("sha1", workflow("!cancelled()")).source("old", workflow(upload=False))
        sc.add_run(1801, conclusion="cancelled", sha="sha1", records=0)
        sc.add_run(1802, conclusion="failure", sha="sha1", records=2, upload_seconds=3)
        sc.add_run(1803, conclusion="cancelled", sha="old", records=0)
        text = "\n".join(rsc.format_report(sc.run()))
        self.assertIn("ЛЕКАРСТВО НЕ ДОСТАВЛЕНО", text)
        self.assertIn("ЦЕНА", text)
        self.assertIn("ADVISORY", text)
        self.assertIn("СЖАТЫЙ размер", text)

    def test_unmeasured_report_says_so_in_one_line(self):
        text = "\n".join(rsc.format_report({"measured": False, "reason": "нет сети"}))
        self.assertEqual(text, "НЕ ИЗМЕРЕНО: нет сети")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
