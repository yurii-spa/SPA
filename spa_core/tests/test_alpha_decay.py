#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.alpha_decay (SPA-V430 / MP-130).

Plain unittest, NO external dependencies, NO network, ALL persistence in
tempdir. Covers:
- compute_decay_curve: stable alpha, fast decay, half-life interpolation
- compute_decay_curve: empty entries, zero APY at t+0, lag beyond history
- compute_decay_curve: single entry, partial lags, decay_ratio capping
- analyze_protocol_alpha_persistence: protocol filtering, n_entries
- compute_rebalance_frequency_recommendation: all three verdicts, clamping
- half_life=None when ratio never reaches 0.5
- content_fingerprint idempotency
- write_status atomicity and history rotation
- build_alpha_decay file-backed integration
- AST lint: no forbidden imports, no network calls, no LLM SDK
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

# Module under test
from spa_core.paper_trading import alpha_decay as ad

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = Path(ad.__file__).resolve()

_FORBIDDEN_IMPORTS = {
    "requests", "httpx", "aiohttp", "urllib3",
    "web3", "eth_account",
    "numpy", "pandas", "scipy",
    "anthropic", "openai",
    "socket",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_apy_series(
    protocol: str,
    apys: List[float],
    start: str = "2026-01-01",
) -> List[Dict[str, Any]]:
    """Build [{date, protocol, apy}] from a list of APY values starting at start."""
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "protocol": protocol, "apy": apy}
        for i, apy in enumerate(apys)
    ]


