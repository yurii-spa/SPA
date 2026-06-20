"""Tests for spa_core.paper_trading.adaptive_scheduler (MP-1576 / Improvement 1).

20 unit tests across:
  - TestDecideCadence          (8)
  - TestMaxPositionWeight      (4)
  - TestDecideFromState        (4)
  - TestRunAndCLI              (4)

Run:
  python3 -m unittest spa_core.tests.test_adaptive_scheduler -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.paper_trading.adaptive_scheduler import (
    MODE_EMERGENCY,
    MODE_NORMAL,
    MODE_RELAXED,
    MODE_TIGHT,
    INTERVAL_MINUTES,
    CadenceDecision,
    decide_cadence,
    decide_from_state,
    max_position_weight_pct,
    run,
    main,
)


class TestDecideCadence(unittest.TestCase):
    def test_emergency_on_high_drawdown(self):
        d = decide_cadence(drawdown_pct=2.5, max_position_pct=10, volatility_pct=0.1)
        self.assertEqual(d.mode, MODE_EMERGENCY)
        self.assertEqual(d.interval_minutes, 30)

    def test_emergency_takes_priority_over_tight(self):
        # both drawdown and position trip — emergency wins
        d = decide_cadence(drawdown_pct=5.0, max_position_pct=40, volatility_pct=2.0)
        self.assertEqual(d.mode, MODE_EMERGENCY)

    def test_tight_on_position_over_cap(self):
        d = decide_cadence(drawdown_pct=0.5, max_position_pct=36, volatility_pct=1.0)
        self.assertEqual(d.mode, MODE_TIGHT)
        self.assertEqual(d.interval_minutes, 60)

    def test_relaxed_on_low_vol_no_concentration(self):
        d = decide_cadence(drawdown_pct=0.1, max_position_pct=20, volatility_pct=0.2)
        self.assertEqual(d.mode, MODE_RELAXED)
        self.assertEqual(d.interval_minutes, 240)

    def test_normal_when_vol_high_but_nothing_else(self):
        d = decide_cadence(drawdown_pct=0.1, max_position_pct=20, volatility_pct=1.0)
        self.assertEqual(d.mode, MODE_NORMAL)
        self.assertEqual(d.interval_minutes, 1440)

    def test_normal_when_position_near_limit_blocks_relax(self):
        # low vol but position above NEAR_LIMIT (30) → not relaxed, not tight
        d = decide_cadence(drawdown_pct=0.1, max_position_pct=32, volatility_pct=0.1)
        self.assertEqual(d.mode, MODE_NORMAL)

    def test_boundary_drawdown_exactly_threshold_not_emergency(self):
        # strictly greater-than → 2.0 exactly is NOT emergency
        d = decide_cadence(drawdown_pct=2.0, max_position_pct=10, volatility_pct=1.0)
        self.assertNotEqual(d.mode, MODE_EMERGENCY)

    def test_handles_garbage_inputs(self):
        d = decide_cadence(drawdown_pct="x", max_position_pct=None, volatility_pct=[])
        self.assertIn(d.mode, INTERVAL_MINUTES)
        self.assertEqual(d.interval_minutes, INTERVAL_MINUTES[d.mode])


class TestMaxPositionWeight(unittest.TestCase):
    def test_basic_weight(self):
        pct = max_position_weight_pct({"a": 40, "b": 60})
        self.assertAlmostEqual(pct, 60.0, places=4)

    def test_empty_returns_zero(self):
        self.assertEqual(max_position_weight_pct({}), 0.0)

    def test_invalid_type_returns_zero(self):
        self.assertEqual(max_position_weight_pct(None), 0.0)

    def test_ignores_nonpositive(self):
        pct = max_position_weight_pct({"a": 0, "b": 100, "c": -5})
        self.assertAlmostEqual(pct, 100.0, places=4)


class TestDecideFromState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)

    def _write(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_missing_files_degrade_to_normal(self):
        d = decide_from_state(self.dir)
        self.assertEqual(d.mode, MODE_NORMAL)

    def test_tight_from_status_positions(self):
        self._write("paper_trading_status.json",
                    {"current_positions": {"compound_v3": 40000, "aave_v3": 60000}})
        self._write("equity_curve_daily.json",
                    {"summary": {"daily_volatility_pct": 1.0}, "daily": []})
        d = decide_from_state(self.dir)
        self.assertEqual(d.mode, MODE_TIGHT)

    def test_emergency_from_equity_drawdown(self):
        self._write("paper_trading_status.json",
                    {"current_positions": {"a": 50, "b": 50}})
        self._write("equity_curve_daily.json",
                    {"summary": {"daily_volatility_pct": 0.1},
                     "daily": [{"drawdown_pct": -3.5}]})
        d = decide_from_state(self.dir)
        self.assertEqual(d.mode, MODE_EMERGENCY)

    def test_positions_fallback_to_equity_bar(self):
        # no status positions; positions live on the latest equity bar
        self._write("equity_curve_daily.json",
                    {"summary": {"daily_volatility_pct": 1.0},
                     "daily": [{"drawdown_pct": -0.1,
                                "positions": {"x": 50, "y": 50}}]})
        d = decide_from_state(self.dir)
        # 50/50 → max 50% > 35 → tight
        self.assertEqual(d.mode, MODE_TIGHT)


class TestRunAndCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)

    def test_run_writes_file(self):
        d = run(data_dir=self.dir, write=True)
        out = self.dir / "adaptive_schedule.json"
        self.assertTrue(out.exists())
        saved = json.loads(out.read_text())
        self.assertEqual(saved["mode"], d.mode)

    def test_run_no_write(self):
        run(data_dir=self.dir, write=False)
        self.assertFalse((self.dir / "adaptive_schedule.json").exists())

    def test_decision_to_dict_roundtrip(self):
        d = CadenceDecision(mode=MODE_NORMAL, interval_minutes=1440, reason="x")
        self.assertEqual(d.to_dict()["interval_minutes"], 1440)

    def test_main_check_exit_zero(self):
        rc = main(["--check", "--data-dir", str(self.dir)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
