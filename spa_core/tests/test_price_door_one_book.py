"""ADR-864: цена хода и его выигрыш обязаны судить ОДНУ книгу.

Предмет. ``rebalance_economics._legs`` выбрасывает дельту
``abs(delta) <= min_leg_frac · capital`` ЦЕЛИКОМ: такая нога не платит ни газа,
ни проскальзывания, ни моста — и НЕ ИСПОЛНЯЕТСЯ. Выигрыш же считался по
ОБЪЯВЛЕННОЙ цели, где эти деньги уже переложены. Знак ошибки зависел от
направления дельты: неисполненная ПОКУПКА начисляла доход деньгам, которые не
двинулись (fail-OPEN), неисполненная ПРОДАЖА отнимала доход у денег, которые
остались на месте.

Положительный контроль — настоящий замер цикла #978 (ADR-861): из 8 «улучшений»
против края отрезка допустимых размеров ВСЕ 8 созданы ровно этой полосой, и
перебор сам сползал к ``min_leg_usd − $0.01``, потому что там приз ничего не
стоит. После ADR-864 на той же истории улучшений **ноль**.

Почему ответ — ОТКАЗ, а не «правильная книга»: первая редакция правки считала
ставку по книге удержания и была ИЗМЕРЕНА НЕВЕРНОЙ (приз не исчез, а вырос:
строго лучших 8 → 19, лучший выигрыш 1.6 → 47.81 дн.), потому что книга
удержания НЕ СОХРАНЯЕТ ДЕНЬГИ — ``trim_optimum._fill`` строит книгу так, что
``buy − sell`` равно объявленному движению кэша. Подробности — в докстринге
``rebalance_economics.unexecuted_legs``.
"""
# FROZEN-DATE-OK: нет ни одной даты — предмет про арифметику двери, не про свежесть

from __future__ import annotations

import unittest
from unittest import mock

from spa_core.allocator import rebalance_economics as re_mod
from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES,
                                                 SATISFIED, UNMEASURED)
from spa_core.paper_trading import trim_optimum as topt

CAPITAL = 100_000.0
PARAMS = re_mod.TriggerParams.for_mode("paper")
MIN_LEG_USD = PARAMS.min_leg_frac * CAPITAL          # $500 при капитале $100 000
APY = {"aave_v3": 5.5724, "compound_v3": 5.31, "morpho_blue_base": 9.0}
CHAINS = {"aave_v3": "ethereum", "compound_v3": "ethereum",
          "morpho_blue_base": "base"}
CURRENT = {"aave_v3": 5_000.0, "compound_v3": 40_000.0, "morpho_blue_base": 0.0}

PROBE_NAME = "price_door_and_gain_door_judge_one_book"


def _target(aave_delta: float) -> dict:
    """Цель, отличающаяся от соседней РОВНО размером дельты ``aave_v3``."""
    return {"aave_v3": CURRENT["aave_v3"] + aave_delta,
            "compound_v3": 30_000.0, "morpho_blue_base": 10_000.0}


def _evaluate(target: dict):
    return re_mod.evaluate(current_positions=dict(CURRENT),
                           target_positions=target, apy_pct=APY,
                           evidenced=set(APY), chains=CHAINS,
                           capital_usd=CAPITAL, params=PARAMS)


def _score(target: dict):
    return topt.score_book(dict(CURRENT), target, APY, capital_usd=CAPITAL,
                           min_leg_frac=PARAMS.min_leg_frac, chains=CHAINS)


def _refused(decision) -> bool:
    return any(str(r).startswith("proposal_has_unexecuted_legs")
               for r in (decision.reasons or []))


