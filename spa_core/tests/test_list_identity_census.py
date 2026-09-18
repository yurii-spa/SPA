"""Контроли переписи личности списков (заказ G34 п. 1, ADR-410).

Каждый тест — сцена, ломающая РОВНО одно звено. Правило семьи: контроль,
который никогда не видел настоящей поломки, есть украшение; поэтому у каждой
проверки есть обратная сторона — сцена, где прибор ОБЯЗАН промолчать.

Часы инъектируются везде, где вердикт от них зависит: литеральных дат в файле
нет вовсе, поэтому и пометки `FROZEN-DATE-OK` ему не нужно.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import _list_identity_probe as probe          # noqa: E402
from spa_core.monitoring import list_identity_census as census         # noqa: E402
from spa_core.monitoring.run_identity_key_price import (               # noqa: E402
    element_identity, indexed,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ClassifyOneList(unittest.TestCase):
    """Один список — один исход, и исходов пять, а не два."""

    def test_named_list_is_named_by_the_whitelisted_field(self):
        row = probe.classify_list([{"code": "a"}, {"code": "b"}])
        self.assertEqual(row["outcome"], "named")
        self.assertEqual(row["field"], "code")

    def test_dicts_without_any_usable_field_stay_positional(self):
        # Обратная сторона: годного поля нет ВООБЩЕ — третий исход честен, и
        # прибор не обязан ничего находить.
        row = probe.classify_list([{"sev": 1}, {"sev": 1}])
        self.assertEqual(row["outcome"], "unnamed_no_candidate")
        self.assertNotIn("candidates", row)

    def test_field_outside_the_whitelist_is_the_finding(self):
        row = probe.classify_list([{"label": "a"}, {"label": "b"}])
        self.assertEqual(row["outcome"], "unnamed_candidate_outside")
        self.assertEqual(row["candidates"], ["label"])

    def test_non_dict_elements_are_not_a_gap_in_the_whitelist(self):
        row = probe.classify_list([1, 2, 3])
        self.assertEqual(row["outcome"], "unnamed_not_dicts")

    def test_empty_list_has_nothing_to_name(self):
        self.assertEqual(probe.classify_list([])["outcome"], "unnamed_empty")

    def test_whitelisted_field_that_failed_is_named_with_its_cause(self):
        # `code` есть у обоих, но повторяется — «личности нет» здесь значит не
        # «имени не нашлось», а «имя нашлось и не годится». Без диагноза эти
        # два состояния неразличимы в отчёте.
        row = probe.classify_list([{"code": "a", "label": "p"},
                                   {"code": "a", "label": "q"}])
        self.assertEqual(row["whitelisted_rejected"], {"code": "not_unique"})


class VerdictIsNotASecondCopyOfTheRule(unittest.TestCase):
    """Классификатор не вправе судить иначе, чем судит сама перепись."""

    CORPUS = [
        [{"code": "a"}, {"code": "b"}],
        [{"code": "a"}, {"code": "a"}],
        [{"code": True}, {"code": False}],
        [{"code": {"x": 1}}, {"code": {"x": 2}}],
        [{"label": "a"}, {"label": "b"}],
        [{"sev": 1}, {"sev": 1}],
        [{"code": "a"}, {"label": "b"}],
        [{"id": 1}, {"id": 2}],
        [],
        [1, 2],
        [{"code": "solo"}],
    ]

    def test_named_iff_element_identity_names_it(self):
        for items in self.CORPUS:
            with self.subTest(items=items):
                row = probe.classify_list(items)
                mine = row.get("field")
                self.assertEqual(mine, element_identity(items))
                self.assertEqual(row["outcome"] == "named", mine is not None)

    def test_bool_is_never_an_identity(self):
        # Положительный контроль на оговорку самой переписи: True/False
        # уникальны в списке из двух — «личность» была бы совпадением.
        row = probe.classify_list([{"code": True}, {"code": False}])
        self.assertNotEqual(row["outcome"], "named")
        self.assertNotIn("code", row.get("candidates") or [])


class FieldVerdictCauses(unittest.TestCase):
    """Причина объясняет, вердикт решает — и они не путаются местами."""

    def test_absent_field_is_rejected_and_named_absent(self):
        ok, cause = probe.field_verdict([{"a": 1}, {}], "a")
        self.assertFalse(ok)
        self.assertEqual(cause, "field_absent")

    def test_non_scalar_is_rejected(self):
        ok, cause = probe.field_verdict([{"a": [1]}, {"a": [2]}], "a")
        self.assertFalse(ok)
        self.assertEqual(cause, "not_scalar")

    def test_repeated_value_is_rejected(self):
        ok, cause = probe.field_verdict([{"a": 1}, {"a": 1}], "a")
        self.assertFalse(ok)
        self.assertEqual(cause, "not_unique")

    def test_a_good_field_passes_with_no_cause(self):
        self.assertEqual(probe.field_verdict([{"a": 1}, {"a": 2}], "a"), (True, ""))


class CandidatePopulationIsTheUnionOfKeys(unittest.TestCase):
    """Кандидаты берутся у ВСЕХ элементов, а не у первого."""

    def test_field_seen_only_on_a_later_element_is_still_considered(self):
        items = [{"x": 1}, {"x": 2, "y": 9}]
        # `y` виден только у второго — он ОБЯЗАН быть рассмотрен и отвергнут
        # как отсутствующий у первого, а не пропущен молча.
        self.assertFalse(probe.field_verdict(items, "y")[0])
        self.assertEqual(probe.candidates_outside(items), ["x"])

    def test_field_present_everywhere_but_absent_from_the_first_key_order(self):
        items = [{"x": 1, "z": "p"}, {"z": "q", "x": 2}]
        self.assertEqual(probe.candidates_outside(items), ["x", "z"])

    def test_whitelisted_names_are_never_returned_as_outside(self):
        for name in probe.IDENTITY_FIELDS:
            with self.subTest(name=name):
                items = [{name: "a"}, {name: "b"}]
                self.assertNotIn(name, probe.candidates_outside(items))


class WalkUsesTheFamilyCoordinateRule(unittest.TestCase):
    """Координата пишется тем же правилом, что у соседей, — иначе не найдётся."""

    def test_children_of_a_named_list_carry_the_identity_suffix(self):
        answer = {"findings": [{"code": "a", "sub": [{"label": 1}, {"label": 2}]}]}
        rows = probe.walk_lists(answer, probe._Budget())
        coords = {r["coord"] for r in rows}
        expected = next(s for s, _ in indexed(answer["findings"], "code"))
        self.assertIn(f".findings{expected}.sub", coords)

    def test_children_of_an_unnamed_list_stay_positional(self):
        answer = {"rows": [{"sev": 1, "sub": [1]}, {"sev": 1, "sub": [2]}]}
        rows = probe.walk_lists(answer, probe._Budget())
        self.assertIn(".rows[0].sub", {r["coord"] for r in rows})

    def test_every_list_in_the_answer_is_reported_once(self):
        answer = {"a": [{"code": "x"}], "b": {"c": [1, 2]}}
        rows = probe.walk_lists(answer, probe._Budget())
        self.assertEqual(sorted(r["coord"] for r in rows), [".a", ".b.c"])


class WalkTerminatesAndSaysWhenItDidNot(unittest.TestCase):
    """«Не досмотрели» обязано быть отличимо от «не нашли»."""

    def test_budget_exhaustion_is_recorded_not_swallowed(self):
        deep = {"rows": [{"label": i} for i in range(50)]}
        budget = probe._Budget(limit=3)
        probe.walk_lists(deep, budget)
        self.assertTrue(budget.exhausted)

    def test_a_full_walk_does_not_claim_exhaustion(self):
        budget = probe._Budget()
        probe.walk_lists({"rows": [{"label": 1}, {"label": 2}]}, budget)
        self.assertFalse(budget.exhausted)

    def test_a_self_referencing_answer_terminates(self):
        node: dict = {"code": "a"}
        node["self"] = [node]
        probe.walk_lists({"top": [node]}, probe._Budget())  # не зависает


class TallyKeepsTheDenominatorHonest(unittest.TestCase):
    """Числитель без знаменателя — не число, а впечатление."""

    def test_singleton_candidates_do_not_enter_the_finding(self):
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 1, "outcome": "unnamed_candidate_outside",
             "candidates": ["label"]}]}}
        counts = census.tally(rows)
        self.assertEqual(counts["finding_rows"], [])
        self.assertEqual(counts["candidate_fields_outside"], {})
        self.assertEqual(counts["singletons"], 1)

    def test_a_real_multi_element_candidate_does_enter_the_finding(self):
        # Обратная сторона предыдущего: та же строка длиной два — находка.
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 2, "outcome": "unnamed_candidate_outside",
             "candidates": ["label"]}]}}
        counts = census.tally(rows)
        self.assertEqual(len(counts["finding_rows"]), 1)
        self.assertEqual(counts["candidate_fields_outside"], {"label": 1})

    def test_truncated_reader_is_named_and_kept_out_of_the_denominator(self):
        rows = {"m": {"entry": "measure", "truncated": True, "lists": [
            {"coord": ".a", "n": 2, "outcome": "unnamed_no_candidate"}]}}
        counts = census.tally(rows)
        self.assertEqual(counts["truncated_readers"], ["m"])
        self.assertEqual(counts["denominator_of_finding"], 0)

    def test_a_complete_reader_does_feed_the_denominator(self):
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 2, "outcome": "unnamed_no_candidate"}]}}
        self.assertEqual(census.tally(rows)["denominator_of_finding"], 1)

    def test_a_list_of_scalars_is_counted_beside_the_denominator_not_inside_it(self):
        # Первая редакция брала в знаменатель всякий `unnamed_*`, и списки
        # скаляров раздували его вчетверо под подписью «словари». Контроль
        # держит обе половины: скаляр — РЯДОМ, словарь — ВНУТРИ.
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".s", "n": 3, "outcome": "unnamed_not_dicts"},
            {"coord": ".d", "n": 3, "outcome": "unnamed_no_candidate"}]}}
        counts = census.tally(rows)
        self.assertEqual(counts["denominator_of_finding"], 1)
        self.assertEqual(counts["scalar_lists_multi"], 1)

    def test_empty_lists_never_reach_the_denominator(self):
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".e", "n": 0, "outcome": "unnamed_empty"}]}}
        self.assertEqual(census.tally(rows)["denominator_of_finding"], 0)

    def test_strength_keeps_the_longest_list_a_field_survived(self):
        # Сила свидетельства — длина, и берётся МАКСИМУМ: уникальность на двух
        # элементах почти неизбежна, на сорока трёх — свойство.
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 2, "outcome": "unnamed_candidate_outside",
             "candidates": ["coordinate"]},
            {"coord": ".b", "n": 43, "outcome": "unnamed_candidate_outside",
             "candidates": ["coordinate"]}]}}
        counts = census.tally(rows)
        self.assertEqual(counts["candidate_field_strength"]["coordinate"], 43)
        self.assertEqual(counts["candidate_fields_outside"]["coordinate"], 2)

    def test_singleton_never_contributes_strength(self):
        rows = {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 1, "outcome": "unnamed_candidate_outside",
             "candidates": ["coordinate"]}]}}
        self.assertEqual(census.tally(rows)["candidate_field_strength"], {})

    def test_uncallable_readers_are_counted_as_unmeasured_not_as_zero(self):
        rows = {"m": {"cause": "no_entry_point", "reason": "нет точки входа"}}
        counts = census.tally(rows)
        self.assertEqual(counts["unmeasured_causes"], {"no_entry_point": 1})
        self.assertEqual(counts["readers_measured"], 0)


class MeasureRefusesInsteadOfGuessing(unittest.TestCase):
    """Любое незакрытое звено даёт НЕ ИЗМЕРЕНО с причиной, а не CLEAN."""

    def test_stand_not_built_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "data"
            empty.mkdir()
            doc = census.measure(empty, ROOT, now=_now())
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("стенд", doc["reason"])

    def test_empty_population_is_unmeasured_not_clean(self):
        real = census.population
        try:
            census.population = lambda root: ([], {"python_branch": 0})
            doc = census.measure(Path(ROOT) / "data", ROOT, now=_now())
        finally:
            census.population = real
        self.assertEqual(doc["status"], "UNMEASURED")

    def _with_stand(self, answer, why: str = "") -> dict:
        """Сцена, где стенд ПОСТРОЕН, — чтобы вердикт решало плечо зонда.

        Рабочее дерево цикла живого ``data/`` не имеет по построению, и без
        этой подмены все сцены ниже упирались бы в «стенд не построен» — то
        есть проверяли бы не то звено, которое названо в их имени.
        """
        real_stand, real_probe = census.build_stands, census.run_probe
        try:
            census.build_stands = lambda src, dest, day=None: (
                {"s1": str(dest), "day": "-", "donor_day": "-"}, "")
            census.run_probe = lambda *a, **k: (answer, why)
            return census.measure(Path(ROOT) / "data", ROOT, now=_now())
        finally:
            census.build_stands, census.run_probe = real_stand, real_probe

    def test_probe_failure_is_unmeasured_not_clean(self):
        doc = self._with_stand(None, "зонд вышел кодом 1")
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("зонд", doc["reason"])

    def test_all_readers_unmeasured_is_unmeasured_not_clean(self):
        doc = self._with_stand(
            {"__modules__": {"m": {"cause": "no_entry_point", "reason": "-"}}})
        self.assertEqual(doc["status"], "UNMEASURED")

    def test_a_measured_population_without_findings_is_clean(self):
        # Обратная сторона: когда всё измерено и находок нет, прибор обязан
        # сказать CLEAN, а не прятаться в НЕ ИЗМЕРЕНО.
        doc = self._with_stand({"__modules__": {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 2, "outcome": "named", "field": "code"}]}}})
        self.assertEqual(doc["status"], "CLEAN")

    def test_a_measured_population_with_a_candidate_outside_is_a_finding(self):
        doc = self._with_stand({"__modules__": {"m": {"entry": "measure", "lists": [
            {"coord": ".a", "n": 2, "outcome": "unnamed_candidate_outside",
             "candidates": ["label"]}]}}})
        self.assertEqual(doc["status"], "FINDING")

    def test_generated_at_is_the_injected_moment(self):
        moment = _now() - dt.timedelta(days=3)
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "data"
            empty.mkdir()
            doc = census.measure(empty, ROOT, now=moment)
        self.assertEqual(doc["generated_at"], moment.isoformat())


class ProbeRefusesToRunAgainstTheLiveTree(unittest.TestCase):
    """Зонд без стенда или без часов ОБЯЗАН отказать, а не мерить."""

    def _run(self, env_extra: dict) -> int:
        env = dict(os.environ)
        env.pop(probe.STAND_ENV, None)
        env.pop(probe.CLOCK_ENV, None)
        env.update(env_extra)
        env["PYTHONPATH"] = str(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "m.json"
            mods.write_text(json.dumps([]), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring._list_identity_probe",
                 str(mods), str(Path(tmp) / "out.json")],
                cwd=str(ROOT), env=env, capture_output=True, timeout=120)
        return proc.returncode

    def test_no_stand_is_a_refusal(self):
        self.assertEqual(self._run({probe.CLOCK_ENV: _now().isoformat()}), 2)

    def test_no_clock_is_a_refusal(self):
        self.assertEqual(self._run({probe.STAND_ENV: str(ROOT)}), 2)

    def test_naive_clock_is_a_refusal(self):
        self.assertEqual(self._run({
            probe.STAND_ENV: str(ROOT),
            probe.CLOCK_ENV: _now().replace(tzinfo=None).isoformat()}), 2)

    def test_both_given_is_accepted(self):
        # Обратная сторона: отказ обязан быть следствием нехватки, а не
        # свойством зонда — иначе три проверки выше проходили бы всегда.
        self.assertEqual(self._run({
            probe.STAND_ENV: str(ROOT),
            probe.CLOCK_ENV: _now().isoformat()}), 0)


class ReportAndExitCode(unittest.TestCase):
    """Отчёт печатает знаменатель рядом с числителем; код возврата — вердикт."""

    def _doc(self, status: str, counts: dict) -> dict:
        return {"status": status, "reason": "-", "advisory": "-", "counts": counts}

    def test_denominator_is_printed_next_to_the_finding(self):
        lines = census.report(self._doc("FINDING", {
            "lists_total": 10, "outcomes": {"named": 4}, "singletons": 2,
            "denominator_of_finding": 3, "candidate_fields_outside": {"label": 1},
            "finding_rows": [{"module": "m", "coord": ".a", "n": 2,
                              "candidates": ["label"]}],
            "truncated_readers": [], "unmeasured_causes": {}, "named_fields": {}}))
        body = "\n".join(lines)
        self.assertIn("ЗНАМЕНАТЕЛЬ", body)
        self.assertIn("label", body)

    def test_unmeasured_report_says_so_and_stops(self):
        # Строка о ЗВАВШЕМ печатается перед этой (ADR-412) — на документе
        # UNMEASURED вопрос «кто это позвал» не менее интересен, чем на
        # измеренном. Проверка осталась ПОЗИЦИОННОЙ, то есть той же силы, и
        # заодно получила недостающую половину своего же имени: «и ОСТАНАВЛИВАЕТСЯ»
        # до сих пор не проверялось ничем.
        lines = census.report({"status": "UNMEASURED", "reason": "стенд не построен"})
        self.assertIn("[ЗВАВШИЙ]", lines[1])
        self.assertIn("[НЕ ИЗМЕРЕНО]", lines[2])
        self.assertEqual(len(lines), 3, f"отчёт не остановился: {lines}")

    def test_exit_codes_separate_the_three_outcomes(self):
        real = census.measure
        codes = {}
        try:
            for status, expected in (("CLEAN", 0), ("FINDING", 1), ("UNMEASURED", 2)):
                census.measure = (lambda *a, s=status, **k:
                                  {"status": s, "reason": "-", "advisory": "-",
                                   "counts": {"lists_total": 0, "outcomes": {},
                                              "singletons": 0,
                                              "denominator_of_finding": 0,
                                              "candidate_fields_outside": {},
                                              "finding_rows": [],
                                              "truncated_readers": [],
                                              "unmeasured_causes": {},
                                              "named_fields": {}}})
                codes[status] = census.main(["--no-write", "--data-dir", str(ROOT)])
                self.assertEqual(codes[status], expected)
        finally:
            census.measure = real


class TactIsDecidedByTheFile(unittest.TestCase):
    """Срок решает артефакт, а не расписание запуска."""

    def test_missing_artifact_means_measure(self):
        with tempfile.TemporaryDirectory() as tmp:
            due, why = census.measurement_due(
                Path(tmp) / census.ARTIFACT, now=_now(),
                tact_days=census.MEASUREMENT_TACT_DAYS)
        self.assertTrue(due)
        self.assertIn("артефакта нет", why)

    def test_fresh_artifact_means_do_not_measure(self):
        moment = _now()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / census.ARTIFACT
            path.write_text(json.dumps({"generated_at": moment.isoformat()}),
                            encoding="utf-8")
            due, _ = census.measurement_due(
                path, now=moment + dt.timedelta(days=1),
                tact_days=census.MEASUREMENT_TACT_DAYS)
        self.assertFalse(due)

    def test_artifact_older_than_the_tact_means_measure(self):
        moment = _now()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / census.ARTIFACT
            path.write_text(json.dumps({"generated_at": moment.isoformat()}),
                            encoding="utf-8")
            due, _ = census.measurement_due(
                path,
                now=moment + dt.timedelta(days=census.MEASUREMENT_TACT_DAYS + 1),
                tact_days=census.MEASUREMENT_TACT_DAYS)
        self.assertTrue(due)

    def test_unreadable_stamp_means_measure_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / census.ARTIFACT
            path.write_text("{не json", encoding="utf-8")
            due, why = census.measurement_due(
                path, now=_now(), tact_days=census.MEASUREMENT_TACT_DAYS)
        self.assertTrue(due)
        self.assertIn("не прочитана", why)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
