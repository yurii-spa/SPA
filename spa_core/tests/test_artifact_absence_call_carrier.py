"""Мера прихода производящего кода стояла на СОСЕДНЕМ файле (ADR-812, #935).

Артефакт переписи появляется в живом ``data/``, когда в дереве лежат ДВА файла:
модуль переписи и **вызов** её ступени. Вызов живёт не в модуле переписи, а в
модуле БЕГУНА (``findings_bridge.py``). `artifact_absence.verdict` брал моментом
прихода дату только ПЕРВОГО, и пока доставка правит оба — даты совпадают и
подмена невидима.

**Повод замера.** Цикл #934 (ADR-811) доставил ступень для
``data/cio_decision_owner.json`` и правил ОБА файла, поэтому живой ответ 25.10
был верен: ``⏳ ещё не производился``. Но верен он был по СОВПАДЕНИЮ формы
доставки, а не по построению — и соседний цикл это немедленно показал бы.

Класс измерен на живом дереве 25.10: ступеней объявлено **116**, у 115 вызов
разбирается как импорт внутри ``main()``, у одной (``no_regression_producer``,
её производитель — СКРИПТ под подпроцессом) форма не разобрана, вызова НЕТ ни у
одной. Дифференциально старый и новый вердикт на живом дереве разошлись у **0**
из 116 — правка добавляет различение, а не смещает ответы молча.

Сцены ниже — положительные контроли обеих сторон подмены:

* **ложная находка** — доставка правит ТОЛЬКО вызывающего (канонический случай
  ADR-259), мера встаёт на не менявшийся модуль переписи, ``ran >= born``, и
  исправная проводка, ждущая такта, объявляется находкой;
* **fail-OPEN, тише и опаснее** — ступень не зовёт НИКТО, но модуль переписи
  недавно правили, и свежая дата файла прячет отсутствие вызова под
  ``⏳ ещё не производился``.

Время — ВХОД (`.claude/rules/deployment.md`): якорь уходит параметром ``now=``,
а даты файлов сцена ставит от этого же якоря через ``os.utime``. Обе стороны
закреплены, стенных часов тест не спрашивает.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW уходит параметром now= в verdict(),
# а mtime файлов сцены ставится от NOW через os.utime(); стенных часов нет.
from __future__ import annotations

import datetime as dt
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import artifact_absence as aa

#: Единственный якорь времени файла — уходит входом в `verdict(now=...)`.
NOW = dt.datetime(2031, 1, 1, 12, 0, tzinfo=dt.timezone.utc)

ARTIFACT = "data/cio_decision_owner.json"
MODULE = "spa_core/monitoring/cio_decision_owner_census.py"
STAGE = "cio_decision_owner_census"
PRODUCTS = {STAGE: {"module": MODULE, "artifact": ARTIFACT}}

#: Модуль бегуна в сцене лежит по ТОМУ ЖЕ относительному пути, что в бою, —
#: иначе сцена проверяла бы не ту дверь.
RUNNER = aa.RUNNER_MODULE_REL


class _Scene(unittest.TestCase):
    """Одноразовое дерево. Живое `data/` не трогает ни одна сцена."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, rel: str, text: str, *, hours_ago: float):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        when = (NOW - dt.timedelta(hours=hours_ago)).timestamp()
        os.utime(p, (when, when))

    def producer(self, *, hours_ago: float):
        self._write(MODULE, "REPORT_REL = 'data/cio_decision_owner.json'\n",
                    hours_ago=hours_ago)

    def runner_module(self, *, hours_ago: float, call: str):
        """Модуль бегуна. `call` — тело `main()`, то есть ФОРМА вызова."""
        self._write(RUNNER, "def main():\n" + call, hours_ago=hours_ago)

    def runner_report(self, *, hours_ago: float, attempted=(),
                      with_start: bool = True):
        """`with_start=False` — отчёт СТАРОГО образца, без `run_started_at`."""
        ran = (NOW - dt.timedelta(hours=hours_ago)).isoformat()
        doc = {"generated_at": ran,
               "censuses": {"attempted": list(attempted), "skipped": {}}}
        if with_start:
            doc["run_started_at"] = ran
        (self.root / aa.RUNNER_REPORT_REL).write_text(
            json.dumps(doc), encoding="utf-8")

    def verdict(self):
        return aa.verdict(ARTIFACT, root=str(self.root), now=NOW,
                          products=PRODUCTS)


