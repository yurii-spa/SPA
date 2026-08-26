"""Сетевые потолки у подборщика И у аллокатора — решение владельца 25.08 (вариант A).

Карточка «Подборщик раскладки И САМ АЛЛОКАТОР не знают про потолки по сетям —
предлагают то, что гейт заворачивает», ADR-136.

Замер на `origin/main` (положительный контроль, воспроизводится скриптами из ADR):

    подборщик: 93.53 % в одной сети, 22.8 % в одном T2 → ГЕЙТ ОТВЕРГ (2 нарушения)
    аллокатор: 95.00 % в одной сети                    → ГЕЙТ ОТВЕРГ ЦЕЛИКОМ

«Отверг целиком» — это цикл БЕЗ СДЕЛОК, а не «слегка неоптимально».

Ни одного нового порога здесь нет: все значения читаются из ``RiskConfig``, того
же объекта, из которого их берёт гейт. Это и есть содержание варианта A —
зеркало, а не собственные числа.

Условие владельца, которое тест держит отдельно: **сеть не определяется ⇒ отказ,
а не догадка.** Отнести неопознанный вес к безымянной корзине значило бы
недосчитать сетевой потолок, то есть fail-OPEN.
"""
from __future__ import annotations

import unittest

from spa_core.risk import policy_enforcer as pe
from spa_core.risk.policy import RiskConfig
from spa_core.tuner.allocation_tuner import AllocationTuner, TunerConstraints

CAPITAL = 100_000.0

#: Книга из одних Ethereum-протоколов — ровно та форма, на которой гейт
#: заворачивал предложение подборщика.
ETH_BOOK = [
    {"id": "aave_v3",           "apy": 3.1, "tvl_usd": 900e6, "tier": "T1", "chain": "ethereum"},
    {"id": "compound_v3",       "apy": 3.4, "tvl_usd": 400e6, "tier": "T1", "chain": "ethereum"},
    {"id": "morpho_steakhouse", "apy": 4.2, "tvl_usd": 300e6, "tier": "T1", "chain": "ethereum"},
    {"id": "pendle",            "apy": 6.8, "tvl_usd": 200e6, "tier": "T2", "chain": "ethereum"},
    {"id": "euler_v2",          "apy": 5.1, "tvl_usd": 120e6, "tier": "T2", "chain": "ethereum"},
]


def chain_totals(weights, book):
    chain_of = {a["id"]: a.get("chain", "") for a in book}
    out = {}
    for p, w in weights.items():
        out[chain_of.get(p, "")] = out.get(chain_of.get(p, ""), 0.0) + w
    return out


class MirrorNotOwnNumbers(unittest.TestCase):
    """Пороги ЧИТАЮТСЯ у политики. Собственное число = будущее расхождение."""

    def test_chain_caps_equal_policy(self):
        cfg, c = RiskConfig(), TunerConstraints()
        self.assertEqual(c.single_chain_max, cfg.max_single_chain_allocation)
        self.assertEqual(c.l2_total_max, cfg.max_l2_total_allocation)
        self.assertEqual(c.base_chain_max, cfg.BASE_CHAIN_CAP)
        self.assertEqual(c.per_protocol_t1_max, cfg.max_concentration_t1)
        self.assertEqual(c.per_protocol_t2_max, cfg.max_concentration_t2)

    def test_protocol_cap_takes_the_stricter_of_margin_and_policy(self):
        """min(запас, потолок тира) — семантика жива, дефолт теперь = политика.

        ИЗМЕНЕНО НАМЕРЕННО (реш. владельца 26.08, cloud): запасы сняты, дефолт
        зеркалит политику РОВНО (T1 40 / T2 20). Историческая слабина (22.8 %
        в T2 при конверте 25 %) по-прежнему закрыта — проверяется явным
        запасом: формула min() не тронута.
        """
        c = TunerConstraints()
        self.assertAlmostEqual(c.protocol_cap("T1"), 0.40)   # дефолт = политика
        self.assertAlmostEqual(c.protocol_cap("T2"), 0.20)
        self.assertAlmostEqual(c.protocol_cap("T3"), 0.20)   # не-T1 судится как T2
        tighter = TunerConstraints(per_protocol_max=0.25)    # вернуть запас — одно поле
        self.assertAlmostEqual(tighter.protocol_cap("T1"), 0.25)
        self.assertAlmostEqual(tighter.protocol_cap("T2"), 0.20)

    def test_l2_set_matches_the_entry_gate(self):
        from spa_core.tuner.allocation_tuner import L2_CHAINS
        self.assertEqual(set(L2_CHAINS), {"arbitrum", "base"})


