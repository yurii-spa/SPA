"""ADR-867 · ТРЕТЬЯ дверь семейства ADR-864: сравнение ФОРМ судит ОДНУ книгу.

Положительный контроль у каждого теста — настоящая находка цикла #984, а не
выдуманная сцена: у ``trim_shape.compare_trim_shapes`` цена формы считалась по
МАТЕРИАЛЬНЫМ ногам, а её выигрыш — по ОБЪЯВЛЕННОЙ книге формы. На прод-истории
(166 записей, 105 урезаемых предложений) подпороговую ногу несли **13**
записей, и у **пяти** она доставалась РОВНО одной форме: победа одной формы над
другой создавалась неисполнимой ногой, а не формой.

Проверка идёт ИСХОДОМ на настоящей двери и в обе стороны: проба зелена на целом
контуре и КРАСНА на каждом порванном звене — с названным звеном (ADR-333).
Живой ``data/`` не читается ни одним тестом файла.

FROZEN-DATE-OK: сцена переписи несёт даты ``2026-01-01…03`` как ЯРЛЫКИ записей —
перепись форм ни одного окна свежести не применяет, и ни один вердикт файла от
календаря не зависит.
"""

import unittest
from unittest import mock

from spa_core.allocator import rebalance_economics as _re
from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES,
                                                 SATISFIED, UNMEASURED)
from spa_core.paper_trading import trim_shape as _ts

PROBE_NAME = "shape_comparison_judges_one_book"


def _scene_params():
    """Те же живые пороги, из которых пробу строит сама проба."""
    from spa_core.paper_trading.admissible_size import admissible_turnover_usd

    params = _re.TriggerParams.for_mode("paper")
    capital = 100_000.0
    cap_usd = float(admissible_turnover_usd(capital, params))
    leg_usd = float(params.min_leg_frac) * capital
    base_move = 1.2 * cap_usd
    boundary = leg_usd * base_move / (cap_usd - leg_usd)
    return params, capital, base_move, boundary, leg_usd


class ThirdDoorJudgesOneBook(unittest.TestCase):
    """Сама дверь: отказ там, где нога не исполнится, и счёт там, где исполнится."""

    def setUp(self):
        self.params, self.capital, self.base, self.boundary, self.leg = _scene_params()
        from spa_core.monitoring import card_acceptance as ca

        self.cur = dict(ca._SHAPE_CURRENT)
        self.apy = dict(ca._SHAPE_APY)
        self.chains = dict(ca._SHAPE_CHAINS)
        self._scene = ca._shape_scene

    def _compare(self, delta):
        return _ts.compare_trim_shapes(
            self.cur, self._scene(self.base, delta), self.apy,
            capital_usd=self.capital, params=self.params,
            chains=self.chains, chains_measured=True)

    def test_subthreshold_leg_in_one_form_is_refused_and_named(self):
        """Рваная сцена: форма с подпороговой ногой ОТКАЗАНА, протокол НАЗВАН."""
        rec = self._compare(self.boundary - 5.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_REFUSED, rec.get("why"))
        self.assertIn("aave_v3", rec["interpolated"]["unexecuted_legs"])
        self.assertEqual(rec["subset"]["unexecuted_legs"], {})
        self.assertEqual(rec["refused_sides"], ["interpolated"])
        self.assertIn("ADR-864", rec["why"])

    def test_a_refused_form_prints_no_gain_no_payback_no_delta(self):
        """Отказ ЗАМЕНЯЕТ число, а не стоит пометкой рядом с ним.

        Это и есть предмет: напечатанный выигрыш остался бы читаемым, а он
        посчитан по книге, которой ход держать не будет.
        """
        rec = self._compare(self.boundary - 5.0)
        for field in ("gain_pp", "payback_days", "cost_usd", "cost_bps"):
            self.assertNotIn(field, rec["interpolated"])
            self.assertNotIn(field, rec["subset"])
        for field in ("gain_delta_pp", "cost_delta_usd", "payback_delta_days",
                      "legs_delta"):
            self.assertNotIn(field, rec)

    def test_a_leg_above_the_threshold_is_still_compared(self):
        """Целая сцена: отказ НЕ съел сравнение, у которого все ноги исполнимы."""
        rec = self._compare(self.boundary + 5.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_MEASURED, rec.get("why"))
        self.assertEqual(rec["interpolated"]["unexecuted_legs"], {})
        self.assertEqual(rec["subset"]["unexecuted_legs"], {})
        self.assertIsNotNone(rec["interpolated"]["gain_pp"])

    def test_no_leg_at_all_is_absence_not_dust(self):
        """Нулевая сцена: ноль есть ОТСУТСТВИЕ ноги, а не пыль."""
        rec = self._compare(0.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_MEASURED, rec.get("why"))
        self.assertEqual(rec["interpolated"]["unexecuted_legs"], {})
        self.assertIsNotNone(rec["subset"]["payback_days"])

    def test_the_axis_is_declared_even_when_it_is_empty(self):
        """Пустой словарь — «измерено и равно нулю» (инв. #17), а не пропуск поля."""
        for delta in (0.0, self.boundary + 5.0):
            rec = self._compare(delta)
            for side in ("interpolated", "subset"):
                self.assertIn("unexecuted_legs", rec[side],
                              f"дельта {delta}: ось формы {side} не объявлена")

    def test_the_wiring_leads_to_the_single_adr_864_door(self):
        """Своего правила пыли у третьей двери нет — она зовёт ЧУЖУЮ дверь.

        Контроль именно подменой ``rebalance_economics.unexecuted_legs``: заведи
        третья дверь свою копию порога, подмена ничего бы не изменила, и
        расхождение копий вернулось бы молча (класс ADR-340).
        """
        with mock.patch.object(_re, "unexecuted_legs", return_value={}):
            rec = self._compare(self.boundary - 5.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_MEASURED,
                         "отказ выжил подмену ЕДИНСТВЕННОЙ двери ⇒ у третьей двери "
                         "своя копия правила пыли")


