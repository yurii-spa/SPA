"""Перепись шести штрафов §15 и слепота сторожа инварианта #3 (ADR-958).

Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на настоящую находку, а не
украшение (`.claude/rules/deployment.md` § «Проверка сторожа сторожей»):
прибор, никогда не видевший настоящей поломки, ничего не охраняет.

FROZEN-DATE-OK: no-dates — ни одна проверка этого файла не судит о свежести:
предмет — ПОВЕДЕНИЕ целевой функции на объявленной сцене и ПОВЕДЕНИЕ сторожа на
подсаженном члене класса. Литеральных дат в файле нет вовсе.
"""
from __future__ import annotations

import tempfile
import shutil
import unittest
from pathlib import Path

from spa_core.analytics import objective_penalties as op
from spa_core.analytics.transaction_economics import CHARGE_KINDS, UNMEASURED


class DeclarationCarriesItsOwnContract(unittest.TestCase):
    """Объявление обязано выдерживать СВОЮ мерку (урок ADR-937/943)."""

    def test_six_penalties_are_declared_in_the_owners_order(self):
        # Число НЕ литерал в утверждении: владелец назвал шесть штрафов, и
        # перечень обязан нести ровно их. Имена сверяются дословно.
        self.assertEqual(
            [p["penalty"] for p in op.PENALTIES],
            ["transaction_cost", "risk_penalty", "concentration_penalty",
             "uncertainty_penalty", "turnover_penalty", "liquidity_penalty"])

    def test_every_penalty_names_a_driver_and_a_reason(self):
        for p in op.PENALTIES:
            with self.subTest(p["penalty"]):
                self.assertTrue(p["owner_words"].strip(), "нет слов владельца")
                self.assertTrue(p["driver"].strip(), "не назван драйвер")
                self.assertTrue(p["why"].strip(), "не названа причина")

    def test_kind_vocabulary_is_IMPORTED_not_reprinted(self):
        # Паритет с §13: своя копия мерки означала бы, что прибор отвечает о
        # себе. Расширение словаря у соседа обязано расширять и этот замер.
        self.assertIs(op.CHARGE_KINDS, CHARGE_KINDS)
        self.assertEqual(op.UNMEASURED, UNMEASURED)

    def test_expected_summand_is_either_None_or_a_real_summand_name(self):
        tuner, why = op.load_objective_door()
        self.assertIsNone(why, f"дверь не ввезена: {why}")
        base, why2 = op._summands(tuner, op._scene_weights(), op._scene_rows())
        self.assertIsNone(why2, why2)
        for p in op.PENALTIES:
            own = p["expect_summand"]
            if own is not None:
                with self.subTest(p["penalty"]):
                    self.assertIn(
                        own, base,
                        "объявлено слагаемое, которого у функции нет — мерка "
                        "разошлась бы с измеряемым молча")


class TheSceneMustBeFitForAttribution(unittest.TestCase):
    """Сцена, сама нарушающая потолки, приписать сдвиг не позволяет."""

    def test_base_scene_violates_nothing(self):
        tuner, why = op.load_objective_door()
        self.assertIsNone(why, why)
        base, why2 = op._summands(tuner, op._scene_weights(), op._scene_rows())
        self.assertIsNone(why2, why2)
        self.assertEqual(base["valid"], 1.0, "базовая сцена недопустима")
        self.assertAlmostEqual(
            base["constraint_penalty"], 0.0, places=9,
            msg="базовая сцена уже несёт штраф за нарушение — сдвиги на ней "
                "смешались бы с уже начисленным")

    def test_concentration_scene_keeps_the_protocol_COUNT(self):
        """Положительный контроль на МОЮ ЖЕ ошибку первой редакции.

        Первая редакция клала весь вес в один протокол, ломала `min_protocols`
        и получала `charged_merged` вместо `charged_named` — неверно, и неверно
        В СТОРОНУ НАХОДКИ. Сцена обязана менять ТОЛЬКО неравномерность.
        """
        weights, rows, why = op._perturb("concentrate_one_protocol")
        self.assertEqual(why, "")
        base_w = op._scene_weights()
        self.assertAlmostEqual(sum(weights.values()), sum(base_w.values()),
                               places=9, msg="суммарный вес сцены изменился")
        active = sum(1 for w in weights.values() if w > 0.01)
        base_active = sum(1 for w in base_w.values() if w > 0.01)
        self.assertEqual(active, base_active,
                         "число активных протоколов изменилось — сцена снова "
                         "начислит чужой штраф за недобор min_protocols")
        self.assertNotAlmostEqual(
            sum(w * w for w in weights.values()),
            sum(w * w for w in base_w.values()), places=9,
            msg="неравномерность не изменилась — мерить было бы нечего")


