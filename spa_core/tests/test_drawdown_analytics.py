#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.drawdown_analytics (SPA-V433 / MP-115).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:
equity-series extraction, the underwater curve, drawdown-episode detection
(recovered / ongoing / multiple / none boundaries), reuse-by-import equality
with tear_sheet's max_drawdown_from_returns, the aggregate headline, honest
handling of missing/broken/empty input, idempotent persistence + history
rotation, the CLI (direct + subprocess), and import hygiene via the real AST
linter.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading import drawdown_analytics as dd
from spa_core.reporting.tear_sheet import max_drawdown_from_returns

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _equity_doc(levels, start="2026-06-10", is_demo=False):
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
    p = data_dir / dd.EQUITY_FILENAME
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _series(levels, start="2026-06-10"):
    return dd.extract_equity_series(_equity_doc(levels, start=start))


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dd_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── Equity-series extraction ────────────────────────────────────────────────


class TestExtractSeries(unittest.TestCase):
    def test_dict_wrapper(self):
        s = dd.extract_equity_series(_equity_doc([100, 101, 102]))
        self.assertEqual([v for _, v in s], [100.0, 101.0, 102.0])

    def test_bare_list(self):
        bars = _equity_doc([100, 101])["daily"]
        s = dd.extract_equity_series(bars)
        self.assertEqual(len(s), 2)

    def test_close_equity_preferred_over_equity(self):
        doc = {"daily": [{"date": "2026-06-10", "close_equity": 100, "equity": 999}]}
        self.assertEqual(dd.extract_equity_series(doc), [("2026-06-10", 100.0)])

    def test_equity_fallback_when_no_close(self):
        doc = {"daily": [{"date": "2026-06-10", "equity": 123.0}]}
        self.assertEqual(dd.extract_equity_series(doc), [("2026-06-10", 123.0)])

    def test_skips_bad_bars(self):
        doc = {"daily": [
            {"date": "2026-06-10", "close_equity": 100},
            {"date": "not-a-date", "close_equity": 200},
            {"close_equity": 300},
            "garbage",
            {"date": "2026-06-11", "close_equity": "x"},
            {"date": "2026-06-12", "close_equity": 105},
        ]}
        self.assertEqual([v for _, v in dd.extract_equity_series(doc)], [100.0, 105.0])

    def test_drops_nonpositive(self):
        doc = {"daily": [
            {"date": "2026-06-10", "close_equity": 0},
            {"date": "2026-06-11", "close_equity": -5},
            {"date": "2026-06-12", "close_equity": 50},
        ]}
        self.assertEqual([v for _, v in dd.extract_equity_series(doc)], [50.0])

    def test_sorts_by_date(self):
        doc = {"daily": [
            {"date": "2026-06-12", "close_equity": 3},
            {"date": "2026-06-10", "close_equity": 1},
            {"date": "2026-06-11", "close_equity": 2},
        ]}
        self.assertEqual([d for d, _ in dd.extract_equity_series(doc)],
                         ["2026-06-10", "2026-06-11", "2026-06-12"])

    def test_bad_input_empty(self):
        for bad in (None, 42, "x", {}, {"daily": "x"}, {"daily": 5}):
            self.assertEqual(dd.extract_equity_series(bad), [])


# ─── Underwater curve ────────────────────────────────────────────────────────


class TestUnderwater(unittest.TestCase):
    def test_monotonic_zero(self):
        curve = dd.underwater_curve(_series([100, 110, 120]))
        self.assertTrue(all(dval == 0.0 for _, dval in curve))

    def test_running_peak(self):
        curve = dd.underwater_curve(_series([100, 90, 95]))
        vals = [round(v, 4) for _, v in curve]
        self.assertEqual(vals, [0.0, -10.0, -5.0])

    def test_empty(self):
        self.assertEqual(dd.underwater_curve([]), [])


# ─── Episode detection ───────────────────────────────────────────────────────