IMPORT_IN_MAIN = ("    from spa_core.monitoring import "
                  "cio_decision_owner_census\n"
                  "    cio_decision_owner_census.run()\n")


class TheFalseFindingWhenOnlyTheCallerWasDelivered(_Scene):
    """(A) Доставка правила ТОЛЬКО вызывающего — ровно случай ADR-259."""

    def test_pending_tick_is_not_a_finding_when_the_carrier_is_the_late_one(self):
        # Модуль переписи лежит в дереве ДАВНО и доставкой НЕ менялся.
        self.producer(hours_ago=400.0)
        # Вызов приехал 1 ч назад; бегун стартовал 5 ч назад — ДО вызова.
        self.runner_module(hours_ago=1.0, call=IMPORT_IN_MAIN)
        self.runner_report(hours_ago=5.0)
        v = self.verdict()
        self.assertTrue(v.not_yet,
                        "исправная проводка, ждущая такта, объявлена находкой — "
                        "мера снова встала на не менявшийся модуль переписи")
        self.assertFalse(v.is_finding)
        self.assertEqual(v.call_state, aa.CALL_PRESENT)
        # Назван ТОТ файл, который и приехал позже: читателя нельзя отправлять
        # смотреть модуль переписи, который не менялся 400 ч.
        self.assertEqual(v.carrier, RUNNER)
        self.assertIn(RUNNER, v.reason)
        self.assertAlmostEqual(v.module_age_h, 1.0, places=2)

    def test_inverse_control_the_fix_is_not_a_silencer(self):
        """Обратный контроль: бегун стартовал ПОСЛЕ обоих ⇒ находка."""
        self.producer(hours_ago=400.0)
        self.runner_module(hours_ago=5.0, call=IMPORT_IN_MAIN)
        self.runner_report(hours_ago=1.0)
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.CALL_PRESENT_NOT_ATTEMPTED)
        self.assertEqual(v.call_state, aa.CALL_PRESENT)

    def test_present_call_without_a_measured_start_says_so_and_claims_no_more(self):
        """Отчёт СТАРОГО образца: `run_started_at` нет, есть только `generated_at`.

        Вердикт обязан остаться «вызов есть, исполнения нет» — форма ADR-259
        ИСКЛЮЧЕНА разбором, — но при этом сказать вслух, что СТАРТ процесса не
        измерен: по `generated_at` нельзя утверждать «стартовал после прихода
        кода», можно лишь «последняя фаза началась после» (урок ADR-536).
        """
        self.producer(hours_ago=400.0)
        self.runner_module(hours_ago=5.0, call=IMPORT_IN_MAIN)
        self.runner_report(hours_ago=1.0, with_start=False)
        v = self.verdict()
        self.assertEqual(v.kind, aa.CALL_PRESENT_NOT_ATTEMPTED)
        self.assertEqual(v.clock_field, "generated_at")
        self.assertIn(aa.UNMEASURED, v.reason)
        self.assertNotIn("ADR-259", v.reason,
                         "вызов разобран как ПРИСУТСТВУЮЩИЙ — форма ADR-259 "
                         "исключена, и ссылаться на неё значит утверждать лишнее")

    def test_declared_attempt_still_beats_every_date(self):
        """Назван бегуном ⇒ находка, какими бы ни были даты файлов."""
        self.producer(hours_ago=0.5)
        self.runner_module(hours_ago=0.5, call=IMPORT_IN_MAIN)
        self.runner_report(hours_ago=5.0, attempted=[STAGE])
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.ATTEMPTED_AND_ABSENT)