class TunerProposalPassesTheGate(unittest.TestCase):
    """Приёмка карточки дословно: предложение проходит гейт БЕЗ нарушений."""

    def _propose(self, book, constraints=None):
        t = AllocationTuner(constraints=constraints)
        res = t.optimize(adapter_data=book, n_candidates=500)
        return t, res

    def _gate(self, weights):
        positions = {p: w * CAPITAL for p, w in weights.items() if w > 0}
        return pe.validate_positions(
            positions, capital_usd=CAPITAL,
            cash_usd=CAPITAL - sum(positions.values()),
        )

    def test_all_ethereum_book_now_passes(self):
        _, res = self._propose(ETH_BOOK)
        verdict = self._gate(res.optimal_weights)
        self.assertTrue(verdict.passed,
                        [f"{v.rule}: {v.message}" for v in (verdict.violations or [])])
        self.assertEqual(list(verdict.violations or []), [])

    def test_single_chain_is_at_or_under_the_policy_cap(self):
        _, res = self._propose(ETH_BOOK)
        top = max(chain_totals(res.optimal_weights, ETH_BOOK).values())
        self.assertLessEqual(top, TunerConstraints().single_chain_max + 1e-9,
                             f"одна сеть {top:.4f}")

    def test_the_trim_is_named_not_silent(self):
        """ADR-055: молчаливый простой капитала запрещён — срез назван.

        ИЗМЕНЕНО НАМЕРЕННО (реш. владельца 26.08): на зеркальных дефолтах
        all-ethereum книга ужимается тир-потолками ниже сетевого 90 % и
        сетевой срез не наступает — исторический сценарий воспроизводится
        явным запасом 25.08 (конверт 25 %, t2_max 35 %), на нём сетевой срез
        обязан быть НАЗВАН. Плюс инвариант дефолтов: ЛЮБОЙ срез именован.
        """
        _, res = self._propose(ETH_BOOK, constraints=TunerConstraints(
            per_protocol_max=0.25, t2_max=0.35))
        self.assertTrue(res.policy_cap_notes, "срез произошёл, но не назван")
        self.assertTrue(any("сеть ethereum" in n for n in res.policy_cap_notes),
                        res.policy_cap_notes)
        _, res_default = self._propose(ETH_BOOK)
        self.assertTrue(res_default.policy_cap_notes,
                        "срезы на дефолтах тоже обязаны быть названы")

    def test_per_protocol_t2_cap_is_respected(self):
        """Второе нарушение того же замера: 22.8 % в T2 при потолке 20 %."""
        _, res = self._propose(ETH_BOOK)
        t2 = {a["id"] for a in ETH_BOOK if a["tier"] != "T1"}
        for pid, w in res.optimal_weights.items():
            if pid in t2:
                with self.subTest(protocol=pid):
                    self.assertLessEqual(w, 0.20 + 1e-9, f"{pid} = {w:.4f}")

    def test_compliant_book_is_not_trimmed(self):
        """Обратный контроль: если резать нечего — не режем и не выдумываем срез."""
        book = [
            dict(ETH_BOOK[0], chain="ethereum"),
            dict(ETH_BOOK[3], chain="arbitrum"),
            dict(ETH_BOOK[4], chain="base"),
        ]
        t = AllocationTuner()
        # Ровно на потолках: T1 25 % (запас подборщика), T2 20 % (политика).
        weights = {"aave_v3": 0.25, "pendle": 0.20, "euler_v2": 0.15}
        out, notes = t._enforce_policy_caps(weights, book)
        self.assertEqual(notes, [])
        self.assertEqual(out, {k: round(v, 6) for k, v in weights.items()})

    def test_l2_total_cap_fires(self):
        book = [
            {"id": "aero", "apy": 6.0, "tvl_usd": 100e6, "tier": "T2", "chain": "base"},
            {"id": "gmx", "apy": 6.0, "tvl_usd": 100e6, "tier": "T2", "chain": "arbitrum"},
            {"id": "silo", "apy": 6.0, "tvl_usd": 100e6, "tier": "T2", "chain": "arbitrum"},
        ]
        t = AllocationTuner()
        out, notes = t._enforce_policy_caps(
            {"aero": 0.15, "gmx": 0.20, "silo": 0.20}, book)
        self.assertLessEqual(sum(out.values()), 0.50 + 1e-6, out)
        self.assertTrue(any("L2 суммарно" in n for n in notes), notes)

    def test_base_chain_cap_fires(self):
        book = [
            {"id": "aero", "apy": 6.0, "tvl_usd": 100e6, "tier": "T2", "chain": "base"},
            {"id": "extra", "apy": 6.0, "tvl_usd": 100e6, "tier": "T2", "chain": "base"},
        ]
        t = AllocationTuner()
        out, notes = t._enforce_policy_caps({"aero": 0.20, "extra": 0.20}, book)
        self.assertLessEqual(sum(out.values()), 0.20 + 1e-6, out)
        self.assertTrue(any("сеть base" in n for n in notes), notes)


