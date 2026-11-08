"""Батарея §12 приказа владельца «Portfolio CIO» — Marginal APY (ADR-955).

Каждая проверка — КОНТРОЛЬ В ОБЕ СТОРОНЫ: сцена, где предмет цел, и сцена, где
порвано ОДНО звено с названным именем. Проверки «число похоже на правильное»
здесь нет намеренно: прошлый цикл (#1071) нашёл мутацией, что сравнение числа С
САМИМ СОБОЙ не ловит инверсию знака, и лечится это только сравнением ДВУХ РЯДОВ
между собой.

Время — ВХОД (`now=`), а не стенные часы: проверка срока, стоящая на календаре,
краснеет от сдвига календаря, а не от кода (`.claude/rules/deployment.md`
§ «Время в тестах»).
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом и уезжает
# аргументом `now=` в `axes_state`/`measure`/`_state`; вторая сторона сравнения
# (отметка файла сцены) ПРОИСХОДИТ от него же либо от `datetime.now()` вместе со
# сдвигом, переданным тем же входом. Подпроцессов батарея не поднимает — второй
# двери к часам нет (ADR-897).
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.analytics import apy_kinds, apy_marginal as am
from spa_core.analytics.report_sections import SECTION_NAMES

#: Якорь сцены. Уезжает ВХОДОМ в каждый вызов, что судит о сроке.
_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _adapters(**over) -> dict:
    """Два протокола: глубокий (разбавление ничтожно) и мелкий (ощутимо).

    Два, а не один, намеренно: инверсию знака вилки ловит только сравнение
    ДВУХ рядов между собой.
    """
    base = {
        "deep_pool": {"display_name": "Deep Pool", "apy": 5.0, "live_apy": 5.0,
                      "apy_base": 4.0, "apy_reward": 1.0,
                      "apy_composition_unmeasured": None,
                      "tvl_usd": 1_000_000_000.0, "tvl_source": "live",
                      "tier": 1},
        "thin_pool": {"display_name": "Thin Pool", "apy": 5.0, "live_apy": 5.0,
                      "apy_base": 4.0, "apy_reward": 1.0,
                      "apy_composition_unmeasured": None,
                      "tvl_usd": 1_000_000.0, "tvl_source": "live",
                      "tier": 2},
    }
    base.update(over)
    return base


def _scene(tmp: Path, adapters=None, extra_files=None) -> Path:
    d = tmp / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "adapter_status.json").write_text(
        json.dumps({"adapters": adapters if adapters is not None else _adapters()}),
        encoding="utf-8")
    for name, body in (extra_files or {}).items():
        (d / name).write_text(json.dumps(body), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# 1. Объявление выдерживает СВОЙ контракт — и ломается, когда его ломают
# ---------------------------------------------------------------------------
class DeclarationParity(unittest.TestCase):
    def test_clean_declaration_has_no_problems(self):
        self.assertEqual(am.validate(), [])

    def test_rungs_are_the_OWNER_literals__not_our_own_choice(self):
        # Мерка НЕЗАВИСИМА от объявления намеренно: сверить `RUNGS_USD` с
        # `RUNGS_USD` значило бы сверять константы САМ С СОБОЙ (урок ADR-913),
        # и тогда «лестница из одной ступени» прошла бы зелёной. Авторитет
        # здесь — ДОСЛОВНЫЙ текст §12 владельца: «APY at +$5k · +$10k · +$20k ·
        # +$40k».
        self.assertEqual(list(am.RUNGS_USD), [5_000.0, 10_000.0, 20_000.0, 40_000.0])

    def test_seven_axes_exactly__owner_named_seven(self):
        self.assertEqual(len(am.AXES), 7)
        self.assertEqual(
            [a["owner_words"] for a in am.AXES],
            ["TVL dilution", "utilization", "reward dilution", "capacity",
             "deposit caps", "liquidity", "withdrawal depth"])

    def test_six_axes_is_a_PROBLEM__not_a_smaller_census(self):
        orig = am.AXES
        try:
            am.AXES = orig[:-1]
            self.assertTrue(any("семь" in p for p in am.validate()),
                            "перепись из шести осей отвечала бы не на вопрос §12")
        finally:
            am.AXES = orig

    def test_non_increasing_rungs_is_a_PROBLEM(self):
        orig = am.RUNGS_USD
        try:
            am.RUNGS_USD = (40_000.0, 5_000.0)
            self.assertTrue(any("возраст" in p for p in am.validate()))
        finally:
            am.RUNGS_USD = orig

    def test_zero_rung_is_a_PROBLEM(self):
        orig = am.RUNGS_USD
        try:
            am.RUNGS_USD = (0.0, 5_000.0)
            self.assertTrue(any("не положительна" in p for p in am.validate()))
        finally:
            am.RUNGS_USD = orig

    def test_forbidden_neighbour_without_a_reason_is_a_PROBLEM(self):
        orig = am.AXES
        try:
            am.AXES = tuple(
                dict(a, not_a_source=(("x.json", ""),)) if a["axis"] == "capacity" else a
                for a in orig)
            self.assertTrue(any("без причины" in p for p in am.validate()),
                            "запрет подстановки без причины запретом не является")
        finally:
            am.AXES = orig

    def test_broken_declaration_makes_measure_UNMEASURED__not_a_number(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            orig = am.RUNGS_USD
            try:
                am.RUNGS_USD = ()
                rep = am.measure(d, now=_NOW)
            finally:
                am.RUNGS_USD = orig
        self.assertEqual(rep["verdict"], "UNMEASURED")
        self.assertNotIn("opportunities", rep)


# ---------------------------------------------------------------------------
# 2. Предмет записи: по ЗНАЧЕНИЮ поля И по КЛЮЧУ отображения
# ---------------------------------------------------------------------------
class RecordSubjects(unittest.TestCase):
    def test_subject_in_a_field_value(self):
        subs, n = am.record_subjects([{"protocol": "Aave V3"}, {"name": "maple"}])
        self.assertEqual(subs, {"aave_v3", "maple"})
        self.assertEqual(n, 2)

    def test_subject_as_a_MAPPING_KEY__adapter_status_shape(self):
        # Положительный контроль дефекта, найденного в СВОЕЙ работе: первая
        # редакция читала только значения полей, и ЕДИНСТВЕННАЯ измеримая ось
        # §12 получала `no_subject` при живых привязанных данных.
        subs, _ = am.record_subjects({"adapters": {"aave_v3": {"apy": 1.0},
                                                   "maple": {"apy": 2.0}}})
        self.assertIn("aave_v3", subs)
        self.assertIn("maple", subs)

    def test_records_without_any_subject_key__empty_set_but_NONZERO_count(self):
        subs, n = am.record_subjects([{"total_trades": 1}, {"total_trades": 2}])
        self.assertEqual(subs, set())
        self.assertEqual(n, 2, "«предмета нет» и «записей нет» — разные состояния")

    def test_nested_positions_are_read(self):
        subs, _ = am.record_subjects([{"positions": [{"protocol": "pendle"}]}])
        self.assertIn("pendle", subs)


# ---------------------------------------------------------------------------
# 3. Состояния оси: девять исходов, и ни один не выдаётся за другой
# ---------------------------------------------------------------------------
class AxisStates(unittest.TestCase):
    def _state(self, axis: str, data_dir: Path, now=None) -> dict:
        got = {a["axis"]: a for a in am.axes_state(data_dir, _adapters(),
                                                   now=now or _NOW)}
        return got[axis]

    def test_absent_file(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            self.assertEqual(self._state("capacity", d)["state"], "absent")

    def test_empty_file_is_NOT_an_answer(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t), extra_files={"vault_capacity_dilution_log.json": []})
            st = self._state("capacity", d)
            self.assertEqual(st["state"], "empty")
            self.assertIn("ПУСТ", st["detail"])

    def test_unparsed_file_names_its_reason(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            (d / "vault_capacity_dilution_log.json").write_text("{не json",
                                                                encoding="utf-8")
            st = self._state("capacity", d)
            self.assertEqual(st["state"], "unparsed")
            self.assertIn("не разобран", st["detail"])

    def test_records_without_subject_give_no_subject(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t), extra_files={
                "vault_capacity_dilution_log.json": [{"score": 1}, {"score": 2}]})
            self.assertEqual(self._state("capacity", d)["state"], "no_subject")

    def test_FIXTURE_SUBJECT__a_full_fresh_file_about_nobody_we_hold(self):
        # ПРЕДМЕТ ЭТОГО ЦИКЛА. Файл НЕ ПУСТ, свеж и по длине неотличим от живого
        # наблюдения — и ни одно его число не привязывается к возможности.
        with TemporaryDirectory() as t:
            d = _scene(Path(t), extra_files={
                "vault_capacity_dilution_log.json":
                    [{"protocol_name": "TestProtocol", "capacity_usd": 1.0}] * 100})
            st = self._state("capacity", d)
            self.assertEqual(st["state"], "fixture_subject")
            self.assertNotEqual(st["state"], "empty",
                                "длина файла мерой привязки не является")
            self.assertEqual(st["source_states"][0]["records"], 100)

    def test_bound_but_unread_gives_no_consumer__NOT_credited(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t), extra_files={
                "vault_capacity_dilution_log.json":
                    [{"protocol": "thin_pool", "capacity_usd": 1.0}]})
            st = self._state("capacity", d)
            self.assertEqual(st["state"], "no_consumer")

    def test_reward_dilution_IS_credited__the_only_one_of_seven(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            self.assertEqual(self._state("reward_dilution", d)["state"], "credited")
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["axes_credited_names"], ["reward_dilution"])
        self.assertEqual(rep["axes_credited"], 1)
        self.assertEqual(rep["axes_blind"], 6)

    def test_staleness_is_an_INPUT_not_the_wall_clock(self):
        # ОДНИ И ТЕ ЖЕ БАЙТЫ, два разных `now` — два разных вердикта. Если бы
        # срок мерился стенными часами, этот тест был бы будильником.
        with TemporaryDirectory() as t:
            d = _scene(Path(t), extra_files={
                "vault_capacity_dilution_log.json":
                    [{"protocol": "thin_pool", "capacity_usd": 1.0}]})
            fresh_now = datetime.now(timezone.utc)
            late_now = fresh_now + timedelta(hours=am.SOURCE_MAX_AGE_H + 1)
            self.assertEqual(self._state("capacity", d, now=fresh_now)["state"],
                             "no_consumer")
            self.assertEqual(self._state("capacity", d, now=late_now)["state"],
                             "stale")

    def test_forbidden_neighbour_is_PRINTED_not_silently_skipped(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            st = self._state("utilization", d)
        names = [n["source"] for n in st["not_a_source"]]
        self.assertIn("borrowing_power_utilization_log.json", names)
        self.assertTrue(all(n["reason"].strip() for n in st["not_a_source"]))


# ---------------------------------------------------------------------------
# 4. Арифметика лестницы: ВИЛКА, порядок и знак
# ---------------------------------------------------------------------------
class LadderArithmetic(unittest.TestCase):
    def test_bracket_is_ordered_lower_le_modelled_le_upper(self):
        g = am.ladder_rung(base_pct=4.0, reward_pct=1.0,
                           tvl_usd=1_000_000.0, amount_usd=40_000.0)
        self.assertLessEqual(g["apy_lower_pct"], g["apy_modelled_pct"])
        self.assertLessEqual(g["apy_modelled_pct"], g["apy_upper_pct"])
        self.assertGreater(g["apy_bracket_width_pp"], 0.0)

    def test_rate_never_RISES_with_our_size(self):
        prev = None
        for amt in am.RUNGS_USD:
            g = am.ladder_rung(4.0, 1.0, 1_000_000.0, amt)
            if prev is not None:
                self.assertLessEqual(g["apy_upper_pct"], prev["apy_upper_pct"])
                self.assertLessEqual(g["apy_lower_pct"], prev["apy_lower_pct"])
                self.assertGreaterEqual(g["apy_bracket_width_pp"],
                                        prev["apy_bracket_width_pp"])
            prev = g

    def test_THIN_pool_is_hurt_MORE_than_a_deep_one__two_series_compared(self):
        # Контроль ЗНАКА. Сравниваются ДВА РЯДА между собой, а не число с самим
        # собой: при обратном знаке самый разбавляемый пул получил бы САМУЮ
        # щедрую оценку — инверсия всего замысла §12, и прошлый цикл показал
        # мутацией, что иначе её не видно.
        thin = am.ladder_rung(4.0, 1.0, 1_000_000.0, 40_000.0)
        deep = am.ladder_rung(4.0, 1.0, 1_000_000_000.0, 40_000.0)
        self.assertLess(thin["apy_lower_pct"], deep["apy_lower_pct"])
        self.assertLess(thin["apy_upper_pct"], deep["apy_upper_pct"])
        self.assertGreater(thin["apy_bracket_width_pp"],
                           deep["apy_bracket_width_pp"])
        self.assertGreater(thin["share_of_pool_pct"], deep["share_of_pool_pct"])

    def test_pure_base_rate_keeps_its_UPPER_bound__reward_is_what_dilutes(self):
        g = am.ladder_rung(base_pct=4.0, reward_pct=0.0,
                           tvl_usd=1_000_000.0, amount_usd=40_000.0)
        self.assertAlmostEqual(g["apy_upper_pct"], 4.0, places=6)
        self.assertLess(g["apy_lower_pct"], 4.0)

    def test_zero_width_is_MEASURED_zero__not_absent(self):
        g = am.ladder_rung(4.0, 0.0, 1e15, 5_000.0)
        self.assertEqual(g["apy_bracket_width_pp"], 0.0)
        self.assertIsNotNone(g["apy_bracket_width_pp"])


# ---------------------------------------------------------------------------
# 5. Отказы: три исхода, и каждый со СВОЕЙ причиной
# ---------------------------------------------------------------------------
class Refusals(unittest.TestCase):
    def _ladder(self, **over):
        a = dict(_adapters()["thin_pool"])
        a.update(over)
        return am.opportunity_ladder(a)

    def test_static_tvl_is_REFUSED__ADR_053(self):
        rec = self._ladder(tvl_source="static")
        self.assertNotIn("rungs", rec)
        self.assertIn("ADR-053", rec["unmeasured"])

    def test_unmeasured_composition_is_REFUSED__not_all_base(self):
        rec = self._ladder(apy_composition_unmeasured="пул не разрешён")
        self.assertNotIn("rungs", rec)
        self.assertIn("нулевое влияние", rec["unmeasured"])

    def test_missing_base_is_REFUSED(self):
        rec = self._ladder(apy_base=None)
        self.assertNotIn("rungs", rec)
        self.assertIn("apy_base", rec["unmeasured"])

    def test_missing_reward_is_REFUSED(self):
        rec = self._ladder(apy_reward=None)
        self.assertNotIn("rungs", rec)
        self.assertIn("apy_reward", rec["unmeasured"])

    def test_clean_opportunity_measures_every_declared_rung(self):
        rec = self._ladder()
        self.assertEqual([g["amount_usd"] for g in rec["rungs"]],
                         list(am.RUNGS_USD))


# ---------------------------------------------------------------------------
# 6. measure(): НЕ ИЗМЕРЕНО отличимо от нуля возможностей
# ---------------------------------------------------------------------------
class MeasureWholeness(unittest.TestCase):
    def test_absent_adapter_status_is_UNMEASURED(self):
        with TemporaryDirectory() as t:
            d = Path(t) / "data"
            d.mkdir()
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["verdict"], "UNMEASURED")
        self.assertEqual(rep["status"], "SKIPPED")

    def test_empty_adapters_is_UNMEASURED__not_zero_opportunities(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t), adapters={})
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["verdict"], "UNMEASURED")
        self.assertIn("неразличимы", rep["reason"])

    def test_counts_split_measured_from_unmeasured(self):
        with TemporaryDirectory() as t:
            ads = _adapters()
            ads["frozen"] = {"display_name": "Frozen", "apy": 3.0,
                             "apy_base": 3.0, "apy_reward": 0.0,
                             "tvl_usd": 7.0, "tvl_source": "static", "tier": 3}
            d = _scene(Path(t), adapters=ads)
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["counts"]["opportunities"], 3)
        self.assertEqual(rep["counts"]["ladder_measured"], 2)
        self.assertEqual(rep["counts"]["ladder_unmeasured"], 1)

    def test_worst_adapter_is_the_THIN_one(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["top_rung_worst_adapter"], "thin_pool")

    def test_no_ladder_at_all_is_UNMEASURED_with_named_reasons(self):
        with TemporaryDirectory() as t:
            ads = {"frozen": {"apy": 3.0, "apy_base": 3.0, "apy_reward": 0.0,
                              "tvl_usd": 7.0, "tvl_source": "static"}}
            d = _scene(Path(t), adapters=ads)
            rep = am.measure(d, now=_NOW)
        self.assertEqual(rep["verdict"], "UNMEASURED")
        self.assertEqual(rep["counts"]["ladder_measured"], 0)
        self.assertTrue(rep["opportunities"][0]["unmeasured"])

    def test_cli_exit_codes_are_distinguishable(self):
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            self.assertEqual(am.main(["--data-dir", str(d)]), 0)
            empty = Path(t) / "nothing"
            empty.mkdir()
            self.assertEqual(am.main(["--data-dir", str(empty)]), 2)


# ---------------------------------------------------------------------------
# 7. ПРОВОДКА: секция обязана быть ПОЗВАНА циклом и ОБЪЯВЛЕНА по родам
# ---------------------------------------------------------------------------
class Wiring(unittest.TestCase):
    """Без этих проверок снятие секции из перечня отчёта не покраснило бы
    ничего, и числа §12 не производились бы ни одним циклом при зелёной
    батарее — ровно класс «прибор написан и не позван» (находка #1071)."""

    def test_section_is_in_the_cycle_report(self):
        self.assertIn("marginal_apy_ladder", SECTION_NAMES)

    def test_section_is_built_BEFORE_the_kind_census(self):
        self.assertLess(SECTION_NAMES.index("marginal_apy_ladder"),
                        SECTION_NAMES.index("apy_name_census"),
                        "перепись родов судит соседей ТОГО ЖЕ прогона")

    def test_name_does_not_collide_with_the_neighbour_instrument(self):
        # `.claude/rules/adapters.md` § «Одно имя — один объект».
        from spa_core.monitoring import marginal_apy_at_size as neighbour
        self.assertNotEqual(am.ENGINE, "marginal_apy_at_size")
        # Сосед ЖИВ и пишет СВОЙ артефакт: имя занято не пустотой, и если
        # кто-то снесёт соседа, этот контроль покраснеет, а не промолчит.
        self.assertEqual(neighbour.REPORT_REL, "data/marginal_apy_at_size.json")
        self.assertNotIn("sections/marginal_apy_at_size",
                         "".join(apy_kinds.PATH_KINDS),
                         "пути §12 обязаны стоять под СВОИМ именем секции")

    def test_every_apy_named_number_of_the_section_is_DECLARED(self):
        from spa_core.analytics.apy_name_census import _walk
        with TemporaryDirectory() as t:
            d = _scene(Path(t))
            rep = am.measure(d, now=_NOW)
        numbers: dict = {}
        non_numeric: dict = {}
        _walk(rep, "sections/marginal_apy_ladder", numbers, non_numeric)
        undeclared = [p for p in numbers if apy_kinds.kind_of(p) is None]
        self.assertEqual(undeclared, [],
                         "apy-именованное число без объявленного рода")
        self.assertTrue(numbers, "перепись не нашла ни одного числа — "
                                 "проверка была бы пустой")

    def test_declared_kinds_are_FORWARD_and_never_wear_an_evidence_base(self):
        for name in ("position_rate_at_size_upper",
                     "position_rate_at_size_modelled",
                     "position_rate_at_size_lower"):
            k = apy_kinds.KINDS[name]
            self.assertEqual(k.horizon, "forward")
            self.assertEqual(k.evidence, "not_applicable")
            self.assertEqual(k.window, "today_at_size")

    def test_bracket_width_is_declared_NOT_a_rate(self):
        k = apy_kinds.KINDS["rate_bracket_width_pp"]
        self.assertFalse(k.is_rate)
        self.assertIsNone(k.denominator)

    def test_layer_is_advisory(self):
        self.assertTrue(am.IS_ADVISORY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