class TheFailOpenWhenNobodyCallsTheStage(_Scene):
    """(Б) Обратная сторона подмены, и она ТИШЕ: вызова нет вовсе."""

    NO_CALL = "    from spa_core.monitoring import something_else\n"

    def test_absent_call_is_a_finding_even_with_a_freshly_edited_producer(self):
        # Модуль переписи правили 1 ч назад, бегун стартовал 5 ч назад. По
        # ДАТАМ это «⏳ ещё не производился» — и так отвечал прибор до ADR-812,
        # то есть fail-OPEN ровно на дефекте, против которого ADR-259 написан.
        self.producer(hours_ago=1.0)
        self.runner_module(hours_ago=400.0, call=self.NO_CALL)
        self.runner_report(hours_ago=5.0)
        v = self.verdict()
        self.assertTrue(v.is_finding,
                        "ступень не зовёт никто, а свежая дата модуля переписи "
                        "снова выдала это за «ещё не производился»")
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertEqual(v.call_state, aa.CALL_ABSENT)
        self.assertIn("ДОКАЗАНО", v.reason)
        self.assertIn("ADR-259", v.reason)

    def test_absent_call_needs_no_dates_at_all(self):
        """Такта ждать бессмысленно ⇒ вердикт не зависит от часов бегуна."""
        self.producer(hours_ago=1.0)
        self.runner_module(hours_ago=400.0, call=self.NO_CALL)
        for ran in (0.1, 5.0, 500.0):
            with self.subTest(runner_ran_hours_ago=ran):
                self.runner_report(hours_ago=ran)
                self.assertEqual(self.verdict().kind, aa.DECLARED_WITHOUT_CALL)


class TheClaimAboutTheParseIsVerifiedNotNoted(_Scene):
    """Разбор ОБЯЗАН различать формы — иначе «доказано» было бы запиской."""

    def test_import_from_the_module_itself_counts(self):
        """Форма ступени `outcomes`: `from ...X import name`.

        Детектор, читающий у `ImportFrom` только `names`, увидел бы здесь
        `append_daily_outcome` и НЕ увидел модуля — то есть объявил бы живой
        вызов отсутствующим.
        """
        self.producer(hours_ago=400.0)
        self.runner_module(
            hours_ago=1.0,
            call="    from spa_core.monitoring.cio_decision_owner_census "
                 "import run\n    run()\n")
        self.runner_report(hours_ago=5.0)
        v = self.verdict()
        self.assertEqual(v.call_state, aa.CALL_PRESENT)
        self.assertFalse(v.is_finding)

    def test_a_call_outside_main_is_not_reported_as_present(self):
        """Утверждение «внутри main()» обязано быть исполнено, а не заявлено."""
        self._write(RUNNER,
                    "def helper():\n"
                    "    from spa_core.monitoring import "
                    "cio_decision_owner_census\n"
                    "def main():\n    pass\n", hours_ago=1.0)
        self.producer(hours_ago=400.0)
        self.runner_report(hours_ago=5.0)
        v = self.verdict()
        self.assertEqual(v.call_state, aa.CALL_FORM_UNPARSED,
                         "импорт ВНЕ main() зачтён как вызов внутри неё — "
                         "область разбора заявлена, но не исполнена")

    def test_unparsed_form_is_not_called_absent(self):
        """Третий исход ≠ «вызова нет»: выдумывать находку нельзя."""
        self.producer(hours_ago=400.0)
        self.runner_module(
            hours_ago=5.0,
            call="    run_script('scripts/cio_decision_owner_census.py')\n")
        self.runner_report(hours_ago=1.0)
        v = self.verdict()
        self.assertEqual(v.call_state, aa.CALL_FORM_UNPARSED)
        self.assertNotEqual(v.kind, aa.CALL_PRESENT_NOT_ATTEMPTED)
        # Поведение прежнее (ветка дат), и оговорка НЕСЁТСЯ в вердикте.
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertIn(aa.CALL_FORM_UNPARSED, v.reason)


