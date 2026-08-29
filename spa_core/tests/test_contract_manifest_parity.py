"""Сверка контракта в коде с контрактом в манифесте (ADR-158).

Почему сторож вообще есть: объявив `PRODUCES` в модулях, мы завели ТРЕТИЙ дом для факта
«что производит агент». Класс «одно знание в двух домах» уже стоил нам карточки про сроки
свежести — завести ту же болезнь самим и не поставить сверку было бы нечестно.

Первая же находка поймала автора объявлений: декларация `daily_cycle`, выписанная утром из
манифеста, к вечеру отстала от него на три артефакта (манифест докурировали параллельные
сессии). Дома разошлись за ЧАСЫ.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import contract_manifest_parity as p


class TestFindsDivergence(unittest.TestCase):
    def test_declared_but_manifest_does_not_know(self):
        """Артефакт без записи в манифесте живёт без SLO — его никто не сторожит."""
        r = p.compare({"a": {"data/x.json", "data/y.json"}}, {"a": {"data/x.json"}})
        self.assertEqual(r["verdict"], p.DECLARED_NOT_IN_MANIFEST)
        self.assertEqual(r["findings"][0]["declared_only"], ["data/y.json"])

    def test_manifest_knows_more_than_the_declaration(self):
        """Ровно случай `daily_cycle`: объявление отстало от манифеста."""
        r = p.compare({"a": {"data/x.json"}}, {"a": {"data/x.json", "data/z.json"}})
        self.assertEqual(r["verdict"], p.MANIFEST_NOT_DECLARED)
        self.assertEqual(r["findings"][0]["manifest_only"], ["data/z.json"])

    def test_full_sets_equal_is_silent(self):
        r = p.compare({"a": {"data/x.json"}}, {"a": {"data/x.json"}})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])


class TestEmptyIntersectionIsItsOwnAnswer(unittest.TestCase):
    def test_agent_living_in_one_home_only_is_not_compared(self):
        r = p.compare({"a": {"data/x.json"}}, {"b": {"data/y.json"}})
        self.assertEqual(r["compared"], 0)
        self.assertEqual(r["verdict"], p.NOT_COMPARED)
        self.assertNotEqual(r["verdict"], p.AGREES)


class TestComparesFullPathsNotBasenames(unittest.TestCase):
    """`data/market_regime.json` и `data/investment_os/market_regime.json` — РАЗНЫЕ файлы.

    Обе стороны здесь хранят путь целиком, поэтому базовое имя сличать не нужно и нельзя:
    иначе сверка объявила бы согласие там, где дома говорят о разных файлах.
    """

    def test_same_basename_different_directory_is_a_divergence(self):
        r = p.compare({"a": {"data/market_regime.json"}},
                      {"a": {"data/investment_os/market_regime.json"}})
        self.assertNotEqual(r["verdict"], p.AGREES)


class TestLiveTree(unittest.TestCase):
    def test_live_audit_runs(self):
        r = p.audit()
        self.assertIn(r["verdict"], (p.AGREES, p.NOT_COMPARED,
                                     p.DECLARED_NOT_IN_MANIFEST, p.MANIFEST_NOT_DECLARED))
        self.assertGreater(r["compared"], 0, "объявления и манифест обязаны пересекаться")


if __name__ == "__main__":
    unittest.main()


class AgentWithoutProducesIsStillCompared(unittest.TestCase):
    """Фильтр гасил ровно ту находку, ради которой сверка написана (замер 29.08).

    `manifest_produces` пропускал агента, у которого `produces` пуст, — и пересечение
    домов выбрасывало его целиком. Объявление в коде оставалось не сверенным НИ С ЧЕМ.
    Так молчали четыре агента: apiserver, familyfund, rtmr_sense, telegram_bot. У
    последнего среди необъявленного — `data/kill_switch_active.json`, файл стоп-крана
    с тремя читателями: конституция не знала, кто его производит.
    """

    def test_empty_produces_is_an_answer_not_an_absence(self):
        man = {"agents": [{"label": "com.spa.x", "produces": []}]}
        self.assertEqual(p.manifest_produces(man), {"com.spa.x": set()})

    def test_declaration_against_empty_manifest_is_a_finding(self):
        r = p.compare({"com.spa.x": {"data/a.json"}}, {"com.spa.x": set()})
        self.assertEqual(r["compared"], 1)
        self.assertEqual(r["verdict"], p.DECLARED_NOT_IN_MANIFEST)
        self.assertEqual(r["findings"][0]["declared_only"], ["data/a.json"])

    def test_agent_absent_from_the_manifest_entirely_is_still_not_compared(self):
        """Граница не сдвинута: про кого решения не принимали — тот не сопоставим."""
        r = p.compare({"com.spa.ghost": {"data/a.json"}}, {"com.spa.x": set()})
        self.assertEqual(r["compared"], 0)
        self.assertEqual(r["verdict"], p.NOT_COMPARED)

    def test_agreement_still_reads_as_agreement(self):
        r = p.compare({"com.spa.x": {"data/a.json"}}, {"com.spa.x": {"data/a.json"}})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])

