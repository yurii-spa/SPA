"""Контроль прибора «выдерживаем ли объявленный срок годности» (`slo_keepability`).

Каждый тест — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не проверка,
что функция что-то вернула. Прибор меряет, способен ли производитель выдержать
объявленный ``slo_hours``, и соврать он может ровно четырьмя способами:

1. выдать «не измерено» за «выдерживаем» (fail-OPEN, тише красного — опаснее);
2. судить по МЕДИАНЕ, а длинный разрыв спрятать;
3. объявить «нарушений нет» в окне, которое короче самого срока (зелёный ПО
   ПОСТРОЕНИЮ, урок ADR-543);
4. судить поАГЕНТНО там, где обещание дано АРТЕФАКТУ, и напечатать находку о
   сроке, который двумя производителями выдерживается.

# FROZEN-DATE-OK: injected-clock — часы входом: единственный литерал даты здесь
# `_ANCHOR`, и он передаётся прибору аргументом `now=`; отметки прогонов в
# стенде считаются ОТ него, поэтому календарь на вердикт не влияет.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import slo_keepability as sk  # noqa: E402

#: Единственный литерал даты набора. Передаётся прибору аргументом `now=`.
_ANCHOR = dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=dt.timezone.utc)

#: Обёртка режима A канонического шаблона — так объявляют имя 50 агентов флота.
_WRAPPER_A = '#!/bin/bash\nexport AGENT_NAME="{name}"\nexec /bin/bash {tpl} \n'
#: Обёртка режима B — имя позиционным аргументом шаблона.
_WRAPPER_B = '#!/bin/bash\n# Generated from scripts/agent_template.sh (canonical).\nexec /bin/bash {tpl} {name} spa_core.monitoring.x --run\n'
#: Обёртка со СВОЕЙ формой записи: шаблон не упомянут вовсе.
_WRAPPER_OWN = '#!/bin/bash\nLOG_FILE=~/logs/own_$(date +%Y%m%d).log\necho start >> "$LOG_FILE"\n'
#: Обёртка, которая шаблон зовёт, а имени не объявляет.
_WRAPPER_NAMELESS = '#!/bin/bash\nexec /bin/bash {tpl} "$TARGET"\n'
#: Обёртка, у которой в КОММЕНТАРИИ рядом с именем шаблона стоит ЧУЖОЕ имя.
#: Живой флот такую форму содержит («# Generated from scripts/agent_template.sh
#: (canonical …)»), и первая редакция резолвера читала оттуда «(canonical» как
#: имя агента у 44 обёрток из 54.
_WRAPPER_COMMENT_DECOY = ('#!/bin/bash\n'
                          '# пример вызова: {tpl} decoy_name spa_core.x\n'
                          'exec /bin/bash {tpl} {name} spa_core.monitoring.x --run\n')


def _banner(moment: dt.datetime, name: str) -> str:
    """Запись ОДНОГО прогона так, как её печатает `scripts/agent_template.sh`.

    `EXIT`-строка здесь не украшение сцены: она есть в каждом живом логе, и
    правило «строка с `agent=`» удвоило бы каждый прогон — то есть вдвое
    занизило бы наблюдённый период, ошибившись В СТОРОНУ ЗДОРОВЬЯ.
    """
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    done = (moment + dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (f"[{stamp}] START agent={name} pid=1\n"
            f"[{stamp}]   exec: python3 -m spa_core.monitoring.x\n"
            f"[{done}] EXIT agent={name} code=0\n")


class _Stand:
    """Одноразовый стенд: конституция, обёртки агентов, записи прогонов.

    Отметки прогонов ВЫЧИСЛЯЮТСЯ от впрыснутого `now`, а не пишутся литералом:
    иначе тест умер бы от сдвига календаря, а не от правки кода.
    """

    def __init__(self, tmp: Path):
        self.root = tmp
        (self.root / "architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        self.agents: list = []
        self.artifacts: list = []

    # ── конституция ──────────────────────────────────────────────────────
    def agent(self, label, produces, *, intent="active", schedule="interval:3600s",
              wrapper=_WRAPPER_A, name=None, program=None):
        short = name or label.split(".")[-1]
        program = program if program is not None else f"agent_{short}.sh"
        if wrapper is not None and program:
            (self.root / "scripts" / program).write_text(
                wrapper.format(name=short, tpl=str(self.root / "scripts" / "agent_template.sh")))
        self.agents.append({"label": label, "intent": intent, "schedule": schedule,
                            "program": program,
                            "produces": [{"artifact": a, **({"slo_hours": s} if s is not None else {})}
                                         for a, s in produces]})
        return short

    def artifact(self, path, slo, *, status="active", producer="com.spa.x"):
        entry = {"path": path, "producer": producer, "status": status}
        if slo is not None:
            entry["slo_hours"] = slo
        self.artifacts.append(entry)

    def write(self) -> Path:
        target = self.root / "architecture" / "manifest.json"
        target.write_text(json.dumps({"agents": self.agents, "artifacts": self.artifacts},
                                     ensure_ascii=False))
        return target

    # ── записи прогонов ──────────────────────────────────────────────────
    def runs(self, short, hours_ago, *, name=None):
        """Баннеры стартов: `hours_ago` — сколько часов назад шёл каждый прогон."""
        text = "".join(_banner(_ANCHOR - dt.timedelta(hours=h), name or short)
                       for h in sorted(hours_ago, reverse=True))
        (self.root / "logs" / f"spa_{short}.log").write_text(text)

    def raw_log(self, short, text):
        (self.root / "logs" / f"spa_{short}.log").write_text(text)

    def measure(self, **kw):
        return sk.measure(self.write(), log_dir=self.root / "logs",
                          scripts_dir=self.root / "scripts", now=_ANCHOR, **kw)


class _StandCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.stand = _Stand(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def row(self, doc, path):
        return next(r for r in doc["rows"] if r["artifact"] == path)


# ───────────────────── вердикт по НАБЛЮДЁННОМУ такту ─────────────────────

class VerdictOnObservedTact(_StandCase):

    def test_period_longer_than_the_slo_is_a_finding_with_BOTH_numbers(self):
        """Дефект ADR-506 дословно: объявлено 7ч, наблюдается до 7.84ч."""
        self.stand.agent("com.spa.loop", [("data/a.json", 7)], schedule="interval:21600s")
        self.stand.runs("loop", [0.1, 7.9, 15.5, 23.1])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["verdict"], sk.UNKEEPABLE)
        self.assertGreater(row["observed_max_hours"], 7)
        self.assertEqual(row["slo_hours"], 7)
        self.assertEqual(doc["tally"][sk.UNKEEPABLE], 1)
        self.assertEqual(doc["verdict"], "declared_slo_unkeepable")

    def test_period_within_the_slo_is_keepable(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", [h for h in range(0, 30)])
        doc = self.stand.measure()
        self.assertEqual(self.row(doc, "data/a.json")["verdict"], sk.KEEPABLE)
        self.assertEqual(doc["verdict"], "every_declared_slo_keepable")

    def test_ONE_long_gap_decides_even_when_the_median_is_fine(self):
        """Обещание нарушает ОДИН разрыв — медиана его прячет, максимум нет."""
        self.stand.agent("com.spa.loop", [("data/a.json", 5)])
        # 30 часовых прогонов и ОДИН разрыв в 9 ч: медиана 1 ч, максимум 9 ч.
        hours = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 19, 20, 21, 22, 23]
        self.stand.runs("loop", hours)
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["observed_median_hours"], 1.0)
        self.assertEqual(row["observed_max_hours"], 9.0)
        self.assertEqual(row["verdict"], sk.UNKEEPABLE,
                         "судить по медиане значит прятать разрыв, ради которого прибор написан")

    def test_a_period_EQUAL_to_the_slo_is_keepable_not_a_finding(self):
        """Протухло — это `age > slo`, а не `>=`: равенство находкой не является."""
        self.stand.agent("com.spa.loop", [("data/a.json", 6)])
        self.stand.runs("loop", [0, 6, 12, 18, 24, 30])
        doc = self.stand.measure()
        self.assertEqual(self.row(doc, "data/a.json")["verdict"], sk.KEEPABLE)

    def test_an_EXIT_banner_is_not_a_second_run(self):
        """Обёртка печатает START и EXIT с одним `agent=`. Правило «строка с
        `agent=`» удвоило бы прогоны и вдвое ЗАНИЗИЛО период — в сторону здоровья."""
        self.stand.agent("com.spa.loop", [("data/a.json", 5)])
        self.stand.runs("loop", [0, 9, 18, 27])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["runs"], 4, "EXIT-строки посчитаны как прогоны")
        self.assertEqual(row["observed_max_hours"], 9.0)
        self.assertEqual(row["verdict"], sk.UNKEEPABLE)

    def test_periods_are_computed_on_SORTED_stamps_so_a_shuffled_log_cannot_invent_a_gap(self):
        ordered = sk.periods_hours([_ANCHOR - dt.timedelta(hours=h) for h in (0, 5, 1, 3)])
        self.assertEqual(ordered, [2.0, 2.0, 1.0])
        self.assertTrue(all(p >= 0 for p in ordered))


# ─────────── третий исход: у «не измерено» ВСЕГДА названа причина ───────────

class ThirdOutcomeHasANamedCause(_StandCase):
    """«Такт не наблюдён» и «срок выдерживается» — разные положения дел (инв. #17)."""

    def _unmeasured(self, expect_cause, path="data/a.json"):
        doc = self.stand.measure()
        row = self.row(doc, path)
        self.assertEqual(row["verdict"], sk.UNMEASURED)
        self.assertIn(expect_cause, row["cause"])
        self.assertEqual(doc["tally"][sk.KEEPABLE], 0,
                         "неизмеренное не имеет права попасть в «выдерживаем»")
        self.assertIn(expect_cause, doc["unmeasured_causes"])
        self.assertIn(expect_cause, sk.CAUSE_RU, "у причины обязано быть объяснение словами")
        return doc

    def test_record_absent_is_not_health(self):
        """Замер 03.10: ровно это у `com.spa.decision_loop` — 91 артефакт."""
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        self._unmeasured(sk.RECORD_ABSENT)

    def test_own_record_form_is_named_not_counted_as_silence(self):
        """Обёртка ведёт свой лог (так живёт `com.spa.daily_cycle` — 15 артефактов)."""
        self.stand.agent("com.spa.cycle", [("data/a.json", 26)], wrapper=_WRAPPER_OWN)
        self._unmeasured(sk.FORM_UNRECOGNISED)

    def test_wrapper_without_a_name_is_an_unresolved_ADDRESS_not_a_missing_record(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 7)], wrapper=_WRAPPER_NAMELESS)
        self._unmeasured(sk.ADDRESS_UNRESOLVED)

    def test_a_missing_wrapper_is_an_unresolved_address(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 7)], wrapper=None)
        self._unmeasured(sk.ADDRESS_UNRESOLVED)

    def test_a_single_run_is_NOT_a_period_of_zero(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        self.stand.runs("loop", [1.0])
        doc = self._unmeasured(sk.FEWER_THAN_TWO_RUNS)
        self.assertIsNone(self.row(doc, "data/a.json")["observed_max_hours"])

    def test_banners_without_a_parsable_stamp_are_named_not_skipped(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        self.stand.raw_log("loop", "[не-дата] START agent=loop pid=1\n"
                                   "[тоже-не-дата] START agent=loop pid=2\n")
        doc = self._unmeasured(sk.TIMESTAMPS_UNPARSABLE)
        self.assertEqual(self.row(doc, "data/a.json")["unparsable_banners"], 2)

    def test_a_log_that_cannot_be_read_is_named(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        (self.stand.root / "logs" / "spa_loop.log").mkdir()  # каталог вместо файла
        self._unmeasured(sk.RECORD_UNREADABLE)

    def test_a_promise_without_a_living_producer_is_named(self):
        """Срок объявлен, писать его некому — это не «выдерживается»."""
        self.stand.agent("com.spa.other", [("data/other.json", 3)])
        self.stand.artifact("data/a.json", 7, producer="com.spa.ghost")
        self._unmeasured(sk.PRODUCER_NOT_DECLARED)

    def test_a_window_SHORTER_than_the_slo_cannot_testify_to_health(self):
        """Урок ADR-543: разрыв в 26ч не поместится в окно 3ч, и «нарушений нет»
        там верно ПО ПОСТРОЕНИЮ."""
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", [0, 1, 2, 3])
        doc = self._unmeasured(sk.WINDOW_SHORTER_THAN_SLO)
        self.assertEqual(self.row(doc, "data/a.json")["span_hours"], 3.0)

    def test_a_document_with_ONLY_unmeasured_rows_says_so_in_its_verdict(self):
        """«Все сроки выдерживаются» и «такт нигде не наблюдён» — разные ответы,
        и путать их в одном слове означало бы доложить здоровье вместо слепоты."""
        self.stand.agent("com.spa.mute", [("data/a.json", 7)])
        doc = self.stand.measure()
        self.assertEqual(doc["verdict"], "tact_not_observed")
        self.assertEqual(doc["tally"][sk.UNMEASURED], 1)
        self.assertEqual(doc["tally"][sk.KEEPABLE], 0)

    def test_the_cause_of_a_periodless_row_is_the_producers_own_cause(self):
        """Подставить правдоподобную причину значило бы завести ВТОРУЮ копию
        правила `run_starts` (ADR-220): мутация «один прогон есть период» на
        такой подстановке выживала, потому что ответ совпадал."""
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        self.stand.runs("loop", [1.0])
        row = self.row(self.stand.measure(), "data/a.json")
        self.assertEqual(row["cause"], sk.FEWER_THAN_TWO_RUNS)
        self.assertNotEqual(row["cause"], sk.CAUSE_NOT_NAMED)

    def test_every_unmeasured_cause_of_the_module_has_words_and_a_test(self):
        """Причина без объяснения словами есть код ошибки, а не ответ."""
        declared = {sk.FORM_UNRECOGNISED, sk.ADDRESS_UNRESOLVED, sk.RECORD_ABSENT,
                    sk.RECORD_UNREADABLE, sk.FEWER_THAN_TWO_RUNS,
                    sk.WINDOW_SHORTER_THAN_SLO, sk.TIMESTAMPS_UNPARSABLE,
                    sk.PRODUCER_NOT_DECLARED, sk.CAUSE_NOT_NAMED}
        self.assertEqual(declared, set(sk.CAUSE_RU))


# ───────── предмет — АРТЕФАКТ, а не агент (ложная находка 03.10) ─────────

class TheArtifactIsTheSubject(_StandCase):

    def test_two_producers_together_serve_a_promise_neither_serves_alone(self):
        """Живой случай: `data/deployment_acceptance.json` пишут ДВА суточных
        агента со сдвигом 12ч, срок 15ч. Поагентный вердикт объявил бы находку
        (24ч > 15ч) там, где обещание ВЫДЕРЖИВАЕТСЯ."""
        self.stand.agent("com.spa.morning", [("data/acc.json", 15)], schedule="calendar:08:00")
        self.stand.agent("com.spa.evening", [("data/acc.json", 15)], schedule="calendar:20:00")
        self.stand.runs("morning", [2, 26, 50, 74])
        self.stand.runs("evening", [14, 38, 62, 86])
        doc = self.stand.measure()
        row = self.row(doc, "data/acc.json")
        self.assertEqual(sorted(row["producers"]), ["com.spa.evening", "com.spa.morning"])
        self.assertEqual(row["observed_max_hours"], 12.0,
                         "период считается по ОБЪЕДИНЁННОЙ записи обоих производителей")
        self.assertEqual(row["verdict"], sk.KEEPABLE)

    def test_dropping_one_of_two_producers_turns_the_same_promise_into_a_finding(self):
        """Обратная сторона того же: один суточный агент срок 15ч не держит."""
        self.stand.agent("com.spa.morning", [("data/acc.json", 15)], schedule="calendar:08:00")
        self.stand.runs("morning", [2, 26, 50, 74])
        doc = self.stand.measure()
        self.assertEqual(self.row(doc, "data/acc.json")["verdict"], sk.UNKEEPABLE)

    def test_a_foreign_banner_in_a_shared_log_is_not_this_agents_run(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 2)])
        own = "".join(_banner(_ANCHOR - dt.timedelta(hours=h), "loop") for h in (0, 1, 2, 3))
        alien = "".join(_banner(_ANCHOR - dt.timedelta(hours=h), "stranger") for h in (0.5, 1.5))
        self.stand.raw_log("loop", own + alien)
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["runs"], 4)
        self.assertEqual(row["foreign_banners"], 2)

    def test_one_producer_silent_and_one_speaking_keeps_the_measured_answer(self):
        """Молчание одного производителя не делает наблюдение другого неизмеренным."""
        self.stand.agent("com.spa.speaks", [("data/acc.json", 30)], schedule="interval:3600s")
        self.stand.agent("com.spa.silent", [("data/acc.json", 30)], wrapper=_WRAPPER_OWN)
        self.stand.runs("speaks", list(range(0, 40)))
        doc = self.stand.measure()
        row = self.row(doc, "data/acc.json")
        self.assertEqual(row["verdict"], sk.KEEPABLE)
        self.assertIn(sk.FORM_UNRECOGNISED, row["producer_causes"],
                      "причина второго производителя обязана быть НАЗВАНА, а не забыта")


