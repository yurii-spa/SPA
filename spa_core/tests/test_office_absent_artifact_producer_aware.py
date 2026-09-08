"""Сторож: «артефакта нет на диске» — это ДВА разных состояния, а не одно.

Каждая проверка воспроизводит НАСТОЯЩУЮ поломку (правило
`.claude/rules/deployment.md`, «проверка сторожа сторожей»):

* **живой замер 2026-09-08, цикл #524.** `cio_substitution_census.py` доставлен
  пушем в 07:42 и лёг в прод-дерево синком в 09:51; `com.spa.decision_loop`,
  который его зовёт, последний раз отработал в **07:05:59Z**. Обязательный шаг
  напечатал «❌ НЕ ПРОЧИТАН · файла нет на диске» об ИСПРАВНОМ модуле — в
  песочнице `run(write=False)` отрабатывает и `positive_control.passed` истинно.
  Форма строки — полноценная находка, подпись под ней требует действовать;
  добросовестная сессия заводит карточку о здоровом контуре;
* **обратная половина** — та же сцена, но бегун отработал ПОСЛЕ прихода
  производителя: это настоящая находка, и смягчить её нельзя. Без этой пары
  правка была бы не различением, а глушилкой;
* **объявление сильнее даты** — перепись, НАЗВАННАЯ бегуном в составе ступени,
  остаётся находкой при любой дате файла: спрашиваем объявление, а не догадку;
* **причина пропуска доезжает** — до #524 провалившаяся перепись писала причину
  в `/tmp/spa_decision_loop.log`, то есть в канал, который читает лишь тот, кто
  уже знает, что смотреть (класс «сторож говорит в канал, который отказывает»);
* **ничего не ослаблено** — артефакт вне карты производителей, отсутствующий
  производитель, нечитаемый отчёт бегуна и отчёт без собственного времени
  остаются находкой. «Не смог измерить» не есть «всё хорошо»;
* **третий исход не вечен** — состояние «ещё не производился» закрывается
  следующим прогоном бегуна САМО, без правки кода и без записи в базу;
* **состав ступени не ведётся руками** — `CENSUS_STAGE` сверяется с телом
  `main()` разбором AST. Перепись, добавленная мимо списка, краснеет: сторож,
  чьё население ведут руками, отказывает ровно тогда, когда кто-то забыл.

Время — ВХОД (`.claude/rules/deployment.md`): ни одной литеральной даты, все
отметки строятся от инъектированного `now`, все mtime выставляются явно.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
_OFFICE = REPO / "scripts" / "consume_office_reports.py"


def _load_office():
    """Шаг 0-офис — СКРИПТ, а не модуль пакета: грузим по пути."""
    spec = importlib.util.spec_from_file_location("_office_c524", _OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


office = _load_office()

#: Настоящая пара из живого замера #524 — берём её, а не выдуманные имена:
#: сцена обязана быть тем случаем, на котором прибор соврал.
ARTIFACT = "data/cio_substitution_census.json"
PRODUCER = "spa_core/monitoring/cio_substitution_census.py"
STAGE = "cio_substitution_census"


class Scenes(unittest.TestCase):
    """Сцены строятся на одноразовом дереве: живое `data/` не трогается."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        (self.root / "spa_core" / "monitoring").mkdir(parents=True)
        # Инъектированные часы. Никаких стенных: и `now`, и обе отметки ниже
        # производны от одного якоря, поэтому сцена бессмертна.
        # FROZEN-DATE-OK: injected-clock — якорь `self.now` уходит параметром
        # `now=` в `_absent_verdict`, а обе отметки сцены (mtime производителя
        # через `os.utime`, `generated_at` отчёта бегуна) строятся вычитанием
        # от него же. Ни одна проба не спрашивает стенных часов.
        self.now = dt.datetime(2031, 1, 1, 12, 0, tzinfo=dt.timezone.utc)

    def tearDown(self):
        self._tmp.cleanup()

    # ── материал сцены ──────────────────────────────────────────────────
    def _producer(self, *, born_hours_ago: float) -> None:
        p = self.root / PRODUCER
        p.write_text("# производитель\n", encoding="utf-8")
        born = self.now - dt.timedelta(hours=born_hours_ago)
        os.utime(p, (born.timestamp(), born.timestamp()))

    def _runner(self, *, ran_hours_ago: float | None, censuses=None,
                broken: bool = False, no_ts: bool = False) -> None:
        p = self.root / "data" / "findings_bridge_report.json"
        if broken:
            p.write_text("{ это не json", encoding="utf-8")
            return
        doc: dict = {}
        if not no_ts and ran_hours_ago is not None:
            doc["generated_at"] = (
                self.now - dt.timedelta(hours=ran_hours_ago)).isoformat()
        if censuses is not None:
            doc["censuses"] = censuses
        p.write_text(json.dumps(doc), encoding="utf-8")

    def _verdict(self):
        return office._absent_verdict(ARTIFACT, root=str(self.root),
                                      data_dir=None, now=self.now)

    # ── сцены ───────────────────────────────────────────────────────────
    def test_live_2026_09_08_producer_arrived_after_the_runner_last_ran(self):
        """Живой замер #524: код приехал в 09:51, бегун отработал в 07:05."""
        self._producer(born_hours_ago=1.0)
        self._runner(ran_hours_ago=3.0)
        is_finding, lines = self._verdict()
        self.assertFalse(is_finding,
                         "исправный контур объявлен находкой — это и есть "
                         "авария 2026-09-08")
        text = "\n".join(lines)
        self.assertIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", text)
        self.assertNotIn("файла нет на диске", text)

    def test_inverse_runner_ran_after_the_producer_arrived_is_a_finding(self):
        """Обратная половина: бегун видел код и файла не оставил."""
        self._producer(born_hours_ago=5.0)
        self._runner(ran_hours_ago=1.0)
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding,
                        "настоящая находка смягчена — правка стала глушилкой")
        self.assertIn("ADR-259", "\n".join(lines))

    def test_declared_stage_beats_the_file_date(self):
        """Названа бегуном ⇒ находка, даже если код «моложе» отчёта."""
        self._producer(born_hours_ago=0.5)
        self._runner(ran_hours_ago=3.0,
                     censuses={"attempted": [STAGE], "skipped": {}})
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding)
        self.assertIn("назван в составе ступени", "\n".join(lines))

    def test_skip_reason_reaches_the_reader(self):
        """Причина пропуска едет в отчёт, а не только в /tmp-лог агента."""
        self._producer(born_hours_ago=0.5)
        self._runner(ran_hours_ago=3.0,
                     censuses={"attempted": [STAGE],
                               "skipped": {STAGE: "KeyError: 'positions'"}})
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding)
        self.assertIn("KeyError: 'positions'", "\n".join(lines))

    def test_third_outcome_closes_itself_on_the_next_run(self):
        """«Ещё не производился» — состояние с выходом, а не вечный UNCHECKED."""
        self._producer(born_hours_ago=1.0)
        self._runner(ran_hours_ago=3.0)
        self.assertFalse(self._verdict()[0])
        # бегун отработал ещё раз — ничего в коде не менялось
        self._runner(ran_hours_ago=0.1)
        self.assertTrue(self._verdict()[0],
                        "состояние не закрывается следующим прогоном ⇒ это "
                        "UNCHECKED, который не станет CHECKED никогда")

    # ── ничего не ослаблено: четыре двери остаются находкой ─────────────
    def test_artifact_outside_the_producer_map_stays_a_finding(self):
        self._producer(born_hours_ago=1.0)
        self._runner(ran_hours_ago=3.0)
        is_finding, lines = office._absent_verdict(
            "data/этого-нет-в-карте.json", root=str(self.root),
            data_dir=None, now=self.now)
        self.assertTrue(is_finding)
        self.assertIn(office._UNMEASURED, "\n".join(lines))

    def test_missing_producer_file_stays_a_finding(self):
        self._runner(ran_hours_ago=3.0)  # производителя не создаём вовсе
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding)
        self.assertIn("писать его нечем", "\n".join(lines))

    def test_unreadable_runner_report_stays_a_finding(self):
        self._producer(born_hours_ago=1.0)
        self._runner(ran_hours_ago=None, broken=True)
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding, "нечитаемый отчёт бегуна ⇒ fail-OPEN")
        self.assertIn(office._UNMEASURED, "\n".join(lines))

    def test_runner_report_without_its_own_time_stays_a_finding(self):
        self._producer(born_hours_ago=1.0)
        self._runner(ran_hours_ago=3.0, no_ts=True)
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding)
        self.assertIn(office._UNMEASURED, "\n".join(lines))

    def test_absent_runner_report_stays_a_finding(self):
        self._producer(born_hours_ago=1.0)  # отчёта бегуна нет на диске
        is_finding, lines = self._verdict()
        self.assertTrue(is_finding)


