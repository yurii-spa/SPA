#!/usr/bin/env python3
"""Тесты risk-aware аллокации (SPA-V406).

Подключение risk scoring engine (``data/risk_scores.json``) к Strategy Allocator:
вес ∝ ``apy_pct × grade_multiplier``, исключение grade D, консервативный дефолт B,
graceful fallback при отсутствии/повреждении файла оценок.

Сетевых вызовов нет, файловые операции — во временном каталоге. pytest в репо не
установлен, поэтому тесты на ``unittest`` (stdlib)::

    python3 -m unittest spa_core.tests.test_risk_adjusted_allocation -v
    python3 spa_core/tests/test_risk_adjusted_allocation.py
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator import allocation_models as m
from spa_core.allocator.allocator import (
    DEFAULT_MODEL,
    StrategyAllocator,
)
try:
    from spa_core.utils.errors import AllocationError as _AllocationError
except ImportError:
    _AllocationError = None


def make_adapters() -> list[dict]:
    """4 T2-адаптера как в реальном снимке оркестратора."""
    return [
        {"protocol": "morpho_blue", "apy_pct": 8.3, "tvl_usd": 0.0, "tier": "T2"},
        {"protocol": "yearn_v3", "apy_pct": 7.2, "tvl_usd": 0.0, "tier": "T2"},
        {"protocol": "euler_v2", "apy_pct": 9.1, "tvl_usd": 0.0, "tier": "T2"},
        {"protocol": "maple", "apy_pct": 10.5, "tvl_usd": 0.0, "tier": "T2"},
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


def write_risk_scores(path: Path, slug_to_grade: dict[str, str]) -> None:
    """Пишет файл в схеме risk scoring engine: {"scores":[{slug,grade}]}."""
    payload = {
        "generated_at": "2026-06-10T00:00:00Z",
        "engine_version": "1.0",
        "scores": [
            {"slug": slug, "grade": grade} for slug, grade in slug_to_grade.items()
        ],
        "summary_by_grade": {"A": 0, "B": 0, "C": 0, "D": 0},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ─── Модель risk_adjusted_weight / risk_adjusted_breakdown ──────────────────────


class TestRiskAdjustedModel(unittest.TestCase):
    def test_grade_a_gets_higher_weight_than_b(self):
        # одинаковый APY, но A (×1.0) против B (×0.85) → A получает больший вес
        adapters = [
            {"protocol": "alpha", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "beta", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        scores = {"alpha": "A", "beta": "B"}
        w = m.risk_adjusted_weight(adapters, scores)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        self.assertGreater(w["alpha"], w["beta"])

    def test_grade_d_excluded_from_allocation(self):
        adapters = [
            {"protocol": "good", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "bad", "apy_pct": 9.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        scores = {"good": "A", "bad": "D"}
        bd = m.risk_adjusted_breakdown(adapters, scores)
        self.assertEqual(bd["weights"]["bad"], 0.0)
        self.assertIn("bad", bd["excluded"])
        # весь капитал ушёл единственному не-исключённому протоколу
        self.assertAlmostEqual(bd["weights"]["good"], 1.0, places=9)

    def test_missing_score_defaults_to_b(self):
        adapters = [{"protocol": "unknown_proto", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"}]
        bd = m.risk_adjusted_breakdown(adapters, {})  # пустые оценки
        self.assertEqual(bd["per_protocol"]["unknown_proto"]["risk_grade"], "B")
        self.assertAlmostEqual(
            bd["per_protocol"]["unknown_proto"]["risk_multiplier"], 0.85, places=9
        )

    def test_all_excluded_fallback_to_equal_weight(self):
        adapters = [
            {"protocol": "d1", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "d2", "apy_pct": 9.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        scores = {"d1": "D", "d2": "D"}
        bd = m.risk_adjusted_breakdown(adapters, scores)
        self.assertTrue(bd["fallback_equal_weight"])
        self.assertAlmostEqual(bd["weights"]["d1"], 0.5, places=9)
        self.assertAlmostEqual(bd["weights"]["d2"], 0.5, places=9)

    def test_weights_sum_to_one(self):
        scores = {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "C"}
        w = m.risk_adjusted_weight(make_adapters(), scores)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)

    def test_empty_adapters_returns_empty(self):
        self.assertEqual(m.risk_adjusted_weight([], {"x": "A"}), {})
        bd = m.risk_adjusted_breakdown([], {"x": "A"})
        self.assertEqual(bd["weights"], {})
        self.assertEqual(bd["per_protocol"], {})

    def test_custom_grade_multipliers(self):
        adapters = [
            {"protocol": "a", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "b", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        # перекрываем: C теперь множитель 0.0 (исключается)
        bd = m.risk_adjusted_breakdown(
            adapters, {"a": "A", "b": "C"}, grade_multipliers={"C": 0.0}
        )
        self.assertIn("b", bd["excluded"])
        self.assertEqual(bd["weights"]["b"], 0.0)

    def test_normalization_underscore_vs_hyphen(self):
        # адаптер euler_v2 должен совпасть со slug euler-v2
        adapters = [{"protocol": "euler_v2", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"}]
        bd = m.risk_adjusted_breakdown(adapters, {"euler-v2": "A"})
        self.assertEqual(bd["per_protocol"]["euler_v2"]["risk_grade"], "A")

    def test_pre_and_post_risk_weights_present(self):
        adapters = [
            {"protocol": "a", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "b", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        bd = m.risk_adjusted_breakdown(adapters, {"a": "A", "b": "B"})
        for p in ("a", "b"):
            entry = bd["per_protocol"][p]
            self.assertIn("pre_risk_weight", entry)
            self.assertIn("post_risk_weight", entry)
        # равный APY → равный pre-risk вес; B имеет меньший post-risk вес
        self.assertAlmostEqual(
            bd["per_protocol"]["a"]["pre_risk_weight"],
            bd["per_protocol"]["b"]["pre_risk_weight"],
            places=9,
        )
        self.assertGreater(
            bd["per_protocol"]["a"]["post_risk_weight"],
            bd["per_protocol"]["b"]["post_risk_weight"],
        )

    def test_zero_apy_all_fallback_equal_weight(self):
        adapters = [
            {"protocol": "a", "apy_pct": 0.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "b", "apy_pct": 0.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        bd = m.risk_adjusted_breakdown(adapters, {"a": "A", "b": "A"})
        self.assertTrue(bd["fallback_equal_weight"])
        self.assertAlmostEqual(sum(bd["weights"].values()), 1.0, places=9)


# ─── StrategyAllocator с risk-моделью ───────────────────────────────────────────


class TestRiskAwareAllocator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.status = self.dir / "adapter_orchestrator_status.json"
        self.risk = self.dir / "risk_scores.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _allocator(self, adapters, scores=None, write_scores=True):
        write_status(self.status, adapters)
        if write_scores and scores is not None:
            write_risk_scores(self.risk, scores)
        # Pass a non-existent registry_path to prevent the real adapter_registry.json
        # from being merged in (MP-REGISTRY feature) — keeps tests hermetic.
        return StrategyAllocator(
            status_path=self.status,
            risk_scores_path=self.risk,
            registry_path=self.dir / "nonexistent_registry.json",
        )

    def test_default_model_is_risk_adjusted(self):
        self.assertEqual(DEFAULT_MODEL, "risk_adjusted")
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate()  # без явной модели → default
        self.assertEqual(res.model_used, "risk_adjusted")
        self.assertTrue(res.risk_model_applied)

    def test_risk_model_applied_flag_true_when_scores_loaded(self):
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate(model="risk_adjusted")
        self.assertTrue(res.risk_model_applied)

    def test_risk_model_applied_flag_false_when_no_file(self):
        # файл оценок не пишем вовсе
        alloc = self._allocator(make_adapters(), scores=None, write_scores=False)
        res = alloc.allocate(model="risk_adjusted")
        self.assertFalse(res.risk_model_applied)

    def test_risk_scores_file_missing_graceful_fallback(self):
        alloc = self._allocator(make_adapters(), scores=None, write_scores=False)
        res = alloc.allocate(model="risk_adjusted")
        self.assertFalse(res.risk_model_applied)
        # деградация на equal_weight: валидное распределение, без падений
        self.assertGreater(len(res.target_weights), 0)
        self.assertLessEqual(sum(res.target_weights.values()), 1.0 + 1e-6)
        self.assertTrue(any("risk_scores.json" in n for n in res.notes))

    def test_risk_scores_corrupt_json_graceful_fallback(self):
        write_status(self.status, make_adapters())
        self.risk.write_text("{ this is not valid json ", encoding="utf-8")
        alloc = StrategyAllocator(status_path=self.status, risk_scores_path=self.risk)
        res = alloc.allocate(model="risk_adjusted")
        self.assertFalse(res.risk_model_applied)
        self.assertGreater(len(res.target_weights), 0)

    def test_output_contains_risk_grade_fields(self):
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate(model="risk_adjusted")
        self.assertTrue(res.risk_breakdown)
        for p, entry in res.risk_breakdown.items():
            self.assertIn("risk_grade", entry)
            self.assertIn("risk_multiplier", entry)
            self.assertIn("pre_risk_weight", entry)
            self.assertIn("post_risk_weight", entry)

    def test_grade_d_not_refunded_by_remainder_fill(self):
        # критично: grade D исключён и НЕ должен получить капитал через
        # _fill_remainder (SPA-V405), даже имея headroom.
        adapters = [
            {"protocol": "good_a", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T1"},
            {"protocol": "bad_d", "apy_pct": 12.0, "tvl_usd": 0.0, "tier": "T1"},
        ]
        alloc = self._allocator(adapters, {"good_a": "A", "bad_d": "D"})
        res = alloc.allocate(model="risk_adjusted")
        self.assertEqual(res.target_weights.get("bad_d", 0.0), 0.0)
        self.assertIn("bad_d", res.risk_breakdown)
        self.assertEqual(res.risk_breakdown["bad_d"]["risk_grade"], "D")

    def test_excluded_by_risk_note_present(self):
        adapters = [
            {"protocol": "good_a", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "bad_d", "apy_pct": 12.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        alloc = self._allocator(adapters, {"good_a": "A", "bad_d": "D"})
        res = alloc.allocate(model="risk_adjusted")
        self.assertTrue(any("excluded_by_risk" in n for n in res.notes))

    def test_all_grade_d_warning_and_fallback(self):
        adapters = [
            {"protocol": "d1", "apy_pct": 5.0, "tvl_usd": 0.0, "tier": "T2"},
            {"protocol": "d2", "apy_pct": 9.0, "tvl_usd": 0.0, "tier": "T2"},
        ]
        alloc = self._allocator(adapters, {"d1": "D", "d2": "D"})
        res = alloc.allocate(model="risk_adjusted")
        self.assertTrue(res.risk_model_applied)
        self.assertTrue(any("WARNING" in n for n in res.notes))

    def test_caps_still_enforced_with_risk_model(self):
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate(model="risk_adjusted")
        for p, w in res.target_weights.items():
            self.assertLessEqual(w, StrategyAllocator.T2_CAP + 1e-9)

    def test_missing_protocol_score_defaults_to_b_in_output(self):
        # maple отсутствует в оценках → консервативный grade B в выводе
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A"},
        )
        res = alloc.allocate(model="risk_adjusted")
        self.assertEqual(res.risk_breakdown["maple"]["risk_grade"], "B")

    def test_unknown_model_still_raises(self):
        alloc = self._allocator(make_adapters(), {"morpho_blue": "A"})
        _exc = (ValueError,) + ((_AllocationError,) if _AllocationError else ())
        with self.assertRaises(_exc):
            alloc.allocate(model="moon_math")

    def test_weights_sum_le_one_after_caps(self):
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate(model="risk_adjusted")
        self.assertLessEqual(sum(res.target_weights.values()), 1.0 + 1e-6)

    def test_save_roundtrip_includes_risk_fields(self):
        alloc = self._allocator(
            make_adapters(),
            {"morpho_blue": "A", "yearn_v3": "B", "euler_v2": "A", "maple": "B"},
        )
        res = alloc.allocate(model="risk_adjusted")
        out = self.dir / "target_allocation.json"
        alloc.save(res, out)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("risk_model_applied", loaded)
        self.assertIn("risk_breakdown", loaded)
        self.assertTrue(loaded["risk_model_applied"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
