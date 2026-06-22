#!/usr/bin/env python3
"""Tests for apy_dispersion_analytics (SPA-V447 / MP-125).

unittest only — NO pytest, NO network, tempdir-isolated. Covers:
- ols_slope (hand-computed +/-/flat, <2→None, len mismatch→None, zero-var x→None)
- _pop_stdev / _median known values
- date alignment (full overlap, partial intersection, disjoint→empty, single→none)
- per-date cross-section math (hand-computed spread/mean/cv/best_protocol; cv None
  when mean<=0)
- headline fields present & consistent (avg/median/current/min/max spread; trend
  sign; leader_share in [0,1]; leadership_counts sums to num_dates;
  recent_dispersion bounded <=90)
- verdict boundaries (current_spread just below/at/above LOW_SPREAD_PP; spread
  trend at/below CONVERGING_SLOPE_PP_YR; leader_share at 0.8; verdict_reason
  always present)
- insufficient_data (0/1 usable protocol, < MIN_DATES aligned, short dropped,
  schema stable)
- tolerance / never-raise (missing file, broken JSON, non-dict root, empty
  protocol_history, garbage records, never-raises property)
- content_fingerprint reuse-by-import (assertIs to tear_sheet, ignores
  generated_at/history, changes with content, stable)
- write_status (first→DATA_WRITTEN, identical→DATA_UNCHANGED byte-identical md5,
  different→DATA_WRITTEN, history grows, rotation EXACTLY HISTORY_MAX=500,
  no *.tmp, tolerant broken existing file)
- CLI direct main(argv) + subprocess (--check no-write, default=check, --run
  writes, idempotent, junk→ERROR exit0 no Traceback, conflict)
- import hygiene (real find_forbidden_imports, py_compile, no network/LLM/socket
  patterns, reuse-by-import marker present, atomic-write pattern present)
- end-to-end smoke 7-protocol / ~30-date round trip
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import apy_dispersion_analytics as ad
from spa_core.reporting import tear_sheet as ts

_MODULE_PATH = Path(ad.__file__)
_TEST_PATH = Path(__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _records(dates: List[str], values: List[float]) -> List[Dict[str, Any]]:
    return [
        {"ts": f"{d}T00:00:00+00:00", "apy": v, "tvl_usd": 1.0e8}
        for d, v in zip(dates, values)
    ]


def _series(n: int, values: List[float], start: str = "2026-01-01") -> List[Dict[str, Any]]:
    return _records(_dates(n, start), values)


def _write_apy(data_dir: Path, ph: Dict[str, Any], extra: Dict[str, Any] = None) -> None:
    doc = {"protocol_history": ph, "last_updated": "2026-01-01"}
    if extra:
        doc.update(extra)
    (data_dir / ad.APY_HISTORY_FILENAME).write_text(json.dumps(doc))


def _linear(n: int, start: float, step: float) -> List[float]:
    return [start + step * i for i in range(n)]


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="apy_dispersion_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ols_slope()
# ═══════════════════════════════════════════════════════════════════════════════

class TestOlsSlope(unittest.TestCase):

    def test_positive_slope_hand_computed(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 3.0, 5.0, 7.0]  # slope 2
        self.assertAlmostEqual(ad.ols_slope(xs, ys), 2.0, places=10)

    def test_negative_slope_hand_computed(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [10.0, 7.0, 4.0, 1.0]  # slope -3
        self.assertAlmostEqual(ad.ols_slope(xs, ys), -3.0, places=10)

    def test_flat_slope_zero(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [5.0, 5.0, 5.0, 5.0]
        self.assertAlmostEqual(ad.ols_slope(xs, ys), 0.0, places=10)

    def test_noisy_hand_computed(self):
        xs = [0.0, 1.0, 2.0]
        ys = [1.0, 2.0, 2.0]
        mx, my = 1.0, 5.0 / 3.0
        num = (0 - mx) * (1 - my) + (1 - mx) * (2 - my) + (2 - mx) * (2 - my)
        den = (0 - mx) ** 2 + (1 - mx) ** 2 + (2 - mx) ** 2
        self.assertAlmostEqual(ad.ols_slope(xs, ys), num / den, places=10)

    def test_one_point_none(self):
        self.assertIsNone(ad.ols_slope([1.0], [2.0]))

    def test_empty_none(self):
        self.assertIsNone(ad.ols_slope([], []))

    def test_length_mismatch_none(self):
        self.assertIsNone(ad.ols_slope([0.0, 1.0, 2.0], [1.0, 2.0]))

    def test_zero_variance_x_none(self):
        self.assertIsNone(ad.ols_slope([3.0, 3.0, 3.0], [1.0, 2.0, 3.0]))

    def test_two_points_valid(self):
        self.assertAlmostEqual(ad.ols_slope([0.0, 1.0], [2.0, 5.0]), 3.0, places=10)

    def test_slope_invariant_to_y_offset(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 2.0, 3.0, 4.0]
        ys2 = [y + 100 for y in ys]
        self.assertAlmostEqual(ad.ols_slope(xs, ys), ad.ols_slope(xs, ys2), places=10)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _pop_stdev / _median
# ═══════════════════════════════════════════════════════════════════════════════

class TestPopStdev(unittest.TestCase):

    def test_known_value(self):
        ys = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]  # pop stdev = 2.0
        self.assertAlmostEqual(ad._pop_stdev(ys), 2.0, places=10)

    def test_constant_zero(self):
        self.assertEqual(ad._pop_stdev([5.0, 5.0, 5.0]), 0.0)

    def test_single_point_zero(self):
        self.assertEqual(ad._pop_stdev([3.0]), 0.0)

    def test_empty_zero(self):
        self.assertEqual(ad._pop_stdev([]), 0.0)

    def test_two_points_hand_computed(self):
        # mean=5, var=((4-5)^2+(6-5)^2)/2=1 → stdev=1
        self.assertAlmostEqual(ad._pop_stdev([4.0, 6.0]), 1.0, places=10)


class TestMedian(unittest.TestCase):

    def test_odd(self):
        self.assertEqual(ad._median([3.0, 1.0, 2.0]), 2.0)

    def test_even(self):
        self.assertEqual(ad._median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_single(self):
        self.assertEqual(ad._median([7.0]), 7.0)

    def test_empty_none(self):
        self.assertIsNone(ad._median([]))

    def test_unsorted_input(self):
        self.assertEqual(ad._median([9.0, 1.0, 5.0, 3.0, 7.0]), 5.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _cv
# ═══════════════════════════════════════════════════════════════════════════════

class TestCv(unittest.TestCase):

    def test_normal(self):
        self.assertAlmostEqual(ad._cv(10.0, 2.0), 0.2, places=10)

    def test_mean_zero_none(self):
        self.assertIsNone(ad._cv(0.0, 1.0))

    def test_mean_negative_none(self):
        self.assertIsNone(ad._cv(-5.0, 1.0))

    def test_zero_stdev(self):
        self.assertEqual(ad._cv(5.0, 0.0), 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Date alignment
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlignment(unittest.TestCase):

    def test_full_overlap(self):
        dm = {
            "a": {"2026-01-01": 1.0, "2026-01-02": 2.0, "2026-01-03": 3.0},
            "b": {"2026-01-01": 4.0, "2026-01-02": 5.0, "2026-01-03": 6.0},
        }
        self.assertEqual(
            ad._aligned_dates(dm),
            ["2026-01-01", "2026-01-02", "2026-01-03"],
        )

    def test_partial_overlap_intersection(self):
        dm = {
            "a": {"2026-01-01": 1.0, "2026-01-02": 2.0, "2026-01-03": 3.0},
            "b": {"2026-01-02": 5.0, "2026-01-03": 6.0, "2026-01-04": 7.0},
        }
        self.assertEqual(ad._aligned_dates(dm), ["2026-01-02", "2026-01-03"])

    def test_disjoint_empty(self):
        dm = {
            "a": {"2026-01-01": 1.0, "2026-01-02": 2.0},
            "b": {"2026-02-01": 5.0, "2026-02-02": 6.0},
        }
        self.assertEqual(ad._aligned_dates(dm), [])

    def test_single_protocol_uses_own_dates(self):
        dm = {"a": {"2026-01-01": 1.0, "2026-01-02": 2.0}}
        self.assertEqual(ad._aligned_dates(dm), ["2026-01-01", "2026-01-02"])

    def test_empty_map(self):
        self.assertEqual(ad._aligned_dates({}), [])

    def test_three_protocols_intersection(self):
        dm = {
            "a": {"d1": 1.0, "d2": 2.0, "d3": 3.0},
            "b": {"d2": 2.0, "d3": 3.0, "d4": 4.0},
            "c": {"d2": 2.0, "d3": 3.0, "d5": 5.0},
        }
        self.assertEqual(ad._aligned_dates(dm), ["d2", "d3"])

    def test_to_date_map(self):
        pairs = [("2026-01-01", 1.0), ("2026-01-02", 2.0)]
        self.assertEqual(ad._to_date_map(pairs), {"2026-01-01": 1.0, "2026-01-02": 2.0})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _cross_section math
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossSection(unittest.TestCase):

    def test_hand_computed_basic(self):
        protocols = ["a", "b", "c"]
        apys = [2.0, 4.0, 6.0]
        cs = ad._cross_section(protocols, apys)
        self.assertEqual(cs["min_apy"], 2.0)
        self.assertEqual(cs["max_apy"], 6.0)
        self.assertEqual(cs["spread"], 4.0)
        self.assertEqual(cs["mean_apy"], 4.0)
        # pop stdev of [2,4,6]: var = (4+0+4)/3 = 8/3 → sqrt = 1.632993...
        self.assertAlmostEqual(cs["stdev"], math.sqrt(8.0 / 3.0), places=6)
        self.assertAlmostEqual(cs["cv"], math.sqrt(8.0 / 3.0) / 4.0, places=6)
        self.assertEqual(cs["best_protocol"], "c")

    def test_best_protocol_argmax(self):
        cs = ad._cross_section(["x", "y", "z"], [5.0, 9.0, 1.0])
        self.assertEqual(cs["best_protocol"], "y")

    def test_best_protocol_tie_first_wins(self):
        cs = ad._cross_section(["x", "y"], [5.0, 5.0])
        self.assertEqual(cs["best_protocol"], "x")

    def test_zero_spread_identical(self):
        cs = ad._cross_section(["a", "b"], [3.0, 3.0])
        self.assertEqual(cs["spread"], 0.0)
        self.assertEqual(cs["stdev"], 0.0)
        self.assertEqual(cs["cv"], 0.0)

    def test_cv_none_when_mean_nonpositive(self):
        cs = ad._cross_section(["a", "b"], [-2.0, 2.0])  # mean 0
        self.assertEqual(cs["mean_apy"], 0.0)
        self.assertIsNone(cs["cv"])

    def test_cv_none_when_mean_negative(self):
        cs = ad._cross_section(["a", "b"], [-5.0, -1.0])
        self.assertLess(cs["mean_apy"], 0)
        self.assertIsNone(cs["cv"])

    def test_single_protocol_cross_section(self):
        cs = ad._cross_section(["only"], [4.2])
        self.assertEqual(cs["spread"], 0.0)
        self.assertEqual(cs["mean_apy"], 4.2)
        self.assertEqual(cs["best_protocol"], "only")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. build_apy_dispersion headline + consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildHeadline(_TmpBase):

    def _good_two(self, n=10):
        # a stays high, b stays low → constant spread of ~5
        return {
            "a": _series(n, [10.0] * n),
            "b": _series(n, [5.0] * n),
        }

    def test_headline_fields_present(self):
        _write_apy(self.data_dir, self._good_two())
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])
        for key in (
            "verdict", "verdict_reason", "num_dates", "num_protocols",
            "protocols", "start_date", "end_date", "avg_spread_pp",
            "median_spread_pp", "current_spread_pp", "min_spread_pp",
            "max_spread_pp", "avg_cv", "current_cv", "spread_trend_per_year",
            "most_frequent_leader", "leader_share", "leadership_counts",
            "recent_dispersion", "skipped_protocols", "is_demo", "notes", "meta",
        ):
            self.assertIn(key, r)

    def test_protocols_sorted(self):
        ph = {
            "zeta": _series(10, [10.0] * 10),
            "alpha": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(r["protocols"], ["alpha", "zeta"])

    def test_spread_constant_consistency(self):
        _write_apy(self.data_dir, self._good_two(10))
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertAlmostEqual(r["current_spread_pp"], 5.0, places=6)
        self.assertAlmostEqual(r["avg_spread_pp"], 5.0, places=6)
        self.assertAlmostEqual(r["median_spread_pp"], 5.0, places=6)
        self.assertAlmostEqual(r["min_spread_pp"], 5.0, places=6)
        self.assertAlmostEqual(r["max_spread_pp"], 5.0, places=6)

    def test_min_max_bound_avg(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, 0.5)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertLessEqual(r["min_spread_pp"], r["avg_spread_pp"])
        self.assertLessEqual(r["avg_spread_pp"], r["max_spread_pp"])
        self.assertLessEqual(r["min_spread_pp"], r["median_spread_pp"])
        self.assertLessEqual(r["median_spread_pp"], r["max_spread_pp"])

    def test_current_spread_is_last_date(self):
        # widening spread → current is the largest
        ph = {
            "a": _series(10, _linear(10, 10.0, 1.0)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertAlmostEqual(r["current_spread_pp"], r["max_spread_pp"], places=6)

    def test_spread_trend_sign_widening(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, 1.0)),  # rising → widening gap
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertGreater(r["spread_trend_per_year"], 0)

    def test_spread_trend_sign_converging(self):
        ph = {
            "a": _series(10, _linear(10, 15.0, -1.0)),  # falling toward b
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertLess(r["spread_trend_per_year"], 0)

    def test_leader_share_in_unit_interval(self):
        _write_apy(self.data_dir, self._good_two(20))
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertGreaterEqual(r["leader_share"], 0.0)
        self.assertLessEqual(r["leader_share"], 1.0)

    def test_leadership_counts_sums_to_num_dates(self):
        ph = {
            "a": _series(20, _linear(20, 10.0, -0.5)),
            "b": _series(20, _linear(20, 5.0, 0.5)),
            "c": _series(20, [7.0] * 20),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(sum(r["leadership_counts"].values()), r["num_dates"])

    def test_most_frequent_leader_is_argmax_count(self):
        # a always best → a leads every date
        _write_apy(self.data_dir, self._good_two(15))
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(r["most_frequent_leader"], "a")
        self.assertAlmostEqual(r["leader_share"], 1.0, places=6)

    def test_recent_dispersion_bounded(self):
        n = 120
        ph = {
            "a": _series(n, _linear(n, 10.0, 0.01)),
            "b": _series(n, [5.0] * n),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(r["num_dates"], n)
        self.assertLessEqual(len(r["recent_dispersion"]), 90)
        self.assertEqual(len(r["recent_dispersion"]), 90)
        # the tail ends at the last date
        self.assertEqual(r["recent_dispersion"][-1]["date"], r["end_date"])

    def test_recent_dispersion_entry_shape(self):
        _write_apy(self.data_dir, self._good_two(10))
        r = ad.build_apy_dispersion(self.data_dir)
        entry = r["recent_dispersion"][0]
        self.assertEqual(
            sorted(entry.keys()),
            ["best_protocol", "cv", "date", "mean", "spread"],
        )

    def test_date_range(self):
        _write_apy(self.data_dir, self._good_two(10))
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(r["start_date"], "2026-01-01")
        self.assertEqual(r["num_dates"], 10)

    def test_num_protocols(self):
        ph = {
            "a": _series(10, [10.0] * 10),
            "b": _series(10, [7.0] * 10),
            "c": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertEqual(r["num_protocols"], 3)

    def test_avg_cv_skips_none(self):
        # mean ≤ 0 on some dates → cv None there; avg_cv only over usable
        ph = {
            "a": _series(10, [-2.0] * 5 + [4.0] * 5),
            "b": _series(10, [2.0] * 5 + [8.0] * 5),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        # first 5 dates mean=0 → cv None; last 5 mean=6 → cv defined
        self.assertIsNotNone(r["avg_cv"])

    def test_avg_cv_all_none(self):
        # every date has mean <= 0 → avg_cv None
        ph = {
            "a": _series(10, [-3.0] * 10),
            "b": _series(10, [-1.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertIsNone(r["avg_cv"])
        self.assertIsNone(r["current_cv"])

    def test_partial_date_overlap_aligned(self):
        ph = {
            "a": _records(_dates(12, "2026-01-01"), [10.0] * 12),
            "b": _records(_dates(12, "2026-01-04"), [5.0] * 12),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        # overlap is 2026-01-04 .. 2026-01-12 → 9 dates
        self.assertTrue(r["available"])
        self.assertEqual(r["num_dates"], 9)

    def test_is_demo_from_source(self):
        _write_apy(self.data_dir, self._good_two(10), extra={"is_demo": True})
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertIs(r["is_demo"], True)

    def test_is_demo_absent_none(self):
        _write_apy(self.data_dir, self._good_two(10))
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertIsNone(r["is_demo"])

    def test_floats_rounded_6dp(self):
        ph = {
            "a": _series(8, [10.0 / 3.0] * 8),
            "b": _series(8, [1.0 / 7.0] * 8),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        for key in ("avg_spread_pp", "current_spread_pp", "min_spread_pp"):
            val = r[key]
            self.assertEqual(round(val, 6), val)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Verdict boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdict(_TmpBase):

    def test_fail_spread_below_low_threshold(self):
        # constant tiny spread of 0.3 < 0.5 → fail
        ph = {
            "a": _series(10, [5.3] * 10),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertLess(r["current_spread_pp"], ad.LOW_SPREAD_PP)
        self.assertEqual(r["verdict"], "fail")
        self.assertTrue(r["verdict_reason"])

    def test_at_low_threshold_not_fail(self):
        # spread exactly 0.5 — NOT < 0.5 → not fail (ok or warn)
        ph = {
            "a": _series(10, [5.5] * 10),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertAlmostEqual(r["current_spread_pp"], 0.5, places=6)
        self.assertNotEqual(r["verdict"], "fail")
        self.assertTrue(r["verdict_reason"])

    def test_above_low_threshold_not_fail(self):
        ph = {
            "a": _series(10, [6.0] * 10),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertGreater(r["current_spread_pp"], ad.LOW_SPREAD_PP)
        self.assertNotEqual(r["verdict"], "fail")

    def test_warn_converging_slope(self):
        # spread shrinks rapidly but stays above the fail floor at the end
        n = 30
        # a falls from 20 to ~6, b flat at 5 → spread 15 → ~1, big neg trend,
        # final spread ~1 > 0.5 so not fail
        a_vals = _linear(n, 20.0, -14.0 / (n - 1))
        ph = {
            "a": _series(n, a_vals),
            "b": _series(n, [5.0] * n),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertLessEqual(r["spread_trend_per_year"], ad.CONVERGING_SLOPE_PP_YR)
        self.assertGreaterEqual(r["current_spread_pp"], ad.LOW_SPREAD_PP)
        self.assertEqual(r["verdict"], "warn")

    def test_warn_leader_share_high(self):
        # a always best (leader_share=1.0 ≥ 0.8), spread stays wide & stable
        ph = {
            "a": _series(20, [12.0] * 20),
            "b": _series(20, [5.0] * 20),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertGreaterEqual(r["leader_share"], ad.LEADER_SHARE_WARN)
        # stable wide spread → no converging slope, but leader concentration warns
        self.assertEqual(r["verdict"], "warn")

    def test_leader_share_at_exactly_threshold_warns(self):
        # 5 protocols, a leads 4/5 dates? We engineer leader_share = 0.8 exactly.
        # 5 dates: a leads on 4, b leads on 1.
        a_vals = [10.0, 10.0, 10.0, 10.0, 1.0]
        b_vals = [5.0, 5.0, 5.0, 5.0, 9.0]
        # spreads: 5,5,5,5,8 → all > 0.5 so not fail; flat-ish slope
        ph = {
            "a": _records(_dates(5), a_vals),
            "b": _records(_dates(5), b_vals),
        }
        _write_apy(self.data_dir, ph)
        # MIN_DATES is 7 → this would be insufficient. Extend to 10 dates with
        # the leader pattern preserved at 0.8.
        a_vals = [10.0] * 8 + [1.0, 1.0]   # a leads 8/10 = 0.8
        b_vals = [5.0] * 8 + [9.0, 9.0]
        ph = {
            "a": _records(_dates(10), a_vals),
            "b": _records(_dates(10), b_vals),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertAlmostEqual(r["leader_share"], 0.8, places=6)
        self.assertEqual(r["verdict"], "warn")

    def test_ok_broad_stable(self):
        # wide stable spread, balanced leadership, flat slope → ok
        n = 20
        # alternate which protocol leads to keep leader_share < 0.8
        a_vals = [10.0 if i % 2 == 0 else 1.0 for i in range(n)]
        b_vals = [1.0 if i % 2 == 0 else 10.0 for i in range(n)]
        ph = {
            "a": _records(_dates(n), a_vals),
            "b": _records(_dates(n), b_vals),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertGreaterEqual(r["current_spread_pp"], ad.LOW_SPREAD_PP)
        self.assertLess(r["leader_share"], ad.LEADER_SHARE_WARN)
        self.assertEqual(r["verdict"], "ok")
        self.assertTrue(r["verdict_reason"])

    def test_verdict_reason_always_present(self):
        for ph in (
            {"a": _series(10, [5.1] * 10), "b": _series(10, [5.0] * 10)},  # fail
            {"a": _series(10, [12.0] * 10), "b": _series(10, [5.0] * 10)},  # warn leader
        ):
            _write_apy(self.data_dir, ph)
            r = ad.build_apy_dispersion(self.data_dir)
            self.assertTrue(r["verdict_reason"])
            self.assertIn(r["verdict"], ("ok", "warn", "fail"))


# ═══════════════════════════════════════════════════════════════════════════════
# 8. insufficient_data / usability guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficientData(_TmpBase):

    def test_zero_usable_protocols(self):
        ph = {"a": _series(3, [5.0] * 3), "b": _series(2, [4.0] * 2)}
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")

    def test_one_usable_protocol(self):
        ph = {
            "ok": _series(ad.MIN_POINTS, [5.0] * ad.MIN_POINTS),
            "short": _series(3, [4.0] * 3),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        self.assertIn("ok", r["usable_protocols"])
        self.assertIn("short", r["skipped_protocols"])

    def test_short_protocol_dropped_but_overall_ok(self):
        n = 10
        ph = {
            "a": _series(n, _linear(n, 5.0, 0.1)),
            "b": _series(n, _linear(n, 8.0, -0.1)),
            "c": _series(ad.MIN_POINTS - 1, [5.0] * (ad.MIN_POINTS - 1)),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])
        self.assertNotIn("c", r["protocols"])
        self.assertIn("c", r["skipped_protocols"])
        self.assertEqual(r["num_protocols"], 2)

    def test_insufficient_aligned_dates(self):
        # both usable (>= MIN_POINTS each) but disjoint dates → 0 aligned < MIN_DATES
        ph = {
            "a": _records(_dates(ad.MIN_POINTS, "2026-01-01"), [5.0] * ad.MIN_POINTS),
            "b": _records(_dates(ad.MIN_POINTS, "2026-06-01"), [4.0] * ad.MIN_POINTS),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")

    def test_partial_overlap_below_min_dates(self):
        # each protocol has MIN_POINTS points but only a few aligned dates
        n = ad.MIN_POINTS
        # a: days 0..n-1; b: days starting late so overlap < MIN_DATES
        ph = {
            "a": _records(_dates(n, "2026-01-01"), [5.0] * n),
            "b": _records(_dates(n, "2026-01-05"), [4.0] * n),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        # overlap = 2026-01-05 .. 2026-01-07 = 3 dates < MIN_DATES(7)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        self.assertIn("min_dates_required", r)

    def test_exactly_min_dates_kept(self):
        n = ad.MIN_DATES
        ph = {
            "a": _series(n, [10.0] * n),
            "b": _series(n, [5.0] * n),
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["num_dates"], n)

    def test_insufficient_schema_stable(self):
        ph = {"p1": _series(3, [5.0] * 3)}
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        for key in (
            "available", "reason", "min_points_required", "min_dates_required",
            "usable_protocols", "skipped_protocols", "is_demo", "notes", "meta",
        ):
            self.assertIn(key, r)
        self.assertIn("generated_at", r["meta"])
        self.assertIn("source", r["meta"])
        self.assertFalse(r["available"])

    def test_no_valid_series_insufficient(self):
        _write_apy(self.data_dir, {"a": "not-a-list", "b": 42})
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Tolerance / never-raise
# ═══════════════════════════════════════════════════════════════════════════════

class TestTolerance(_TmpBase):

    def test_missing_file(self):
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("meta", r)

    def test_broken_json(self):
        (self.data_dir / ad.APY_HISTORY_FILENAME).write_text("{ not valid json ")
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])

    def test_non_dict_root(self):
        (self.data_dir / ad.APY_HISTORY_FILENAME).write_text("[1, 2, 3]")
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])

    def test_empty_protocol_history(self):
        _write_apy(self.data_dir, {})
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])

    def test_protocol_history_not_dict(self):
        (self.data_dir / ad.APY_HISTORY_FILENAME).write_text(
            json.dumps({"protocol_history": [1, 2, 3]})
        )
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertFalse(r["available"])

    def test_garbage_points_subtests_never_raise(self):
        garbage_records = [
            [{"ts": "2026-01-01", "apy": "not-a-number"}],
            [{"ts": "2026-01-01", "apy": None}],
            [{"ts": "2026-01-01", "apy": float("nan")}],
            [{"ts": "2026-01-01", "apy": float("inf")}],
            [{"ts": "2026-01-01", "apy": True}],   # bool excluded
            [{"no_ts": True, "apy": 5.0}],
            ["not-a-dict", 42, None],
            [],
            "not-a-list",
            {"nested": "dict"},
        ]
        for i, recs in enumerate(garbage_records):
            with self.subTest(case=i):
                _write_apy(self.data_dir, {"p1": recs, "p2": recs})
                try:
                    r = ad.build_apy_dispersion(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"build raised on garbage case {i}: {exc}")
                self.assertIn("available", r)

    def test_mixed_garbage_and_valid(self):
        good_a = _series(10, _linear(10, 10.0, -0.3))
        good_b = _series(10, _linear(10, 5.0, 0.3))
        good_a = good_a + [{"ts": "bad", "apy": "x"}, {"ts": "2026-09-01", "apy": None}]
        _write_apy(self.data_dir, {"a": good_a, "b": good_b})
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])

    def test_never_raises_property(self):
        cases = [
            "null", "123", '"string"', "true",
            json.dumps({"protocol_history": {}}),
            json.dumps({"protocol_history": {"p": None}}),
            json.dumps({"protocol_history": {"p": [{"ts": 5, "apy": 1.0}]}}),
        ]
        for i, payload in enumerate(cases):
            with self.subTest(case=i):
                (self.data_dir / ad.APY_HISTORY_FILENAME).write_text(payload)
                try:
                    r = ad.build_apy_dispersion(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"raised on case {i}: {exc}")
                self.assertIn("available", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. content_fingerprint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def test_reused_by_import_same_object(self):
        self.assertIs(ad.content_fingerprint, ts.content_fingerprint)

    def test_ignores_generated_at(self):
        d1 = {"verdict": "ok", "meta": {"generated_at": "A", "source": "x"}}
        d2 = {"verdict": "ok", "meta": {"generated_at": "B", "source": "x"}}
        self.assertEqual(ad.content_fingerprint(d1), ad.content_fingerprint(d2))

    def test_ignores_history(self):
        d1 = {"verdict": "ok", "history": [1, 2, 3], "meta": {"source": "x"}}
        d2 = {"verdict": "ok", "history": [], "meta": {"source": "x"}}
        self.assertEqual(ad.content_fingerprint(d1), ad.content_fingerprint(d2))

    def test_changes_with_content(self):
        d1 = {"verdict": "ok", "meta": {"source": "x"}}
        d2 = {"verdict": "fail", "meta": {"source": "x"}}
        self.assertNotEqual(ad.content_fingerprint(d1), ad.content_fingerprint(d2))

    def test_stable_across_calls(self):
        d = {"verdict": "warn", "current_spread_pp": 0.3, "meta": {"source": "x"}}
        self.assertEqual(ad.content_fingerprint(d), ad.content_fingerprint(d))


# ═══════════════════════════════════════════════════════════════════════════════
# 11. write_status — persistence, idempotency, rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _result(self, verdict="ok"):
        return {
            "available": True,
            "verdict": verdict,
            "num_protocols": 3,
            "meta": {"generated_at": "2026-01-01T00:00:00", "source": ad.SOURCE_NAME},
        }

    def test_first_write_returns_written(self):
        status = ad.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        self.assertTrue((self.data_dir / ad.STATUS_FILENAME).exists())

    def test_identical_write_unchanged_byte_identical(self):
        r = self._result()
        ad.write_status(r, self.data_dir)
        out = self.data_dir / ad.STATUS_FILENAME
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        status2 = ad.write_status(r, self.data_dir)
        md5_2 = hashlib.md5(out.read_bytes()).hexdigest()
        self.assertEqual(status2, "DATA_UNCHANGED")
        self.assertEqual(md5_1, md5_2)

    def test_different_content_written(self):
        ad.write_status(self._result("ok"), self.data_dir)
        status = ad.write_status(self._result("fail"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_history_grows(self):
        ad.write_status(self._result("ok"), self.data_dir)
        ad.write_status(self._result("warn"), self.data_dir)
        doc = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 1)
        ad.write_status(self._result("fail"), self.data_dir)
        doc = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 2)

    def test_history_rotation_exactly_max(self):
        for i in range(ad.HISTORY_MAX + 5):
            r = self._result()
            r["num_protocols"] = i  # force content change each write
            ad.write_status(r, self.data_dir)
        doc = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), ad.HISTORY_MAX)

    def test_no_tmp_files_left(self):
        for v in ("ok", "warn", "fail"):
            ad.write_status(self._result(v), self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp*")) + list(
            self.data_dir.glob(".tmp*")
        )
        self.assertEqual(leftovers, [])

    def test_tolerant_broken_existing_file(self):
        (self.data_dir / ad.STATUS_FILENAME).write_text("{ broken json")
        status = ad.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        doc = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertIn("_fingerprint", doc)

    def test_tolerant_non_dict_existing_file(self):
        (self.data_dir / ad.STATUS_FILENAME).write_text("[1,2,3]")
        status = ad.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_fingerprint_stored(self):
        ad.write_status(self._result(), self.data_dir)
        doc = json.loads((self.data_dir / ad.STATUS_FILENAME).read_text())
        self.assertIn("_fingerprint", doc)
        self.assertIn("history", doc)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. CLI — direct main() + subprocess
# ═══════════════════════════════════════════════════════════════════════════════

class TestCliDirect(_TmpBase):

    def _setup_valid(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, -0.2)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)

    def test_check_does_not_write(self):
        self._setup_valid()
        out_path = self.data_dir / ad.STATUS_FILENAME
        ad.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertFalse(out_path.exists())

    def test_default_is_check_no_write(self):
        self._setup_valid()
        out_path = self.data_dir / ad.STATUS_FILENAME
        ad.main(["--data-dir", str(self.data_dir)])
        self.assertFalse(out_path.exists())

    def test_run_writes_file(self):
        self._setup_valid()
        out_path = self.data_dir / ad.STATUS_FILENAME
        ad.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertTrue(out_path.exists())

    def test_run_idempotent_second_call(self):
        self._setup_valid()
        out_path = self.data_dir / ad.STATUS_FILENAME
        ad.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(out_path.read_bytes()).hexdigest()
        ad.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(out_path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_args_exit_zero_error_stderr(self):
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            with self.assertRaises(SystemExit) as ctx:
                ad.main(["--unknown-garbage-flag-xyz"])
        finally:
            sys.stderr = old_stderr
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("ERROR", stderr_capture.getvalue())

    def test_check_run_conflict_exit_zero_error(self):
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            with self.assertRaises(SystemExit) as ctx:
                ad.main(["--check", "--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stderr = old_stderr
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("ERROR", stderr_capture.getvalue())

    def test_no_file_check_exits_clean(self):
        try:
            ad.main(["--check", "--data-dir", str(self.data_dir)])
        except SystemExit as e:
            self.assertEqual(e.code, 0)


class TestCliSubprocess(_TmpBase):

    def _setup_valid(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, -0.2)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.apy_dispersion_analytics", *args],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )

    def test_subprocess_check_no_write(self):
        self._setup_valid()
        res = self._run("--check", "--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertIn("available=", res.stdout)
        self.assertFalse((self.data_dir / ad.STATUS_FILENAME).exists())

    def test_subprocess_default_is_check(self):
        self._setup_valid()
        res = self._run("--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertFalse((self.data_dir / ad.STATUS_FILENAME).exists())

    def test_subprocess_run_writes(self):
        self._setup_valid()
        res = self._run("--run", "--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertIn("DATA_WRITTEN", res.stdout)
        self.assertTrue((self.data_dir / ad.STATUS_FILENAME).exists())

    def test_subprocess_run_idempotent(self):
        self._setup_valid()
        self._run("--run", "--data-dir", str(self.data_dir))
        res2 = self._run("--run", "--data-dir", str(self.data_dir))
        self.assertEqual(res2.returncode, 0)
        self.assertIn("DATA_UNCHANGED", res2.stdout)

    def test_subprocess_junk_arg_exit_zero_no_traceback(self):
        res = self._run("--totally-bogus-arg")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ERROR", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_subprocess_conflict_exit_zero_no_traceback(self):
        res = self._run("--check", "--run")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ERROR", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_subprocess_no_tmp_leak(self):
        self._setup_valid()
        self._run("--run", "--data-dir", str(self.data_dir))
        self._run("--run", "--data-dir", str(self.data_dir))
        leftovers = list(self.data_dir.glob("*.tmp*")) + list(
            self.data_dir.glob(".tmp*")
        )
        self.assertEqual(leftovers, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Import / AST hygiene + lint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_TOP = {
    "requests", "httpx", "aiohttp", "urllib3",
    "web3", "eth_account",
    "numpy", "pandas", "scipy",
    "anthropic", "openai",
    "socket",
}


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

    def test_no_forbidden_top_level_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        used = self._collect_imports(source)
        bad = used & _FORBIDDEN_TOP
        self.assertEqual(bad, set(), msg=f"Forbidden imports found: {bad}")

    def test_real_find_forbidden_imports_zero_violations(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        source = _MODULE_PATH.read_text(encoding="utf-8")
        violations = find_forbidden_imports(source, str(_MODULE_PATH))
        self.assertEqual(len(violations), 0, msg=f"forbidden imports: {violations}")

    def test_module_compiles(self):
        import py_compile
        py_compile.compile(str(_MODULE_PATH), doraise=True)

    def test_test_file_compiles(self):
        import py_compile
        py_compile.compile(str(_TEST_PATH), doraise=True)

    def test_no_network_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("requests.get", "requests.post", "urllib.request",
                        "http.client", "socket.connect", "socket.socket"):
            self.assertNotIn(pattern, source, msg=f"Found network pattern: {pattern}")

    def test_no_llm_sdk_patterns(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("anthropic.", "openai.", "from anthropic", "from openai"):
            self.assertNotIn(pattern, source, msg=f"Found LLM SDK pattern: {pattern}")

    def test_atomic_write_pattern_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        # Atomic write contract: centralized atomic_save (tmp + os.replace) OR
        # the legacy inline tempfile.mkstemp + os.replace pattern.
        self.assertTrue(
            "atomic_save" in source
            or ("tempfile.mkstemp" in source and "os.replace" in source),
            "module must write atomically (atomic_save or tempfile.mkstemp+os.replace)",
        )

    def test_reuse_by_import_marker_present(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.reporting.tear_sheet import content_fingerprint", source
        )

    def test_no_pip_install_or_eval_or_subprocess(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("pip install", "subprocess", "eval(", "exec("):
            self.assertNotIn(pattern, source, msg=f"Found pattern: {pattern}")


# ═══════════════════════════════════════════════════════════════════════════════
# 14. End-to-end smoke
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd(_TmpBase):

    def test_seven_protocols_realistic(self):
        n = 30
        ph = {}
        ph["aave-v3-usdc-ethereum"] = _series(n, _linear(n, 6.0, -0.01))
        ph["aave-v3-usdt-ethereum"] = _series(n, _linear(n, 5.5, 0.005))
        ph["compound-v3-usdc-ethereum"] = _series(n, [4.0] * n)
        ph["euler-v2-usdc-ethereum"] = _series(n, _linear(n, 8.0, -0.02))
        ph["maple-usdc-ethereum"] = _series(n, _linear(n, 9.0, 0.01))
        ph["morpho-usdc-ethereum"] = _series(n, [7.0] * n)
        ph["yearn-v3-usdc-ethereum"] = _series(n, _linear(n, 5.0, 0.0))
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["num_protocols"], 7)
        self.assertEqual(r["num_dates"], n)
        self.assertIn(r["verdict"], ("ok", "warn", "fail"))
        self.assertTrue(r["verdict_reason"])
        self.assertEqual(sum(r["leadership_counts"].values()), n)
        self.assertLessEqual(len(r["recent_dispersion"]), 90)
        # write round trip
        s1 = ad.write_status(r, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        s2 = ad.write_status(r, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")

    def test_collapsed_opportunity_set_fails(self):
        # all 7 protocols converge to nearly the same APY → tiny spread → fail
        n = 30
        ph = {
            f"p{i}": _series(n, [5.0 + 0.01 * i] * n) for i in range(7)
        }
        _write_apy(self.data_dir, ph)
        r = ad.build_apy_dispersion(self.data_dir)
        self.assertTrue(r["available"])
        self.assertLess(r["current_spread_pp"], ad.LOW_SPREAD_PP)
        self.assertEqual(r["verdict"], "fail")


if __name__ == "__main__":
    unittest.main(verbosity=2)
