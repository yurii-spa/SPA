#!/usr/bin/env python3
"""Tests for structural_break (SPA-V452 / MP-138).

unittest only -- NO pytest, NO network, tempdir-isolated. Covers:
- pure math: cusum_path (hand-verified small series + degenerate),
  max_cusum_deviation, candidate_break_index (min_segment guard),
  welch_t_test (hand-computed t / df), two_sided_p_from_t (t=0 -> ~1,
  monotone in |t|, symmetric in sign, p in [0,1], reference anchors)
- detect_structural_break: clear deterioration break, improvement break,
  noise -> no break, min_segment edge guard
- verdict boundaries: deterioration -> fail, improvement -> warn,
  no-break -> ok, verdict_reason present, band invariant
- insufficient_data: empty / short / flat / zero-variance -> available:false,
  schema stable, verdict='ok'
- tolerance / never-raise: missing / broken / non-dict / garbage data_dir
  (subTest) + property fuzzing with seed
- content_fingerprint reuse-by-import: assertIs to tear_sheet, ignores
  generated_at/history, changes with content, stable
- write_status: first -> WRITTEN, identical -> UNCHANGED byte-identical md5,
  different -> WRITTEN + history grows, rotation EXACTLY HISTORY_MAX=500,
  no *.tmp, tolerant broken existing file
- CLI direct main(argv) + subprocess (--check no-write, default=check, --run
  writes / idempotent UNCHANGED md5-identical, junk -> ERROR exit0 no Traceback,
  conflict -> exit0)
- import hygiene (real find_forbidden_imports, py_compile both files, no
  network/LLM/socket/subprocess/eval/exec, reuse-by-import marker, atomic-write
  pattern, e2e round-trip on real data/)
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import os
import py_compile
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

# -- project path -------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import structural_break as sb
from spa_core.reporting import tear_sheet as ts

_MODULE_PATH = Path(sb.__file__)
_TEST_PATH = Path(__file__)


# -- helpers ------------------------------------------------------------------

def _write_pnl(data_dir: Path, returns_pct: List[float], start_cap: float = 100000.0) -> None:
    """Write a pnl_history.json that yields the given daily_return_pct series.

    equity_curve derives daily_return_pct from total_capital_usd. Day 1 is a
    seed (0.0 return, dropped by the builder), so we prepend a seed bar then
    compound the requested per-day returns.
    """
    d0 = date.fromisoformat("2026-01-01")
    cap = start_cap
    records = [{
        "timestamp": f"{d0.isoformat()} 00:00:00",
        "total_capital_usd": cap,
        "total_pnl_usd": 0.0,
        "total_pnl_pct": 0.0,
    }]
    for i, r in enumerate(returns_pct, start=1):
        cap = cap * (1.0 + r / 100.0)
        d = d0 + timedelta(days=i)
        records.append({
            "timestamp": f"{d.isoformat()} 00:00:00",
            "total_capital_usd": cap,
            "total_pnl_usd": cap - start_cap,
            "total_pnl_pct": (cap / start_cap - 1.0) * 100.0,
        })
    (data_dir / "pnl_history.json").write_text(json.dumps(records))


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="structural_break_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# =============================================================================
# Pure math -- cusum_path
# =============================================================================

class TestCusumPath(unittest.TestCase):
    def test_hand_verified(self) -> None:
        # returns [1,2,3]: mean=2, pstdev=sqrt(2/3). standardized devs:
        # (-1, 0, +1)/sd -> cumulative: -1/sd, -1/sd, 0
        r = [1.0, 2.0, 3.0]
        sd = math.sqrt(2.0 / 3.0)
        path = sb.cusum_path(r)
        self.assertAlmostEqual(path[0], -1.0 / sd, places=12)
        self.assertAlmostEqual(path[1], -1.0 / sd, places=12)
        self.assertAlmostEqual(path[2], 0.0, places=12)

    def test_returns_to_zero_at_end(self) -> None:
        r = [0.3, -0.1, 0.5, 0.2, -0.4, 0.1]
        path = sb.cusum_path(r)
        self.assertAlmostEqual(path[-1], 0.0, places=9)

    def test_length_matches(self) -> None:
        r = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(len(sb.cusum_path(r)), 5)

    def test_empty(self) -> None:
        self.assertEqual(sb.cusum_path([]), [])

    def test_single(self) -> None:
        self.assertEqual(sb.cusum_path([4.2]), [0.0])

    def test_flat_zero_variance(self) -> None:
        self.assertEqual(sb.cusum_path([3.0, 3.0, 3.0, 3.0]), [0.0, 0.0, 0.0, 0.0])


# =============================================================================
# Pure math -- max_cusum_deviation
# =============================================================================

class TestMaxCusumDeviation(unittest.TestCase):
    def test_hand(self) -> None:
        r = [1.0, 2.0, 3.0]
        sd = math.sqrt(2.0 / 3.0)
        dev = sb.max_cusum_deviation(r)
        self.assertEqual(dev["index"], 0)
        self.assertAlmostEqual(dev["value"], -1.0 / sd, places=12)

    def test_empty(self) -> None:
        self.assertEqual(sb.max_cusum_deviation([]), {"index": None, "value": 0.0})

    def test_flat(self) -> None:
        self.assertEqual(sb.max_cusum_deviation([2.0, 2.0, 2.0]),
                         {"index": None, "value": 0.0})

    def test_signed_value(self) -> None:
        # a clear up->down shift makes a strong positive excursion mid-series
        r = [1.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0, -1.0]
        dev = sb.max_cusum_deviation(r)
        self.assertIsNotNone(dev["index"])
        self.assertGreater(abs(dev["value"]), 0.0)


# =============================================================================
# Pure math -- candidate_break_index (min_segment guard)
# =============================================================================

class TestCandidateBreakIndex(unittest.TestCase):
    def test_midseries_candidate(self) -> None:
        r = [1.0] * 8 + [-1.0] * 8
        idx = sb.candidate_break_index(r, min_segment=5)
        self.assertIsNotNone(idx)
        # both sides must clear min_segment
        self.assertGreaterEqual(idx + 1, 5)
        self.assertGreaterEqual(len(r) - (idx + 1), 5)

    def test_edge_guard_returns_none(self) -> None:
        # candidate forced near the very front by a single huge first value
        r = [10.0] + [0.0, 0.01, -0.01, 0.0, 0.005, -0.005, 0.0, 0.01, -0.01, 0.0, 0.005]
        self.assertIsNone(sb.candidate_break_index(r, min_segment=5))

    def test_flat_none(self) -> None:
        self.assertIsNone(sb.candidate_break_index([1.0] * 20, min_segment=5))

    def test_empty_none(self) -> None:
        self.assertIsNone(sb.candidate_break_index([], min_segment=5))

    def test_small_min_segment_allows(self) -> None:
        r = [10.0] + [0.0, 0.01, -0.01, 0.0]
        # with min_segment=1 the front candidate is allowed
        idx = sb.candidate_break_index(r, min_segment=1)
        self.assertIsNotNone(idx)


# =============================================================================
# Pure math -- welch_t_test
# =============================================================================

class TestWelchTTest(unittest.TestCase):
    def test_hand_equal_n(self) -> None:
        # a=[1,2,3,4] mean 2.5 var 1.6667 ; b=[6,7,8,9] mean 7.5 var 1.6667
        # se = sqrt(1.6667/4 + 1.6667/4) = sqrt(0.83333) = 0.912871
        # t = (2.5-7.5)/0.912871 = -5.477226 ; df = 6 (symmetric equal-var/n)
        a = [1.0, 2.0, 3.0, 4.0]
        b = [6.0, 7.0, 8.0, 9.0]
        wt = sb.welch_t_test(a, b)
        self.assertAlmostEqual(wt["mean_a"], 2.5, places=12)
        self.assertAlmostEqual(wt["mean_b"], 7.5, places=12)
        self.assertAlmostEqual(wt["t_stat"], -5.477225575051661, places=9)
        self.assertAlmostEqual(wt["df"], 6.0, places=9)
        self.assertEqual(wt["n_a"], 4)
        self.assertEqual(wt["n_b"], 4)

    def test_unequal_variance_df(self) -> None:
        # a tight, b wide -> Welch df strictly less than n_a+n_b-2
        a = [10.0, 10.1, 9.9, 10.0, 10.05]
        b = [0.0, 20.0, -10.0, 30.0, 5.0]
        wt = sb.welch_t_test(a, b)
        self.assertIsNotNone(wt["t_stat"])
        self.assertLess(wt["df"], wt["n_a"] + wt["n_b"] - 2)
        self.assertGreater(wt["df"], 0.0)

    def test_degenerate_small_group(self) -> None:
        wt = sb.welch_t_test([1.0], [1.0, 2.0, 3.0])
        self.assertIsNone(wt["t_stat"])
        self.assertIsNone(wt["df"])

    def test_degenerate_both_constant(self) -> None:
        wt = sb.welch_t_test([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        self.assertIsNone(wt["t_stat"])

    def test_sign_of_t(self) -> None:
        # mean_a > mean_b -> positive t
        wt = sb.welch_t_test([5.0, 6.0, 7.0], [1.0, 2.0, 3.0])
        self.assertGreater(wt["t_stat"], 0.0)


# =============================================================================
# Pure math -- two_sided_p_from_t
# =============================================================================

class TestTwoSidedP(unittest.TestCase):
    def test_t_zero_is_one(self) -> None:
        self.assertAlmostEqual(sb.two_sided_p_from_t(0.0, 10.0), 1.0, places=9)

    def test_known_anchor_t2_df10(self) -> None:
        # reference two-sided p for t=2, df=10 ~ 0.07339
        self.assertAlmostEqual(sb.two_sided_p_from_t(2.0, 10.0), 0.073388, places=5)

    def test_known_anchor_t2228_df10(self) -> None:
        # critical t ~ 2.228 at df=10 -> p ~ 0.05
        self.assertAlmostEqual(sb.two_sided_p_from_t(2.228, 10.0), 0.05, places=3)

    def test_known_anchor_t35_df20(self) -> None:
        self.assertAlmostEqual(sb.two_sided_p_from_t(3.5, 20.0), 0.002255, places=5)

    def test_symmetric_in_sign(self) -> None:
        self.assertAlmostEqual(
            sb.two_sided_p_from_t(1.7, 8.0),
            sb.two_sided_p_from_t(-1.7, 8.0), places=12)

    def test_monotone_decreasing_in_abs_t(self) -> None:
        prev = 1.0
        for t in [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0]:
            p = sb.two_sided_p_from_t(t, 15.0)
            self.assertLessEqual(p, prev + 1e-12)
            prev = p

    def test_in_unit_interval(self) -> None:
        for t in [-100.0, -3.0, 0.0, 0.1, 4.0, 50.0, 1000.0]:
            for df in [1.0, 2.5, 10.0, 100.0, 5000.0]:
                p = sb.two_sided_p_from_t(t, df)
                self.assertGreaterEqual(p, 0.0)
                self.assertLessEqual(p, 1.0)

    def test_none_t(self) -> None:
        self.assertIsNone(sb.two_sided_p_from_t(None, 10.0))

    def test_none_df(self) -> None:
        self.assertIsNone(sb.two_sided_p_from_t(2.0, None))

    def test_nonpositive_df(self) -> None:
        self.assertIsNone(sb.two_sided_p_from_t(2.0, 0.0))
        self.assertIsNone(sb.two_sided_p_from_t(2.0, -3.0))

    def test_large_t_tiny_p(self) -> None:
        self.assertLess(sb.two_sided_p_from_t(20.0, 30.0), 1e-6)


# =============================================================================
# detect_structural_break
# =============================================================================

class TestDetect(unittest.TestCase):
    def test_clear_deterioration(self) -> None:
        hi = [0.011, 0.009, 0.010, 0.012, 0.008, 0.011, 0.009, 0.010]
        lo = [-0.011, -0.009, -0.010, -0.012, -0.008, -0.011, -0.009, -0.010]
        d = sb.detect_structural_break(hi + lo)
        self.assertTrue(d["break_detected"])
        self.assertEqual(d["shift_direction"], "deterioration")
        self.assertIsNotNone(d["break_index"])
        self.assertLess(d["p_value"], 0.05)
        self.assertGreater(d["mean_before"], d["mean_after"])

    def test_clear_improvement(self) -> None:
        hi = [0.011, 0.009, 0.010, 0.012, 0.008, 0.011, 0.009, 0.010]
        lo = [-0.011, -0.009, -0.010, -0.012, -0.008, -0.011, -0.009, -0.010]
        d = sb.detect_structural_break(lo + hi)
        self.assertTrue(d["break_detected"])
        self.assertEqual(d["shift_direction"], "improvement")
        self.assertLess(d["mean_before"], d["mean_after"])

    def test_noise_no_break(self) -> None:
        rng = random.Random(7)
        r = [rng.gauss(0.0, 1.0) for _ in range(40)]
        d = sb.detect_structural_break(r)
        self.assertFalse(d["break_detected"])
        # a candidate exists mid-series but is not significant
        self.assertIsNotNone(d["break_index"])
        self.assertGreaterEqual(d["p_value"], 0.05)

    def test_edge_guard_no_candidate(self) -> None:
        r = [10.0] + [0.0, 0.01, -0.01, 0.0, 0.005, -0.005, 0.0, 0.01, -0.01, 0.0, 0.005]
        d = sb.detect_structural_break(r, min_segment=5)
        self.assertFalse(d["break_detected"])
        self.assertIsNone(d["break_index"])
        self.assertIsNone(d["p_value"])
        self.assertEqual(d["shift_direction"], "none")
        self.assertEqual(d["segment_lengths"], [0, 0])

    def test_segment_lengths_sum(self) -> None:
        r = [1.0] * 8 + [-1.0] * 8
        d = sb.detect_structural_break(r)
        self.assertEqual(sum(d["segment_lengths"]), len(r))

    def test_detected_implies_p_below_alpha(self) -> None:
        r = [0.02] * 10 + [-0.02] * 10
        # add tiny jitter for nonzero variance
        r = [v + (0.001 if i % 2 else -0.001) for i, v in enumerate(r)]
        d = sb.detect_structural_break(r, alpha=0.05)
        if d["break_detected"]:
            self.assertLess(d["p_value"], 0.05)

    def test_alpha_threshold_effect(self) -> None:
        rng = random.Random(123)
        r = [rng.gauss(0.0, 1.0) for _ in range(30)]
        d_loose = sb.detect_structural_break(r, alpha=0.99)
        d_tight = sb.detect_structural_break(r, alpha=1e-9)
        # looser alpha can only detect more (or equal), never fewer
        if d_tight["break_detected"]:
            self.assertTrue(d_loose["break_detected"])


# =============================================================================
# Verdict boundaries (via build_structural_break)
# =============================================================================

class TestVerdictBoundaries(_TmpBase):
    def _build(self, returns: List[float]) -> Dict[str, Any]:
        _write_pnl(self.data_dir, returns)
        return sb.build_structural_break(self.data_dir)

    def test_deterioration_fail(self) -> None:
        r = [0.5] * 8 + [-0.5] * 8
        r = [v + (0.01 if i % 2 else -0.01) for i, v in enumerate(r)]
        res = self._build(r)
        self.assertTrue(res["available"])
        self.assertTrue(res["break_detected"])
        self.assertEqual(res["shift_direction"], "deterioration")
        self.assertEqual(res["verdict"], "fail")
        self._band_invariant(res)

    def test_improvement_warn(self) -> None:
        r = [-0.5] * 8 + [0.5] * 8
        r = [v + (0.01 if i % 2 else -0.01) for i, v in enumerate(r)]
        res = self._build(r)
        self.assertTrue(res["available"])
        self.assertTrue(res["break_detected"])
        self.assertEqual(res["shift_direction"], "improvement")
        self.assertEqual(res["verdict"], "warn")
        self._band_invariant(res)

    def test_no_break_ok(self) -> None:
        rng = random.Random(99)
        r = [rng.gauss(0.0, 0.3) for _ in range(40)]
        res = self._build(r)
        self.assertTrue(res["available"])
        self.assertFalse(res["break_detected"])
        self.assertEqual(res["verdict"], "ok")
        self._band_invariant(res)

    def test_verdict_reason_present(self) -> None:
        rng = random.Random(5)
        r = [rng.gauss(0.0, 0.4) for _ in range(30)]
        res = self._build(r)
        self.assertIn("verdict", res)
        self.assertIn("verdict_reason", res)
        self.assertTrue(res["verdict_reason"])

    def _band_invariant(self, res: Dict[str, Any]) -> None:
        if res["break_detected"] and res["shift_direction"] == "deterioration":
            self.assertEqual(res["verdict"], "fail")
        elif res["break_detected"] and res["shift_direction"] == "improvement":
            self.assertEqual(res["verdict"], "warn")
        else:
            self.assertEqual(res["verdict"], "ok")

    def test_break_date_populated_on_detection(self) -> None:
        r = [0.5] * 8 + [-0.5] * 8
        r = [v + (0.01 if i % 2 else -0.01) for i, v in enumerate(r)]
        res = self._build(r)
        self.assertTrue(res["break_detected"])
        self.assertIsNotNone(res["break_date"])
        # break_date is a parseable ISO date string
        date.fromisoformat(res["break_date"])


# =============================================================================
# insufficient_data & schema stability
# =============================================================================

_SCHEMA_KEYS = {
    "available", "is_demo", "break_detected", "break_index", "break_date",
    "n_observations", "cusum_max_abs", "mean_before", "mean_after",
    "shift_direction", "t_stat", "p_value", "verdict", "verdict_reason",
    "min_segment", "alpha", "notes", "meta",
}


class TestInsufficientData(_TmpBase):
    def test_empty_equity(self) -> None:
        (self.data_dir / "pnl_history.json").write_text("[]")
        r = sb.build_structural_break(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("reason", r)
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))
        self.assertEqual(r["verdict"], "ok")

    def test_short_equity(self) -> None:
        _write_pnl(self.data_dir, [0.1, 0.2, 0.3])  # only 3 daily returns < MIN_OBS
        r = sb.build_structural_break(self.data_dir)
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))
        self.assertEqual(r["verdict"], "ok")

    def test_flat_series(self) -> None:
        _write_pnl(self.data_dir, [0.0] * 20)
        r = sb.build_structural_break(self.data_dir)
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))
        self.assertEqual(r["verdict"], "ok")

    def test_missing_file(self) -> None:
        r = sb.build_structural_break(self.data_dir)  # nothing written
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))
        self.assertEqual(r["verdict"], "ok")

    def test_exactly_below_min_obs(self) -> None:
        _write_pnl(self.data_dir, [0.1] * (sb.MIN_OBS - 1))
        r = sb.build_structural_break(self.data_dir)
        self.assertFalse(r["available"])


# =============================================================================
# Tolerance / never-raise
# =============================================================================

class TestNeverRaise(_TmpBase):
    def test_garbage_inputs(self) -> None:
        garbage = [
            "not json at all",
            "{",
            "null",
            "123",
            '"a string"',
            "{\"protocol_history\": 5}",
            "[1, 2, 3]",
            "{}",
        ]
        for g in garbage:
            with self.subTest(g=g):
                (self.data_dir / "pnl_history.json").write_text(g)
                r = sb.build_structural_break(self.data_dir)
                self.assertIsInstance(r, dict)
                self.assertIn("available", r)
                self.assertIn("verdict", r)
                self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))

    def test_garbage_data_dir_path(self) -> None:
        # a data_dir that does not exist at all
        r = sb.build_structural_break(self.data_dir / "does" / "not" / "exist")
        self.assertIsInstance(r, dict)
        self.assertFalse(r["available"])

    def test_property_fuzz(self) -> None:
        rng = random.Random(20260612)
        tokens = ["{", "}", "[", "]", "null", "true", "1.5", "\"x\"", ",", ":",
                  "pnl", "equity", "NaN", "Infinity", "-1e400"]
        for i in range(40):
            blob = "".join(rng.choice(tokens) for _ in range(rng.randint(1, 20)))
            with self.subTest(i=i, blob=blob[:20]):
                (self.data_dir / "pnl_history.json").write_text(blob)
                r = sb.build_structural_break(self.data_dir)
                self.assertIsInstance(r, dict)
                self.assertIn("available", r)

    def test_random_valid_series_never_raise(self) -> None:
        rng = random.Random(424242)
        for i in range(20):
            n = rng.randint(0, 60)
            r = [rng.gauss(0.0, rng.uniform(0.01, 2.0)) for _ in range(n)]
            with self.subTest(i=i, n=n):
                _write_pnl(self.data_dir, r)
                res = sb.build_structural_break(self.data_dir)
                self.assertIsInstance(res, dict)
                self.assertIn("verdict", res)


# =============================================================================
# content_fingerprint reuse-by-import
# =============================================================================

class TestFingerprintReuse(unittest.TestCase):
    def test_same_object(self) -> None:
        self.assertIs(sb.content_fingerprint, ts.content_fingerprint)

    def test_ignores_generated_at_and_history(self) -> None:
        a = {"x": 1, "meta": {"generated_at": "A", "source": "s"}, "history": [1]}
        b = {"x": 1, "meta": {"generated_at": "B", "source": "s"}, "history": [9, 9]}
        self.assertEqual(sb.content_fingerprint(a), sb.content_fingerprint(b))

    def test_changes_with_content(self) -> None:
        a = {"x": 1, "meta": {"source": "s"}}
        b = {"x": 2, "meta": {"source": "s"}}
        self.assertNotEqual(sb.content_fingerprint(a), sb.content_fingerprint(b))

    def test_stable(self) -> None:
        a = {"x": 1, "y": [1, 2, 3], "meta": {"source": "s"}}
        self.assertEqual(sb.content_fingerprint(a), sb.content_fingerprint(dict(a)))


# =============================================================================
# write_status
# =============================================================================

class TestWriteStatus(_TmpBase):
    def _md5(self, p: Path) -> str:
        return hashlib.md5(p.read_bytes()).hexdigest()

    def test_first_write_then_unchanged(self) -> None:
        res = {"available": True, "verdict": "ok", "x": 1,
               "meta": {"generated_at": "T1", "source": sb.SOURCE_NAME}}
        s1 = sb.write_status(res, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        out = self.data_dir / sb.STATUS_FILENAME
        md5_1 = self._md5(out)

        res2 = dict(res)
        res2["meta"] = {"generated_at": "T2", "source": sb.SOURCE_NAME}
        s2 = sb.write_status(res2, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")
        self.assertEqual(self._md5(out), md5_1)

    def test_different_content_grows_history(self) -> None:
        r1 = {"available": True, "x": 1, "meta": {"generated_at": "T1", "source": "s"}}
        r2 = {"available": True, "x": 2, "meta": {"generated_at": "T2", "source": "s"}}
        ds1 = sb.write_status(r1, self.data_dir)
        ds2 = sb.write_status(r2, self.data_dir)
        self.assertEqual(ds1, "DATA_WRITTEN")
        self.assertEqual(ds2, "DATA_WRITTEN")
        doc = json.loads((self.data_dir / sb.STATUS_FILENAME).read_text())
        self.assertEqual(doc["x"], 2)
        self.assertEqual(len(doc["history"]), 1)
        self.assertEqual(doc["history"][0]["x"], 1)

    def test_history_rotation_exact(self) -> None:
        for i in range(sb.HISTORY_MAX + 50):
            r = {"available": True, "x": i, "meta": {"generated_at": str(i), "source": "s"}}
            sb.write_status(r, self.data_dir)
        doc = json.loads((self.data_dir / sb.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), sb.HISTORY_MAX)

    def test_no_tmp_left(self) -> None:
        r = {"available": True, "x": 1, "meta": {"generated_at": "T", "source": "s"}}
        sb.write_status(r, self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + list(self.data_dir.glob(".tmp*"))
        self.assertEqual(leftovers, [])

    def test_tolerant_broken_existing(self) -> None:
        out = self.data_dir / sb.STATUS_FILENAME
        out.write_text("not json {{{")
        r = {"available": True, "x": 1, "meta": {"generated_at": "T", "source": "s"}}
        s = sb.write_status(r, self.data_dir)
        self.assertEqual(s, "DATA_WRITTEN")
        doc = json.loads(out.read_text())
        self.assertEqual(doc["x"], 1)

    def test_real_result_round_trip(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        res = sb.build_structural_break(self.data_dir)
        s1 = sb.write_status(res, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        out = self.data_dir / sb.STATUS_FILENAME
        md5_1 = self._md5(out)
        # re-build (new generated_at) then write -> UNCHANGED + byte-identical
        res2 = sb.build_structural_break(self.data_dir)
        s2 = sb.write_status(res2, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")
        self.assertEqual(self._md5(out), md5_1)


# =============================================================================
# CLI -- direct main(argv)
# =============================================================================

class TestCLIDirect(_TmpBase):
    def _run_main(self, argv: List[str]) -> tuple[str, str, int]:
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ret = sb.main(argv)
                code = int(ret) if ret is not None else 0
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        return out.getvalue(), err.getvalue(), code

    def test_check_no_write(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        out, err, code = self._run_main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / sb.STATUS_FILENAME).exists())
        self.assertIn("structural_break", out)

    def test_default_is_check(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        out, err, code = self._run_main(["--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / sb.STATUS_FILENAME).exists())

    def test_run_writes_and_idempotent(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        o1, _, c1 = self._run_main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(c1, 0)
        self.assertTrue((self.data_dir / sb.STATUS_FILENAME).exists())
        self.assertIn("DATA_WRITTEN", o1)
        o2, _, c2 = self._run_main(["--run", "--data-dir", str(self.data_dir)])
        self.assertIn("DATA_UNCHANGED", o2)

    def test_junk_arg_exit0(self) -> None:
        out, err, code = self._run_main(["--frobnicate"])
        self.assertEqual(code, 0)
        self.assertIn("ERROR", err)

    def test_conflict_exit0(self) -> None:
        out, err, code = self._run_main(["--check", "--run"])
        self.assertEqual(code, 0)
        self.assertIn("mutually exclusive", err)


# =============================================================================
# CLI -- subprocess (real process, exit code + no traceback)
# =============================================================================

class TestCLISubprocess(_TmpBase):
    def _run(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.structural_break", *args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120,
        )

    def test_check_subprocess(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        cp = self._run(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(cp.returncode, 0)
        self.assertNotIn("Traceback", cp.stderr)

    def test_run_idempotent_subprocess(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05,
                                   0.1, 0.2, -0.1, 0.3, 0.0, 0.2])
        cp1 = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(cp1.returncode, 0)
        out = self.data_dir / sb.STATUS_FILENAME
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        cp2 = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(cp2.returncode, 0)
        self.assertIn("DATA_UNCHANGED", cp2.stdout)
        self.assertEqual(hashlib.md5(out.read_bytes()).hexdigest(), md5_1)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_junk_subprocess_exit0_no_traceback(self) -> None:
        cp = self._run(["--zzz"])
        self.assertEqual(cp.returncode, 0)
        self.assertNotIn("Traceback", cp.stderr)
        self.assertIn("ERROR", cp.stderr)

    def test_conflict_subprocess_exit0(self) -> None:
        cp = self._run(["--check", "--run"])
        self.assertEqual(cp.returncode, 0)
        self.assertNotIn("Traceback", cp.stderr)


# =============================================================================
# Import hygiene
# =============================================================================

class TestImportHygiene(unittest.TestCase):
    def test_no_forbidden_imports(self) -> None:
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        for p in (_MODULE_PATH, _TEST_PATH):
            with self.subTest(file=p.name):
                src = p.read_text(encoding="utf-8")
                viol = find_forbidden_imports(src, filename=str(p))
                self.assertEqual(viol, [], f"forbidden imports in {p}: {viol}")

    def test_py_compile_both(self) -> None:
        for p in (_MODULE_PATH, _TEST_PATH):
            with self.subTest(file=p.name):
                py_compile.compile(str(p), doraise=True)

    def test_no_dangerous_patterns(self) -> None:
        src = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad_modules = {"socket", "requests", "urllib", "http", "subprocess",
                       "anthropic", "openai"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], bad_modules)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(node.module.split(".")[0], bad_modules)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "compile"})

    def test_no_network_llm_strings(self) -> None:
        src = _MODULE_PATH.read_text(encoding="utf-8")
        for bad in ("import socket", "import requests", "import subprocess",
                    "anthropic", "openai", "eval(", "exec(", "pip install"):
            self.assertNotIn(bad, src)

    def test_reuse_by_import_marker(self) -> None:
        src = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("from spa_core.reporting.tear_sheet import content_fingerprint", src)
        self.assertIn("from spa_core.paper_trading.equity_curve import", src)

    def test_atomic_write_pattern(self) -> None:
        # write_status delegates atomicity to atomic_save (spa_core.utils.atomic)
        # which internally uses tempfile.mkstemp + os.replace. Verify the source
        # calls atomic_save rather than a raw open/write.
        src = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("atomic_save", src)


# =============================================================================
# e2e round-trip on the real repo data/ dir (must not raise; schema stable)
# =============================================================================

class TestRealDataRoundTrip(unittest.TestCase):
    def test_real_build_does_not_raise(self) -> None:
        real_data = _REPO_ROOT / "data"
        r = sb.build_structural_break(real_data)
        self.assertIsInstance(r, dict)
        self.assertIn("available", r)
        self.assertIn("verdict", r)
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))


if __name__ == "__main__":
    unittest.main(verbosity=2)
