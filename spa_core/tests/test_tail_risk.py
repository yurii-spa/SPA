#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.tail_risk (SPA-V438 / MP-119).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:

- percentile linear interpolation (empty/single/exact/mid/boundary)
- VaR = percentile of sorted returns at correct tail
- CVaR = average of worst tail slice
- Invariant: |CVaR| >= |VaR| (CVaR ≤ VaR in loss terms) across many datasets
- worst_day = min daily return
- worst_week (rolling 5 bars) — boundary at exactly 5 bars
- worst_month (rolling 21 bars) — boundary at exactly 21 bars
- population_std, skewness (symmetric=0, right/left skewed), kurtosis (normal≈0)
- tail_ratio (pos/neg, all-positive → None)
- verdict thresholds (ok < 3%, warn 3-5%, fail >= 5%, None → ok)
- build_tail_risk: available/unavailable, field completeness, is_demo propagation
- content_fingerprint excludes generated_at and history
- write_status: atomic write, idempotent (no rewrite on same content),
  history appended on change, rotation at HISTORY_MAX, broken prev tolerated
- no stray *.tmp files after write
- CLI: --check no-write, --run writes, --run twice idempotent,
  junk arg → ERROR on stderr + exit 0, --data-dir override, subprocess calls
- edge cases: missing/broken/empty JSON, no valid bars, single bar,
  bars with NaN/negative equity filtered out
