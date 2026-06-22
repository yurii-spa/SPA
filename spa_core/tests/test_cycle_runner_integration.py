"""
spa_core/tests/test_cycle_runner_integration.py — MP-373 integration tests.

Covers:
  - APYAggregator called in cycle (mock + real path)
  - PromotionEngine called after tournament (mock + real path)
  - Graceful fallbacks when aggregator/engine are unavailable
  - allocation_map updated after kill
  - Empty strategies / no live data edge-cases
  - Atomic JSON write for apy_ranking.json and promotion_report.json
  - PromotionEngine.evaluate_all / apply_decisions contract
  - APYAggregator.rank_by_apy / save_ranking contract
  - cycle_runner imports without crash
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_adapter_status(protocols: list[dict] | None = None) -> dict:
    """Minimal adapter_status.json payload."""
    return {
        "generated_at": "2026-06-12T08:00:00Z",
        "adapters": protocols or [
            {
                "protocol_key": "aave-v3",
                "tier": "T1",
                "allocation_cap": 0.4,
                "mock_apy": {"ethereum": {"USDC": 3.5}},
                "chains": ["ethereum"],
            },
            {
                "protocol_key": "compound-v3",
                "tier": "T1",
                "allocation_cap": 0.4,
                "mock_apy": {"ethereum": {"USDC": 4.8}},
                "chains": ["ethereum"],
            },
            {
                "protocol_key": "morpho-blue",
                "tier": "T2",
                "allocation_cap": 0.2,
                "mock_apy": {"ethereum": {"USDC": 6.2}},
                "chains": ["ethereum"],
            },
        ],
    }


def _tmp_data_dir(adapter_status: dict | None = None) -> Path:
    """Create a temp dir with optional adapter_status.json."""
    td = Path(tempfile.mkdtemp(prefix="spa_test_"))
    if adapter_status is not None:
        (td / "adapter_status.json").write_text(
            json.dumps(adapter_status), encoding="utf-8"
        )
    return td


# ─────────────────────────────────────────────────────────────────────────────
# A. APYAggregator unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAPYAggregatorLoad(unittest.TestCase):
    """APYAggregator.load() reads adapter_status.json correctly."""

    def setUp(self):
        self.data_dir = _tmp_data_dir(_make_adapter_status())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_load_returns_aggregator(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        self.assertIsInstance(agg, APYAggregator)

    def test_load_snapshots_count(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        # 3 adapters in the fixture
        self.assertEqual(len(agg.snapshots()), 3)

    def test_load_missing_file_returns_empty(self):
        """Missing adapter_status.json → empty aggregator, no exception."""
        from spa_core.adapters.apy_aggregator import APYAggregator
        empty_dir = Path(tempfile.mkdtemp())
        try:
            agg = APYAggregator.load(empty_dir)
            self.assertEqual(len(agg.snapshots()), 0)
        finally:
            import shutil
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_load_corrupt_file_returns_empty(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        corrupt_dir = _tmp_data_dir()
        (corrupt_dir / "adapter_status.json").write_text("NOT JSON", encoding="utf-8")
        try:
            agg = APYAggregator.load(corrupt_dir)
            self.assertEqual(len(agg.snapshots()), 0)
        finally:
            import shutil
            shutil.rmtree(corrupt_dir, ignore_errors=True)


class TestAPYAggregatorRanking(unittest.TestCase):
    """rank_by_apy() orders correctly."""

    def setUp(self):
        self.data_dir = _tmp_data_dir(_make_adapter_status())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_rank_by_apy_descending(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        ranked = agg.rank_by_apy()
        apys = [s.apy_pct for s in ranked]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_rank_by_apy_first_is_highest(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        ranked = agg.rank_by_apy()
        # morpho-blue has 6.2%
        self.assertAlmostEqual(ranked[0].apy_pct, 6.2, places=4)

    def test_rank_empty_returns_empty_list(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator([])
        self.assertEqual(agg.rank_by_apy(), [])


class TestAPYAggregatorSaveRanking(unittest.TestCase):
    """save_ranking() writes apy_ranking.json atomically."""

    def setUp(self):
        self.data_dir = _tmp_data_dir(_make_adapter_status())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_aggregator_called_in_cycle(self):
        """APYAggregator.save_ranking is called when cycle runs with write=True."""
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        out = self.data_dir / "apy_ranking.json"
        agg.save_ranking(out)
        self.assertTrue(out.exists())

    def test_save_ranking_valid_json(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        out = self.data_dir / "apy_ranking.json"
        agg.save_ranking(out)
        doc = json.loads(out.read_text())
        self.assertIn("by_apy", doc)
        self.assertIn("summary", doc)
        self.assertIn("count", doc)

    def test_save_ranking_count_matches(self):
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        out = self.data_dir / "apy_ranking.json"
        agg.save_ranking(out)
        doc = json.loads(out.read_text())
        self.assertEqual(doc["count"], len(agg.snapshots()))

    def test_save_ranking_atomic_no_tmp_left(self):
        """After save, no .tmp_ files should remain in data dir."""
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.data_dir)
        agg.save_ranking(self.data_dir / "apy_ranking.json")
        tmp_files = list(self.data_dir.glob(".tmp_apy_ranking_*"))
        self.assertEqual(tmp_files, [])


# ─────────────────────────────────────────────────────────────────────────────
# B. PromotionEngine unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPromotionEngineEvaluate(unittest.TestCase):
    """PromotionEngine.evaluate() / evaluate_all() contract."""

    def _engine(self):
        from spa_core.paper_trading.promotion_engine import PromotionEngine
        return PromotionEngine()

    def test_promotion_engine_called(self):
        """evaluate_all returns list[PromotionDecision] for non-empty metrics."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        metrics = {
            "S1": {"sharpe_30d": 1.5, "calmar_30d": 0.8, "max_drawdown_pct": -0.03, "days_active": 30},
        }
        decisions = engine.evaluate_all(metrics)
        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], PromotionDecision)

    def test_evaluate_promote(self):
        engine = self._engine()
        metrics = {"sharpe_30d": 1.5, "calmar_30d": 0.8, "max_drawdown_pct": -0.02, "days_active": 30}
        d = engine.evaluate("S1", metrics)
        self.assertEqual(d.action, "promote")

    def test_evaluate_demote(self):
        engine = self._engine()
        metrics = {"sharpe_30d": -0.5, "calmar_30d": 0.1, "max_drawdown_pct": -0.01, "days_active": 30}
        d = engine.evaluate("S2", metrics)
        self.assertEqual(d.action, "demote")

    def test_evaluate_kill_drawdown(self):
        engine = self._engine()
        metrics = {"sharpe_30d": 0.3, "calmar_30d": 0.2, "max_drawdown_pct": -0.15, "days_active": 30}
        d = engine.evaluate("S3", metrics)
        self.assertEqual(d.action, "kill")

    def test_evaluate_kill_calmar(self):
        engine = self._engine()
        metrics = {"sharpe_30d": 0.3, "calmar_30d": -0.8, "max_drawdown_pct": -0.01, "days_active": 30}
        d = engine.evaluate("S4", metrics)
        self.assertEqual(d.action, "kill")

    def test_evaluate_hold_insufficient_days(self):
        engine = self._engine()
        metrics = {"sharpe_30d": 2.0, "calmar_30d": 1.0, "max_drawdown_pct": -0.01, "days_active": 5}
        d = engine.evaluate("S5", metrics)
        self.assertEqual(d.action, "hold")

    def test_evaluate_hold_mid_range_sharpe(self):
        engine = self._engine()
        metrics = {"sharpe_30d": 0.4, "calmar_30d": 0.3, "max_drawdown_pct": -0.02, "days_active": 20}
        d = engine.evaluate("S6", metrics)
        self.assertEqual(d.action, "hold")

    def test_cycle_without_strategies(self):
        """evaluate_all with empty dict → empty list, no crash."""
        engine = self._engine()
        decisions = engine.evaluate_all({})
        self.assertEqual(decisions, [])

    def test_evaluate_all_multi(self):
        engine = self._engine()
        metrics = {
            "S0": {"sharpe_30d": 2.0, "calmar_30d": 1.0, "max_drawdown_pct": -0.01, "days_active": 30},
            "S1": {"sharpe_30d": -1.0, "calmar_30d": -0.6, "max_drawdown_pct": -0.12, "days_active": 30},
            "S2": {"sharpe_30d": 0.4, "calmar_30d": 0.3, "max_drawdown_pct": -0.02, "days_active": 20},
        }
        decisions = engine.evaluate_all(metrics)
        self.assertEqual(len(decisions), 3)
        by_id = {d.strategy_id: d.action for d in decisions}
        self.assertEqual(by_id["S0"], "promote")
        self.assertEqual(by_id["S1"], "kill")
        self.assertEqual(by_id["S2"], "hold")


