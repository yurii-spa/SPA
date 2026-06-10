#!/usr/bin/env python3
"""Тесты устранения структурного cash-drag в аллокаторе (SPA-V405).

Проверяют, что T1-якорь (Aave V3) заполняет остаток после cap'ов по T2 и что
``cash_pct``/``t1_pct``/``t2_pct``/``total_deployed_pct`` считаются честно.

Сети нет, файлы — во временном каталоге. Тесты на ``unittest``::

    python3 -m unittest spa_core.tests.test_allocator_cash_drag -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator.allocator import StrategyAllocator


def write_status(path: Path, adapters: list[dict]) -> None:
    payload = {
        "adapters": [
            {
                "protocol": a["protocol"],
                "apy_pct": a["apy_pct"],
                "tvl_usd": a.get("tvl_usd", 0.0),
                "tier": a["tier"],
                "status": a.get("status", "ok"),
            }
            for a in adapters
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def four_t2() -> list[dict]:
    return [
        {"protocol": "morpho_blue", "apy_pct": 8.3, "tier": "T2"},
        {"protocol": "yearn_v3", "apy_pct": 7.2, "tier": "T2"},
        {"protocol": "euler_v2", "apy_pct": 9.1, "tier": "T2"},
        {"protocol": "maple", "apy_pct": 10.5, "tier": "T2"},
    ]


def four_t2_plus_aave() -> list[dict]:
    return four_t2() + [
        {"protocol": "aave_v3", "apy_pct": 5.2, "tier": "T1", "tvl_usd": 9e8},
    ]


class TestCashDrag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.status = self.dir / "adapter_orchestrator_status.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _alloc(self, adapters) -> StrategyAllocator:
        write_status(self.status, adapters)
        return StrategyAllocator(status_path=self.status)

    # ── базовая проблема: drag без якоря ─────────────────────────────────
    def test_drag_present_without_t1_anchor(self):
        # 4×T2 equal = 0.25 → cap 0.20 → 0.80 размещено, 0.20 кэш (нет якоря).
        res = self._alloc(four_t2()).allocate(model="equal_weight")
        self.assertAlmostEqual(res.cash_pct, 0.20, places=6)
        self.assertAlmostEqual(res.total_deployed_pct, 0.80, places=6)

    # ── решение: якорь заполняет остаток ─────────────────────────────────
    def test_no_cash_drag_when_all_adapters_live(self):
        # 4×T2 + 1 T1: остаток 20% уходит в Aave (cap 40%) → cash_pct == 0.
        res = self._alloc(four_t2_plus_aave()).allocate(model="equal_weight")
        self.assertAlmostEqual(res.cash_pct, 0.0, places=6)
        self.assertAlmostEqual(res.total_deployed_pct, 1.0, places=6)

    def test_t1_fills_remainder(self):
        # equal_weight 5 адаптеров = 0.20 каждый; T2 ровно на cap, Aave 0.20.
        # Остатка нет, но проверяем, что T1 несёт ненулевой вес и разбивка верна.
        res = self._alloc(four_t2_plus_aave()).allocate(model="equal_weight")
        self.assertGreater(res.t1_pct, 0.0)
        self.assertIn("aave_v3", res.target_weights)
        self.assertAlmostEqual(res.t1_pct + res.t2_pct + res.cash_pct, 1.0, places=6)

    def test_best_apy_remainder_goes_to_anchor(self):
        # best_apy выбирает top-3 T2 (maple/euler/morpho) по 0.333 → cap 0.20.
        # 3×0.20 = 0.60 размещено по T2, остаток 0.40 → Aave (cap 0.40).
        res = self._alloc(four_t2_plus_aave()).allocate(model="best_apy")
        self.assertIn("aave_v3", res.target_weights)
        self.assertAlmostEqual(res.target_weights["aave_v3"], 0.40, places=6)
        self.assertAlmostEqual(res.cash_pct, 0.0, places=6)
        self.assertAlmostEqual(res.total_deployed_pct, 1.0, places=6)

    def test_t1_weight_never_exceeds_cap(self):
        res = self._alloc(four_t2_plus_aave()).allocate(model="best_apy")
        self.assertLessEqual(
            res.target_weights.get("aave_v3", 0.0), StrategyAllocator.T1_CAP + 1e-9
        )

    def test_t2_weights_never_exceed_cap_after_fill(self):
        res = self._alloc(four_t2_plus_aave()).allocate(model="best_apy")
        for p, w in res.target_weights.items():
            if p == "aave_v3":
                continue
            self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9, msg=p)

    # ── честный кэш, когда якорь недоступен ──────────────────────────────
    def test_cash_remains_when_t1_unavailable(self):
        # T1 в статусе error → отфильтрован → остаток уходит в headroom T2.
        # При 4×T2 (все на cap) headroom нет → 0.20 честно остаётся кэшем.
        adapters = four_t2() + [
            {"protocol": "aave_v3", "apy_pct": 5.2, "tier": "T1", "status": "error"}
        ]
        res = self._alloc(adapters).allocate(model="equal_weight")
        self.assertNotIn("aave_v3", res.target_weights)
        self.assertAlmostEqual(res.cash_pct, 0.20, places=6)

    def test_cash_fallback_when_all_error(self):
        adapters = [
            {"protocol": "aave_v3", "apy_pct": 5.2, "tier": "T1", "status": "error"},
            {"protocol": "morpho_blue", "apy_pct": 8.3, "tier": "T2", "status": "error"},
        ]
        res = self._alloc(adapters).allocate(model="equal_weight")
        self.assertEqual(res.target_weights, {})
        self.assertAlmostEqual(res.cash_pct, 1.0, places=6)
        self.assertAlmostEqual(res.total_deployed_pct, 0.0, places=6)

    def test_remainder_to_best_t2_when_no_t1(self):
        # Нет T1 вообще, best_apy берёт top-3 из 4 T2 → 0.60 размещено,
        # остаток 0.40 заполняет headroom 4-го T2 (cap 0.20) → 0.20,
        # итог 0.80 размещено, 0.20 кэш (нет якоря, ёмкости не хватает).
        res = self._alloc(four_t2()).allocate(model="best_apy")
        self.assertAlmostEqual(res.total_deployed_pct, 0.80, places=6)
        self.assertAlmostEqual(res.cash_pct, 0.20, places=6)
        # 4-й T2 (yearn) подхватил часть остатка.
        self.assertIn("yearn_v3", res.target_weights)

    # ── инварианты вывода ────────────────────────────────────────────────
    def test_breakdown_fields_sum_to_one(self):
        res = self._alloc(four_t2_plus_aave()).allocate(model="risk_parity")
        self.assertAlmostEqual(
            res.t1_pct + res.t2_pct + res.cash_pct, 1.0, places=6
        )

    def test_total_deployed_equals_allocated(self):
        res = self._alloc(four_t2_plus_aave()).allocate(model="equal_weight")
        self.assertAlmostEqual(res.total_deployed_pct, res.allocated_pct, places=9)
        self.assertAlmostEqual(res.cash_pct, res.unallocated_pct, places=9)

    def test_expected_apy_excludes_cash(self):
        # APY портфеля = Σ(weight·apy); кэш вносит 0%.
        res = self._alloc(four_t2_plus_aave()).allocate(model="equal_weight")
        apy_map = {a["protocol"]: a["apy_pct"] for a in four_t2_plus_aave()}
        manual = sum(res.target_weights[p] * apy_map[p] for p in res.target_weights)
        self.assertAlmostEqual(res.expected_apy_pct, manual, places=4)

    def test_no_cash_drag_persists_to_saved_json(self):
        alloc = self._alloc(four_t2_plus_aave())
        res = alloc.allocate(model="equal_weight")
        out = self.dir / "target_allocation.json"
        alloc.save(res, out)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("cash_pct", loaded)
        self.assertIn("t1_pct", loaded)
        self.assertIn("t2_pct", loaded)
        self.assertIn("total_deployed_pct", loaded)
        self.assertAlmostEqual(loaded["cash_pct"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