# ───────────── обещание в силе — САМОЕ КОРОТКОЕ из объявленных ─────────────

class TheBindingPromiseIsTheShortest(_StandCase):

    def test_two_homes_disagreeing_bind_the_shorter_number_and_the_clash_is_counted(self):
        """Живой случай: `data/analytics_report_full.json` — 3ч у одного агента,
        26ч у другого. Взять длинный значило бы выбрать удобный."""
        self.stand.agent("com.spa.tier_b", [("data/r.json", 3)])
        self.stand.agent("com.spa.tier_c", [("data/r.json", 26)])
        self.stand.runs("tier_b", list(range(0, 40)))
        self.stand.runs("tier_c", [0, 24])
        doc = self.stand.measure()
        row = self.row(doc, "data/r.json")
        self.assertEqual(row["slo_hours"], 3)
        self.assertEqual(row["slo_declared"], [3.0, 26.0])
        self.assertTrue(row["slo_disagreement"])
        self.assertEqual(doc["slo_disagreements"], 1)

    def test_a_retired_artifact_promise_is_not_in_force(self):
        """Правило отставного артефакта взято у ЕДИНСТВЕННОГО читателя срока
        (`manifest_slo`), второй копии правила здесь нет."""
        self.stand.agent("com.spa.loop", [("data/live.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        self.stand.artifact("data/retired.json", 1, status="retired")
        doc = self.stand.measure()
        self.assertNotIn("data/retired.json", [r["artifact"] for r in doc["rows"]])


# ─────────────────────── население ОБЪЯВЛЕНО ───────────────────────

class PopulationIsDeclaredNotGuessed(_StandCase):

    def test_retired_and_designed_agents_are_excluded_AND_counted(self):
        self.stand.agent("com.spa.live", [("data/a.json", 26)])
        self.stand.runs("live", list(range(0, 40)))
        self.stand.agent("com.spa.old", [("data/b.json", 1)], intent="retired")
        self.stand.agent("com.spa.future", [("data/c.json", 1)], intent="designed")
        doc = self.stand.measure()
        self.assertEqual(doc["excluded_by_intent"]["retired"], 1)
        self.assertEqual(doc["excluded_by_intent"]["designed"], 1)
        self.assertEqual([r["artifact"] for r in doc["rows"]], ["data/a.json"])

    def test_produces_without_an_slo_is_counted_not_judged(self):
        """«Срок не объявлен» — пробел СОСЕДА (B2 `slo_unassigned`), не находка здесь."""
        self.stand.agent("com.spa.loop", [("data/a.json", 26), ("data/b.json", None)])
        self.stand.runs("loop", list(range(0, 40)))
        doc = self.stand.measure()
        self.assertEqual(doc["produces_without_slo"], 1)
        self.assertEqual([r["artifact"] for r in doc["rows"]], ["data/a.json"])

    def test_an_empty_population_is_UNMEASURED_not_a_clean_pass(self):
        self.stand.agent("com.spa.loop", [("data/a.json", None)])
        with self.assertRaises(sk.Unmeasured):
            self.stand.measure()

    def test_a_manifest_without_agents_is_UNMEASURED(self):
        target = self.stand.root / "architecture" / "manifest.json"
        target.write_text(json.dumps({"artifacts": []}))
        with self.assertRaises(sk.Unmeasured):
            sk.measure(target, log_dir=self.stand.root / "logs",
                       scripts_dir=self.stand.root / "scripts", now=_ANCHOR)

    def test_a_misshaped_artifacts_list_is_UNMEASURED_not_an_empty_promise_set(self):
        """`manifest_slo` на кривой форме отдаёт ПУСТОЕ отображение и ПРИЧИНУ.
        Промолчать о причине значило бы судить флот по неполному перечню сроков."""
        target = self.stand.root / "architecture" / "manifest.json"
        target.write_text(json.dumps({
            "agents": [{"label": "com.spa.loop", "intent": "active",
                        "program": "agent_loop.sh", "schedule": "interval:3600s",
                        "produces": [{"artifact": "data/a.json", "slo_hours": 3}]}],
            "artifacts": ["это не запись"]}))
        with self.assertRaises(sk.Unmeasured) as caught:
            sk.measure(target, log_dir=self.stand.root / "logs",
                       scripts_dir=self.stand.root / "scripts", now=_ANCHOR)
        self.assertIn("срок годности НЕ прочитан", str(caught.exception))

    def test_an_unreadable_manifest_is_UNMEASURED_and_names_the_file(self):
        missing = self.stand.root / "architecture" / "nope.json"
        with self.assertRaises(sk.Unmeasured) as caught:
            sk.measure(missing, log_dir=self.stand.root / "logs",
                       scripts_dir=self.stand.root / "scripts", now=_ANCHOR)
        self.assertIn("nope.json", str(caught.exception))


# ─────────────────── окно наблюдения — ВХОД, а не часы ───────────────────

class TheWindowIsAnInput(_StandCase):

    def test_a_run_older_than_the_window_is_outside_it(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 2)])
        self.stand.runs("loop", [0, 1, 2, 400])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["runs"], 3)
        self.assertEqual(row["observed_max_hours"], 1.0)

    def test_a_stamp_from_the_FUTURE_is_dropped_and_counted(self):
        """Сдвиг часов хоста не имеет права стать отрицательным периодом."""
        self.stand.agent("com.spa.loop", [("data/a.json", 2)])
        text = "".join(_banner(_ANCHOR - dt.timedelta(hours=h), "loop") for h in (0, 1, 2))
        text += _banner(_ANCHOR + dt.timedelta(hours=5), "loop")
        self.stand.raw_log("loop", text)
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["future_banners"], 1)
        self.assertEqual(row["runs"], 3)

    def test_shrinking_the_window_can_never_turn_a_finding_into_health(self):
        """Узкое окно обязано давать «НЕ ИЗМЕРЕНО», а не «выдерживаем»."""
        self.stand.agent("com.spa.loop", [("data/a.json", 9)])
        self.stand.runs("loop", [0, 10, 20, 30])
        wide = self.stand.measure()
        self.assertEqual(self.row(wide, "data/a.json")["verdict"], sk.UNKEEPABLE)
        narrow = self.row(self.stand.measure(window_hours=5.0), "data/a.json")
        self.assertEqual(narrow["verdict"], sk.UNMEASURED)
        self.assertIn(narrow["cause"], set(sk.CAUSE_RU),
                      "причина обязана быть ОБЪЯВЛЕННОЙ, а не вымышленной на ходу")

    def test_the_window_WIDENS_to_the_longest_declared_slo_so_it_cannot_blind_itself(self):
        """Окно 168ч при сроке 192ч делало бы находку недостижимой по построению —
        слепота была бы СВОЯ, а не чужая, и это худший её вид."""
        self.stand.agent("com.spa.loop", [("data/a.json", 192)])
        self.stand.runs("loop", [1, 100, 190, 300])
        doc = self.stand.measure(window_hours=168.0)
        self.assertEqual(doc["window_hours"], 168.0)
        self.assertEqual(doc["effective_window_hours"], 192.0)
        self.assertEqual(self.row(doc, "data/a.json")["runs"], 3)

    def test_the_window_is_recorded_in_the_document(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 1)])
        self.stand.runs("loop", [0, 0.5, 1.0])
        self.assertEqual(self.stand.measure(window_hours=12.0)["window_hours"], 12.0)