class AskingIsImpossibleIsItsOwnOutcome(_Scene):
    """Инв. #17: «спросить нечем» — отдельное значение, не подстановка."""

    def test_missing_runner_module_is_unmeasured_not_absent(self):
        self.producer(hours_ago=400.0)
        self.runner_report(hours_ago=1.0)          # модуля бегуна в дереве нет
        v = self.verdict()
        self.assertEqual(v.call_state, aa.CALL_UNMEASURED)
        # Прежнее поведение сохранено: правка не смеет ни заглушить, ни
        # выдумать находку там, где измерить не удалось.
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertTrue(v.is_finding)

    def test_unparsable_runner_module_is_unmeasured(self):
        self.producer(hours_ago=400.0)
        self._write(RUNNER, "def main(:\n", hours_ago=1.0)   # синтаксис битый
        self.runner_report(hours_ago=5.0)
        self.assertEqual(self.verdict().call_state, aa.CALL_UNMEASURED)

    def test_runner_module_without_main_is_unmeasured(self):
        self.producer(hours_ago=400.0)
        self._write(RUNNER, "x = 1\n", hours_ago=1.0)
        self.runner_report(hours_ago=5.0)
        self.assertEqual(self.verdict().call_state, aa.CALL_UNMEASURED)


class TheOfficeNamesWhichFileWasLate(_Scene):
    """Читатель обязан назвать ТОТ файл, который приехал позже.

    Шаг 0-офис — СКРИПТ, грузится по пути. Объявление ступени он берёт живое,
    поэтому сцена пользуется НАСТОЯЩЕЙ парой (`cio_decision_owner_census`), а
    не выдуманной: иначе ступень не нашлась бы и ответ был бы о другом.
    """

    @staticmethod
    def _office():
        import importlib.util

        path = (Path(__file__).resolve().parents[2] / "scripts"
                / "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_office_c935", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_pending_line_points_at_the_carrier_not_the_producer(self):
        self.producer(hours_ago=400.0)
        self.runner_module(hours_ago=1.0, call=IMPORT_IN_MAIN)
        self.runner_report(hours_ago=5.0)
        is_finding, lines = self._office()._absent_verdict(
            ARTIFACT, root=str(self.root), data_dir=None, now=NOW)
        text = "\n".join(lines)
        self.assertFalse(is_finding, text)
        self.assertIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", text)
        self.assertIn(RUNNER, text,
                      "офис не назвал файл, который приехал позже — читателя "
                      "отправили смотреть модуль, не менявшийся 400 ч")
        self.assertNotIn(f"производитель {MODULE}", text)


class TheDetectorWorksOnTheRealRunnerModule(unittest.TestCase):
    """Контроль «не вакуумно»: разбор запускается на БОЕВОМ модуле бегуна.

    Без него все сцены выше могли бы проходить на игрушечном файле, а на
    настоящем — на четырёх тысячах строк — детектор отвечал бы `unmeasured`
    для всего населения, и правка была бы украшением.
    """

    ROOT = str(Path(__file__).resolve().parents[2])

    def test_live_declaration_parses_and_finds_no_uncalled_stage(self):
        from spa_core.monitoring.findings_bridge import CENSUS_PRODUCT as CP

        states: dict[str, int] = {}
        for stage, spec in CP.items():
            st = aa._call_state(stage, spec, root=self.ROOT).state
            states[st] = states.get(st, 0) + 1
        self.assertGreater(states.get(aa.CALL_PRESENT, 0), 100,
                           f"разбор боевого модуля бегуна почти ничего не "
                           f"нашёл — детектор вакуумен: {states}")
        self.assertEqual(states.get(aa.CALL_UNMEASURED, 0), 0,
                         f"боевой модуль бегуна не разобран: {states}")
        self.assertEqual(
            states.get(aa.CALL_ABSENT, 0), 0,
            f"ступень, которую не зовёт никто (форма ADR-259): {states}")

    def test_the_subprocess_shaped_stage_is_unparsed_not_absent(self):
        """`no_regression_producer` — производитель-СКРИПТ под подпроцессом."""
        from spa_core.monitoring.findings_bridge import CENSUS_PRODUCT as CP

        spec = CP.get("no_regression_producer")
        if spec is None:
            self.skipTest("ступень no_regression_producer больше не объявлена")
        self.assertEqual(
            aa._call_state("no_regression_producer", spec,
                           root=self.ROOT).state,
            aa.CALL_FORM_UNPARSED,
            "форма «скрипт под подпроцессом» зачтена как отсутствие вызова — "
            "это выдуманная находка")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
