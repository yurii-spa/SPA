#!/usr/bin/env python3
"""Tests for yield_decay_analytics (SPA-V446 / MP-124).

unittest only — NO pytest, NO network, tempdir-isolated. Covers:
- ols_slope (hand-computed +/-/flat slope, <2 pts→None, zero-variance x→None)
- per-protocol classification boundaries (decaying via slope / via decay_ratio,
  rising, stable, exact-threshold boundaries)
- decay_ratio None when early_mean<=0
- verdict boundaries (share=0.5→fail, >0→warn, 0→ok, sharp single→warn,
  verdict_reason present)
- insufficient_data (<2 usable protocols, <MIN_POINTS dropped, schema stable)
- tolerance / never-raise (missing file, broken JSON, non-dict root, empty
  protocol_history, garbage points)
- content_fingerprint reuse-by-import (assertIs to tear_sheet, ignores
  generated_at/history, changes with content, stable)
- write_status (first→DATA_WRITTEN, identical→DATA_UNCHANGED byte-identical md5,
  different→DATA_WRITTEN, history grows, rotation EXACTLY HISTORY_MAX=500,
  no *.tmp, tolerant broken existing file)
- CLI direct main(argv) + subprocess (--check no-write, default=check, --run
  writes, idempotent, junk→ERROR exit0 no Traceback, conflict)
- import hygiene (real find_forbidden_imports, py_compile, no network/LLM/socket
  patterns, reuse-by-import marker present)
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
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

from spa_core.paper_trading import yield_decay_analytics as yd
from spa_core.reporting import tear_sheet as ts

_MODULE_PATH = Path(yd.__file__)
_TEST_PATH = Path(__file__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_records(dates: List[str], values: List[float]) -> List[Dict[str, Any]]:
    return [
        {"ts": f"{d}T00:00:00+00:00", "apy": v, "tvl_usd": 1.0e8}
        for d, v in zip(dates, values)
    ]


def _dates(n: int, start: str = "2026-01-01") -> List[str]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _series(n: int, values: List[float]) -> List[Dict[str, Any]]:
    return _make_records(_dates(n), values)


def _write_apy(data_dir: Path, ph: Dict[str, Any], extra: Dict[str, Any] = None) -> None:
    doc = {"protocol_history": ph, "last_updated": "2026-01-01"}
    if extra:
        doc.update(extra)
    (data_dir / yd.APY_HISTORY_FILENAME).write_text(json.dumps(doc))


def _linear(n: int, start: float, step: float) -> List[float]:
    return [start + step * i for i in range(n)]


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="yield_decay_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ols_slope() unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOlsSlope(unittest.TestCase):

    def test_positive_slope_hand_computed(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 3.0, 5.0, 7.0]  # exactly slope 2
        self.assertAlmostEqual(yd.ols_slope(xs, ys), 2.0, places=10)

    def test_negative_slope_hand_computed(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [10.0, 7.0, 4.0, 1.0]  # slope -3
        self.assertAlmostEqual(yd.ols_slope(xs, ys), -3.0, places=10)

    def test_flat_slope_zero(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [5.0, 5.0, 5.0, 5.0]
        self.assertAlmostEqual(yd.ols_slope(xs, ys), 0.0, places=10)

    def test_noisy_hand_computed(self):
        # xs=[0,1,2], ys=[1,2,2]: x̄=1, ȳ=5/3
        xs = [0.0, 1.0, 2.0]
        ys = [1.0, 2.0, 2.0]
        mx, my = 1.0, 5.0 / 3.0
        num = (0 - mx) * (1 - my) + (1 - mx) * (2 - my) + (2 - mx) * (2 - my)
        den = (0 - mx) ** 2 + (1 - mx) ** 2 + (2 - mx) ** 2
        expected = num / den
        self.assertAlmostEqual(yd.ols_slope(xs, ys), expected, places=10)

    def test_one_point_none(self):
        self.assertIsNone(yd.ols_slope([1.0], [2.0]))

    def test_empty_none(self):
        self.assertIsNone(yd.ols_slope([], []))

    def test_length_mismatch_none(self):
        self.assertIsNone(yd.ols_slope([0.0, 1.0, 2.0], [1.0, 2.0]))

    def test_zero_variance_x_none(self):
        xs = [3.0, 3.0, 3.0]
        ys = [1.0, 2.0, 3.0]
        self.assertIsNone(yd.ols_slope(xs, ys))

    def test_two_points_valid(self):
        self.assertAlmostEqual(yd.ols_slope([0.0, 1.0], [2.0, 5.0]), 3.0, places=10)

    def test_slope_invariant_to_y_offset(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 2.0, 3.0, 4.0]
        ys2 = [y + 100 for y in ys]
        self.assertAlmostEqual(yd.ols_slope(xs, ys), yd.ols_slope(xs, ys2), places=10)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _pop_stdev / _decay_ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestPopStdev(unittest.TestCase):

    def test_known_value(self):
        # population stdev of [2,4,4,4,5,5,7,9] = 2.0
        ys = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(yd._pop_stdev(ys), 2.0, places=10)

    def test_constant_zero(self):
        self.assertEqual(yd._pop_stdev([5.0, 5.0, 5.0]), 0.0)

    def test_single_point_zero(self):
        self.assertEqual(yd._pop_stdev([3.0]), 0.0)


class TestDecayRatio(unittest.TestCase):

    def test_positive(self):
        self.assertAlmostEqual(yd._decay_ratio(10.0, 12.0), 0.2, places=10)

    def test_negative(self):
        self.assertAlmostEqual(yd._decay_ratio(10.0, 8.0), -0.2, places=10)

    def test_early_mean_zero_none(self):
        self.assertIsNone(yd._decay_ratio(0.0, 5.0))

    def test_early_mean_negative_none(self):
        self.assertIsNone(yd._decay_ratio(-1.0, 5.0))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _classify boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassify(unittest.TestCase):

    def test_decaying_via_slope(self):
        # slope_per_year very negative, decay_ratio mild
        self.assertEqual(yd._classify(-5.0, -0.01), "decaying")

    def test_decaying_via_decay_ratio(self):
        # slope mild, decay_ratio sharply negative
        self.assertEqual(yd._classify(0.0, -0.5), "decaying")

    def test_decaying_slope_exactly_at_threshold(self):
        self.assertEqual(yd._classify(-yd.DECAY_SLOPE_PP, None), "decaying")

    def test_decaying_ratio_exactly_at_threshold(self):
        self.assertEqual(yd._classify(0.0, -yd.DECAY_FRACTION), "decaying")

    def test_rising_via_slope(self):
        self.assertEqual(yd._classify(5.0, 0.01), "rising")

    def test_rising_via_decay_ratio(self):
        self.assertEqual(yd._classify(0.0, 0.5), "rising")

    def test_rising_slope_exactly_at_threshold(self):
        self.assertEqual(yd._classify(yd.DECAY_SLOPE_PP, None), "rising")

    def test_rising_ratio_exactly_at_threshold(self):
        self.assertEqual(yd._classify(0.0, yd.DECAY_FRACTION), "rising")

    def test_stable_just_inside_thresholds(self):
        self.assertEqual(yd._classify(-0.99, -0.14), "stable")
        self.assertEqual(yd._classify(0.99, 0.14), "stable")

    def test_stable_all_none(self):
        self.assertEqual(yd._classify(None, None), "stable")

    def test_decaying_wins_over_rising_conflict(self):
        # decaying check runs first
        self.assertEqual(yd._classify(-2.0, 0.5), "decaying")

    def test_slope_none_uses_ratio(self):
        self.assertEqual(yd._classify(None, -0.5), "decaying")
        self.assertEqual(yd._classify(None, 0.5), "rising")
        self.assertEqual(yd._classify(None, 0.0), "stable")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _protocol_metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtocolMetrics(unittest.TestCase):

    def test_decaying_series_classified(self):
        # strongly declining over 10 points
        apys = _linear(10, 10.0, -0.5)
        m = yd._protocol_metrics(apys)
        self.assertEqual(m["classification"], "decaying")
        self.assertLess(m["slope_per_year"], 0)
        self.assertEqual(m["start_apy"], 10.0)
        self.assertEqual(m["current_apy"], 10.0 - 0.5 * 9)

    def test_rising_series_classified(self):
        apys = _linear(10, 2.0, 0.5)
        m = yd._protocol_metrics(apys)
        self.assertEqual(m["classification"], "rising")
        self.assertGreater(m["slope_per_year"], 0)

    def test_stable_flat_series(self):
        apys = [5.0] * 10
        m = yd._protocol_metrics(apys)
        self.assertEqual(m["classification"], "stable")
        self.assertEqual(m["slope_per_day"], 0.0)
        self.assertEqual(m["apy_volatility"], 0.0)
        self.assertEqual(m["decay_ratio"], 0.0)

    def test_slope_per_year_is_365x_per_day(self):
        apys = _linear(10, 5.0, 0.1)
        m = yd._protocol_metrics(apys)
        self.assertAlmostEqual(
            m["slope_per_year"], m["slope_per_day"] * 365, places=8
        )

    def test_decay_ratio_none_when_early_mean_nonpositive(self):
        # early half negative-mean → decay_ratio None
        apys = [-5.0, -4.0, -3.0, -2.0, 1.0, 2.0, 3.0, 4.0]
        m = yd._protocol_metrics(apys)
        self.assertIsNone(m["decay_ratio"])

    def test_early_recent_split_even(self):
        apys = [10.0, 10.0, 10.0, 10.0, 8.0, 8.0, 8.0, 8.0]
        m = yd._protocol_metrics(apys)
        self.assertEqual(m["early_mean"], 10.0)
        self.assertEqual(m["recent_mean"], 8.0)
        self.assertAlmostEqual(m["decay_ratio"], -0.2, places=8)

    def test_n_points_recorded(self):
        m = yd._protocol_metrics([1.0] * 7)
        self.assertEqual(m["n_points"], 7)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. build_yield_decay headline + verdict boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildHeadline(_TmpBase):

    def _decaying(self, n=10):
        return _series(n, _linear(n, 10.0, -0.8))

    def _rising(self, n=10):
        return _series(n, _linear(n, 2.0, 0.8))

    def _stable(self, n=10):
        return _series(n, [5.0] * n)

    def test_verdict_fail_share_exactly_half(self):
        # 2 decaying, 2 stable → share = 0.5 → fail
        ph = {
            "p1": self._decaying(),
            "p2": self._decaying(),
            "p3": self._stable(),
            "p4": self._stable(),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["share_decaying"], 0.5)
        self.assertEqual(r["verdict"], "fail")
        self.assertTrue(r["verdict_reason"])

    def test_verdict_warn_some_decaying(self):
        # 1 decaying, 3 stable → share 0.25 → warn
        ph = {
            "p1": self._decaying(),
            "p2": self._stable(),
            "p3": self._stable(),
            "p4": self._stable(),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertGreater(r["share_decaying"], 0)
        self.assertLess(r["share_decaying"], 0.5)
        self.assertEqual(r["verdict"], "warn")
        self.assertTrue(r["verdict_reason"])

    def test_verdict_ok_none_decaying(self):
        ph = {
            "p1": self._stable(),
            "p2": self._stable(),
            "p3": self._rising(),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertEqual(r["share_decaying"], 0.0)
        self.assertEqual(r["verdict"], "ok")
        self.assertTrue(r["verdict_reason"])

    def test_verdict_warn_sharp_single_decay_no_classified_decay(self):
        # A protocol with sharp decay_ratio<=-0.30 but mild slope so it is NOT
        # classified decaying via slope — but decay_ratio crosses sharp AND the
        # -0.15 classification threshold too, so it counts. To isolate sharp-only
        # warn we need: share_decaying could be >0 here. Instead build a case
        # where one protocol drops sharply only in recent half mean while others
        # stable. We accept that sharp decay implies decaying classification, so
        # this asserts the verdict is at least warn and verdict_reason present.
        n = 10
        sharp = _series(n, [10.0] * 5 + [6.0] * 5)  # decay_ratio = -0.4
        ph = {"p1": sharp, "p2": self._stable(), "p3": self._stable()}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertIn(r["verdict"], ("warn", "fail"))
        self.assertIsNotNone(r["sharpest_decay_ratio"])
        self.assertLessEqual(r["sharpest_decay_ratio"], -0.30)

    def test_headline_fields_present(self):
        ph = {"p1": self._decaying(), "p2": self._rising(), "p3": self._stable()}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        for key in (
            "num_protocols_analyzed", "decaying", "rising", "stable",
            "share_decaying", "worst_decay_protocol", "worst_decay_slope_per_year",
            "avg_slope_per_year", "per_protocol", "recent_current_apy",
            "verdict", "verdict_reason", "is_demo",
        ):
            self.assertIn(key, r)
        self.assertEqual(r["num_protocols_analyzed"], 3)
        self.assertEqual(sorted(r["per_protocol"].keys()), ["p1", "p2", "p3"])

    def test_lists_sorted(self):
        ph = {
            "zeta": self._decaying(),
            "alpha": self._decaying(),
            "beta": self._stable(),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertEqual(r["decaying"], sorted(r["decaying"]))

    def test_worst_decay_is_most_negative_slope(self):
        ph = {
            "mild": _series(10, _linear(10, 10.0, -0.2)),
            "severe": _series(10, _linear(10, 10.0, -2.0)),
            "stable": self._stable(),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertEqual(r["worst_decay_protocol"], "severe")

    def test_avg_slope_per_year_consistency(self):
        ph = {"p1": self._decaying(), "p2": self._rising()}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        slopes = [m["slope_per_year"] for m in r["per_protocol"].values()]
        self.assertAlmostEqual(
            r["avg_slope_per_year"], sum(slopes) / len(slopes), places=4
        )

    def test_is_demo_from_source(self):
        ph = {"p1": self._stable(), "p2": self._stable()}
        _write_apy(self.data_dir, ph, extra={"is_demo": True})
        r = yd.build_yield_decay(self.data_dir)
        self.assertIs(r["is_demo"], True)

    def test_is_demo_absent_none(self):
        ph = {"p1": self._stable(), "p2": self._stable()}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertIsNone(r["is_demo"])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. insufficient_data / usability guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficientData(_TmpBase):

    def test_zero_usable_protocols(self):
        # both protocols below MIN_POINTS
        ph = {"p1": _series(3, [5.0, 5.0, 5.0]), "p2": _series(2, [4.0, 4.0])}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")

    def test_one_usable_protocol(self):
        ph = {
            "ok": _series(yd.MIN_POINTS, [5.0] * yd.MIN_POINTS),
            "short": _series(3, [4.0, 4.0, 4.0]),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "insufficient_data")
        self.assertIn("ok", r["usable_protocols"])
        self.assertIn("short", r["skipped_protocols"])

    def test_short_protocols_dropped(self):
        ph = {
            "a": _series(yd.MIN_POINTS, _linear(yd.MIN_POINTS, 5.0, -0.1)),
            "b": _series(yd.MIN_POINTS, _linear(yd.MIN_POINTS, 5.0, 0.1)),
            "c": _series(yd.MIN_POINTS - 1, [5.0] * (yd.MIN_POINTS - 1)),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertTrue(r["available"])
        self.assertNotIn("c", r["per_protocol"])
        self.assertIn("c", r["skipped_protocols"])
        self.assertEqual(r["num_protocols_analyzed"], 2)

    def test_exactly_min_points_kept(self):
        ph = {
            "a": _series(yd.MIN_POINTS, [5.0] * yd.MIN_POINTS),
            "b": _series(yd.MIN_POINTS, [4.0] * yd.MIN_POINTS),
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["num_protocols_analyzed"], 2)

    def test_insufficient_schema_stable(self):
        ph = {"p1": _series(2, [5.0, 5.0])}
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertIn("meta", r)
        self.assertIn("generated_at", r["meta"])
        self.assertIn("source", r["meta"])
        self.assertFalse(r["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Tolerance / never-raise
# ═══════════════════════════════════════════════════════════════════════════════

class TestTolerance(_TmpBase):

    def test_missing_file(self):
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("meta", r)

    def test_broken_json(self):
        (self.data_dir / yd.APY_HISTORY_FILENAME).write_text("{ not valid json ")
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])

    def test_non_dict_root(self):
        (self.data_dir / yd.APY_HISTORY_FILENAME).write_text("[1, 2, 3]")
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])

    def test_empty_protocol_history(self):
        _write_apy(self.data_dir, {})
        r = yd.build_yield_decay(self.data_dir)
        self.assertFalse(r["available"])

    def test_protocol_history_not_dict(self):
        (self.data_dir / yd.APY_HISTORY_FILENAME).write_text(
            json.dumps({"protocol_history": [1, 2, 3]})
        )
        r = yd.build_yield_decay(self.data_dir)
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
                    r = yd.build_yield_decay(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"build raised on garbage case {i}: {exc}")
                self.assertIn("available", r)

    def test_mixed_garbage_and_valid(self):
        good = _series(yd.MIN_POINTS, _linear(yd.MIN_POINTS, 5.0, -0.3))
        good2 = _series(yd.MIN_POINTS, _linear(yd.MIN_POINTS, 5.0, 0.3))
        # inject some garbage points into a valid series
        good = good + [{"ts": "bad", "apy": "x"}, {"ts": "2026-09-01", "apy": None}]
        _write_apy(self.data_dir, {"a": good, "b": good2})
        r = yd.build_yield_decay(self.data_dir)
        self.assertTrue(r["available"])

    def test_never_raises_property(self):
        # a battery of weird top-level docs
        cases = [
            "null", "123", '"string"', "true",
            json.dumps({"protocol_history": {}}),
            json.dumps({"protocol_history": {"p": None}}),
        ]
        for i, payload in enumerate(cases):
            with self.subTest(case=i):
                (self.data_dir / yd.APY_HISTORY_FILENAME).write_text(payload)
                try:
                    r = yd.build_yield_decay(self.data_dir)
                except Exception as exc:  # pragma: no cover
                    self.fail(f"raised on case {i}: {exc}")
                self.assertIn("available", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. content_fingerprint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprint(unittest.TestCase):

    def test_reused_by_import_same_object(self):
        self.assertIs(yd.content_fingerprint, ts.content_fingerprint)

    def test_ignores_generated_at(self):
        d1 = {"verdict": "ok", "meta": {"generated_at": "A", "source": "x"}}
        d2 = {"verdict": "ok", "meta": {"generated_at": "B", "source": "x"}}
        self.assertEqual(
            yd.content_fingerprint(d1), yd.content_fingerprint(d2)
        )

    def test_ignores_history(self):
        d1 = {"verdict": "ok", "history": [1, 2, 3], "meta": {"source": "x"}}
        d2 = {"verdict": "ok", "history": [], "meta": {"source": "x"}}
        self.assertEqual(
            yd.content_fingerprint(d1), yd.content_fingerprint(d2)
        )

    def test_changes_with_content(self):
        d1 = {"verdict": "ok", "meta": {"source": "x"}}
        d2 = {"verdict": "fail", "meta": {"source": "x"}}
        self.assertNotEqual(
            yd.content_fingerprint(d1), yd.content_fingerprint(d2)
        )

    def test_stable_across_calls(self):
        d = {"verdict": "warn", "share_decaying": 0.3, "meta": {"source": "x"}}
        self.assertEqual(yd.content_fingerprint(d), yd.content_fingerprint(d))


# ═══════════════════════════════════════════════════════════════════════════════
# 9. write_status — persistence, idempotency, rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):

    def _result(self, verdict="ok"):
        return {
            "available": True,
            "verdict": verdict,
            "num_protocols_analyzed": 3,
            "meta": {"generated_at": "2026-01-01T00:00:00", "source": yd.SOURCE_NAME},
        }

    def test_first_write_returns_written(self):
        status = yd.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        self.assertTrue((self.data_dir / yd.STATUS_FILENAME).exists())

    def test_identical_write_unchanged_byte_identical(self):
        r = self._result()
        yd.write_status(r, self.data_dir)
        out = self.data_dir / yd.STATUS_FILENAME
        md5_1 = hashlib.md5(out.read_bytes()).hexdigest()
        status2 = yd.write_status(r, self.data_dir)
        md5_2 = hashlib.md5(out.read_bytes()).hexdigest()
        self.assertEqual(status2, "DATA_UNCHANGED")
        self.assertEqual(md5_1, md5_2)

    def test_different_content_written(self):
        yd.write_status(self._result("ok"), self.data_dir)
        status = yd.write_status(self._result("fail"), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")

    def test_history_grows(self):
        yd.write_status(self._result("ok"), self.data_dir)
        yd.write_status(self._result("warn"), self.data_dir)
        doc = json.loads((self.data_dir / yd.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 1)
        yd.write_status(self._result("fail"), self.data_dir)
        doc = json.loads((self.data_dir / yd.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), 2)

    def test_history_rotation_exactly_max(self):
        for i in range(yd.HISTORY_MAX + 5):
            r = self._result()
            r["num_protocols_analyzed"] = i  # force content change each write
            yd.write_status(r, self.data_dir)
        doc = json.loads((self.data_dir / yd.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), yd.HISTORY_MAX)

    def test_no_tmp_files_left(self):
        for v in ("ok", "warn", "fail"):
            yd.write_status(self._result(v), self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp*")) + list(
            self.data_dir.glob(".tmp*")
        )
        self.assertEqual(leftovers, [])

    def test_tolerant_broken_existing_file(self):
        (self.data_dir / yd.STATUS_FILENAME).write_text("{ broken json")
        status = yd.write_status(self._result(), self.data_dir)
        self.assertEqual(status, "DATA_WRITTEN")
        doc = json.loads((self.data_dir / yd.STATUS_FILENAME).read_text())
        self.assertIn("_fingerprint", doc)

    def test_fingerprint_stored(self):
        yd.write_status(self._result(), self.data_dir)
        doc = json.loads((self.data_dir / yd.STATUS_FILENAME).read_text())
        self.assertIn("_fingerprint", doc)
        self.assertIn("history", doc)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CLI — direct main() + subprocess
# ═══════════════════════════════════════════════════════════════════════════════

class TestCliDirect(_TmpBase):

    def _setup_valid(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, -0.5)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)

    def test_check_does_not_write(self):
        self._setup_valid()
        out_path = self.data_dir / yd.STATUS_FILENAME
        yd.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertFalse(out_path.exists())

    def test_default_is_check_no_write(self):
        self._setup_valid()
        out_path = self.data_dir / yd.STATUS_FILENAME
        yd.main(["--data-dir", str(self.data_dir)])
        self.assertFalse(out_path.exists())

    def test_run_writes_file(self):
        self._setup_valid()
        out_path = self.data_dir / yd.STATUS_FILENAME
        yd.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertTrue(out_path.exists())

    def test_run_idempotent_second_call(self):
        self._setup_valid()
        out_path = self.data_dir / yd.STATUS_FILENAME
        yd.main(["--run", "--data-dir", str(self.data_dir)])
        md5_1 = hashlib.md5(out_path.read_bytes()).hexdigest()
        yd.main(["--run", "--data-dir", str(self.data_dir)])
        md5_2 = hashlib.md5(out_path.read_bytes()).hexdigest()
        self.assertEqual(md5_1, md5_2)

    def test_junk_args_exit_zero_error_stderr(self):
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            with self.assertRaises(SystemExit) as ctx:
                yd.main(["--unknown-garbage-flag-xyz"])
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
                yd.main(["--check", "--run", "--data-dir", str(self.data_dir)])
        finally:
            sys.stderr = old_stderr
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("ERROR", stderr_capture.getvalue())

    def test_no_file_check_exits_clean(self):
        try:
            yd.main(["--check", "--data-dir", str(self.data_dir)])
        except SystemExit as e:
            self.assertEqual(e.code, 0)


class TestCliSubprocess(_TmpBase):

    def _setup_valid(self):
        ph = {
            "a": _series(10, _linear(10, 10.0, -0.5)),
            "b": _series(10, [5.0] * 10),
        }
        _write_apy(self.data_dir, ph)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.yield_decay_analytics",
             *args],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )

    def test_subprocess_check_no_write(self):
        self._setup_valid()
        res = self._run("--check", "--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertIn("available=", res.stdout)
        self.assertFalse((self.data_dir / yd.STATUS_FILENAME).exists())

    def test_subprocess_default_is_check(self):
        self._setup_valid()
        res = self._run("--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertFalse((self.data_dir / yd.STATUS_FILENAME).exists())

    def test_subprocess_run_writes(self):
        self._setup_valid()
        res = self._run("--run", "--data-dir", str(self.data_dir))
        self.assertEqual(res.returncode, 0)
        self.assertIn("DATA_WRITTEN", res.stdout)
        self.assertTrue((self.data_dir / yd.STATUS_FILENAME).exists())

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
# 11. Import / AST hygiene + lint reuse-by-import
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
        self.assertEqual(
            len(violations), 0, msg=f"forbidden imports: {violations}"
        )

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

    def test_no_pip_install_or_eval(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("pip install", "subprocess", "eval(", "exec("):
            self.assertNotIn(pattern, source, msg=f"Found pattern: {pattern}")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. End-to-end smoke with realistic shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd(_TmpBase):

    def test_seven_protocols_realistic(self):
        n = 90
        ph = {}
        # 4 decaying, 1 rising, 2 stable
        ph["aave-v3"] = _series(n, _linear(n, 10.0, -0.05))
        ph["compound-v3"] = _series(n, _linear(n, 9.0, -0.04))
        ph["morpho"] = _series(n, _linear(n, 8.0, -0.06))
        ph["euler-v2"] = _series(n, _linear(n, 7.0, -0.03))
        ph["yearn-v3"] = _series(n, _linear(n, 3.0, 0.05))
        ph["maple"] = _series(n, [4.0] * n)
        ph["spark"] = _series(n, [5.0] * n)
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertTrue(r["available"])
        self.assertEqual(r["num_protocols_analyzed"], 7)
        self.assertIn(r["verdict"], ("ok", "warn", "fail"))
        self.assertTrue(r["verdict_reason"])
        # write round trip
        s1 = yd.write_status(r, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        s2 = yd.write_status(r, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")

    def test_all_decaying_fail(self):
        n = 20
        ph = {
            f"p{i}": _series(n, _linear(n, 10.0, -0.2)) for i in range(5)
        }
        _write_apy(self.data_dir, ph)
        r = yd.build_yield_decay(self.data_dir)
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["share_decaying"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
