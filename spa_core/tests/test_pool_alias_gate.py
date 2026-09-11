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


class Morpho(unittest.TestCase):
    """Вторая пара того же класса (монитор pool_identity_collision, 11.09)."""

    def test_two_morpho_keys_cannot_hold_forty_percent_of_one_vault(self):
        out = g.apply_pool_alias_gate({"morpho_blue": 20000.0, "morpho_steakhouse": 20000.0},
                                      capital_usd=CAP, notes=[])
        self.assertLessEqual(out["morpho_blue"] + out["morpho_steakhouse"], 20000.0 + 0.01)

    def test_the_key_the_owner_kept_is_trimmed_last(self):
        """Решение владельца 18.08 (вариант B): morpho_blue оставить."""
        out = g.apply_pool_alias_gate({"morpho_blue": 20000.0, "morpho_steakhouse": 20000.0},
                                      capital_usd=CAP, notes=[])
        self.assertEqual(out["morpho_blue"], 20000.0)
        self.assertEqual(out["morpho_steakhouse"], 0.0)


class WhatIsNotAViolation(unittest.TestCase):

    def test_a_t3_pair_is_not_declared_because_the_tier_cap_already_holds_it(self):
        """ethena_susde + susde — один пул, но T3 держит потолок ТИРА: дыры нет."""
        members = {m for grp in g.POOL_ALIASES.values() for m in grp["trim_order"]}
        self.assertFalse({"ethena_susde", "susde"} & members)

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
    def test_every_group_carries_its_proof_and_no_tier_of_its_own(self):
        # Инв. #16 — изменение намеренное (ADR-340): прежде здесь стояло
        # `assertIn(grp["tier"], ("T1", "T2"))`, то есть тест ТРЕБОВАЛ у группы свою
        # копию тира. Эта копия и разошлась с RiskPolicy: реестр назвал ключ T1, политика
        # разрешила 30 %, шаг срезал до 20 % (замер: test_yield_calculation, недобор
        # $6.41 вместо $8.19). Проверка не сужена, а заменена более сильной: тира у группы
        # быть НЕ должно, тир ключа берётся у политики (см. PolicyTier ниже).
        for pid, grp in g.POOL_ALIASES.items():
            self.assertGreaterEqual(len(grp["trim_order"]), 2, pid)
            self.assertNotIn("tier", grp, f"{pid}: вторая копия тира рядом с группой")
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


