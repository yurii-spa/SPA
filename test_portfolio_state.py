#!/usr/bin/env python3
"""Тесты Portfolio State Tracker (SPA-V389).

Сетевых вызовов нет, файлы пишутся во временный каталог. pytest в репо не
установлен, поэтому тесты на ``unittest`` (stdlib)::

    python3 -m unittest spa_core.tests.test_portfolio_state -v
    python3 spa_core/tests/test_portfolio_state.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.portfolio.drift_calculator import (
    calculate_drift,
    portfolio_drift_score,
)
from spa_core.portfolio.rebalance_signal import generate_signals
from spa_core.portfolio.state_tracker import (
    PortfolioPosition,
    PortfolioStateTracker,
)


def balanced_positions() -> list[PortfolioPosition]:
    """4 позиции точно на цели (дрейф 0)."""
    return [
        PortfolioPosition(p, 20000.0, 20000.0, 0.20, 0.20)
        for p in ("morpho_blue", "yearn_v3", "euler_v2", "maple")
    ]


def write_target(path: Path) -> None:
    payload = {
        "target_weights": {"a": 0.2, "b": 0.2, "c": 0.2, "d": 0.2},
        "target_usd": {"a": 20000.0, "b": 20000.0, "c": 20000.0, "d": 20000.0},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ─── Drift ────────────────────────────────────────────────────────────────────


class TestDrift(unittest.TestCase):
    def test_drift_zero_when_balanced(self):
        drifts = calculate_drift(balanced_positions())
        for d in drifts:
            self.assertAlmostEqual(d.drift_pct, 0.0, places=9)
            self.assertAlmostEqual(d.drift_usd, 0.0, places=2)
            self.assertFalse(d.needs_rebalance)

    def test_drift_score_zero_when_balanced(self):
        score = portfolio_drift_score(calculate_drift(balanced_positions()))
        self.assertEqual(score, 0.0)

    def test_drift_calculation_values(self):
        # перевес: actual 0.30 vs target 0.20 → drift +0.10, $+10000
        pos = [PortfolioPosition("x", 30000.0, 20000.0, 0.30, 0.20)]
        d = calculate_drift(pos)[0]
        self.assertAlmostEqual(d.drift_pct, 0.10, places=9)
        self.assertAlmostEqual(d.drift_usd, 10000.0, places=2)
        self.assertTrue(d.needs_rebalance)

    def test_drift_below_threshold_no_rebalance(self):
        # дрейф 3% < 5% порога
        pos = [PortfolioPosition("x", 23000.0, 20000.0, 0.23, 0.20)]
        d = calculate_drift(pos)[0]
        self.assertFalse(d.needs_rebalance)

    def test_custom_threshold(self):
        pos = [PortfolioPosition("x", 23000.0, 20000.0, 0.23, 0.20)]
        d = calculate_drift(pos, threshold=0.02)[0]
        self.assertTrue(d.needs_rebalance)

    def test_drift_score_nonzero(self):
        pos = [
            PortfolioPosition("a", 30000.0, 20000.0, 0.30, 0.20),  # +0.10
            PortfolioPosition("b", 10000.0, 20000.0, 0.10, 0.20),  # -0.10
        ]
        score = portfolio_drift_score(calculate_drift(pos))
        self.assertAlmostEqual(score, 0.10, places=6)

    def test_drift_score_empty(self):
        self.assertEqual(portfolio_drift_score([]), 0.0)


# ─── Rebalance signals ──────────────────────────────────────────────────────────


class TestRebalanceSignals(unittest.TestCase):
    def test_signal_high_priority_overweight_sells(self):
        # перевес 12% → HIGH, SELL, usd_delta < 0
        pos = [PortfolioPosition("x", 32000.0, 20000.0, 0.32, 0.20)]
        sig = generate_signals(calculate_drift(pos))[0]
        self.assertEqual(sig.action, "SELL")
        self.assertEqual(sig.priority, "HIGH")
        self.assertLess(sig.usd_delta, 0)

    def test_signal_buy_when_underweight(self):
        # недовес 12% → BUY, usd_delta > 0
        pos = [PortfolioPosition("x", 8000.0, 20000.0, 0.08, 0.20)]
        sig = generate_signals(calculate_drift(pos))[0]
        self.assertEqual(sig.action, "BUY")
        self.assertGreater(sig.usd_delta, 0)
        self.assertEqual(sig.priority, "HIGH")

    def test_signal_medium_priority(self):
        # дрейф 6% → MEDIUM (≥5%, <10%)
        pos = [PortfolioPosition("x", 26000.0, 20000.0, 0.26, 0.20)]
        sig = generate_signals(calculate_drift(pos))[0]
        self.assertEqual(sig.priority, "MEDIUM")
        self.assertEqual(sig.action, "SELL")

    def test_signal_hold_when_balanced(self):
        sig = generate_signals(calculate_drift(balanced_positions()))
        for s in sig:
            self.assertEqual(s.action, "HOLD")
            self.assertEqual(s.priority, "LOW")
            self.assertEqual(s.usd_delta, 0.0)

    def test_min_trade_usd_filter(self):
        # дрейф 6% по весу, но всего $300 → ниже min_trade_usd=500 → HOLD
        pos = [PortfolioPosition("x", 5300.0, 5000.0, 0.26, 0.20)]
        sig = generate_signals(calculate_drift(pos), min_trade_usd=500)[0]
        self.assertEqual(sig.action, "HOLD")

    def test_min_trade_usd_allows_large(self):
        pos = [PortfolioPosition("x", 32000.0, 20000.0, 0.32, 0.20)]
        sig = generate_signals(calculate_drift(pos), min_trade_usd=500)[0]
        self.assertNotEqual(sig.action, "HOLD")


# ─── State tracker ───────────────────────────────────────────────────────────────


class TestStateTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "portfolio_state.json"
        self.target = self.dir / "target_allocation.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_from_target_when_no_state(self):
        write_target(self.target)
        tracker = PortfolioStateTracker(state_path=self.state, target_path=self.target)
        positions = tracker.load_state()
        self.assertEqual(len(positions), 4)
        # mock-старт: actual == target
        for p in positions:
            self.assertAlmostEqual(p.actual_usd, p.target_usd, places=2)
            self.assertAlmostEqual(p.actual_weight, p.target_weight, places=9)

    def test_load_empty_when_no_target_no_state(self):
        tracker = PortfolioStateTracker(
            state_path=self.dir / "nope.json", target_path=self.dir / "none.json"
        )
        self.assertEqual(tracker.load_state(), [])

    def test_atomic_save_and_reload(self):
        write_target(self.target)
        tracker = PortfolioStateTracker(state_path=self.state, target_path=self.target)
        positions = tracker.load_state()
        # сдвигаем одну позицию и сохраняем
        positions[0].actual_usd = 25000.0
        positions[0].actual_weight = 0.25
        tracker.save_state(positions)
        self.assertTrue(self.state.exists())
        # никаких .tmp-хвостов рядом
        leftovers = list(self.dir.glob("*.tmp"))
        self.assertEqual(leftovers, [])
        reloaded = tracker.load_state()
        self.assertAlmostEqual(reloaded[0].actual_usd, 25000.0, places=2)

    def test_save_writes_valid_json_with_totals(self):
        tracker = PortfolioStateTracker(state_path=self.state, target_path=self.target)
        tracker.save_state(balanced_positions())
        data = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(data["num_positions"], 4)
        self.assertAlmostEqual(data["total_actual_usd"], 80000.0, places=2)
        self.assertEqual(data["execution_mode"], "read_only_simulation")

    def test_snapshot_structure(self):
        tracker = PortfolioStateTracker(state_path=self.state, target_path=self.target)
        tracker.save_state(balanced_positions())
        snap = tracker.snapshot()
        self.assertIn("positions", snap)
        self.assertIn("generated_at", snap)
        self.assertEqual(len(snap["positions"]), 4)

    def test_state_takes_precedence_over_target(self):
        # state есть → грузим его, а не инициализируем из target
        write_target(self.target)
        tracker = PortfolioStateTracker(state_path=self.state, target_path=self.target)
        custom = [PortfolioPosition("solo", 100.0, 100.0, 1.0, 1.0)]
        tracker.save_state(custom)
        loaded = tracker.load_state()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].protocol, "solo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