# ───────────── ось «расписание против наблюдения» — не вердикт ─────────────

class TheScheduleAxisIsNotTheVerdict(_StandCase):

    def test_the_declared_interval_is_read_in_both_forms(self):
        self.assertEqual(sk.parse_schedule("interval:3600s"), 1.0)
        self.assertEqual(sk.parse_schedule("interval:21600s"), 6.0)
        self.assertEqual(sk.parse_schedule("interval:6h"), 6.0)

    def test_a_calendar_list_gives_the_WIDEST_gap_not_the_average(self):
        """`05:00,06:00` — это два прогона в сутки и ждать между ними 23 часа.
        «24 / число отметок» соврало бы в сторону здоровья."""
        self.assertEqual(sk.parse_schedule("calendar:05:00,06:00"), 23.0)
        self.assertEqual(sk.parse_schedule("calendar:00:00,06:00,12:00,18:00"), 6.0)
        self.assertEqual(sk.parse_schedule("calendar:08:00"), 24.0)

    def test_a_weekly_calendar_counts_over_a_WEEK(self):
        self.assertEqual(sk.parse_schedule("calendar:wd0·10:00"), 168.0)
        self.assertEqual(sk.parse_schedule("calendar:wd2·04:00,wd5·04:00"), 96.0)

    def test_a_non_periodic_schedule_has_NO_invented_number(self):
        for raw in ("daemon", "manual", "event:watchpaths"):
            self.assertIsNone(sk.parse_schedule(raw), raw)
            self.assertTrue(sk.non_periodic(raw), raw)
        self.assertFalse(sk.non_periodic("interval:3600s"))

    def test_an_unreadable_schedule_form_is_None_not_zero(self):
        for raw in ("interval:every-hour", "calendar:утром", None, 3600):
            self.assertIsNone(sk.parse_schedule(raw), repr(raw))

    def test_schedule_unparsed_and_observation_absent_are_DIFFERENT_outcomes(self):
        """Форма объявлена верно, не хватает ЗАПИСИ — это не вина конституции."""
        self.stand.agent("com.spa.silent", [("data/a.json", 7)])
        self.stand.agent("com.spa.odd", [("data/b.json", 7)], schedule="interval:every-hour")
        self.stand.runs("odd", [0, 1, 2, 3, 4, 5, 6, 7, 8])
        doc = self.stand.measure()
        self.assertEqual(self.row(doc, "data/a.json")["schedule_axis"],
                         sk.SCHEDULE_OBSERVATION_ABSENT)
        self.assertEqual(self.row(doc, "data/b.json")["schedule_axis"], sk.SCHEDULE_UNPARSED)

    def test_a_period_longer_than_the_declared_interval_does_not_itself_decide(self):
        """Ось EXCEEDS при выдерживаемом сроке — вердикт остаётся «выдерживаем»."""
        self.stand.agent("com.spa.loop", [("data/a.json", 26)], schedule="interval:3600s")
        self.stand.runs("loop", [h * 1.2 for h in range(0, 30)])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["schedule_axis"], sk.SCHEDULE_EXCEEDS)
        self.assertEqual(row["verdict"], sk.KEEPABLE)
        self.assertEqual(doc["tally"][sk.UNKEEPABLE], 0)

    def test_the_MAGNITUDE_of_the_divergence_is_reported_with_its_artifact(self):
        """Сам факт почти всегда верен (launchd считает от завершения), поэтому
        решает отношение: ADR-506 нашёл ×1.27, а не ×1.001."""
        self.stand.agent("com.spa.loop", [("data/a.json", 26)], schedule="interval:3600s")
        self.stand.runs("loop", [h * 1.5 for h in range(0, 30)])
        doc = self.stand.measure()
        worst = doc["worst_schedule_ratio"]
        self.assertEqual(worst["artifact"], "data/a.json")
        self.assertAlmostEqual(worst["ratio"], 1.5, places=2)

    def test_the_axis_sum_is_declared_separately_from_the_tally(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        doc = self.stand.measure()
        self.assertEqual(sum(doc["tally"].values()), doc["population"])


# ─────────────── запас на один пропуск — ОСЬ, а не вердикт ───────────────

class TheMarginIsAnAxis(_StandCase):

    def test_no_margin_for_one_miss_is_counted_but_stays_keepable(self):
        """Пол Архитектора (такт × 2) — правило ADR-158, и вердикт на нём не стоит."""
        self.stand.agent("com.spa.loop", [("data/a.json", 15)], schedule="calendar:08:00,20:00")
        self.stand.runs("loop", [2, 14, 26, 38, 50, 62, 74, 86])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["verdict"], sk.KEEPABLE)
        self.assertEqual(doc["no_margin_for_one_miss"], 1)
        self.assertEqual(doc["margin_factor"], 2.0)

    def test_a_promise_with_room_for_one_miss_is_not_counted(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        self.assertEqual(self.stand.measure()["no_margin_for_one_miss"], 0)


# ─────────────────────── коды возврата и артефакт ───────────────────────

class ExitCodesSeparateThreeOutcomes(_StandCase):

    def _argv(self, **kw):
        argv = ["--manifest", str(self.stand.write()),
                "--log-dir", str(self.stand.root / "logs"),
                "--scripts-dir", str(self.stand.root / "scripts")]
        for key, value in kw.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        return argv

    def test_everything_keepable_exits_zero(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        self.assertEqual(sk.main(self._argv()), 0)

    def test_a_finding_exits_one(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 5)])
        self.stand.runs("loop", [0, 9, 18, 27])
        self.assertEqual(sk.main(self._argv()), 1)

    def test_ONLY_unmeasured_still_exits_one_never_zero(self):
        """fail-OPEN тише красного, поэтому опаснее: «не измерено» не есть «чисто»."""
        self.stand.agent("com.spa.loop", [("data/a.json", 7)])
        self.assertEqual(sk.main(self._argv()), 1)

    def test_no_measurement_at_all_exits_two(self):
        self.stand.agent("com.spa.loop", [("data/a.json", None)])
        self.assertEqual(sk.main(self._argv()), 2)

    def test_the_three_codes_are_DISTINCT(self):
        self.assertEqual(len({0, 1, 2}), 3)


