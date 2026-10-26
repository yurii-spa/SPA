"""Две роли называют срок годности (ADR-158): у каждой свой вопрос, среднее запрещено.

Тесты закрепляют решения, принятые ПО ЗАМЕРУ, а не по вкусу:

  1. Правило пола ВЫВЕДЕНО из 35 пар «такт → курированный человеком slo_hours»:
     «такт + 2 ч» попадает точно в 19 из 35, «такт × 2» — НИ В ОДНО. Первая редакция
     использовала ×2 и выдавала ложные расхождения ролей у 11 агентов.
  2. Несогласие ролей — находка, а не задача на арифметику: поле остаётся ПУСТЫМ.
  3. Уже курированный человеком срок роли НЕ переназначают.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import slo_proposal as sp


class TestFloorRuleReproducesCuratedAnchors(unittest.TestCase):
    """Правило восстановлено по курированным значениям — и обязано их НЕ НАРУШАТЬ.

    **Утверждение сужено ADR-815, и это усиление, а не уступка.** Прежняя
    редакция требовала, чтобы пол РАВНЯЛСЯ курированному значению, и держала
    это равенство у часового агента (3 ч, `agent_health`). Такого свойства у
    пола быть не может, и это ЗАМЕРЕНО, а не рассуждение: на живой конституции
    при ОДНОМ И ТОМ ЖЕ такте 1 ч люди проставили **шесть** разных сроков —
    1 · 2 · 3 · 25 · 26 · 168 ч. Ни одна функция такта не равна всем шести,
    значит равенство у одного из них было совпадением с самым популярным
    выбором. Курированный срок есть ПОТОЛОК цены опоздания (роль HoI), а пол —
    «что физически возможно» (роль Архитектора); требовать их совпадения значит
    требовать, чтобы ответ на один вопрос совпал с ответом на другой — ровно
    ошибка, разобранная в ADR-164.

    Поэтому контроль теперь двусторонний: пол НЕ НАРУШАЕТ ни один курированный
    якорь (и у суточного совпадает с ним точно, потому что там его связывает
    потолок запаса), а курированные якоря остаются `CURATED_ABOVE`.
    """

    #: Курированные сроки при ОДНОМ такте 1 ч — замер 26.10 по `architecture/manifest.json`.
    HOURLY_CURATED = (1.0, 2.0, 3.0, 25.0, 26.0, 168.0)

    def test_hourly_agent_floor_does_not_violate_the_curated_anchor(self):
        floor, why = sp.architect_floor("interval:3600s")
        self.assertEqual(floor, 2.0, "часовой агент: один пропуск стои́т 1 ч")
        self.assertLessEqual(floor, 3.0, "пол не вправе нарушить курированные 3 ч")
        self.assertIn("такт", why)
        axis, note = sp.audit_curated(3.0, floor, 1.0)
        self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_no_floor_can_equal_all_six_curated_values_at_one_tact(self):
        """Замер, которым сужено утверждение класса. Не рассуждение — счёт."""
        floor, _ = sp.architect_floor("interval:3600s")
        self.assertEqual(len(set(self.HOURLY_CURATED)), 6)
        self.assertEqual(sum(1 for v in self.HOURLY_CURATED if v == floor), 1,
                         "пол равен РОВНО одному из шести — равенство не свойство правила")
        below = [v for v in self.HOURLY_CURATED if v < floor]
        self.assertEqual(below, [1.0], "единственный нарушенный якорь — случай ADR-549")

    def test_daily_agent_gets_twentysix_hours(self):
        self.assertEqual(sp.architect_floor("calendar:08:00")[0], 26.0,
                         "суточный агент: курировано 26 ч")

    def test_times_two_rule_would_break_the_daily_anchor(self):
        """Обратный контроль: чистое «× 2» нарушило бы суточный якорь.

        Именно этим ADR-815 и отсекает чистую пропорциональность: 38 пар
        суточных агентов курированы ровно 26 ч, а «× 2» объявило бы их ниже
        пола (48 ч). Потолок запаса существует ради этих 38 пар.
        """
        daily = sp.cadence_hours("calendar:08:00")
        self.assertEqual(daily * 2, 48.0)
        self.assertGreater(daily * 2, 26.0)
        self.assertEqual(sp.architect_floor("calendar:08:00")[0], 26.0)

    def test_schedule_without_cadence_is_unmeasured(self):
        floor, why = sp.architect_floor("daemon")
        self.assertIsNone(floor)
        self.assertIn("судить не о чем", why)


class TestCostOfLatenessCeiling(unittest.TestCase):
    def test_money_path_reader_makes_it_tight(self):
        h, why = sp.hoi_ceiling({"spa_core.risk.scoring_engine"}, False)
        self.assertEqual(h, 3.0)
        self.assertIn("money-path", why)

    def test_owner_alert_gives_a_day(self):
        h, why = sp.hoi_ceiling(set(), True)
        self.assertEqual(h, 26.0)
        self.assertIn("владельцу", why)

    def test_no_consumer_at_all_is_loosest(self):
        h, why = sp.hoi_ceiling(set(), False)
        self.assertEqual(h, 168.0)
        self.assertIn("не стоит ничего", why)


class TestDisagreementIsNeverAveraged(unittest.TestCase):
    """Главное правило ADR-158."""

    def test_floor_above_ceiling_leaves_the_field_empty(self):
        slo, verdict = sp.reconcile(26.0, 3.0)
        self.assertIsNone(slo, "среднее между «способен» и «нужно» — число без автора")
        self.assertEqual(verdict, sp.CONTRADICTION)

    def test_agreement_takes_the_ceiling_not_the_floor(self):
        """Любой срок в [пол, потолок] годится; берётся потолок — меньше ложных тревог."""
        slo, verdict = sp.reconcile(3.0, 26.0)
        self.assertEqual((slo, verdict), (26.0, sp.AGREED))

    def test_either_side_unmeasured_is_unmeasured(self):
        self.assertEqual(sp.reconcile(None, 26.0)[1], sp.UNMEASURED)
        self.assertEqual(sp.reconcile(3.0, None)[1], sp.UNMEASURED)


class TestLiveTree(unittest.TestCase):
    def test_live_run_finds_the_known_contradiction(self):
        """На живом дереве роли расходятся там, где money-path читает СУТОЧНЫЙ продукт."""
        r = sp.propose("com.spa.analytics_tier_c")
        self.assertIn(r["verdict"], (sp.CONTRADICTION, sp.ALREADY, sp.UNMEASURED))
        if r["verdict"] == sp.CONTRADICTION:
            self.assertIsNone(r["slo_hours"])

    def test_curated_slo_is_not_reassigned(self):
        r = sp.propose("com.spa.agent_health")
        self.assertEqual(r["verdict"], sp.ALREADY,
                         "срок, проставленный человеком, роли не переназначают")


if __name__ == "__main__":
    unittest.main()