class StageIsDeclaredNotHandMaintained(unittest.TestCase):
    """`CENSUS_STAGE` обязан совпадать с телом `main()` — сверка разбором AST.

    Ручной список — ровно тот дефект, ради которого написан сторож: он
    отказывает тогда, когда кто-то забыл дописать в него строку.
    """

    def test_constant_matches_the_stage_actually_run_by_main(self):
        from spa_core.monitoring import findings_bridge

        src = Path(findings_bridge.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        # Имя ступени — первый аргумент-строка вызова `census_skipped(...)`:
        # это ровно та дверь, через которую пропуск попадает в отчёт.
        seen: list[str] = []
        for node in ast.walk(main):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "census_skipped"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)):
                seen.append(node.args[1].value)
        self.assertTrue(seen, "в теле main() не найдено ни одной ступени — "
                              "разбор промахнулся, а не ступеней нет")
        self.assertEqual(sorted(seen), sorted(findings_bridge.CENSUS_STAGE),
                         "состав ступени разошёлся с объявлением CENSUS_STAGE")
        self.assertEqual(len(seen), len(set(seen)), "ступень названа дважды")


class WiringOfTheAbsenceBranch(unittest.TestCase):
    """Различение обязано стоять В ТОМ САМОМ месте, где печаталась находка.

    Проверка деталей отдельно от проводки — известный способ получить зелёный
    набор над мёртвой правкой: `_absent_verdict` может быть безупречен и не
    вызываться ниоткуда. Меряется ФОРМА вызова в теле `main()` шага 0-офис.
    """

    def test_absence_branch_calls_the_verdict_and_has_its_own_mark(self):
        src = _OFFICE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = [n for n in ast.walk(main)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_absent_verdict"]
        self.assertEqual(len(called), 1,
                         "вердикт об отсутствии не вызывается из main() ровно "
                         "один раз — правка мертва либо задвоена")
        self.assertIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", src,
                      "у третьего исхода нет собственной пометки ⇒ он снова "
                      "неотличим от находки")
        self.assertIn("not_yet", src,
                      "третий исход не имеет своего слагаемого в итоге ⇒ он "
                      "складывается либо с прочитанным, либо с находками")