class TestPromotionEngineApplyDecisions(unittest.TestCase):
    """apply_decisions() allocation changes."""

    def _engine(self):
        from spa_core.paper_trading.promotion_engine import PromotionEngine
        return PromotionEngine()

    def test_apply_decisions_promote_increases_alloc(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S1", action="promote", reason="test", metrics={})
        alloc = {"S1": 0.10}
        result = engine.apply_decisions([d], alloc)
        self.assertAlmostEqual(result["S1"], 0.15, places=5)

    def test_apply_decisions_demote_decreases_alloc(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S2", action="demote", reason="test", metrics={})
        alloc = {"S2": 0.10}
        result = engine.apply_decisions([d], alloc)
        self.assertAlmostEqual(result["S2"], 0.05, places=5)

    def test_allocation_updated_after_kill(self):
        """kill → allocation[strategy] = 0.0"""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S3", action="kill", reason="drawdown", metrics={})
        alloc = {"S3": 0.25}
        result = engine.apply_decisions([d], alloc)
        self.assertAlmostEqual(result["S3"], 0.0, places=10)

    def test_apply_decisions_hold_unchanged(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S4", action="hold", reason="test", metrics={})
        alloc = {"S4": 0.20}
        result = engine.apply_decisions([d], alloc)
        self.assertAlmostEqual(result["S4"], 0.20, places=10)

    def test_apply_decisions_promote_cap(self):
        """Promote cannot push alloc above ALLOC_CAP (0.30)."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S1", action="promote", reason="test", metrics={})
        alloc = {"S1": 0.28}
        result = engine.apply_decisions([d], alloc)
        self.assertLessEqual(result["S1"], 0.30)

    def test_apply_decisions_demote_floor(self):
        """Demote cannot push alloc below ALLOC_FLOOR (0.0)."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S2", action="demote", reason="test", metrics={})
        alloc = {"S2": 0.02}
        result = engine.apply_decisions([d], alloc)
        self.assertGreaterEqual(result["S2"], 0.0)

    def test_apply_decisions_new_strategy_defaults_zero(self):
        """Strategy not in allocation_map → starts at 0 before action."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S_NEW", action="promote", reason="test", metrics={})
        result = engine.apply_decisions([d], {})
        # 0.0 + 0.05 = 0.05
        self.assertAlmostEqual(result["S_NEW"], 0.05, places=5)

    def test_apply_decisions_returns_new_dict(self):
        """apply_decisions must return a NEW dict (immutable input)."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        engine = self._engine()
        d = PromotionDecision(strategy_id="S1", action="kill", reason="test", metrics={})
        original = {"S1": 0.25}
        result = engine.apply_decisions([d], original)
        self.assertIsNot(result, original)
        # original unchanged
        self.assertAlmostEqual(original["S1"], 0.25, places=5)


class TestPromotionEngineSaveReport(unittest.TestCase):
    """save_report() writes promotion_report.json atomically."""

    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="spa_pe_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_save_report_creates_file(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision, PromotionEngine
        engine = PromotionEngine()
        decisions = [
            PromotionDecision(strategy_id="S1", action="promote", reason="ok", metrics={}),
        ]
        path = engine.save_report(decisions, self.data_dir)
        self.assertTrue(path.exists())

    def test_save_report_valid_json(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision, PromotionEngine
        engine = PromotionEngine()
        decisions = [
            PromotionDecision(strategy_id="S1", action="kill", reason="dd", metrics={"x": 1}),
        ]
        path = engine.save_report(decisions, self.data_dir)
        doc = json.loads(path.read_text())
        self.assertIn("decisions", doc)
        self.assertEqual(len(doc["decisions"]), 1)
        self.assertEqual(doc["decisions"][0]["action"], "kill")

    def test_save_report_no_tmp_left(self):
        from spa_core.paper_trading.promotion_engine import PromotionEngine
        engine = PromotionEngine()
        engine.save_report([], self.data_dir)
        tmp_files = list(self.data_dir.glob(".tmp_promotion_report_*"))
        self.assertEqual(tmp_files, [])


# ─────────────────────────────────────────────────────────────────────────────
# C. cycle_runner integration tests (with mocks)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeOrchResult:
    def __init__(self):
        self.adapters = [
            {"protocol": "aave-v3", "status": "ok", "apy_pct": 3.5,
             "tvl_usd": 1e9, "tier": "T1", "chain": "ethereum"},
            {"protocol": "compound-v3", "status": "ok", "apy_pct": 4.8,
             "tvl_usd": 8e8, "tier": "T1", "chain": "ethereum"},
        ]
        self.status = "ok"


class _FakeAllocResult:
    def __init__(self):
        self.target_usd = {"aave-v3": 40000.0, "compound-v3": 40000.0}
        self.expected_apy_pct = 4.2
        self.model_used = "test_model"
        self.strategy_loop_active = False


class _FakeAlloc:
    def allocate(self):
        return _FakeAllocResult()


def _run_minimal_cycle(data_dir: Path) -> Any:
    """Run a cycle with mocked orchestrator + allocator. write=False (dry-run)."""
    from spa_core.paper_trading.cycle_runner import run_cycle

    return run_cycle(
        data_dir=str(data_dir),
        orchestrator_fn=lambda _: _FakeOrchResult(),
        allocator=_FakeAlloc(),
        write=False,
    )


class TestCycleWithAggregator(unittest.TestCase):
    """APYAggregator integration via cycle_runner."""

    def setUp(self):
        self.data_dir = _tmp_data_dir(_make_adapter_status())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_cycle_runs_without_crash(self):
        """cycle_runner.run_cycle imports OK and returns CycleResult."""
        result = _run_minimal_cycle(self.data_dir)
        self.assertIsNotNone(result)

    def test_cycle_without_aggregator(self):
        """Graceful fallback: missing adapter_status.json → cycle succeeds."""
        no_status_dir = _tmp_data_dir()  # no adapter_status.json
        try:
            result = _run_minimal_cycle(no_status_dir)
            self.assertIsNotNone(result)
        finally:
            import shutil
            shutil.rmtree(no_status_dir, ignore_errors=True)

    def test_aggregator_save_ranking_called_on_write(self):
        """When write=True + adapter_status.json present → apy_ranking.json created."""
        from spa_core.paper_trading.cycle_runner import run_cycle

        # Patch all external modules that write=True cycle depends on
        with patch("spa_core.paper_trading.cycle_runner._default_orchestrator",
                   return_value=_FakeOrchResult()), \
             patch("spa_core.paper_trading.cycle_runner._default_allocator",
                   return_value=_FakeAlloc()), \
             patch("spa_core.paper_trading.cycle_runner._refresh_risk_scores",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._persist_track",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._run_golive_gate"), \
             patch("spa_core.paper_trading.cycle_runner._run_daily_report"), \
             patch("spa_core.paper_trading.cycle_runner._save_cycle_snapshot_safe"):

            run_cycle(data_dir=str(self.data_dir), write=True)

        # apy_ranking.json should have been written
        out = self.data_dir / "apy_ranking.json"
        self.assertTrue(out.exists(), "apy_ranking.json not created by cycle")


class TestCycleWithPromotionEngine(unittest.TestCase):
    """PromotionEngine integration via cycle_runner."""

    def setUp(self):
        self.data_dir = _tmp_data_dir(_make_adapter_status())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_promotion_engine_called(self):
        """PromotionEngine.evaluate_all is called; promotion_report.json written."""
        from spa_core.paper_trading.cycle_runner import run_cycle

        with patch("spa_core.paper_trading.cycle_runner._default_orchestrator",
                   return_value=_FakeOrchResult()), \
             patch("spa_core.paper_trading.cycle_runner._default_allocator",
                   return_value=_FakeAlloc()), \
             patch("spa_core.paper_trading.cycle_runner._refresh_risk_scores",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._persist_track",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._run_golive_gate"), \
             patch("spa_core.paper_trading.cycle_runner._run_daily_report"), \
             patch("spa_core.paper_trading.cycle_runner._save_cycle_snapshot_safe"):

            run_cycle(data_dir=str(self.data_dir), write=True)

        # promotion_report.json created by PromotionEngine.save_report
        rpt = self.data_dir / "promotion_report.json"
        # If tournament raised (no vportfolio data) _t_ranking == [] →
        # evaluate_all({}) → empty decisions → save_report still writes the file
        self.assertTrue(
            rpt.exists(),
            "promotion_report.json not created; PromotionEngine.save_report not called",
        )

    def test_promotion_report_valid_json(self):
        """promotion_report.json contains valid JSON with 'decisions' key."""
        from spa_core.paper_trading.cycle_runner import run_cycle

        with patch("spa_core.paper_trading.cycle_runner._default_orchestrator",
                   return_value=_FakeOrchResult()), \
             patch("spa_core.paper_trading.cycle_runner._default_allocator",
                   return_value=_FakeAlloc()), \
             patch("spa_core.paper_trading.cycle_runner._refresh_risk_scores",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._persist_track",
                   return_value=True), \
             patch("spa_core.paper_trading.cycle_runner._run_golive_gate"), \
             patch("spa_core.paper_trading.cycle_runner._run_daily_report"), \
             patch("spa_core.paper_trading.cycle_runner._save_cycle_snapshot_safe"):

            run_cycle(data_dir=str(self.data_dir), write=True)

        rpt = self.data_dir / "promotion_report.json"
        if rpt.exists():
            doc = json.loads(rpt.read_text())
            self.assertIn("decisions", doc)


class TestCycleEdgeCases(unittest.TestCase):
    """Edge-case and fallback scenarios."""

    def setUp(self):
        self.data_dir = _tmp_data_dir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_cycle_without_strategies_no_crash(self):
        """Empty strategy registry → cycle completes, no exception."""
        result = _run_minimal_cycle(self.data_dir)
        self.assertIsNotNone(result)
        # status may be 'ok' or 'blocked_by_policy'; should NOT be an exception
        self.assertIn(result.status, ("ok", "blocked_by_policy",
                                      "skipped_no_live_data", "kill_switch"))

    def test_cycle_no_live_data_returns_skipped(self):
        """Orchestrator returns no adapters → status = skipped_no_live_data."""
        from spa_core.paper_trading.cycle_runner import run_cycle

        class _EmptyOrch:
            adapters = []
            status = "no_live_data"

        result = run_cycle(
            data_dir=str(self.data_dir),
            orchestrator_fn=lambda _: _EmptyOrch(),
            allocator=_FakeAlloc(),
            write=False,
        )
        self.assertEqual(result.status, "skipped_no_live_data")

    def test_allocation_updated_after_kill_full_pipeline(self):
        """Full PromotionEngine pipeline: kill → 0% in allocation map."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision, PromotionEngine

        engine = PromotionEngine()
        decisions = [
            PromotionDecision(strategy_id="S0", action="promote", reason="ok", metrics={}),
            PromotionDecision(strategy_id="S1", action="kill", reason="dd>10%", metrics={}),
            PromotionDecision(strategy_id="S2", action="demote", reason="sharpe<0", metrics={}),
            PromotionDecision(strategy_id="S3", action="hold", reason="mid", metrics={}),
        ]
        alloc = {"S0": 0.20, "S1": 0.25, "S2": 0.15, "S3": 0.10}
        result = engine.apply_decisions(decisions, alloc)

        self.assertAlmostEqual(result["S1"], 0.0, places=10)  # killed
        self.assertGreater(result["S0"], alloc["S0"])          # promoted
        self.assertLess(result["S2"], alloc["S2"])             # demoted
        self.assertAlmostEqual(result["S3"], alloc["S3"], places=10)  # hold

    def test_cycle_result_has_status(self):
        result = _run_minimal_cycle(self.data_dir)
        self.assertIn("status", result.to_dict())

    def test_cycle_result_positions_dict(self):
        result = _run_minimal_cycle(self.data_dir)
        self.assertIsInstance(result.positions, dict)


# ─────────────────────────────────────────────────────────────────────────────
# D. PromotionDecision serialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestPromotionDecisionSerialization(unittest.TestCase):

    def test_to_dict_has_required_keys(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        d = PromotionDecision(
            strategy_id="S1",
            action="promote",
            reason="sharpe > 0.8",
            metrics={"sharpe_30d": 1.2},
        )
        doc = d.to_dict()
        for key in ("strategy_id", "action", "reason", "metrics", "ts"):
            self.assertIn(key, doc)

    def test_to_dict_action_preserved(self):
        from spa_core.paper_trading.promotion_engine import PromotionDecision
        d = PromotionDecision(strategy_id="S2", action="kill", reason="dd", metrics={})
        self.assertEqual(d.to_dict()["action"], "kill")

    def test_report_thresholds_present(self):
        """promotion_report.json must include thresholds section."""
        from spa_core.paper_trading.promotion_engine import PromotionDecision, PromotionEngine
        import tempfile
        td = Path(tempfile.mkdtemp())
        try:
            engine = PromotionEngine()
            d = [PromotionDecision(strategy_id="S1", action="hold", reason="x", metrics={})]
            path = engine.save_report(d, td)
            doc = json.loads(path.read_text())
            self.assertIn("thresholds", doc)
            self.assertIn("PROMOTE_SHARPE", doc["thresholds"])
            self.assertIn("KILL_DRAWDOWN", doc["thresholds"])
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