class PolicyTier(unittest.TestCase):
    """ADR-340: шаг судит ключ под ТЕМ ЖЕ тиром, что и RiskPolicy, — не своим литералом."""

    def _registry(self, entries):
        import json, tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        Path(d.name, "adapter_registry.json").write_text(
            json.dumps({"adapters": entries}), encoding="utf-8")
        return d.name

    def test_a_key_the_registry_names_t1_is_held_to_the_t1_cap(self):
        """Сцена test_yield_calculation: реестр — T1, мета молчит ⇒ политика даёт 40 %."""
        ddir = self._registry({"morpho_steakhouse": {"tier": 1}})
        notes = []
        out = g.apply_pool_alias_gate({"morpho_steakhouse": 30000.0}, capital_usd=CAP,
                                      notes=notes, adapters=[], ddir=ddir)
        self.assertEqual(out["morpho_steakhouse"], 30000.0)
        self.assertEqual(notes, [])

    def test_the_orchestrator_tier_outranks_the_registry(self):
        """Прод: оркестратор объявляет T2 (решение владельца 10.08) — реестр его не смягчает."""
        ddir = self._registry({"morpho_steakhouse": {"tier": 1}})
        out = g.apply_pool_alias_gate(
            {"morpho_steakhouse": 30000.0}, capital_usd=CAP, notes=[],
            adapters=[{"protocol": "morpho_steakhouse", "tier": "T2"}], ddir=ddir)
        self.assertAlmostEqual(out["morpho_steakhouse"], 20000.0, places=2)

    def test_the_strictest_key_holding_money_sets_the_group_cap(self):
        ddir = self._registry({"morpho_steakhouse": {"tier": 1}, "morpho_blue": {"tier": 2}})
        out = g.apply_pool_alias_gate({"morpho_steakhouse": 15000.0, "morpho_blue": 15000.0},
                                      capital_usd=CAP, notes=[], adapters=[], ddir=ddir)
        self.assertAlmostEqual(sum(out.values()), 20000.0, places=2)

    def test_a_key_without_money_does_not_set_the_tier(self):
        ddir = self._registry({"morpho_steakhouse": {"tier": 1}, "morpho_blue": {"tier": 2}})
        out = g.apply_pool_alias_gate({"morpho_steakhouse": 30000.0, "morpho_blue": 0.0},
                                      capital_usd=CAP, notes=[], adapters=[], ddir=ddir)
        self.assertEqual(out["morpho_steakhouse"], 30000.0)

    def test_an_unreadable_registry_falls_to_t2_the_stricter_side(self):
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        Path(d.name, "adapter_registry.json").write_text("{не json", encoding="utf-8")
        out = g.apply_pool_alias_gate({"morpho_steakhouse": 30000.0}, capital_usd=CAP,
                                      notes=[], adapters=[], ddir=d.name)
        self.assertAlmostEqual(out["morpho_steakhouse"], 20000.0, places=2)

    def test_a_registry_read_that_raises_falls_to_t2_too(self):
        """Ветка `except` — не та же, что «нечитаемый JSON»: `_read_json` глотает разбор
        сам, а сюда приходит, когда падает само чтение (права, диск). Замер батареи
        ADR-340: без этой сцены мутация «ошибка ⇒ T1» выживала."""
        from unittest import mock
        from spa_core.paper_trading import risk_gate
        with mock.patch.object(risk_gate, "registry_adapters",
                               side_effect=PermissionError("нет доступа")):
            out = g.apply_pool_alias_gate({"morpho_steakhouse": 30000.0}, capital_usd=CAP,
                                          notes=[], adapters=[], ddir="/nonexistent")
        self.assertAlmostEqual(out["morpho_steakhouse"], 20000.0, places=2)

    def test_the_gate_and_the_policy_share_one_tier_rule(self):
        """Одно правило — один объект: шаг зовёт функцию гейта, а не её копию."""
        from spa_core.paper_trading import risk_gate
        src = (ROOT / "spa_core" / "paper_trading" / "pool_alias_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("policy_tier", called)
        self.assertIn("registry_adapters", called)
        gsrc = (ROOT / "spa_core" / "paper_trading" / "risk_gate.py").read_text(encoding="utf-8")
        gtree = ast.parse(gsrc)
        gate = next(n for n in gtree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_apply_risk_policy_gate")
        gcalled = {n.func.id for n in ast.walk(gate)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("policy_tier", gcalled, "гейт RiskPolicy судит тир не той функцией")
        self.assertIn("registry_adapters", gcalled)
        self.assertTrue(callable(risk_gate.policy_tier))

    def test_the_cycle_hands_the_gate_the_policy_inputs(self):
        """Проводка формой вызова: без adapters/ddir шаг снова судил бы по умолчанию."""
        src = (ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "apply_pool_alias_gate"]
        self.assertTrue(calls)
        for c in calls:
            kw = {k.arg: k.value for k in c.keywords}
            self.assertIsInstance(kw.get("adapters"), ast.Name)
            self.assertEqual(kw["adapters"].id, "adapters")
            self.assertIsInstance(kw.get("ddir"), ast.Name)
            self.assertEqual(kw["ddir"].id, "ddir")


class TheBookHasOneKeyPerPool(unittest.TestCase):
    """ADR-331: «книгу привести в соответствие» — второе имя пула убирается из книги."""

    def test_the_second_name_is_read_under_the_canonical_key(self):
        notes = []
        out = g.canonicalize_positions({"fluid_usdc": 20000.0, "maple": 5263.16}, notes)
        self.assertEqual(out, {"fluid_fusdc": 20000.0, "maple": 5263.16})
        self.assertTrue(any("fluid_usdc" in n and "fluid_fusdc" in n for n in notes))

    def test_the_amount_is_preserved_when_both_names_are_held(self):
        out = g.canonicalize_positions({"fluid_usdc": 12000.0, "fluid_fusdc": 3000.0}, [])
        self.assertEqual(out, {"fluid_fusdc": 15000.0})

    def test_morpho_is_not_merged_the_owner_kept_it_apart(self):
        """Решение владельца 18.08 (вариант B): morpho_blue — отдельный предмет."""
        out = g.canonicalize_positions({"morpho_blue": 9000.0, "morpho_steakhouse": 1000.0}, [])
        self.assertEqual(out, {"morpho_blue": 9000.0, "morpho_steakhouse": 1000.0})

    def test_an_untouched_book_says_nothing(self):
        notes = []
        g.canonicalize_positions({"maple": 1.0}, notes)
        self.assertEqual(notes, [])

    def test_the_cycle_canonicalizes_at_every_read_of_the_book(self):
        """Оба чтения книги (основное и после ALLOC-001) — формой вызова в AST."""
        src = (ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        n = sum(1 for x in ast.walk(tree)
                if isinstance(x, ast.Assign) and isinstance(x.value, ast.Call)
                and getattr(x.value.func, "id", None) == "canonicalize_positions"
                and any(isinstance(t, ast.Name) and t.id == "current_positions"
                        for t in x.targets))
        self.assertGreaterEqual(n, 2, "одно из чтений книги не канонизируется")

    def test_no_canonical_target_is_itself_an_alias(self):
        """Цепочка псевдонимов разрешалась бы в зависимости от порядка — запрещено."""
        for alias, canon in g.CANONICAL_KEYS.items():
            self.assertNotIn(canon, g.CANONICAL_KEYS, f"{canon} сам объявлен псевдонимом")


if __name__ == "__main__":
    unittest.main()