class BridgeRecordsWhatItTried(unittest.TestCase):
    """Отчёт моста несёт состав ступени только когда ступень действительно шла."""

    def test_census_skipped_records_the_reason_not_only_prints_it(self):
        """Пропуск ЗАПИСЫВАЕТСЯ. Печать в /tmp-лог — не канал наружу."""
        from spa_core.monitoring import findings_bridge

        record: dict = {}
        findings_bridge.census_skipped(record, "проверка",
                                       KeyError("positions"))
        self.assertIn("проверка", record,
                      "причина пропуска не попала в запись — снаружи у неё "
                      "снова нет следа, кроме отсутствующего артефакта")
        self.assertIn("KeyError", record["проверка"])
        self.assertIn("positions", record["проверка"])

    def test_direct_run_makes_no_claim_about_the_stage(self):
        from spa_core.monitoring import findings_bridge

        sig = findings_bridge.run_bridge.__defaults__
        self.assertIn(None, sig, "censuses обязан иметь умолчание None")
        src = Path(findings_bridge.__file__).read_text(encoding="utf-8")
        self.assertIn("if censuses is not None:", src,
                      "ключ censuses пишется безусловно ⇒ прямой вызов моста "
                      "объявил бы попытку, которой не было")


if __name__ == "__main__":
    unittest.main()
