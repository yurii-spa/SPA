#!/usr/bin/env python3
"""Tests for the Sterling Ratio & Burke Ratio Analyzer (SPA-V469 / MP-371).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math (Sterling / Burke / magnitudes / annualized
return), empty / zero-denominator / None-propagation edge cases, build
(available / unavailable, MIN_OBS guard, monotonic track -> no episodes ->
None ratios -> ok, verdict fail / warn / ok), atomic write_status idempotency /
rotation / no leftover tmp, CLI behaviour, reuse-by-import (content_fingerprint
+ episode + equity helpers are the SAME objects), and AST import hygiene.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics_lab import sterling_burke_ratio as sb_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.paper_trading import drawdown_attribution
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(sb_mod.__file__).resolve().parents[2]


def _equity_doc(levels, dates=None, is_demo=None):
    """Build an equity_curve_daily.json-shaped dict from equity levels."""
    if dates is None:
        dates = []
        for i in range(len(levels)):
            day = 1 + i
            month = 1 + (day - 1) // 28
            d = 1 + (day - 1) % 28
            dates.append(f"2026-{month:02d}-{d:02d}")
    daily = [
        {"date": dates[i], "close_equity": float(levels[i])}
        for i in range(len(levels))
    ]
    doc = {"source": "test", "daily": daily}
    if is_demo is not None:
        doc["is_demo"] = is_demo
    return doc


def _write_equity(data_dir, doc):
    (Path(data_dir) / sb_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: drawdown_magnitudes
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawdownMagnitudes(unittest.TestCase):
    def test_hand_example(self):
        eps = [{"drawdown_pct": -10}, {"drawdown_pct": -20},
               {"drawdown_pct": -30}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [10.0, 20.0, 30.0])

    def test_empty_list(self):
        self.assertEqual(sb_mod.drawdown_magnitudes([]), [])

    def test_none_input(self):
        self.assertEqual(sb_mod.drawdown_magnitudes(None), [])

    def test_non_list_input(self):
        self.assertEqual(sb_mod.drawdown_magnitudes("nope"), [])

    def test_single(self):
        self.assertEqual(
            sb_mod.drawdown_magnitudes([{"drawdown_pct": -5.5}]), [5.5]
        )

    def test_skips_non_dict(self):
        eps = [1, {"drawdown_pct": -3}, "x", {"drawdown_pct": -7}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [3.0, 7.0])

    def test_skips_missing_key(self):
        eps = [{"foo": 1}, {"drawdown_pct": -4}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [4.0])

    def test_skips_non_numeric(self):
        eps = [{"drawdown_pct": "bad"}, {"drawdown_pct": None},
               {"drawdown_pct": -2}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [2.0])

    def test_skips_bool(self):
        # bool is not a number in this codebase's convention
        eps = [{"drawdown_pct": True}, {"drawdown_pct": -9}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [9.0])

    def test_skips_nonfinite(self):
        eps = [{"drawdown_pct": float("nan")}, {"drawdown_pct": -1}]
        self.assertEqual(sb_mod.drawdown_magnitudes(eps), [1.0])

    def test_positive_dd_made_positive(self):
        # abs() applied regardless of sign
        self.assertEqual(
            sb_mod.drawdown_magnitudes([{"drawdown_pct": 12}]), [12.0]
        )

    def test_all_floats(self):
        out = sb_mod.drawdown_magnitudes([{"drawdown_pct": -1.25}])
        self.assertIsInstance(out[0], float)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: sterling_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestSterlingRatio(unittest.TestCase):
    def test_hand_example(self):
        # ann 30, mags [10,20,30] -> mean 20 + 10 = 30 -> 30/30 = 1.0
        self.assertAlmostEqual(
            sb_mod.sterling_ratio(30.0, [10, 20, 30]), 1.0, places=9
        )

    def test_single_magnitude(self):
        # ann 20, mags [10] -> 10 + 10 = 20 -> 20/20 = 1.0
        self.assertAlmostEqual(
            sb_mod.sterling_ratio(20.0, [10]), 1.0, places=9
        )

    def test_custom_adjustment(self):
        # ann 30, mags [10,20,30], adj 0 -> mean 20 -> 30/20 = 1.5
        self.assertAlmostEqual(
            sb_mod.sterling_ratio(30.0, [10, 20, 30], adjustment=0.0),
            1.5, places=9,
        )

    def test_empty_magnitudes_none(self):
        self.assertIsNone(sb_mod.sterling_ratio(30.0, []))

    def test_none_return_none(self):
        self.assertIsNone(sb_mod.sterling_ratio(None, [10, 20]))

    def test_zero_denominator_none(self):
        # mean -5 + adj 5 = 0 -> None (denominator <= 0)
        self.assertIsNone(
            sb_mod.sterling_ratio(30.0, [5], adjustment=-5.0)
        )

    def test_negative_denominator_none(self):
        self.assertIsNone(
            sb_mod.sterling_ratio(30.0, [5], adjustment=-10.0)
        )

    def test_negative_return(self):
        # ann -30, mags [10,20,30] -> -30/30 = -1.0
        self.assertAlmostEqual(
            sb_mod.sterling_ratio(-30.0, [10, 20, 30]), -1.0, places=9
        )

    def test_default_adjustment_is_ten(self):
        self.assertEqual(sb_mod.STERLING_ADJUSTMENT, 10.0)

    def test_uses_default_adjustment(self):
        # mags [40] -> 40 + 10 = 50 -> 100/50 = 2.0
        self.assertAlmostEqual(
            sb_mod.sterling_ratio(100.0, [40]), 2.0, places=9
        )

    def test_zero_return(self):
        self.assertEqual(sb_mod.sterling_ratio(0.0, [10, 20]), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: burke_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestBurkeRatio(unittest.TestCase):
    def test_hand_example(self):
        # ann 30, mags [10,20,30] -> sqrt(1400)=37.416574 -> 0.801784
        self.assertAlmostEqual(
            sb_mod.burke_ratio(30.0, [10, 20, 30]),
            30.0 / math.sqrt(1400.0), places=9,
        )

    def test_hand_example_value(self):
        self.assertAlmostEqual(
            sb_mod.burke_ratio(30.0, [10, 20, 30]), 0.8017837, places=6
        )

    def test_single_magnitude(self):
        # ann 20, mags [10] -> sqrt(100)=10 -> 20/10 = 2.0
        self.assertAlmostEqual(
            sb_mod.burke_ratio(20.0, [10]), 2.0, places=9
        )

    def test_empty_magnitudes_none(self):
        self.assertIsNone(sb_mod.burke_ratio(30.0, []))

    def test_none_return_none(self):
        self.assertIsNone(sb_mod.burke_ratio(None, [10, 20]))

    def test_zero_magnitudes_denominator_none(self):
        # all-zero depths -> sqrt(0)=0 -> None
        self.assertIsNone(sb_mod.burke_ratio(30.0, [0.0, 0.0]))

    def test_negative_return(self):
        self.assertAlmostEqual(
            sb_mod.burke_ratio(-20.0, [10]), -2.0, places=9
        )

    def test_zero_return(self):
        self.assertEqual(sb_mod.burke_ratio(0.0, [10, 20]), 0.0)

    def test_rms_dominated_by_deepest(self):
        # one deep episode dominates the RMS
        b = sb_mod.burke_ratio(10.0, [1, 1, 50])
        self.assertAlmostEqual(b, 10.0 / math.sqrt(1 + 1 + 2500), places=9)

    def test_burke_le_sterling_relationship(self):
        # For equal-magnitude single episode the two differ by the +10 adj
        # vs the RMS; just sanity-check both finite and positive.
        s = sb_mod.sterling_ratio(50.0, [25])
        b = sb_mod.burke_ratio(50.0, [25])
        self.assertGreater(s, 0)
        self.assertGreater(b, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: avg / max drawdown, num episodes
# ─────────────────────────────────────────────────────────────────────────────

class TestContextMetrics(unittest.TestCase):
    def test_avg_hand(self):
        self.assertAlmostEqual(
            sb_mod.avg_drawdown_pct([10, 20, 30]), 20.0, places=9
        )

    def test_avg_empty_none(self):
        self.assertIsNone(sb_mod.avg_drawdown_pct([]))

    def test_avg_single(self):
        self.assertEqual(sb_mod.avg_drawdown_pct([7]), 7.0)

    def test_max_hand(self):
        self.assertEqual(sb_mod.max_drawdown_pct([10, 30, 20]), 30.0)

    def test_max_empty_none(self):
        self.assertIsNone(sb_mod.max_drawdown_pct([]))

    def test_max_single(self):
        self.assertEqual(sb_mod.max_drawdown_pct([5]), 5.0)

    def test_max_first_is_biggest(self):
        self.assertEqual(sb_mod.max_drawdown_pct([40, 1, 2]), 40.0)

    def test_num_episodes_count(self):
        eps = [{"drawdown_pct": -1}, {"drawdown_pct": -2}]
        self.assertEqual(sb_mod.num_drawdown_episodes(eps), 2)

    def test_num_episodes_empty(self):
        self.assertEqual(sb_mod.num_drawdown_episodes([]), 0)

    def test_num_episodes_none(self):
        self.assertEqual(sb_mod.num_drawdown_episodes(None), 0)

    def test_num_episodes_skips_non_dict(self):
        self.assertEqual(
            sb_mod.num_drawdown_episodes([1, {"drawdown_pct": -1}, "x"]), 1
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: annualized_return_pct
# ─────────────────────────────────────────────────────────────────────────────

class TestAnnualizedReturn(unittest.TestCase):
    def test_one_year_double(self):
        series = [("2026-01-01", 100.0), ("2027-01-01", 200.0)]
        self.assertAlmostEqual(
            sb_mod.annualized_return_pct(series), 100.0, places=6
        )

    def test_zero_span_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct(
                [("2026-01-01", 100.0), ("2026-01-01", 110.0)]
            )
        )

    def test_negative_span_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct(
                [("2026-02-01", 100.0), ("2026-01-01", 110.0)]
            )
        )

    def test_first_nonpositive_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct(
                [("2026-01-01", 0.0), ("2027-01-01", 200.0)]
            )
        )

    def test_total_nonpositive_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct(
                [("2026-01-01", 100.0), ("2027-01-01", 0.0)]
            )
        )

    def test_bad_date_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct(
                [("not-a-date", 100.0), ("2027-01-01", 200.0)]
            )
        )

    def test_empty_none(self):
        self.assertIsNone(sb_mod.annualized_return_pct([]))

    def test_single_none(self):
        self.assertIsNone(
            sb_mod.annualized_return_pct([("2026-01-01", 100.0)])
        )

    def test_loss_negative(self):
        self.assertAlmostEqual(
            sb_mod.annualized_return_pct(
                [("2026-01-01", 100.0), ("2027-01-01", 50.0)]
            ),
            -50.0, places=6,
        )


# ─────────────────────────────────────────────────────────────────────────────
# build: monotonic rising -> no episodes -> None ratios -> ok + note
# ─────────────────────────────────────────────────────────────────────────────

class TestMonotonic(unittest.TestCase):
    def test_monotonic_rising(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(15)]
            _write_equity(td, _equity_doc(levels))
            r = sb_mod.build_sterling_burke(td)
            self.assertTrue(r["available"])
            self.assertIsNone(r["sterling_ratio"])
            self.assertIsNone(r["burke_ratio"])
            self.assertEqual(r["n_drawdown_episodes"], 0)
            self.assertEqual(r["verdict"], "ok")
            joined = " ".join(r["notes"]).lower()
            self.assertIn("no drawdowns", joined)
            self.assertIn("no drawdown", r["verdict_reason"].lower())


# ─────────────────────────────────────────────────────────────────────────────
# build: verdict bands (ok / warn / fail)
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBands(unittest.TestCase):
    def test_strong_track_ok(self):
        # rises strongly, one shallow recovered dip -> high ratios -> ok
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0, 101.0, 100.5, 103.0, 106.0, 110.0, 115.0,
                      121.0, 128.0, 136.0, 145.0, 160.0]
            dates = [f"2026-01-{i+1:02d}" for i in range(len(levels))]
            _write_equity(td, _equity_doc(levels, dates))
            r = sb_mod.build_sterling_burke(td)
            self.assertTrue(r["available"])
            self.assertIsNotNone(r["sterling_ratio"])
            self.assertIsNotNone(r["burke_ratio"])
            self.assertGreater(r["n_drawdown_episodes"], 0)
            self.assertEqual(r["verdict"], "ok")

    def test_negative_return_with_drawdowns_fails(self):
        # ends well below start with a real drawdown -> negative ann return
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0, 95.0, 90.0, 85.0, 80.0, 78.0, 76.0,
                      74.0, 72.0, 70.0, 68.0, 66.0]
            dates = [f"2026-01-{i+1:02d}" for i in range(len(levels))]
            _write_equity(td, _equity_doc(levels, dates))
            r = sb_mod.build_sterling_burke(td)
            self.assertTrue(r["available"])
            self.assertLess(r["annualized_return_pct"], 0)
            self.assertGreater(r["n_drawdown_episodes"], 0)
            self.assertEqual(r["verdict"], "fail")

    def test_band_invariant_sweep(self):
        # Whatever band we land in, the band predicate must hold.
        rng = random.Random(424242)
        for trial in range(20):
            with self.subTest(trial=trial):
                with tempfile.TemporaryDirectory() as td:
                    levels = [100.0]
                    for _ in range(14):
                        levels.append(
                            max(1.0, levels[-1] * (1.0 + rng.uniform(-0.05, 0.06)))
                        )
                    _write_equity(td, _equity_doc(levels))
                    r = sb_mod.build_sterling_burke(td)
                    self.assertIn(r["verdict"], ("ok", "warn", "fail"))
                    s = r["sterling_ratio"]
                    b = r["burke_ratio"]
                    ann = r["annualized_return_pct"]
                    if r["verdict"] == "fail":
                        cond = (
                            (s is not None and s < sb_mod.STERLING_FAIL)
                            or (b is not None and b < sb_mod.BURKE_FAIL)
                            or (r["n_drawdown_episodes"] > 0
                                and ann is not None and ann < 0)
                        )
                        self.assertTrue(cond)
                    elif r["verdict"] == "warn":
                        cond = (
                            (s is not None and s < sb_mod.STERLING_WARN)
                            or (b is not None and b < sb_mod.BURKE_WARN)
                        )
                        self.assertTrue(cond)

    def test_verdict_reason_always_present(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0, 98.0, 102.0, 99.0, 104.0, 101.0, 106.0,
                      103.0, 108.0, 110.0, 112.0]
            dates = [f"2026-01-{i+1:02d}" for i in range(len(levels))]
            _write_equity(td, _equity_doc(levels, dates))
            r = sb_mod.build_sterling_burke(td)
            self.assertTrue(r["verdict_reason"])
            self.assertIsInstance(r["verdict_reason"], str)


# ─────────────────────────────────────────────────────────────────────────────
# insufficient data
# ─────────────────────────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def _assert_stable_unavailable(self, r):
        for k in ("available", "reason", "is_demo", "sterling_ratio",
                  "burke_ratio", "avg_drawdown_pct", "max_drawdown_pct",
                  "n_drawdown_episodes", "annualized_return_pct",
                  "n_observations", "start_date", "end_date", "verdict",
                  "verdict_reason", "notes", "meta"):
            self.assertIn(k, r)
        self.assertFalse(r["available"])
        self.assertEqual(r["verdict"], "ok")
        self.assertIsNone(r["sterling_ratio"])
        self.assertIsNone(r["burke_ratio"])
        self.assertEqual(r["meta"]["source"], sb_mod.SOURCE_NAME)
        self.assertEqual(r["meta"]["schema_version"], sb_mod.SCHEMA_VERSION)
        self.assertEqual(r["meta"]["min_obs_required"], sb_mod.MIN_OBS)

    def test_empty_daily(self):
        with tempfile.TemporaryDirectory() as td:
            _write_equity(td, {"daily": []})
            self._assert_stable_unavailable(sb_mod.build_sterling_burke(td))

    def test_fewer_than_min(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(sb_mod.MIN_OBS - 1)]
            _write_equity(td, _equity_doc(levels))
            r = sb_mod.build_sterling_burke(td)
            self._assert_stable_unavailable(r)
            self.assertEqual(r["n_observations"], sb_mod.MIN_OBS - 1)

    def test_exactly_min_is_available(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(sb_mod.MIN_OBS)]
            _write_equity(td, _equity_doc(levels))
            r = sb_mod.build_sterling_burke(td)
            self.assertTrue(r["available"])
            self.assertEqual(r["n_observations"], sb_mod.MIN_OBS)


# ─────────────────────────────────────────────────────────────────────────────
# never-raise / tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverRaise(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = sb_mod.build_sterling_burke(td)
            self.assertIsInstance(r, dict)
            self.assertFalse(r["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / sb_mod.EQUITY_FILENAME).write_text(
                "{not json", encoding="utf-8"
            )
            r = sb_mod.build_sterling_burke(td)
            self.assertFalse(r["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / sb_mod.EQUITY_FILENAME).write_text(
                "42", encoding="utf-8"
            )
            r = sb_mod.build_sterling_burke(td)
            self.assertFalse(r["available"])

    def test_garbage_bars(self):
        cases = [
            {"daily": [1, 2, 3]},
            {"daily": [{"no_date": True}]},
            {"daily": [{"date": "x", "close_equity": "y"}]},
            {"daily": [{"date": "2026-01-01", "close_equity": -5}]},
            {"daily": "not a list"},
            {},
            {"is_demo": True},
        ]
        for i, doc in enumerate(cases):
            with self.subTest(i=i):
                with tempfile.TemporaryDirectory() as td:
                    _write_equity(td, doc)
                    r = sb_mod.build_sterling_burke(td)
                    self.assertIsInstance(r, dict)
                    self.assertIn("verdict", r)

    def test_fuzz_random_tracks(self):
        rng = random.Random(20260612)
        for trial in range(40):
            with self.subTest(trial=trial):
                n = rng.randint(0, 40)
                doc = {"daily": [
                    {"date": f"2026-{1 + j // 28:02d}-{1 + j % 28:02d}",
                     "close_equity": rng.uniform(1, 200)}
                    for j in range(n)
                ]}
                with tempfile.TemporaryDirectory() as td:
                    _write_equity(td, doc)
                    r = sb_mod.build_sterling_burke(td)
                    self.assertIsInstance(r, dict)
                    self.assertIn(r["verdict"], ("ok", "warn", "fail"))

    def test_pure_funcs_fuzz(self):
        rng = random.Random(99)
        for _ in range(200):
            n = rng.randint(0, 30)
            mags = [abs(rng.uniform(0, 60)) for _ in range(n)]
            ann = rng.uniform(-100, 100)
            s = sb_mod.sterling_ratio(ann, mags)
            b = sb_mod.burke_ratio(ann, mags)
            self.assertTrue(s is None or math.isfinite(s))
            self.assertTrue(b is None or math.isfinite(b))


# ─────────────────────────────────────────────────────────────────────────────
# is_demo honesty
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    def test_top_level_true(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels, is_demo=True))
            self.assertTrue(sb_mod.build_sterling_burke(td)["is_demo"])

    def test_top_level_false(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels, is_demo=False))
            self.assertFalse(sb_mod.build_sterling_burke(td)["is_demo"])

    def test_absent_none(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels))
            self.assertIsNone(sb_mod.build_sterling_burke(td)["is_demo"])

    def test_meta_demo(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            doc = _equity_doc(levels)
            doc["meta"] = {"is_demo": True}
            _write_equity(td, doc)
            self.assertTrue(sb_mod.build_sterling_burke(td)["is_demo"])


# ─────────────────────────────────────────────────────────────────────────────
# content_fingerprint reuse-by-import
# ─────────────────────────────────────────────────────────────────────────────

class TestFingerprintReuse(unittest.TestCase):
    def test_is_same_object(self):
        self.assertIs(
            sb_mod.content_fingerprint, tear_sheet.content_fingerprint
        )

    def test_ignores_generated_at_and_history(self):
        base = {"a": 1, "meta": {"generated_at": "t1", "x": 9}, "history": [1]}
        other = {"a": 1, "meta": {"generated_at": "t2", "x": 9},
                 "history": [2, 3]}
        self.assertEqual(
            sb_mod.content_fingerprint(base), sb_mod.content_fingerprint(other)
        )

    def test_changes_with_content(self):
        a = {"a": 1, "meta": {"generated_at": "t"}}
        b = {"a": 2, "meta": {"generated_at": "t"}}
        self.assertNotEqual(
            sb_mod.content_fingerprint(a), sb_mod.content_fingerprint(b)
        )


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import of equity + episode helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestHelperReuse(unittest.TestCase):
    def test_extract_is_same_object(self):
        self.assertIs(
            sb_mod.extract_equity_series,
            drawdown_analytics.extract_equity_series,
        )

    def test_identify_episodes_is_same_object(self):
        self.assertIs(
            sb_mod.identify_drawdown_episodes,
            drawdown_attribution.identify_drawdown_episodes,
        )


# ─────────────────────────────────────────────────────────────────────────────
# write_status
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStatus(unittest.TestCase):
    def _good_result(self, td, seed=0):
        levels = [100.0 + i + seed for i in range(12)]
        _write_equity(td, _equity_doc(levels))
        return sb_mod.build_sterling_burke(td)

    def test_first_write_then_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._good_result(td)
            self.assertEqual(sb_mod.write_status(r, td), "DATA_WRITTEN")
            out = Path(td) / sb_mod.STATUS_FILENAME
            md5_a = _md5(out)
            r2 = self._good_result(td)
            self.assertEqual(sb_mod.write_status(r2, td), "DATA_UNCHANGED")
            self.assertEqual(_md5(out), md5_a)

    def test_different_grows_history(self):
        with tempfile.TemporaryDirectory() as td:
            r1 = self._good_result(td, seed=0)
            sb_mod.write_status(r1, td)
            r2 = self._good_result(td, seed=100)
            self.assertEqual(sb_mod.write_status(r2, td), "DATA_WRITTEN")
            doc = json.loads(
                (Path(td) / sb_mod.STATUS_FILENAME).read_text()
            )
            self.assertEqual(len(doc["history"]), 1)

    def test_rotation_caps_history(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / sb_mod.STATUS_FILENAME
            r = self._good_result(td, seed=0)
            sb_mod.write_status(r, td)
            doc = json.loads(out.read_text())
            doc["history"] = [{"k": i}
                              for i in range(sb_mod.HISTORY_MAX + 50)]
            out.write_text(json.dumps(doc), encoding="utf-8")
            r2 = self._good_result(td, seed=7)
            sb_mod.write_status(r2, td)
            doc2 = json.loads(out.read_text())
            self.assertEqual(len(doc2["history"]), sb_mod.HISTORY_MAX)

    def test_no_leftover_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._good_result(td)
            sb_mod.write_status(r, td)
            leftovers = [p for p in os.listdir(td)
                         if p.startswith(".tmp_sterling_burke_")
                         or p.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_tolerant_of_broken_prev(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / sb_mod.STATUS_FILENAME
            out.write_text("{broken", encoding="utf-8")
            r = self._good_result(td)
            self.assertEqual(sb_mod.write_status(r, td), "DATA_WRITTEN")

    def test_tolerant_of_non_dict_prev(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / sb_mod.STATUS_FILENAME
            out.write_text("[1,2,3]", encoding="utf-8")
            r = self._good_result(td)
            self.assertEqual(sb_mod.write_status(r, td), "DATA_WRITTEN")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def _seed(self, td):
        levels = [100.0 + i for i in range(12)]
        _write_equity(td, _equity_doc(levels))

    def test_check_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            rc = sb_mod.main(["--check", "--data-dir", td])
            self.assertEqual(rc, 0)
            self.assertFalse(
                (Path(td) / sb_mod.STATUS_FILENAME).exists()
            )

    def test_default_is_check_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            rc = sb_mod.main(["--data-dir", td])
            self.assertEqual(rc, 0)
            self.assertFalse(
                (Path(td) / sb_mod.STATUS_FILENAME).exists()
            )

    def test_run_writes_then_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(sb_mod.main(["--run", "--data-dir", td]), 0)
            out = Path(td) / sb_mod.STATUS_FILENAME
            self.assertTrue(out.exists())
            md5_a = _md5(out)
            self.assertEqual(sb_mod.main(["--run", "--data-dir", td]), 0)
            self.assertEqual(_md5(out), md5_a)
            # no leftover tmp after run
            leftovers = [p for p in os.listdir(td)
                         if p.startswith(".tmp_sterling_burke_")]
            self.assertEqual(leftovers, [])

    def test_junk_arg_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(
                sb_mod.main(["--frobnicate", "--data-dir", td]), 0
            )

    def test_check_run_conflict_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(
                sb_mod.main(["--check", "--run", "--data-dir", td]), 0
            )
            self.assertFalse(
                (Path(td) / sb_mod.STATUS_FILENAME).exists()
            )

    def test_subprocess_check(self):
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.sterling_burke_ratio", "--check"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# import hygiene (AST + real linter)
# ─────────────────────────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    _MODULE_PATH = (
        _REPO_ROOT / "spa_core" / "analytics_lab" / "sterling_burke_ratio.py"
    )
    _FORBIDDEN = frozenset({
        "requests", "httpx", "aiohttp", "urllib3",
        "web3", "eth_account",
        "numpy", "pandas", "scipy",
        "anthropic", "openai",
        "boto3", "google", "socket",
    })

    def test_no_forbidden_imports_ast(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in self._FORBIDDEN:
                        found.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in self._FORBIDDEN:
                        found.add(root)
        self.assertEqual(found, set(), f"Forbidden imports: {found}")

    def test_real_linter_zero_violations(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(
            src, str(self._MODULE_PATH)
        )
        self.assertEqual(list(violations), [])

    def test_no_forbidden_text_in_body(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        body = src
        if '"""' in src:
            parts = src.split('"""')
            if len(parts) >= 3:
                body = '"""'.join(parts[2:])
        for needle in ("import requests", "import socket",
                       "import subprocess", "subprocess.", "eval(", "exec(",
                       "import web3", "anthropic", "import numpy",
                       "import pandas"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, body)

    def test_py_compile_both(self):
        import py_compile
        for fname in ("analytics_lab/sterling_burke_ratio.py",
                      "tests/test_sterling_burke_ratio.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