- import hygiene: no forbidden imports (numpy/scipy/pandas/requests/web3/
  socket/urllib/anthropic/LLM SDK) via AST linter
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.paper_trading import tail_risk as tr

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _equity_doc(levels, *, start="2026-06-10", is_demo=False):
    """Build an equity_curve_daily-shaped doc from a list of close levels."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    daily = []
    for i, lvl in enumerate(levels):
        daily.append({
            "date": (d0 + timedelta(days=i)).isoformat(),
            "close_equity": lvl,
            "equity": lvl,
        })
    return {"daily": daily, "is_demo": is_demo, "source": "test"}


def _write_equity(data_dir: Path, doc) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / tr.EQUITY_FILENAME
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _series(levels, *, start="2026-06-10"):
    return tr.extract_equity_series(_equity_doc(levels, start=start))


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tailrisk_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Percentile / interpolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPercentile(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(tr.percentile([], 50))

    def test_single_element_any_p(self):
        for p in [0, 5, 50, 95, 99, 100]:
            with self.subTest(p=p):
                self.assertEqual(tr.percentile([-3.0], p), -3.0)

    def test_p0_is_minimum(self):
        data = [-5.0, -3.0, 0.0, 2.0, 4.0]
        self.assertAlmostEqual(tr.percentile(data, 0), -5.0)

    def test_p100_is_maximum(self):
        data = [-5.0, -3.0, 0.0, 2.0, 4.0]
        self.assertAlmostEqual(tr.percentile(data, 100), 4.0)

    def test_p50_median_odd(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(tr.percentile(data, 50), 3.0)

    def test_p50_median_even_interpolated(self):
        data = [0.0, 2.0, 4.0, 6.0]
        # idx = 0.5 * 3 = 1.5 → data[1] + 0.5*(data[2]-data[1]) = 2 + 0.5*2 = 3.0
        self.assertAlmostEqual(tr.percentile(data, 50), 3.0)

    def test_p5_linear_interpolation_two_elements(self):
        data = [-10.0, 0.0]
        # idx = 0.05 * 1 = 0.05 → -10 + 0.05*(0-(-10)) = -10 + 0.5 = -9.5
        self.assertAlmostEqual(tr.percentile(data, 5), -9.5)

    def test_p1_fractional_index(self):
        data = sorted([-5.0, -3.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        # n=10, idx = 0.01*9 = 0.09 → data[0] + 0.09*(data[1]-data[0]) = -5+0.09*2 = -4.82
        result = tr.percentile(data, 1)
        self.assertAlmostEqual(result, -4.82, places=10)

    def test_p5_ten_elements(self):
        data = sorted(range(10))  # [0,1,2,...,9]
        # idx = 0.05*9 = 0.45 → 0 + 0.45*(1-0) = 0.45
        self.assertAlmostEqual(tr.percentile(data, 5), 0.45)

    def test_p25_four_elements(self):
        data = [0.0, 1.0, 2.0, 3.0]
        # idx = 0.25*3 = 0.75 → 0 + 0.75*(1-0) = 0.75
        self.assertAlmostEqual(tr.percentile(data, 25), 0.75)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. VaR (historical simulation)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVaR(unittest.TestCase):

    def test_var95_is_5th_percentile(self):
        returns = sorted([-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                          11, 12, 13, 14])  # 20 values
        var95 = tr.compute_var(returns, 95)
        expected = tr.percentile(returns, 5)
        self.assertAlmostEqual(var95, expected)

    def test_var99_is_1st_percentile(self):
        returns = sorted(range(-10, 90))  # 100 values
        var99 = tr.compute_var(returns, 99)
        expected = tr.percentile(returns, 1)
        self.assertAlmostEqual(var99, expected)

    def test_var_empty_returns_none(self):
        self.assertIsNone(tr.compute_var([], 95))
        self.assertIsNone(tr.compute_var([], 99))

    def test_var_single_observation(self):
        self.assertAlmostEqual(tr.compute_var([-2.5], 95), -2.5)
        self.assertAlmostEqual(tr.compute_var([-2.5], 99), -2.5)

    def test_var_all_positive_returns_positive(self):
        returns = sorted([0.1, 0.5, 1.0, 2.0, 3.0])
        # Even with all positive returns, VaR is "the worst" i.e. the smallest
        var95 = tr.compute_var(returns, 95)
        self.assertGreater(var95, 0)  # no loss days → VaR is positive


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CVaR (Expected Shortfall)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCVaR(unittest.TestCase):

    def test_cvar95_average_of_worst_5pct(self):
        # 20 observations: worst 5% = ceil(20*0.05)=1 → first element
        data = sorted([-10.0, -8.0, -6.0, -4.0, -2.0, 0.0, 1.0, 2.0, 3.0, 4.0,
                       5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0])
        cvar95 = tr.compute_cvar(data, 95)
        self.assertAlmostEqual(cvar95, -10.0)  # average of [-10] = -10

    def test_cvar99_average_of_worst_1pct(self):
        # 100 observations: worst 1% = ceil(100*0.01)=1 → first element
        data = sorted(range(-50, 50))  # [-50,-49,...,49]
        cvar99 = tr.compute_cvar(data, 99)
        self.assertAlmostEqual(cvar99, -50.0)

    def test_cvar_empty_returns_none(self):
        self.assertIsNone(tr.compute_cvar([], 95))
        self.assertIsNone(tr.compute_cvar([], 99))

    def test_cvar_single_observation(self):
        self.assertAlmostEqual(tr.compute_cvar([-3.0], 95), -3.0)
        self.assertAlmostEqual(tr.compute_cvar([-3.0], 99), -3.0)

    def test_cvar_at_least_one_tail_obs(self):
        # Even with very few observations the tail has at least 1 value
        data = sorted([-1.0, 1.0])
        cvar = tr.compute_cvar(data, 99)
        self.assertIsNotNone(cvar)

    def test_cvar_exact_2_tail_obs(self):
        # 40 obs, 95%: ceil(40*0.05)=2 → average of first 2
        data = sorted([-20.0, -15.0] + list(range(-10, 28)))  # 2 + 38 = 40 obs
        cvar95 = tr.compute_cvar(data, 95)
        self.assertAlmostEqual(cvar95, (-20.0 + -15.0) / 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Invariant: |CVaR| >= |VaR|
# ═══════════════════════════════════════════════════════════════════════════════

class TestCVaRVaRInvariant(unittest.TestCase):
    """CVaR ≤ VaR in loss terms (|CVaR| ≥ |VaR|) — core mathematical invariant."""

    def _check_invariant(self, returns, confidence):
        s = sorted(returns)
        var = tr.compute_var(s, confidence)
        cvar = tr.compute_cvar(s, confidence)
        if var is None or cvar is None:
            return
        # CVaR is average of worst tail → at least as bad as VaR
        self.assertLessEqual(
            cvar, var + 1e-9,
            msg=f"CVaR={cvar} > VaR={var} at {confidence}% (violation!)"
        )

    def test_invariant_95_small(self):
        self._check_invariant([-5, -3, -1, 0, 1, 2, 3], 95)

    def test_invariant_99_small(self):
        self._check_invariant([-5, -3, -1, 0, 1, 2, 3], 99)

    def test_invariant_95_large(self):
        import random
        random.seed(42)
        returns = [random.gauss(0.05, 1.5) for _ in range(200)]
        self._check_invariant(returns, 95)

    def test_invariant_99_large(self):
        import random
        random.seed(7)
        returns = [random.gauss(0.0, 2.0) for _ in range(300)]
        self._check_invariant(returns, 99)

    def test_invariant_all_negative(self):
        self._check_invariant([-5.0, -4.0, -3.0, -2.0, -1.0], 95)
        self._check_invariant([-5.0, -4.0, -3.0, -2.0, -1.0], 99)

    def test_invariant_all_positive(self):
        self._check_invariant([1.0, 2.0, 3.0, 4.0, 5.0], 95)
        self._check_invariant([1.0, 2.0, 3.0, 4.0, 5.0], 99)

    def test_invariant_single_obs(self):
        self._check_invariant([-2.5], 95)
        self._check_invariant([-2.5], 99)

    def test_cvar_worse_than_var_with_fat_tail(self):
        # Extreme outlier makes CVaR much worse than VaR
        data = sorted([-100.0] + [0.0] * 99)  # 100 obs, 1% outlier
        var95 = tr.compute_var(data, 95)
        cvar95 = tr.compute_cvar(data, 95)
        self.assertLessEqual(cvar95, var95 + 1e-9)
        self.assertLess(cvar95, var95)  # strictly worse here


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Worst window returns
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorstRolling(unittest.TestCase):

    def test_worst_day_equiv_to_min_return(self):
        levels = [100.0, 99.0, 98.0, 100.0, 97.0, 101.0]
        series = _series(levels)
        returns = tr._returns_from_levels(series)
        self.assertAlmostEqual(min(returns), min(returns))
        # worst_rolling with window=1 equals min return
        result = tr.worst_rolling([l for _, l in series], 1)
        self.assertAlmostEqual(result, min(returns), places=8)

    def test_worst_week_needs_at_least_5_levels(self):
        for n in [1, 2, 3, 4]:
            with self.subTest(n=n):
                levels = list(range(100, 100 + n))
                self.assertIsNone(tr.worst_rolling(levels, 4))

    def test_worst_week_exactly_5_levels(self):
        levels = [100.0, 99.0, 98.0, 97.0, 96.0]
        result = tr.worst_rolling(levels, 4)
        expected = (96.0 / 100.0 - 1) * 100
        self.assertAlmostEqual(result, expected)

    def test_worst_week_multiple_windows(self):
        # [100, 98, 96, 95, 97, 99] — two 5-bar windows
        # window i=4: 97/100-1 = -3%
        # window i=5: 99/98-1 ≈ +1.02%
        levels = [100.0, 98.0, 96.0, 95.0, 97.0, 99.0]
        result = tr.worst_rolling(levels, 4)
        self.assertAlmostEqual(result, (97.0 / 100.0 - 1) * 100)

    def test_worst_month_needs_at_least_21_levels(self):
        for n in [1, 5, 20]:
            with self.subTest(n=n):
                levels = [100.0 - i * 0.1 for i in range(n)]
                self.assertIsNone(tr.worst_rolling(levels, 20))

    def test_worst_month_exactly_21_levels(self):
        levels = [100.0 - i * 0.5 for i in range(21)]  # monotone decline
        result = tr.worst_rolling(levels, 20)
        expected = (levels[-1] / levels[0] - 1) * 100
        self.assertAlmostEqual(result, expected)

    def test_worst_window_picks_global_minimum(self):
        # Sudden crash at position 10 then recovery
        levels = [100.0] * 5 + [80.0] + [100.0] * 15
        result = tr.worst_rolling(levels, 4)
        # One 5-bar window will catch the crash
        self.assertLess(result, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Population std, skewness, kurtosis
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributionStats(unittest.TestCase):

    def test_population_std_empty(self):
        self.assertIsNone(tr.population_std([]))

    def test_population_std_single(self):
        self.assertIsNone(tr.population_std([5.0]))

    def test_population_std_known(self):
        # [0, 2, 4]: mean=2, variance=(4+0+4)/3=8/3, std=sqrt(8/3)
        std = tr.population_std([0.0, 2.0, 4.0])
        self.assertAlmostEqual(std, math.sqrt(8 / 3))

    def test_skewness_needs_3_obs(self):
        self.assertIsNone(tr.skewness([]))
        self.assertIsNone(tr.skewness([1.0]))
        self.assertIsNone(tr.skewness([1.0, 2.0]))

    def test_skewness_symmetric_is_zero(self):
        data = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
        sk = tr.skewness(data)
        self.assertAlmostEqual(sk, 0.0, places=10)

    def test_skewness_right_skewed_positive(self):
        # Long right tail: mean pulled right
        data = [1.0, 1.0, 1.0, 1.0, 1.0, 10.0]
        sk = tr.skewness(data)
        self.assertGreater(sk, 0)

    def test_skewness_left_skewed_negative(self):
        # Long left tail
        data = [-10.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        sk = tr.skewness(data)
        self.assertLess(sk, 0)

    def test_skewness_zero_std_returns_none(self):
        self.assertIsNone(tr.skewness([5.0, 5.0, 5.0]))

    def test_kurtosis_needs_4_obs(self):
        self.assertIsNone(tr.excess_kurtosis([]))
        self.assertIsNone(tr.excess_kurtosis([1.0, 2.0, 3.0]))

    def test_kurtosis_normal_near_zero(self):
        # Large sample from N(0,1) should be near 0 excess kurtosis
        import random
        random.seed(0)
        data = [random.gauss(0, 1) for _ in range(10000)]
        kt = tr.excess_kurtosis(data)
        self.assertAlmostEqual(kt, 0.0, delta=0.3)  # allow some sampling error

    def test_kurtosis_leptokurtic_positive(self):
        # Many near-zero values with one extreme outlier → heavy right tail
        # n=10, mean=1, std=3: kurtosis = 657/81 - 3 ≈ +5.11 > 0
        data = [0.0] * 9 + [10.0]
        kt = tr.excess_kurtosis(data)
        self.assertGreater(kt, 0)

    def test_kurtosis_zero_std_returns_none(self):
        self.assertIsNone(tr.excess_kurtosis([3.0, 3.0, 3.0, 3.0]))


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Tail ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestTailRatio(unittest.TestCase):

    def test_basic_ratio(self):
        # pos=[2,4] → avg_pos=3; neg=[-1,-3] → avg_neg_abs=2 → ratio=1.5
        returns = [-1.0, -3.0, 2.0, 4.0]
        ratio = tr.tail_ratio(returns)
        self.assertAlmostEqual(ratio, 3.0 / 2.0)

    def test_all_positive_returns_none(self):
        self.assertIsNone(tr.tail_ratio([1.0, 2.0, 3.0]))

    def test_all_negative_returns_zero(self):
        ratio = tr.tail_ratio([-1.0, -2.0, -3.0])
        self.assertAlmostEqual(ratio, 0.0)

    def test_empty_returns_none(self):
        self.assertIsNone(tr.tail_ratio([]))

    def test_ratio_greater_than_one_when_gains_dominate(self):
        returns = [-0.5, 5.0, 6.0, 7.0]
        ratio = tr.tail_ratio(returns)
        self.assertGreater(ratio, 1.0)

    def test_ratio_less_than_one_when_losses_dominate(self):
        returns = [-5.0, -6.0, 0.1, 0.2]
        ratio = tr.tail_ratio(returns)
        self.assertLess(ratio, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Verdict thresholds
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdict(unittest.TestCase):

    def test_ok_below_warn_threshold(self):
        v, _ = tr._verdict(-2.99)
        self.assertEqual(v, "ok")

    def test_ok_exactly_at_zero(self):
        v, _ = tr._verdict(0.0)
        self.assertEqual(v, "ok")

    def test_boundary_warn_exactly_3(self):
        v, _ = tr._verdict(-3.0)
        self.assertEqual(v, "warn")

    def test_warn_between_3_and_5(self):
        v, _ = tr._verdict(-4.0)
        self.assertEqual(v, "warn")

    def test_boundary_fail_exactly_5(self):
        v, _ = tr._verdict(-5.0)
        self.assertEqual(v, "fail")

    def test_fail_above_5(self):
        v, _ = tr._verdict(-10.0)
        self.assertEqual(v, "fail")

    def test_none_var_gives_ok(self):
        v, reason = tr._verdict(None)
        self.assertEqual(v, "ok")
        self.assertIn("insufficient", reason)

    def test_verdict_reason_contains_value(self):
        _, reason = tr._verdict(-4.5)
        self.assertIn("4.5", reason)

    def test_positive_var99_still_ok(self):
        # All-positive return days → VaR is positive → abs < 3 → ok
        v, _ = tr._verdict(0.5)
        self.assertEqual(v, "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. build_tail_risk — main document builder
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildTailRisk(_TmpBase):

    def test_no_file_available_false(self):
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertFalse(doc["available"])
        self.assertEqual(doc["n_observations"], 0)
        self.assertIsNone(doc["var_95_pct"])
        self.assertIsNone(doc["var_99_pct"])

    def test_single_bar_no_returns_available_false(self):
        _write_equity(self.data_dir, _equity_doc([100000.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertFalse(doc["available"])
        self.assertEqual(doc["n_observations"], 0)

    def test_two_bars_one_return_available_true(self):
        _write_equity(self.data_dir, _equity_doc([100000.0, 100100.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertTrue(doc["available"])
        self.assertEqual(doc["n_observations"], 1)
        # Only 1 return → var/cvar = that return
        self.assertAlmostEqual(doc["var_95_pct"], doc["worst_day_pct"])

    def test_three_bars_two_returns(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 99.0, 101.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertTrue(doc["available"])
        self.assertEqual(doc["n_observations"], 2)
        # worst_day = min(-1%, +2.02%) ≈ -1%
        self.assertLess(doc["worst_day_pct"], 0)

    def test_sufficient_data_all_fields_present(self):
        # 25 bars → 24 returns
        import random
        random.seed(1)
        levels = [100000.0]
        for _ in range(24):
            levels.append(levels[-1] * (1 + random.gauss(0.0003, 0.01)))
        _write_equity(self.data_dir, _equity_doc(levels))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertTrue(doc["available"])
        self.assertIsNotNone(doc["var_95_pct"])
        self.assertIsNotNone(doc["var_99_pct"])
        self.assertIsNotNone(doc["cvar_95_pct"])
        self.assertIsNotNone(doc["cvar_99_pct"])
        self.assertIsNotNone(doc["worst_day_pct"])
        self.assertIn("verdict", doc)
        self.assertIn(doc["verdict"], ("ok", "warn", "fail"))

    def test_is_demo_false_propagated(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 101.0], is_demo=False))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertFalse(doc["is_demo"])

    def test_is_demo_true_propagated(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 101.0], is_demo=True))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertTrue(doc["is_demo"])

    def test_is_demo_absent_returns_none(self):
        doc_in = _equity_doc([100.0, 101.0])
        del doc_in["is_demo"]
        _write_equity(self.data_dir, doc_in)
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertIsNone(doc["is_demo"])

    def test_worst_week_none_when_too_few_bars(self):
        # 4 bars → 3 returns, not enough for 5-bar window
        _write_equity(self.data_dir, _equity_doc([100, 99, 98, 97]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertIsNone(doc["worst_week_pct"])

    def test_worst_week_available_with_5_bars(self):
        _write_equity(self.data_dir, _equity_doc([100, 99, 98, 97, 96]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertIsNotNone(doc["worst_week_pct"])
        self.assertAlmostEqual(doc["worst_week_pct"],
                               (96.0 / 100.0 - 1.0) * 100.0, places=4)

    def test_worst_month_none_when_too_few_bars(self):
        _write_equity(self.data_dir, _equity_doc([100.0 - i for i in range(20)]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertIsNone(doc["worst_month_pct"])

    def test_schema_version_present(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 101.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertEqual(doc["schema_version"], tr.SCHEMA_VERSION)

    def test_advisory_fields_present(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 101.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertTrue(doc.get("advisory_only"))
        self.assertIn("disclaimer", doc)

    def test_never_raises_on_garbage_equity_doc(self):
        garbage = [None, 42, "bad", {}, [], {"daily": "nope"}, {"daily": [None, 42]}]
        for g in garbage:
            with self.subTest(g=type(g).__name__):
                p = self.data_dir / tr.EQUITY_FILENAME
                p.write_text(json.dumps(g), encoding="utf-8")
                try:
                    doc = tr.build_tail_risk(data_dir=self.data_dir)
                    self.assertFalse(doc["available"])
                except Exception as e:
                    self.fail(f"build_tail_risk raised {e!r} on garbage input")

    def test_bars_with_negative_equity_filtered(self):
        raw = {
            "daily": [
                {"date": "2026-06-10", "close_equity": 100.0, "is_demo": False},
                {"date": "2026-06-11", "close_equity": -50.0},   # invalid
                {"date": "2026-06-12", "close_equity": 101.0},
            ],
            "is_demo": False,
        }
        _write_equity(self.data_dir, raw)
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        # Should skip bar with -50 → only 2 valid bars → 1 return
        self.assertEqual(doc["n_observations"], 1)

    def test_cvar_le_var_invariant_in_build(self):
        import random
        random.seed(99)
        levels = [100000.0]
        for _ in range(60):
            levels.append(levels[-1] * (1 + random.gauss(0.0002, 0.015)))
        _write_equity(self.data_dir, _equity_doc(levels))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertIsNotNone(doc["cvar_95_pct"])
        self.assertIsNotNone(doc["var_95_pct"])
        self.assertLessEqual(doc["cvar_95_pct"], doc["var_95_pct"] + 1e-9)
        self.assertLessEqual(doc["cvar_99_pct"], doc["var_99_pct"] + 1e-9)

    def test_notes_non_empty_with_few_observations(self):
        _write_equity(self.data_dir, _equity_doc([100.0, 101.0]))
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        # < 30 observations → note about uncertainty
        self.assertTrue(any("uncertainty" in n for n in doc.get("notes", [])))

    def test_broken_json_file(self):
        p = self.data_dir / tr.EQUITY_FILENAME
        p.write_text("not valid json {{{", encoding="utf-8")
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertFalse(doc["available"])

    def test_empty_daily_list(self):
        _write_equity(self.data_dir, {"daily": [], "is_demo": False})
        doc = tr.build_tail_risk(data_dir=self.data_dir)
        self.assertFalse(doc["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# 10. content_fingerprint
# ═══════════════════════════════════════════════════════════════════════════════

class TestContentFingerprint(unittest.TestCase):

    def _doc(self):
        return {
            "schema_version": "1.0",
            "generated_at": "2026-06-12T10:00:00+00:00",
            "var_99_pct": -2.5,
            "verdict": "ok",
            "history": [{"generated_at": "earlier", "verdict": "ok"}],
        }

    def test_different_generated_at_same_fingerprint(self):
        d1 = self._doc()
        d2 = {**d1, "generated_at": "2026-06-13T00:00:00+00:00"}
        self.assertEqual(tr.content_fingerprint(d1), tr.content_fingerprint(d2))

    def test_different_history_same_fingerprint(self):
        d1 = self._doc()
        d2 = {**d1, "history": [{"more": "entries"}]}
        self.assertEqual(tr.content_fingerprint(d1), tr.content_fingerprint(d2))

    def test_different_content_different_fingerprint(self):
        d1 = self._doc()
        d2 = {**d1, "var_99_pct": -5.0}
        self.assertNotEqual(tr.content_fingerprint(d1), tr.content_fingerprint(d2))

    def test_non_dict_gives_sentinel(self):
        fp = tr.content_fingerprint(None)
        self.assertEqual(fp, "<invalid>")
        fp2 = tr.content_fingerprint([1, 2, 3])
        self.assertEqual(fp2, "<invalid>")

    def test_deterministic(self):
        d = self._doc()
        self.assertEqual(tr.content_fingerprint(d), tr.content_fingerprint(d))


# ═══════════════════════════════════════════════════════════════════════════════
# 11. write_status — persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _build(self, levels=None):
        if levels is None:
            levels = [100.0, 99.0, 101.0, 100.5, 102.0]
        _write_equity(self.data_dir, _equity_doc(levels))
        return tr.build_tail_risk(data_dir=self.data_dir)

    def test_write_creates_file(self):
        doc = self._build()
        tr.write_status(doc, data_dir=self.data_dir)
        self.assertTrue((self.data_dir / tr.STATUS_FILENAME).exists())

    def test_written_file_valid_json(self):
        doc = self._build()
        tr.write_status(doc, data_dir=self.data_dir)
        raw = (self.data_dir / tr.STATUS_FILENAME).read_text()
        obj = json.loads(raw)
        self.assertIsInstance(obj, dict)

    def test_no_stray_tmp_files(self):
        doc = self._build()
        tr.write_status(doc, data_dir=self.data_dir)
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "stray .tmp files left after write")

    def test_idempotent_same_content(self):
        doc = self._build()
        r1 = tr.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(r1["changed"])
        r2 = tr.write_status(doc, data_dir=self.data_dir)
        self.assertFalse(r2["changed"])

    def test_idempotent_byte_identical(self):
        doc = self._build()
        tr.write_status(doc, data_dir=self.data_dir)
        path = self.data_dir / tr.STATUS_FILENAME
        md5_1 = hashlib.md5(path.read_bytes()).hexdigest()
        tr.write_status(doc, data_dir=self.data_dir)
        md5_2 = hashlib.md5(path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_history_appended_on_change(self):
        doc1 = self._build([100.0, 99.0, 101.0])
        tr.write_status(doc1, data_dir=self.data_dir)
        doc2 = self._build([100.0, 95.0, 101.0])  # different data
        # Ensure fingerprint differs (different returns → different var)
        if tr.content_fingerprint(doc1) == tr.content_fingerprint(doc2):
            # Force a field difference
            doc2["n_observations"] = doc2["n_observations"] + 99
        tr.write_status(doc2, data_dir=self.data_dir)
        saved = json.loads((self.data_dir / tr.STATUS_FILENAME).read_text())
        self.assertIsInstance(saved.get("history"), list)
        self.assertGreaterEqual(len(saved["history"]), 1)

    def test_history_rotation_at_max(self):
        doc = self._build()
        # Pre-fill a file with HISTORY_MAX entries
        pre = dict(doc)
        pre["history"] = [{"generated_at": "x", "verdict": "ok"}] * tr.HISTORY_MAX
        (self.data_dir / tr.STATUS_FILENAME).write_text(
            json.dumps(pre), encoding="utf-8"
        )
        doc2 = dict(doc)
        doc2["var_99_pct"] = (doc2.get("var_99_pct") or 0) - 99  # change content
        tr.write_status(doc2, data_dir=self.data_dir)
        saved = json.loads((self.data_dir / tr.STATUS_FILENAME).read_text())
        self.assertLessEqual(len(saved["history"]), tr.HISTORY_MAX)

    def test_tolerant_to_broken_prev_file(self):
        p = self.data_dir / tr.STATUS_FILENAME
        p.write_text("BROKEN JSON !!!", encoding="utf-8")
        doc = self._build()
        result = tr.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(result["changed"])
        # File is now valid
        json.loads(p.read_text())


# ═══════════════════════════════════════════════════════════════════════════════
# 12. CLI
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLI(_TmpBase):

    def _make_data(self, levels=None):
        if levels is None:
            levels = [100.0, 99.0, 101.0, 100.5, 102.0, 101.0]
        _write_equity(self.data_dir, _equity_doc(levels))

    def test_check_does_not_write(self):
        self._make_data()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tr.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / tr.STATUS_FILENAME).exists())

    def test_check_outputs_valid_json(self):
        self._make_data()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tr.main(["--check", "--data-dir", str(self.data_dir)])
        obj = json.loads(buf.getvalue())
        self.assertIn("verdict", obj)

    def test_run_writes_file(self):
        self._make_data()
        tr.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertTrue((self.data_dir / tr.STATUS_FILENAME).exists())

    def test_run_idempotent_message(self):
        self._make_data()
        buf1 = io.StringIO()
        with contextlib.redirect_stdout(buf1):
            tr.main(["--run", "--data-dir", str(self.data_dir)])
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            tr.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertIn("idempotent", buf2.getvalue())

    def test_no_args_defaults_to_check(self):
        self._make_data()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tr.main([])
        self.assertEqual(code, 0)
        # Should print JSON (check mode)
        obj = json.loads(buf.getvalue())
        self.assertIn("schema_version", obj)

    def test_junk_arg_exit_0_error_to_stderr(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code = tr.main(["--totally-unknown-arg"])
        self.assertEqual(code, 0)
        self.assertIn("ERROR", buf.getvalue())

    def test_data_dir_override(self):
        self._make_data()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tr.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        obj = json.loads(buf.getvalue())
        self.assertTrue(obj["available"])

    def test_subprocess_check_exit_0(self):
        self._make_data()
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.tail_risk",
             "--check", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        obj = json.loads(result.stdout)
        self.assertIn("verdict", obj)

    def test_subprocess_run_exit_0(self):
        self._make_data()
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.tail_risk",
             "--run", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.data_dir / tr.STATUS_FILENAME).exists())

    def test_subprocess_junk_arg_exit_0(self):
        result = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.tail_risk",
             "--blah-blah-garbage"],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stderr)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Import hygiene (AST linter — no forbidden imports)
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportHygiene(unittest.TestCase):

    FORBIDDEN = frozenset([
        "numpy", "scipy", "pandas", "requests", "web3", "socket",
        "urllib", "aiohttp", "httpx", "anthropic", "openai",
    ])

    def _check_file(self, path: Path):
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as e:
            self.fail(f"SyntaxError in {path}: {e}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    self.assertNotIn(
                        base, self.FORBIDDEN,
                        msg=f"Forbidden import '{alias.name}' in {path}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split(".")[0]
                    self.assertNotIn(
                        base, self.FORBIDDEN,
                        msg=f"Forbidden 'from {node.module} import ...' in {path}",
                    )

    def test_tail_risk_no_forbidden_imports(self):
        p = _REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
        self.assertTrue(p.exists(), "tail_risk.py not found")
        self._check_file(p)

    def test_no_network_calls(self):
        p = _REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
        src = p.read_text(encoding="utf-8")
        for forbidden in ["requests.", "urllib.request", "http.client"]:
            self.assertNotIn(
                forbidden, src,
                msg=f"Found '{forbidden}' in tail_risk.py",
            )

    def test_no_execution_imports(self):
        p = _REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
        src = p.read_text(encoding="utf-8")
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("import spa_core.execution", src)

    def test_no_risk_policy_imports(self):
        p = _REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
        src = p.read_text(encoding="utf-8")
        self.assertNotIn("from spa_core.risk", src)
        self.assertNotIn("import spa_core.risk", src)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Regression — existing analytics not broken
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionImports(unittest.TestCase):

    def test_drawdown_analytics_importable(self):
        from spa_core.paper_trading import drawdown_analytics
        self.assertTrue(callable(drawdown_analytics.build_drawdown_analytics))

    def test_concentration_analytics_importable(self):
        from spa_core.paper_trading import concentration_analytics
        self.assertTrue(callable(concentration_analytics.build_concentration))

    def test_yield_attribution_importable(self):
        from spa_core.paper_trading import yield_attribution
        self.assertTrue(callable(yield_attribution.build_yield_attribution))

    def test_risk_contribution_importable(self):
        from spa_core.paper_trading import risk_contribution
        self.assertTrue(callable(risk_contribution.build_risk_contribution))

    def test_tail_risk_does_not_import_drawdown_analytics(self):
        # tail_risk is standalone — no cross-module dependencies
        src = (_REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("drawdown_analytics", src)

    def test_tail_risk_does_not_import_concentration_analytics(self):
        src = (_REPO_ROOT / "spa_core" / "paper_trading" / "tail_risk.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("concentration_analytics", src)

    def test_build_tail_risk_callable_with_default_data_dir(self):
        # Should not raise even if the real data dir has minimal data
        try:
            doc = tr.build_tail_risk()
            self.assertIsInstance(doc, dict)
        except Exception as e:
            self.fail(f"build_tail_risk() raised {e!r}")

    def test_cvar_le_var_regression_with_real_style_data(self):
        """Regression: invariant holds on realistic equity-like returns."""
        import random
        random.seed(314)
        returns = sorted([random.gauss(0.05, 1.2) for _ in range(365)])
        for conf in [95, 99]:
            with self.subTest(conf=conf):
                var = tr.compute_var(returns, conf)
                cvar = tr.compute_cvar(returns, conf)
                self.assertLessEqual(cvar, var + 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