class TestEpisodes(unittest.TestCase):
    def test_monotonic_no_episode(self):
        self.assertEqual(dd.detect_drawdown_episodes(_series([100, 101, 102, 103])), [])

    def test_flat_no_episode(self):
        self.assertEqual(dd.detect_drawdown_episodes(_series([100, 100, 100])), [])

    def test_too_short(self):
        self.assertEqual(dd.detect_drawdown_episodes(_series([100])), [])
        self.assertEqual(dd.detect_drawdown_episodes([]), [])

    def test_single_recovered(self):
        eps = dd.detect_drawdown_episodes(_series([100, 90, 95, 100, 100]))
        self.assertEqual(len(eps), 1)
        e = eps[0]
        self.assertEqual(e["peak_date"], "2026-06-10")
        self.assertEqual(e["peak_value"], 100.0)
        self.assertEqual(e["trough_date"], "2026-06-11")
        self.assertEqual(e["trough_value"], 90.0)
        self.assertEqual(e["depth_pct"], -10.0)
        self.assertEqual(e["decline_days"], 1)
        self.assertEqual(e["recovery_date"], "2026-06-13")
        self.assertEqual(e["recovery_days"], 2)
        self.assertEqual(e["underwater_days"], 3)
        self.assertTrue(e["recovered"])

    def test_ongoing_unrecovered(self):
        # peak 110 @ d1, then 100, 95 — still underwater at end of track
        eps = dd.detect_drawdown_episodes(_series([100, 110, 100, 95]))
        self.assertEqual(len(eps), 1)
        e = eps[0]
        self.assertFalse(e["recovered"])
        self.assertIsNone(e["recovery_date"])
        self.assertIsNone(e["recovery_days"])
        self.assertEqual(e["peak_value"], 110.0)
        self.assertEqual(e["trough_value"], 95.0)
        self.assertEqual(e["depth_pct"], round((95 / 110 - 1) * 100, 6))
        self.assertEqual(e["underwater_days"], 2)  # d1 (06-11) → d3 (06-13)

    def test_two_episodes(self):
        eps = dd.detect_drawdown_episodes(_series([100, 90, 100, 95, 100]))
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0]["depth_pct"], -10.0)
        self.assertEqual(eps[1]["depth_pct"], -5.0)
        self.assertTrue(all(e["recovered"] for e in eps))

    def test_trough_tracks_lowest(self):
        # decline 100 -> 95 -> 80 -> 90 -> recover; trough must be 80
        eps = dd.detect_drawdown_episodes(_series([100, 95, 80, 90, 100]))
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]["trough_value"], 80.0)
        self.assertEqual(eps[0]["trough_date"], "2026-06-12")


# ─── Reuse-by-import equality with tear_sheet ────────────────────────────────


class TestReuseEquality(unittest.TestCase):
    def test_worst_depth_equals_tear_sheet_maxdd(self):
        for levels in ([100, 90, 95, 100, 100],
                       [100, 110, 100, 95],
                       [100, 95, 80, 90, 100],
                       [100, 90, 100, 95, 100]):
            series = _series(levels)
            returns = dd._returns_from_levels(series)
            expected = round(max_drawdown_from_returns(returns), 6)
            eps = dd.detect_drawdown_episodes(series)
            worst = min(e["depth_pct"] for e in eps)
            self.assertAlmostEqual(worst, expected, places=6, msg=str(levels))

    def test_headline_maxdd_uses_reused_helper(self):
        out = _build([100, 90, 95, 100, 100])
        series = _series([100, 90, 95, 100, 100])
        expected = round(max_drawdown_from_returns(dd._returns_from_levels(series)), 6)
        self.assertEqual(out["headline"]["max_drawdown_pct"], expected)


def _build(levels, start="2026-06-10", is_demo=False, data_dir=None):
    """Build analytics from in-memory levels via a tempdir round-trip."""
    if data_dir is None:
        tmp = tempfile.mkdtemp(prefix="dd_build_")
        data_dir = Path(tmp)
    _write_equity(Path(data_dir), _equity_doc(levels, start=start, is_demo=is_demo))
    return dd.build_drawdown_analytics(data_dir=data_dir)