class TheArtifactCarriesItsOwnTally(_StandCase):
    """Урок ADR-547: вердикт доходит до читателя только артефактом, и счёт в нём
    обязан быть ПРОЧИТАН, а не сложен читателем заново (вторая копия мерки)."""

    def test_run_writes_a_document_whose_tally_can_be_READ(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 5)])
        self.stand.runs("loop", [0, 9, 18, 27])
        self.stand.write()
        out = self.stand.root / "data" / sk.ARTIFACT
        result = sk.run(root=self.stand.root, dest=out, log_dir=self.stand.root / "logs",
                        scripts_dir=self.stand.root / "scripts", now=_ANCHOR)
        self.assertTrue(result["measured"])
        doc = json.loads(out.read_text())
        self.assertEqual(doc["status"], "OK")
        for field in ("tally", "population", "verdict", "unmeasured_causes",
                      "schedule_axis", "window_hours", "findings"):
            self.assertIn(field, doc, field)
        self.assertEqual(doc["tally"][sk.UNKEEPABLE], 1)

    def test_run_writes_a_document_EVEN_when_the_measurement_failed(self):
        """Иначе один отказ сделал бы артефакт нечитаемым, а шаг 0-офис
        сказал бы «не прочитан» об исправном модуле."""
        (self.stand.root / "architecture" / "manifest.json").write_text("{не json")
        out = self.stand.root / "data" / sk.ARTIFACT
        sk.run(root=self.stand.root, dest=out, log_dir=self.stand.root / "logs",
               now=_ANCHOR)
        doc = json.loads(out.read_text())
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertTrue(doc["reason"])
        self.assertIn("generated_at", doc)

    def test_the_document_NAMES_what_it_does_not_report(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        doc = self.stand.measure()
        self.assertTrue(doc["not_reported"])
        self.assertTrue(any("СТАРТ" in line for line in doc["not_reported"]))
        self.assertEqual(doc["measured_from"]["manifest"],
                         str(self.stand.root / "architecture" / "manifest.json"))


class TheReportRefusesToClaimHealth(_StandCase):

    def test_an_unmeasured_document_renders_as_НЕ_ИЗМЕРЕНО(self):
        lines = sk.report({"status": "UNMEASURED", "reason": "конституция не прочитана"})
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines))
        self.assertFalse(any("ВЫДЕРЖИВАЕМ" in line for line in lines),
                         "о сроках не сказано ничего — печатать счёт нельзя")

    def test_the_report_prints_the_tally_the_causes_and_the_blindness(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 5)])
        self.stand.agent("com.spa.mute", [("data/b.json", 5)])
        self.stand.runs("loop", [0, 9, 18, 27])
        lines = sk.report(self.stand.measure())
        text = "\n".join(lines)
        self.assertIn("ВЫДЕРЖИВАЕМ", text)
        self.assertIn(sk.RECORD_ABSENT, text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)
        self.assertIn("ADVISORY", text)

    def test_a_tally_with_a_missing_key_prints_НЕ_ИЗМЕРЕНО_not_zero(self):
        lines = sk.report({"status": "OK", "tally": {}, "population": 3,
                           "unmeasured_causes": {}, "schedule_axis": {},
                           "findings": [], "not_reported": []})
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(lines))

    def test_format_report_indents_for_the_office_step(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)])
        self.stand.runs("loop", list(range(0, 40)))
        doc = self.stand.measure()
        self.assertTrue(all(line.startswith("   ") for line in sk.format_report(doc)))


