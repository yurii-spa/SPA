"""Запас поверх такта — ОДИН ПРОПУСК с потолком, а не константа (ADR-815).

Заказ **G814 п. 1** стоячего приказа владельца «Portfolio CIO»: вывести запас для
БЫСТРЫХ производителей. До ADR-815 запас был константой 2 ч, калиброванной по
медленным тактам, и у пятиминутного агента пол 2,08 ч требовал срока в 25 его
тактов. Замер 26.10 на живой конституции: таких ложных тревог **7** на оси
объявленного расписания и **6** на оси наблюдённой медианы.

Каждый тест ниже — положительный контроль на ИЗМЕРЕННУЮ пару, а не на выдуманную:
числа взяты из строк живого прибора (`slo_keepability --json`) и названы в ADR-815.

Литеральных дат и стенных часов в файле НЕТ по построению: предмет — чистая
функция «такт → пол», времени в нём не участвует.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import slo_proposal as sp


class MarginIsOneMissedRunWithACeiling(unittest.TestCase):
    """Запас пропорционален такту, пока такт дешевле потолка."""

    def test_fast_producer_gets_a_margin_of_one_tact_not_two_hours(self):
        # data/resource_health.json: такт 5 мин, срок 0,5 ч — ИЗМЕРЕННАЯ пара,
        # которую ADR-814 назвал по имени как предел константы.
        self.assertAlmostEqual(sp.margin_hours(0.0834), 0.0834, places=4)
        self.assertEqual(sp.floor_from_tact(0.0834), 0.16)

    def test_the_floor_is_rounded_towards_possible_not_towards_nearest(self):
        """Пол, поднятый ОКРУГЛЕНИЕМ, объявляет невозможным возможное.

        Нашёл это соседний тест этого же файла: один пропуск у пятиминутного
        производителя стои́т ровно ``2 × 0,0834 = 0,1668`` ч, а округление к
        ближайшему даёт 0,17 — и срок 0,1668 ч получал «ниже пола» на 18 секундах
        арифметики. Контроль на НАПРАВЛЕНИЕ, а не на само число.
        """
        for tact in (0.0834, 0.251, 0.501, 1.002, 6.001, 7.278, 24.0, 168.0):
            with self.subTest(tact=tact):
                floor = sp.floor_from_tact(tact)
                self.assertLessEqual(floor, tact + sp.margin_hours(tact),
                                     "округление подняло пол выше точного значения")
                self.assertGreaterEqual(floor, tact,
                                        "округление опустило пол НИЖЕ такта — свежее "
                                        "своего такта агент не бывает")

    def test_rounding_never_drops_the_floor_below_the_tact_itself(self):
        """Та же сторона у очень быстрого такта: цена округления больше запаса."""
        self.assertEqual(sp.floor_from_tact(0.004), 0.004)
        floor, _ = sp.observed_floor(0.004)
        axis, note = sp.audit_curated(0.002, floor, 0.004)
        self.assertEqual(axis, sp.CURATED_BELOW, note)

    def test_slow_producer_keeps_the_calibrated_ceiling(self):
        # Суточный агент: один пропуск стоит 24 ч, а кураторы сошлись на 26 ч —
        # потолок запаса и есть этот их выбор, и он НЕ двигается.
        self.assertEqual(sp.margin_hours(24.0), 2.0)
        self.assertEqual(sp.floor_from_tact(24.0), 26.0)

    def test_both_known_anchors_survive(self):
        # Два якоря правила, названные автором `_MARGIN_HOURS`: суточный → 26 ч и
        # часовой `agent_health` → 3 ч. Пол есть НИЖНЯЯ граница, поэтому у часового
        # проверяется не равенство, а то, что курированные 3 ч его НЕ нарушают.
        self.assertEqual(sp.floor_from_tact(24.0), 26.0)
        self.assertLessEqual(sp.floor_from_tact(1.0), 3.0)
        axis, _ = sp.audit_curated(3.0, sp.floor_from_tact(1.0), 1.0)
        self.assertEqual(axis, sp.CURATED_ABOVE)

    def test_the_ceiling_binds_exactly_where_the_tact_is_longer_than_it(self):
        for tact in (0.0834, 0.25, 0.5, 1.0, 1.9):
            with self.subTest(tact=tact, side="ниже потолка"):
                self.assertAlmostEqual(sp.margin_hours(tact), tact, places=4)
        for tact in (2.1, 6.0, 24.0, 168.0):
            with self.subTest(tact=tact, side="выше потолка"):
                self.assertEqual(sp.margin_hours(tact), sp._MARGIN_HOURS)

    def test_the_removed_one_hour_clamp_does_not_come_back(self):
        """Второй нигде не объявленный порог внутри пола — контроль на его отсутствие.

        До ADR-815 пол считался ``round(max(такт + 2, 1.0), 2)``. Зажим был
        НЕДОСТИЖИМ (такт + 2 ≥ 2,0834 всегда) и ни одного ответа не изменил; с
        пропорциональным запасом он стал бы достижимым и держал бы ниже пола
        РОВНО ОДНУ пару — ту самую ``data/resource_health.json``.
        """
        self.assertLess(sp.floor_from_tact(0.0834), 1.0)
        axis, _ = sp.audit_curated(0.5, sp.floor_from_tact(0.0834), 0.0834)
        self.assertEqual(axis, sp.CURATED_ABOVE)


class TheRuleHasOneDoor(unittest.TestCase):
    """Контроль ДВЕРИ, а не «одного определения» (заказ G814 п. 3).

    Мутация №2 батареи ADR-814 выжила именно потому, что запас был заведён вторым
    определением РЯДОМ с дверью: проверка «константа одна на оба пола» этого не
    видит. Поэтому здесь константу ДВИГАЮТ и требуют, чтобы сдвинулись оба пола и
    напечатанный довод.
    """

    def _move_ceiling(self, value: float):
        before = sp._MARGIN_HOURS
        sp._MARGIN_HOURS = value
        self.addCleanup(setattr, sp, "_MARGIN_HOURS", before)

    def test_moving_the_ceiling_moves_both_floors_through_the_door(self):
        base_declared, _ = sp.architect_floor("interval:86400s")
        base_observed, _ = sp.observed_floor(24.0)
        self.assertEqual((base_declared, base_observed), (26.0, 26.0))
        self._move_ceiling(5.0)
        moved_declared, why_d = sp.architect_floor("interval:86400s")
        moved_observed, why_o = sp.observed_floor(24.0)
        self.assertEqual(moved_declared, 29.0, "пол из РАСПИСАНИЯ не прошёл через дверь")
        self.assertEqual(moved_observed, 29.0, "пол из НАБЛЮДЕНИЯ не прошёл через дверь")
        # Довод обязан нести ФАКТИЧЕСКИЙ запас, иначе копия правила переживёт замер.
        self.assertIn("5", why_d)
        self.assertIn("5", why_o)

    def test_moving_the_ceiling_does_not_move_a_tact_below_it(self):
        """Та же дверь, другая сторона: ниже потолка число от него НЕ зависит."""
        base, _ = sp.observed_floor(0.5)
        self._move_ceiling(50.0)
        moved, _ = sp.observed_floor(0.5)
        self.assertEqual(base, moved, "запас быстрого производителя зависит от ПОТОЛКА — "
                                      "значит пропорциональность не доехала до двери")


class NoFalseAlarmAndNoLostFinding(unittest.TestCase):
    """Критерий, по которому форма запаса и выбрана (смысл запаса из шапки модуля)."""

    #: Пары «такт → срок» — ИЗМЕРЕННЫЕ строки живого прибора, не выдуманные.
    KEPT_WITH_SLACK = (
        ("data/resource_health.json", 0.083, 0.5),
        ("data/watchdog_report.json", 0.083, 1.0),
        ("data/intraday_equity.json", 0.083, 1.0),
        ("data/trading_research/status.json", 0.251, 2.0),
        ("data/gas_price_history.json", 0.501, 1.5),
        ("docs/SYSTEM_BRIEFING.md", 0.501, 2.0),
        ("data/orphaned_pytest.json", 1.002, 2.0),
    )
    #: Остаток — утверждение про них ВЕРНО и после правки (запаса на пропуск нет).
    KEPT_WITHOUT_SLACK = (
        ("data/architecture_conformance.json", 6.001, 7.0),
        ("data/investment_os/chief_investment.json", 1.0, 1.0),
    )

    def test_seven_measured_false_alarms_are_gone(self):
        for name, median, declared in self.KEPT_WITH_SLACK:
            with self.subTest(artifact=name):
                floor, _ = sp.observed_floor(median)
                axis, note = sp.audit_curated(declared, floor, median)
                self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_the_two_that_remain_are_still_named(self):
        for name, median, declared in self.KEPT_WITHOUT_SLACK:
            with self.subTest(artifact=name):
                floor, _ = sp.observed_floor(median)
                axis, note = sp.audit_curated(declared, floor, median)
                self.assertEqual(axis, sp.CURATED_MARGIN_ONLY, note)
                self.assertIn("ОДИН ПРОПУСК", note)
                self.assertNotIn("КОНСТАНТНОГО", note)

    def test_a_broken_promise_is_never_lost_at_any_tact(self):
        """ПОТЕРЯННЫХ НАХОДОК ноль ПО ПОСТРОЕНИЮ: пол не ниже такта никогда."""
        for tact in (0.0834, 0.25, 1.0, 6.0, 7.278, 24.0, 168.0):
            with self.subTest(tact=tact):
                self.assertGreaterEqual(sp.floor_from_tact(tact), tact)
                floor, _ = sp.observed_floor(tact)
                axis, note = sp.audit_curated(tact / 2.0, floor, tact)
                self.assertEqual(axis, sp.CURATED_BELOW, note)

    def test_a_promise_with_one_miss_of_slack_is_never_called_impossible(self):
        """ЛОЖНЫХ ТРЕВОГ ноль: срок ≥ 2 × такт не бывает «ниже пола»."""
        for tact in (0.0834, 0.25, 0.5, 1.0, 6.0, 24.0, 168.0):
            with self.subTest(tact=tact):
                floor, _ = sp.observed_floor(tact)
                axis, note = sp.audit_curated(2.0 * tact, floor, tact)
                self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_the_third_outcome_survives_the_change(self):
        floor, why = sp.observed_floor(None)
        self.assertIsNone(floor)
        self.assertIn("ADR-506", why)
        axis, _ = sp.audit_curated(1.0, None)
        self.assertEqual(axis, sp.CURATED_UNMEASURED)


if __name__ == "__main__":
    unittest.main()