class TheRodOfEachPenaltyIsMeasuredNotAsserted(unittest.TestCase):
    """Род снимается ДИФФЕРЕНЦИАЛЬНО на живой двери."""

    def setUp(self):
        self.tuner, why = op.load_objective_door()
        self.assertIsNone(why, why)
        self.terms, self.unmeasured = op.probe_penalties(self.tuner)
        self.by = {t["penalty"]: t for t in self.terms}

    def test_every_penalty_got_a_kind_from_the_imported_vocabulary(self):
        self.assertEqual(len(self.terms), len(op.PENALTIES))
        allowed = set(CHARGE_KINDS) | {UNMEASURED}
        for t in self.terms:
            with self.subTest(t["penalty"]):
                self.assertIn(t["charge_kind"], allowed)

    def test_concentration_is_the_one_with_its_OWN_summand(self):
        rec = self.by["concentration_penalty"]
        self.assertEqual(rec["charge_kind"], "charged_named", rec.get("evidence"))
        self.assertEqual(list(rec["shifted_summands"]), ["concentration_penalty"],
                         "сдвиг лёг не только в своё слагаемое — приписать его "
                         "концентрации было бы нельзя")

    def test_liquidity_is_EXPRESSIBLE_and_ignored(self):
        """Самая острая находка §15: вход доезжает, и функция его не читает."""
        rec = self.by["liquidity_penalty"]
        self.assertTrue(rec["field_in_contract"],
                        "поле tvl_usd обязано доезжать до двери — иначе это "
                        "другая находка (no_input_door), а не эта")
        self.assertEqual(rec["charge_kind"], "not_charged", rec.get("evidence"))
        self.assertAlmostEqual(rec["delta_pp"], 0.0, places=9)

    def test_uncertainty_has_NO_input_and_that_is_a_different_claim(self):
        rec = self.by["uncertainty_penalty"]
        self.assertEqual(rec["charge_kind"], "no_input_door", rec.get("evidence"))
        self.assertFalse(rec["field_in_contract"])

    def test_cost_and_turnover_are_inexpressible_at_THIS_door(self):
        for key in ("transaction_cost", "turnover_penalty"):
            with self.subTest(key):
                self.assertEqual(self.by[key]["charge_kind"], "no_input_door")

    def test_charged_named_is_REFUSED_when_the_shift_spills_elsewhere(self):
        """Строгость различителя `charged_named` / `charged_merged`.

        Мутант, заменивший условие `own and own in shifted and len(shifted) == 1`
        на простое `own`, ВЫЖИВАЛ: у единственного штрафа со своим суммандом
        сдвиг и так лежит ровно в нём, поэтому ослабление не проявлялось. Здесь
        различитель спрашивается ИЗВЕСТНЫМ ЧЛЕНОМ — той самой сценой, которой
        первая редакция прибора ошиблась: весь вес в ОДИН протокол, сдвиг
        растекается в `constraint_penalty` вместе со своим суммандом, и род
        `charged_named` обязан быть ОТКАЗАН.
        """
        base, _ = op._summands(self.tuner, op._scene_weights(), op._scene_rows())
        total = op.SCENE_WEIGHT * len(op.SCENE_PROTOCOLS)
        spilled = {op.SCENE_PROTOCOLS[0]: total}
        moved, why = op._summands(self.tuner, spilled, op._scene_rows())
        self.assertIsNone(why, why)
        shifted = {n for n in ("weighted_apy", "concentration_penalty",
                               "constraint_penalty")
                   if abs(moved[n] - base[n]) > op.SCORE_EPS}
        # Предпосылка сцены: сдвиг обязан растечься БОЛЕЕ ЧЕМ в одно слагаемое,
        # иначе проверка ничего не различает и обязана сказать это громко.
        self.assertIn("concentration_penalty", shifted)
        self.assertGreater(
            len(shifted), 1,
            "сцена не растекается — различитель ею не проверяется (предпосылка "
            "НЕ ОБЕСПЕЧЕНА, а не «всё в порядке»)")
        spec = next(p for p in op.PENALTIES
                    if p["penalty"] == "concentration_penalty")
        own = spec["expect_summand"]
        # Различитель ВЫЗЫВАЕТСЯ, а не пересказывается. Первая редакция этой
        # проверки повторяла условие прямо в тесте — и мутант, ослабивший
        # условие В ПРИБОРЕ, выживал: тест судил о данных, а не о поведении.
        self.assertEqual(
            op.classify_shift(own, {n: 1.0 for n in shifted}),
            "charged_merged",
            "различитель назвал это `charged_named`, хотя сдвиг лёг не только "
            "в своё слагаемое")

    def test_the_discriminator_requires_BOTH_facts(self):
        """Заряд именем требует двух фактов, и каждый проверяется отдельно."""
        # оба факта на месте ⇒ своё имя
        self.assertEqual(
            op.classify_shift("concentration_penalty",
                              {"concentration_penalty": -0.03}),
            "charged_named")
        # сдвиг растёкся в соседа ⇒ чужое число
        self.assertEqual(
            op.classify_shift("concentration_penalty",
                              {"concentration_penalty": -0.03,
                               "constraint_penalty": 4.0}),
            "charged_merged")
        # у штрафа нет своего сумманда ⇒ чужое число, даже если сдвиг одинок
        self.assertEqual(
            op.classify_shift(None, {"constraint_penalty": 3.2}),
            "charged_merged")
        # сумманд объявлен, но сдвинулся ДРУГОЙ ⇒ чужое число
        self.assertEqual(
            op.classify_shift("concentration_penalty",
                              {"constraint_penalty": 3.2}),
            "charged_merged")

    def test_an_infeasible_base_scene_REFUSES_instead_of_attributing(self):
        """Сцена, сама нарушающая потолки, обязана остановить замер.

        Мутант, заменивший проверку `base["valid"] != 1.0` на `if False`,
        ВЫЖИВАЛ: боевая сцена допустима, и ветка не срабатывала никогда. Здесь
        недопустимость создаётся явно — потолок на протокол опускается НИЖЕ
        веса сцены, — и прибор обязан отказать с названной причиной, а не
        приписывать сдвиги поверх уже начисленного нарушения.
        """
        tuner, why = op.load_objective_door()
        self.assertIsNone(why, why)
        tuner.constraints.per_protocol_t1_max = op.SCENE_WEIGHT / 2.0
        tuner.constraints.per_protocol_max = op.SCENE_WEIGHT / 2.0
        base, why2 = op._summands(tuner, op._scene_weights(), op._scene_rows())
        self.assertIsNone(why2, why2)
        self.assertGreater(
            base["constraint_penalty"], 0.0,
            "предпосылка НЕ ОБЕСПЕЧЕНА: сцена осталась допустимой, и отказ "
            "проверять нечем")
        terms, unmeasured = op.probe_penalties(tuner)
        self.assertEqual(terms, [], "прибор мерил на негодной сцене")
        self.assertTrue(unmeasured, "отказ без названной причины")
        self.assertIn("сцена", unmeasured[0].lower())

    def test_scene_fitness_has_TWO_conditions_and_each_is_exercised(self):
        """Годность сцены ВЫЗЫВАЕТСЯ дверью, а не пересказывается тестом.

        Обе ветки отказа обязаны быть ДОСТИЖИМЫ: пока условие стояло внутри
        цикла, ветка `valid=False` на боевой сцене не срабатывала никогда, и
        мутант `if False` выживал — отказ существовал на бумаге.
        """
        fit = {"valid": 1.0, "constraint_penalty": 0.0}
        self.assertIsNone(op.scene_unfit_reason(fit),
                          "годная сцена объявлена негодной")
        grossly = {"valid": 0.0, "constraint_penalty": 0.0}
        why = op.scene_unfit_reason(grossly)
        self.assertIsNotNone(why, "сцена с valid=False пропущена")
        self.assertIn("valid=False", why)
        already = {"valid": 1.0, "constraint_penalty": 4.0}
        why2 = op.scene_unfit_reason(already)
        self.assertIsNotNone(why2, "сцена с уже начисленным штрафом пропущена")
        self.assertIn("потолк", why2)
        self.assertNotEqual(why, why2,
                            "две РАЗНЫЕ негодности объяснены одной причиной")

    def test_row_contract_comes_from_the_REAL_loader(self):
        contract, why = op.measure_row_contract()
        self.assertIsNone(why, f"контракт не измерен: {why}")
        self.assertIn("tvl_usd", contract)
        self.assertIn("apy", contract)
        self.assertNotIn("apy_vol_30d_pp", contract,
                         "если разброс однажды доедет до двери, род "
                         "uncertainty обязан смениться — это и есть смысл "
                         "спрашивать контракт у загрузчика, а не у списка")


