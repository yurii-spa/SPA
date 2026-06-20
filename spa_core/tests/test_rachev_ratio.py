#!/usr/bin/env python3
"""Tests for the Rachev Ratio analyzer (SPA-V463 / MP-148).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math (period_returns / tail_cutoff /
expected_tail_gain / expected_tail_loss / rachev_ratio), verdict bands at the
documented thresholds, the low-sample guard, the no-losing-tail degenerate case,
insufficient-data + never-raise / tolerance, reuse-by-import
(content_fingerprint + equity helper), atomic write_status idempotency /
rotation, CLI behaviour (direct + subprocess), and import hygiene.
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

from spa_core.paper_trading import rachev_ratio as rr_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(rr_mod.__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dates(n):
    """n consecutive ISO dates starting 2026-01-01 (28-day month wrap)."""
    out = []
    for i in range(n):
        day = 1 + i
        month = 1 + (day - 1) // 28
        d = 1 + (day - 1) % 28
        out.append(f"2026-{month:02d}-{d:02d}")
    return out


def _equity_from_returns(returns, start=100.0):
    """Equity levels reconstructing the given simple period returns."""
    levels = [start]
    for r in returns:
        levels.append(levels[-1] * (1.0 + r))
    return levels


def _equity_doc(levels, dates=None, is_demo=None):
    """Build an equity_curve_daily.json-shaped dict from equity levels."""
    if dates is None:
        dates = _dates(len(levels))
    daily = [
        {"date": dates[i], "close_equity": float(levels[i])}
        for i in range(len(levels))
    ]
    doc = {"source": "test", "daily": daily}
    if is_demo is not None:
        doc["is_demo"] = is_demo
    return doc


def _write_equity(data_dir, doc):
    (Path(data_dir) / rr_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _build_from_returns(data_dir, returns, **kw):
    levels = _equity_from_returns(returns)
    _write_equity(data_dir, _equity_doc(levels, **kw))
    return rr_mod.build_rachev_ratio(data_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: period_returns
# ─────────────────────────────────────────────────────────────────────────────

class TestPeriodReturns(unittest.TestCase):
    def test_hand_example(self):
        series = [("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]
        r = rr_mod.period_returns(series)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        self.assertAlmostEqual(r[1], -0.10, places=12)

    def test_len_is_n_minus_1(self):
        series = [(f"d{i}", 100.0 + i) for i in range(10)]
        self.assertEqual(len(rr_mod.period_returns(series)), 9)

    def test_empty_and_single(self):
        self.assertEqual(rr_mod.period_returns([]), [])
        self.assertEqual(rr_mod.period_returns([("d0", 100.0)]), [])

    def test_skips_nonpositive_prev(self):
        series = [("d0", 0.0), ("d1", 100.0), ("d2", 110.0)]
        r = rr_mod.period_returns(series)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        for v in r:
            self.assertTrue(math.isfinite(v))

    def test_no_inf_or_nan(self):
        series = [("d0", 100.0), ("d1", 50.0), ("d2", 75.0), ("d3", 75.0)]
        for v in rr_mod.period_returns(series):
            self.assertTrue(math.isfinite(v))


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: tail_cutoff
# ─────────────────────────────────────────────────────────────────────────────

class TestTailCutoff(unittest.TestCase):
    def test_hand_examples(self):
        self.assertEqual(rr_mod.tail_cutoff(10, 0.2), 2)   # ceil(2.0)
        self.assertEqual(rr_mod.tail_cutoff(10, 0.05), 1)  # max(1, ceil(0.5))
        self.assertEqual(rr_mod.tail_cutoff(40, 0.05), 2)  # ceil(2.0)
        self.assertEqual(rr_mod.tail_cutoff(21, 0.05), 2)  # ceil(1.05)

    def test_at_least_one(self):
        self.assertEqual(rr_mod.tail_cutoff(3, 0.001), 1)

    def test_zero_or_negative_n(self):
        self.assertEqual(rr_mod.tail_cutoff(0, 0.05), 0)
        self.assertEqual(rr_mod.tail_cutoff(-5, 0.05), 0)

    def test_frac_clamped(self):
        self.assertEqual(rr_mod.tail_cutoff(10, 5.0), 10)   # frac > 1 -> all
        self.assertEqual(rr_mod.tail_cutoff(10, 0.0), 1)    # frac <= 0 -> 1


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: expected_tail_gain / expected_tail_loss
# ─────────────────────────────────────────────────────────────────────────────

class TestTailExpectations(unittest.TestCase):
    SAMPLE = [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6]

    def test_etg_hand_example(self):
        # alpha=0.2 over 10 -> cutoff 2 -> best two = 5,6 -> mean 5.5
        self.assertAlmostEqual(
            rr_mod.expected_tail_gain(self.SAMPLE, 0.2), 5.5, places=12
        )

    def test_etl_hand_example(self):
        # beta=0.2 over 10 -> cutoff 2 -> worst two = -3,-2 -> mean -2.5 -> ETL 2.5
        self.assertAlmostEqual(
            rr_mod.expected_tail_loss(self.SAMPLE, 0.2), 2.5, places=12
        )

    def test_etg_single_obs(self):
        # alpha=0.05 over 10 -> cutoff 1 -> best = 6
        self.assertAlmostEqual(
            rr_mod.expected_tail_gain(self.SAMPLE, 0.05), 6.0, places=12
        )

    def test_etl_single_obs(self):
        # beta=0.05 over 10 -> cutoff 1 -> worst = -3 -> ETL 3
        self.assertAlmostEqual(
            rr_mod.expected_tail_loss(self.SAMPLE, 0.05), 3.0, places=12
        )

    def test_empty_none(self):
        self.assertIsNone(rr_mod.expected_tail_gain([], 0.05))
        self.assertIsNone(rr_mod.expected_tail_loss([], 0.05))

    def test_all_positive_etl_negative(self):
        # worst tail of an all-winning series is itself positive -> ETL < 0
        pos = [0.01, 0.02, 0.03, 0.04, 0.05]
        self.assertLess(rr_mod.expected_tail_loss(pos, 0.2), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: rachev_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestRachevRatioPure(unittest.TestCase):
    def test_hand_example(self):
        self.assertAlmostEqual(rr_mod.rachev_ratio(5.5, 2.5), 2.2, places=12)

    def test_none_inputs(self):
        self.assertIsNone(rr_mod.rachev_ratio(None, 2.0))
        self.assertIsNone(rr_mod.rachev_ratio(1.0, None))

    def test_nonpositive_etl_none(self):
        self.assertIsNone(rr_mod.rachev_ratio(1.0, 0.0))
        self.assertIsNone(rr_mod.rachev_ratio(1.0, -0.5))

    def test_symmetric_one(self):
        self.assertAlmostEqual(rr_mod.rachev_ratio(2.0, 2.0), 1.0, places=12)


# ─────────────────────────────────────────────────────────────────────────────
# build_rachev_ratio: verdict bands
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBands(unittest.TestCase):
    # n=40 returns -> 5% tail cutoff = ceil(2.0) = 2 (>= MIN_TAIL_OBS, no cap)

    def test_fail_left_tail_dominates(self):
        # worst two = -0.02 (ETL 0.02), best two = +0.01 (ETG 0.01) -> RR 0.5
        returns = [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["tail_obs_gain"], 2)
        self.assertEqual(res["tail_obs_loss"], 2)
        self.assertAlmostEqual(res["expected_tail_gain"], 0.01, places=6)
        self.assertAlmostEqual(res["expected_tail_loss"], 0.02, places=6)
        self.assertAlmostEqual(res["rachev_ratio"], 0.5, places=6)
        self.assertEqual(res["verdict"], "fail")

    def test_warn_mild_asymmetry(self):
        # ETG 0.014, ETL 0.02 -> RR 0.7 (in [FAIL, WARN))
        returns = [-0.02, -0.02] + [0.0] * 36 + [0.014, 0.014]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["rachev_ratio"], 0.7, places=6)
        self.assertEqual(res["verdict"], "warn")

    def test_ok_symmetric(self):
        # ETG 0.02, ETL 0.02 -> RR 1.0 (>= WARN)
        returns = [-0.02, -0.02] + [0.0] * 36 + [0.02, 0.02]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["rachev_ratio"], 1.0, places=6)
        self.assertEqual(res["verdict"], "ok")

    def test_low_sample_guard_caps_fail_to_warn(self):
        # n=20 returns -> 5% tail cutoff = ceil(1.0) = 1 (< MIN_TAIL_OBS=2).
        # RR = 0.01 / 0.02 = 0.5 would be fail, but capped to warn.
        returns = [-0.02] + [0.0] * 18 + [0.01]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["tail_obs_gain"], 1)
        self.assertEqual(res["tail_obs_loss"], 1)
        self.assertAlmostEqual(res["rachev_ratio"], 0.5, places=6)
        self.assertEqual(res["verdict"], "warn")
        self.assertTrue(any("low-sample guard" in n for n in res["notes"]))

    def test_verdict_reason_always_present(self):
        returns = [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertIn("verdict_reason", res)
        self.assertTrue(res["verdict_reason"])

    def test_band_invariant(self):
        # verdict must be consistent with the ratio + thresholds (no cap path)
        for ratio_target, exp in ((0.4, "fail"), (0.75, "warn"), (1.2, "ok")):
            etg = round(0.02 * ratio_target, 6)
            returns = [-0.02, -0.02] + [0.0] * 36 + [etg, etg]
            with tempfile.TemporaryDirectory() as d:
                res = _build_from_returns(d, returns)
            with self.subTest(ratio=ratio_target):
                self.assertEqual(res["verdict"], exp)


# ─────────────────────────────────────────────────────────────────────────────
# build_rachev_ratio: no-losing-tail degenerate + insufficient data
# ─────────────────────────────────────────────────────────────────────────────

class TestDegenerate(unittest.TestCase):
    def test_no_losing_tail(self):
        # all returns non-negative -> worst tail mean >= 0 -> ETL <= 0 -> undefined
        returns = [0.0] * 38 + [0.01, 0.01]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertIsNone(res["rachev_ratio"])
        self.assertEqual(res["verdict"], "ok")
        self.assertTrue(any("no losing tail" in n for n in res["notes"]))

    def test_all_winning_tail(self):
        # even the worst tail is strictly positive
        returns = [0.01] * 38 + [0.02, 0.02]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertIsNone(res["rachev_ratio"])
        self.assertEqual(res["verdict"], "ok")

    def test_insufficient_returns(self):
        # 19 returns -> 20 equity points but only 19 returns (< MIN_OBS=20)
        returns = [0.01, -0.01] * 9 + [0.02]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(res["n_observations"], 19)

    def test_empty_equity(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = rr_mod.build_rachev_ratio(d)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")

    def test_schema_stable_when_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = rr_mod.build_rachev_ratio(d)
        for key in ("available", "rachev_ratio", "expected_tail_gain",
                    "expected_tail_loss", "alpha", "beta", "tail_obs_gain",
                    "tail_obs_loss", "verdict", "verdict_reason", "meta"):
            self.assertIn(key, res)


# ─────────────────────────────────────────────────────────────────────────────
# is_demo passthrough
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    RETURNS = [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01]

    def test_is_demo_true(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, self.RETURNS, is_demo=True)
        self.assertIs(res["is_demo"], True)

    def test_is_demo_false(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, self.RETURNS, is_demo=False)
        self.assertIs(res["is_demo"], False)

    def test_is_demo_absent_none(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, self.RETURNS)
        self.assertIsNone(res["is_demo"])


# ─────────────────────────────────────────────────────────────────────────────
# never-raise / tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverRaise(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            res = rr_mod.build_rachev_ratio(d)
        self.assertFalse(res["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / rr_mod.EQUITY_FILENAME).write_text("{not json", encoding="utf-8")
            res = rr_mod.build_rachev_ratio(d)
        self.assertFalse(res["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / rr_mod.EQUITY_FILENAME).write_text("123", encoding="utf-8")
            res = rr_mod.build_rachev_ratio(d)
        self.assertFalse(res["available"])

    def test_list_root(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [{"date": dt, "close_equity": 100.0 + i}
                    for i, dt in enumerate(_dates(30))]
            (Path(d) / rr_mod.EQUITY_FILENAME).write_text(
                json.dumps(bars), encoding="utf-8"
            )
            res = rr_mod.build_rachev_ratio(d)
        # a bare list IS accepted by extract_equity_series -> should be available
        self.assertTrue(res["available"])

    def test_garbage_bars(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"daily": ["nope", 7, None, {"date": "bad"}, {}]}
            _write_equity(d, doc)
            res = rr_mod.build_rachev_ratio(d)
        self.assertFalse(res["available"])

    def test_fuzz_never_raises(self):
        rnd = random.Random(13)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / rr_mod.EQUITY_FILENAME
            for _ in range(40):
                kind = rnd.randint(0, 4)
                if kind == 0:
                    p.write_text("", encoding="utf-8")
                elif kind == 1:
                    p.write_text("{", encoding="utf-8")
                elif kind == 2:
                    p.write_text(json.dumps({"daily": rnd.random()}), encoding="utf-8")
                elif kind == 3:
                    bars = [{"date": "2026-01-01", "close_equity": rnd.uniform(-5, 100)}
                            for _ in range(rnd.randint(0, 50))]
                    p.write_text(json.dumps({"daily": bars}), encoding="utf-8")
                else:
                    levels = [rnd.uniform(50, 150) for _ in range(rnd.randint(0, 60))]
                    p.write_text(json.dumps(_equity_doc(levels)), encoding="utf-8")
                res = rr_mod.build_rachev_ratio(d)
                self.assertIn("verdict", res)
                self.assertIn(res["verdict"], ("ok", "warn", "fail"))


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import (single source of truth)
# ─────────────────────────────────────────────────────────────────────────────

class TestReuseByImport(unittest.TestCase):
    def test_content_fingerprint_is_tear_sheet_object(self):
        self.assertIs(rr_mod.content_fingerprint, tear_sheet.content_fingerprint)

    def test_extract_equity_series_is_drawdown_object(self):
        self.assertIs(
            rr_mod.extract_equity_series, drawdown_analytics.extract_equity_series
        )

    def test_fingerprint_ignores_volatile_fields(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01])
            a = dict(res)
            b = dict(res)
            b["meta"] = dict(b["meta"])
            b["meta"]["generated_at"] = "DIFFERENT"
            b["history"] = [{"x": 1}]
            self.assertEqual(
                rr_mod.content_fingerprint(a), rr_mod.content_fingerprint(b)
            )

    def test_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01])
            a = dict(res)
            b = dict(res)
            b["rachev_ratio"] = 99.0
            self.assertNotEqual(
                rr_mod.content_fingerprint(a), rr_mod.content_fingerprint(b)
            )


# ─────────────────────────────────────────────────────────────────────────────
# write_status: idempotency / rotation / atomicity
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStatus(unittest.TestCase):
    GOOD = [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01]

    def _good_result(self, d):
        return _build_from_returns(d, self.GOOD)

    def test_written_then_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            self.assertEqual(rr_mod.write_status(res, d), "DATA_WRITTEN")
            res2 = rr_mod.build_rachev_ratio(d)  # fresh generated_at
            self.assertEqual(rr_mod.write_status(res2, d), "DATA_UNCHANGED")

    def test_md5_identical_on_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            rr_mod.write_status(res, d)
            p = Path(d) / rr_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            res2 = rr_mod.build_rachev_ratio(d)
            rr_mod.write_status(res2, d)
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            rr_mod.write_status(res, d)
            leftovers = list(Path(d).glob(".tmp_rachev_ratio_*"))
            self.assertEqual(leftovers, [])

    def test_history_rotation_exactly_max(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / rr_mod.STATUS_FILENAME
            base = self._good_result(d)
            big_hist = [{"_fingerprint": f"x{i}", "rachev_ratio": i}
                        for i in range(rr_mod.HISTORY_MAX + 50)]
            seed = dict(base)
            seed["_fingerprint"] = "SEED_DIFFERENT"
            seed["history"] = big_hist
            out.write_text(json.dumps(seed), encoding="utf-8")
            changed = dict(base)
            changed["rachev_ratio"] = 99.0
            self.assertEqual(rr_mod.write_status(changed, d), "DATA_WRITTEN")
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(doc["history"]), rr_mod.HISTORY_MAX)

    def test_tolerates_broken_previous(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / rr_mod.STATUS_FILENAME
            out.write_text("{garbage", encoding="utf-8")
            res = self._good_result(d)
            self.assertEqual(rr_mod.write_status(res, d), "DATA_WRITTEN")

    def test_creates_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "nested" / "data"
            _write_equity(d, _equity_doc(_equity_from_returns(self.GOOD)))
            res = rr_mod.build_rachev_ratio(d)
            self.assertEqual(rr_mod.write_status(res, sub), "DATA_WRITTEN")
            self.assertTrue((sub / rr_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# CLI: direct main(argv) + subprocess
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    GOOD = [-0.02, -0.02] + [0.0] * 36 + [0.01, 0.01]

    def _seed(self, d):
        _write_equity(d, _equity_doc(_equity_from_returns(self.GOOD)))

    def test_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = rr_mod.main(["--check", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / rr_mod.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = rr_mod.main(["--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / rr_mod.STATUS_FILENAME).exists())

    def test_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = rr_mod.main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / rr_mod.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rr_mod.main(["--run", "--data-dir", d])
            p = Path(d) / rr_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            rr_mod.main(["--run", "--data-dir", d])
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_conflict_check_run(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = rr_mod.main(["--check", "--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / rr_mod.STATUS_FILENAME).exists())

    def test_unknown_args(self):
        rc = rr_mod.main(["--frobnicate"])
        self.assertEqual(rc, 0)

    def test_subprocess_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.rachev_ratio",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("[rachev_ratio]", proc.stdout)

    def test_subprocess_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.rachev_ratio",
                 "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertTrue((Path(d) / rr_mod.STATUS_FILENAME).exists())

    def test_subprocess_garbage_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / rr_mod.EQUITY_FILENAME).write_text("{bad", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.rachev_ratio",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# import hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = Path(rr_mod.__file__).read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(src, rr_mod.__file__)
        self.assertEqual(violations, [])

    def test_no_forbidden_text(self):
        # Strip the module docstring before scanning: the prose disclaimer
        # legitimately lists the forbidden module names and must not be flagged.
        src = Path(rr_mod.__file__).read_text(encoding="utf-8")
        body = src
        if '"""' in src:
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
        for fname in ("paper_trading/rachev_ratio.py",
                      "tests/test_rachev_ratio.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