class UnknownChainIsRefusedNotGuessed(unittest.TestCase):
    """Условие владельца: «отказ, а не догадка»."""

    def test_protocol_without_chain_is_dropped_and_named(self):
        book = [dict(a) for a in ETH_BOOK]
        book.append({"id": "mystery", "apy": 9.9, "tvl_usd": 500e6, "tier": "T2",
                     "chain": ""})
        t = AllocationTuner()
        res = t.optimize(adapter_data=book, n_candidates=200)
        self.assertNotIn("mystery", res.optimal_weights)
        self.assertIn("mystery", res.refused_no_chain)

    def test_refusal_list_is_empty_when_all_chains_are_known(self):
        """Пустой список = «проверено, таких нет», а не «не проверяли»."""
        t = AllocationTuner()
        res = t.optimize(adapter_data=ETH_BOOK, n_candidates=200)
        self.assertEqual(res.refused_no_chain, [])

    def test_the_highest_apy_protocol_is_refused_too(self):
        """Соблазн: у безымянного самый высокий APY. Всё равно отказ."""
        book = [{"id": "mystery", "apy": 25.0, "tvl_usd": 900e6, "tier": "T2", "chain": ""}]
        book += [dict(a) for a in ETH_BOOK]
        t = AllocationTuner()
        eligible = t._eligible_adapters(book)
        self.assertNotIn("mystery", {a["id"] for a in eligible})


