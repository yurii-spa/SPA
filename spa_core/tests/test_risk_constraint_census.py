#!/usr/bin/env python3
"""Контроли переписи §16 «Risk» — в ОБЕ стороны, на настоящем приборе.

Правило `.claude/rules/acceptance.md` п. 3: проба регистрируется только с
тестом, где она зелёная на целом контуре и КРАСНАЯ на каждом порванном звене —
с названным звеном. Здесь порванные звенья — это:

* непригодная сцена (базовая книга связывает посторонний потолок);
* не сработавший положительный контроль у оси субъекта;
* претензия о потолке, назвавшая несуществующее поле `RiskConfig`;
* порог, недостижимый под остальными объявленными потолками;
* падение прибора, которое НЕ ИМЕЕТ ПРАВА выглядеть находкой.

Время и личность процесса сюда не входят ни одним литералом: предмет замера —
ПОВЕДЕНИЕ ГЕЙТА на объявленной сцене, и он не зависит ни от календаря, ни от
номеров процессов (`.claude/rules/deployment.md`).
"""

from __future__ import annotations

import dataclasses
import unittest

from spa_core.analytics import risk_constraint_census as rcc
from spa_core.analytics.transaction_economics import CHARGE_KINDS, UNMEASURED


class TestKindsAreImportedNotReprinted(unittest.TestCase):
    """Словарь родов ВВЕЗЁН из §13. Вторая копия = две шкалы, расходящиеся молча."""

    def test_same_object_as_section_13(self):
        self.assertIs(rcc.CHARGE_KINDS, CHARGE_KINDS)
        self.assertEqual(rcc.UNMEASURED, UNMEASURED)

    def test_unmeasured_is_not_on_the_kind_scale(self):
        # «не измерено» — ОТДЕЛЬНЫЙ исход (инв. #17), а не худший род.
        self.assertNotIn(UNMEASURED, CHARGE_KINDS)

    def test_subject_axis_is_its_own_vocabulary(self):
        # Ось субъекта не имеет права быть подмножеством рода: иначе две оси
        # несут один бит (ADR-943), и «исполняется не над тем субъектом»
        # становится неотличимо от лучшего исхода.
        self.assertFalse(set(rcc.SUBJECT_KINDS) & set(CHARGE_KINDS))


class TestNineConstraintsAreTheOwnersNine(unittest.TestCase):
    """Перечень — ДЕВЯТЬ пунктов §16, дословно и без добавлений."""

    def test_exactly_nine(self):
        self.assertEqual(len(rcc.CONSTRAINTS), 9)

    def test_owner_words_present_and_unique(self):
        words = [c["owner_words"] for c in rcc.CONSTRAINTS]
        self.assertEqual(len(set(words)), 9)
        for expected in ("protocol concentration", "vault concentration",
                         "Tier concentration", "chain concentration",
                         "asset concentration", "strategy concentration",
                         "liquidity", "withdrawal availability",
                         "correlated dependencies"):
            self.assertIn(expected, words)

    def test_every_constraint_has_a_registered_probe(self):
        for c in rcc.CONSTRAINTS:
            self.assertIn(c["probe"], {
                "protocol_subject", "vault_subject", "tier_total",
                "chain_total", "liquidity_floor", "signature_absent",
            }, msg=f"{c['key']}: проба не зарегистрирована")


