#!/usr/bin/env python3
"""Tests for the Upside Potential Ratio analyzer (SPA-V464 / MP-149).

Plain ``unittest`` -- no pytest, no network, all I/O confined to a tempdir.
Covers: hand-computed pure math (period_returns / upside_potential /
downside_deviation / upside_potential_ratio), verdict bands at the documented
thresholds, the low-sample (downside) guard, the no-downside degenerate case,
insufficient-data + never-raise / tolerance, reuse-by-import
(content_fingerprint + equity helper), atomic write_status idempotency /
rotation, CLI behaviour (direct + subprocess), and import hygiene.
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

from spa_core.paper_trading import upside_potential_ratio as upr_mod
from spa_core.paper_trading import drawdown_analytics
from spa_core.reporting import tear_sheet
from spa_core.ci import llm_forbidden_lint

_REPO_ROOT = Path(upr_mod.__file__).resolve().parents[2]


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
    (Path(data_dir) / upr_mod.EQUITY_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _build_from_returns(data_dir, returns, **kw):
    levels = _equity_from_returns(returns)
    _write_equity(data_dir, _equity_doc(levels, **kw))
    return upr_mod.build_upside_potential_ratio(data_dir)


def _track(u, d=0.01, k=4, m=4, n=40):
    """n returns: k downside at -d, m upside at +u, rest 0.

    With k=m=4, d=0.01, n=40 the partial moments are
    UP = m*u/40 and DD = d*sqrt(k/40) = 0.01*sqrt(0.1) = 0.00316228, so the
    Upside Potential Ratio is 0.1*u / 0.00316228 = 3.16228 * (u/d). count_downside
    = k (>= MIN_SIDE_OBS=3 by default, no cap path).
    """
    return [-d] * k + [u] * m + [0.0] * (n - k - m)


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: period_returns
# ─────────────────────────────────────────────────────────────────────────────

class TestPeriodReturns(unittest.TestCase):
    def test_hand_example(self):
        series = [("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]
        r = upr_mod.period_returns(series)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        self.assertAlmostEqual(r[1], -0.10, places=12)

    def test_len_is_n_minus_1(self):
        series = [(f"d{i}", 100.0 + i) for i in range(10)]
        self.assertEqual(len(upr_mod.period_returns(series)), 9)

    def test_empty_and_single(self):
        self.assertEqual(upr_mod.period_returns([]), [])
        self.assertEqual(upr_mod.period_returns([("d0", 100.0)]), [])

    def test_skips_nonpositive_prev(self):
        series = [("d0", 0.0), ("d1", 100.0), ("d2", 110.0)]
        r = upr_mod.period_returns(series)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], 0.10, places=12)
        for v in r:
            self.assertTrue(math.isfinite(v))

    def test_no_inf_or_nan(self):
        series = [("d0", 100.0), ("d1", 50.0), ("d2", 75.0), ("d3", 75.0)]
        for v in upr_mod.period_returns(series):
            self.assertTrue(math.isfinite(v))


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: upside_potential
# ─────────────────────────────────────────────────────────────────────────────

class TestUpsidePotential(unittest.TestCase):
    SAMPLE = [0.02, -0.01, 0.04, -0.03]

    def test_hand_example(self):
        # max-terms [0.02,0,0.04,0] -> mean 0.06/4 = 0.015
        self.assertAlmostEqual(
            upr_mod.upside_potential(self.SAMPLE, 0.0), 0.015, places=12
        )

    def test_over_all_returns_not_just_winners(self):
        # divisor is n=4, not the 2 winning days
        self.assertAlmostEqual(
            upr_mod.upside_potential([0.10, -0.10], 0.0), 0.05, places=12
        )

    def test_no_upside_is_zero(self):
        self.assertEqual(upr_mod.upside_potential([-0.01, -0.02, 0.0], 0.0), 0.0)

    def test_empty_is_zero(self):
        self.assertEqual(upr_mod.upside_potential([], 0.0), 0.0)

    def test_mar_shifts_threshold(self):
        # with mar=0.03 only the 0.04 return clears it: max(0.01,0)/4 ... others 0
        self.assertAlmostEqual(
            upr_mod.upside_potential(self.SAMPLE, 0.03), 0.01 / 4, places=12
        )

    def test_default_mar_is_zero(self):
        self.assertAlmostEqual(
            upr_mod.upside_potential(self.SAMPLE),
            upr_mod.upside_potential(self.SAMPLE, 0.0),
            places=15,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: downside_deviation
# ─────────────────────────────────────────────────────────────────────────────

class TestDownsideDeviation(unittest.TestCase):
    SAMPLE = [0.02, -0.01, 0.04, -0.03]

    def test_hand_example(self):
        # min-terms [0,-0.01,0,-0.03] -> squares [0,1e-4,0,9e-4] -> mean 2.5e-4
        # -> sqrt 0.0158113883...
        self.assertAlmostEqual(
            upr_mod.downside_deviation(self.SAMPLE, 0.0),
            math.sqrt(0.00025), places=12,
        )

    def test_over_all_returns_not_just_losers(self):
        # divisor is n=2: sqrt(mean([0, 0.01])) = sqrt(0.005)
        self.assertAlmostEqual(
            upr_mod.downside_deviation([0.10, -0.10], 0.0),
            math.sqrt((0.10 ** 2) / 2), places=12,
        )

    def test_no_downside_is_zero(self):
        self.assertEqual(upr_mod.downside_deviation([0.01, 0.02, 0.0], 0.0), 0.0)

    def test_empty_is_zero(self):
        self.assertEqual(upr_mod.downside_deviation([], 0.0), 0.0)

    def test_always_nonnegative(self):
        self.assertGreaterEqual(
            upr_mod.downside_deviation([-0.5, 0.5, -0.2], 0.0), 0.0
        )

    def test_default_mar_is_zero(self):
        self.assertAlmostEqual(
            upr_mod.downside_deviation(self.SAMPLE),
            upr_mod.downside_deviation(self.SAMPLE, 0.0),
            places=15,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pure math: upside_potential_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestUprPure(unittest.TestCase):
    def test_hand_example(self):
        self.assertAlmostEqual(
            upr_mod.upside_potential_ratio(0.015, math.sqrt(0.00025)),
            0.015 / math.sqrt(0.00025), places=12,
        )

    def test_basic(self):
        self.assertAlmostEqual(
            upr_mod.upside_potential_ratio(0.03, 0.015), 2.0, places=12
        )

    def test_none_inputs(self):
        self.assertIsNone(upr_mod.upside_potential_ratio(None, 2.0))
        self.assertIsNone(upr_mod.upside_potential_ratio(1.0, None))

    def test_nonpositive_dd_none(self):
        self.assertIsNone(upr_mod.upside_potential_ratio(1.0, 0.0))
        self.assertIsNone(upr_mod.upside_potential_ratio(1.0, -0.5))

    def test_symmetric_one(self):
        self.assertAlmostEqual(
            upr_mod.upside_potential_ratio(2.0, 2.0), 1.0, places=12
        )

    def test_zero_up_positive_dd_is_zero(self):
        self.assertAlmostEqual(
            upr_mod.upside_potential_ratio(0.0, 0.5), 0.0, places=12
        )


# ─────────────────────────────────────────────────────────────────────────────
# build_upside_potential_ratio: verdict bands
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictBands(unittest.TestCase):
    # n=40, k=m=4 downside obs -> count_downside=4 (>= MIN_SIDE_OBS=3, no cap)

    def test_fail_downside_dominates(self):
        # u/d=1.264912 -> UPR ~= 0.4 (< UPR_FAIL 0.5)
        res = self._build(_track(0.01264912))
        self.assertTrue(res["available"])
        self.assertEqual(res["count_downside"], 4)
        self.assertAlmostEqual(res["upside_potential_ratio"], 0.4, places=4)
        self.assertEqual(res["verdict"], "fail")

    def test_warn_below_reference(self):
        # u/d=2.37171 -> UPR ~= 0.75 (in [FAIL, WARN))
        res = self._build(_track(0.0237171))
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["upside_potential_ratio"], 0.75, places=4)
        self.assertEqual(res["verdict"], "warn")

    def test_ok_at_reference(self):
        # u/d=3.16228 -> UPR ~= 1.0 (>= WARN)
        res = self._build(_track(0.0316228))
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["upside_potential_ratio"], 1.0, places=4)
        self.assertEqual(res["verdict"], "ok")

    def test_ok_strongly_above(self):
        res = self._build(_track(0.06))  # u/d=6 -> UPR ~= 1.9
        self.assertEqual(res["verdict"], "ok")
        self.assertGreater(res["upside_potential_ratio"], 1.0)

    def test_headline_keys_present(self):
        res = self._build(_track(0.0316228))
        for key in ("upside_potential_ratio", "upside_potential",
                    "downside_deviation", "mar", "count_upside",
                    "count_downside", "count_returns", "mean_return",
                    "n_observations", "start_date", "end_date", "is_demo",
                    "verdict", "verdict_reason", "notes"):
            self.assertIn(key, res)

    def test_mar_is_zero_in_output(self):
        res = self._build(_track(0.0316228))
        self.assertEqual(res["mar"], 0.0)

    def test_counts_consistent(self):
        res = self._build(_track(0.0316228))
        self.assertEqual(res["count_upside"], 4)
        self.assertEqual(res["count_downside"], 4)
        self.assertEqual(res["count_returns"], 40)
        self.assertEqual(res["n_observations"], 40)

    def test_verdict_reason_always_present(self):
        res = self._build(_track(0.01264912))
        self.assertIn("verdict_reason", res)
        self.assertTrue(res["verdict_reason"])

    def test_band_invariant(self):
        # verdict must be consistent with the ratio + thresholds (no cap path)
        for u, exp in ((0.01264912, "fail"), (0.0237171, "warn"),
                       (0.0316228, "ok"), (0.06, "ok")):
            res = self._build(_track(u))
            with self.subTest(u=u):
                upr = res["upside_potential_ratio"]
                if upr < upr_mod.UPR_FAIL:
                    self.assertEqual(res["verdict"], "fail")
                elif upr < upr_mod.UPR_WARN:
                    self.assertEqual(res["verdict"], "warn")
                else:
                    self.assertEqual(res["verdict"], "ok")
                self.assertEqual(res["verdict"], exp)

    def _build(self, returns, **kw):
        with tempfile.TemporaryDirectory() as d:
            return _build_from_returns(d, returns, **kw)


# ─────────────────────────────────────────────────────────────────────────────
# build_upside_potential_ratio: low-sample (downside) guard
# ─────────────────────────────────────────────────────────────────────────────

class TestLowSampleGuard(unittest.TestCase):
    def test_caps_fail_to_warn(self):
        # only 2 downside obs (< MIN_SIDE_OBS=3); u/d=1 -> UPR ~= 0.224 (< FAIL)
        # would be fail but capped to warn.
        returns = [-0.01] * 2 + [0.01] * 2 + [0.0] * 36
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertEqual(res["count_downside"], 2)
        self.assertLess(res["upside_potential_ratio"], upr_mod.UPR_FAIL)
        self.assertEqual(res["verdict"], "warn")
        self.assertTrue(any("low-sample guard" in n for n in res["notes"]))

    def test_three_downside_not_capped(self):
        # exactly MIN_SIDE_OBS=3 downside obs -> the guard does NOT fire; a
        # genuine fail stays fail. k=3 d=0.01 -> DD=0.01*sqrt(3/40)=0.0027386;
        # u=0.001,m=3 -> UP=3*0.001/40=7.5e-5 -> UPR ~= 0.0274 (fail).
        returns = [-0.01] * 3 + [0.001] * 3 + [0.0] * 34
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertEqual(res["count_downside"], 3)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(any("low-sample guard" in n for n in res["notes"]))

    def test_cap_only_affects_fail(self):
        # 2 downside obs but UPR in the warn band -> stays warn, no cap note
        # (the guard only rescues a fail). u/d chosen for UPR ~= 0.75.
        # k=2 d=0.01 -> DD=0.01*sqrt(2/40)=0.00223607; want UP=0.75*DD=0.00167705
        # -> m=2,u: 2u/40=u/20=0.00167705 -> u=0.0335410
        returns = [-0.01] * 2 + [0.0335410] * 2 + [0.0] * 36
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertEqual(res["count_downside"], 2)
        self.assertEqual(res["verdict"], "warn")
        self.assertFalse(any("low-sample guard" in n for n in res["notes"]))


# ─────────────────────────────────────────────────────────────────────────────
# build_upside_potential_ratio: degenerate (no downside) + insufficient data
# ─────────────────────────────────────────────────────────────────────────────

class TestDegenerate(unittest.TestCase):
    def test_no_downside(self):
        # all returns non-negative -> DD == 0 -> ratio undefined
        returns = [0.0] * 36 + [0.01] * 4
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertIsNone(res["upside_potential_ratio"])
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(res["count_downside"], 0)
        self.assertTrue(any("no downside observations" in n for n in res["notes"]))

    def test_no_downside_note_text(self):
        returns = [0.0] * 36 + [0.01] * 4
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(any(
            n == "Upside Potential Ratio undefined (no downside observations)"
            for n in res["notes"]
        ))

    def test_all_flat(self):
        # every return exactly 0 -> no upside AND no downside -> undefined ok
        returns = [0.0] * 40
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, returns)
        self.assertTrue(res["available"])
        self.assertIsNone(res["upside_potential_ratio"])
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(res["downside_deviation"], 0.0)

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
            res = upr_mod.build_upside_potential_ratio(d)
        self.assertFalse(res["available"])
        self.assertEqual(res["verdict"], "ok")

    def test_schema_stable_when_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            _write_equity(d, {"daily": []})
            res = upr_mod.build_upside_potential_ratio(d)
        for key in ("available", "upside_potential_ratio", "upside_potential",
                    "downside_deviation", "mar", "count_upside",
                    "count_downside", "count_returns", "mean_return",
                    "n_observations", "start_date", "end_date", "verdict",
                    "verdict_reason", "notes", "meta"):
            self.assertIn(key, res)


# ─────────────────────────────────────────────────────────────────────────────
# is_demo passthrough
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDemo(unittest.TestCase):
    RETURNS = _track(0.0316228)

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
            res = upr_mod.build_upside_potential_ratio(d)
        self.assertFalse(res["available"])

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / upr_mod.EQUITY_FILENAME).write_text("{not json", encoding="utf-8")
            res = upr_mod.build_upside_potential_ratio(d)
        self.assertFalse(res["available"])

    def test_non_dict_root(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / upr_mod.EQUITY_FILENAME).write_text("123", encoding="utf-8")
            res = upr_mod.build_upside_potential_ratio(d)
        self.assertFalse(res["available"])

    def test_list_root(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [{"date": dt, "close_equity": 100.0 + i}
                    for i, dt in enumerate(_dates(30))]
            (Path(d) / upr_mod.EQUITY_FILENAME).write_text(
                json.dumps(bars), encoding="utf-8"
            )
            res = upr_mod.build_upside_potential_ratio(d)
        # a bare list IS accepted by extract_equity_series -> should be available
        self.assertTrue(res["available"])

    def test_garbage_bars(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"daily": ["nope", 7, None, {"date": "bad"}, {}]}
            _write_equity(d, doc)
            res = upr_mod.build_upside_potential_ratio(d)
        self.assertFalse(res["available"])

    def test_fuzz_never_raises(self):
        rnd = random.Random(13)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / upr_mod.EQUITY_FILENAME
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
                res = upr_mod.build_upside_potential_ratio(d)
                self.assertIn("verdict", res)
                self.assertIn(res["verdict"], ("ok", "warn", "fail"))


# ─────────────────────────────────────────────────────────────────────────────
# reuse-by-import (single source of truth)
# ─────────────────────────────────────────────────────────────────────────────

class TestReuseByImport(unittest.TestCase):
    def test_content_fingerprint_is_tear_sheet_object(self):
        self.assertIs(upr_mod.content_fingerprint, tear_sheet.content_fingerprint)

    def test_extract_equity_series_is_drawdown_object(self):
        self.assertIs(
            upr_mod.extract_equity_series, drawdown_analytics.extract_equity_series
        )

    def test_fingerprint_ignores_volatile_fields(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _track(0.0316228))
            a = dict(res)
            b = dict(res)
            b["meta"] = dict(b["meta"])
            b["meta"]["generated_at"] = "DIFFERENT"
            b["history"] = [{"x": 1}]
            self.assertEqual(
                upr_mod.content_fingerprint(a), upr_mod.content_fingerprint(b)
            )

    def test_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as d:
            res = _build_from_returns(d, _track(0.0316228))
            a = dict(res)
            b = dict(res)
            b["upside_potential_ratio"] = 99.0
            self.assertNotEqual(
                upr_mod.content_fingerprint(a), upr_mod.content_fingerprint(b)
            )


# ─────────────────────────────────────────────────────────────────────────────
# write_status: idempotency / rotation / atomicity
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStatus(unittest.TestCase):
    GOOD = _track(0.0316228)

    def _good_result(self, d):
        return _build_from_returns(d, self.GOOD)

    def test_written_then_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            self.assertEqual(upr_mod.write_status(res, d), "DATA_WRITTEN")
            res2 = upr_mod.build_upside_potential_ratio(d)  # fresh generated_at
            self.assertEqual(upr_mod.write_status(res2, d), "DATA_UNCHANGED")

    def test_md5_identical_on_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            upr_mod.write_status(res, d)
            p = Path(d) / upr_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            res2 = upr_mod.build_upside_potential_ratio(d)
            upr_mod.write_status(res2, d)
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._good_result(d)
            upr_mod.write_status(res, d)
            leftovers = list(Path(d).glob(".tmp_upside_potential_ratio_*"))
            self.assertEqual(leftovers, [])

    def test_history_rotation_exactly_max(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / upr_mod.STATUS_FILENAME
            base = self._good_result(d)
            big_hist = [{"_fingerprint": f"x{i}", "upside_potential_ratio": i}
                        for i in range(upr_mod.HISTORY_MAX + 50)]
            seed = dict(base)
            seed["_fingerprint"] = "SEED_DIFFERENT"
            seed["history"] = big_hist
            out.write_text(json.dumps(seed), encoding="utf-8")
            changed = dict(base)
            changed["upside_potential_ratio"] = 99.0
            self.assertEqual(upr_mod.write_status(changed, d), "DATA_WRITTEN")
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(doc["history"]), upr_mod.HISTORY_MAX)

    def test_tolerates_broken_previous(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / upr_mod.STATUS_FILENAME
            out.write_text("{garbage", encoding="utf-8")
            res = self._good_result(d)
            self.assertEqual(upr_mod.write_status(res, d), "DATA_WRITTEN")

    def test_creates_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "nested" / "data"
            _write_equity(d, _equity_doc(_equity_from_returns(self.GOOD)))
            res = upr_mod.build_upside_potential_ratio(d)
            self.assertEqual(upr_mod.write_status(res, sub), "DATA_WRITTEN")
            self.assertTrue((sub / upr_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# CLI: direct main(argv) + subprocess
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    GOOD = _track(0.0316228)

    def _seed(self, d):
        _write_equity(d, _equity_doc(_equity_from_returns(self.GOOD)))

    def test_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = upr_mod.main(["--check", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / upr_mod.STATUS_FILENAME).exists())

    def test_default_is_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = upr_mod.main(["--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / upr_mod.STATUS_FILENAME).exists())

    def test_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = upr_mod.main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / upr_mod.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            upr_mod.main(["--run", "--data-dir", d])
            p = Path(d) / upr_mod.STATUS_FILENAME
            m1 = hashlib.md5(p.read_bytes()).hexdigest()
            upr_mod.main(["--run", "--data-dir", d])
            m2 = hashlib.md5(p.read_bytes()).hexdigest()
        self.assertEqual(m1, m2)

    def test_conflict_check_run(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            rc = upr_mod.main(["--check", "--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / upr_mod.STATUS_FILENAME).exists())

    def test_unknown_args(self):
        rc = upr_mod.main(["--frobnicate"])
        self.assertEqual(rc, 0)

    def test_subprocess_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.upside_potential_ratio",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("[upside_potential_ratio]", proc.stdout)

    def test_subprocess_run_writes(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.upside_potential_ratio",
                 "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertTrue((Path(d) / upr_mod.STATUS_FILENAME).exists())

    def test_subprocess_garbage_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / upr_mod.EQUITY_FILENAME).write_text("{bad", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.upside_potential_ratio",
                 "--check", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_conflict_no_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            proc = subprocess.run(
                [sys.executable, "-m",
                 "spa_core.paper_trading.upside_potential_ratio",
                 "--check", "--run", "--data-dir", d],
                cwd=str(_REPO_ROOT), capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertFalse((Path(d) / upr_mod.STATUS_FILENAME).exists())


# ─────────────────────────────────────────────────────────────────────────────
# import hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = Path(upr_mod.__file__).read_text(encoding="utf-8")
        violations = llm_forbidden_lint.find_forbidden_imports(src, upr_mod.__file__)
        self.assertEqual(violations, [])

    def test_no_forbidden_text(self):
        # Strip the module docstring before scanning: the prose disclaimer
        # legitimately lists the forbidden module names and must not be flagged.
        src = Path(upr_mod.__file__).read_text(encoding="utf-8")
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
        for fname in ("paper_trading/upside_potential_ratio.py",
                      "tests/test_upside_potential_ratio.py"):
            with self.subTest(fname=fname):
                py_compile.compile(
                    str(_REPO_ROOT / "spa_core" / fname), doraise=True
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