class RiskIsFreeInsideTheCapAndThatIsTwoMeasurements(unittest.TestCase):
    """Обе стороны границы, иначе утверждение о риске неполно."""

    def setUp(self):
        self.tuner, why = op.load_objective_door()
        self.assertIsNone(why, why)

    def test_inside_the_cap_the_tier_costs_nothing(self):
        out = op.probe_boundary_is_free(self.tuner)
        self.assertNotIn("unmeasured", out, out.get("unmeasured"))
        self.assertTrue(out["risk_inside_the_cap_is_free"],
                        f"сдвиг T1→T2 внутри потолка {out['delta_pp']}")

    def test_beyond_the_cap_only_the_constraint_number_moves(self):
        out = op.probe_cap_violation(self.tuner)
        self.assertNotIn("unmeasured", out, out.get("unmeasured"))
        self.assertTrue(out["moves_only_the_constraint_number"],
                        f"сдвиг лёг в {out['shifted_summands']} — если бы он "
                        "лёг в собственное слагаемое риска, у риска это "
                        "слагаемое было бы")
        self.assertLess(out["delta_pp"], 0.0,
                        "за границей потолка T2 обязан быть ХУЖЕ T1")

    def test_the_two_sides_disagree_and_that_is_the_point(self):
        inside = op.probe_boundary_is_free(self.tuner)
        beyond = op.probe_cap_violation(self.tuner)
        self.assertNotAlmostEqual(
            inside["delta_pp"], beyond["delta_pp"], places=6,
            msg="если обе стороны границы отвечают одинаково, ось ничего не "
                "измеряет")


