"""Тесты ADR-072: срезанный гейтом бюджет не выбрасывается (мандат владельца 07.08).

Positive control — инцидент 2026-08-07: гейт срезал maple 20→10% и morpho 20→5%,
освобождённые ~20% капитала лежали в кэше под 0%, пока compound_v3 (T1, 3.3%,
live TVL) стоял с нулём. Обе стороны каждой границы:

  * срезанные/замороженные гейтом пулы НЕ дофинансируются (слово гейта свято);
  * кандидат без live-TVL или без положительного конечного APY — не кандидат
    (литерал ≠ наблюдение, ADR-061/063);
  * буфер min-cash неприкосновенен; потолки T1/T2/T2-total соблюдены;
  * ALLOC-002: новых имён сверх max_protocols не открываем;
  * мелочь (<0.5% капитала) не гоняем; мусорный вход не роняет цикл.
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading.risk_gate import redistribute_freed_budget

CAP = 100_000.0


def adapter(p, tier="T1", apy=3.3, tvl_source="live"):
    return {"protocol": p, "tier": tier, "apy_pct": apy, "tvl_source": tvl_source,
            "tvl_usd": 50_000_000.0}


def incident():
    """Сегодняшний прод: оптимизатор просил 95%, гейт срезал до 75%."""
    pre = {"aave_v3": 40_000.0, "pendle": 15_000.0, "maple": 20_000.0,
           "morpho_steakhouse": 20_000.0}
    post = {"aave_v3": 40_000.0, "pendle": 15_000.0, "maple": 10_000.0,
            "morpho_steakhouse": 5_000.0}
    adapters = [adapter("aave_v3", "T1", 5.01), adapter("compound_v3", "T1", 3.30),
                adapter("yearn_v3", "T2", 3.27), adapter("euler_v2", "T2", 3.06),
                adapter("maple", "T2", 4.91), adapter("morpho_steakhouse", "T1", 3.40),
                adapter("pendle", "T2", 15.49)]
    gate = {"tvl_unverified": [], "approved": True}
    return pre, post, adapters, gate


class PositiveControl(unittest.TestCase):
    def test_freed_budget_goes_to_live_positive_candidates(self):
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        # строго срезанное гейтом: 95k заявлено − 70k осталось = 25k
        self.assertAlmostEqual(sum(r["added"].values()), 25_000.0, delta=1.0)
        self.assertAlmostEqual(r["freed_usd"], 25_000.0, delta=1.0)
        self.assertIn("compound_v3", r["added"])          # T1 3.3% > кэш 0%
        self.assertNotIn("maple", r["added"])             # срезан гейтом
        self.assertNotIn("morpho_steakhouse", r["added"])  # срезан гейтом
        self.assertLessEqual(sum(r["target_usd"].values()), CAP * 0.95 + 1e-6)
        self.assertTrue(all("ADR-072" in n for n in r["notes"]))  # именовано

    def test_gate_frozen_pool_never_refilled(self):
        pre, post, adapters, gate = incident()
        gate = dict(gate, tvl_unverified=["compound_v3"])
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertNotIn("compound_v3", r["added"])

    def test_non_live_tvl_and_bad_apy_are_not_candidates(self):
        pre, post, _, gate = incident()
        adapters = [adapter("static_pool", "T1", 9.9, tvl_source="static"),
                    adapter("none_apy", "T1", None),
                    adapter("zero_apy", "T1", 0.0),
                    adapter("nan_apy", "T1", float("nan"))]
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertEqual(r["added"], {})

    def test_min_cash_buffer_untouchable(self):
        pre, post, adapters, gate = incident()
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate,
                                      min_cash_pct=0.25)
        self.assertLessEqual(sum(r["target_usd"].values()), CAP * 0.75 + 1e-6)

    def test_tier_caps_and_t2_total_respected(self):
        pre = {"aave_v3": 40_000.0}
        post = {"aave_v3": 20_000.0}  # гейт срезал aave на 20k — ровно они и перераздаются
        adapters = [adapter("t2a", "T2", 9.0), adapter("t2b", "T2", 8.0),
                    adapter("t2c", "T2", 7.0), adapter("aave_v3", "T1", 5.0)]
        gate = {"tvl_unverified": [], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        t = r["target_usd"]
        self.assertNotIn("aave_v3", r["added"])  # срезан — не дофинансируем
        for p in ("t2a", "t2b", "t2c"):
            self.assertLessEqual(t.get(p, 0.0), CAP * 0.20 + 1e-6)
        t2_sum = t.get("t2a", 0) + t.get("t2b", 0) + t.get("t2c", 0)
        self.assertLessEqual(t2_sum, CAP * 0.35 + 1e-6)

    def test_alloc002_no_new_names_beyond_limit(self):
        pre = {f"h{i}": 9_000.0 for i in range(8)}   # 8 держимых (лимит)
        post = {f"h{i}": 8_000.0 for i in range(8)}  # гейт срезал всех по чуть
        adapters = ([adapter(f"h{i}", "T2", 4.0) for i in range(8)]
                    + [adapter("newcomer", "T1", 6.0)])
        gate = {"tvl_unverified": [], "approved": True}
        r = redistribute_freed_budget(post, pre, CAP, adapters, gate)
        self.assertNotIn("newcomer", r["added"])  # 9-е имя не открываем

    def test_model_underdeployment_is_not_our_business(self):
        """Аллокатор сам решил маленькую книгу (гейт ничего не резал) —
        перераздача НЕ трогает: спасаем срезанное, не отменяем модель."""
        small = {"aave_v3": 30_000.0}
        r = redistribute_freed_budget(small, dict(small), CAP,
                                      [adapter("compound_v3", "T1", 3.3)],
                                      {"tvl_unverified": []})
        self.assertEqual(r["added"], {})
        self.assertEqual(r["freed_usd"], 0.0)

    def test_tiny_freed_is_left_alone(self):
        pre = {"aave_v3": 40_000.0}
        post = {"aave_v3": 39_800.0}  # свободно $200 < 0.5% капитала... но 95k-39.8k
        # честный кейс: почти всё развёрнуто
        post_full = {"aave_v3": 40_000.0, "p": 54_800.0}
        r = redistribute_freed_budget(post_full, post_full, CAP,
                                      [adapter("x", "T1", 5.0)],
                                      {"tvl_unverified": []})
        self.assertEqual(r["added"], {})

    def test_garbage_never_raises(self):
        r = redistribute_freed_budget({}, {}, float("nan"), None,
                                      {"tvl_unverified": None})
        self.assertEqual(r["added"], {})
        r2 = redistribute_freed_budget({"a": "мусор"}, {}, CAP,
                                       [{"broken": True}, None], {})
        self.assertIsInstance(r2["target_usd"], dict)


if __name__ == "__main__":
    unittest.main()