class AllocatorChainCaps(unittest.TestCase):
    """Тот же класс дефекта у ступени, чья раскладка ИДЁТ В ЦИКЛ."""

    def _alloc(self):
        from spa_core.allocator.allocator import StrategyAllocator
        return StrategyAllocator()

    def test_caps_mirror_policy(self):
        a, cfg = self._alloc(), RiskConfig()
        self.assertEqual(a.SINGLE_CHAIN_CAP, cfg.max_single_chain_allocation)
        self.assertEqual(a.L2_TOTAL_CAP, cfg.max_l2_total_allocation)
        self.assertEqual(a.BASE_CHAIN_CAP, cfg.BASE_CHAIN_CAP)

    def test_ethereum_95_is_trimmed_to_90_and_the_rest_stays_cash(self):
        """Дословный замер карточки: 95 % в Ethereum, гейт отвергал целиком."""
        a = self._alloc()
        w = {"morpho_steakhouse": 0.40, "pendle": 0.20, "frax": 0.20,
             "scrvusd": 0.10, "compound_v3": 0.05}
        out, notes = a._enforce_chain_caps(w)
        self.assertAlmostEqual(sum(out.values()), 0.90, places=6)
        self.assertTrue(any("сеть ethereum" in n for n in notes), notes)
        # Освободившийся вес НЕ уехал ни в один протокол — все доли уменьшились.
        for p in w:
            self.assertLessEqual(out[p], w[p] + 1e-9, p)

    def test_enforcement_is_idempotent(self):
        a = self._alloc()
        w = {"morpho_steakhouse": 0.40, "pendle": 0.20, "frax": 0.20,
             "scrvusd": 0.10, "compound_v3": 0.05}
        once, _ = a._enforce_chain_caps(w)
        twice, notes2 = a._enforce_chain_caps(once)
        self.assertEqual(notes2, [])
        for p in once:
            self.assertAlmostEqual(once[p], twice[p], places=9)

    def test_compliant_book_is_untouched(self):
        a = self._alloc()
        w = {"aave_v3": 0.40, "pendle": 0.20}     # 60 % в Ethereum
        out, notes = a._enforce_chain_caps(w)
        self.assertEqual(notes, [])
        self.assertEqual(out, w)

    def test_unresolved_chain_is_named_and_counted_as_one_worst_case_chain(self):
        """У ступени, чья раскладка идёт в цикл, — худший случай, а не обнуление.

        Обнулять реальный протокол из-за пробела в реестре значило бы
        воспроизвести ровно ту аварию, которую ADR-136 чинит (цикл без сделок).
        Неопознанные считаются ОДНОЙ неизвестной сетью — оценка строже правды,
        поэтому потолок недосчитан быть не может. Расхождение с буквой решения
        владельца названо в ADR-136 §3.
        """
        a = self._alloc()
        w = {"unknown_one": 0.50, "unknown_two": 0.50}
        out, notes = a._enforce_chain_caps(w)
        self.assertAlmostEqual(sum(out.values()), a.SINGLE_CHAIN_CAP, places=6)
        self.assertGreater(out["unknown_one"], 0.0, "реальный вес обнулён — это не худший случай")
        self.assertTrue(any("сеть не определена" in n for n in notes), notes)
        self.assertTrue(any("unknown_one" in n and "unknown_two" in n for n in notes),
                        "неопознанные не названы поимённо")

    def test_unresolved_are_one_bucket_not_one_chain_each(self):
        """Положительный контроль к предыдущему: их НЕ считают порознь.

        Если бы каждый неопознанный шёл своей сетью, книга из десяти таких по
        10 % не нарушила бы потолок никогда — это и есть fail-OPEN.
        """
        a = self._alloc()
        w = {f"unknown_{i}": 0.10 for i in range(10)}
        out, _ = a._enforce_chain_caps(w)
        self.assertAlmostEqual(sum(out.values()), a.SINGLE_CHAIN_CAP, places=6)

    def test_unbuildable_chain_map_judges_the_whole_book_as_one_chain(self):
        """Инв. #17: «карту не построили» ≠ «потолки соблюдены»."""
        import spa_core.risk.policy_enforcer as enforcer
        a = self._alloc()
        saved = enforcer._resolve_chain_map
        try:
            def _boom(_protocols):
                raise RuntimeError("реестр недоступен")
            enforcer._resolve_chain_map = _boom
            out, notes = a._enforce_chain_caps({"aave_v3": 0.60, "pendle": 0.35})
        finally:
            enforcer._resolve_chain_map = saved
        self.assertAlmostEqual(sum(out.values()), a.SINGLE_CHAIN_CAP, places=6)
        self.assertTrue(any("сеть не определена" in n for n in notes), notes)

    def test_empty_book_is_not_an_error(self):
        a = self._alloc()
        out, notes = a._enforce_chain_caps({})
        self.assertEqual(out, {})
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
