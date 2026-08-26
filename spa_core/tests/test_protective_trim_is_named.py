#!/usr/bin/env python3
"""Защитный трим АЛЛОКАТОРА называется — и называется ПО ФЛАГУ, а не по сумме.

Карточка `inbox-adr-072-ne-srabotal-trim-proishodit-v-al` (08.08). ADR-072
считал освобождённый бюджет как ``asked − deployed`` ВОКРУГ ГЕЙТА. Защитные
тримы (потолки тира, суммарный T2/T3, capacity) срабатывают РАНЬШЕ — внутри
``StrategyAllocator.allocate`` — поэтому гейт получал уже урезанную книгу,
разность выходила нулевой, и 20 п.п. капитала сверх буфера лежали кэшем без
единой строки, называющей причину (ADR-055 запрещает молчаливый простой).

Positive control — ровно эта авария: книга из четырёх T2 по 20 % упирается в
потолки, $20 000 остаются кэшем. Проверка обязана НАЗВАТЬ эти доллары.

Обе стороны каждой границы:
  * флаг стадии — судья: сумма упала, а флаг молчит ⇒ ``not_measured``, деньги
    в ``unnamed_usd`` (не «причин нет»);
  * стадия сработала, но перераспределила ВНУТРИ книги ⇒ кэшем ноль;
  * честный cap-bound остаток оптимизатора (флаг не взводился, суммы равны) в
    защитный трим НЕ попадает;
  * нефинитная сумма ⇒ ``measured=False``;
  * money-path: по умолчанию сумма ТОЛЬКО НАЗЫВАЕТСЯ и капитал НЕ двигает;
    включённая перераздача не смеет пробить min-cash буфер.

Сети нет, часов нет, литеральных дат нет. stdlib + unittest::

    python3 -m unittest spa_core.tests.test_protective_trim_is_named -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator.allocator import (  # noqa: E402
    PROTECTIVE_TRIM_SCHEMA,
    StrategyAllocator,
    measure_protective_trim,
)
from spa_core.paper_trading.cycle_gates import build_gate_ledger  # noqa: E402
from spa_core.paper_trading.risk_gate import redistribute_freed_budget  # noqa: E402

CAP = 100_000.0


def stage(name, flag, fired, before, after, rule_ref="ref"):
    return {"stage": name, "rule_ref": rule_ref, "flag": flag, "fired": fired,
            "before": before, "after": after}


class FlagIsTheJudge(unittest.TestCase):
    """Факт тримa устанавливается ФЛАГОМ; сумма даёт только величину."""

    def test_positive_control_incident_20pp_left_as_cash_is_named(self):
        # Потолки тира срезали книгу с 1.00 до 0.80 и объявили это флагом.
        r = measure_protective_trim(
            [stage("tier_caps", "was_capped", True, 1.00, 0.80)], CAP)
        self.assertEqual(r["schema"], PROTECTIVE_TRIM_SCHEMA)
        self.assertAlmostEqual(r["total_usd"], 20_000.0, delta=1.0)
        self.assertEqual(r["unnamed_usd"], 0.0)
        self.assertTrue(r["measured"])
        self.assertEqual(r["stages"][0]["status"], "named")

    def test_sum_dropped_but_flag_silent_is_not_measured(self):
        # ОБРАТНАЯ СТОРОНА: те же 20 п.п., но стадия причину не объявила.
        # «Не измерено» обязано отличаться от «причин нет».
        r = measure_protective_trim(
            [stage("tier_caps", "was_capped", False, 1.00, 0.80)], CAP)
        self.assertEqual(r["total_usd"], 0.0)
        self.assertAlmostEqual(r["unnamed_usd"], 20_000.0, delta=1.0)
        self.assertFalse(r["measured"])
        self.assertEqual(r["stages"][0]["status"], "not_measured")

    def test_stage_fired_but_redistributed_inside_book_leaves_no_cash(self):
        r = measure_protective_trim(
            [stage("t2_total_cap", "t2_total_cap_enforced", True, 0.95, 0.95)], CAP)
        self.assertEqual(r["total_usd"], 0.0)
        self.assertTrue(r["measured"])
        self.assertTrue(r["flags"]["t2_total_cap_enforced"])

    def test_honest_cap_bound_optimizer_remainder_is_not_a_protective_trim(self):
        # Оптимизатор сам не добрал до буфера: ни одна защита не срабатывала,
        # суммы вокруг стадий не менялись. Это НЕ срезанное защитами.
        r = measure_protective_trim([
            stage("tier_caps", "was_capped", False, 0.75, 0.75),
            stage("headroom_fill", "remainder_filled", False, 0.75, 0.75),
        ], CAP)
        self.assertEqual(r["total_usd"], 0.0)
        self.assertEqual(r["unnamed_usd"], 0.0)
        self.assertTrue(r["measured"])

    def test_headroom_fill_that_returns_weight_is_reported_separately(self):
        r = measure_protective_trim(
            [stage("headroom_fill", "remainder_filled", True, 0.80, 0.95)], CAP)
        self.assertEqual(r["total_usd"], 0.0)
        self.assertAlmostEqual(r["returned_to_book_usd"], 15_000.0, delta=1.0)

    def test_non_finite_sum_is_not_measured(self):
        r = measure_protective_trim(
            [stage("tier_caps", "was_capped", True, float("nan"), 0.80)], CAP)
        self.assertFalse(r["measured"])
        self.assertIsNone(r["stages"][0]["usd_left_as_cash"])

    def test_garbage_input_never_raises(self):
        r = measure_protective_trim(["nonsense", None], CAP)  # type: ignore[list-item]
        self.assertFalse(r["measured"])
        self.assertEqual(r["total_usd"], 0.0)


class AllocatorNamesItEndToEnd(unittest.TestCase):
    """Реальный аллокатор на офлайн-снимке: четыре T2 по 20 % ⇒ 20 % кэшем."""

    def _allocate(self):
        adapters = [
            {"protocol": p, "apy_pct": apy, "tvl_usd": 5e7, "tier": "T2",
             "status": "ok"}
            for p, apy in (("morpho_blue", 8.3), ("yearn_v3", 7.2),
                           ("euler_v2", 9.1), ("maple", 10.5))
        ]
        tmp = Path(tempfile.mkdtemp())
        (tmp / "adapter_status.json").write_text(
            json.dumps({"adapters": adapters}), encoding="utf-8")
        alloc = StrategyAllocator(
            status_path=tmp / "adapter_status.json",
            risk_scores_path=tmp / "missing_risk_scores.json",
            # Пустой реестр — иначе MP-REGISTRY подмешал бы прод-вселенную и
            # авария (только T2, потолки упираются) не воспроизвелась бы.
            registry_path=tmp / "missing_registry.json",
            allocation_model="equal_weight",
            live_apy_provider=False,
        )
        return alloc.allocate()

    def test_tier_caps_leave_20k_as_cash_and_the_allocator_names_it(self):
        res = self._allocate()
        self.assertGreater(res.cash_pct, 0.15)          # авария воспроизведена
        pt = res.protective_trim
        self.assertEqual(pt["schema"], PROTECTIVE_TRIM_SCHEMA)
        self.assertTrue(pt["flags"]["was_capped"])      # флаг, а не разность
        self.assertGreater(pt["total_usd"], 15_000.0)
        self.assertTrue(pt["measured"])
        self.assertTrue(
            any("protective_trim" in n for n in res.notes),
            "ADR-055: срезанное защитами обязано быть НАЗВАНО в нотах цикла",
        )

    def test_result_serialises_the_record(self):
        self.assertIn("protective_trim", self._allocate().to_dict())


class MoneyPathStaysPut(unittest.TestCase):
    """Сигнал называется; капитал по умолчанию не двигается (решение владельца)."""

    @staticmethod
    def _adapters():
        return [{"protocol": p, "tier": t, "apy_pct": apy, "tvl_source": "live",
                 "tvl_usd": 5e7, "chain": "ethereum"}
                for p, t, apy in (("aave_v3", "T1", 5.0), ("compound_v3", "T1", 3.3))]

    def test_named_but_not_spent_by_default(self):
        book = {"aave_v3": 40_000.0}          # аллокатор уже срезал сам себя
        r = redistribute_freed_budget(
            book, dict(book), CAP, self._adapters(), {"tvl_unverified": []},
            protective_trim_usd=20_000.0)
        self.assertEqual(r["freed_usd"], 0.0)             # деньги не тронуты
        self.assertEqual(r["added"], {})
        self.assertEqual(r["target_usd"], book)
        self.assertEqual(r["protective_trim_usd"], 20_000.0)   # но НАЗВАНЫ
        self.assertFalse(r["protective_trim_redistributed"])
        self.assertTrue(any("ADR-055" in n for n in r["notes"]))

    def test_enabled_signal_places_it_and_never_breaches_the_buffer(self):
        book = {"aave_v3": 40_000.0}
        r = redistribute_freed_budget(
            book, dict(book), CAP, self._adapters(), {"tvl_unverified": []},
            protective_trim_usd=90_000.0,      # заведомо больше буфера
            redistribute_protective_trim=True)
        self.assertTrue(r["protective_trim_redistributed"])
        self.assertGreater(sum(r["added"].values()), 0.0)
        # min-cash 5 % неприкосновенен даже при завышенном сигнале.
        self.assertLessEqual(sum(r["target_usd"].values()), CAP * 0.95 + 1e-6)

    def test_absent_signal_keeps_the_prior_behaviour_bit_for_bit(self):
        pre = {"aave_v3": 40_000.0, "maple": 20_000.0}
        post = {"aave_v3": 40_000.0, "maple": 10_000.0}
        base = redistribute_freed_budget(
            post, pre, CAP, self._adapters(), {"tvl_unverified": []})
        self.assertEqual(base["protective_trim_usd"], 0.0)
        self.assertFalse(base["protective_trim_redistributed"])
        self.assertGreater(base["freed_usd"], 0.0)   # прежний путь жив

    def test_garbage_signal_is_ignored_not_trusted(self):
        book = {"aave_v3": 40_000.0}
        for bad in (float("nan"), float("inf"), -5.0, "много", None):
            r = redistribute_freed_budget(
                book, dict(book), CAP, self._adapters(), {"tvl_unverified": []},
                protective_trim_usd=bad, redistribute_protective_trim=True)
            self.assertEqual(r["protective_trim_usd"], 0.0, bad)
            self.assertEqual(r["added"], {}, bad)


class LedgerCarriesIt(unittest.TestCase):
    def test_gate_ledger_records_the_allocator_side_trim(self):
        pt = measure_protective_trim(
            [stage("tier_caps", "was_capped", True, 1.00, 0.80)], CAP)
        led = build_gate_ledger(
            allocator_target={"aave_v3": 40_000.0},
            pre_gate_target={"aave_v3": 40_000.0},
            post_gate_target={"aave_v3": 40_000.0},
            gate={"approved": True, "error": None},
            protective_trim=pt,
        )
        self.assertAlmostEqual(
            led["allocator_protective_trim"]["total_usd"], 20_000.0, delta=1.0)

    def test_ledger_without_the_record_says_empty_not_zero(self):
        led = build_gate_ledger(
            allocator_target={}, pre_gate_target={}, post_gate_target={},
            gate={"approved": True, "error": None})
        self.assertEqual(led["allocator_protective_trim"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