class TestClassifyBothDirections(unittest.TestCase):
    """`classify` обязана давать РАЗНЫЕ ответы на разных звеньях."""

    OK = {"approved": True, "violations": [], "warnings": []}

    def test_shift_changes_nothing_is_not_charged(self):
        kind, _ = rcc.classify(self.OK, self.OK, markers=("Чего-то",))
        self.assertEqual(kind, "not_charged")

    def test_own_violation_is_charged_named(self):
        shifted = {"approved": False, "violations": ["Total T2 allocation 53% …"],
                   "warnings": []}
        kind, detail = rcc.classify(self.OK, shifted, markers=("Total T2 allocation",))
        self.assertEqual(kind, "charged_named")
        self.assertTrue(detail["own_violations"])

    def test_foreign_violation_is_charged_merged(self):
        # Вердикт шевельнулся, но СВОЕГО сообщения нет — отличить от соседа нечем.
        shifted = {"approved": False, "violations": ["Insufficient cash: need …"],
                   "warnings": []}
        kind, detail = rcc.classify(self.OK, shifted, markers=("Total T2 allocation",))
        self.assertEqual(kind, "charged_merged")
        self.assertEqual(detail["own_violations"], [])

    def test_unfit_base_is_unmeasured_with_a_named_reason(self):
        # ПОРВАННОЕ ЗВЕНО: базовая книга уже отвергнута, значит сцена связывает
        # посторонний потолок и о предмете не говорит ничего.
        bad = {"approved": False, "violations": ["Concentration after trade …"],
               "warnings": []}
        kind, detail = rcc.classify(bad, bad, markers=("что угодно",))
        self.assertEqual(kind, UNMEASURED)
        self.assertIn("НЕ ОДОБРЕНА", detail["reason"])

    def test_door_failure_is_unmeasured_not_a_verdict(self):
        kind, detail = rcc.classify(self.OK, {"error": "Boom"}, markers=("x",))
        self.assertEqual(kind, UNMEASURED)
        self.assertIn("Boom", detail["reason"])

    def test_unmeasured_always_carries_a_reason(self):
        # Третий исход без причины — это инв. #17 наизнанку. Первая редакция
        # прибора печатала «unmeasured: None».
        for base, shifted in (
            ({"approved": False, "violations": ["x"], "warnings": []}, self.OK),
            (self.OK, {"error": "e"}),
            ({"error": "e"}, self.OK),
        ):
            kind, detail = rcc.classify(base, shifted, markers=("x",))
            self.assertEqual(kind, UNMEASURED)
            self.assertTrue(detail.get("reason"), msg="третий исход без причины")


class TestSceneFitness(unittest.TestCase):
    def test_rejected_base_is_unfit(self):
        self.assertIsNotNone(rcc.scene_unfit_reason(
            {"approved": False, "violations": ["Concentration …"], "warnings": []}))

    def test_approved_base_is_fit(self):
        self.assertIsNone(rcc.scene_unfit_reason(
            {"approved": True, "violations": [], "warnings": []}))

    def test_failed_base_is_unfit_and_names_the_RIGHT_cause(self):
        # Мутация нашла слабость первой редакции: при снятой ветке «вопрос упал»
        # исход попадал в ветку «книга не одобрена» — причина оставалась
        # НЕПУСТОЙ, и тест зеленел, НАЗЫВАЯ НЕ ТУ беду. Третий исход без ВЕРНОЙ
        # причины — это инв. #17 наполовину.
        reason = rcc.scene_unfit_reason({"error": "Boom"})
        self.assertIsNotNone(reason)
        self.assertIn("упал", reason)
        self.assertIn("Boom", reason)
        self.assertNotIn("НЕ ОДОБРЕНА", reason)


class _AlwaysApproves:
    """Гейт, который одобряет ВСЁ — для контроля оси субъекта."""

    class _R:
        approved = True
        violations: list = []
        warnings: list = []

    def check_new_position(self, *a, **kw):
        return self._R()