class TheOtherHalfOfTheDoorIsTheSubsetForm(unittest.TestCase):
    """Пыль у ПОДМНОЖЕСТВА — другой механизм и отдельное звено.

    У интерполяции пыль берётся из множителя ``k``, у подмножества — из
    ЧАСТИЧНОГО ДОБОРА (``subset_trim`` берёт ``min(room, left)`` у последней
    ноги стороны). Положительный контроль мутационный: замер #984 с одной лишь
    сценой интерполяции оставил мутанта «дверь не спрашивается у формы
    подмножества» ЖИВЫМ — при том, что на прод-истории подпороговую ногу несёт
    подмножество у ДЕСЯТИ записей из тринадцати.
    """

    def setUp(self):
        from spa_core.monitoring import card_acceptance as ca

        self.params, self.capital, _b, _bo, self.leg = _scene_params()
        from spa_core.paper_trading.admissible_size import admissible_turnover_usd

        self.cap_usd = float(admissible_turnover_usd(self.capital, self.params))
        self.cur = dict(ca._SHAPE_CURRENT)
        self.apy = dict(ca._SHAPE_APY)
        self.chains = dict(ca._SHAPE_CHAINS)
        self._scene = ca._shape_subset_scene

    def _compare(self, room_best):
        return _ts.compare_trim_shapes(
            self.cur, self._scene(room_best, 3.0 * self.leg), self.apy,
            capital_usd=self.capital, params=self.params,
            chains=self.chains, chains_measured=True)

    def test_a_partial_top_up_below_the_threshold_is_refused(self):
        rec = self._compare(self.cap_usd - self.leg / 2.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_REFUSED, rec.get("why"))
        self.assertEqual(rec["refused_sides"], ["subset"])
        self.assertIn("fluid_fusdc", rec["subset"]["unexecuted_legs"])
        self.assertEqual(rec["interpolated"]["unexecuted_legs"], {})

    def test_a_partial_top_up_above_the_threshold_is_still_compared(self):
        rec = self._compare(self.cap_usd - 2.0 * self.leg)
        self.assertEqual(rec["kind"], _ts.SHAPE_MEASURED, rec.get("why"))
        self.assertEqual(rec["subset"]["unexecuted_legs"], {})
        self.assertIsNotNone(rec["subset"]["payback_days"])

    def test_the_subset_door_is_the_same_single_adr_864_door(self):
        with mock.patch.object(_re, "unexecuted_legs", return_value={}):
            rec = self._compare(self.cap_usd - self.leg / 2.0)
        self.assertEqual(rec["kind"], _ts.SHAPE_MEASURED,
                         "отказ подмножества выжил подмену ЕДИНСТВЕННОЙ двери")


