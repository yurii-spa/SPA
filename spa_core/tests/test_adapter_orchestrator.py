#!/usr/bin/env python3
"""Тесты adapter-оркестратора (SPA-V386).

Сетевых вызовов нет — адаптеры мокаются через ``unittest.mock``.
pytest в этом репо не установлен, поэтому файл написан на ``unittest`` (полностью
stdlib) и запускается как::

    python3 -m unittest spa_core.tests.test_adapter_orchestrator -v
    python3 spa_core/tests/test_adapter_orchestrator.py

При наличии pytest он тоже подхватит эти ``unittest.TestCase``-классы.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.orchestrator import adapter_orchestrator as orch
from spa_core.orchestrator.adapter_orchestrator import (
    OrchestratorResult,
    run_orchestrator,
)
from spa_core.orchestrator.health_score import (
    compute_health_score,
    compute_overall_health,
    grade_for_score,
)


# ─── Фейковые адаптеры ──────────────────────────────────────────────────────────


def make_adapter(
    protocol: str,
    apy: float = 0.08,
    tvl: float = 1_000_000.0,
    tier: str = "T2",
    *,
    raises: Exception | None = None,
    sleep: float = 0.0,
):
    """Сконструировать класс фейкового read-only адаптера."""

    class _FakeAdapter:
        PROTOCOL = protocol

        def __init__(self, *_a, **_k):
            if raises is not None and isinstance(raises, type):
                # исключение при инстанцировании
                raise raises("boom-in-init")

        def get_yield_info(self):
            if sleep:
                time.sleep(sleep)
            if raises is not None and not isinstance(raises, type):
                raise raises
            return YieldInfo(
                protocol=protocol,
                asset="USDC",
                apy=apy,
                tvl_usd=tvl,
                tier=tier,
                risk_score=0.3,
            )

    _FakeAdapter.__name__ = f"Fake_{protocol}"
    return _FakeAdapter


def registry_from(specs):
    """specs: list of (protocol_key, tier, adapter_cls) → реестр оркестратора."""
    return list(specs)


FIXED_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def fixed_now():
    return FIXED_NOW


# ─── Тесты оркестратора ─────────────────────────────────────────────────────────


class TestOrchestratorRun(unittest.TestCase):
    def test_all_adapters_ok(self):
        reg = registry_from([
            ("a", "T1", make_adapter("a", apy=0.05, tvl=2_000_000)),
            ("b", "T2", make_adapter("b", apy=0.07, tvl=3_000_000)),
            ("c", "T2", make_adapter("c", apy=0.09, tvl=1_000_000)),
            ("d", "T2", make_adapter("d", apy=0.06, tvl=4_000_000)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertIsInstance(res, OrchestratorResult)
        self.assertEqual(res.summary["total"], 4)
        self.assertEqual(res.summary["ok"], 4)
        self.assertEqual(res.summary["error"], 0)
        self.assertEqual(res.overall_health["grade"], "A")
        self.assertEqual(res.overall_health["score"], 1.0)

    def test_one_adapter_fails(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.05)),
            ("b", "T2", make_adapter("b", apy=0.07)),
            ("c", "T2", make_adapter("c", apy=0.09)),
            ("bad", "T2", make_adapter("bad", raises=RuntimeError("net down"))),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["ok"], 3)
        self.assertEqual(res.summary["error"], 1)
        # средний health < 1.0 из-за упавшего адаптера (3*1.0 + 0)/4 = 0.75
        self.assertLess(res.overall_health["score"], 1.0)
        self.assertEqual(res.overall_health["error_count"], 1)
        bad = next(a for a in res.adapters if a["protocol"] == "bad")
        self.assertEqual(bad["status"], "error")
        self.assertIsNotNone(bad["error"])
        self.assertEqual(bad["health_score"], 0.0)

    def test_all_adapters_fail(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", raises=RuntimeError("x"))),
            ("b", "T2", make_adapter("b", raises=ValueError("y"))),
            ("c", "T2", make_adapter("c", raises=KeyError("z"))),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["ok"], 0)
        self.assertEqual(res.summary["error"], 3)
        self.assertEqual(res.overall_health["grade"], "F")
        self.assertEqual(res.overall_health["score"], 0.0)

    def test_init_failure_isolated(self):
        # исключение при инстанцировании адаптера тоже изолируется
        reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.05)),
            ("boom", "T2", make_adapter("boom", raises=RuntimeError)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["ok"], 1)
        self.assertEqual(res.summary["error"], 1)

    def test_timeout_handling(self):
        # один адаптер «висит» дольше таймаута → status=timeout, health=0
        reg = registry_from([
            ("fast", "T2", make_adapter("fast", apy=0.05)),
            ("slow", "T2", make_adapter("slow", apy=0.05, sleep=1.5)),
        ])
        res = run_orchestrator(
            registry=reg, write=False, timeout=0.2, now_fn=fixed_now
        )
        slow = next(a for a in res.adapters if a["protocol"] == "slow")
        self.assertEqual(slow["status"], "timeout")
        self.assertEqual(slow["health_score"], 0.0)
        self.assertIn("timeout", slow["error"])
        self.assertEqual(res.summary["error"], 1)

    def test_partial_when_non_positive_apy(self):
        reg = registry_from([
            ("z", "T2", make_adapter("z", apy=0.0, tvl=500_000)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        z = res.adapters[0]
        self.assertEqual(z["status"], "partial")
        self.assertEqual(z["health_score"], 0.25)
        self.assertEqual(res.summary["partial"], 1)

    def test_apy_pct_conversion(self):
        # YieldInfo.apy десятичный (0.083) → apy_pct в процентах (8.3)
        reg = registry_from([("m", "T2", make_adapter("m", apy=0.083))])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertAlmostEqual(res.adapters[0]["apy_pct"], 8.3, places=4)

    def test_summary_best_apy(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.04)),
            ("b", "T2", make_adapter("b", apy=0.11)),  # лучший
            ("c", "T2", make_adapter("c", apy=0.07)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["best_apy"]["protocol"], "b")
        self.assertAlmostEqual(res.summary["best_apy"]["apy_pct"], 11.0, places=4)

    def test_summary_best_apy_none_when_all_fail(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", raises=RuntimeError("x"))),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertIsNone(res.summary["best_apy"])

    def test_summary_total_tvl(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.05, tvl=1_500_000)),
            ("b", "T2", make_adapter("b", apy=0.06, tvl=2_500_000)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["total_tvl_usd"], 4_000_000.0)

    def test_adapters_stable_order(self):
        reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.05, sleep=0.05)),
            ("b", "T2", make_adapter("b", apy=0.06)),
            ("c", "T2", make_adapter("c", apy=0.07)),
        ])
        res = run_orchestrator(registry=reg, write=False, now_fn=fixed_now)
        self.assertEqual([a["protocol"] for a in res.adapters], ["a", "b", "c"])

    def test_default_registry_has_readonly_adapters(self):
        # реестр по умолчанию — read-only адаптеры из spa_core/adapters.
        # SPA-V405: добавлен T1-якорь AaveV3Adapter.
        # SPA-V411: добавлен второй T1-якорь CompoundV3Adapter → теперь 6 адаптеров.
        names = [cls.__name__ for (_, _, cls) in orch.ADAPTER_REGISTRY]
        self.assertEqual(len(orch.ADAPTER_REGISTRY), 6)
        self.assertIn("AaveV3Adapter", names)
        self.assertIn("CompoundV3Adapter", names)
        self.assertIn("MorphoBlueAdapter", names)
        self.assertIn("YearnV3Adapter", names)
        self.assertIn("EulerV2Adapter", names)
        self.assertIn("MapleAdapter", names)
        # SPA-V411: Aave и Compound — два T1-якоря в реестре по умолчанию.
        tiers = {cls.__name__: tier for (_, tier, cls) in orch.ADAPTER_REGISTRY}
        self.assertEqual(tiers["AaveV3Adapter"], "T1")
        self.assertEqual(tiers["CompoundV3Adapter"], "T1")


# ─── Тесты записи на диск ───────────────────────────────────────────────────────


class TestAtomicWriteAndRing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.reg = registry_from([
            ("a", "T2", make_adapter("a", apy=0.05)),
            ("b", "T2", make_adapter("b", apy=0.07)),
        ])

    def tearDown(self):
        self._tmp.cleanup()

    def test_atomic_write(self):
        run_orchestrator(
            registry=self.reg, write=True, data_dir=self.data_dir, now_fn=fixed_now
        )
        status_file = self.data_dir / orch.STATUS_FILENAME
        self.assertTrue(status_file.exists())
        doc = json.loads(status_file.read_text(encoding="utf-8"))
        self.assertEqual(doc["source"], "adapter_orchestrator")
        self.assertEqual(doc["summary"]["total"], 2)
        # никаких незакрытых tmp-файлов не осталось
        leftovers = [p.name for p in self.data_dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_overwrites_cleanly(self):
        for _ in range(3):
            run_orchestrator(
                registry=self.reg, write=True, data_dir=self.data_dir, now_fn=fixed_now
            )
        files = [p.name for p in self.data_dir.iterdir()]
        # ровно два файла: status + runs (без .tmp-мусора)
        self.assertIn(orch.STATUS_FILENAME, files)
        self.assertIn(orch.RUNS_FILENAME, files)
        self.assertFalse(any(f.endswith(".tmp") for f in files))

    def test_does_not_touch_execution_adapter_status(self):
        # оркестратор НЕ должен писать execution-owned data/adapter_status.json
        run_orchestrator(
            registry=self.reg, write=True, data_dir=self.data_dir, now_fn=fixed_now
        )
        self.assertFalse((self.data_dir / "adapter_status.json").exists())

    def test_dry_run_no_write(self):
        run_orchestrator(
            registry=self.reg, write=False, data_dir=self.data_dir, now_fn=fixed_now
        )
        self.assertFalse((self.data_dir / orch.STATUS_FILENAME).exists())
        self.assertFalse((self.data_dir / orch.RUNS_FILENAME).exists())

    def test_orchestrator_runs_ring_buffer(self):
        runs_file = self.data_dir / orch.RUNS_FILENAME
        # стартовый файл с маленьким max_runs, чтобы быстро проверить обрезание
        runs_file.write_text(json.dumps({"runs": [], "max_runs": 3}), encoding="utf-8")
        for _ in range(5):
            run_orchestrator(
                registry=self.reg, write=True, data_dir=self.data_dir, now_fn=fixed_now
            )
        data = json.loads(runs_file.read_text(encoding="utf-8"))
        self.assertEqual(data["max_runs"], 3)
        self.assertEqual(len(data["runs"]), 3)  # кольцевой буфер обрезал до 3
        for r in data["runs"]:
            self.assertIn("summary", r)
            self.assertIn("overall_health", r)

    def test_ring_buffer_default_max_runs(self):
        # без стартового файла — дефолтный max_runs = 30
        run_orchestrator(
            registry=self.reg, write=True, data_dir=self.data_dir, now_fn=fixed_now
        )
        data = json.loads((self.data_dir / orch.RUNS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(data["max_runs"], orch.DEFAULT_MAX_RUNS)
        self.assertEqual(len(data["runs"]), 1)


# ─── Тесты health_score ─────────────────────────────────────────────────────────


class TestHealthScore(unittest.TestCase):
    def test_health_score_ok(self):
        r = {"status": "ok", "apy_pct": 7.2, "error": None}
        self.assertEqual(compute_health_score(r), 1.0)

    def test_health_score_low_apy(self):
        r = {"status": "ok", "apy_pct": 0.05, "error": None}
        self.assertEqual(compute_health_score(r), 0.75)

    def test_health_score_stale(self):
        old = (FIXED_NOW - timedelta(hours=2)).isoformat()
        r = {"status": "ok", "apy_pct": 7.0, "last_updated": old, "error": None}
        self.assertEqual(compute_health_score(r, now=FIXED_NOW), 0.5)

    def test_health_score_partial_warning(self):
        r = {"status": "ok", "apy_pct": 7.0, "warning": "stale-ish", "error": None}
        self.assertEqual(compute_health_score(r), 0.25)

    def test_health_score_error(self):
        r = {"status": "error", "error": "RuntimeError: boom"}
        self.assertEqual(compute_health_score(r), 0.0)

    def test_health_score_timeout(self):
        r = {"status": "timeout", "error": "timeout after 5s"}
        self.assertEqual(compute_health_score(r), 0.0)

    def test_health_score_missing_apy_is_partial(self):
        r = {"status": "ok", "apy_pct": None, "error": None}
        self.assertEqual(compute_health_score(r), 0.25)

    def test_grade_thresholds(self):
        self.assertEqual(grade_for_score(0.95), "A")
        self.assertEqual(grade_for_score(0.80), "B")
        self.assertEqual(grade_for_score(0.65), "C")
        self.assertEqual(grade_for_score(0.45), "D")
        self.assertEqual(grade_for_score(0.10), "F")

    def test_compute_overall_health_counts(self):
        results = [
            {"status": "ok", "apy_pct": 7.0, "health_score": 1.0},
            {"status": "ok", "apy_pct": 0.05, "health_score": 0.75},
            {"status": "partial", "warning": "x", "health_score": 0.25},
            {"status": "error", "error": "boom", "health_score": 0.0},
        ]
        overall = compute_overall_health(results)
        self.assertEqual(overall["total"], 4)
        self.assertEqual(overall["ok_count"], 2)
        self.assertEqual(overall["partial_count"], 1)
        self.assertEqual(overall["error_count"], 1)
        self.assertAlmostEqual(overall["score"], 0.5, places=4)
        self.assertEqual(overall["grade"], "D")

    def test_overall_health_empty(self):
        overall = compute_overall_health([])
        self.assertEqual(overall["total"], 0)
        self.assertEqual(overall["score"], 0.0)
        self.assertEqual(overall["grade"], "F")


# ─── Тест с патчем реестра по умолчанию ─────────────────────────────────────────


class TestPatchedRegistry(unittest.TestCase):
    def test_run_uses_patched_default_registry(self):
        fake_reg = [
            ("p1", "T1", make_adapter("p1", apy=0.05)),
            ("p2", "T2", make_adapter("p2", apy=0.08)),
        ]
        with mock.patch.object(orch, "ADAPTER_REGISTRY", fake_reg):
            res = run_orchestrator(write=False, now_fn=fixed_now)
        self.assertEqual(res.summary["total"], 2)
        self.assertEqual(res.summary["ok"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