class TheDoorNamesWhatItWillNotExecute(unittest.TestCase):
    """Сама дверь: ЧТО она называет и чего НЕ называет."""

    def test_a_sub_threshold_nonzero_delta_is_named(self):
        legs, _turnover = re_mod._legs(CURRENT, _target(MIN_LEG_USD - 0.01),
                                       CAPITAL, PARAMS.min_leg_frac)
        self.assertNotIn("aave_v3", {leg["protocol"] for leg in legs},
                         "подпороговая нога попала в ноги — предмет исчез")
        self.assertEqual(
            re_mod.unexecuted_legs(CURRENT, _target(MIN_LEG_USD - 0.01),
                                   CAPITAL, PARAMS.min_leg_frac),
            {"aave_v3": 499.99})

    def test_a_delta_above_the_threshold_is_not_named(self):
        self.assertEqual(
            re_mod.unexecuted_legs(CURRENT, _target(MIN_LEG_USD + 0.01),
                                   CAPITAL, PARAMS.min_leg_frac), {})

    def test_a_zero_delta_is_absence_of_a_move_not_dust(self):
        """Ноль — не пыль. Иначе отказ съел бы подмножество без протокола,
        то есть ровно рычаг «меньше ног — меньше газа»."""
        self.assertEqual(
            re_mod.unexecuted_legs(CURRENT, _target(0.0), CAPITAL,
                                   PARAMS.min_leg_frac), {})

    def test_the_threshold_itself_is_still_dust(self):
        """Дверь ``_legs`` отсекает НЕСТРОГО — ровно на пороге дельта ещё пыль."""
        self.assertEqual(
            re_mod.unexecuted_legs(CURRENT, _target(MIN_LEG_USD), CAPITAL,
                                   PARAMS.min_leg_frac),
            {"aave_v3": 500.0})


class TheVerdictRefusesAMoveItCannotPrice(unittest.TestCase):
    """Вердикт цикла: отказ НАЗВАН, и он не съедает исполнимые ходы."""

    def test_the_torn_move_is_held_with_the_protocol_named(self):
        d = _evaluate(_target(MIN_LEG_USD - 0.01))
        self.assertEqual(d.decision, "HOLD")
        self.assertTrue(_refused(d), d.reasons)
        self.assertIn("aave_v3", str(d.reasons))
        self.assertEqual(d.evidence["unexecuted_legs"], {"aave_v3": 499.99})

    def test_the_whole_move_is_priced_as_before(self):
        d = _evaluate(_target(MIN_LEG_USD + 0.01))
        self.assertFalse(_refused(d), d.reasons)
        self.assertEqual(d.evidence["unexecuted_legs"], {})
        self.assertGreater(len(d.legs), 0)

    def test_the_axis_is_published_even_when_empty(self):
        """Инв. #17: пустой словарь — «измерено и равно нулю», а не отсутствие."""
        for name, delta in (("целая", MIN_LEG_USD + 0.01), ("нулевая", 0.0)):
            with self.subTest(scene=name):
                d = _evaluate(_target(delta))
                self.assertIn("unexecuted_legs", d.evidence)
                self.assertEqual(d.evidence["unexecuted_legs"], {})

    def test_no_legs_at_all_keeps_its_own_reason(self):
        """«Ног нет вовсе» и «часть ног дверь не исполнит» — РАЗНЫЕ состояния."""
        only_dust = {"aave_v3": CURRENT["aave_v3"] + MIN_LEG_USD - 0.01,
                     "compound_v3": CURRENT["compound_v3"] - MIN_LEG_USD + 0.01,
                     "morpho_blue_base": 0.0}
        d = _evaluate(only_dust)
        self.assertIn("no_material_legs", d.reasons)
        self.assertFalse(_refused(d),
                         "состояния слиты: отказ подменил «ног нет вовсе»")


class TheSizeScanCannotWinInTheDustBand(unittest.TestCase):
    """Перебор размеров: щель, которой он сползал к порогу, закрыта."""

    def test_a_book_with_an_unexecutable_leg_is_not_scored(self):
        self.assertIsNone(_score(_target(MIN_LEG_USD - 0.01)))

    def test_the_same_book_one_cent_above_the_threshold_is_scored(self):
        scored = _score(_target(MIN_LEG_USD + 0.01))
        self.assertIsNotNone(scored)
        self.assertIsNotNone(scored["payback_days"])

    def test_a_book_without_the_delta_is_scored(self):
        scored = _score(_target(0.0))
        self.assertIsNotNone(scored, "рычаг «меньше ног — меньше газа» закрыт")

    def test_the_scan_wiring_uses_the_one_door(self):
        """Своей копии правила пыли у перебора нет: проводка зовёт дверь."""
        with mock.patch.object(re_mod, "unexecuted_legs",
                               return_value={}) as door:
            self.assertIsNotNone(_score(_target(MIN_LEG_USD - 0.01)))
        self.assertTrue(door.called, "проводка не дошла до двери")


