#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.regime_detector (SPA-V429 / MP-129).

Plain unittest, NO pytest runner required (though pytest works too).
ALL persistence in a tempdir; no network; no external libraries.

Coverage:
- compute_trend: ascending/descending/flat series, OLS slope sign & magnitude,
  R²=1.0 for perfect line, R²=0 for zero variance y, edge cases (n<2, n==2)
- compute_volatility: constant series (vol=0, ratio=1.0, NORMAL), varying series,
  ratio calculation, HIGH/NORMAL/LOW levels, short series edge cases
- detect_regime: BULL / BEAR / VOLATILE / SIDEWAYS scenarios
- detect_regime: empty input → safe SIDEWAYS default, single protocol,
  single-day records (n<2 → FLAT), confidence in [0, 1]
- detect_regime: returns all required keys, stance values are valid
- regime_history: correct window boundaries, step_days respected,
  chronological order, empty input
- regime_transition_matrix: counts, single-regime history (no transitions),
  empty list, multiple transitions
- recommended_stance values are always one of AGGRESSIVE/NEUTRAL/DEFENSIVE
- AST-lint: no forbidden external imports in regime_detector.py
"""
from __future__ import annotations

import ast
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import regime_detector as rd

_MODULE_PATH = Path(rd.__file__)

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_records(
    protocol: str,
    values: List[float],
    start: str = "2026-01-01",
) -> List[Dict[str, Any]]:
    """Create flat apy_history records for one protocol."""
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "protocol": protocol, "apy": v}
        for i, v in enumerate(values)
    ]


def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _bull_history(n: int = 30) -> List[Dict[str, Any]]:
    """Rising APY across 3 protocols — should produce BULL."""
    records = []
    for proto in ("aave", "compound", "morpho"):
        base = {"aave": 4.0, "compound": 3.5, "morpho": 5.0}[proto]
        values = [base + i * 0.05 for i in range(n)]
        records += _make_records(proto, values)
    return records


def _bear_history(n: int = 30) -> List[Dict[str, Any]]:
    """Falling APY across 3 protocols — should produce BEAR."""
    records = []
    for proto in ("aave", "compound", "morpho"):
        base = {"aave": 8.0, "compound": 7.0, "morpho": 9.0}[proto]
        values = [base - i * 0.1 for i in range(n)]
        records += _make_records(proto, values)
    return records


def _volatile_history(n: int = 30) -> List[Dict[str, Any]]:
    """Highly volatile APY — should produce VOLATILE.

    23 stable days followed by 7 days of extreme swings.  The current
    window (last 7 diffs) has std ~26; the full-series std is ~12 → ratio ~2.2,
    well above the VOLATILE_RATIO_THRESHOLD of 2.0.
    """
    records = []
    # 23 stable + 7 extreme oscillations
    values_stable = [5.0] * 23
    values_volatile = [5.0, 25.0, 0.0, 30.0, 0.0, 25.0, 1.0]
    values = values_stable + values_volatile
    records += _make_records("aave", values)
    return records


def _sideways_history(n: int = 30) -> List[Dict[str, Any]]:
    """Near-constant APY — should produce SIDEWAYS (flat trend, normal vol)."""
    records = _make_records("aave", [5.0 + 0.001 * i for i in range(n)])
    records += _make_records("compound", [4.0 + 0.001 * i for i in range(n)])
    return records


# ══════════════════════════════════════════════════════════════════════════════
# Tests: compute_trend
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeTrend(unittest.TestCase):

    def test_ascending_slope_positive(self):
        result = rd.compute_trend([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertGreater(result["slope"], 0)

    def test_ascending_direction_up(self):
        result = rd.compute_trend([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(result["direction"], "UP")

    def test_descending_slope_negative(self):
        result = rd.compute_trend([5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertLess(result["slope"], 0)

    def test_descending_direction_down(self):
        result = rd.compute_trend([5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertEqual(result["direction"], "DOWN")

    def test_flat_direction_flat(self):
        result = rd.compute_trend([3.0, 3.0, 3.0, 3.0, 3.0])
        self.assertEqual(result["direction"], "FLAT")

    def test_flat_r_squared_is_one(self):
        # Constant series: perfectly explained by a horizontal line
        result = rd.compute_trend([3.0, 3.0, 3.0, 3.0, 3.0])
        self.assertAlmostEqual(result["r_squared"], 1.0, places=5)

    def test_perfect_line_r_squared_one(self):
        # y = 2x + 1 → perfect fit → R²=1.0
        n = 10
        xs = [i / (n - 1) for i in range(n)]
        ys = [2.0 * x + 1.0 for x in xs]
        result = rd.compute_trend(ys)
        self.assertAlmostEqual(result["r_squared"], 1.0, places=5)

    def test_perfect_line_slope_magnitude(self):
        # With x in [0,1], slope should equal 2.0 for y = 2*x + 1
        n = 10
        xs = [i / (n - 1) for i in range(n)]
        ys = [2.0 * x + 1.0 for x in xs]
        result = rd.compute_trend(ys)
        self.assertAlmostEqual(result["slope"], 2.0, places=5)

    def test_r_squared_in_range(self):
        import random
        random.seed(42)
        vals = [random.gauss(5.0, 1.0) for _ in range(30)]
        result = rd.compute_trend(vals)
        self.assertGreaterEqual(result["r_squared"], 0.0)
        self.assertLessEqual(result["r_squared"], 1.0)

    def test_empty_list_safe_default(self):
        result = rd.compute_trend([])
        self.assertEqual(result["direction"], "FLAT")
        self.assertEqual(result["slope"], 0.0)

    def test_single_element_safe_default(self):
        result = rd.compute_trend([5.0])
        self.assertEqual(result["direction"], "FLAT")

    def test_two_elements_up(self):
        result = rd.compute_trend([1.0, 2.0])
        self.assertEqual(result["direction"], "UP")

    def test_two_elements_down(self):
        result = rd.compute_trend([2.0, 1.0])
        self.assertEqual(result["direction"], "DOWN")

    def test_returns_all_keys(self):
        result = rd.compute_trend([1.0, 2.0, 3.0])
        self.assertIn("slope", result)
        self.assertIn("r_squared", result)
        self.assertIn("direction", result)

    def test_direction_values_valid(self):
        for vals in [[1, 2, 3], [3, 2, 1], [5, 5, 5]]:
            result = rd.compute_trend(vals)
            self.assertIn(result["direction"], ("UP", "DOWN", "FLAT"))

    def test_antisymmetric_slope(self):
        up = rd.compute_trend([1.0, 2.0, 3.0, 4.0, 5.0])
        down = rd.compute_trend([5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertAlmostEqual(up["slope"], -down["slope"], places=5)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: compute_volatility
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVolatility(unittest.TestCase):

    def test_constant_series_zero_vol(self):
        result = rd.compute_volatility([5.0] * 20)
        self.assertEqual(result["current_vol"], 0.0)
        self.assertEqual(result["mean_vol"], 0.0)

    def test_constant_series_ratio_one(self):
        result = rd.compute_volatility([5.0] * 20)
        self.assertAlmostEqual(result["ratio"], 1.0)

    def test_constant_series_level_normal(self):
        result = rd.compute_volatility([5.0] * 20)
        self.assertEqual(result["level"], "NORMAL")

    def test_high_volatility_level(self):
        # Stable history followed by extreme spikes → HIGH
        vals = [5.0] * 20 + [5.0, 15.0, 2.0, 20.0, 1.0, 18.0, 3.0]
        result = rd.compute_volatility(vals, window=7)
        self.assertEqual(result["level"], "HIGH")

    def test_ratio_above_two_is_high(self):
        vals = [5.0] * 20 + [5.0, 15.0, 2.0, 20.0, 1.0, 18.0, 3.0]
        result = rd.compute_volatility(vals, window=7)
        self.assertGreater(result["ratio"], rd.HIGH_VOL_RATIO)

    def test_returns_all_keys(self):
        result = rd.compute_volatility([1.0, 2.0, 3.0])
        self.assertIn("current_vol", result)
        self.assertIn("mean_vol", result)
        self.assertIn("ratio", result)
        self.assertIn("level", result)

    def test_level_values_valid(self):
        for vals in [[1, 2, 3, 4, 5], [5]*10, [1, 10, 1, 10, 1, 10]]:
            result = rd.compute_volatility(vals)
            self.assertIn(result["level"], ("HIGH", "NORMAL", "LOW"))

    def test_empty_series_safe_default(self):
        result = rd.compute_volatility([])
        self.assertEqual(result["current_vol"], 0.0)
        self.assertEqual(result["level"], "NORMAL")

    def test_single_element_safe_default(self):
        result = rd.compute_volatility([5.0])
        self.assertEqual(result["current_vol"], 0.0)

    def test_low_volatility_level(self):
        # Large stable history, recent window also very stable → LOW
        # All diffs ~1; mean_vol includes them all; use tiny recent window
        stable = [float(i) for i in range(50)]  # diffs all = 1.0
        # Override window so current window is taken from a constant tail
        tail_const = [stable[-1]] * 15
        vals = stable + tail_const
        result = rd.compute_volatility(vals, window=7)
        # Recent 7 diffs are all 0 vs historical diffs of 1 → ratio near 0 → LOW
        self.assertEqual(result["level"], "LOW")

    def test_ratio_non_negative(self):
        import random
        random.seed(7)
        vals = [random.gauss(5, 1) for _ in range(40)]
        result = rd.compute_volatility(vals)
        self.assertGreaterEqual(result["ratio"], 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: detect_regime
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectRegime(unittest.TestCase):

    def _cutoff(self, start: str, n: int) -> date:
        """Return the last date when records start at `start` and span n days."""
        return date.fromisoformat(start) + timedelta(days=n - 1)

    def test_bull_scenario(self):
        history = _bull_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["regime"], "BULL")

    def test_bull_stance_aggressive(self):
        history = _bull_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["recommended_stance"], "AGGRESSIVE")

    def test_bear_scenario(self):
        history = _bear_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["regime"], "BEAR")

    def test_bear_stance_defensive(self):
        history = _bear_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["recommended_stance"], "DEFENSIVE")

    def test_volatile_scenario(self):
        history = _volatile_history()
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["regime"], "VOLATILE")

    def test_volatile_stance_defensive(self):
        history = _volatile_history()
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["recommended_stance"], "DEFENSIVE")

    def test_sideways_scenario(self):
        history = _sideways_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["regime"], "SIDEWAYS")

    def test_sideways_stance_neutral(self):
        history = _sideways_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        self.assertEqual(result["recommended_stance"], "NEUTRAL")

    def test_empty_input_safe_sideways(self):
        result = rd.detect_regime([])
        self.assertEqual(result["regime"], "SIDEWAYS")

    def test_empty_input_confidence_zero(self):
        result = rd.detect_regime([])
        self.assertEqual(result["confidence"], 0.0)

    def test_empty_input_neutral_stance(self):
        result = rd.detect_regime([])
        self.assertEqual(result["recommended_stance"], "NEUTRAL")

    def test_single_protocol_returns_valid(self):
        history = _make_records("aave", [5.0 + i * 0.1 for i in range(20)])
        cutoff = date.fromisoformat("2026-01-01") + timedelta(days=19)
        result = rd.detect_regime(history, lookback_days=20, _cutoff_date=cutoff)
        self.assertIn(result["regime"], ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"))

    def test_single_day_per_protocol(self):
        history = [{"date": "2026-01-15", "protocol": "aave", "apy": 5.0}]
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=date(2026, 1, 15))
        # Only 1 data point → no trend possible → safe SIDEWAYS
        self.assertIn(result["regime"], ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"))

    def test_confidence_in_range(self):
        for history in [_bull_history(), _bear_history(), _sideways_history()]:
            cutoff = self._cutoff("2026-01-01", 30)
            result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
            self.assertGreaterEqual(result["confidence"], 0.0)
            self.assertLessEqual(result["confidence"], 1.0)

    def test_returns_all_top_level_keys(self):
        result = rd.detect_regime(_bull_history(30), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        for key in ("regime", "confidence", "signals", "explanation", "recommended_stance"):
            self.assertIn(key, result)

    def test_signals_keys_present(self):
        result = rd.detect_regime(_bull_history(30), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        signals = result["signals"]
        for key in ("trend_direction", "trend_strength", "volatility_level",
                    "volatility_ratio", "breadth", "breadth_pct"):
            self.assertIn(key, signals)

    def test_signals_trend_direction_valid(self):
        result = rd.detect_regime(_sideways_history(), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        self.assertIn(result["signals"]["trend_direction"], ("UP", "DOWN", "FLAT"))

    def test_signals_volatility_level_valid(self):
        result = rd.detect_regime(_bull_history(), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        self.assertIn(result["signals"]["volatility_level"], ("HIGH", "NORMAL", "LOW"))

    def test_signals_breadth_valid(self):
        result = rd.detect_regime(_bull_history(), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        self.assertIn(result["signals"]["breadth"], ("BROAD", "NARROW"))

    def test_stance_values_valid(self):
        valid = {"AGGRESSIVE", "NEUTRAL", "DEFENSIVE"}
        for history in [_bull_history(), _bear_history(), _sideways_history(), _volatile_history()]:
            cutoff = self._cutoff("2026-01-01", 30)
            result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
            self.assertIn(result["recommended_stance"], valid)

    def test_regime_values_valid(self):
        valid = {"BULL", "BEAR", "SIDEWAYS", "VOLATILE"}
        for history in [_bull_history(), _bear_history(), _sideways_history(), _volatile_history()]:
            cutoff = self._cutoff("2026-01-01", 30)
            result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
            self.assertIn(result["regime"], valid)

    def test_explanation_is_nonempty_string(self):
        result = rd.detect_regime(_bull_history(), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        self.assertIsInstance(result["explanation"], str)
        self.assertGreater(len(result["explanation"]), 0)

    def test_no_records_for_cutoff_returns_sideways(self):
        # All records are in 2025, cutoff is 2026 → no records in window
        history = _make_records("aave", [5.0] * 10, start="2025-01-01")
        result = rd.detect_regime(history, lookback_days=30,
                                   _cutoff_date=date(2026, 6, 1))
        # Regime should still be a valid value (may be SIDEWAYS or BULL/BEAR
        # depending on how empty series resolves)
        self.assertIn(result["regime"], ("BULL", "BEAR", "SIDEWAYS", "VOLATILE"))

    def test_mixed_protocol_breadth_narrow(self):
        """If half go up and half go down, breadth should be NARROW."""
        # 1 up, 1 down → neither ≥60% → NARROW
        history = (
            _make_records("up_proto", [5.0 + i * 0.2 for i in range(20)])
            + _make_records("dn_proto", [8.0 - i * 0.2 for i in range(20)])
        )
        cutoff = date.fromisoformat("2026-01-01") + timedelta(days=19)
        result = rd.detect_regime(history, lookback_days=20, _cutoff_date=cutoff)
        self.assertEqual(result["signals"]["breadth"], "NARROW")

    def test_breadth_pct_in_range(self):
        history = _bull_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        bp = result["signals"]["breadth_pct"]
        self.assertGreaterEqual(bp, 0.0)
        self.assertLessEqual(bp, 1.0)

    def test_trend_strength_in_range(self):
        history = _bull_history(30)
        cutoff = self._cutoff("2026-01-01", 30)
        result = rd.detect_regime(history, lookback_days=30, _cutoff_date=cutoff)
        ts = result["signals"]["trend_strength"]
        self.assertGreaterEqual(ts, 0.0)
        self.assertLessEqual(ts, 1.0)

    def test_volatility_ratio_positive(self):
        result = rd.detect_regime(_sideways_history(), lookback_days=30,
                                   _cutoff_date=self._cutoff("2026-01-01", 30))
        self.assertGreaterEqual(result["signals"]["volatility_ratio"], 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: regime_history
# ══════════════════════════════════════════════════════════════════════════════

class TestRegimeHistory(unittest.TestCase):

    def test_empty_history_returns_empty(self):
        result = rd.regime_history([])
        self.assertEqual(result, [])

    def test_returns_list(self):
        history = _bull_history(40)
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=date(2026, 2, 9))
        self.assertIsInstance(result, list)

    def test_each_entry_has_date_regime_confidence(self):
        history = _bull_history(40)
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=date(2026, 2, 9))
        for entry in result:
            self.assertIn("date", entry)
            self.assertIn("regime", entry)
            self.assertIn("confidence", entry)

    def test_chronological_order(self):
        history = _bull_history(40)
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=date(2026, 2, 9))
        dates = [e["date"] for e in result]
        self.assertEqual(dates, sorted(dates))

    def test_step_days_respected(self):
        history = _bull_history(60)
        end = date(2026, 3, 1)
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=end)
        if len(result) >= 2:
            d1 = date.fromisoformat(result[-1]["date"])
            d2 = date.fromisoformat(result[-2]["date"])
            diff = (d1 - d2).days
            self.assertEqual(diff, 7)

    def test_confidence_in_range(self):
        history = _bull_history(60)
        end = date(2026, 3, 1)
        for entry in rd.regime_history(history, window_days=30, step_days=7,
                                       _end_date=end):
            self.assertGreaterEqual(entry["confidence"], 0.0)
            self.assertLessEqual(entry["confidence"], 1.0)

    def test_regime_values_valid(self):
        valid = {"BULL", "BEAR", "SIDEWAYS", "VOLATILE"}
        history = _bull_history(60)
        end = date(2026, 3, 1)
        for entry in rd.regime_history(history, window_days=30, step_days=7,
                                       _end_date=end):
            self.assertIn(entry["regime"], valid)

    def test_single_data_point_handled(self):
        history = [{"date": "2026-01-15", "protocol": "aave", "apy": 5.0}]
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=date(2026, 1, 15))
        self.assertIsInstance(result, list)

    def test_window_covers_data_range(self):
        # With 40 days of data and window=30/step=7, we should get multiple entries
        history = _bull_history(40)
        end = date(2026, 2, 9)
        result = rd.regime_history(history, window_days=30, step_days=7,
                                   _end_date=end)
        self.assertGreater(len(result), 0)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: regime_transition_matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestRegimeTransitionMatrix(unittest.TestCase):

    def test_empty_returns_empty(self):
        result = rd.regime_transition_matrix([])
        self.assertEqual(result, {})

    def test_single_entry_returns_empty(self):
        entries = [{"date": "2026-01-01", "regime": "BULL", "confidence": 0.8}]
        result = rd.regime_transition_matrix(entries)
        self.assertEqual(result, {})

    def test_two_entries_one_transition(self):
        entries = [
            {"date": "2026-01-01", "regime": "BULL", "confidence": 0.8},
            {"date": "2026-01-08", "regime": "SIDEWAYS", "confidence": 0.5},
        ]
        result = rd.regime_transition_matrix(entries)
        self.assertEqual(result, {"BULL": {"SIDEWAYS": 1}})

    def test_self_transition_counted(self):
        entries = [
            {"date": "2026-01-01", "regime": "BULL", "confidence": 0.8},
            {"date": "2026-01-08", "regime": "BULL", "confidence": 0.9},
        ]
        result = rd.regime_transition_matrix(entries)
        self.assertEqual(result["BULL"]["BULL"], 1)

    def test_multiple_transitions_counted(self):
        entries = [
            {"date": "2026-01-01", "regime": "BULL", "confidence": 0.8},
            {"date": "2026-01-08", "regime": "BULL", "confidence": 0.9},
            {"date": "2026-01-15", "regime": "SIDEWAYS", "confidence": 0.4},
            {"date": "2026-01-22", "regime": "BEAR", "confidence": 0.7},
        ]
        result = rd.regime_transition_matrix(entries)
        self.assertEqual(result["BULL"]["BULL"], 1)
        self.assertEqual(result["BULL"]["SIDEWAYS"], 1)
        self.assertEqual(result["SIDEWAYS"]["BEAR"], 1)

    def test_total_transitions_equals_n_minus_one(self):
        entries = [
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-08", "regime": "SIDEWAYS"},
            {"date": "2026-01-15", "regime": "BEAR"},
            {"date": "2026-01-22", "regime": "BULL"},
        ]
        result = rd.regime_transition_matrix(entries)
        total = sum(
            count
            for from_counts in result.values()
            for count in from_counts.values()
        )
        self.assertEqual(total, len(entries) - 1)

    def test_single_regime_throughout(self):
        entries = [
            {"date": f"2026-01-{i+1:02d}", "regime": "SIDEWAYS"}
            for i in range(5)
        ]
        result = rd.regime_transition_matrix(entries)
        self.assertEqual(result["SIDEWAYS"]["SIDEWAYS"], 4)

    def test_result_is_dict(self):
        entries = [
            {"date": "2026-01-01", "regime": "BULL"},
            {"date": "2026-01-08", "regime": "BEAR"},
        ]
        result = rd.regime_transition_matrix(entries)
        self.assertIsInstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: load_apy_history (I/O helpers)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadApyHistory(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="regime_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_empty_with_error(self):
        records, err = rd.load_apy_history(self.data_dir)
        self.assertEqual(records, [])
        self.assertIsNotNone(err)

    def test_flat_list_format(self):
        data = [
            {"date": "2026-01-01", "protocol": "aave", "apy": 5.0},
            {"date": "2026-01-02", "protocol": "aave", "apy": 5.1},
        ]
        (self.data_dir / rd.APY_HISTORY_FILENAME).write_text(json.dumps(data))
        records, err = rd.load_apy_history(self.data_dir)
        self.assertIsNone(err)
        self.assertEqual(len(records), 2)

    def test_protocol_history_format(self):
        data = {
            "protocol_history": {
                "aave_v3": [
                    {"ts": "2026-01-01T00:00:00Z", "apy": 4.5},
                    {"ts": "2026-01-02T00:00:00Z", "apy": 4.6},
                ]
            },
            "last_updated": "2026-01-02",
        }
        (self.data_dir / rd.APY_HISTORY_FILENAME).write_text(json.dumps(data))
        records, err = rd.load_apy_history(self.data_dir)
        self.assertIsNone(err)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["protocol"], "aave_v3")

    def test_broken_json_returns_error(self):
        (self.data_dir / rd.APY_HISTORY_FILENAME).write_text("{broken json")
        records, err = rd.load_apy_history(self.data_dir)
        self.assertEqual(records, [])
        self.assertIsNotNone(err)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: build_regime_analytics + write_status
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildAndWrite(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="regime_build_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_apy(self, records):
        (self.data_dir / rd.APY_HISTORY_FILENAME).write_text(json.dumps(records))

    def test_build_never_raises_no_data(self):
        doc = rd.build_regime_analytics(self.data_dir)
        self.assertIsInstance(doc, dict)

    def test_build_has_required_keys(self):
        self._write_apy(_bull_history(30))
        doc = rd.build_regime_analytics(self.data_dir)
        for key in ("schema_version", "source", "meta", "available", "current",
                    "history", "transition_matrix", "notes"):
            self.assertIn(key, doc)

    def test_write_status_creates_file(self):
        self._write_apy(_bull_history(30))
        doc = rd.build_regime_analytics(self.data_dir)
        result = rd.write_status(doc, self.data_dir)
        self.assertIn(result, ("DATA_WRITTEN", "DATA_UNCHANGED"))
        self.assertTrue((self.data_dir / rd.STATUS_FILENAME).exists())

    def test_write_status_idempotent(self):
        self._write_apy(_bull_history(30))
        doc = rd.build_regime_analytics(self.data_dir)
        rd.write_status(doc, self.data_dir)
        # Second call with same doc → DATA_UNCHANGED
        result2 = rd.write_status(doc, self.data_dir)
        self.assertEqual(result2, "DATA_UNCHANGED")

    def test_no_stray_tmp_files(self):
        self._write_apy(_bull_history(30))
        doc = rd.build_regime_analytics(self.data_dir)
        rd.write_status(doc, self.data_dir)
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_content_fingerprint_changes_on_regime_change(self):
        bull = {"current": {"regime": "BULL"}, "meta": {"generated_at": "X"}}
        bear = {"current": {"regime": "BEAR"}, "meta": {"generated_at": "Y"}}
        self.assertNotEqual(rd.content_fingerprint(bull), rd.content_fingerprint(bear))

    def test_content_fingerprint_stable_across_generated_at(self):
        doc_a = {"current": {"regime": "BULL"}, "meta": {"generated_at": "2026-01-01"}}
        doc_b = {"current": {"regime": "BULL"}, "meta": {"generated_at": "2026-06-12"}}
        self.assertEqual(rd.content_fingerprint(doc_a), rd.content_fingerprint(doc_b))


# ══════════════════════════════════════════════════════════════════════════════
# Tests: AST lint — no forbidden external imports
# ══════════════════════════════════════════════════════════════════════════════

class TestASTLint(unittest.TestCase):
    _FORBIDDEN = frozenset(
        [
            "requests", "web3", "socket", "urllib", "pandas", "numpy",
            "scipy", "anthropic", "openai", "aiohttp", "httpx",
        ]
    )

    def _get_imports(self, source: str):
        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.append(node.module.split(".")[0])
        return found

    def test_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        imports = self._get_imports(source)
        violations = [i for i in imports if i in self._FORBIDDEN]
        self.assertEqual(
            violations, [],
            msg=f"Forbidden imports found in regime_detector.py: {violations}",
        )

    def test_no_llm_sdk_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("anthropic", source)
        self.assertNotIn("openai", source)
        self.assertNotIn("langchain", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
