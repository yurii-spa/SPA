#!/usr/bin/env python3
"""Контроли переписи §17 «Correlated risk» (ADR-960, заказ G948 п. 1).

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: он рвёт одно звено и требует, чтобы
прибор об этом СКАЗАЛ, а не округлил до чистого ответа. Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Время и личность процесса здесь не участвуют: прибор не судит о свежести и не
спрашивает ОС о живости, поэтому литеральных дат и pid в файле нет вовсе.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

from spa_core.analytics import correlated_dependency_census as cdc


class VocabularyIsImportedNotCopied(unittest.TestCase):
    """Словари ВВЕЗЕНЫ. Вторая копия = две шкалы, расходящиеся молча."""

    def test_charge_kinds_are_the_same_object_as_section_13(self):
        from spa_core.analytics.transaction_economics import CHARGE_KINDS
        self.assertEqual(tuple(cdc.CHARGE_KINDS), tuple(CHARGE_KINDS))
        self.assertTrue(cdc.CHARGE_KINDS, "словарь родов §13 пуст — ввоз не состоялся")

    def test_subject_kinds_are_the_same_object_as_section_16(self):
        from spa_core.analytics.risk_constraint_census import SUBJECT_KINDS
        self.assertEqual(tuple(cdc.SUBJECT_KINDS), tuple(SUBJECT_KINDS))

    def test_no_second_copy_of_the_axis_lists_in_this_module(self):
        """Списки осей берутся у канона `risk_axes`, а не перепечатываются."""
        src = Path(cdc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in (
                        "PEG_PROTOCOLS", "BRIDGE_PROTOCOLS",
                        "CREDIT_PROTOCOLS", "DURATION_DEFAULT_PROTOCOLS"):
                    self.fail(f"вторая копия канонического списка {tgt.id} "
                              "в приборе — две шкалы вместо одной")

    def test_axis_lists_come_from_the_canon(self):
        axes, err = cdc.load_axes()
        self.assertIsNone(err)
        from spa_core.risk import risk_axes
        self.assertEqual(axes["PEG"], list(risk_axes.PEG_PROTOCOLS))
        self.assertEqual(axes["BRIDGE"], list(risk_axes.BRIDGE_PROTOCOLS))
        self.assertIs(axes["_matches"], risk_axes._matches)


class TenDependenciesAreTheOwnersTen(unittest.TestCase):
    """Перечень — слова владельца дословно и в порядке приказа."""

    EXPECTED = (
        "protocol", "chain", "oracle", "curator", "collateral", "stablecoin",
        "bridge", "smart-contract implementation", "reward token",
        "liquidity venue",
    )

    def test_exactly_ten_in_the_owners_order(self):
        self.assertEqual(
            tuple(d["owner_words"] for d in cdc.DEPENDENCIES), self.EXPECTED)

    def test_every_dependency_declares_a_registered_probe(self):
        for d in cdc.DEPENDENCIES:
            self.assertIn(d["probe"], cdc.PROBES, d["key"])

    def test_every_claim_belongs_to_its_vocabulary(self):
        for d in cdc.DEPENDENCIES:
            self.assertIn(d["express_claim"], cdc.EXPRESS_KINDS, d["key"])
            self.assertIn(d["observe_claim"], cdc.OBSERVE_KINDS, d["key"])


class ReportKindsStayInsideTheirVocabulary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = cdc.census()

    def test_every_measured_kind_is_a_declared_kind(self):
        allowed_ind = set(cdc.INDEPENDENCE_KINDS) | {cdc.UNMEASURED}
        for key, row in self.report["dependencies"].items():
            self.assertIn(row["express"]["kind"],
                          set(cdc.EXPRESS_KINDS) | {cdc.UNMEASURED}, key)
            self.assertIn(row["observe"]["kind"],
                          set(cdc.OBSERVE_KINDS) | {cdc.UNMEASURED}, key)
            self.assertIn(row["independence"]["kind"], allowed_ind, key)
            self.assertIn(row["independence"].get("door"), set(cdc.DOORS) | {None}, key)

    def test_totals_sum_to_ten(self):
        t = self.report["totals"]
        self.assertEqual(sum(t.values()), len(cdc.DEPENDENCIES))

    def test_a_deliberately_wrong_claim_is_caught_as_a_phantom(self):
        """Положительный контроль самой оси фантомов.

        Без него «фантомов нет» остаётся верным и когда ось зашита в False —
        мутация №17 цикла #1078 так и пережила проверку «phantoms == []».
        """
        con, err = cdc.contracts()
        self.assertIsNone(err)
        axes, err2 = cdc.load_axes()
        self.assertIsNone(err2)
        truthful = dict(cdc.DEPENDENCIES[1])          # chain: door_input
        measured = cdc.measure_expressibility(truthful, con, axes)
        self.assertEqual(measured["kind"], "door_input")
        self.assertFalse(measured["phantom"], "верная претензия названа фантомом")
        lying = dict(truthful, express_claim="absent")
        caught = cdc.measure_expressibility(lying, con, axes)
        self.assertEqual(caught["kind"], "door_input")
        self.assertTrue(caught["phantom"],
                        "ложная претензия НЕ поймана — ось фантомов не работает")

    def test_a_deliberately_wrong_observation_claim_is_caught(self):
        con, err = cdc.contracts()
        self.assertIsNone(err)
        axes, _ = cdc.load_axes()
        lying = dict(cdc.DEPENDENCIES[1], observe_claim="absent")
        caught = cdc.measure_observation(lying, con, axes)
        self.assertEqual(caught["kind"], "observed")
        self.assertTrue(caught["phantom"])

    def test_the_instrument_reports_no_phantom_of_its_own(self):
        """Претензия прибора о себе обязана быть подтверждена замером."""
        self.assertEqual(self.report["phantoms"], [],
                         "прибор утверждает о зависимости то, чего замер не "
                         "подтвердил — это дефект ПРИБОРА, а не находка")

    def test_absent_dependency_population_is_unmeasured_not_zero(self):
        """Карты нет ⇒ население НЕ ИЗМЕРЕНО. Ноль был бы ложью (инв. #17)."""
        for key in ("oracle", "curator", "collateral", "implementation",
                    "reward_token", "liquidity_venue"):
            self.assertIn("unmeasured", self.report["population"][key], key)
            self.assertNotIn("by_value", self.report["population"][key], key)

    def test_rendered_text_names_all_three_outcomes(self):
        txt = cdc.render(self.report)
        self.assertIn("сведено в одно ведро", txt)
        self.assertIn("СЧИТАЮТСЯ НЕЗАВИСИМЫМИ", txt)
        self.assertIn("назвать нечем", txt)


class UnfitSceneIsNamedNotRounded(unittest.TestCase):
    """Непригодная сцена = НЕ ИЗМЕРЕНО. Это главный класс ошибок §16."""

    def test_base_refused_before_the_perturbation_is_unmeasured(self):
        base = {"approved": False, "violations": ["посторонний потолок"]}
        shifted = {"approved": False, "violations": ["что угодно"]}
        kind, detail = cdc.classify_independence(base, shifted, ("что угодно",))
        self.assertEqual(kind, cdc.UNMEASURED)
        self.assertIn("НЕ ОДОБРЕНА", detail["reason"])

    def test_a_crashed_question_is_unmeasured_with_its_reason(self):
        kind, detail = cdc.classify_independence(
            {"approved": True, "violations": []},
            {"error": "RuntimeError: дверь упала"}, ("x",))
        self.assertEqual(kind, cdc.UNMEASURED)
        self.assertIn("дверь упала", detail["reason"])

    def test_verdict_moved_but_no_violation_is_ours_is_unmeasured(self):
        """Сошёл ПОСТОРОННИЙ потолок — это не «сведено в одно ведро»."""
        kind, detail = cdc.classify_independence(
            {"approved": True, "violations": []},
            {"approved": False, "violations": ["Cash buffer breach"]},
            ("Chain concentration",))
        self.assertEqual(kind, cdc.UNMEASURED)
        self.assertIn("посторонний потолок", detail["reason"])

    def test_own_violation_is_bucketed_together(self):
        kind, detail = cdc.classify_independence(
            {"approved": True, "violations": []},
            {"approved": False,
             "violations": ["Chain concentration on ethereum 92.0% exceeds 90.0%"]},
            ("Chain concentration",))
        self.assertEqual(kind, "bucketed_together")
        self.assertEqual(len(detail["own_violations"]), 1)

    def test_approved_perturbation_is_independence_assumed(self):
        kind, _ = cdc.classify_independence(
            {"approved": True, "violations": []},
            {"approved": True, "violations": []}, ("x",))
        self.assertEqual(kind, "independence_assumed")


class ProtocolProbeRefusesAnUncrossableThreshold(unittest.TestCase):
    """Встроенный контроль: порог не пересекаем ⇒ НЕ ИЗМЕРЕНО, не «независимы».

    Это та ошибка, на которой спотыкался §16: проба ёмкости порог не
    пересекала, и «не заряжено» было верно СЛУЧАЙНО.
    """

    class _AlwaysApproves:
        def check_new_position(self, *a, **kw):
            class R:
                approved, violations, warnings = True, [], []
            return R()

    class _ApprovesSiblingRefusesSameKey:
        def check_new_position(self, state, protocol_key=None, **kw):
            held = {p.protocol_key for p in state.positions}
            refuse = protocol_key in held and kw.get("amount_usd", 0) > 1.0
            class R:
                approved = not refuse
                violations = (["Concentration after trade 38.0% exceeds T2 limit 20.0%"]
                              if refuse else [])
                warnings: list = []
            return R()

    def test_control_not_firing_makes_the_answer_unmeasured(self):
        out = cdc.probe_protocol_family(self._AlwaysApproves(), {})
        self.assertEqual(out["kind"], cdc.UNMEASURED)
        self.assertIn("КОНТРОЛЬ НЕ СРАБОТАЛ", out["reason"])

    def test_control_firing_lets_independence_be_claimed(self):
        out = cdc.probe_protocol_family(self._ApprovesSiblingRefusesSameKey(), {})
        self.assertEqual(out["kind"], "independence_assumed")
        self.assertFalse(out["control_same_key"]["approved"])

    def test_scene_uses_the_tier_whose_ceiling_is_crossable(self):
        """T1 (40 %) не пересекается 38 % — сцена ОБЯЗАНА быть T2 (20 %).

        Спрашивается у САМОЙ СЦЕНЫ (`scene_rows`), а не у ярлыка рядом с ней:
        мутация «тир сцены опущен до T1» переживала проверку ярлыка молча.
        """
        out = cdc.probe_protocol_family(self._ApprovesSiblingRefusesSameKey(), {})
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        rows = out["scene_rows"]
        self.assertTrue(rows, "сцена не предъявлена — проверять нечего")
        for row in rows:
            self.assertEqual(row[1], "T2", "строка сцены не в тире с пересекаемым потолком")
        self.assertEqual(out["tier"], rows[0][1], "ярлык тира разошёлся со сценой")
        share = 2 * rows[0][2] / cdc.SCENE_CAPITAL_USD
        self.assertGreater(share, cfg.max_concentration_t2,
                           "сцена НЕ ПЕРЕСЕКАЕТ потолок своего тира — ответ был бы "
                           "верен случайно")
        self.assertLess(share, cfg.max_concentration_t1)
        self.assertAlmostEqual(out["exposure_pct"], share * 100.0, places=3)

    def test_the_asked_tier_is_the_tier_of_the_scene(self):
        """Вопрос двери обязан идти в ТОМ ЖЕ тире, в котором стои́т книга."""
        asked = []

        class Recorder:
            def check_new_position(self, state, **kw):
                asked.append((kw.get("tier"),
                              tuple(p.tier for p in state.positions),
                              kw.get("amount_usd")))
                class R:
                    approved = kw.get("amount_usd", 0) <= 1.0
                    violations = [] if approved else ["Concentration exceeds T2 limit"]
                    warnings: list = []
                return R()

        cdc.probe_protocol_family(Recorder(), {})
        self.assertTrue(asked)
        for asked_tier, book_tiers, _usd in asked:
            self.assertEqual((asked_tier,), tuple(set(book_tiers)),
                             "тир вопроса расходится с тиром книги — сцена спутана")


class ChainProbePerturbsOnlyTheChainLabel(unittest.TestCase):
    """Возмущение обязано быть ОДНО. Менять состав книги = отвечать о другом."""

    def test_both_questions_carry_the_same_book_and_the_same_money(self):
        seen = []

        class Recorder:
            def check_new_position(self, state, **kw):
                seen.append((tuple((p.protocol_key, p.amount_usd, p.chain)
                                   for p in state.positions),
                             kw.get("amount_usd"), kw.get("tier"),
                             kw.get("protocol_key"), kw.get("chain")))
                class R:
                    approved, violations, warnings = True, [], []
                return R()

        cdc.probe_chain_shared(Recorder(), {})
        self.assertEqual(len(seen), 2)
        base, shifted = seen
        self.assertEqual(base[0], shifted[0], "книга изменилась — возмущение не одно")
        self.assertEqual(base[1], shifted[1], "сумма изменилась — возмущение не одно")
        self.assertEqual(base[2], shifted[2])
        self.assertEqual(base[3], shifted[3])
        self.assertNotEqual(base[4], shifted[4], "ярлык цепи не возмущён — предмета нет")

    def test_on_the_live_door_the_chain_bucket_is_charged(self):
        policy, err = cdc.load_policy()
        self.assertIsNone(err)
        out = cdc.probe_chain_shared(policy, {})
        self.assertEqual(out["kind"], "bucketed_together")
        self.assertTrue(any("hain" in v for v in out["own_violations"]))


class PegProbeAsksTheMoneyPathCallForm(unittest.TestCase):
    """Род §17 присваивается по ДЕНЕЖНОМУ ПУТИ, а не по «с осями»."""

    def test_axes_only_bucket_is_independence_assumed_on_the_money_path(self):
        class AxesOnlyRefuses:
            def check_portfolio_health(self, state, **kw):
                on = kw.get("check_axes") is True
                class R:
                    approved = not on
                    violations = ["PEG axis: peg_weight=30.0% > limit 10.0%"] if on else []
                    warnings: list = []
                return R()

        axes, err = cdc.load_axes()
        self.assertIsNone(err)
        out = cdc.probe_peg_axis(AxesOnlyRefuses(), axes)
        self.assertEqual(out["kind"], "independence_assumed")
        self.assertEqual(out["axes_on_kind"], "bucketed_together")
        self.assertIn("check_axes", out["reason"])

    def test_three_pools_each_below_its_own_ceiling(self):
        """Иначе отказ дал бы потолок концентрации — сцена была бы спутана."""
        axes, _ = cdc.load_axes()
        rows, err = cdc._peg_rows(axes)
        self.assertIsNone(err)
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        peg_rows = [r for r in rows if r[1] == "T2"]
        self.assertEqual(len(peg_rows), 3, "§17 говорит о ТРЁХ vault")
        for _k, _t, usd, _ch, _a in peg_rows:
            self.assertLess(usd / cdc.SCENE_CAPITAL_USD, cfg.max_concentration_t2)
        total = sum(r[2] for r in peg_rows) / cdc.SCENE_CAPITAL_USD
        self.assertGreater(total, 0.10, "сумма обязана пересекать предел оси peg")

    def test_short_canonical_list_is_unmeasured_not_a_finding(self):
        out = cdc.probe_peg_axis(object(), {"PEG": ["only_one"]})
        self.assertEqual(out["kind"], cdc.UNMEASURED)
        self.assertIn("короче трёх", out["reason"])

    def test_on_the_live_doors_the_money_path_approves_what_axes_refuse(self):
        policy, err = cdc.load_policy()
        self.assertIsNone(err)
        axes, err2 = cdc.load_axes()
        self.assertIsNone(err2)
        out = cdc.probe_peg_axis(policy, axes)
        self.assertEqual(out["kind"], "independence_assumed")
        self.assertTrue(out["money_path"]["approved"])
        self.assertFalse(out["book_axes_on"]["approved"])


class BridgePairCannotBeNamedAndThatIsNotIndependence(unittest.TestCase):

    def test_zero_matching_registry_keys_is_pair_not_namable(self):
        policy, err = cdc.load_policy()
        self.assertIsNone(err)
        axes, err2 = cdc.load_axes()
        self.assertIsNone(err2)
        out = cdc.probe_bridge_axis(policy, axes)
        self.assertEqual(out["kind"], "pair_not_namable")
        self.assertLess(len(out["registry_matched"]), 2)
        self.assertIn("нельзя назвать", out["reason"])

    def test_empty_canonical_list_is_unmeasured_not_pair_not_namable(self):
        out = cdc.probe_bridge_axis(object(), {"BRIDGE": [], "_matches": lambda a, b: False})
        self.assertEqual(out["kind"], cdc.UNMEASURED)

    def test_missing_canonical_matcher_is_unmeasured(self):
        out = cdc.probe_bridge_axis(object(), {"BRIDGE": ["across"]})
        self.assertEqual(out["kind"], cdc.UNMEASURED)
        self.assertIn("матчер", out["reason"])


class FieldReadersAreMeasuredNotAsserted(unittest.TestCase):
    """«Поле объявлено» и «поле читают» — РАЗНЫЕ утверждения."""

    def test_asset_is_declared_and_never_read_by_the_policy(self):
        n, err = cdc.policy_field_readers("asset")
        self.assertIsNone(err)
        self.assertEqual(n, 0, "если поле стали читать — это НОВОСТЬ, а не сбой теста")

    def test_chain_is_declared_and_read(self):
        n, err = cdc.policy_field_readers("chain")
        self.assertIsNone(err)
        self.assertGreater(n, 0)

    def test_missing_canon_is_unmeasured_not_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            n, err = cdc.policy_field_readers("asset", root=Path(td))
        self.assertIsNone(n, "отсутствие канона дало ЧИСЛО — это fail-OPEN")
        self.assertIn("не найден", err)

    def test_stablecoin_row_carries_the_declared_not_read_fact(self):
        report = cdc.census()
        row = report["dependencies"]["stablecoin"]["express"]
        self.assertEqual(row["kind"], "state_field")
        self.assertEqual(row["state_field_readers"], 0)
        self.assertTrue(row["declared_not_read"])


class MoneyPathCallFormIsMeasuredByAst(unittest.TestCase):

    def test_live_tree_money_path_calls_the_book_door_with_axes_off(self):
        calls, err = cdc.money_path_axis_call_forms()
        self.assertIsNone(err)
        self.assertTrue(calls, "ни одного зова не найдено — претензия не подтверждена")
        self.assertTrue(all(not c["axes_on"] for c in calls))

    def test_missing_declared_file_is_unmeasured_not_axes_off(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            calls, err = cdc.money_path_axis_call_forms(root=Path(td))
        self.assertEqual(calls, [])
        self.assertIn("не найдены", err)

    def test_a_keyword_true_is_read_as_axes_on(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tgt = Path(td) / cdc.MONEY_PATH_FILES[0]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text("self.policy.check_portfolio_health(state, check_axes=True)\n",
                           encoding="utf-8")
            calls, err = cdc.money_path_axis_call_forms(root=Path(td))
        self.assertIsNone(err)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["axes_on"])
        self.assertEqual(calls[0]["keywords"], ["check_axes"])

    def test_the_word_elsewhere_in_the_file_is_not_the_call_form(self):
        """Подстрока сказала бы «оси включены» о комментарии рядом с зовом."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tgt = Path(td) / cdc.MONEY_PATH_FILES[0]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text("# check_axes=True когда-нибудь\n"
                           "self.policy.check_portfolio_health(state)\n",
                           encoding="utf-8")
            calls, err = cdc.money_path_axis_call_forms(root=Path(td))
        self.assertIsNone(err)
        self.assertFalse(calls[0]["axes_on"])


class VerdictCodeSeparatesFindingFromUnmeasured(unittest.TestCase):
    """Падение прибора, прочитанное как находка, — класс ADR-897 п. 2."""

    BASE = {"totals": {"bucketed_together": 10, "independence_assumed": 0,
                       "pair_not_namable": 0, "unmeasured": 0},
            "unmeasured_reasons": [], "phantoms": [], "money_path_axes_on": True}

    def test_clean_is_zero(self):
        self.assertEqual(cdc.verdict_code(dict(self.BASE)), 0)

    def test_independence_assumed_is_a_finding(self):
        r = dict(self.BASE)
        r["totals"] = {**self.BASE["totals"], "bucketed_together": 9,
                       "independence_assumed": 1}
        self.assertEqual(cdc.verdict_code(r), 1)

    def test_pair_not_namable_is_a_finding(self):
        r = dict(self.BASE)
        r["totals"] = {**self.BASE["totals"], "bucketed_together": 9,
                       "pair_not_namable": 1}
        self.assertEqual(cdc.verdict_code(r), 1)

    def test_axes_off_on_the_money_path_is_a_finding(self):
        r = dict(self.BASE, money_path_axes_on=False)
        self.assertEqual(cdc.verdict_code(r), 1)

    def test_unmeasured_wins_over_a_finding(self):
        r = dict(self.BASE, unmeasured_reasons=["дверь не ввезена"])
        r["totals"] = {**self.BASE["totals"], "bucketed_together": 9,
                       "independence_assumed": 1}
        self.assertEqual(cdc.verdict_code(r), 2,
                         "НЕ ИЗМЕРЕНО обязано перебивать находку (fail-CLOSED)")

    def test_a_phantom_of_the_instrument_is_a_finding(self):
        self.assertEqual(cdc.verdict_code(dict(self.BASE, phantoms=["chain"])), 1)

    def test_cli_returns_two_when_the_instrument_crashes(self):
        orig = cdc.census
        cdc.census = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("прибор упал"))
        try:
            self.assertEqual(cdc.main([]), 2)
        finally:
            cdc.census = orig


class InstrumentOnlyReads(unittest.TestCase):
    """§17 просит ПРЕДЛОЖЕНИЕ. Правка risk-слоя — предмет №1 ADR-285."""

    FORBIDDEN_WRITES = ("atomic_save", "open(", "write_text", "Path.write",
                        "json.dump(")

    def test_no_writer_anywhere_in_the_instrument(self):
        src = Path(cdc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.dump(node.func)
                for bad in ("atomic_save", "write_text", "write_bytes"):
                    self.assertNotIn(f"attr='{bad}'", name,
                                     f"прибор пишет ({bad}) — §17 просит замер")
                    self.assertNotIn(f"id='{bad}'", name)

    def test_the_live_track_is_not_read_by_a_single_number(self):
        src = Path(cdc.__file__).read_text(encoding="utf-8")
        self.assertNotIn("equity_curve_daily", src.replace(
            "`data/equity_curve_daily.json`", ""),
            "живой трек в сцене запрещён (CLAUDE.md)")

    def test_scene_capital_is_declared_not_taken_from_the_track(self):
        self.assertEqual(cdc.SCENE_CAPITAL_USD, 100_000.0)


if __name__ == "__main__":
    unittest.main()