class TheInvariantGuardIsAskedNotRead(unittest.TestCase):
    """Положительный контроль: известный член класса подсаживается в каталог."""

    def test_guard_sees_the_control_in_every_directory_the_invariant_names(self):
        rep = op.probe_invariant_guard()
        self.assertNotIn("unmeasured", rep, rep.get("unmeasured"))
        blind = rep["blind_to"]
        self.assertEqual(
            blind, [],
            "сторож инв. #3 СЛЕП к каталогам: " + ", ".join(blind)
            + " — подсаженный член класса не увиден НИ ОДНОЙ дверью")

    def test_kill_and_the_math_layer_are_among_the_named_directories(self):
        named = {rel for _, rel, _ in op.INVARIANT_DIRS}
        self.assertIn("spa_core/governance", named,
                      "«kill» инварианта #3 — это каталог стоп-крана")
        self.assertIn("spa_core/tuner", named,
                      "§15 называет источником финансовой математики целевую "
                      "функцию, и она живёт здесь")

    def test_BOTH_doors_are_exercised_by_the_control(self):
        """Зелёный ответ одной двери не есть ответ о другой."""
        rep = op.probe_invariant_guard()
        self.assertTrue(rep["launch_door_importable"],
                        "дверь-запуск не ввезена — ось отвечала бы половиной "
                        "правила (урок MP-309 → ADR-370)")
        for d in rep["directories"]:
            with self.subTest(d["dir"]):
                self.assertTrue(d["sdk_door_sees_control"],
                                "дверь-SDK не увидела подсаженный import")
                self.assertTrue(d["launch_door_sees_control"],
                                "дверь-запуск не увидела подсаженный "
                                "subprocess к бинарю claude")

    def test_a_directory_OUTSIDE_the_scan_list_is_reported_blind(self):
        """Контроль САМОГО прибора: он обязан уметь сказать «СЛЕП».

        Без этой проверки «blind_to пуст» было бы неотличимо от «прибор не
        умеет находить слепоту» — ровно тот ложный зелёный, тише красного
        теста, против которого написан инв. #17.
        """
        root = Path(tempfile.mkdtemp(prefix="spa_inv3_selftest_"))
        try:
            # Дерево-однодневка с ПОДМЕНЁННЫМ сторожем: его список каталогов
            # заведомо не содержит того, что перечисляет INVARIANT_DIRS.
            (root / "scripts").mkdir(parents=True)
            real = Path(op.__file__).resolve().parents[2] / "scripts" / "lint_llm_forbidden.py"
            src = real.read_text(encoding="utf-8")
            needle = "SCAN_DIRS_DEFAULT = ["
            self.assertIn(needle, src, "форма объявления сторожа изменилась")
            head, _, tail = src.partition(needle)
            _, _, rest = tail.partition("]")
            narrowed = head + 'SCAN_DIRS_DEFAULT = ["spa_core/nothing_here"]' + rest
            (root / "scripts" / "lint_llm_forbidden.py").write_text(
                narrowed, encoding="utf-8")
            rep = op.probe_invariant_guard(repo_root=root)
            self.assertNotIn("unmeasured", rep, rep.get("unmeasured"))
            self.assertEqual(
                sorted(rep["blind_to"]),
                sorted(rel for _, rel, _ in op.INVARIANT_DIRS),
                "прибор не назвал слепым НИ ОДИН каталог, хотя сторожу был "
                "подсунут список, не покрывающий ни одного из них")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_missing_guard_is_the_THIRD_outcome_not_a_clean_pass(self):
        root = Path(tempfile.mkdtemp(prefix="spa_inv3_absent_"))
        try:
            rep = op.probe_invariant_guard(repo_root=root)
            self.assertIn("unmeasured", rep,
                          "отсутствие сторожа выдано за чистый ответ — ровно "
                          "fail-OPEN урока pyflakes")
            self.assertIn("НЕ ИЗМЕРЕНА", rep["unmeasured"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TheReportKeepsTheReportsContract(unittest.TestCase):
    """Своя терминология статуса покрасила бы действующих сторожей."""

    def test_status_is_from_the_reports_vocabulary(self):
        rep = op.measure()
        self.assertIn(rep["status"], ("OK", "SKIPPED", "ERROR"))

    def test_report_carries_no_apy_named_number(self):
        """§5: одно имя — один показатель. Счёт APY-ставкой не является."""
        from spa_core.analytics.apy_name_census import _walk

        numbers: dict = {}
        non_numeric: dict = {}
        _walk({"objective_penalties": op.measure()}, "sections",
              numbers, non_numeric)
        self.assertEqual(
            numbers, {},
            "секция принесла apy-именованное число: его обязан объявить "
            "apy_kinds.PATH_KINDS, иначе перепись §5 покраснеет")

    def test_measure_does_not_read_the_live_data_dir(self):
        rep = op.measure(Path("/nonexistent/path/that/must/not/be/read"))
        self.assertEqual(rep["status"], "OK",
                         "прибор споткнулся о несуществующий data-dir — значит "
                         "он его всё-таки читает")
        self.assertFalse(rep["data_dir_read"])

    def test_headline_names_every_bucket(self):
        rep = op.measure()
        self.assertIn("штрафов §15", rep["headline"])
        counts = rep["counts"]
        self.assertEqual(sum(counts.values()), len(op.PENALTIES),
                         "сумма родов не равна числу штрафов — один штраф "
                         "посчитан дважды или потерян")

    def test_the_section_is_wired_into_the_cycle(self):
        """Прибор без читателя неотличим от незапущенного (ADR-526)."""
        from spa_core.analytics.report_sections import SECTION_NAMES

        self.assertIn("objective_penalties", SECTION_NAMES)


class TheMeasurementIsDeterministic(unittest.TestCase):
    """§15 требует deterministic calculation layer — замер тоже обязан им быть."""

    def test_two_runs_agree_term_by_term(self):
        a = op.measure()
        b = op.measure()
        self.assertEqual(
            [(t["penalty"], t["charge_kind"]) for t in a["terms"]],
            [(t["penalty"], t["charge_kind"]) for t in b["terms"]])
        self.assertEqual(a["counts"], b["counts"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
