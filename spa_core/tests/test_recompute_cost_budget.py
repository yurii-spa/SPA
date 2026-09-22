"""Заказ G69 п. 1: цена пересчёта — ИЗМЕРЕННАЯ величина, а не объявленный литерал.

ADR-446 оставил остаток «прогон не оплачен» и назвал ему цену **35 с**. Число
это было снято одним прогоном на одном дереве и записано в таблицу руками:
свойством читателя оно не является, а вердикт «не по карману» на нём стоял.
Заказ спрашивает числом — сколько стои́т пересчёт каждого читателя и
укладывается ли он в такт ступени.

Каждый тест здесь — положительный контроль с ОБРАТНОЙ стороной: проверяется не
только, что прибор говорит нужное на исправном стенде, но и что он ЗАГОВОРИЛ БЫ
иначе, будь состояние обратным. Стенд одноразовый; живой трекер, живое `data/`
и рабочее дерево не трогаются.

Ни литеральной даты, ни литерального pid здесь нет вовсе: прибор читает
исходники и манифест стенда, а часы участвуют только как ИЗМЕРИТЕЛЬ цены —
никакая проверка не сравнивает время с календарём (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as rscc

from spa_core.monitoring.rule_second_copy_census import (
    BUDGET_ARTIFACT,
    BUDGET_DOES_NOT_FIT,
    BUDGET_FITS,
    BUDGET_MANIFEST,
    BUDGET_TOO_CLOSE,
    BUDGET_UNMEASURED,
    COST_BASIS_BOTH,
    COST_BASIS_WIDENED,
    COST_CLAIM_TOLERANCE,
    DECISION_NOT_EXECUTED,
    DECISION_UNCHANGED,
    PRODUCER,
    REQUIRED_COST_MARGIN,
    _projection_is_vacuous,
    _scale_projection,
    _tact_seconds,
    recompute_cost_budget,
    report,
)


def _manifest(schedule: object = "interval:21600s",
              artifact: str = BUDGET_ARTIFACT,
              label: str = "com.spa.decision_loop") -> dict:
    return {"agents": [
        {"label": "com.spa.other", "schedule": "interval:60s",
         "produces": [{"artifact": "data/other.json"}]},
        {"label": label, "schedule": schedule,
         "produces": [{"artifact": artifact}]},
    ]}


class Stand:
    """Одноразовое дерево с манифестом. Прибор читает ФАЙЛ, а не память."""

    def __init__(self, manifest: object = None) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        if manifest is not None:
            self.write_manifest(manifest)

    def write_manifest(self, manifest: object) -> None:
        path = self.root / BUDGET_MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (manifest if isinstance(manifest, str)
                else json.dumps(manifest, ensure_ascii=False))
        path.write_text(text, encoding="utf-8")

    def close(self) -> None:
        self._tmp.cleanup()


def _harm(executed: list) -> dict:
    return {"status": "MEASURED", "executed": executed}


def _entry(key: str, *, measured: object = 10.0, declared: object = 10,
           outcome: str = DECISION_UNCHANGED,
           basis: str = COST_BASIS_WIDENED, runs: int = 1) -> dict:
    row = {"key": key, "outcome": outcome, "cost_s_declared": declared,
           "cost_basis": basis, "runs_timed": runs}
    if measured is not None:
        row["cost_s_measured"] = measured
    return row


class TactSecondsTests(unittest.TestCase):
    """Бюджет ЧИТАЕТСЯ у объявителя. Своя копия такта была бы второй копией
    правила — ровно тем, что эта перепись ищет у других."""

    def setUp(self) -> None:
        self.stand = Stand(_manifest())
        self.addCleanup(self.stand.close)

    def test_the_tact_is_read_from_the_producer_of_the_artifact(self) -> None:
        seconds, source, refused = _tact_seconds(self.stand.root)
        self.assertEqual(seconds, 21600.0)
        self.assertIsNone(refused)
        self.assertIn("com.spa.decision_loop", source)

    def test_a_DIFFERENT_interval_in_the_manifest_gives_a_DIFFERENT_budget(self) -> None:
        """Обратная сторона и положительный контроль разом: число приходит из
        ФАЙЛА. Вписанная в код константа этот тест не прошла бы."""
        self.stand.write_manifest(_manifest(schedule="interval:900s"))
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertEqual(seconds, 900.0)
        self.assertIsNone(refused)

    def test_no_producer_of_the_artifact_is_a_NAMED_refusal_not_a_default(self) -> None:
        self.stand.write_manifest(_manifest(artifact="data/someone_else.json"))
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn(BUDGET_ARTIFACT, refused)

    def test_an_unreadable_manifest_is_a_NAMED_refusal(self) -> None:
        self.stand.write_manifest("{not json")
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn(BUDGET_MANIFEST, refused)

    def test_an_absent_manifest_is_a_NAMED_refusal(self) -> None:
        stand = Stand()
        self.addCleanup(stand.close)
        seconds, _source, refused = _tact_seconds(stand.root)
        self.assertIsNone(seconds)
        self.assertIn(BUDGET_MANIFEST, refused)

    def test_a_manifest_without_an_agent_list_is_a_NAMED_refusal(self) -> None:
        self.stand.write_manifest({"agents": "нет"})
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn("списка агентов", refused)

    def test_a_schedule_that_is_not_an_interval_is_a_NAMED_refusal(self) -> None:
        self.stand.write_manifest(_manifest(schedule="calendar:08:00"))
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn("calendar:08:00", refused)

    def test_a_non_numeric_interval_is_a_NAMED_refusal(self) -> None:
        self.stand.write_manifest(_manifest(schedule="interval:часs"))
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn("не разбирается", refused)

    def test_a_non_positive_interval_is_a_NAMED_refusal_not_a_zero_budget(self) -> None:
        """Нулевой такт прошёл бы дальше как число и дал бы деление на ноль
        либо «не укладывается» из пустоты."""
        self.stand.write_manifest(_manifest(schedule="interval:0s"))
        seconds, _source, refused = _tact_seconds(self.stand.root)
        self.assertIsNone(seconds)
        self.assertIn("не положителен", refused)

    def test_a_schedule_of_the_WRONG_agent_is_not_taken(self) -> None:
        """Обратная сторона отбора: такт берётся у производителя ЭТОГО
        артефакта, а не у первого агента списка."""
        seconds, _source, _refused = _tact_seconds(self.stand.root)
        self.assertNotEqual(seconds, 60.0)


class BudgetVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stand = Stand(_manifest())
        self.addCleanup(self.stand.close)

    def test_a_cheap_recompute_FITS_and_the_margin_is_a_number(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root, _harm([_entry("a", measured=60.0, declared=60)]))
        self.assertEqual(doc["verdict"], BUDGET_FITS)
        self.assertEqual(doc["budget_s"], 21600.0)
        self.assertEqual(doc["total_cost_s"], 60.0)
        self.assertEqual(doc["margin"], 360.0)
        self.assertEqual(doc["status"], "MEASURED")

    def test_a_recompute_DEARER_than_the_tact_does_NOT_fit_and_is_CRITICAL(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=30000.0, declared=30000)]))
        self.assertEqual(doc["verdict"], BUDGET_DOES_NOT_FIT)
        self.assertEqual(doc["status"], "CRITICAL")

    def test_a_cost_inside_the_tact_but_under_the_declared_margin_is_a_THIRD_outcome(self) -> None:
        """Цена измерена на ОДНОЙ машине. Ответ, который сменился бы от её
        неточности, не есть ответ — и «уложились» из него делать нельзя."""
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=21600.0 / 2, declared=1)]))
        self.assertEqual(doc["verdict"], BUDGET_TOO_CLOSE)
        self.assertLess(doc["margin"], REQUIRED_COST_MARGIN)
        self.assertNotEqual(doc["verdict"], BUDGET_FITS)

    def test_the_required_margin_is_DECLARED_in_the_document(self) -> None:
        """Запрет G62: запас объявлен ДО замера, иначе «уложились» читалось бы
        как выбор удобного порога после результата."""
        doc = recompute_cost_budget(self.stand.root, _harm([_entry("a")]))
        self.assertEqual(doc["required_margin_declared"], REQUIRED_COST_MARGIN)
        self.assertEqual(doc["claim_tolerance_declared"], COST_CLAIM_TOLERANCE)

    def test_the_coordinate_is_ADVISORY(self) -> None:
        doc = recompute_cost_budget(self.stand.root, _harm([_entry("a")]))
        self.assertFalse(doc["applied"])

    def test_an_unreadable_budget_is_UNMEASURED_not_a_fit(self) -> None:
        self.stand.write_manifest("{")
        doc = recompute_cost_budget(self.stand.root, _harm([_entry("a")]))
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertNotEqual(doc["verdict"], BUDGET_FITS)

    def test_an_absent_harm_is_UNMEASURED_with_a_reason(self) -> None:
        doc = recompute_cost_budget(self.stand.root, None)
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIn("НЕ «уложились»", doc["reason"])

    def test_a_harm_without_an_executed_list_is_UNMEASURED(self) -> None:
        doc = recompute_cost_budget(self.stand.root, {"status": "UNMEASURED"})
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)

    def test_no_priced_reader_is_UNMEASURED_not_a_zero_cost_fit(self) -> None:
        """Обратная сторона: «никого не мерили» и «пересчёт бесплатен» — два
        разных утверждения, и второе вместо первого есть fail-OPEN."""
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=None, outcome=DECISION_NOT_EXECUTED)]))
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIsNone(doc["total_cost_s"])
        self.assertIn("делить бюджет не на что", doc["budget_refused"])

    def test_a_measured_cost_of_zero_is_UNMEASURED_not_an_infinite_margin(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root, _harm([_entry("a", measured=0.0)]))
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIsNone(doc["margin"])

    def test_costs_of_SEVERAL_readers_are_summed_not_taken_one_by_one(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root, _harm([_entry("a", measured=10.0),
                                    _entry("b", measured=25.0)]))
        self.assertEqual(doc["total_cost_s"], 35.0)
        self.assertEqual(doc["counts"]["priced"], 2)

    def test_a_non_dict_row_in_executed_does_not_crash_the_measure(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root, _harm(["мусор", _entry("a", measured=5.0)]))
        self.assertEqual(doc["counts"]["readers"], 1)


class ClaimTests(unittest.TestCase):
    """Объявленная цена оставлена как ПРЕТЕНЗИЯ и сверяется с замером."""

    def setUp(self) -> None:
        self.stand = Stand(_manifest())
        self.addCleanup(self.stand.close)

    def test_a_declared_cost_close_to_the_measured_one_is_CONFIRMED(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=36.0, declared=35)]))
        self.assertEqual(doc["costs"][0]["claim"], "confirmed")
        self.assertEqual(doc["costs"][0]["cost_s_per_run"], 36.0)
        self.assertEqual(doc["counts"]["claims_confirmed"], 1)
        self.assertEqual(doc["counts"]["claims_refuted"], 0)

    def test_a_declared_cost_far_from_the_measured_one_is_REFUTED_and_named(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=200.0, declared=35)]))
        self.assertEqual(doc["costs"][0]["claim"], "refuted")
        kinds = [f["kind"] for f in doc["findings"]]
        self.assertIn("declared_cost_refuted_by_measurement", kinds)

    def test_an_unmeasured_cost_is_NOT_a_confirmed_claim(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=None, outcome=DECISION_NOT_EXECUTED)]))
        self.assertEqual(doc["costs"][0]["claim"], "unmeasured")
        self.assertEqual(doc["counts"]["claims_confirmed"], 0)
        self.assertIn("НЕ нулевая цена", doc["costs"][0]["claim_reason"])

    def test_a_reader_without_a_declared_cost_says_so_rather_than_confirming(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=12.0, declared=None)]))
        self.assertEqual(doc["costs"][0]["claim"], "undeclared")

    def test_the_claim_is_checked_against_the_price_of_ONE_run(self) -> None:
        """Объявленная цена (ADR-446) была ценой ОДНОГО прогона, а измеряется
        весь пересчёт. Сверить их напрямую значило бы сравнить числа с РАЗНЫМИ
        знаменателями и назвать разницу ошибкой претензии."""
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=80.0, declared=35,
                          basis=COST_BASIS_BOTH, runs=2)]))
        self.assertEqual(doc["costs"][0]["cost_s_per_run"], 40.0)
        self.assertEqual(doc["costs"][0]["claim"], "confirmed")
        # Обратная сторона: та же полная цена при ОДНОМ прогоне — претензия
        # опровергнута, и это другой ответ на тот же вход.
        other = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=80.0, declared=35, runs=1)]))
        self.assertEqual(other["costs"][0]["cost_s_per_run"], 80.0)
        self.assertEqual(other["costs"][0]["claim"], "refuted")

    def test_a_cost_without_a_run_counter_is_UNMEASURED_not_confirmed(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=80.0, declared=35, runs=0)]))
        self.assertEqual(doc["costs"][0]["claim"], "unmeasured")
        self.assertIn("разных знаменателей", doc["costs"][0]["claim_reason"])

    def test_the_basis_of_the_measured_cost_travels_with_the_number(self) -> None:
        """Маржинальная цена и цена двух прогонов — разные числа, и молча
        сложить их значило бы ответить не на тот вопрос."""
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("a", measured=12.0, basis=COST_BASIS_BOTH, runs=2)]))
        self.assertEqual(doc["costs"][0]["cost_basis"], COST_BASIS_BOTH)
        self.assertEqual(doc["costs"][0]["runs_timed"], 2)


class RemainderTests(unittest.TestCase):
    """Главный ответ заказа: неоплаченный прогон при укладывающемся бюджете
    есть ОТКАЗ ОТ ЗАМЕРА, а не остаток."""

    def setUp(self) -> None:
        self.stand = Stand(_manifest())
        self.addCleanup(self.stand.close)

    def test_an_unpaid_reader_under_a_fitting_budget_is_a_FINDING(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("paid", measured=60.0, declared=60),
                   _entry("unpaid", measured=None, declared=35,
                          outcome=DECISION_NOT_EXECUTED)]))
        kinds = [f["kind"] for f in doc["findings"]]
        self.assertIn("unpaid_recompute_was_affordable", kinds)
        finding = next(f for f in doc["findings"]
                       if f["kind"] == "unpaid_recompute_was_affordable")
        self.assertEqual(finding["fields"], ["unpaid"])
        self.assertEqual(finding["file"], PRODUCER)
        self.assertEqual(doc["counts"]["remainder"], 1)

    def test_an_unpaid_reader_under_a_budget_that_does_NOT_fit_is_NOT_a_finding(self) -> None:
        """Обратная сторона: когда пересчёт и правда дорог, «не оплачено»
        остаётся честным остатком, и объявлять его отказом нельзя."""
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("paid", measured=30000.0, declared=30000),
                   _entry("unpaid", measured=None,
                          outcome=DECISION_NOT_EXECUTED)]))
        kinds = [f["kind"] for f in doc["findings"]]
        self.assertNotIn("unpaid_recompute_was_affordable", kinds)

    def test_no_remainder_at_all_leaves_the_finding_silent(self) -> None:
        doc = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("paid", measured=60.0, declared=60)]))
        self.assertEqual(doc["counts"]["remainder"], 0)
        self.assertEqual(doc["findings"], [])


class VacuousProjectionTests(unittest.TestCase):
    """Совпадение ПУСТОТ не есть «решение то же»."""

    def test_a_projection_with_nothing_observed_is_vacuous(self) -> None:
        self.assertTrue(_projection_is_vacuous(
            {"status": None, "counts_observed": False,
             "findings_observed": False}))

    def test_one_observed_field_is_enough_to_make_it_NOT_vacuous(self) -> None:
        self.assertFalse(_projection_is_vacuous(
            {"status": None, "counts_observed": True,
             "findings_observed": False}))

    def test_a_named_status_is_enough_to_make_it_NOT_vacuous(self) -> None:
        self.assertFalse(_projection_is_vacuous(
            {"status": "UNMEASURED", "counts_observed": False}))

    def test_a_projection_WITHOUT_observation_flags_is_vacuous_too(self) -> None:
        """Проектор, забывший признаки наблюдённости, сам есть вырожденность:
        по нему нельзя отличить «поля нет» от «поле пусто»."""
        self.assertTrue(_projection_is_vacuous({"status": None, "x": 1}))


class ScaleProjectionTests(unittest.TestCase):
    """Проекция второго читателя — СВОЯ. Общая дала бы у него сплошной
    ``None``, то есть «решение не изменилось» из пустоты."""

    def test_absent_counts_and_empty_counts_are_DIFFERENT_decisions(self) -> None:
        absent = _scale_projection({"status": "OK"})
        empty = _scale_projection({"status": "OK", "counts": {}})
        self.assertNotEqual(absent, empty)
        self.assertFalse(absent["counts_observed"])
        self.assertTrue(empty["counts_observed"])

    def test_the_understated_list_is_part_of_the_decision(self) -> None:
        one = _scale_projection({"status": "CRITICAL", "understated": ["a"]})
        two = _scale_projection({"status": "CRITICAL",
                                 "understated": ["a", "b"]})
        self.assertNotEqual(one, two)

    def test_the_same_list_in_another_ORDER_is_the_same_decision(self) -> None:
        one = _scale_projection({"status": "CRITICAL",
                                 "understated": ["a", "b"]})
        two = _scale_projection({"status": "CRITICAL",
                                 "understated": ["b", "a"]})
        self.assertEqual(one, two)

    def test_the_counters_of_the_scale_travel_in_the_projection(self) -> None:
        doc = {"status": "CRITICAL",
               "counts": {"understated": 43, "understated_upper_bound": 47,
                          "blanked_to_zero": 0}}
        got = _scale_projection(doc)
        self.assertEqual(got["understated_count"], 43)
        self.assertEqual(got["understated_upper_bound"], 47)
        self.assertEqual(got["blanked_to_zero_count"], 0)

    def test_finding_kinds_are_part_of_the_decision(self) -> None:
        one = _scale_projection({"status": "CRITICAL", "findings": []})
        two = _scale_projection({"status": "CRITICAL",
                                 "findings": [{"kind": "k"}]})
        self.assertNotEqual(one, two)

    def test_an_empty_projection_of_an_empty_doc_is_recognised_as_vacuous(self) -> None:
        self.assertTrue(_projection_is_vacuous(_scale_projection({})))


class ReportTests(unittest.TestCase):
    """Число, которого не видно в отчёте, до оркестратора не доезжает."""

    def setUp(self) -> None:
        self.stand = Stand(_manifest())
        self.addCleanup(self.stand.close)
        self.budget = recompute_cost_budget(
            self.stand.root,
            _harm([_entry("paid", measured=60.0, declared=60),
                   _entry("unpaid", measured=None, declared=35,
                          outcome=DECISION_NOT_EXECUTED)]))

    def _lines(self, doc: dict) -> str:
        return "\n".join(report(doc))

    def test_the_section_prints_the_cost_the_budget_and_the_margin(self) -> None:
        text = self._lines({"recompute_cost_budget": self.budget})
        self.assertIn("[ЦЕНА ПЕРЕСЧЁТА]", text)
        self.assertIn("21600", text)
        self.assertIn("360.0", text)

    def test_the_finding_reaches_the_report(self) -> None:
        text = self._lines({"recompute_cost_budget": self.budget})
        self.assertIn("unpaid_recompute_was_affordable", text)

    def test_an_ABSENT_key_prints_NOT_MEASURED_rather_than_silence(self) -> None:
        """Мутация проводки: снятый из документа ключ обязан быть ВИДЕН."""
        text = self._lines({})
        self.assertIn("[ЦЕНА ПЕРЕСЧЁТА] НЕ ИЗМЕРЕНА", text)

    def test_an_unmeasured_budget_prints_its_REASON(self) -> None:
        self.stand.write_manifest("{")
        doc = recompute_cost_budget(self.stand.root,
                                    _harm([_entry("a", measured=5.0)]))
        text = self._lines({"recompute_cost_budget": doc})
        self.assertIn("НЕ ИЗМЕРЕНА", text)
        self.assertIn(BUDGET_MANIFEST, text)


class WiringTests(unittest.TestCase):
    """Проводка меряется ФОРМОЙ ЗОВА, а не наличием имени в файле: координата,
    посчитанная и не положенная в документ, до оркестратора не доезжает."""

    def setUp(self) -> None:
        self.tree = ast.parse(
            Path(rscc.__file__).read_text(encoding="utf-8"))
        self.measure = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "measure")

    def test_measure_calls_the_coordinate_and_carries_it_under_its_key(self) -> None:
        bound = set()
        for node in ast.walk(self.measure):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "recompute_cost_budget"):
                bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        self.assertTrue(bound, "measure() не зовёт recompute_cost_budget()")
        carried = {}
        for node in ast.walk(self.measure):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant)
                            and isinstance(value, ast.Name)):
                        carried[key.value] = value.id
        self.assertIn("recompute_cost_budget", carried)
        self.assertIn(carried["recompute_cost_budget"], bound)

    def test_the_coordinate_is_fed_the_harm_document_not_recomputed(self) -> None:
        """Вход у цены — уже посчитанный документ вреда: пересчитать его
        значило бы заплатить полторы минуты ни за что и померить ДРУГОЙ
        прогон, а не тот, чью цену называют."""
        call = next(node for node in ast.walk(self.measure)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "recompute_cost_budget")
        self.assertEqual(len(call.args), 2)
        self.assertEqual([a.id for a in call.args if isinstance(a, ast.Name)],
                         ["root", "population_harm"])

    def test_every_executable_reader_declares_a_projection_that_EXISTS(self) -> None:
        """Имя проекции — объявление ДО прогона; неизвестное имя означает
        третий исход, и молча сравнить чужой проекцией нельзя."""
        for spec in rscc._EXECUTABLE_READERS:
            self.assertIn(spec["project"], rscc._PROJECTORS, spec["key"])

    def test_every_executable_reader_has_a_runner_so_no_remainder_is_left(self) -> None:
        """Ответ заказа G69 п. 1: остатка «не оплачено» в таблице больше нет."""
        for spec in rscc._EXECUTABLE_READERS:
            self.assertTrue(spec["execute"], spec["key"])
            self.assertIn(spec["key"], rscc._HARM_RUNNERS, spec["key"])

    def test_the_budget_number_lives_in_the_manifest_and_NOT_in_the_code(self) -> None:
        """Прямая проверка на вторую копию правила: такт 21600 с объявлен
        манифестом, и перепечатанный в модуль литерал был бы ровно тем
        дефектом, который эта перепись ищет у других."""
        source = Path(rscc.__file__).read_text(encoding="utf-8")
        self.assertNotIn("21600", source)


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()
