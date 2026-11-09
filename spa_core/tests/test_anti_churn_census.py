"""Батарея §22 (`spa_core/analytics/anti_churn_census.py`).

Каждый тест — контроль В ОБЕ СТОРОНЫ: зелёный на целом контуре и красный на
КАЖДОМ порванном звене, с названным звеном. Проверка подстрокой здесь
запрещена (ADR-333): «отчёт содержит слово ABSENT» ответило бы одинаково и на
верный замер, и на сломанную пробу.

Часы и журнал ходов сцен инъектируются от якоря модуля
(`anti_churn_census.SCENE_NOW` → `churn_damper.decide(now=...)` и отметки
журнала); стенных часов батарея не знает, и ЛИТЕРАЛЬНОЙ ДАТЫ в ней нет ни
одной — ожидаемые отметки ВЫЧИСЛЯЮТСЯ от якоря. Пометки о замороженной дате
здесь поэтому не нужно: класс закрыт не запиской, а отсутствием второй копии
якоря.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import unittest
from datetime import timedelta
from pathlib import Path

from spa_core.analytics import anti_churn_census as ACC
from spa_core.monitoring import cio_auto_execution_limits as L41

_SRC = Path(ACC.__file__)


class OwnerWordsAreDeclaredVerbatim(unittest.TestCase):
    """Пересказ теряет пункты, и расхождение обязано краснеть ТЕСТОМ."""

    def test_nine_params_named_verbatim_and_counted(self):
        self.assertEqual(ACC.OWNER_PARAMS, (
            "minimum yield edge",
            "minimum net gain",
            "minimum allocation delta",
            "minimum persistence",
            "minimum confidence",
            "cooldown",
            "maximum daily turnover",
            "rebalance cost budget",
            "decision expiry",
        ))
        self.assertEqual(len(ACC.OWNER_PARAMS), ACC.OWNER_PARAMS_DECLARED)

    def test_every_param_is_either_delegated_or_has_its_own_probe(self):
        """Третьего состояния нет: величина без обоих выпала бы молча."""
        for name in ACC.OWNER_PARAMS:
            with self.subTest(name):
                self.assertTrue(
                    (name in ACC.DELEGATED_TO_41) ^ (name in ACC.OWN_PROBES),
                    f"«{name}» не делегирована и не имеет своей пробы",
                )

    def test_swing_kinds_declare_the_unmeasured_outcome(self):
        self.assertIn(ACC.UNMEASURED, ACC.SWING_KINDS)


class TheScaleIsImportedNotCopied(unittest.TestCase):
    """Вторая шкала об одном предмете расходится МОЛЧА — поэтому её нет."""

    def test_vocabularies_are_imported_without_error(self):
        self.assertEqual(ACC._VOCAB_ERRORS, [])

    def test_the_five_labels_are_the_ones_section_41_declares(self):
        for mine, theirs in ((ACC.BINDING, L41.BINDING), (ACC.LITERAL, L41.LITERAL),
                             (ACC.ABSENT, L41.ABSENT),
                             (ACC.DECLARED_INERT, L41.DECLARED_INERT),
                             (ACC.UNCHECKED, L41.UNCHECKED)):
            self.assertEqual(mine, theirs)

    def test_the_labels_arrive_by_import_and_not_by_a_literal(self):
        """AST: шкала ВВЕЗЕНА. Своя копия литералов — ровно вторая шкала."""
        tree = ast.parse(_SRC.read_text(encoding="utf-8"))
        imported_from = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imported_from.add((node.module, alias.name))
        self.assertIn(
            ("spa_core.monitoring.cio_auto_execution_limits", "BINDING"),
            imported_from)
        self.assertIn(
            ("spa_core.monitoring.cio_auto_execution_limits", "_classify"),
            imported_from)

    def test_surfaces_extend_the_imported_list_and_add_the_live_door(self):
        from spa_core.analytics.new_capital_census import SURFACES_20
        self.assertEqual(ACC.SURFACES_22[:len(SURFACES_20)], tuple(SURFACES_20))
        self.assertIn("damper", ACC.SURFACES_22)
        self.assertNotIn("damper", tuple(SURFACES_20),
                         "шестая поверхность уже есть у §20 — расширение лишнее")


class DelegationCannotDivergeFromSection41(unittest.TestCase):
    """Делегированная строка РАВНА строке §41, иначе шкал снова две."""

    @classmethod
    def setUpClass(cls):
        cls.report = ACC.census()
        cls.doc41 = L41.run(write=False)

    def test_each_delegated_row_equals_the_section_41_verdict(self):
        by_word = {r["owner_wording"]: r for r in self.doc41["limits"]}
        rows = {p["param"]: p for p in self.report["params"]}
        for mine, theirs in ACC.DELEGATED_TO_41.items():
            with self.subTest(mine):
                self.assertIn(theirs, by_word,
                              f"§41 не называет «{theirs}» — делегировать нечему")
                self.assertEqual(rows[mine]["outcome"], by_word[theirs]["outcome"])
                self.assertEqual(rows[mine]["detail"], by_word[theirs]["detail"])

    def test_a_delegated_row_carries_no_records_of_its_own(self):
        """Записи у делегированной строки значили бы ПЕРЕМЕР."""
        rows = {p["param"]: p for p in self.report["params"]}
        for mine in ACC.DELEGATED_TO_41:
            with self.subTest(mine):
                self.assertEqual(rows[mine]["records"], [])
                self.assertTrue(rows[mine]["delegated_to"].startswith("§41"))

    def test_a_renamed_section_41_row_becomes_unmeasured_not_absent(self):
        """Порванное звено: §41 переименовал величину. Молчать здесь нельзя."""
        original = dict(ACC.DELEGATED_TO_41)
        try:
            ACC.DELEGATED_TO_41["minimum persistence"] = "величины такой нет"
            report = ACC.census()
            row = next(p for p in report["params"]
                       if p["param"] == "minimum persistence")
            self.assertEqual(row["outcome"], ACC.UNMEASURED)
            self.assertIn("не содержит", row["detail"])
            self.assertEqual(ACC.verdict_code(report), 2)
        finally:
            ACC.DELEGATED_TO_41.clear()
            ACC.DELEGATED_TO_41.update(original)


class TheControlIsAConditionOfTheWholeReport(unittest.TestCase):
    """«Дверь отказала» и «проба сломана» выглядят одинаково без контроля."""

    def test_the_healthy_scene_is_permitted_on_both_surfaces(self):
        ok, why, base = ACC._control()
        self.assertTrue(ok, why)
        self.assertEqual(base, {"economics": "ACT", "damper": "ALLOW"})

    def test_a_price_door_that_always_holds_makes_the_count_unreadable(self):
        """Порванное звено: сцена цены не даёт ACT ⇒ счёт читать нельзя."""
        from spa_core.allocator import rebalance_economics as economics
        real = economics.evaluate

        def always_hold(**kw):
            d = real(**kw)
            d.decision = "HOLD"
            return d

        economics.evaluate = always_hold
        try:
            ok, why, _ = ACC._control()
            self.assertFalse(ok)
            self.assertIn("ACT", why)
            report = ACC.census()
            own = [p for p in report["params"] if p["param"] in ACC.OWN_PROBES]
            self.assertTrue(own)
            for p in own:
                self.assertEqual(p["outcome"], ACC.UNMEASURED)
            self.assertEqual(ACC.verdict_code(report), 2)
        finally:
            economics.evaluate = real

    def test_a_damper_that_always_blocks_makes_the_count_unreadable(self):
        """Второе звено того же контроля — дверь ЖИВОГО пути."""
        from spa_core.governance import churn_damper as damper
        real = damper.decide

        def always_block(*a, **kw):
            v = real(*a, **kw)
            v.decision = damper.BLOCK
            return v

        damper.decide = always_block
        try:
            ok, why, _ = ACC._control()
            self.assertFalse(ok)
            self.assertIn("ограничител", why)
        finally:
            damper.decide = real


class TheNineAreMeasuredOnBothSurfaces(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = ACC.census()
        cls.rows = {p["param"]: p for p in cls.report["params"]}

    def test_every_outcome_is_a_word_of_the_imported_scale(self):
        allowed = {ACC.BINDING, ACC.LITERAL, ACC.DECLARED_INERT, ACC.ABSENT,
                   ACC.UNCHECKED, ACC.UNMEASURED}
        for p in self.report["params"]:
            with self.subTest(p["param"]):
                self.assertIn(p["outcome"], allowed)

    def test_cooldown_is_the_only_param_binding_on_both_doors(self):
        """Ответ по существу: остальные восемь живут на ОДНОЙ двери.

        Красным этот тест становится ровно тогда, когда вторая дверь получает
        (или теряет) ручку — то есть когда §22 действительно сдвинулся.
        """
        both = sorted(p["param"] for p in self.report["params"]
                      if set(p.get("surfaces_binding") or []) >= {"damper", "economics"})
        self.assertEqual(both, ["cooldown"])

    def test_a_policy_field_is_claimed_only_after_it_is_measured_declared(self):
        """Ручкой зовётся ТОЛЬКО поле объявленного контракта."""
        declared = set()
        for names in self.report["declared_policy_fields"].values():
            declared |= set(names)
        for p in self.report["params"]:
            for rec in p.get("records") or []:
                if rec.get("policy_field"):
                    with self.subTest(p["param"], field=rec["policy_field"]):
                        self.assertIn(rec["policy_field"], declared)

    def test_the_absent_three_are_absent_for_a_named_reason(self):
        absent = sorted(p["param"] for p in self.report["params"]
                        if p["outcome"] == ACC.ABSENT)
        self.assertEqual(absent, ["decision expiry", "minimum persistence",
                                  "rebalance cost budget"])
        for name in ("rebalance cost budget",):
            gaps = self.rows[name].get("gaps") or []
            self.assertTrue(gaps, f"«{name}» объявлена отсутствующей без причины")

    def test_a_dial_that_stops_turning_flips_the_outcome_off_binding(self):
        """Порванное звено: ручка перестала двигать вердикт ⇒ не BINDING.

        Полоса выигрыша измеряется возмущением `min_gain_pp`; обездвижим
        именно её и проверим, что исход перестаёт быть BINDING. Это и есть
        смысл оси (б): поле в конфиге само по себе ответом не является.
        """
        real = ACC._trigger_params

        def deaf_dial(**over):
            over.pop("min_gain_pp", None)
            return real(**over)

        ACC._trigger_params = deaf_dial
        try:
            records = ACC._probe_minimum_yield_edge(L41._declared_policy_fields())
            outcome, _ = L41._classify(records)
            self.assertNotEqual(outcome, ACC.BINDING)
            self.assertEqual(outcome, ACC.LITERAL)
        finally:
            ACC._trigger_params = real

    def test_the_damper_first_allowed_day_follows_the_declared_min_hold(self):
        """Число 3 здесь не литерал теста: оно читается у политики."""
        params = L41._trigger_params()
        declared = float(params.min_hold_days)
        measured = self.report["reachability"]["damper"][
            "first_day_a_return_is_allowed"]
        self.assertEqual(measured, declared)

    def test_turning_the_min_hold_dial_moves_the_damper_verdict(self):
        at_one_day = ACC._damper_move(
            {"aave_v3": 30000.0, "pendle": 20000.0},
            {"aave_v3": 40000.0, "pendle": 10000.0},
            [ACC._trade(1.0, 10000.0, ACC.SCENE_NOW)])
        self.assertFalse(at_one_day.allowed)
        turned = ACC._damper_move(
            {"aave_v3": 30000.0, "pendle": 20000.0},
            {"aave_v3": 40000.0, "pendle": 10000.0},
            [ACC._trade(1.0, 10000.0, ACC.SCENE_NOW)],
            params=L41._trigger_params(min_hold_days=0))
        self.assertTrue(turned.allowed)


class TheSwingSceneIsBuiltNotAssumed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.reach = ACC.census()["reachability"]

    def test_both_swing_scenes_reach_their_intermediate_book(self):
        """Сцена, не дошедшая до B, судила бы НЕ качели."""
        econ = self.reach["economics"]
        self.assertEqual(econ["step1_reaches_B"], "ACT")
        self.assertEqual(econ["three_step"]["intermediate_step"], "ACT")

    def test_the_kinds_come_from_the_declared_vocabulary(self):
        econ = self.reach["economics"]
        for key in ("two_step", "three_step"):
            with self.subTest(key):
                self.assertIn(econ[key]["kind"], ACC.SWING_KINDS)
        self.assertIn(self.reach["damper"]["full_cycle_within_a_week"]["kind"],
                      ACC.SWING_KINDS)
        self.assertIn(self.reach["tact"]["kind"],
                      ("unreachable_by_construction", "permitted", ACC.UNMEASURED))

    def test_the_band_edge_is_found_and_equals_the_escalated_band(self):
        """«permitted» не значит «защиты нет»: защита — ПОЛОСА, и вот её край."""
        edge = self.reach["economics"]["band_edge"]
        self.assertIsNotNone(edge, "край полосы не найден — сцена не доказывает ничего")
        params = L41._trigger_params()
        expected = params.min_gain_pp * params.reversal_escalation
        self.assertAlmostEqual(edge["required_gain_pp"], expected, places=6)
        self.assertGreaterEqual(edge["last_permitted_gain_pp"], expected - 1e-6)
        self.assertLess(edge["first_refused_gain_pp"], expected)

    def test_below_the_band_the_same_swing_is_refused(self):
        """Обратная сторона: мелкое колебание разворот НЕ проходит."""
        books = ACC._books(ACC._scene_capital())
        step1 = ACC._econ_move(books["A"], books["B"], "pendle")
        legs1 = ACC._legs_of(step1)
        small = ACC._econ_move(
            books["B"], books["A"], "aave_v3", last_move_legs=legs1,
            days_since_last_move=1.0,
            apy_pct={**ACC._apy_favouring("aave_v3"), "aave_v3": 3.0})
        self.assertEqual(small.decision, "HOLD")
        self.assertTrue(any("gain_below_band" in r for r in small.reasons))

    def test_the_escalation_fires_on_the_reversing_leg(self):
        """Гистерезис СУЩЕСТВУЕТ — и назван: иначе «permitted» было бы о пустоте."""
        econ = self.reach["economics"]
        self.assertTrue(any("reversal_of_recent_move" in r
                            for r in econ["two_step"]["reasons"]))
        self.assertGreater(econ["two_step"]["required_gain_pp"],
                           L41._trigger_params().min_gain_pp)

    def test_the_door_is_not_asked_about_the_book_on_either_surface(self):
        """Ответ владельца 27.10 (вариант 1) — вопрос о СОСТОЯНИИ книги."""
        self.assertFalse(self.reach["economics"]["asks_about_the_book"])
        self.assertFalse(self.reach["damper"]["asks_about_the_book"])
        from spa_core.allocator import rebalance_economics as economics
        from spa_core.governance import churn_damper as damper
        econ_inputs = set(inspect.signature(economics.evaluate).parameters)
        damp_inputs = set(inspect.signature(damper.decide).parameters)
        book_words = {"prior_books", "book_states", "recent_books",
                      "visited_books", "book_history"}
        self.assertEqual(econ_inputs & book_words, set())
        self.assertEqual(damp_inputs & book_words, set())

    def test_the_tact_is_measured_not_reprinted(self):
        """Число такта приходит от прибора §21, а не из текста."""
        tact = self.reach["tact"]
        self.assertIsNotNone(tact["tact_s"])
        from spa_core.analytics.cadence_census import (load_manifest,
                                                       recalculation_tact)
        manifest, err = load_manifest(Path(ACC.__file__).resolve().parents[2])
        self.assertIsNone(err, f"объявление не прочитано: {err}")
        self.assertEqual(tact["tact_s"], recalculation_tact(manifest)["tact_s"])

    def test_an_unreadable_manifest_is_the_third_outcome(self):
        """Порванное звено: такт не измерен ⇒ не «сутки», а НЕ ИЗМЕРЕНО."""
        out = ACC._tact_counterpoint(Path("/nonexistent-tree-for-section-22"))
        self.assertEqual(out["kind"], ACC.UNMEASURED)
        self.assertIsNone(out["tact_s"])
        self.assertTrue(out["why"])


class RefusalKindsAreDistinguished(unittest.TestCase):
    """«Ход не окупается» ≠ «ход разворачивает недавний ход»."""

    def test_an_anti_churn_reason_is_recognised(self):
        for reason in ("reversal_of_recent_move:['pendle']",
                       "cooldown_active:1.0d<3d",
                       "positions_below_min_hold:['pendle']"):
            with self.subTest(reason):
                self.assertTrue(ACC._anti_churn_reason([reason]))

    def test_an_economics_reason_is_not_counted_as_protection(self):
        for reason in ("gain_below_band:0.100pp<0.500pp",
                       "payback_too_long:91.0d", "no_material_legs"):
            with self.subTest(reason):
                self.assertFalse(ACC._anti_churn_reason([reason]))

    def test_the_damper_reasons_are_read_from_the_damper_vocabulary(self):
        from spa_core.governance import churn_damper as damper
        self.assertTrue(ACC._anti_churn_reason([], damper.REASON_MIN_HOLD))
        self.assertTrue(ACC._anti_churn_reason([], damper.REASON_WEEK_BUDGET))
        self.assertFalse(ACC._anti_churn_reason([], damper.REASON_WITHIN_LIMITS))


class TheVerdictHasThreeOutcomes(unittest.TestCase):

    def test_unmeasured_wins_over_a_finding(self):
        report = {"control": {"passed": True}, "vocab_errors": [],
                  "tally": {ACC.ABSENT: 3, ACC.UNMEASURED: 1},
                  "reachability": {}}
        self.assertEqual(ACC.verdict_code(report), 2)

    def test_a_finding_is_one_not_zero(self):
        report = {"control": {"passed": True}, "vocab_errors": [],
                  "tally": {ACC.ABSENT: 3},
                  "reachability": {"economics": {"two_step": {"kind": "permitted"},
                                                 "three_step": {"kind": "permitted"}},
                                   "damper": {"kind": "ok"},
                                   "tact": {"kind": "unreachable_by_construction"}}}
        self.assertEqual(ACC.verdict_code(report), 1)

    def test_a_clean_report_is_zero(self):
        report = {"control": {"passed": True}, "vocab_errors": [],
                  "tally": {ACC.BINDING: 9},
                  "reachability": {
                      "economics": {"two_step": {"kind": "refused_by_anti_churn"},
                                    "three_step": {"kind": "refused_by_anti_churn"}},
                      "damper": {"kind": "ok"},
                      "tact": {"kind": "unreachable_by_construction"}}}
        self.assertEqual(ACC.verdict_code(report), 0)

    def test_a_missing_param_alone_is_already_a_finding(self):
        """Качели отказаны на ОБЕИХ сценах, а величины нет ⇒ всё равно 1.

        Этот тест написан потому, что мутация M7 (ветка «ABSENT/LITERAL ⇒ 1»
        удалена) ПЕРЕЖИЛА первую редакцию батареи: её гасила соседняя ветка про
        качели, и «отсутствующая величина» до вердикта не доезжала.
        """
        refused = {"economics": {"two_step": {"kind": "refused_by_anti_churn"},
                                 "three_step": {"kind": "refused_by_anti_churn"}},
                   "damper": {"kind": "ok"},
                   "tact": {"kind": "unreachable_by_construction"}}
        for tally in ({ACC.ABSENT: 1}, {ACC.LITERAL: 1},
                      {ACC.DECLARED_INERT: 1}):
            with self.subTest(tally=tally):
                self.assertEqual(ACC.verdict_code(
                    {"control": {"passed": True}, "vocab_errors": [],
                     "tally": tally, "reachability": refused}), 1)

    def test_a_permitted_swing_alone_is_already_a_finding(self):
        """Девять ручек на месте не делают §22 исполненным."""
        report = {"control": {"passed": True}, "vocab_errors": [],
                  "tally": {ACC.BINDING: 9},
                  "reachability": {
                      "economics": {"two_step": {"kind": "refused_by_anti_churn"},
                                    "three_step": {"kind": "permitted"}},
                      "damper": {"kind": "ok"},
                      "tact": {"kind": "unreachable_by_construction"}}}
        self.assertEqual(ACC.verdict_code(report), 1)


class TheCensusOnlyReads(unittest.TestCase):
    """ADVISORY объявлено словами — и проверено разбором, а не обещанием."""

    def test_the_module_never_writes_a_file(self):
        tree = ast.parse(_SRC.read_text(encoding="utf-8"))
        writers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None)
                if name in ("atomic_save", "write_text", "mkdir", "unlink"):
                    writers.append(name)
                if name == "open" and len(node.args) > 1:
                    writers.append("open(w)")
        self.assertEqual(writers, [], f"прибор пишет: {writers}")

    def test_the_module_does_not_touch_the_live_trade_journal(self):
        src = _SRC.read_text(encoding="utf-8")
        for forbidden in ("data/trades.json", "equity_curve_daily",
                          "current_positions.json"):
            self.assertNotIn(forbidden, src)

    def test_the_scene_journal_is_built_from_the_injected_anchor(self):
        """Ожидаемое значение ВЫЧИСЛЯЕТСЯ от якоря, а не вписано литералом.

        Литеральная дата здесь была бы второй копией якоря: сдвинь сцену — и
        тест покраснел бы от КАЛЕНДАРЯ, а не от поведения
        (`.claude/rules/deployment.md` § «Время в тестах»).
        """
        rec = ACC._trade(3.0, 1234.0, ACC.SCENE_NOW)
        expected = (ACC.SCENE_NOW - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(rec["ts"], expected)
        self.assertEqual(rec["delta_abs"], 1234.0)

    def test_the_damper_reads_the_ts_key_the_scene_writes(self):
        """Сцена обязана говорить на языке читателя (замер 29.08)."""
        from spa_core.governance import churn_damper as damper
        hours, turnover = damper._recent(
            [ACC._trade(2.0, 500.0, ACC.SCENE_NOW)], ACC.SCENE_NOW)
        self.assertAlmostEqual(hours, 48.0, places=3)
        self.assertEqual(turnover, 500.0)


class TheTriggerParamsContractIsUnchanged(unittest.TestCase):
    """Растяжка: прибор НЕ имеет права добавлять ручки, только мерить."""

    def test_the_policy_contract_fields_are_the_ones_the_census_reports(self):
        from spa_core.allocator.rebalance_economics import TriggerParams
        declared = {f.name for f in dataclasses.fields(TriggerParams)}
        reported = set(ACC.census()["declared_policy_fields"]["TriggerParams"])
        self.assertEqual(declared, reported)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
