#!/usr/bin/env python3
"""Тесты Strategy Allocator (SPA-V388).

Сетевых вызовов нет, файловые операции идут во временный каталог. pytest в репо
не установлен, поэтому тесты на ``unittest`` (stdlib) и запускаются как::

    python3 -m unittest spa_core.tests.test_allocator -v
    python3 spa_core/tests/test_allocator.py
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator import allocation_models as m
from spa_core.allocator.allocator import StrategyAllocator


def make_adapters() -> list[dict]:
    """4 T2-адаптера как в реальном снимке оркестратора.

    TVL ≥ $5M, чтобы проходить MP-011 TVL-floor: эти тесты проверяют cap'ы,
    а не фильтр (фильтр покрыт в test_allocator_filters.py).
    """
    return [
        {"protocol": "morpho_blue", "apy_pct": 8.3, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "yearn_v3", "apy_pct": 7.2, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "euler_v2", "apy_pct": 9.1, "tvl_usd": 5e7, "tier": "T2"},
        {"protocol": "maple", "apy_pct": 10.5, "tvl_usd": 5e7, "tier": "T2"},
    ]


def write_status(path: Path, adapters: list[dict]) -> None:
    payload = {
        "adapters": [
            {
                "protocol": a["protocol"],
                "apy_pct": a["apy_pct"],
                "tvl_usd": a["tvl_usd"],
                "tier": a["tier"],
                "status": a.get("status", "ok"),
            }
            for a in adapters
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ─── Модели ──────────────────────────────────────────────────────────────────


class TestAllocationModels(unittest.TestCase):
    def test_equal_weight_sums_to_one(self):
        w = m.equal_weight(make_adapters())
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        self.assertEqual(len(w), 4)
        for v in w.values():
            self.assertAlmostEqual(v, 0.25, places=9)

    def test_equal_weight_empty(self):
        self.assertEqual(m.equal_weight([]), {})

    def test_best_apy_weight_top3(self):
        w = m.best_apy_weight(make_adapters(), top_n=3)
        self.assertEqual(len(w), 3)
        # top-3 по APY: maple(10.5), euler_v2(9.1), morpho_blue(8.3)
        self.assertEqual(set(w), {"maple", "euler_v2", "morpho_blue"})
        self.assertNotIn("yearn_v3", w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)

    def test_best_apy_weight_fewer_than_top_n(self):
        adapters = make_adapters()[:2]
        w = m.best_apy_weight(adapters, top_n=5)
        self.assertEqual(len(w), 2)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)

    def test_best_apy_weight_empty(self):
        self.assertEqual(m.best_apy_weight([], top_n=3), {})

    def test_risk_parity_no_division_by_zero(self):
        # все TVL == 0 и нет волатильности → fallback на равные веса, без ошибок
        w = m.risk_parity_weight(make_adapters())
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        for v in w.values():
            self.assertAlmostEqual(v, 0.25, places=9)

    def test_risk_parity_tvl_proxy(self):
        adapters = make_adapters()
        adapters[0]["tvl_usd"] = 30_000_000  # morpho
        adapters[1]["tvl_usd"] = 10_000_000  # yearn
        adapters[2]["tvl_usd"] = 10_000_000  # euler
        adapters[3]["tvl_usd"] = 0.0         # maple
        w = m.risk_parity_weight(adapters)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        # больший TVL → больший вес
        self.assertGreater(w["morpho_blue"], w["yearn_v3"])

    def test_risk_parity_volatility_inverse(self):
        adapters = make_adapters()
        adapters[0]["apy_vol"] = 1.0
        adapters[1]["apy_vol"] = 2.0
        adapters[2]["apy_vol"] = 4.0
        adapters[3]["apy_vol"] = 4.0
        w = m.risk_parity_weight(adapters)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        # меньшая волатильность → больший вес
        self.assertGreater(w["morpho_blue"], w["euler_v2"])


# ─── Allocator + cap'ы ─────────────────────────────────────────────────────────


class TestStrategyAllocator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.status = self.dir / "adapter_orchestrator_status.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _allocator(self, adapters):
        write_status(self.status, adapters)
        # Disable the MP-REGISTRY merge (point at a nonexistent registry) so these
        # unit tests exercise only the adapters they provide, not the full
        # registered universe.
        return StrategyAllocator(
            status_path=self.status, registry_path=self.dir / "no_registry.json"
        )

    def test_t2_cap_enforced(self):
        # 4×T2 equal weight = 0.25 каждый > 0.20 cap → каждый капается на 0.20.
        # MP-011: совокупный T2 ограничен 50% (ADR-019) — без T1-якоря остальное в кэш.
        alloc = self._allocator(make_adapters())
        res = alloc.allocate(model="equal_weight")
        for p, w in res.target_weights.items():
            self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9)
        self.assertAlmostEqual(
            res.allocated_pct, StrategyAllocator.T2_TOTAL_CAP, places=6
        )
        self.assertAlmostEqual(
            res.unallocated_pct, 1.0 - StrategyAllocator.T2_TOTAL_CAP, places=6
        )

    def test_t1_cap_enforced(self):
        # один T1 при best_apy top-1 хотел бы 1.0 → капается на 0.40
        adapters = [
            {"protocol": "aave_v3", "apy_pct": 5.0, "tvl_usd": 9e6, "tier": "T1"},
            {"protocol": "compound_v3", "apy_pct": 4.0, "tvl_usd": 9e6, "tier": "T1"},
        ]
        alloc = self._allocator(adapters)
        res = alloc.allocate(model="best_apy")  # top_n=3 → оба попадают, 0.5 each
        for p, w in res.target_weights.items():
            self.assertLessEqual(w, StrategyAllocator.T1_CAP + 1e-9)

    def test_weights_never_exceed_caps_any_model(self):
        for model in ("equal_weight", "best_apy", "risk_parity"):
            alloc = self._allocator(make_adapters())
            res = alloc.allocate(model=model)
            for p, w in res.target_weights.items():
                self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9, msg=model)

    def test_empty_adapters(self):
        alloc = self._allocator([])
        res = alloc.allocate(model="equal_weight")
        self.assertEqual(res.target_weights, {})
        self.assertEqual(res.target_usd, {})
        self.assertEqual(res.expected_apy_pct, 0.0)
        self.assertAlmostEqual(res.unallocated_pct, 1.0, places=6)

    def test_all_zero_apy(self):
        # 5×T2 по equal weight = 0.20 каждый (ровно cap, без обрезки).
        # MP-011: суммарный T2 срезается до 50% (ADR-019) — без T1 остальное в кэш.
        adapters = [
            {"protocol": f"p{i}", "apy_pct": 0.0, "tvl_usd": 1e7, "tier": "T2"}
            for i in range(5)
        ]
        alloc = self._allocator(adapters)
        res = alloc.allocate(model="equal_weight")
        self.assertEqual(res.expected_apy_pct, 0.0)
        self.assertAlmostEqual(
            sum(res.target_weights.values()), StrategyAllocator.T2_TOTAL_CAP,
            places=6,
        )

    def test_expected_apy_correct(self):
        # 3×T1, equal weight ≈0.333 (≤0.40 cap, без обрезки), APY 6/9/12 → среднее 9.0
        adapters = [
            {"protocol": "a", "apy_pct": 6.0, "tvl_usd": 1e7, "tier": "T1"},
            {"protocol": "b", "apy_pct": 9.0, "tvl_usd": 1e7, "tier": "T1"},
            {"protocol": "c", "apy_pct": 12.0, "tvl_usd": 1e7, "tier": "T1"},
        ]
        alloc = self._allocator(adapters)
        res = alloc.allocate(model="equal_weight")
        self.assertAlmostEqual(res.allocated_pct, 1.0, places=6)
        self.assertAlmostEqual(res.expected_apy_pct, 9.0, places=4)
        # инвариант: expected_apy == Σ(weight·apy)
        manual = sum(res.target_weights[p] * apy for p, apy in
                     (("a", 6.0), ("b", 9.0), ("c", 12.0)))
        self.assertAlmostEqual(res.expected_apy_pct, manual, places=4)

    def test_target_usd_matches_weights(self):
        alloc = self._allocator(make_adapters())
        res = alloc.allocate(model="equal_weight")
        for p, w in res.target_weights.items():
            self.assertAlmostEqual(
                res.target_usd[p], round(w * StrategyAllocator.CAPITAL, 2), places=2
            )

    def test_unknown_model_raises(self):
        alloc = self._allocator(make_adapters())
        with self.assertRaises(ValueError):
            alloc.allocate(model="moon_math")

    def test_save_writes_valid_json(self):
        alloc = self._allocator(make_adapters())
        res = alloc.allocate(model="equal_weight")
        out = self.dir / "target_allocation.json"
        alloc.save(res, out)
        self.assertTrue(out.exists())
        loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["model_used"], "equal_weight")
        self.assertIn("target_weights", loaded)
        self.assertIn("expected_apy_pct", loaded)

    def test_missing_status_file_returns_empty(self):
        alloc = StrategyAllocator(
            status_path=self.dir / "nope.json",
            registry_path=self.dir / "no_registry.json",
        )
        res = alloc.allocate(model="equal_weight")
        self.assertEqual(res.target_weights, {})

    def test_filters_non_ok_adapters(self):
        adapters = make_adapters()
        adapters[0]["status"] = "error"
        alloc = self._allocator(adapters)
        res = alloc.allocate(model="equal_weight")
        self.assertNotIn("morpho_blue", res.target_weights)
        self.assertEqual(len(res.target_weights), 3)


class TestRoundWeightsSumLeOne(unittest.TestCase):
    """_round_weights_sum_le_one: per-weight rounding must never push sum > 1.0."""

    def test_sum_never_exceeds_one(self):
        from spa_core.allocator.allocator import _round_weights_sum_le_one
        # Nine weights that each round UP at 6 decimals → naive sum = 1.000009.
        w = {f"p{i}": 0.1111111 for i in range(9)}
        out = _round_weights_sum_le_one(w, 6)
        self.assertLessEqual(sum(out.values()), 1.0 + 1e-9)

    def test_reduction_taken_from_largest(self):
        from spa_core.allocator.allocator import _round_weights_sum_le_one
        w = {"big": 0.6000005, "small": 0.4000005}  # naive rounded sum > 1.0
        out = _round_weights_sum_le_one(w, 6)
        self.assertLessEqual(sum(out.values()), 1.0 + 1e-9)
        # excess comes off the largest weight; no weight is ever increased
        self.assertLessEqual(out["big"], 0.600001)
        self.assertEqual(out["small"], 0.4)

    def test_under_one_left_untouched(self):
        from spa_core.allocator.allocator import _round_weights_sum_le_one
        w = {"a": 0.25, "b": 0.25}
        out = _round_weights_sum_le_one(w, 6)
        self.assertEqual(out, {"a": 0.25, "b": 0.25})


if __name__ == "__main__":
    unittest.main(verbosity=2)
