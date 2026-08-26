"""Тюнер = зеркало RiskPolicy БЕЗ запасов (решение владельца 2026-08-26).

Разворот решения 25.08 «запас оставить» назван вслух (последнее побеждает).
Паритет читается из ЖИВОГО RiskConfig, не из литералов: изменится политика —
зеркало обязано поехать следом, иначе этот тест краснеет (класс «эхо» #197).

    python3 -m unittest spa_core.tests.test_tuner_mirrors_policy -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.risk.policy import RiskConfig
from spa_core.tuner.allocation_tuner import TunerConstraints
from spa_core.tuner.portfolio_rebalancer import _DEFAULT_CONSTRAINTS


class TestTunerMirrorsPolicy(unittest.TestCase):
    def setUp(self):
        self.cfg = RiskConfig()
        self.c = TunerConstraints()

    def test_no_floor_beyond_policy(self):
        # В политике пола T1 нет — и у тюнера его больше нет (запас 0.55 снят).
        self.assertEqual(self.c.t1_min, 0.0)

    def test_t2_total_mirrors_policy(self):
        self.assertEqual(self.c.t2_max, self.cfg.max_total_t2_allocation)

    def test_per_protocol_caps_equal_policy_exactly(self):
        self.assertEqual(self.c.protocol_cap("T1"), self.cfg.max_concentration_t1)
        self.assertEqual(self.c.protocol_cap("T2"), self.cfg.max_concentration_t2)

    def test_cash_and_max_protocols_mirror(self):
        self.assertEqual(self.c.cash_min, self.cfg.min_cash_pct)
        self.assertEqual(self.c.max_protocols, self.cfg.max_protocols)

    def test_rebalancer_uses_the_same_source(self):
        # Один источник правды: у ребалансера нет собственных литералов.
        self.assertEqual(_DEFAULT_CONSTRAINTS, TunerConstraints())

    def test_tightening_still_possible_via_envelope(self):
        # Формула min() жива: вернуть запас можно одним полем, без правки кода.
        tighter = TunerConstraints(per_protocol_max=0.25)
        self.assertEqual(tighter.protocol_cap("T1"), 0.25)
        self.assertEqual(tighter.protocol_cap("T2"), 0.20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