# ───────────────────────────── проводка ─────────────────────────────

class TheStageIsWiredNotJustWritten(unittest.TestCase):
    """Написать прибор и не позвать его — то же, что не написать (ADR-259)."""

    def test_the_stage_is_declared_in_the_bridge_composition(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("slo_keepability", fb.CENSUS_STAGE)
        self.assertIn("data/slo_keepability.json", fb.PRODUCES)
        self.assertEqual(fb.CENSUS_PRODUCT["slo_keepability"],
                         {"module": "spa_core/monitoring/slo_keepability.py",
                          "artifact": "data/slo_keepability.json"})

    def test_the_bridge_CALLS_the_stage_and_an_import_is_not_a_call(self):
        """Урок ADR-547: храповик проводки считает проводкой ЛЮБУЮ ссылку, и один
        импорт делает сироту «подключённой» молча. Здесь спрашивается ЗОВ."""
        import ast
        source = (_REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        aliases = {alias.asname or alias.name
                   for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                   for alias in node.names if alias.name == "slo_keepability"}
        self.assertTrue(aliases, "модуль ступени не ввезён вовсе")
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "run"
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id in aliases]
        self.assertTrue(calls, "ступень ввезена, но НЕ позвана — импорт не есть вызов")

    def test_the_artifact_is_declared_in_the_manifest_with_a_producer_and_an_slo(self):
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(a for a in man["artifacts"]
                     if a.get("path") == "data/slo_keepability.json")
        self.assertEqual(entry["producer"], "com.spa.decision_loop")
        self.assertEqual(entry["status"], "active")
        self.assertTrue(entry["consumers"])
        produced = [p for a in man["agents"] if a.get("label") == "com.spa.decision_loop"
                    for p in a.get("produces", [])
                    if p.get("artifact") == "data/slo_keepability.json"]
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0]["slo_hours"], entry["slo_hours"])

    def test_its_OWN_declared_slo_exceeds_the_runner_period_it_measures(self):
        """Объявить 7ч значило бы воспроизвести ровно тот дефект, который прибор
        меряет: наблюдённый период бегуна ≈7.6ч (ADR-506), гейт моста 6ч."""
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(a for a in man["artifacts"]
                     if a.get("path") == "data/slo_keepability.json")
        self.assertGreater(entry["slo_hours"], 6.0 + 7.6)

    def test_the_office_step_has_a_NAMED_branch_and_a_schema(self):
        source = (_REPO / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn('elif name == "slo_keepability.json":', source)
        self.assertIn("from spa_core.monitoring.slo_keepability import format_report", source)
        sys.path.insert(0, str(_REPO / "scripts"))
        import consume_office_reports as office  # noqa: PLC0415
        schema = office._READ_SCHEMA["slo_keepability.json"]
        for field in ("status", "tally", "verdict", "unmeasured_causes", "window_hours"):
            self.assertIn(field, schema, field)

    def test_the_SLO_number_comes_from_the_single_reader_not_a_second_copy(self):
        """Число верхнего дома берётся у `manifest_slo` (ADR-342): второй копии
        правила «какой срок в силе» прибор не заводит."""
        import ast
        source = (_REPO / "spa_core" / "monitoring" / "slo_keepability.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module
                    and node.module.endswith("manifest_slo") for alias in node.names}
        self.assertIn("slo_hours_by_path", imported)


class TheLogAddressIsMeasuredNotAssumed(_StandCase):
    """Соглашение `com.spa.X` → `/tmp/spa_X.log` — соглашение, а не замер: имя
    читается ИЗ ОБЁРТКИ, которую запускает launchd."""

    def test_mode_A_declares_the_name_with_an_assignment(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)], wrapper=_WRAPPER_A,
                         name="watchdog")
        self.stand.runs("watchdog", list(range(0, 40)))
        self.assertEqual(self.row(self.stand.measure(), "data/a.json")["verdict"], sk.KEEPABLE)

    def test_mode_B_declares_the_name_as_a_template_argument(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)], wrapper=_WRAPPER_B,
                         name="decision_loop")
        self.stand.runs("decision_loop", list(range(0, 40)))
        self.assertEqual(self.row(self.stand.measure(), "data/a.json")["verdict"], sk.KEEPABLE)

    def test_a_COMMENT_naming_the_template_is_not_a_declaration(self):
        """Первая редакция резолвера приняла слово из комментария за имя агента и
        «нашла» агента по имени `(canonical` у 44 обёрток из 54."""
        name, cause = sk.log_address("agent_x.sh", self.stand.root / "scripts")
        self.assertIsNone(name)
        (self.stand.root / "scripts" / "agent_x.sh").write_text(
            "#!/bin/bash\n# Generated from scripts/agent_template.sh (canonical pattern).\n"
            "export AGENT_NAME=\"real_name\"\nexec /bin/bash tpl\n")
        name, cause = sk.log_address("agent_x.sh", self.stand.root / "scripts")
        self.assertEqual(name, "real_name")
        self.assertIsNone(cause)

    def test_a_comment_naming_a_DIFFERENT_agent_does_not_win_over_the_real_call(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)],
                         wrapper=_WRAPPER_COMMENT_DECOY, name="real_name")
        self.stand.runs("real_name", list(range(0, 40)))
        self.stand.runs("decoy_name", [0, 50])
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json")
        self.assertEqual(row["verdict"], sk.KEEPABLE)
        self.assertIn("spa_real_name.log", row["records"][0])

    def test_the_record_path_is_reported_so_a_reader_can_check_it(self):
        self.stand.agent("com.spa.loop", [("data/a.json", 26)], name="loop")
        self.stand.runs("loop", list(range(0, 40)))
        row = self.row(self.stand.measure(), "data/a.json")
        self.assertIn("spa_loop.log", row["records"][0])


if __name__ == "__main__":
    unittest.main()
