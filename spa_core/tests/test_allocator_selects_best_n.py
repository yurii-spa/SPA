"""Осознанный отбор лучших N в аллокаторе — решение владельца 25.08 (вариант A).

Карточка «Вести опрос от полного реестра адаптеров? Замер: 27 проходных при
пределе 8 — книга каждый цикл уходит в аварийную», ADR-138.

**Что было.** Аллокатор раздавал деньги по ВСЕМ проходным протоколам, а готовую
раскладку уже потом ловило правило «не больше 8 позиций» (ALLOC-002) — и вместо
того, чтобы отсечь худших, система выбрасывала раскладку целиком и брала
аварийную книгу, которая идёт мимо проверок свежести. Порог ``max_protocols``
доходил ТОЛЬКО до модели ``optimized_yield``; модель по умолчанию
(``risk_adjusted``) и ``equal_weight`` о нём не знали вовсе.

Замер до правки (реальные имена протоколов, чтобы гейт судил своей картой тиров
и сетей):

    risk_adjusted  кандидатов=12 → funded=12 → ГЕЙТ ОТВЕРГ (max_protocols)
    risk_adjusted  кандидатов=27 → funded=27 → ГЕЙТ ОТВЕРГ (max_protocols)

Замер после:

    risk_adjusted  кандидатов=12 → funded=8
    risk_adjusted  кандидатов=27 → funded=8 → **ГЕЙТ PASSED, нарушений 0**

То есть книга, которая каждый цикл уходила в аварийный фолбэк, теперь проходит.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.allocator.allocator import StrategyAllocator
from spa_core.risk import policy_enforcer as pe

# Настоящие имена: у гейта СВОЯ карта тиров и сетей, синтетические имена он
# судит как T2 / неизвестная сеть — и замер мерил бы не тот порог.
REAL_PROTOCOLS = [
    "aave_v3", "compound_v3", "morpho_steakhouse", "spark_susds", "sdai",
    "sfrax", "frax", "scrvusd", "stusd", "wusdm", "yearn_v3", "euler_v2",
    "pendle", "susde", "maple", "morpho_blue", "usual_usd0pp", "fluid_usdc",
    "aave_arbitrum", "silo_arbitrum", "dolomite_arbitrum", "aave_v3_base",
    "moonwell_base", "extra_finance_base", "aerodrome_base",
    "velodrome_optimism", "aave_v3_optimism",
]
_T1 = {"aave_v3", "compound_v3", "morpho_steakhouse", "spark_susds", "sdai"}


def _allocator(n: int, model: str = "risk_adjusted"):
    tmp = Path(tempfile.mkdtemp(prefix="bestn_"))
    adapters = [
        {"protocol": name, "apy_pct": 3.0 + i * 0.25, "tvl_usd": 5e8,
         "tier": "T1" if name in _T1 else "T2"}
        for i, name in enumerate(REAL_PROTOCOLS[:n])
    ]
    (tmp / "status.json").write_text(json.dumps({"adapters": adapters}))
    return StrategyAllocator(
        status_path=tmp / "status.json",
        registry_path=tmp / "__no_registry__.json",
        live_apy_provider=False,
        allocation_model=model,
    )


def _funded(res) -> dict:
    return {p: w for p, w in res.target_weights.items() if w > 1e-9}


class CountLimitIsRespectedByEveryModel(unittest.TestCase):
    """Порог доходил только до одной модели из трёх — теперь до всех."""

    def test_default_model_never_funds_more_than_the_limit(self):
        for n in (8, 12, 27):
            with self.subTest(candidates=n):
                a = _allocator(n)
                res = a.allocate()
                self.assertLessEqual(len(_funded(res)), a.MAX_PROTOCOLS,
                                     f"{n} кандидатов → {len(_funded(res))} позиций")

    def test_equal_weight_too(self):
        for n in (12, 27):
            with self.subTest(candidates=n):
                a = _allocator(n, model="equal_weight")
                res = a.allocate()
                self.assertLessEqual(len(_funded(res)), a.MAX_PROTOCOLS)

    def test_book_of_27_now_passes_the_gate(self):
        """Ради чего всё: раньше здесь включалась аварийная книга."""
        a = _allocator(27)
        res = a.allocate()
        funded = _funded(res)
        cap = res.capital_usd or 100_000.0
        positions = {p: w * cap for p, w in funded.items()}
        verdict = pe.validate_positions(
            positions, capital_usd=cap, cash_usd=cap - sum(positions.values()))
        self.assertTrue(verdict.passed,
                        [f"{v.rule}: {v.message}" for v in (verdict.violations or [])])

    def test_max_protocols_violation_is_gone_at_every_size(self):
        """Узкое утверждение: именно ЭТО нарушение больше не возникает.

        Отдельно от предыдущего теста намеренно: прочие нарушения зависят от
        раскладки APY в фикстуре, а это — от предмета карточки.
        """
        for n in (8, 12, 27):
            with self.subTest(candidates=n):
                a = _allocator(n)
                res = a.allocate()
                funded = _funded(res)
                cap = res.capital_usd or 100_000.0
                positions = {p: w * cap for p, w in funded.items()}
                verdict = pe.validate_positions(
                    positions, capital_usd=cap,
                    cash_usd=cap - sum(positions.values()))
                rules = {v.rule for v in (verdict.violations or [])}
                self.assertNotIn("max_protocols", rules)


class SelectionIsConsciousNotAccidental(unittest.TestCase):
    """Отсекаются ХУДШИЕ, а не первые попавшиеся."""

    def setUp(self):
        self.a = _allocator(8)

    def test_keeps_the_heaviest_and_drops_the_lightest(self):
        weights = {f"p{i}": 0.10 - i * 0.001 for i in range(12)}
        kept, dropped, notes = self.a._select_best_n(weights)
        self.assertEqual(len(kept), self.a.MAX_PROTOCOLS)
        self.assertEqual(dropped, {"p8", "p9", "p10", "p11"})
        self.assertTrue(notes)

    def test_equal_weights_are_broken_by_apy(self):
        """У equal_weight веса равны — «лучшие 8» решает доходность."""
        weights = {f"p{i}": 0.08 for i in range(10)}
        apy = {f"p{i}": float(i) for i in range(10)}   # p0 худший, p9 лучший
        kept, dropped, _ = self.a._select_best_n(weights, apy_map=apy)
        self.assertEqual(dropped, {"p0", "p1"})
        self.assertIn("p9", kept)

    def test_tie_break_is_deterministic_by_name(self):
        weights = {f"p{i}": 0.08 for i in range(10)}
        first = self.a._select_best_n(weights)[1]
        second = self.a._select_best_n(weights)[1]
        self.assertEqual(first, second)

    def test_no_cut_when_within_the_limit(self):
        """Обратный контроль: резать нечего ⇒ не режем и не выдумываем срез."""
        weights = {f"p{i}": 0.10 for i in range(5)}
        kept, dropped, notes = self.a._select_best_n(weights)
        self.assertEqual(kept, weights)
        self.assertEqual(dropped, set())
        self.assertEqual(notes, [])

    def test_zero_weight_rows_do_not_count_toward_the_limit(self):
        """Нулевой вес — не позиция; иначе отсечение сработало бы на пустом месте."""
        weights = {f"p{i}": 0.10 for i in range(6)}
        weights.update({f"z{i}": 0.0 for i in range(10)})
        kept, dropped, notes = self.a._select_best_n(weights)
        self.assertEqual(dropped, set())
        self.assertEqual(notes, [])

    def test_dropped_are_removed_not_zeroed(self):
        """Обнуление НЕ работало — и это измерено.

        Обнулённый протокол остаётся в словаре, и следующие шаги честно считают
        его «есть ёмкость, вес ноль»: ``_apply_caps`` разливает на него излишек,
        ``_fill_remainder`` — остаток. Замер с обнулением: 12 кандидатов → 11
        профинансировано при пределе 8, то есть отсечение не срабатывало вовсе.
        """
        weights = {f"p{i}": 0.10 - i * 0.001 for i in range(12)}
        kept, dropped, _ = self.a._select_best_n(weights)
        for p in dropped:
            self.assertNotIn(p, kept, f"{p} обнулён, а не удалён — вернётся водоналивом")

    def test_selection_is_idempotent(self):
        weights = {f"p{i}": 0.10 - i * 0.001 for i in range(12)}
        once, dropped_once, _ = self.a._select_best_n(weights)
        twice, dropped_twice, notes2 = self.a._select_best_n(once)
        self.assertEqual(once, twice)
        self.assertEqual(dropped_twice, set())
        self.assertEqual(notes2, [])


class TheCutIsVisible(unittest.TestCase):
    """Инв. #17 и ADR-055: отсечённый капитал обязан быть НАЗВАН."""

    def test_note_names_the_dropped_protocols_and_the_freed_weight(self):
        a = _allocator(8)
        weights = {f"p{i}": 0.10 - i * 0.001 for i in range(12)}
        _, dropped, notes = a._select_best_n(weights)
        self.assertEqual(len(notes), 1)
        for p in dropped:
            self.assertIn(p, notes[0])
        self.assertIn("ALLOC-002", notes[0])

    def test_allocation_notes_carry_the_cut(self):
        a = _allocator(27)
        res = a.allocate()
        self.assertTrue(any("ALLOC-002 (ADR-138)" in n for n in res.notes), res.notes)

    def test_dropped_stay_visible_as_zero_rows(self):
        """Молча исчезнувший протокол неотличим от «его не рассматривали»."""
        a = _allocator(27)
        res = a.allocate()
        funded = set(_funded(res))
        considered = set(res.target_weights)
        self.assertGreater(len(considered - funded), 0,
                           "отсечённые пропали из вывода целиком")


if __name__ == "__main__":
    unittest.main()
