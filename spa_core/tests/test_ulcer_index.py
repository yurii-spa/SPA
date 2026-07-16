#!/usr/bin/env python3
"""Tests for the Ulcer Index & Martin Ratio Analyzer (SPA-V461 / MP-146).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math, monotonic / drawdown verdicts at the
documented thresholds, insufficient-data + never-raise / tolerance, reuse-by-
import (content_fingerprint + equity helpers), atomic write_status idempotency
/ rotation, CLI behaviour (direct + subprocess), and import hygiene.
"""
from __future__ import annotations

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

from spa_core.analytics_lab import ulcer_index as ui_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(ui_mod.__file__).resolve().parents[2]


def _equity_doc(levels, dates=None, is_demo=None):
    """Build an equity_curve_daily.json-shaped dict from equity levels."""
    if dates is None:
        # consecutive days starting 2026-01-01
        dates = []
        base = 1
        for i in range(len(levels)):
            day = base + i
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
    (Path(data_dir) / ui_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: ulcer_index
# ─────────────────────────────────────────────────────────────────────────────

class TestUlcerIndexPure(unittest.TestCase):
    def test_hand_example(self):
        ui = ui_mod.ulcer_index([0, -10, -20])
        self.assertAlmostEqual(ui, 12.909944487358056, places=9)

    def test_all_zeros_is_zero(self):
        self.assertEqual(ui_mod.ulcer_index([0, 0, 0, 0]), 0.0)

    def test_single_zero(self):
        self.assertEqual(ui_mod.ulcer_index([0]), 0.0)

    def test_empty_is_none(self):
        self.assertIsNone(ui_mod.ulcer_index([]))

    def test_constant_depth_equals_depth(self):
        # RMS of a constant series equals its magnitude.
        for v in (1.0, 7.5, 15.0, 23.4):
            with self.subTest(v=v):
                ui = ui_mod.ulcer_index([-v] * 11)
                self.assertAlmostEqual(ui, v, places=9)

    def test_sign_irrelevant_squares(self):
        # squaring removes sign; positive (shouldn't occur) handled same way
        a = ui_mod.ulcer_index([-3, -4])
        self.assertAlmostEqual(a, math.sqrt((9 + 16) / 2), places=9)

    def test_single_value(self):
        self.assertAlmostEqual(ui_mod.ulcer_index([-5]), 5.0, places=9)

    def test_never_raises_floats(self):
        self.assertIsInstance(ui_mod.ulcer_index([-1.5, -2.5, 0.0]), float)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: pain_index
# ─────────────────────────────────────────────────────────────────────────────

class TestPainIndexPure(unittest.TestCase):
    def test_hand_example(self):
        self.assertAlmostEqual(ui_mod.pain_index([0, -10, -20]), 10.0, places=9)

    def test_empty_none(self):
        self.assertIsNone(ui_mod.pain_index([]))

    def test_all_zero(self):
        self.assertEqual(ui_mod.pain_index([0, 0]), 0.0)

    def test_abs_mean(self):
        self.assertAlmostEqual(ui_mod.pain_index([-2, -4, -6]), 4.0, places=9)

    def test_single(self):
        self.assertAlmostEqual(ui_mod.pain_index([-9]), 9.0, places=9)

    def test_pain_le_ulcer(self):
        # Pain index (mean abs) <= Ulcer index (RMS) by power-mean inequality.
        uw = [0, -3, -10, -1, -22, -5]
        self.assertLessEqual(ui_mod.pain_index(uw), ui_mod.ulcer_index(uw) + 1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: max_drawdown_pct
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxDrawdownPure(unittest.TestCase):
    def test_hand_example(self):
        self.assertEqual(ui_mod.max_drawdown_pct([0, -10, -20]), -20.0)

    def test_empty_none(self):
        self.assertIsNone(ui_mod.max_drawdown_pct([]))

    def test_all_zero(self):
        self.assertEqual(ui_mod.max_drawdown_pct([0, 0, 0]), 0.0)

    def test_returns_negative(self):
        self.assertEqual(ui_mod.max_drawdown_pct([-1, -50, -3]), -50.0)

    def test_single(self):
        self.assertEqual(ui_mod.max_drawdown_pct([-7]), -7.0)

    def test_first_worst(self):
        self.assertEqual(ui_mod.max_drawdown_pct([-9, -1, -2]), -9.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: annualized_return_pct
# ─────────────────────────────────────────────────────────────────────────────

class TestAnnualizedReturnPure(unittest.TestCase):
    def test_known_one_year_double(self):
        # exactly 365 days, equity doubles -> 100% annualized.
        series = [("2026-01-01", 100.0), ("2027-01-01", 200.0)]
        self.assertAlmostEqual(ui_mod.annualized_return_pct(series), 100.0, places=6)

    def test_known_half_year(self):
        # ~182 days, 10% total -> compounds up to ~21% annualized.
        series = [("2026-01-01", 100.0), ("2026-07-02", 110.0)]
        span = (
            __import__("datetime").date(2026, 7, 2)
            - __import__("datetime").date(2026, 1, 1)
        ).days
        expected = ((110.0 / 100.0) ** (365.0 / span) - 1.0) * 100.0
        self.assertAlmostEqual(
            ui_mod.annualized_return_pct(series), expected, places=6
        )

    def test_zero_span_none(self):
        series = [("2026-01-01", 100.0), ("2026-01-01", 110.0)]
        self.assertIsNone(ui_mod.annualized_return_pct(series))

    def test_negative_span_none(self):
        series = [("2026-02-01", 100.0), ("2026-01-01", 110.0)]
        self.assertIsNone(ui_mod.annualized_return_pct(series))

    def test_first_nonpositive_none(self):
        series = [("2026-01-01", 0.0), ("2027-01-01", 200.0)]
        self.assertIsNone(ui_mod.annualized_return_pct(series))

    def test_total_nonpositive_none(self):
        # last equity 0 -> total = 0 -> None (can't take fractional power)
        series = [("2026-01-01", 100.0), ("2027-01-01", 0.0)]
        self.assertIsNone(ui_mod.annualized_return_pct(series))

    def test_bad_date_none(self):
        series = [("not-a-date", 100.0), ("2027-01-01", 200.0)]
        self.assertIsNone(ui_mod.annualized_return_pct(series))

    def test_empty_none(self):
        self.assertIsNone(ui_mod.annualized_return_pct([]))

    def test_single_none(self):
        self.assertIsNone(ui_mod.annualized_return_pct([("2026-01-01", 100.0)]))

    def test_loss_negative(self):
        series = [("2026-01-01", 100.0), ("2027-01-01", 50.0)]
        self.assertAlmostEqual(ui_mod.annualized_return_pct(series), -50.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: martin_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestMartinRatioPure(unittest.TestCase):
    def test_division(self):
        self.assertAlmostEqual(ui_mod.martin_ratio(20.0, 4.0), 5.0, places=9)

    def test_none_return(self):
        self.assertIsNone(ui_mod.martin_ratio(None, 4.0))

    def test_none_ui(self):
        self.assertIsNone(ui_mod.martin_ratio(20.0, None))

    def test_zero_ui_none(self):
        self.assertIsNone(ui_mod.martin_ratio(20.0, 0.0))

    def test_negative_return(self):
        self.assertAlmostEqual(ui_mod.martin_ratio(-10.0, 5.0), -2.0, places=9)

    def test_both_none(self):
        self.assertIsNone(ui_mod.martin_ratio(None, None))


# ─────────────────────────────────────────────────────────────────────────────
# build: monotonic rising -> ui == 0, martin None, ok + note
# ─────────────────────────────────────────────────────────────────────────────

class TestMonotonic(unittest.TestCase):
    def test_monotonic_rising(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(15)]
            _write_equity(td, _equity_doc(levels))
            r = ui_mod.build_ulcer_index(td)
            self.assertTrue(r["available"])
            self.assertEqual(r["ulcer_index"], 0.0)
            self.assertIsNone(r["martin_ratio"])
            self.assertEqual(r["verdict"], "ok")
            self.assertEqual(r["max_drawdown_pct"], 0.0)
            joined = " ".join(r["notes"]).lower()
            self.assertIn("no drawdowns", joined)
            self.assertIn("no drawdowns", r["verdict_reason"].lower())


# ─────────────────────────────────────────────────────────────────────────────
# build: threshold boundaries (UI_WARN, UI_FAIL, MARTIN_WARN, MARTIN_FAIL)
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBoundaries(unittest.TestCase):
    """Construct equity tracks whose underwater RMS lands at known UI values.

    A track that drops to a level and stays flat there for the rest of the run
    has a constant underwater % = the drop %, so its Ulcer Index equals that
    drop magnitude (RMS of a near-constant series), letting us straddle the
    documented thresholds. We assert at the band level (fail / warn / ok)
    rather than the exact float, and check the band-consistency invariant.
    """

    def _build_for_drop(self, drop_pct, n_flat=40):
        # peak=100, then drop to 100*(1+drop) and stay flat -> underwater is
        # 0 at peak then drop_pct repeated -> UI ~ |drop_pct| for large n_flat.
        levels = [100.0] + [100.0 * (1.0 + drop_pct / 100.0)] * n_flat
        return levels

    def _verdict_for_drop(self, drop_pct, n_flat=40):
        with tempfile.TemporaryDirectory() as td:
            levels = self._build_for_drop(drop_pct, n_flat)
            _write_equity(td, _equity_doc(levels))
            return ui_mod.build_ulcer_index(td)

    def test_just_below_ui_warn_not_warn_by_ui(self):
        # UI ~ 7.0 < UI_WARN=7.5. Could still warn via Martin; keep return
        # neutral by giving a tiny positive annualized return. Just assert the
        # UI value is below the warn threshold.
        r = self._verdict_for_drop(-7.0)
        self.assertTrue(r["available"])
        self.assertLess(r["ulcer_index"], ui_mod.UI_WARN)

    def test_at_ui_warn_is_warn_or_fail(self):
        r = self._verdict_for_drop(-7.5)
        self.assertGreaterEqual(r["ulcer_index"], ui_mod.UI_WARN - 0.3)
        self.assertIn(r["verdict"], ("warn", "fail"))

    def test_above_ui_warn_below_fail_warns(self):
        r = self._verdict_for_drop(-10.0)
        self.assertGreaterEqual(r["ulcer_index"], ui_mod.UI_WARN)
        self.assertLess(r["ulcer_index"], ui_mod.UI_FAIL)
        self.assertIn(r["verdict"], ("warn", "fail"))

    def test_at_ui_fail_is_fail(self):
        r = self._verdict_for_drop(-15.0)
        self.assertGreaterEqual(r["ulcer_index"], ui_mod.UI_FAIL - 0.3)
        self.assertEqual(r["verdict"], "fail")

    def test_above_ui_fail_is_fail(self):
        r = self._verdict_for_drop(-25.0)
        self.assertGreaterEqual(r["ulcer_index"], ui_mod.UI_FAIL)
        self.assertEqual(r["verdict"], "fail")

    def test_band_consistency_invariant(self):
        # fail implies it would also clear warn-or-fail; sweep many drops.
        for drop in (-1, -5, -7.5, -8, -12, -15, -20, -30):
            with self.subTest(drop=drop):
                r = self._verdict_for_drop(float(drop))
                self.assertIn(r["verdict"], ("ok", "warn", "fail"))
                if r["verdict"] == "fail":
                    # at/above fail UI OR martin below fail OR neg-return rule
                    cond = (
                        (r["ulcer_index"] is not None
                         and r["ulcer_index"] >= ui_mod.UI_FAIL)
                        or (r["martin_ratio"] is not None
                            and r["martin_ratio"] < ui_mod.MARTIN_FAIL)
                        or (r["martin_ratio"] is None
                            and r["annualized_return_pct"] is not None
                            and r["annualized_return_pct"] < 0)
                    )
                    self.assertTrue(cond)

    def test_negative_return_with_drawdowns_fails(self):
        # A drop with no recovery: total return < 0, drawdowns exist.
        r = self._verdict_for_drop(-10.0)
        self.assertLess(r["annualized_return_pct"], 0)
        self.assertEqual(r["verdict"], "fail")


# ─────────────────────────────────────────────────────────────────────────────
# build: martin-driven verdicts via a recovering track
# ─────────────────────────────────────────────────────────────────────────────

class TestMartinDrivenVerdict(unittest.TestCase):
    def test_strong_track_ok(self):
        # rises, a shallow dip, recovers strongly -> low UI, high martin -> ok
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0, 101.0, 100.5, 102.0, 103.0, 104.0, 105.0,
                      106.0, 107.0, 108.0, 110.0, 112.0]
            dates = [f"2026-01-{i+1:02d}" for i in range(len(levels))]
            _write_equity(td, _equity_doc(levels, dates))
            r = ui_mod.build_ulcer_index(td)
            self.assertTrue(r["available"])
            self.assertLess(r["ulcer_index"], ui_mod.UI_WARN)
            self.assertEqual(r["verdict"], "ok")

    def test_martin_fields_present_when_recovering(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0, 99.0, 98.0, 99.0, 100.0, 101.0, 102.0,
                      103.0, 104.0, 105.0, 106.0]
            dates = [f"2026-01-{i+1:02d}" for i in range(len(levels))]
            _write_equity(td, _equity_doc(levels, dates))
            r = ui_mod.build_ulcer_index(td)
            self.assertIsNotNone(r["martin_ratio"])
            self.assertIsNotNone(r["annualized_return_pct"])


# ─────────────────────────────────────────────────────────────────────────────
# insufficient data
# ─────────────────────────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def _assert_stable_unavailable(self, r):
        for k in ("available", "reason", "is_demo", "ulcer_index", "pain_index",
                  "max_drawdown_pct", "annualized_return_pct", "martin_ratio",
                  "n_observations", "start_date", "end_date", "verdict",
                  "verdict_reason", "notes", "meta"):
            self.assertIn(k, r)
        self.assertFalse(r["available"])
        self.assertEqual(r["verdict"], "ok")
        self.assertIsNone(r["ulcer_index"])
        self.assertIsNone(r["martin_ratio"])
        self.assertEqual(r["meta"]["source"], ui_mod.SOURCE_NAME)
        self.assertEqual(r["meta"]["schema_version"], ui_mod.SCHEMA_VERSION)
        self.assertEqual(r["meta"]["min_obs_required"], ui_mod.MIN_OBS)

    def test_empty_daily(self):
        with tempfile.TemporaryDirectory() as td:
            _write_equity(td, {"daily": []})
            self._assert_stable_unavailable(ui_mod.build_ulcer_index(td))

    def test_fewer_than_min(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(ui_mod.MIN_OBS - 1)]
            _write_equity(td, _equity_doc(levels))
            r = ui_mod.build_ulcer_index(td)
            self._assert_stable_unavailable(r)
            self.assertEqual(r["n_observations"], ui_mod.MIN_OBS - 1)

    def test_exactly_min_is_available(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(ui_mod.MIN_OBS)]
            _write_equity(td, _equity_doc(levels))
            r = ui_mod.build_ulcer_index(td)
            self.assertTrue(r["available"])
            self.assertEqual(r["n_observations"], ui_mod.MIN_OBS)


# ─────────────────────────────────────────────────────────────────────────────
# never-raise / tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverRaise(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = ui_mod.build_ulcer_index(td)
            self.assertIsInstance(r, dict)
            self.assertFalse(r["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ui_mod.EQUITY_FILENAME).write_text("{not json", encoding="utf-8")
            r = ui_mod.build_ulcer_index(td)
            self.assertIsInstance(r, dict)
            self.assertFalse(r["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ui_mod.EQUITY_FILENAME).write_text("42", encoding="utf-8")
            r = ui_mod.build_ulcer_index(td)
            self.assertIsInstance(r, dict)
            self.assertFalse(r["available"])

    def test_list_root(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ui_mod.EQUITY_FILENAME).write_text(
                json.dumps([{"date": "2026-01-01", "close_equity": 100.0}]),
                encoding="utf-8",
            )
            r = ui_mod.build_ulcer_index(td)
            self.assertIsInstance(r, dict)
            # bare list with one bar -> < MIN_OBS -> unavailable (stable)
            self.assertFalse(r["available"])

    def test_garbage_bars(self):
        cases = [
            {"daily": [1, 2, 3]},
            {"daily": [{"no_date": True}]},
            {"daily": [{"date": "x", "close_equity": "y"}]},
            {"daily": [{"date": "2026-01-01", "close_equity": -5}]},
            {"daily": [{"date": "2026-01-01"}]},
            {"daily": "not a list"},
            {},
            {"is_demo": True},
        ]
        for i, doc in enumerate(cases):
            with self.subTest(i=i):
                with tempfile.TemporaryDirectory() as td:
                    _write_equity(td, doc)
                    r = ui_mod.build_ulcer_index(td)
                    self.assertIsInstance(r, dict)
                    self.assertIn("verdict", r)

    def test_fuzz_random_tracks(self):
        rng = random.Random(20260612)
        for trial in range(60):
            with self.subTest(trial=trial):
                n = rng.randint(0, 40)
                levels = [rng.uniform(-50, 200) for _ in range(n)]
                doc = {"daily": [
                    {"date": f"2026-{1 + j // 28:02d}-{1 + j % 28:02d}",
                     "close_equity": levels[j]}
                    for j in range(n)
                ]}
                with tempfile.TemporaryDirectory() as td:
                    _write_equity(td, doc)
                    r = ui_mod.build_ulcer_index(td)
                    self.assertIsInstance(r, dict)
                    self.assertIn(r["verdict"], ("ok", "warn", "fail"))

    def test_pure_funcs_fuzz(self):
        rng = random.Random(99)
        for _ in range(200):
            n = rng.randint(0, 30)
            uw = [-abs(rng.uniform(0, 60)) for _ in range(n)]
            self.assertTrue(ui_mod.ulcer_index(uw) is None or ui_mod.ulcer_index(uw) >= 0)
            self.assertTrue(ui_mod.pain_index(uw) is None or ui_mod.pain_index(uw) >= 0)
            mdd = ui_mod.max_drawdown_pct(uw)
            self.assertTrue(mdd is None or mdd <= 0)


# ─────────────────────────────────────────────────────────────────────────────
# is_demo honesty
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    def test_top_level_true(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels, is_demo=True))
            self.assertTrue(ui_mod.build_ulcer_index(td)["is_demo"])

    def test_top_level_false(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels, is_demo=False))
            self.assertFalse(ui_mod.build_ulcer_index(td)["is_demo"])

    def test_absent_none(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            _write_equity(td, _equity_doc(levels))
            self.assertIsNone(ui_mod.build_ulcer_index(td)["is_demo"])

    def test_meta_demo(self):
        with tempfile.TemporaryDirectory() as td:
            levels = [100.0 + i for i in range(12)]
            doc = _equity_doc(levels)
            doc["meta"] = {"is_demo": True}
            _write_equity(td, doc)
            self.assertTrue(ui_mod.build_ulcer_index(td)["is_demo"])


# ─────────────────────────────────────────────────────────────────────────────
# content_fingerprint reuse-by-import
# ─────────────────────────────────────────────────────────────────────────────

class TestFingerprintReuse(unittest.TestCase):
    def test_is_same_object(self):
        self.assertIs(ui_mod.content_fingerprint, tear_sheet.content_fingerprint)

    def test_ignores_generated_at_and_history(self):
        base = {"a": 1, "meta": {"generated_at": "t1", "x": 9}, "history": [1]}
        other = {"a": 1, "meta": {"generated_at": "t2", "x": 9}, "history": [2, 3]}
        self.assertEqual(
            ui_mod.content_fingerprint(base), ui_mod.content_fingerprint(other)
        )

    def test_changes_with_content(self):
        a = {"a": 1, "meta": {"generated_at": "t"}}
        b = {"a": 2, "meta": {"generated_at": "t"}}
        self.assertNotEqual(
            ui_mod.content_fingerprint(a), ui_mod.content_fingerprint(b)
        )

    def test_stable_for_identical(self):
        a = {"a": 1, "meta": {"generated_at": "t"}}
        self.assertEqual(
            ui_mod.content_fingerprint(a), ui_mod.content_fingerprint(dict(a))
        )


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import of equity helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestEquityHelperReuse(unittest.TestCase):
    def test_extract_is_same_object(self):
        self.assertIs(
            ui_mod.extract_equity_series, drawdown_analytics.extract_equity_series
        )

    def test_underwater_is_same_object(self):
        self.assertIs(
            ui_mod.underwater_curve, drawdown_analytics.underwater_curve
        )


# ─────────────────────────────────────────────────────────────────────────────
# write_status
# ─────────────────────────────────────────────────────────────────────────────

def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


class TestWriteStatus(unittest.TestCase):
    def _good_result(self, td, seed=0):
        levels = [100.0 + i + seed for i in range(12)]
        _write_equity(td, _equity_doc(levels))
        return ui_mod.build_ulcer_index(td)

    def test_first_write_then_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._good_result(td)
            self.assertEqual(ui_mod.write_status(r, td), "DATA_WRITTEN")
            out = Path(td) / ui_mod.STATUS_FILENAME
            md5_a = _md5(out)
            # re-running build yields a new generated_at but identical content
            r2 = self._good_result(td)
            self.assertEqual(ui_mod.write_status(r2, td), "DATA_UNCHANGED")
            self.assertEqual(_md5(out), md5_a)

    def test_different_grows_history(self):
        with tempfile.TemporaryDirectory() as td:
            r1 = self._good_result(td, seed=0)
            ui_mod.write_status(r1, td)
            r2 = self._good_result(td, seed=100)
            self.assertEqual(ui_mod.write_status(r2, td), "DATA_WRITTEN")
            doc = json.loads((Path(td) / ui_mod.STATUS_FILENAME).read_text())
            self.assertEqual(len(doc["history"]), 1)

    def test_rotation_caps_history(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / ui_mod.STATUS_FILENAME
            # Seed a fat history beyond HISTORY_MAX directly.
            r = self._good_result(td, seed=0)
            ui_mod.write_status(r, td)
            doc = json.loads(out.read_text())
            doc["history"] = [{"k": i} for i in range(ui_mod.HISTORY_MAX + 50)]
            out.write_text(json.dumps(doc), encoding="utf-8")
            r2 = self._good_result(td, seed=7)
            ui_mod.write_status(r2, td)
            doc2 = json.loads(out.read_text())
            self.assertLessEqual(len(doc2["history"]), ui_mod.HISTORY_MAX)
            self.assertEqual(len(doc2["history"]), ui_mod.HISTORY_MAX)

    def test_no_leftover_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._good_result(td)
            ui_mod.write_status(r, td)
            leftovers = [p for p in os.listdir(td) if p.startswith(".tmp_ulcer_index_")]
            self.assertEqual(leftovers, [])

    def test_tolerant_of_broken_prev(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / ui_mod.STATUS_FILENAME
            out.write_text("{broken", encoding="utf-8")
            r = self._good_result(td)
            self.assertEqual(ui_mod.write_status(r, td), "DATA_WRITTEN")

    def test_tolerant_of_non_dict_prev(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / ui_mod.STATUS_FILENAME
            out.write_text("[1,2,3]", encoding="utf-8")
            r = self._good_result(td)
            self.assertEqual(ui_mod.write_status(r, td), "DATA_WRITTEN")


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
            rc = ui_mod.main(["--check", "--data-dir", td])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(td) / ui_mod.STATUS_FILENAME).exists())

    def test_default_is_check_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            rc = ui_mod.main(["--data-dir", td])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(td) / ui_mod.STATUS_FILENAME).exists())

    def test_run_writes_then_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(ui_mod.main(["--run", "--data-dir", td]), 0)
            out = Path(td) / ui_mod.STATUS_FILENAME
            self.assertTrue(out.exists())
            md5_a = _md5(out)
            self.assertEqual(ui_mod.main(["--run", "--data-dir", td]), 0)
            self.assertEqual(_md5(out), md5_a)

    def test_junk_arg_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(
                ui_mod.main(["--frobnicate", "--data-dir", td]), 0
            )

    def test_check_run_conflict_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self._seed(td)
            self.assertEqual(
                ui_mod.main(["--check", "--run", "--data-dir", td]), 0
            )
            # conflict -> no write
            self.assertFalse((Path(td) / ui_mod.STATUS_FILENAME).exists())

    def test_subprocess_check(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.analytics_lab.ulcer_index", "--check"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# import hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = Path(ui_mod.__file__).read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(
            src, ui_mod.__file__
        )
        self.assertEqual(violations, [])

    def test_no_forbidden_text(self):
        # Strip the module docstring before scanning: the prose disclaimer
        # legitimately lists the forbidden module names ("...no requests/web3/
        # ...subprocess/eval/exec") and must not be flagged. We assert no
        # forbidden *code* (imports / calls) appears in the executable source.
        src = Path(ui_mod.__file__).read_text(encoding="utf-8")
        body = src
        if '"""' in src:
            # drop everything up to and including the module docstring close
            parts = src.split('"""')
            if len(parts) >= 3:
                body = '"""'.join(parts[2:])
        for needle in ("import requests", "import socket", "import subprocess",
                       "subprocess.", "eval(", "exec(", "import web3",
                       "anthropic", "import numpy", "import pandas"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, body)

    def test_py_compile_both(self):
        import py_compile
        for fname in ("analytics_lab/ulcer_index.py",
                      "tests/test_ulcer_index.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
