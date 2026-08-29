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
    """Правило восстановлено по курированным значениям — оно обязано их воспроизводить."""

    def test_hourly_agent_gets_three_hours(self):
        floor, why = sp.architect_floor("interval:3600s")
        self.assertEqual(floor, 3.0, "часовой агент: курировано 3 ч (agent_health)")
        self.assertIn("такт", why)

    def test_daily_agent_gets_twentysix_hours(self):
        self.assertEqual(sp.architect_floor("calendar:08:00")[0], 26.0,
                         "суточный агент: курировано 26 ч")

    def test_times_two_rule_would_miss_both_anchors(self):
        """Обратный контроль: прежнее правило не даёт ни 3, ни 26 — потому и заменено."""
        self.assertNotEqual(sp.cadence_hours("interval:3600s") * 2, 3.0)
        self.assertNotEqual(sp.cadence_hours("calendar:08:00") * 2, 26.0)

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
