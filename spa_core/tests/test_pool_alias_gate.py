"""Одно имя — один контракт (карточка agent-dva-imeni-odin-kontrakt-20-deneg-stoyat).

Сцена аварии: книга держит $20 000 под `fluid_usdc`, аллокатор числит `fluid_fusdc`
свободным местом. Это ОДИН пул (pool_id 4438dabc…), и вместе они дали бы 40 % капитала
при потолке T2 20 % — а подсчёт по имени сказал бы «нарушения нет».
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from spa_core.paper_trading import pool_alias_gate as g

ROOT = Path(__file__).resolve().parents[2]
CAP = 100_000.0


class TheBypassIsClosed(unittest.TestCase):
    def test_two_names_of_one_pool_cannot_exceed_the_t2_cap(self):
        """СЦЕНА АВАРИИ: $20k удержано + $20k новых в тот же пул."""
        notes = []
        out = g.apply_pool_alias_gate(
            {"fluid_usdc": 20000.0, "fluid_fusdc": 20000.0, "maple": 10000.0},
            capital_usd=CAP, notes=notes)
        self.assertLessEqual(out["fluid_usdc"] + out["fluid_fusdc"], 20000.0 + 0.01)
        self.assertTrue(notes, "срез не назван — отложенные деньги исчезли молча")

    def test_the_new_money_path_is_trimmed_before_the_frozen_holding(self):
        """Удерживаемую замороженную позицию нельзя продавать принудительно (ADR-053)."""
        out = g.apply_pool_alias_gate({"fluid_usdc": 20000.0, "fluid_fusdc": 20000.0},
                                      capital_usd=CAP, notes=[])
        self.assertEqual(out["fluid_usdc"], 20000.0, "срезали удерживаемую позицию")
        self.assertEqual(out["fluid_fusdc"], 0.0)

    def test_it_only_ever_reduces(self):
        before = {"fluid_usdc": 20000.0, "fluid_fusdc": 20000.0, "maple": 10000.0}
        out = g.apply_pool_alias_gate(before, capital_usd=CAP, notes=[])
        for k, v in out.items():
            self.assertLessEqual(v, before.get(k, 0.0) + 1e-9, k)

    def test_other_protocols_are_untouched(self):
        out = g.apply_pool_alias_gate({"fluid_usdc": 20000.0, "fluid_fusdc": 20000.0,
                                       "maple": 18000.0, "compound_v3": 40000.0},
                                      capital_usd=CAP, notes=[])
        self.assertEqual((out["maple"], out["compound_v3"]), (18000.0, 40000.0))


class WhatIsNotAViolation(unittest.TestCase):
    """Обратная сторона: сторож, срезающий всё, — не сторож."""

    def test_one_name_within_the_cap_is_untouched(self):
        notes = []
        out = g.apply_pool_alias_gate({"fluid_fusdc": 20000.0}, capital_usd=CAP, notes=notes)
        self.assertEqual(out, {"fluid_fusdc": 20000.0})
        self.assertEqual(notes, [])

    def test_both_names_together_within_the_cap_are_untouched(self):
        out = g.apply_pool_alias_gate({"fluid_usdc": 12000.0, "fluid_fusdc": 8000.0},
                                      capital_usd=CAP, notes=[])
        self.assertEqual(out, {"fluid_usdc": 12000.0, "fluid_fusdc": 8000.0})


class Declared(unittest.TestCase):
    def test_every_group_carries_its_proof_and_tier(self):
        for pid, grp in g.POOL_ALIASES.items():
            self.assertGreaterEqual(len(grp["trim_order"]), 2, pid)
            self.assertIn(grp["tier"], ("T1", "T2"))
            self.assertTrue(grp["proof"].strip(), f"{pid}: тождество без доказательства")

    def test_the_cap_comes_from_riskconfig_not_a_literal(self):
        from spa_core.risk.policy import RiskConfig
        self.assertEqual(g._tier_cap("T2"), RiskConfig().max_concentration_t2)

    def test_the_cycle_applies_the_gate_before_the_cio_judges(self):
        """Проводка формой вызова И порядком: CIO обязан судить уже итоговую цель."""
        src = (ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        gate_lines = [n.lineno for n in ast.walk(tree)
                      if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                      and getattr(n.value.func, "id", None) == "apply_pool_alias_gate"
                      and any(isinstance(t, ast.Name) and t.id == "target_usd" for t in n.targets)]
        cio_lines = [n.lineno for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                     and getattr(n.value.func, "id", None) == "write_shadow_rationale"]
        self.assertTrue(gate_lines, "шаг псевдонимов пула не перезаписывает target_usd")
        self.assertTrue(cio_lines)
        self.assertLess(min(gate_lines), min(cio_lines), "CIO судит цель ДО среза")


if __name__ == "__main__":
    unittest.main()
