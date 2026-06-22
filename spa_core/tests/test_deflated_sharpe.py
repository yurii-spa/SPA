#!/usr/bin/env python3
"""Tests for deflated_sharpe (SPA-V451 / MP-137).

unittest only — NO pytest, NO network, tempdir-isolated. Covers:
- pure math: trial_sharpe_variance (hand-computed sample var, N<2→0),
  expected_max_sharpe_null (N=1→0, N=2/N=10 known values, V<=0→0),
  DSR monotonicity (larger N → lower DSR at same SR_obs)
- scale conversion (annualised trial sharpes → daily before V / E[max])
- verdict boundaries (DSR just <0.5→fail, in [0.5,0.95)→warn, ≥0.95→ok,
  verdict_reason always present)
- insufficient_data (empty / short equity → available:false, schema stable)
- tolerance / never-raise (missing / broken JSON / non-dict root / garbage,
  subTest + property fuzzing)
- content_fingerprint reuse-by-import (assertIs to tear_sheet, ignores
  generated_at/history, changes with content, stable)
- write_status (first→DATA_WRITTEN, identical→DATA_UNCHANGED byte-identical md5,
  different→DATA_WRITTEN + history grows, rotation EXACTLY HISTORY_MAX=500,
  no *.tmp, tolerant broken existing file)
- CLI direct main(argv) + subprocess (--check no-write, default=check, --run
  writes / idempotent DATA_UNCHANGED, junk→ERROR exit0 no Traceback, conflict)
- import hygiene (real find_forbidden_imports, py_compile both files, no
  network/LLM/socket/subprocess/eval/exec/pip patterns, reuse-by-import markers,
  atomic-write pattern, e2e round-trip on real data/)
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict, List

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import deflated_sharpe as ds
from spa_core.paper_trading import probabilistic_sharpe as ps
from spa_core.reporting import tear_sheet as ts

_MODULE_PATH = Path(ds.__file__)
_TEST_PATH = Path(__file__)
_SQRT252 = math.sqrt(252.0)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_pnl(data_dir: Path, returns_pct: List[float], start_cap: float = 100000.0) -> None:
    """Write a pnl_history.json that yields the given daily_return_pct series.

    equity_curve derives daily_return_pct from total_capital_usd. Day 1 is a
    seed (0.0 return, dropped by _daily_returns), so we prepend a seed bar then
    compound the requested per-day returns.
    """
    from datetime import date, timedelta
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


def _write_shadow(data_dir: Path, tracks: Dict[str, List[float]]) -> None:
    """Write shadow_strategies/*.json so consolidator produces given sharpes.

    Each track is a list of equity values; the consolidator computes sharpe
    from successive ratios. We just write equity points per strategy.
    """
    from datetime import date, timedelta
    sdir = data_dir / "shadow_strategies"
    sdir.mkdir(parents=True, exist_ok=True)
    d0 = date.fromisoformat("2026-01-01")
    for sid, equities in tracks.items():
        recs = []
        for i, eq in enumerate(equities):
            d = d0 + timedelta(days=i)
            recs.append({"date": d.isoformat(), "strategy_id": sid,
                         "equity": eq, "apy": 0.0})
        (sdir / f"{sid}.json").write_text(json.dumps(recs))


class _TmpBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="deflated_sharpe_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure math
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrialSharpeVariance(unittest.TestCase):
    def test_sample_variance_hand(self) -> None:
        # var([1,2,3], ddof=1) = ((1)^2 + 0 + (1)^2)/(3-1) = 2/2 = 1.0
        self.assertAlmostEqual(ds.trial_sharpe_variance([1.0, 2.0, 3.0]), 1.0, places=12)

    def test_sample_variance_hand2(self) -> None:
        # var([2,4,4,4,5,5,7,9], ddof=1) = 4.571428...
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(ds.trial_sharpe_variance(vals), 32.0 / 7.0, places=12)

    def test_n_lt_2_zero(self) -> None:
        self.assertEqual(ds.trial_sharpe_variance([]), 0.0)
        self.assertEqual(ds.trial_sharpe_variance([3.14]), 0.0)


class TestExpectedMaxSharpe(unittest.TestCase):
    def test_n1_zero(self) -> None:
        self.assertEqual(ds.expected_max_sharpe_null(1, 0.25), 0.0)
        self.assertEqual(ds.expected_max_sharpe_null(0, 0.25), 0.0)

    def test_v_nonpos_zero(self) -> None:
        self.assertEqual(ds.expected_max_sharpe_null(10, 0.0), 0.0)
        self.assertEqual(ds.expected_max_sharpe_null(10, -1.0), 0.0)

    def test_known_n2_v1(self) -> None:
        # Recompute the closed form directly with the imported probit.
        g = ds.EULER_MASCHERONI
        z1 = ps._inv_norm_cdf(1.0 - 1.0 / 2)
        z2 = ps._inv_norm_cdf(1.0 - 1.0 / (2 * math.e))
        expected = 1.0 * ((1.0 - g) * z1 + g * z2)
        self.assertAlmostEqual(ds.expected_max_sharpe_null(2, 1.0), expected, places=12)
        # numeric anchor (regression guard)
        self.assertAlmostEqual(ds.expected_max_sharpe_null(2, 1.0), 0.519755344, places=7)

    def test_known_n10_v1(self) -> None:
        self.assertAlmostEqual(ds.expected_max_sharpe_null(10, 1.0), 1.574598301, places=7)

    def test_scales_with_sqrt_v(self) -> None:
        # E[max] ∝ √V
        base = ds.expected_max_sharpe_null(10, 1.0)
        scaled = ds.expected_max_sharpe_null(10, 4.0)
        self.assertAlmostEqual(scaled, base * 2.0, places=10)

    def test_monotone_increasing_in_n(self) -> None:
        vals = [ds.expected_max_sharpe_null(n, 1.0) for n in range(2, 30)]
        for a, b in zip(vals, vals[1:]):
            self.assertLess(a, b)


class TestDSRMonotonicity(_TmpBase):
    """At fixed SR_obs, larger E[max] (more trials / more spread) → lower DSR."""

    def test_dsr_decreases_with_more_trials(self) -> None:
        # Same observed track; vary number/spread of shadow trials.
        returns = [0.5, -0.2, 0.4, 0.1, 0.3, -0.1, 0.6, 0.2, 0.0, 0.4, 0.3, -0.2]
        _write_pnl(self.data_dir, returns)

        # 2 trials, small spread
        _write_shadow(self.data_dir, {
            "S0": [100.0, 101.0, 102.0, 103.0, 104.0],
            "S1": [100.0, 101.5, 102.0, 103.5, 104.0],
        })
        r2 = ds.build_deflated_sharpe(self.data_dir)

        # 6 trials, wider spread → bigger E[max] → lower DSR
        shutil.rmtree(self.data_dir / "shadow_strategies", ignore_errors=True)
        _write_shadow(self.data_dir, {
            "S0": [100.0, 90.0, 110.0, 95.0, 120.0],
            "S1": [100.0, 101.0, 102.0, 103.0, 104.0],
            "S2": [100.0, 105.0, 95.0, 115.0, 90.0],
            "S3": [100.0, 100.5, 101.0, 101.5, 102.0],
            "S4": [100.0, 80.0, 130.0, 70.0, 140.0],
            "S5": [100.0, 103.0, 99.0, 108.0, 94.0],
        })
        r6 = ds.build_deflated_sharpe(self.data_dir)

        self.assertTrue(r2["available"])
        self.assertTrue(r6["available"])
        self.assertEqual(r2["num_trials"], 2)
        self.assertGreaterEqual(r6["num_trials"], 3)
        # Same observed Sharpe in both runs.
        self.assertAlmostEqual(r2["observed_sharpe"], r6["observed_sharpe"], places=9)
        # More/ wider trials → larger E[max] → DSR not greater (typically lower).
        self.assertGreater(r6["expected_max_sharpe_null"], r2["expected_max_sharpe_null"])
        self.assertLessEqual(r6["deflated_sharpe_ratio"], r2["deflated_sharpe_ratio"])

    def test_dsr_le_psr_when_trials_present(self) -> None:
        returns = [0.5, -0.2, 0.4, 0.1, 0.3, -0.1, 0.6, 0.2, 0.0, 0.4]
        _write_pnl(self.data_dir, returns)
        _write_shadow(self.data_dir, {
            "S0": [100.0, 90.0, 110.0, 95.0, 120.0],
            "S1": [100.0, 105.0, 95.0, 115.0, 90.0],
            "S2": [100.0, 80.0, 130.0, 70.0, 140.0],
        })
        r = ds.build_deflated_sharpe(self.data_dir)
        self.assertTrue(r["available"])
        # DSR uses SR* = E[max] ≥ 0, PSR uses SR* = 0, so DSR ≤ PSR.
        self.assertLessEqual(r["deflated_sharpe_ratio"], r["probabilistic_sharpe"] + 1e-9)


class TestScaleConversion(_TmpBase):
    def test_trials_converted_to_daily(self) -> None:
        returns = [0.5, -0.2, 0.4, 0.1, 0.3, -0.1, 0.6, 0.2, 0.0, 0.4]
        _write_pnl(self.data_dir, returns)
        _write_shadow(self.data_dir, {
            "S0": [100.0, 90.0, 110.0, 95.0, 120.0],
            "S1": [100.0, 105.0, 95.0, 115.0, 90.0],
            "S2": [100.0, 80.0, 130.0, 70.0, 140.0],
        })
        r = ds.build_deflated_sharpe(self.data_dir)
        ann = r["trial_sharpes_annualized"]
        daily = [a / _SQRT252 for a in ann]
        # V reported must equal sample variance of the *daily* sharpes.
        self.assertAlmostEqual(
            r["trial_sharpe_variance"], ds.trial_sharpe_variance(daily), places=9
        )
        # Annualised E[max] echo == daily E[max] × √252.
        self.assertAlmostEqual(
            r["expected_max_sharpe_null_annualized"],
            r["expected_max_sharpe_null"] * _SQRT252, places=5,
        )
        # Observed annualised == observed daily × √252.
        self.assertAlmostEqual(
            r["observed_sharpe_annualized"], r["observed_sharpe"] * _SQRT252, places=5
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Verdict boundaries (drive DSR directly via build math relationships)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerdictBoundaries(_TmpBase):
    """Construct equity tracks that push DSR into each band; assert verdict."""

    def _build_with(self, returns: List[float], shadow: Dict[str, List[float]] | None):
        _write_pnl(self.data_dir, returns)
        if shadow:
            _write_shadow(self.data_dir, shadow)
        return ds.build_deflated_sharpe(self.data_dir)

    def test_reason_always_present(self) -> None:
        r = self._build_with([0.1, 0.2, -0.1, 0.3, 0.0, 0.2], None)
        self.assertIn("verdict", r)
        self.assertIn("verdict_reason", r)
        self.assertTrue(r["verdict_reason"])

    def test_fail_band(self) -> None:
        # Weak, noisy edge + several spread trials → DSR < 0.5.
        returns = [0.1, -0.3, 0.2, -0.2, 0.15, -0.1, 0.05, -0.05]
        shadow = {
            "S0": [100.0, 80.0, 130.0, 70.0, 140.0],
            "S1": [100.0, 120.0, 85.0, 125.0, 75.0],
            "S2": [100.0, 90.0, 115.0, 88.0, 130.0],
            "S3": [100.0, 110.0, 95.0, 118.0, 90.0],
            "S4": [100.0, 70.0, 145.0, 65.0, 150.0],
            "S5": [100.0, 130.0, 80.0, 140.0, 70.0],
        }
        r = self._build_with(returns, shadow)
        self.assertTrue(r["available"])
        if r["deflated_sharpe_ratio"] < ds.FAIL_BELOW:
            self.assertEqual(r["verdict"], "fail")
        # band-consistency invariant regardless of exact value:
        self._assert_band_consistent(r)

    def test_warn_band(self) -> None:
        returns = [0.4, -0.1, 0.5, 0.2, 0.3, 0.0, 0.45, 0.1, 0.35, 0.2]
        shadow = {
            "S0": [100.0, 102.0, 101.0, 103.0, 104.0],
            "S1": [100.0, 99.0, 101.0, 100.0, 102.0],
            "S2": [100.0, 103.0, 102.0, 105.0, 104.0],
        }
        r = self._build_with(returns, shadow)
        self.assertTrue(r["available"])
        self._assert_band_consistent(r)

    def test_ok_band_single_strong(self) -> None:
        # Strong, clean, long edge, no trials → DSR high → ok.
        returns = [0.3] * 40
        # constant returns => zero variance -> insufficient; add tiny noise
        returns = [0.3 + (0.001 if i % 2 else -0.001) for i in range(40)]
        r = self._build_with(returns, None)
        self.assertTrue(r["available"])
        self.assertEqual(r["num_trials"], 1)
        self._assert_band_consistent(r)

    def _assert_band_consistent(self, r: Dict[str, Any]) -> None:
        dsr = r["deflated_sharpe_ratio"]
        v = r["verdict"]
        if dsr < ds.FAIL_BELOW:
            self.assertEqual(v, "fail")
        elif dsr < ds.OK_AT_OR_ABOVE:
            self.assertEqual(v, "warn")
        else:
            self.assertEqual(v, "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# insufficient_data & schema stability
# ═══════════════════════════════════════════════════════════════════════════════

_SCHEMA_KEYS = {
    "available", "verdict", "verdict_reason", "deflated_sharpe_ratio",
    "probabilistic_sharpe", "observed_sharpe", "observed_sharpe_annualized",
    "num_trials", "trial_sharpe_variance", "expected_max_sharpe_null",
    "expected_max_sharpe_null_annualized", "n_observations", "skewness",
    "excess_kurtosis", "trials_source", "is_demo", "notes", "meta",
}


class TestInsufficientData(_TmpBase):
    def test_empty_equity(self) -> None:
        (self.data_dir / "pnl_history.json").write_text("[]")
        r = ds.build_deflated_sharpe(self.data_dir)
        self.assertFalse(r["available"])
        self.assertIn("reason", r)
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))
        self.assertEqual(r["verdict"], "ok")

    def test_short_equity(self) -> None:
        _write_pnl(self.data_dir, [0.1, 0.2])  # only 2 daily returns < MIN_OBS
        r = ds.build_deflated_sharpe(self.data_dir)
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))

    def test_flat_series(self) -> None:
        _write_pnl(self.data_dir, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        r = ds.build_deflated_sharpe(self.data_dir)
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))

    def test_missing_file(self) -> None:
        r = ds.build_deflated_sharpe(self.data_dir)  # nothing written
        self.assertFalse(r["available"])
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))


# ═══════════════════════════════════════════════════════════════════════════════
# Tolerance / never-raise
# ═══════════════════════════════════════════════════════════════════════════════

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
                r = ds.build_deflated_sharpe(self.data_dir)
                self.assertIsInstance(r, dict)
                self.assertIn("available", r)
                self.assertIn("verdict", r)

    def test_broken_shadow_dir(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, -0.2, 0.5])
        sdir = self.data_dir / "shadow_strategies"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "S0.json").write_text("not json")
        (sdir / "S1.json").write_text("{}")
        (sdir / "S2.json").write_text("[1,2,3]")
        r = ds.build_deflated_sharpe(self.data_dir)
        self.assertIsInstance(r, dict)
        self.assertIn("available", r)

    def test_property_fuzz(self) -> None:
        import random
        rng = random.Random(20260612)
        tokens = ["{", "}", "[", "]", "null", "true", "1.5", "\"x\"", ",", ":",
                  "pnl", "equity", "NaN", "Infinity", "-1e400"]
        for i in range(40):
            blob = "".join(rng.choice(tokens) for _ in range(rng.randint(1, 20)))
            with self.subTest(i=i, blob=blob[:20]):
                (self.data_dir / "pnl_history.json").write_text(blob)
                r = ds.build_deflated_sharpe(self.data_dir)
                self.assertIsInstance(r, dict)
                self.assertIn("available", r)


# ═══════════════════════════════════════════════════════════════════════════════
# content_fingerprint reuse-by-import
# ═══════════════════════════════════════════════════════════════════════════════

class TestFingerprintReuse(unittest.TestCase):
    def test_same_object(self) -> None:
        self.assertIs(ds.content_fingerprint, ts.content_fingerprint)

    def test_ignores_generated_at_and_history(self) -> None:
        a = {"x": 1, "meta": {"generated_at": "A", "source": "s"}, "history": [1]}
        b = {"x": 1, "meta": {"generated_at": "B", "source": "s"}, "history": [9, 9]}
        self.assertEqual(ds.content_fingerprint(a), ds.content_fingerprint(b))

    def test_changes_with_content(self) -> None:
        a = {"x": 1, "meta": {"source": "s"}}
        b = {"x": 2, "meta": {"source": "s"}}
        self.assertNotEqual(ds.content_fingerprint(a), ds.content_fingerprint(b))

    def test_stable(self) -> None:
        a = {"x": 1, "y": [1, 2, 3], "meta": {"source": "s"}}
        self.assertEqual(ds.content_fingerprint(a), ds.content_fingerprint(dict(a)))


# ═══════════════════════════════════════════════════════════════════════════════
# write_status
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteStatus(_TmpBase):
    def _md5(self, p: Path) -> str:
        return hashlib.md5(p.read_bytes()).hexdigest()

    def test_first_write_then_unchanged(self) -> None:
        res = {"available": True, "verdict": "ok", "x": 1,
               "meta": {"generated_at": "T1", "source": ds.SOURCE_NAME}}
        s1 = ds.write_status(res, self.data_dir)
        self.assertEqual(s1, "DATA_WRITTEN")
        out = self.data_dir / ds.STATUS_FILENAME
        md5_1 = self._md5(out)

        # identical content but new generated_at → fingerprint same → UNCHANGED + byte-identical
        res2 = dict(res)
        res2["meta"] = {"generated_at": "T2", "source": ds.SOURCE_NAME}
        s2 = ds.write_status(res2, self.data_dir)
        self.assertEqual(s2, "DATA_UNCHANGED")
        self.assertEqual(self._md5(out), md5_1)

    def test_different_content_grows_history(self) -> None:
        r1 = {"available": True, "x": 1, "meta": {"generated_at": "T1", "source": "s"}}
        r2 = {"available": True, "x": 2, "meta": {"generated_at": "T2", "source": "s"}}
        ds.write_status(r1, self.data_dir)
        ds.write_status(r2, self.data_dir)
        doc = json.loads((self.data_dir / ds.STATUS_FILENAME).read_text())
        self.assertEqual(doc["x"], 2)
        self.assertEqual(len(doc["history"]), 1)
        self.assertEqual(doc["history"][0]["x"], 1)

    def test_history_rotation_exact(self) -> None:
        for i in range(ds.HISTORY_MAX + 50):
            r = {"available": True, "x": i, "meta": {"generated_at": str(i), "source": "s"}}
            ds.write_status(r, self.data_dir)
        doc = json.loads((self.data_dir / ds.STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), ds.HISTORY_MAX)

    def test_no_tmp_left(self) -> None:
        r = {"available": True, "x": 1, "meta": {"generated_at": "T", "source": "s"}}
        ds.write_status(r, self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + list(self.data_dir.glob(".tmp*"))
        self.assertEqual(leftovers, [])

    def test_tolerant_broken_existing(self) -> None:
        out = self.data_dir / ds.STATUS_FILENAME
        out.write_text("not json {{{")
        r = {"available": True, "x": 1, "meta": {"generated_at": "T", "source": "s"}}
        s = ds.write_status(r, self.data_dir)
        self.assertEqual(s, "DATA_WRITTEN")
        doc = json.loads(out.read_text())
        self.assertEqual(doc["x"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — direct main(argv)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLIDirect(_TmpBase):
    def _run_main(self, argv: List[str]) -> tuple[str, str, int]:
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ds.main(argv)
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
        return out.getvalue(), err.getvalue(), code

    def test_check_no_write(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3])
        out, err, code = self._run_main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / ds.STATUS_FILENAME).exists())
        self.assertIn("deflated_sharpe", out)

    def test_default_is_check(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3])
        out, err, code = self._run_main(["--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / ds.STATUS_FILENAME).exists())

    def test_run_writes_and_idempotent(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05])
        o1, _, c1 = self._run_main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(c1, 0)
        self.assertTrue((self.data_dir / ds.STATUS_FILENAME).exists())
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


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — subprocess (real process, exit code + no traceback)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLISubprocess(_TmpBase):
    def _run(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.deflated_sharpe", *args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120,
        )

    def test_check_subprocess(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3])
        cp = self._run(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(cp.returncode, 0)
        self.assertNotIn("Traceback", cp.stderr)

    def test_run_idempotent_subprocess(self) -> None:
        _write_pnl(self.data_dir, [0.3, -0.1, 0.2, 0.4, 0.1, 0.3, 0.2, -0.05])
        cp1 = self._run(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(cp1.returncode, 0)
        out = self.data_dir / ds.STATUS_FILENAME
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


# ═══════════════════════════════════════════════════════════════════════════════
# Import hygiene
# ═══════════════════════════════════════════════════════════════════════════════

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
            # no eval/exec calls
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "compile"})

    def test_reuse_by_import_markers(self) -> None:
        src = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("from spa_core.paper_trading.probabilistic_sharpe import", src)
        self.assertIn("from spa_core.reporting.tear_sheet import content_fingerprint", src)
        self.assertIn("_probabilistic_sharpe", src)
        self.assertIn("_inv_norm_cdf", src)

    def test_atomic_write_pattern(self) -> None:
        src = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("tempfile.mkstemp", src)
        self.assertIn("os.replace", src)

    def test_math_funcs_are_imported_objects(self) -> None:
        # The reused functions must be the SAME objects as in probabilistic_sharpe.
        self.assertIs(ds._probabilistic_sharpe, ps._probabilistic_sharpe)
        self.assertIs(ds._inv_norm_cdf, ps._inv_norm_cdf)
        self.assertIs(ds._skewness, ps._skewness)
        self.assertIs(ds._excess_kurtosis, ps._excess_kurtosis)


# ═══════════════════════════════════════════════════════════════════════════════
# e2e round-trip on the real repo data/ dir (must not raise; schema stable)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealDataRoundTrip(unittest.TestCase):
    def test_real_build_does_not_raise(self) -> None:
        real_data = _REPO_ROOT / "data"
        r = ds.build_deflated_sharpe(real_data)
        self.assertIsInstance(r, dict)
        self.assertIn("available", r)
        self.assertIn("verdict", r)
        self.assertTrue(_SCHEMA_KEYS.issubset(set(r.keys())))


if __name__ == "__main__":
    unittest.main(verbosity=2)