class TheAcceptanceProbeHasAControlInBothDirections(unittest.TestCase):
    """Правило приёмки, п. 3: зелена на ЦЕЛОМ контуре, красна на КАЖДОМ рваном
    звене — с НАЗВАННЫМ звеном, и не проходит подстрокой."""

    def _ask(self):
        return PROBES[PROBE_NAME](None)

    def test_the_whole_circuit_is_satisfied(self):
        verdict, why = self._ask()
        self.assertEqual(verdict, SATISFIED, why)
        self.assertIn("500.00", why)

    def test_a_door_that_refuses_nothing_is_refused(self):
        """Звено 1 — дверь перестала называть неисполнимые ноги."""
        with mock.patch.object(re_mod, "unexecuted_legs", return_value={}):
            verdict, why = self._ask()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("РВАНАЯ", why)
        self.assertIn("БЕСПЛАТНО", why)

    def test_a_scan_that_stops_refusing_alone_is_refused(self):
        """Звено 2 — вердикт отказывает, а перебор размеров уже нет.

        Рвётся ПОИМЁННО (``trim_optimum._unexecuted``): подмена самой двери
        порвала бы оба звена сразу, и этот контроль был бы неотличим от
        предыдущего.
        """
        with mock.patch.object(topt, "_unexecuted", return_value={}):
            verdict, why = self._ask()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("перебор размеров ПОСЧИТАЛ", why)

    def test_a_door_that_refuses_everything_is_refused(self):
        """Звено 3 — отказ съел исполнимый ход (правка наизнанку)."""
        with mock.patch.object(re_mod, "unexecuted_legs",
                               return_value={"aave_v3": 1.0}):
            verdict, why = self._ask()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("ЦЕЛАЯ", why)

    def test_a_missing_axis_is_refused(self):
        """Звено 4 — ось `unexecuted_legs` пропала из evidence."""
        real = re_mod.evaluate

        def _stripped(**kw):
            d = real(**kw)
            if isinstance(d.evidence, dict):
                d.evidence.pop("unexecuted_legs", None)
            return d

        with mock.patch.object(re_mod, "evaluate", _stripped):
            verdict, why = self._ask()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("unexecuted_legs", why)
        self.assertIn("инв. #17", why)

    def test_an_unimportable_door_is_unmeasured_not_a_refusal(self):
        """Нечем мерить ≠ критерий не выполнен (третий исход, инв. #17)."""
        import builtins
        real_import = builtins.__import__

        def _boom(name, *a, **kw):
            if name == "spa_core.paper_trading.trim_optimum":
                raise ImportError("дверь перебора не ввезена")
            return real_import(name, *a, **kw)

        with mock.patch.object(builtins, "__import__", _boom):
            verdict, why = self._ask()
        self.assertEqual(verdict, UNMEASURED, why)
        self.assertIn("не ввезены", why)

    def test_the_probe_does_not_pass_on_a_substring(self):
        """Проба судит ИСХОД настоящих дверей, а не текст: отказ, в котором
        название протокола подменено, остаётся отказом по ИСХОДУ."""
        real = re_mod.evaluate

        def _renamed(**kw):
            d = real(**kw)
            d.reasons = [str(r).replace("aave_v3", "нечто") for r in (d.reasons or [])]
            return d

        with mock.patch.object(re_mod, "evaluate", _renamed):
            verdict, why = self._ask()
        self.assertEqual(verdict, NOT_SATISFIED, why)
        self.assertIn("не НАЗЫВАЕТ протокол", why)

    def test_the_probe_takes_no_argument(self):
        verdict, why = PROBES[PROBE_NAME]("что-нибудь")
        self.assertEqual(verdict, UNMEASURED)
        self.assertIn("не принимает аргумента", why)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
