"""Явный сигнал «сколько срезали защитные тримы» (ADR-072-остаток, G3).

Карточка `inbox-adr-072-ne-srabotal-trim-proishodit-v-al`: тримы внутри
аллокатора (T2/T3 total-cap) роняли вес в кэш молча — перезаполнитель считал
freed по разнице сумм гейта и видел ноль. Теперь дельта каждого защитного шага
измеряется по факту и уезжает в `AllocationResult.protective_trims` + notes.

Offline, файлы во временном каталоге::

    python3 -m unittest spa_core.tests.test_allocator_protective_trims -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator.allocator import StrategyAllocator


def _alloc(adapters):
    tmp = Path(tempfile.mkdtemp(prefix="trims_"))
    (tmp / "status.json").write_text(json.dumps({"adapters": adapters}))
    return StrategyAllocator(
        status_path=tmp / "status.json",
        registry_path=tmp / "__no_registry__.json",
        live_apy_provider=False,
    )


def four_t2():
    return [
        {"protocol": "morpho_blue", "apy_pct": 8.3, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "yearn_v3", "apy_pct": 7.2, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "euler_v2", "apy_pct": 9.1, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "maple", "apy_pct": 10.5, "tvl_usd": 5e7, "tier": "T2"},
    ]


class TestProtectiveTrimSignal(unittest.TestCase):
    def test_t2_total_cap_cut_is_measured(self):
        # 4×T2 без T1: caps дают 4×20% = 80%, T2-total режет до 50% →
        # срез 30% обязан быть НАЗВАН числом, а не потеряться в кэше молча.
        res = _alloc(four_t2()).allocate(model="equal_weight")
        self.assertIn("t2_total_cap", res.protective_trims)
        self.assertAlmostEqual(res.protective_trims["t2_total_cap"], 0.30, places=6)
        self.assertTrue(any("Защитные тримы" in n for n in res.notes))
        self.assertAlmostEqual(res.cash_pct, 0.50, places=6)

    def test_no_trim_no_signal(self):
        # ДВА T1-якоря впитывают излишек T2-капа целиком (headroom 2×(40−16.7)%
        # > срезанных 16.7%): тримы в кэш не срезали ничего → сигнала нет
        # (пустой dict, нет ложной тревоги).
        res = _alloc(four_t2() + [
            {"protocol": "aave_v3", "apy_pct": 5.2, "tvl_usd": 9e8, "tier": "T1"},
            {"protocol": "compound_v3", "apy_pct": 4.8, "tvl_usd": 8e8, "tier": "T1"},
        ]).allocate(model="equal_weight")
        self.assertEqual(res.protective_trims, {})
        self.assertFalse(any("Защитные тримы" in n for n in res.notes))

    def test_signal_matches_actual_cash(self):
        # Сигнал обязан сходиться с фактическим кэшем: сумма срезов ≤ кэш.
        res = _alloc(four_t2()).allocate(model="equal_weight")
        self.assertLessEqual(sum(res.protective_trims.values()),
                             res.cash_pct + 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