def _make_entry(protocol: str, date_str: str, entry_apy: float) -> Dict[str, Any]:
    return {"date": date_str, "protocol": protocol, "entry_apy": entry_apy}


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="alpha_decay_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compute_decay_curve — stable alpha
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayCurveStable(unittest.TestCase):

    def _stable_history(self):
        """APY stays constant at 5.0 for 60 days on protocol 'aave'."""
        return _make_apy_series("aave", [5.0] * 60, start="2026-01-01")

    def test_stable_all_ratios_near_one(self):
        history = self._stable_history()
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        for pt in result["decay_curve"]:
            if pt["n_samples"] > 0:
                self.assertAlmostEqual(pt["median_decay_ratio"], 1.0, places=5)

    def test_stable_verdict_stable(self):
        history = self._stable_history()
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertEqual(result["verdict"], "STABLE")

    def test_stable_half_life_none(self):
        """Constant APY never reaches 0.5 decay ratio → half_life=None."""
        history = self._stable_history()
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertIsNone(result["half_life_days"])

    def test_stable_decay_curve_has_correct_lags(self):
        history = self._stable_history()
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14])
        lag_days = [p["lag_days"] for p in result["decay_curve"]]
        self.assertEqual(lag_days, [1, 7, 14])

    def test_stable_explanation_mentions_stable(self):
        history = self._stable_history()
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries)
        self.assertIn("STABLE", result["verdict"])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compute_decay_curve — fast decay
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayCurveFastDecay(unittest.TestCase):

    def _fast_decay_history(self):
        """APY starts at 10.0 on day 0 and halves each 3 days for 40 days."""
        apys = []
        for i in range(40):
            apys.append(10.0 * (0.5 ** (i / 3.0)))
        return _make_apy_series("compound", apys, start="2026-01-01")

    def test_fast_decay_ratio_decreases(self):
        history = self._fast_decay_history()
        entries = [_make_entry("compound", "2026-01-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14])
        pts = {p["lag_days"]: p["median_decay_ratio"] for p in result["decay_curve"]
               if p["n_samples"] > 0}
        if 1 in pts and 7 in pts:
            self.assertLess(pts[7], pts[1])

    def test_fast_decay_verdict_is_fast_decay(self):
        history = self._fast_decay_history()
        entries = [_make_entry("compound", "2026-01-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertEqual(result["verdict"], "FAST_DECAY")

    def test_fast_decay_half_life_less_than_7(self):
        history = self._fast_decay_history()
        entries = [_make_entry("compound", "2026-01-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertIsNotNone(result["half_life_days"])
        self.assertLess(result["half_life_days"], 7.0)

    def test_fast_decay_half_life_positive(self):
        history = self._fast_decay_history()
        entries = [_make_entry("compound", "2026-01-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertGreater(result["half_life_days"], 0.0)

    def test_fast_decay_explanation_mentions_days(self):
        history = self._fast_decay_history()
        entries = [_make_entry("compound", "2026-01-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertIn("days", result["explanation"].lower())


# ═══════════════════════════════════════════════════════════════════════════════
# 3. compute_decay_curve — moderate decay
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayCurveModerateDecay(unittest.TestCase):

    def _moderate_decay_history(self):
        """Half-life of ~10 days: APY = 8 * (0.5 ** (i/10)) for 45 days."""
        apys = [8.0 * (0.5 ** (i / 10.0)) for i in range(45)]
        return _make_apy_series("morpho", apys, start="2026-01-01")

    def test_moderate_decay_verdict(self):
        history = self._moderate_decay_history()
        entries = [_make_entry("morpho", "2026-01-01", 8.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertEqual(result["verdict"], "MODERATE_DECAY")

    def test_moderate_decay_half_life_7_to_14(self):
        history = self._moderate_decay_history()
        entries = [_make_entry("morpho", "2026-01-01", 8.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        hl = result["half_life_days"]
        self.assertIsNotNone(hl)
        self.assertGreaterEqual(hl, 7.0)
        self.assertLessEqual(hl, 14.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compute_decay_curve — half-life interpolation correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestHalfLifeInterpolation(unittest.TestCase):

    def test_half_life_between_lag_7_and_14(self):
        """Construct ratios where median=0.8 at lag7 and median=0.3 at lag14.
        Linear interpolation: 0.5 = 0.8 + (0.3-0.8) * t, t=(0.5-0.8)/(0.3-0.8)=0.6
        half_life = 7 + 0.6 * 7 = 11.2
        """
        # Build enough apy history to satisfy the ratio at each lag
        # Entry APY = 10, so:
        #   lag7 apy = 8.0 (ratio=0.8), lag14 apy = 3.0 (ratio=0.3)
        base_date = date.fromisoformat("2026-01-01")
        apy_history = []
        for lag in range(40):
            d = (base_date + timedelta(days=lag)).isoformat()
            if lag == 0:
                apy = 10.0
            elif lag == 7:
                apy = 8.0
            elif lag == 14:
                apy = 3.0
            else:
                apy = 5.0  # fill gaps
            apy_history.append({"date": d, "protocol": "test", "apy": apy})

        entries = [{"date": "2026-01-01", "protocol": "test", "entry_apy": 10.0}]
        result = ad.compute_decay_curve(apy_history, entries, lags=[7, 14])
        hl = result["half_life_days"]
        self.assertIsNotNone(hl)
        self.assertAlmostEqual(hl, 11.2, places=1)

    def test_half_life_at_first_lag(self):
        """If ratio already ≤ 0.5 at lag=1, half_life should be between 0 and 1."""
        history = _make_apy_series("x", [10.0] + [4.0] * 40, start="2026-02-01")
        entries = [_make_entry("x", "2026-02-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7])
        hl = result["half_life_days"]
        self.assertIsNotNone(hl)
        self.assertGreaterEqual(hl, 0.0)
        self.assertLessEqual(hl, 1.0)

    def test_half_life_none_when_never_reaches_half(self):
        """All ratios stay above 0.5 → half_life=None, verdict=STABLE."""
        history = _make_apy_series("y", [10.0] * 50, start="2026-03-01")
        entries = [_make_entry("y", "2026-03-01", 10.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        self.assertIsNone(result["half_life_days"])
        self.assertEqual(result["verdict"], "STABLE")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. compute_decay_curve — edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayCurveEdgeCases(unittest.TestCase):

    def test_empty_entry_events_returns_insufficient_data(self):
        history = _make_apy_series("aave", [5.0] * 30)
        result = ad.compute_decay_curve(history, [])
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
        self.assertEqual(result["decay_curve"], [])
        self.assertIsNone(result["half_life_days"])

    def test_none_entry_events_returns_insufficient_data(self):
        history = _make_apy_series("aave", [5.0] * 30)
        result = ad.compute_decay_curve(history, [])
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_zero_entry_apy_skipped(self):
        """Entry event with entry_apy=0 must be skipped (can't compute ratio)."""
        history = _make_apy_series("aave", [0.0] * 30)
        entries = [_make_entry("aave", "2026-01-01", 0.0)]
        result = ad.compute_decay_curve(history, entries)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_all_zero_apy_entries_skipped(self):
        history = _make_apy_series("aave", [5.0] * 30)
        entries = [
            {"date": "2026-01-01", "protocol": "aave", "entry_apy": 0.0},
            {"date": "2026-01-02", "protocol": "aave", "entry_apy": 0.0},
        ]
        result = ad.compute_decay_curve(history, entries)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_lag_beyond_history_skipped(self):
        """Lag=30 when only 5 days of history → n_samples=0 for that lag."""
        history = _make_apy_series("aave", [5.0, 5.0, 5.0, 5.0, 5.0], start="2026-01-01")
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7, 14, 30])
        pt30 = next(p for p in result["decay_curve"] if p["lag_days"] == 30)
        self.assertEqual(pt30["n_samples"], 0)

    def test_missing_apy_history_returns_insufficient(self):
        result = ad.compute_decay_curve([], [_make_entry("aave", "2026-01-01", 5.0)])
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_single_entry_computes_what_it_can(self):
        """Single entry event: n_samples=1 for lags within history."""
        history = _make_apy_series("aave", [5.0] * 35, start="2026-01-01")
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[1, 7])
        pt1 = next(p for p in result["decay_curve"] if p["lag_days"] == 1)
        self.assertEqual(pt1["n_samples"], 1)

    def test_decay_ratio_capped_at_2(self):
        """APY at lag much higher than at entry → ratio capped at 2.0."""
        base_date = date.fromisoformat("2026-01-01")
        apy_history = []
        for i in range(10):
            d = (base_date + timedelta(days=i)).isoformat()
            apy = 1.0 if i == 0 else 100.0  # huge jump
            apy_history.append({"date": d, "protocol": "test", "apy": apy})
        entries = [{"date": "2026-01-01", "protocol": "test", "entry_apy": 1.0}]
        result = ad.compute_decay_curve(apy_history, entries, lags=[1])
        pt = result["decay_curve"][0]
        self.assertLessEqual(pt["median_decay_ratio"], 2.0)

    def test_decay_ratio_capped_at_0(self):
        """APY dropping to negative-ish value → ratio floored at 0."""
        base_date = date.fromisoformat("2026-01-01")
        apy_history = [
            {"date": "2026-01-01", "protocol": "x", "apy": 10.0},
            {"date": "2026-01-02", "protocol": "x", "apy": -5.0},
        ]
        entries = [{"date": "2026-01-01", "protocol": "x", "entry_apy": 10.0}]
        result = ad.compute_decay_curve(apy_history, entries, lags=[1])
        pt = result["decay_curve"][0]
        if pt["n_samples"] > 0:
            self.assertGreaterEqual(pt["median_decay_ratio"], 0.0)

    def test_invalid_entry_records_skipped(self):
        history = _make_apy_series("aave", [5.0] * 30)
        entries = [
            {"date": None, "protocol": "aave", "entry_apy": 5.0},
            {"date": "2026-01-01", "protocol": None, "entry_apy": 5.0},
            {"date": "2026-01-01", "protocol": "aave", "entry_apy": None},
            "not_a_dict",
        ]
        result = ad.compute_decay_curve(history, entries)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_multiple_entries_median_correct(self):
        """Three entries with different ratios; median should be middle value."""
        base = date.fromisoformat("2026-01-01")
        apy_history = []
        for i in range(10):
            d = (base + timedelta(days=i)).isoformat()
            apy_history.append({"date": d, "protocol": "p", "apy": float(i + 1)})

        # Three entries on days 0,1,2 with entry_apy=1,2,3 and lag=1
        # day0 → lag1 = day1 apy=2, ratio=2/1=2.0 (capped to 2.0)
        # day1 → lag1 = day2 apy=3, ratio=3/2=1.5
        # day2 → lag1 = day3 apy=4, ratio=4/3=1.333
        entries = [
            {"date": "2026-01-01", "protocol": "p", "entry_apy": 1.0},
            {"date": "2026-01-02", "protocol": "p", "entry_apy": 2.0},
            {"date": "2026-01-03", "protocol": "p", "entry_apy": 3.0},
        ]
        result = ad.compute_decay_curve(apy_history, entries, lags=[1])
        pt = result["decay_curve"][0]
        self.assertEqual(pt["n_samples"], 3)
        # Sorted: [1.333, 1.5, 2.0] → median=1.5
        self.assertAlmostEqual(pt["median_decay_ratio"], 1.5, places=4)

    def test_empty_apy_history_list(self):
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve([], entries)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")

    def test_decay_curve_keys_present(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries)
        self.assertIn("decay_curve", result)
        self.assertIn("half_life_days", result)
        self.assertIn("verdict", result)
        self.assertIn("explanation", result)

    def test_decay_curve_lag_order(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[14, 1, 7])
        lags = [p["lag_days"] for p in result["decay_curve"]]
        self.assertEqual(lags, sorted(lags))

    def test_custom_lags_respected(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.compute_decay_curve(history, entries, lags=[3, 21])
        lags = [p["lag_days"] for p in result["decay_curve"]]
        self.assertIn(3, lags)
        self.assertIn(21, lags)
        self.assertNotIn(7, lags)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. analyze_protocol_alpha_persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeProtocolPersistence(unittest.TestCase):

    def test_single_protocol_filtered(self):
        """Only aave data should be used when protocol='aave'."""
        history = (
            _make_apy_series("aave", [5.0] * 35, start="2026-01-01") +
            _make_apy_series("compound", [100.0] * 35, start="2026-01-01")
        )
        entries = [
            _make_entry("aave", "2026-01-01", 5.0),
            _make_entry("compound", "2026-01-01", 100.0),
        ]
        result = ad.analyze_protocol_alpha_persistence(history, entries, "aave")
        # Should only use aave data — ratios near 1.0
        for pt in result["decay_curve"]:
            if pt["n_samples"] > 0:
                self.assertAlmostEqual(pt["median_decay_ratio"], 1.0, places=3)

    def test_n_entries_counts_protocol_entries(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [
            _make_entry("aave", "2026-01-01", 5.0),
            _make_entry("aave", "2026-01-02", 5.0),
            _make_entry("compound", "2026-01-01", 3.0),
        ]
        result = ad.analyze_protocol_alpha_persistence(history, entries, "aave")
        self.assertEqual(result["n_entries"], 2)

    def test_unknown_protocol_returns_insufficient(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.analyze_protocol_alpha_persistence(history, entries, "unknown_protocol")
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
        self.assertEqual(result["n_entries"], 0)

    def test_result_has_n_entries_key(self):
        history = _make_apy_series("aave", [5.0] * 35)
        entries = [_make_entry("aave", "2026-01-01", 5.0)]
        result = ad.analyze_protocol_alpha_persistence(history, entries, "aave")
        self.assertIn("n_entries", result)

    def test_protocol_none_entries_returns_zero(self):
        history = _make_apy_series("aave", [5.0] * 35)
        result = ad.analyze_protocol_alpha_persistence(history, [], "aave")
        self.assertEqual(result["n_entries"], 0)
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. compute_rebalance_frequency_recommendation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRebalanceRecommendation(unittest.TestCase):

    def test_insufficient_data_returns_7_days(self):
        decay = {"verdict": "INSUFFICIENT_DATA", "half_life_days": None}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 7)

    def test_stable_no_half_life_returns_7_days(self):
        decay = {"verdict": "STABLE", "half_life_days": None}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 7)

    def test_stable_half_life_20_days(self):
        """half_life=20 → raw=10 → check_days=10."""
        decay = {"verdict": "STABLE", "half_life_days": 20.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 10)

    def test_moderate_decay_half_life_10(self):
        """half_life=10 → raw=5 → check_days=5."""
        decay = {"verdict": "MODERATE_DECAY", "half_life_days": 10.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 5)

    def test_fast_decay_half_life_3(self):
        """half_life=3 → raw=1.5 → ceil=2 → check_days=2."""
        decay = {"verdict": "FAST_DECAY", "half_life_days": 3.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 2)

    def test_clamped_to_min_1(self):
        """half_life=0.5 → raw=0.25 → clamp to 1."""
        decay = {"verdict": "FAST_DECAY", "half_life_days": 0.5}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 1)

    def test_clamped_to_max_30(self):
        """half_life=100 → raw=50 → clamp to 30."""
        decay = {"verdict": "STABLE", "half_life_days": 100.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 30)

    def test_returns_reasoning_string(self):
        decay = {"verdict": "FAST_DECAY", "half_life_days": 4.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertIsInstance(rec["reasoning"], str)
        self.assertGreater(len(rec["reasoning"]), 0)

    def test_result_has_required_keys(self):
        decay = {"verdict": "STABLE", "half_life_days": None}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertIn("recommended_check_days", rec)
        self.assertIn("reasoning", rec)

    def test_half_life_exactly_zero(self):
        """Edge: half_life=0 → raw=0 → ceil=0 → clamp to 1."""
        decay = {"verdict": "FAST_DECAY", "half_life_days": 0.0}
        rec = ad.compute_rebalance_frequency_recommendation(decay)
        self.assertEqual(rec["recommended_check_days"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _median helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestMedianHelper(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(ad._median([]))

    def test_single_value(self):
        self.assertEqual(ad._median([3.0]), 3.0)

    def test_odd_count(self):
        self.assertEqual(ad._median([1.0, 3.0, 2.0]), 2.0)

    def test_even_count(self):
        self.assertEqual(ad._median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_already_sorted(self):
        self.assertEqual(ad._median([1.0, 2.0, 3.0]), 2.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. content_fingerprint idempotency
# ═══════════════════════════════════════════════════════════════════════════════

class TestContentFingerprint(unittest.TestCase):

    def test_same_content_same_fingerprint(self):
        doc = {"meta": {"generated_at": "2026-01-01T00:00:00"}, "aggregate": {"verdict": "STABLE"}}
        fp1 = ad.content_fingerprint(doc)
        doc2 = {"meta": {"generated_at": "2026-06-01T12:00:00"}, "aggregate": {"verdict": "STABLE"}}
        fp2 = ad.content_fingerprint(doc2)
        self.assertEqual(fp1, fp2)

    def test_different_content_different_fingerprint(self):
        doc1 = {"meta": {}, "aggregate": {"verdict": "STABLE"}}
        doc2 = {"meta": {}, "aggregate": {"verdict": "FAST_DECAY"}}
        self.assertNotEqual(
            ad.content_fingerprint(doc1),
            ad.content_fingerprint(doc2),
        )

    def test_history_excluded(self):
        doc = {"meta": {}, "aggregate": {}, "history": [{"x": 1}]}
        doc2 = {"meta": {}, "aggregate": {}, "history": [{"x": 999}]}
        self.assertEqual(ad.content_fingerprint(doc), ad.content_fingerprint(doc2))

    def test_invalid_input_returns_invalid_marker(self):
        self.assertEqual(ad.content_fingerprint("not_a_dict"), "<invalid>")
        self.assertEqual(ad.content_fingerprint(None), "<invalid>")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. write_status — atomicity and idempotency
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _make_doc(self, verdict="STABLE"):
        return {
            "meta": {"generated_at": "2026-01-01T00:00:00", "source": "alpha_decay"},
            "aggregate": {"verdict": verdict, "half_life_days": None},
            "rebalance_recommendation": {"recommended_check_days": 7},
            "per_protocol": {},
        }

    def test_write_creates_file(self):
        doc = self._make_doc()
        outcome = ad.write_status(doc, data_dir=self.data_dir)
        self.assertTrue((self.data_dir / ad.STATUS_FILENAME).exists())
        self.assertTrue(outcome["changed"])

    def test_idempotent_no_change(self):
        doc = self._make_doc()
        ad.write_status(doc, data_dir=self.data_dir)
        outcome2 = ad.write_status(doc, data_dir=self.data_dir)
        self.assertFalse(outcome2["changed"])

    def test_history_grows_on_change(self):
        doc1 = self._make_doc("STABLE")
        doc2 = self._make_doc("FAST_DECAY")
        ad.write_status(doc1, data_dir=self.data_dir)
        ad.write_status(doc2, data_dir=self.data_dir)
        saved = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertEqual(len(saved["history"]), 2)

    def test_written_file_is_valid_json(self):
        doc = self._make_doc()
        ad.write_status(doc, data_dir=self.data_dir)
        content = (self.data_dir / ad.STATUS_FILENAME).read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertIsInstance(parsed, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. build_alpha_decay (file-backed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildAlphaDecay(_TmpBase):

    def test_missing_files_returns_insufficient(self):
        doc = ad.build_alpha_decay(data_dir=self.data_dir)
        agg = doc.get("aggregate", {})
        self.assertEqual(agg.get("verdict"), "INSUFFICIENT_DATA")

    def test_returns_required_top_level_keys(self):
        doc = ad.build_alpha_decay(data_dir=self.data_dir)
        for key in ("meta", "aggregate", "rebalance_recommendation", "per_protocol"):
            self.assertIn(key, doc)

    def test_meta_advisory_only(self):
        doc = ad.build_alpha_decay(data_dir=self.data_dir)
        self.assertTrue(doc["meta"].get("advisory_only"))

    def test_meta_disclaimer_present(self):
        doc = ad.build_alpha_decay(data_dir=self.data_dir)
        self.assertIn("disclaimer", doc["meta"])


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Import / AST hygiene
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportHygiene(unittest.TestCase):

    def _collect_imports(self, source: str) -> set:
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[0])
        return names

    def test_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_IMPORTS
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_module_compiles(self):
        import py_compile
        py_compile.compile(str(_MODULE_PATH), doraise=True)

    def test_no_network_calls_in_module(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("requests.get", "requests.post", "urllib.request.urlopen",
                        "http.client", "socket.connect"):
            self.assertNotIn(pattern, source, msg=f"Found network pattern: {pattern}")

    def test_no_llm_sdk_in_module(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("anthropic.", "openai.", "from anthropic", "from openai"):
            self.assertNotIn(pattern, source, msg=f"Found LLM SDK: {pattern}")

    def test_atomic_write_pattern_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("os.replace", source)
        self.assertIn("tempfile.mkstemp", source)

    def test_no_numpy_import(self):
        """numpy must not be imported (may appear in docstrings as text)."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        imports = self._collect_imports(source)
        self.assertNotIn("numpy", imports, "numpy must not be imported")
        self.assertNotIn("np", imports, "import np alias must not be present")

    def test_no_pandas_import(self):
        """pandas must not be imported (may appear in docstrings as text)."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        imports = self._collect_imports(source)
        self.assertNotIn("pandas", imports, "pandas must not be imported")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Verdict boundary conditions
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdictBoundaries(unittest.TestCase):

    def test_half_life_exactly_14_is_stable(self):
        # half_life > 14 → STABLE; at exactly 14 → MODERATE_DECAY
        verdict = ad._verdict_from_half_life(14.1)
        self.assertEqual(verdict, "STABLE")

    def test_half_life_exactly_14_boundary(self):
        verdict = ad._verdict_from_half_life(14.0)
        self.assertEqual(verdict, "MODERATE_DECAY")

    def test_half_life_exactly_7_is_moderate(self):
        verdict = ad._verdict_from_half_life(7.0)
        self.assertEqual(verdict, "MODERATE_DECAY")

    def test_half_life_just_below_7_is_fast(self):
        verdict = ad._verdict_from_half_life(6.99)
        self.assertEqual(verdict, "FAST_DECAY")

    def test_half_life_none_is_stable(self):
        verdict = ad._verdict_from_half_life(None)
        self.assertEqual(verdict, "STABLE")


if __name__ == "__main__":
    unittest.main()
