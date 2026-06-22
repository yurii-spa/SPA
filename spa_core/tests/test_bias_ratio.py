#!/usr/bin/env python3
"""Tests for the Bias Ratio analyzer (SPA-V462 / MP-147).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math (period_returns / sample_std / band_counts /
bias_ratio), verdict bands at the documented thresholds, the low-sample guard,
zero-dispersion handling, insufficient-data + never-raise / tolerance,
reuse-by-import (content_fingerprint + equity helper), atomic write_status
idempotency / rotation, CLI behaviour (direct + subprocess), and import hygiene.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from spa_core.paper_trading import bias_ratio as br_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(br_mod.__file__).resolve().parents[2]


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
    (Path(data_dir) / br_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _build_from_returns(data_dir, returns, **kw):
    levels = _equity_from_returns(returns)
    _write_equity(data_dir, _equity_doc(levels, **kw))
    return br_mod.build_bias_ratio(data_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: period_returns
# ─────────────────────────────────────────────────────────────────────────────

class TestPeriodReturns(unittest.TestCase):
    def test_hand_example(self):
        series = [("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]
        r = br_mod.period_returns(series)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        self.assertAlmostEqual(r[1], -0.10, places=12)

    def test_len_is_n_minus_1(self):
        series = [(f"d{i}", 100.0 + i) for i in range(10)]
        self.assertEqual(len(br_mod.period_returns(series)), 9)

    def test_empty_and_single(self):
        self.assertEqual(br_mod.period_returns([]), [])
        self.assertEqual(br_mod.period_returns([("d0", 100.0)]), [])

    def test_skips_nonpositive_prev(self):
        # prior level <= 0 must not produce a return (and never raise/inf)
        series = [("d0", 0.0), ("d1", 100.0), ("d2", 110.0)]
        r = br_mod.period_returns(series)
        # step from 0 is skipped; only 100->110 yields a return
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        for v in r:
            self.assertTrue(math.isfinite(v))

    def test_no_inf_or_nan(self):
        series = [("d0", 100.0), ("d1", 50.0), ("d2", 75.0), ("d3", 75.0)]
        for v in br_mod.period_returns(series):
            self.assertTrue(math.isfinite(v))


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: sample_std
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleStd(unittest.TestCase):
    def test_hand_example(self):
        # variance of 1..5 (sample) = 2.5 -> std = 1.5811388300841898
        self.assertAlmostEqual(
            br_mod.sample_std([1, 2, 3, 4, 5]), 1.5811388300841898, places=12
        )

    def test_identical_values_zero(self):
        self.assertEqual(br_mod.sample_std([0.01, 0.01, 0.01, 0.01]), 0.0)

    def test_fewer_than_two_none(self):
        self.assertIsNone(br_mod.sample_std([]))
        self.assertIsNone(br_mod.sample_std([0.5]))

    def test_two_values(self):
        # [0, 2]: mean 1, ss = 1+1 = 2, var = 2/1 = 2, std = sqrt(2)
        self.assertAlmostEqual(br_mod.sample_std([0.0, 2.0]), math.sqrt(2), places=12)

    def test_nonnegative(self):
        rnd = random.Random(7)
        for _ in range(50):
            vals = [rnd.uniform(-1, 1) for _ in range(rnd.randint(2, 30))]
            s = br_mod.sample_std(vals)
            self.assertIsNotNone(s)
            self.assertGreaterEqual(s, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: band_counts
# ─────────────────────────────────────────────────────────────────────────────

class TestBandCounts(unittest.TestCase):
    def test_hand_example(self):
        returns = [0.005, -0.005, 0.02, 0.005]
        pos, neg = br_mod.band_counts(returns, 0.01)
        self.assertEqual((pos, neg), (2, 1))  # 0.02 is outside +s

    def test_zero_counts_as_positive(self):
        pos, neg = br_mod.band_counts([0.0, 0.0, -0.001], 0.01)
        self.assertEqual((pos, neg), (2, 1))

    def test_boundary_inclusive(self):
        # exactly +s is included in positive; exactly -s included in negative
        pos, neg = br_mod.band_counts([0.01, -0.01], 0.01)
        self.assertEqual((pos, neg), (1, 1))

    def test_all_outside(self):
        pos, neg = br_mod.band_counts([0.5, -0.5, 0.9], 0.01)
        self.assertEqual((pos, neg), (0, 0))

    def test_zero_s_only_exact_zeros(self):
        pos, neg = br_mod.band_counts([0.0, 0.0, 0.001, -0.001], 0.0)
        self.assertEqual((pos, neg), (2, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: bias_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestBiasRatioPure(unittest.TestCase):
    def test_hand_example(self):
        self.assertEqual(br_mod.bias_ratio(8, 1), 4.0)

    def test_balanced_near_one(self):
        # equal small gains/losses -> just below 1 due to the +1 denominator
        self.assertAlmostEqual(br_mod.bias_ratio(10, 10), 10 / 11, places=12)

    def test_no_small_negatives_finite(self):
        # the +1 keeps it finite (the smoothing case)
        self.assertEqual(br_mod.bias_ratio(5, 0), 5.0)

    def test_zero_zero(self):
        self.assertEqual(br_mod.bias_ratio(0, 0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(br_mod.bias_ratio(3, 2), float)


# ─────────────────────────────────────────────────────────────────────────────
# build_bias_ratio: verdict bands
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBands(unittest.TestCase):
    def test_fail_strong_smoothing(self):
        # 9 small +0.004, 1 small -0.004, plus 2 large to set dispersion.
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["count_small_positive"], 9)
        self.assertEqual(res["count_small_negative"], 1)
        self.assertAlmostEqual(res["bias_ratio"], 4.5, places=6)
        self.assertEqual(res["verdict"], "fail")

    def test_warn_mild_asymmetry(self):
        # 5 small +, 1 small -, 6 large outside-band returns -> BR = 2.5
        returns = [0.004] * 5 + [-0.004] + [0.05, -0.05] * 3
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["count_small_positive"], 5)
        self.assertEqual(res["count_small_negative"], 1)
        self.assertAlmostEqual(res["bias_ratio"], 2.5, places=6)
        self.assertEqual(res["verdict"], "warn")

    def test_ok_balanced(self):
        # 4 small +, 4 small -, 4 large outside-band -> BR = 0.8
        returns = [0.004] * 4 + [-0.004] * 4 + [0.05, -0.05, 0.05, -0.05]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["count_small_positive"], 4)
        self.assertEqual(res["count_small_negative"], 4)
        self.assertAlmostEqual(res["bias_ratio"], 0.8, places=6)
        self.assertEqual(res["verdict"], "ok")

    def test_low_sample_guard_caps_fail_to_warn(self):
        # 4 small +, 0 small -, 8 large outside-band -> BR = 4.0 (> FAIL) but
        # only 4 returns in the small band (< MIN_BAND_OBS=6) -> capped to warn
        returns = [0.004] * 4 + [0.05, -0.05] * 4
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["count_small_positive"], 4)
        self.assertEqual(res["count_small_negative"], 0)
        self.assertAlmostEqual(res["bias_ratio"], 4.0, places=6)
        self.assertEqual(res["verdict"], "warn")
        self.assertTrue(any("low-sample guard" in n for n in res["notes"]))

    def test_verdict_reason_always_present(self):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertIn("verdict_reason", res)
        self.assertTrue(res["verdict_reason"])


# ─────────────────────────────────────────────────────────────────────────────
# build_bias_ratio: zero dispersion + insufficient data
# ─────────────────────────────────────────────────────────────────────────────

class TestDegenerate(unittest.TestCase):
    def test_zero_dispersion(self):
        # constant geometric growth -> all returns identical -> std 0
        returns = [0.01] * 14
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertIsNone(res["bias_ratio"])
        self.assertEqual(res["std_returns"], 0.0)
        self.assertEqual(res["verdict"], "ok")
        self.assertTrue(any("zero return dispersion" in n for n in res["notes"]))

    def test_insufficient_returns(self):
        # 11 returns -> 12 equity points but only 11 returns (< MIN_OBS=12)
        returns = [0.01, -0.01] * 5 + [0.02]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(res["n_observations"], 11)

    def test_empty_equity(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = br_mod.build_bias_ratio(d)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")

    def test_schema_stable_when_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = br_mod.build_bias_ratio(d)
        for key in ("available", "bias_ratio", "std_returns",
                    "count_small_positive", "count_small_negative",
                    "verdict", "verdict_reason", "meta"):
            self.assertIn(key, res)


# ─────────────────────────────────────────────────────────────────────────────
# is_demo passthrough
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    def test_is_demo_true(self):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns, is_demo=True)
        self.assertIs(res["is_demo"], True)

    def test_is_demo_false(self):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns, is_demo=False)
        self.assertIs(res["is_demo"], False)

    def test_is_demo_absent_none(self):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertIsNone(res["is_demo"])


# ─────────────────────────────────────────────────────────────────────────────
# never-raise / tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverRaise(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            res = br_mod.build_bias_ratio(d)
        self.assertFalse(res["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / br_mod.EQUITY_FILENAME).write_text("{not json", encoding="utf-8")
            res = br_mod.build_bias_ratio(d)
        self.assertFalse(res["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / br_mod.EQUITY_FILENAME).write_text("123", encoding="utf-8")
            res = br_mod.build_bias_ratio(d)
        self.assertFalse(res["available"])

    def test_list_root(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [{"date": dt, "close_equity": 100.0 + i}
                    for i, dt in enumerate(_dates(20))]
            (Path(d) / br_mod.EQUITY_FILENAME).write_text(
                json.dumps(bars), encoding="utf-8"
            )
            res = br_mod.build_bias_ratio(d)
        # a bare list IS accepted by extract_equity_series -> should be available
        self.assertTrue(res["available"])

    def test_garbage_bars(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"daily": ["nope", 7, None, {"date": "bad"}, {}]}
            _write_equity(d, doc)
            res = br_mod.build_bias_ratio(d)
        self.assertFalse(res["available"])

    def test_fuzz_never_raises(self):
        rnd = random.Random(13)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / br_mod.EQUITY_FILENAME
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
                            for _ in range(rnd.randint(0, 30))]
                    p.write_text(json.dumps({"daily": bars}), encoding="utf-8")
                else:
                    levels = [rnd.uniform(50, 150) for _ in range(rnd.randint(0, 40))]
                    p.write_text(json.dumps(_equity_doc(levels)), encoding="utf-8")
                res = br_mod.build_bias_ratio(d)
                self.assertIn("verdict", res)
                self.assertIn(res["verdict"], ("ok", "warn", "fail"))


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import (single source of truth)
# ─────────────────────────────────────────────────────────────────────────────

class TestReuseByImport(unittest.TestCase):
    def test_content_fingerprint_is_tear_sheet_object(self):
        self.assertIs(br_mod.content_fingerprint, tear_sheet.content_fingerprint)

    def test_extract_equity_series_is_drawdown_object(self):
        self.assertIs(
            br_mod.extract_equity_series, drawdown_analytics.extract_equity_series
        )


# ─────────────────────────────────────────────────────────────────────────────
# write_status: idempotency / rotation / atomicity
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStatus(unittest.TestCase):
    def _good_result(self, d):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        return _build_from_returns(d, returns)

    def test_written_then_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            self.assertEqual(br_mod.write_status(res, d), "DATA_WRITTEN")
            res2 = br_mod.build_bias_ratio(d)  # fresh generated_at
            self.assertEqual(br_mod.write_status(res2, d), "DATA_UNCHANGED")

    def test_md5_identical_on_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            br_mod.write_status(res, d)
            p = Path(d) / br_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            res2 = br_mod.build_bias_ratio(d)
            br_mod.write_status(res2, d)
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            br_mod.write_status(res, d)
            leftovers = list(Path(d).glob(".tmp_bias_ratio_*"))
            self.assertEqual(leftovers, [])

    def test_history_rotation_exactly_max(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / br_mod.STATUS_FILENAME
            # seed an oversized history; write once -> rotation to <= MAX
            base = self._good_result(d)
            big_hist = [{"_fingerprint": f"x{i}", "bias_ratio": i}
                        for i in range(br_mod.HISTORY_MAX + 50)]
            seed = dict(base)
            seed["_fingerprint"] = "SEED_DIFFERENT"
            seed["history"] = big_hist
            out.write_text(json.dumps(seed), encoding="utf-8")
            # a genuinely different result forces a new history entry
            changed = dict(base)
            changed["bias_ratio"] = 99.0
            self.assertEqual(br_mod.write_status(changed, d), "DATA_WRITTEN")
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertLessEqual(len(doc["history"]), br_mod.HISTORY_MAX)
            self.assertEqual(len(doc["history"]), br_mod.HISTORY_MAX)

    def test_tolerates_broken_previous(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / br_mod.STATUS_FILENAME
            out.write_text("{garbage", encoding="utf-8")
            res = self._good_result(d)
            self.assertEqual(br_mod.write_status(res, d), "DATA_WRITTEN")

    def test_creates_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "nested" / "data"
            # build needs an equity file; build in d, then write to nested dir
            returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
            _write_equity(d, _equity_doc(_equity_from_returns(returns)))
            res = br_mod.build_bias_ratio(d)
            self.assertEqual(br_mod.write_status(res, sub), "DATA_WRITTEN")
            self.assertTrue((sub / br_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# CLI: direct main(argv) + subprocess
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def _seed(self, d):
        returns = [0.004] * 9 + [-0.004] + [0.06, -0.06]
        _write_equity(d, _equity_doc(_equity_from_returns(returns)))

    def test_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = br_mod.main(["--check", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / br_mod.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = br_mod.main(["--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / br_mod.STATUS_FILENAME).exists())

    def test_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = br_mod.main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / br_mod.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            br_mod.main(["--run", "--data-dir", d])
            p = Path(d) / br_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            br_mod.main(["--run", "--data-dir", d])
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_conflict_check_run(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = br_mod.main(["--check", "--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / br_mod.STATUS_FILENAME).exists())

    def test_unknown_args(self):
        rc = br_mod.main(["--frobnicate"])
        self.assertEqual(rc, 0)

    def test_subprocess_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.bias_ratio",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("[bias_ratio]", proc.stdout)

    def test_subprocess_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.bias_ratio",
                 "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertTrue((Path(d) / br_mod.STATUS_FILENAME).exists())

    def test_subprocess_garbage_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / br_mod.EQUITY_FILENAME).write_text("{bad", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.paper_trading.bias_ratio",
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
        src = Path(br_mod.__file__).read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(src, br_mod.__file__)
        self.assertEqual(violations, [])

    def test_no_forbidden_text(self):
        # Strip the module docstring before scanning: the prose disclaimer
        # legitimately lists the forbidden module names and must not be flagged.
        src = Path(br_mod.__file__).read_text(encoding="utf-8")
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
        for fname in ("paper_trading/bias_ratio.py",
                      "tests/test_bias_ratio.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