# ─── Aggregate build ─────────────────────────────────────────────────────────


class TestBuild(_TmpBase):
    def test_recovered_headline(self):
        out = _build([100, 90, 95, 100, 100], data_dir=self.data_dir)
        h = out["headline"]
        self.assertTrue(out["available"])
        self.assertEqual(h["max_drawdown_pct"], -10.0)
        self.assertEqual(h["num_episodes"], 1)
        self.assertEqual(h["num_recovered"], 1)
        self.assertEqual(h["num_ongoing"], 0)
        self.assertFalse(h["currently_underwater"])
        self.assertEqual(h["current_drawdown_pct"], 0.0)
        # underwater bars: d1(-10), d2(-5) of 5 bars → 40%
        self.assertEqual(h["time_in_drawdown_pct"], 40.0)
        self.assertEqual(h["worst_episode"]["depth_pct"], -10.0)

    def test_ongoing_headline(self):
        out = _build([100, 110, 100, 95], data_dir=self.data_dir)
        h = out["headline"]
        self.assertTrue(h["currently_underwater"])
        self.assertEqual(h["num_ongoing"], 1)
        self.assertEqual(h["num_recovered"], 0)
        self.assertIsNone(h["avg_recovery_days"])
        self.assertEqual(h["current_drawdown_pct"], round((95 / 110 - 1) * 100, 6))

    def test_two_episodes_averages(self):
        out = _build([100, 90, 100, 95, 100], data_dir=self.data_dir)
        h = out["headline"]
        self.assertEqual(h["num_episodes"], 2)
        self.assertEqual(h["avg_depth_pct"], -7.5)
        self.assertEqual(h["worst_episode"]["depth_pct"], -10.0)

    def test_monotonic_no_drawdown(self):
        out = _build([100, 101, 102, 103], data_dir=self.data_dir)
        h = out["headline"]
        self.assertEqual(h["num_episodes"], 0)
        self.assertEqual(h["max_drawdown_pct"], 0.0)
        self.assertEqual(h["time_in_drawdown_pct"], 0.0)
        self.assertFalse(h["currently_underwater"])
        self.assertIsNone(h["worst_episode"])

    def test_longest_underwater(self):
        # two episodes, second one longer underwater
        out = _build([100, 90, 100, 95, 96, 97, 100], data_dir=self.data_dir)
        # ep1 underwater 06-10->06-12 = 2d; ep2 06-12->06-16 = 4d
        self.assertEqual(out["headline"]["longest_underwater_days"], 4)

    def test_track_section(self):
        out = _build([100, 90, 100], data_dir=self.data_dir)
        self.assertEqual(out["track"]["num_bars"], 3)
        self.assertEqual(out["track"]["first_date"], "2026-06-10")
        self.assertEqual(out["track"]["last_date"], "2026-06-12")
        self.assertIsNotNone(out["track"]["total_return_pct"])

    def test_recent_underwater_bounded(self):
        levels = [100] + [100 - i * 0.01 for i in range(1, 200)]
        out = _build(levels, data_dir=self.data_dir)
        self.assertLessEqual(len(out["recent_underwater"]), dd.RECENT_UNDERWATER_MAX)

    def test_meta_fields(self):
        out = _build([100, 90, 100], data_dir=self.data_dir)
        m = out["meta"]
        self.assertTrue(m["advisory_only"])
        self.assertEqual(m["disclaimer"], "NOT investment advice")
        self.assertEqual(m["source_file"], dd.EQUITY_FILENAME)
        self.assertEqual(m["real_track_start"], dd.REAL_TRACK_START)
        self.assertIn("generated_at", m)

    def test_is_demo_honest(self):
        self.assertFalse(_build([100, 90, 100], is_demo=False,
                                data_dir=self.data_dir)["meta"]["is_demo"])
        t = Path(tempfile.mkdtemp(prefix="dd_demo_"))
        self.assertTrue(_build([100, 90, 100], is_demo=True,
                               data_dir=t)["meta"]["is_demo"])

    def test_is_demo_null_when_absent(self):
        doc = {"daily": _equity_doc([100, 90, 100])["daily"]}  # no is_demo key
        _write_equity(self.data_dir, doc)
        out = dd.build_drawdown_analytics(data_dir=self.data_dir)
        self.assertIsNone(out["meta"]["is_demo"])

    def test_missing_file_honest(self):
        out = dd.build_drawdown_analytics(data_dir=self.data_dir)  # empty dir
        self.assertFalse(out["available"])
        self.assertEqual(out["headline"]["num_episodes"], 0)
        self.assertIsNone(out["headline"]["max_drawdown_pct"])
        self.assertTrue(any("missing" in n for n in out["meta"]["notes"]))

    def test_broken_file_tolerated(self):
        (self.data_dir / dd.EQUITY_FILENAME).write_text("{ not json", encoding="utf-8")
        out = dd.build_drawdown_analytics(data_dir=self.data_dir)
        self.assertFalse(out["available"])

    def test_single_bar_unavailable(self):
        _write_equity(self.data_dir, _equity_doc([100]))
        out = dd.build_drawdown_analytics(data_dir=self.data_dir)
        self.assertFalse(out["available"])
        self.assertEqual(out["track"]["num_bars"], 1)

    def test_never_raises_on_garbage(self):
        for bad in ('{"daily": "x"}', '[]', '{"daily": []}', 'null', '123'):
            (self.data_dir / dd.EQUITY_FILENAME).write_text(bad, encoding="utf-8")
            out = dd.build_drawdown_analytics(data_dir=self.data_dir)
            self.assertIn("available", out)