class TestProtocolSubjectControlMustFire(unittest.TestCase):
    """Положительный контроль оси субъекта — НЕСУЩИЙ, и его отказ обязан быть виден.

    Без контроля «одобрено у соседнего ключа» означало бы ЛИБО «потолок
    ключуется вautом» (находка), ЛИБО «потолок не работает вообще» (другая
    находка). Различить их может только вопрос о ТОМ ЖЕ ключе.
    """

    def test_live_door_gives_the_proxy_finding(self):
        res = rcc.probe_protocol_subject(rcc.load_policy()[0])
        self.assertNotEqual(res["kind"], UNMEASURED, msg=res.get("reason"))
        self.assertEqual(res["subject"], "proxy")
        self.assertFalse(res["control_same_key"]["approved"],
                         msg="контроль обязан быть ОТКАЗОМ")
        self.assertTrue(res["subject_sibling_key"]["approved"])

    def test_broken_control_is_unmeasured_not_a_finding(self):
        # ПОРВАННОЕ ЗВЕНО: потолок не связал даже тот же ключ.
        res = rcc.probe_protocol_subject(_AlwaysApproves())
        self.assertEqual(res["kind"], UNMEASURED)
        self.assertIn("контроль не сработал", res["reason"])

    def test_no_family_map_in_the_risk_layer(self):
        fm = rcc.family_map_exists()
        self.assertFalse(fm["exists"], msg=f"нашлось поле семейства: {fm}")
        self.assertIn("protocol_key", fm["position_fields"])


class TestCeilingClaimsAreCheckedAgainstTheDataclass(unittest.TestCase):
    def test_every_claimed_field_exists(self):
        _, cfg_cls, err = rcc.load_policy()
        self.assertIsNone(err, msg=err)
        ceilings, c_err = rcc.measure_ceilings(cfg_cls)
        self.assertIsNone(c_err)
        for key, e in ceilings.items():
            self.assertEqual(e["phantom"], [],
                             msg=f"{key}: претензия назвала несуществующее поле")

    def test_phantom_field_is_named_not_rounded_to_absent(self):
        # ПОРВАННОЕ ЗВЕНО: претензия о поле, которого в RiskConfig нет. Такое
        # обязано быть НАЗВАНО дефектом прибора, а не прочитано как «потолка нет».
        @dataclasses.dataclass
        class Narrow:
            min_tvl_usd: float = 5_000_000.0

        ceilings, err = rcc.measure_ceilings(Narrow)
        self.assertIsNone(err)
        self.assertEqual(ceilings["liquidity"]["phantom"], [])
        self.assertIn("max_concentration_t1",
                      ceilings["protocol_concentration"]["phantom"])

    def test_missing_config_is_unmeasured(self):
        _, err = rcc.measure_ceilings(None)
        self.assertTrue(err)


class TestCapacityReachability(unittest.TestCase):
    """Род нельзя печатать у порога, которого сцена не пересекает."""

    def test_unreachable_under_declared_ceilings(self):
        res = rcc.probe_capacity_reachable(rcc.load_policy()[0], [])
        self.assertEqual(res["kind"], UNMEASURED)
        self.assertIn("НЕДОСТИЖИМ", res["reason"])
        # Порог становится достижим на БОЛЬШЕЙ книге, и это число названо.
        self.assertGreater(res["becomes_reachable_at_capital_usd"],
                           rcc.SCENE_CAPITAL_USD)

    def test_numbers_come_from_the_real_producers(self):
        res = rcc.probe_capacity_reachable(rcc.load_policy()[0], [])
        from spa_core.risk.capacity_limits import effective_max_pct
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        self.assertEqual(res["capacity_pct_of_tvl"],
                         float(effective_max_pct(rcc.SCENE_SAME_KEY, "T1",
                                                 cfg.min_tvl_usd)))
        self.assertEqual(res["tvl_floor_usd"], cfg.min_tvl_usd)