class CensusCountsTheRefusalAsAPopulation(unittest.TestCase):
    """Отказ — население, а не вычет из населения."""

    def setUp(self):
        self.params, self.capital, self.base, self.boundary, _leg = _scene_params()
        from spa_core.monitoring import card_acceptance as ca

        self.chains = dict(ca._SHAPE_CHAINS)
        self.records = [
            {"cycle_date": "2026-01-01", "capital_usd": self.capital,
             "current_positions": dict(ca._SHAPE_CURRENT),
             "apy_evidenced_pct": dict(ca._SHAPE_APY),
             "target_positions": ca._shape_scene(self.base, self.boundary - 5.0)},
            {"cycle_date": "2026-01-02", "capital_usd": self.capital,
             "current_positions": dict(ca._SHAPE_CURRENT),
             "apy_evidenced_pct": dict(ca._SHAPE_APY),
             "target_positions": ca._shape_scene(self.base, self.boundary + 5.0)},
        ]
        from spa_core.paper_trading.admissible_size import admissible_turnover_usd

        cap_usd = float(admissible_turnover_usd(self.capital, self.params))
        leg = float(self.params.min_leg_frac) * self.capital
        self.subset_dusty = {
            "cycle_date": "2026-01-03", "capital_usd": self.capital,
            "current_positions": dict(ca._SHAPE_CURRENT),
            "apy_evidenced_pct": dict(ca._SHAPE_APY),
            "target_positions": ca._shape_subset_scene(cap_usd - leg / 2.0,
                                                       3.0 * leg)}

    def _census(self, records=None):
        return _ts.trim_shape_census(records if records is not None else self.records,
                                     params=self.params, chains=self.chains,
                                     chains_measured=True)

    def test_the_refusal_is_split_by_form(self):
        cen = self._census()
        self.assertEqual(cen["refused"]["population"], 1)
        self.assertEqual(cen["refused"]["only_interpolated"], 1)
        self.assertEqual(cen["refused"]["only_subset"], 0)
        self.assertEqual(cen["refused"]["both_forms"], 0)
        self.assertEqual(cen["population"], 1)
        self.assertEqual(cen["outcomes"].get(_ts.SHAPE_REFUSED), 1)

    def test_both_forms_are_split_apart_in_the_census(self):
        """Ось «нога РОВНО у одной формы» различает, у КАКОЙ именно."""
        cen = self._census(self.records + [self.subset_dusty])
        self.assertEqual(cen["refused"]["population"], 2)
        self.assertEqual(cen["refused"]["only_interpolated"], 1)
        self.assertEqual(cen["refused"]["only_subset"], 1)
        self.assertEqual(cen["refused"]["both_forms"], 0)

    def test_zero_refusals_is_a_measurement_not_a_silence(self):
        """«Дверь спрошена, таких ног нет» обязано отличаться от «не спрашивали»."""
        cen = self._census([self.records[1]])
        self.assertEqual(cen["refused"]["population"], 0)
        self.assertEqual(cen["refused"]["only_interpolated"], 0)

    def test_the_printed_report_names_the_refusal_even_at_zero(self):
        lines = _ts.format_trim_shape(self._census([self.records[1]]))
        self.assertTrue(any("отказ ADR-867" in ln for ln in lines),
                        f"печать переписи молчит об отказе: {lines}")

    def test_the_printed_report_names_an_absent_block_as_unmeasured(self):
        """Блока нет ⇒ ТРЕТИЙ исход, а не молчание: неизвестно, спрашивали ли дверь."""
        cen = self._census()
        cen.pop("refused")
        lines = _ts.format_trim_shape(cen)
        self.assertTrue(any("НЕ ИЗМЕРЕН" in ln for ln in lines), lines)


class ProbeIsRedOnEveryTornLink(unittest.TestCase):
    """Приёмка ADR-333: зелена на целом контуре, красна на КАЖДОМ порванном звене."""

    def _probe(self):
        return PROBES[PROBE_NAME](None)

    def test_whole_contour_is_green(self):
        verdict, why = self._probe()
        self.assertEqual(verdict, SATISFIED, why)

    def test_link_1_the_adr_864_door_disabled(self):
        with mock.patch.object(_re, "unexecuted_legs", return_value={}):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("РВАНАЯ", why)

    def test_link_2_the_local_wiring_disabled(self):
        """Звено проводки рвётся ОТДЕЛЬНО от самой двери — иначе контроль
        «сравнение форм перестало отказывать» был бы неотличим от контроля
        «вердикт цикла перестал отказывать»."""
        with mock.patch.object(_ts, "_unexecuted", return_value={}):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)

    def test_link_3_the_refusal_eats_an_executable_comparison(self):
        """Обратная сторона: отказ, выданный ВСЕМУ, — тоже дефект, а не строгость.

        Отказ, доставшийся КАЖДОЙ форме, проба ловит первым же вопросом «какая
        форма отказана»: ``['interpolated', 'subset']`` там, где пыль только у
        подмножества. Вердикт один и тот же — не пропустить; проверяется ИМЕННО
        он, а не формулировка первой сработавшей проверки.
        """
        with mock.patch.object(_ts, "_unexecuted",
                               return_value={"aave_v3": 1.0}):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertTrue("съел" in why or "refused_sides" in why, why)

    def test_link_4_the_axis_dropped_from_the_record(self):
        real = _ts.compare_trim_shapes

        def _without_axis(*a, **kw):
            rec = real(*a, **kw)
            for side in ("interpolated", "subset"):
                if isinstance(rec.get(side), dict):
                    rec[side].pop("unexecuted_legs", None)
            return rec

        with mock.patch.object(_ts, "compare_trim_shapes", _without_axis):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("unexecuted_legs", why)

    def test_link_5_the_refused_form_keeps_printing_its_gain(self):
        real = _ts.compare_trim_shapes

        def _with_gain(*a, **kw):
            rec = real(*a, **kw)
            if rec.get("kind") == _ts.SHAPE_REFUSED:
                rec["interpolated"]["gain_pp"] = 0.5
            return rec

        with mock.patch.object(_ts, "compare_trim_shapes", _with_gain):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("gain_pp", why)

    def test_link_6_the_census_stops_counting_the_refusal(self):
        real = _ts.trim_shape_census

        def _without_block(*a, **kw):
            cen = real(*a, **kw)
            cen.pop("refused", None)
            return cen

        with mock.patch.object(_ts, "trim_shape_census", _without_block):
            verdict, why = self._probe()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("refused", why)

    def test_the_probe_refuses_an_argument(self):
        verdict, why = PROBES[PROBE_NAME]("x")
        self.assertEqual(verdict, UNMEASURED, why)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