# ─── Persistence / idempotency ───────────────────────────────────────────────


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class TestPersistence(_TmpBase):
    def _status_path(self):
        return self.data_dir / dd.STATUS_FILENAME

    def test_run_writes(self):
        doc = _build([100, 90, 100], data_dir=self.data_dir)
        out = dd.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        self.assertTrue(self._status_path().exists())
        loaded = json.loads(self._status_path().read_text())
        self.assertIn("history", loaded)
        self.assertEqual(len(loaded["history"]), 1)

    def test_idempotent_byte_identical(self):
        d1 = dd.build_drawdown_analytics(
            data_dir=self.data_dir, now=datetime(2026, 6, 12, tzinfo=timezone.utc))
        # write requires the equity file present
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        d1 = dd.build_drawdown_analytics(data_dir=self.data_dir)
        dd.write_status(d1, data_dir=self.data_dir)
        h1 = _md5(self._status_path())
        # second build has a fresh generated_at but identical content
        d2 = dd.build_drawdown_analytics(data_dir=self.data_dir)
        self.assertNotEqual(d1["meta"]["generated_at"], d2["meta"]["generated_at"])
        out2 = dd.write_status(d2, data_dir=self.data_dir)
        self.assertFalse(out2["changed"])
        self.assertEqual(h1, _md5(self._status_path()))

    def test_generated_at_preserved_when_unchanged(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        d1 = dd.build_drawdown_analytics(data_dir=self.data_dir)
        dd.write_status(d1, data_dir=self.data_dir)
        stored = json.loads(self._status_path().read_text())["meta"]["generated_at"]
        d2 = dd.build_drawdown_analytics(data_dir=self.data_dir)
        dd.write_status(d2, data_dir=self.data_dir)
        again = json.loads(self._status_path().read_text())["meta"]["generated_at"]
        self.assertEqual(stored, again)

    def test_history_grows_on_change(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        dd.write_status(dd.build_drawdown_analytics(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        _write_equity(self.data_dir, _equity_doc([100, 80, 100]))  # deeper dd
        dd.write_status(dd.build_drawdown_analytics(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        hist = json.loads(self._status_path().read_text())["history"]
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[-1]["max_drawdown_pct"], -20.0)

    def test_history_rotation(self):
        doc = _build([100, 90, 100], data_dir=self.data_dir)
        prev = dict(doc)
        prev["history"] = [{"generated_at": f"t{i}"} for i in range(600)]
        prev["headline"] = dict(doc["headline"])
        prev["headline"]["num_episodes"] = 999  # ensure CONTENT fingerprint differs
        dd._atomic_write_json(self._status_path(), prev)
        out = dd.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        hist = json.loads(self._status_path().read_text())["history"]
        self.assertEqual(len(hist), dd.HISTORY_MAX)

    def test_no_tmp_left(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        dd.write_status(dd.build_drawdown_analytics(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_broken_prev_status_tolerated(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        self._status_path().write_text("{ broken", encoding="utf-8")
        out = dd.write_status(dd.build_drawdown_analytics(data_dir=self.data_dir),
                              data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        self.assertEqual(len(json.loads(self._status_path().read_text())["history"]), 1)


# ─── content_fingerprint ─────────────────────────────────────────────────────


class TestFingerprint(unittest.TestCase):
    def test_ignores_volatile(self):
        a = {"meta": {"generated_at": "A", "x": 1}, "headline": {"n": 1}}
        b = {"meta": {"generated_at": "B", "x": 1}, "headline": {"n": 1},
             "history": [1, 2, 3]}
        self.assertEqual(dd.content_fingerprint(a), dd.content_fingerprint(b))

    def test_detects_content_change(self):
        a = {"meta": {"generated_at": "A"}, "headline": {"n": 1}}
        b = {"meta": {"generated_at": "A"}, "headline": {"n": 2}}
        self.assertNotEqual(dd.content_fingerprint(a), dd.content_fingerprint(b))

    def test_non_dict(self):
        self.assertEqual(dd.content_fingerprint(None), "<invalid>")


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpBase):
    def _run(self, argv):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            rc = dd.main(argv)
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def test_check_default_prints_json(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        rc, out, _ = self._run(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        self.assertIn("headline", parsed)

    def test_check_does_not_write(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        before = sorted(p.name for p in self.data_dir.iterdir())
        self._run(["--check", "--data-dir", str(self.data_dir)])
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertNotIn(dd.STATUS_FILENAME, after)

    def test_run_writes(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        rc, out, _ = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / dd.STATUS_FILENAME).exists())

    def test_run_idempotent(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        self._run(["--run", "--data-dir", str(self.data_dir)])
        rc, out, _ = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("idempotent", out)

    def test_empty_data_dir_exit0(self):
        rc, out, _ = self._run(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("available", out)

    def test_junk_arg_exit0_no_traceback(self):
        rc, out, err = self._run(["--frobnicate"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_conflicting_flags_exit0(self):
        rc, _, err = self._run(["--check", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)

    def test_subprocess_check(self):
        _write_equity(self.data_dir, _equity_doc([100, 90, 100]))
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.drawdown_analytics",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("headline", proc.stdout)

    def test_subprocess_junk_arg(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.drawdown_analytics",
             "--nope"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)


# ─── Import hygiene ──────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    def _src(self, name):
        return (_REPO_ROOT / name).read_text(encoding="utf-8")

    def test_module_no_forbidden_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._src("spa_core/paper_trading/drawdown_analytics.py")
        self.assertEqual(
            find_forbidden_imports(src, "drawdown_analytics.py"), [])

    def test_test_no_forbidden_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._src("spa_core/tests/test_drawdown_analytics.py")
        self.assertEqual(
            find_forbidden_imports(src, "test_drawdown_analytics.py"), [])

    def test_reuses_tear_sheet_by_import(self):
        src = self._src("spa_core/paper_trading/drawdown_analytics.py")
        self.assertIn("from spa_core.reporting.tear_sheet import", src)
        self.assertIn("max_drawdown_from_returns", src)

    def test_no_network_libs(self):
        src = self._src("spa_core/paper_trading/drawdown_analytics.py")
        for banned in ("import requests", "import socket", "import web3", "urllib"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