class TestLiveCensus(unittest.TestCase):
    """Замер на живой двери — целый контур."""

    @classmethod
    def setUpClass(cls):
        cls.rep = rcc.measure()

    def test_all_nine_got_a_kind_by_measurement(self):
        self.assertEqual(len(self.rep["constraints"]), 9)
        self.assertEqual(self.rep["unmeasured"], [],
                         msg=f"НЕ ИЗМЕРЕНО: {self.rep['unmeasured']}")

    def test_door_is_the_admission_gate_the_owner_names(self):
        self.assertEqual(self.rep["admission_door"],
                         "RiskPolicy.check_new_position")

    def test_protocol_ceiling_binds_a_proxy_subject(self):
        e = self.rep["constraints"]["protocol_concentration"]
        self.assertTrue(e["ceiling_declared"])
        self.assertEqual(e["kind"], "charged_named")
        self.assertEqual(e["subject"], "proxy")

    def test_vault_constraint_is_enforced_without_being_declared(self):
        e = self.rep["constraints"]["vault_concentration"]
        self.assertFalse(e["ceiling_declared"])
        self.assertEqual(e["subject"], "named")

    def test_four_constraints_cannot_even_be_expressed(self):
        silent = sorted(k for k, e in self.rep["constraints"].items()
                        if e["kind"] == "no_input_door")
        self.assertEqual(silent, ["asset_concentration",
                                  "correlated_dependencies",
                                  "strategy_concentration",
                                  "withdrawal_availability"])

    def test_health_door_is_named_where_it_exists(self):
        # «Нет у двери допуска» ≠ «нет в системе»: где измерено — НАЗВАНО.
        for key in ("withdrawal_availability", "correlated_dependencies"):
            self.assertTrue(self.rep["constraints"][key]["health_door"],
                            msg=f"{key}: вторая дверь не названа")

    def test_base_chain_cap_is_declared_and_does_not_reach(self):
        fields = {sf["field"]: sf for sf in self.rep["field_findings"]}
        self.assertIn("BASE_CHAIN_CAP", fields)
        self.assertEqual(fields["BASE_CHAIN_CAP"]["kind"], "not_charged")

    def test_field_findings_reach_the_verdict(self):
        # ПОРВАННОЕ ЗВЕНО прежней редакции: род ограничения `charged_named`
        # ПРЯТАЛ находку поля, и вердикт выходил 0.
        self.assertTrue(self.rep["field_findings"])
        self.assertEqual(rcc.main([]), 1)

    def test_tally_names_its_members(self):
        # Счёт без ЧЛЕНОВ перемерить нельзя.
        for k, members in self.rep["tally"].items():
            self.assertTrue(members, msg=f"род {k} без членов")
        self.assertEqual(sum(len(v) for v in self.rep["tally"].values()), 9)

    def test_registry_families_are_measured_not_listed(self):
        fams = self.rep["registry_families"]
        self.assertIn("morpho", fams)
        self.assertIn("aave", fams)
        self.assertGreater(self.rep["registry_family_keys"], 1)

    def test_instrument_does_not_write_anything(self):
        # Прибор ТОЛЬКО ЧИТАЕТ: §16 просит предложение, а не правку.
        self.assertIn("ЧИТАЕТ", self.rep["doors_touched"])


class TestCrashIsNotAFinding(unittest.TestCase):
    """Падение прибора обязано отличаться от находки КОДОМ ВОЗВРАТА.

    У Python необработанное исключение даёт код 1, а код 1 здесь объявлен
    НАХОДКОЙ — то есть обрыв читался бы как утверждение о системе. Тот же
    класс, что и совпадение кодов у производителя §12 (ADR-897 п. 2).
    """

    def test_measure_failure_returns_two(self):
        orig = rcc.measure
        rcc.measure = lambda: (_ for _ in ()).throw(RuntimeError("Boom"))
        try:
            self.assertEqual(rcc.main([]), 2)
        finally:
            rcc.measure = orig

    def test_missing_kinds_vocabulary_returns_two(self):
        orig = rcc.CHARGE_KINDS
        rcc.CHARGE_KINDS = ()
        try:
            rep = rcc.measure()
            self.assertTrue(rep["unmeasured"])
            self.assertEqual(rcc.main([]), 2)
        finally:
            rcc.CHARGE_KINDS = orig

    def test_no_policy_door_returns_two(self):
        orig = rcc.load_policy
        rcc.load_policy = lambda: (None, None, "дверь не ввезена (сцена)")
        try:
            self.assertEqual(rcc.main([]), 2)
        finally:
            rcc.load_policy = orig


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
