#!/usr/bin/env python3
"""Tests for the K-Ratio (Kestner) Analyzer (SPA-V482 / MP-513).

Covers: pure OLS math with a fully hand-computed numeric case, cumulative
log returns, slope standard error, the Kestner K-Ratio, the equity bundle,
edge cases (perfectly linear, insufficient data, negative/non-finite inputs),
the build verdict logic, atomic idempotent write_status, the CLI (always exit
0), import hygiene and reuse-by-import identity.
"""
from __future__ import annotations

import ast
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spa_core.analytics_lab import k_ratio as kr
from spa_core.analytics_lab.k_ratio import (
    build_k_ratio,
    cumulative_log_returns,
    k_ratio,
    k_ratio_from_equity,
    main,
    ols_slope_intercept,
    slope_std_error,
    write_status,
    K_FAIL,
    K_WARN,
    MIN_OBS,
)

_MODULE_PATH = Path(kr.__file__)


# Hand-computed reference (see module docstring):
#   xs=[1,2,3,4,5], ys=[1,2,3,4,6] ->
#   slope=1.2, intercept=-0.4, SSE=0.4, s=sqrt(0.4/3),
#   se_b=0.115470, t=10.392305, K=2.078461
_HX = [1, 2, 3, 4, 5]
_HY = [1, 2, 3, 4, 6]


# ------------------------------------------------------------------------------
# cumulative_log_returns
# ------------------------------------------------------------------------------
class TestCumulativeLogReturns(unittest.TestCase):
    def test_basic(self):
        out = cumulative_log_returns([100, 110, 121])
        self.assertEqual(len(out), 3)
        self.assertAlmostEqual(out[0], 0.0, places=12)
        self.assertAlmostEqual(out[1], math.log(1.1), places=12)
        self.assertAlmostEqual(out[2], math.log(1.21), places=12)

    def test_first_element_zero(self):
        self.assertEqual(cumulative_log_returns([50, 60, 70])[0], 0.0)

    def test_flat_series_all_zero(self):
        out = cumulative_log_returns([100, 100, 100])
        self.assertTrue(all(abs(v) < 1e-12 for v in out))

    def test_decreasing_negative(self):
        out = cumulative_log_returns([100, 90, 80])
        self.assertLess(out[1], 0)
        self.assertLess(out[2], out[1])

    def test_empty(self):
        self.assertEqual(cumulative_log_returns([]), [])

    def test_not_a_list(self):
        self.assertEqual(cumulative_log_returns("nope"), [])  # type: ignore[arg-type]

    def test_first_non_positive(self):
        self.assertEqual(cumulative_log_returns([0, 10, 20]), [])
        self.assertEqual(cumulative_log_returns([-5, 10, 20]), [])

    def test_first_non_finite(self):
        self.assertEqual(cumulative_log_returns([float("nan"), 1, 2]), [])
        self.assertEqual(cumulative_log_returns([float("inf"), 1, 2]), [])

    def test_first_bool_rejected(self):
        self.assertEqual(cumulative_log_returns([True, 1.0, 2.0]), [])

    def test_later_non_positive_dropped(self):
        out = cumulative_log_returns([100, -5, 121])
        self.assertEqual(len(out), 2)  # the -5 dropped
        self.assertAlmostEqual(out[1], math.log(1.21), places=12)

    def test_later_non_finite_dropped(self):
        out = cumulative_log_returns([100, float("nan"), 121])
        self.assertEqual(len(out), 2)

    def test_single_element(self):
        self.assertEqual(cumulative_log_returns([100]), [0.0])


# ------------------------------------------------------------------------------
# ols_slope_intercept — hand-verified
# ------------------------------------------------------------------------------
class TestOLS(unittest.TestCase):
    def test_hand_example(self):
        fit = ols_slope_intercept(_HX, _HY)
        self.assertIsNotNone(fit)
        slope, intercept = fit  # type: ignore[misc]
        self.assertAlmostEqual(slope, 1.2, places=9)
        self.assertAlmostEqual(intercept, -0.4, places=9)

    def test_perfect_line(self):
        fit = ols_slope_intercept([1, 2, 3, 4], [2, 4, 6, 8])
        slope, intercept = fit  # type: ignore[misc]
        self.assertAlmostEqual(slope, 2.0, places=12)
        self.assertAlmostEqual(intercept, 0.0, places=12)

    def test_negative_slope(self):
        fit = ols_slope_intercept([1, 2, 3], [9, 6, 3])
        slope, _ = fit  # type: ignore[misc]
        self.assertAlmostEqual(slope, -3.0, places=12)

    def test_flat_zero_slope(self):
        fit = ols_slope_intercept([1, 2, 3, 4], [5, 5, 5, 5])
        slope, intercept = fit  # type: ignore[misc]
        self.assertAlmostEqual(slope, 0.0, places=12)
        self.assertAlmostEqual(intercept, 5.0, places=12)

    def test_empty(self):
        self.assertIsNone(ols_slope_intercept([], []))

    def test_length_mismatch(self):
        self.assertIsNone(ols_slope_intercept([1, 2, 3], [1, 2]))

    def test_too_short(self):
        self.assertIsNone(ols_slope_intercept([1], [1]))

    def test_zero_x_variance(self):
        self.assertIsNone(ols_slope_intercept([3, 3, 3], [1, 2, 3]))

    def test_non_finite_input(self):
        self.assertIsNone(ols_slope_intercept([1, 2, 3], [1, float("nan"), 3]))
        self.assertIsNone(ols_slope_intercept([1, float("inf"), 3], [1, 2, 3]))

    def test_bool_rejected(self):
        self.assertIsNone(ols_slope_intercept([1, 2, 3], [True, 2, 3]))


# ------------------------------------------------------------------------------
# slope_std_error — hand-verified
# ------------------------------------------------------------------------------
class TestSlopeStdError(unittest.TestCase):
    def test_hand_example(self):
        se = slope_std_error(_HX, _HY)
        self.assertIsNotNone(se)
        self.assertAlmostEqual(se, 0.115470, places=6)  # type: ignore[arg-type]

    def test_perfect_line_zero(self):
        se = slope_std_error([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        self.assertIsNotNone(se)
        self.assertAlmostEqual(se, 0.0, places=12)  # type: ignore[arg-type]

    def test_too_short_none(self):
        # n=2 -> n-2=0 -> undefined
        self.assertIsNone(slope_std_error([1, 2], [1, 2]))

    def test_n3_defined(self):
        se = slope_std_error([1, 2, 3], [1, 2, 4])
        self.assertIsNotNone(se)
        self.assertGreaterEqual(se, 0.0)  # type: ignore[arg-type]

    def test_zero_x_variance_none(self):
        self.assertIsNone(slope_std_error([2, 2, 2, 2], [1, 2, 3, 4]))

    def test_empty_none(self):
        self.assertIsNone(slope_std_error([], []))

    def test_non_finite_none(self):
        self.assertIsNone(slope_std_error([1, 2, 3], [1, 2, float("inf")]))


# ------------------------------------------------------------------------------
# k_ratio — hand-verified
# ------------------------------------------------------------------------------
class TestKRatio(unittest.TestCase):
    def test_hand_example(self):
        k = k_ratio(1.2, 0.115470, 5)
        self.assertIsNotNone(k)
        self.assertAlmostEqual(k, 2.078461, places=5)  # type: ignore[arg-type]

    def test_slope_none(self):
        self.assertIsNone(k_ratio(None, 0.1, 5))

    def test_se_none(self):
        self.assertIsNone(k_ratio(1.2, None, 5))

    def test_se_zero(self):
        self.assertIsNone(k_ratio(1.2, 0.0, 5))

    def test_se_negative(self):
        self.assertIsNone(k_ratio(1.2, -0.1, 5))

    def test_n_zero(self):
        self.assertIsNone(k_ratio(1.2, 0.1, 0))

    def test_n_negative(self):
        self.assertIsNone(k_ratio(1.2, 0.1, -3))

    def test_negative_slope_negative_k(self):
        k = k_ratio(-1.2, 0.115470, 5)
        self.assertIsNotNone(k)
        self.assertLess(k, 0)  # type: ignore[arg-type]

    def test_higher_n_lowers_magnitude(self):
        a = k_ratio(1.2, 0.1, 5)
        b = k_ratio(1.2, 0.1, 50)
        self.assertGreater(abs(a), abs(b))  # type: ignore[arg-type]


# ------------------------------------------------------------------------------
# k_ratio_from_equity
# ------------------------------------------------------------------------------
def _series(levels, start="2026-01-01"):
    """Build a (date, level) series with sequential ISO dates."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), float(lv))
            for i, lv in enumerate(levels)]


class TestKRatioFromEquity(unittest.TestCase):
    def test_steady_growth_bundle(self):
        # ~1% daily compounding, slightly noisy
        levels = [100 * (1.01 ** i) * (1 + (0.0005 if i % 2 else -0.0005))
                  for i in range(20)]
        b = k_ratio_from_equity(_series(levels))
        self.assertEqual(b["n"], 20)
        self.assertIsNotNone(b["slope"])
        self.assertIsNotNone(b["k_ratio"])
        self.assertGreater(b["slope"], 0)
        self.assertGreater(b["k_ratio"], 0)

    def test_near_linear_log_equity_huge_k(self):
        # Near-exact constant compounding -> log curve is almost a straight
        # line -> tiny residual std error -> very large positive K-Ratio.
        # (Float ``ln`` never yields a bit-exact zero residual, so the
        # se==0 / k=None guard is exercised by the pure-function tests below;
        # here we assert the realistic near-linear behaviour.)
        levels = [100 * (1.01 ** i) for i in range(15)]
        b = k_ratio_from_equity(_series(levels))
        self.assertIsNotNone(b["slope_std_error"])
        self.assertGreater(b["slope_std_error"], 0.0)
        self.assertIsNotNone(b["k_ratio"])
        self.assertGreater(b["k_ratio"], 100.0)
        self.assertIsNotNone(b["t_stat"])

    def test_declining_negative_k(self):
        levels = [100 * (0.99 ** i) * (1 + (0.0005 if i % 2 else -0.0005))
                  for i in range(20)]
        b = k_ratio_from_equity(_series(levels))
        self.assertLess(b["slope"], 0)
        self.assertLess(b["k_ratio"], 0)

    def test_empty_series(self):
        b = k_ratio_from_equity([])
        self.assertEqual(b["n"], 0)
        self.assertIsNone(b["k_ratio"])

    def test_not_a_list(self):
        b = k_ratio_from_equity("nope")  # type: ignore[arg-type]
        self.assertIsNone(b["k_ratio"])

    def test_single_point(self):
        b = k_ratio_from_equity(_series([100]))
        self.assertIsNone(b["k_ratio"])

    def test_two_points_n2(self):
        # n=2 -> regression slope defined, se undefined -> k None
        b = k_ratio_from_equity(_series([100, 110]))
        self.assertIsNone(b["k_ratio"])

    def test_bundle_keys_stable(self):
        b = k_ratio_from_equity(_series([100, 101, 102]))
        for key in ("slope", "intercept", "slope_std_error", "t_stat",
                    "k_ratio", "n", "perfectly_linear"):
            self.assertIn(key, b)

    def test_t_stat_equals_k_times_n(self):
        levels = [100 * (1.01 ** i) + (i % 3) for i in range(18)]
        b = k_ratio_from_equity(_series(levels))
        if b["k_ratio"] is not None and b["t_stat"] is not None:
            self.assertAlmostEqual(b["t_stat"], b["k_ratio"] * b["n"], places=6)


# ------------------------------------------------------------------------------
# build_k_ratio — verdict logic via data-dir fixtures
# ------------------------------------------------------------------------------
def _write_equity(data_dir: Path, levels, start="2026-01-01", is_demo=False):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    daily = []
    for i, lv in enumerate(levels):
        daily.append({
            "date": (d0 + timedelta(days=i)).isoformat(),
            "close_equity": float(lv),
            "equity": float(lv),
        })
    doc = {"is_demo": is_demo, "daily": daily}
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


class TestBuild(unittest.TestCase):
    def _tmp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_unavailable_when_no_file(self):
        d = self._tmp()
        r = build_k_ratio(d)
        self.assertFalse(r["available"])
        self.assertEqual(r["verdict"], "ok")

    def test_unavailable_below_min_obs(self):
        d = self._tmp()
        _write_equity(d, [100, 101, 102])  # 3 < MIN_OBS
        r = build_k_ratio(d)
        self.assertFalse(r["available"])
        self.assertEqual(r["n_observations"], 3)
        self.assertEqual(r["verdict"], "ok")

    def test_available_steady_growth_ok(self):
        d = self._tmp()
        levels = [100 * (1.01 ** i) * (1 + (0.0005 if i % 2 else -0.0005))
                  for i in range(20)]
        _write_equity(d, levels)
        r = build_k_ratio(d)
        self.assertTrue(r["available"])
        self.assertIsNotNone(r["k_ratio"])
        self.assertGreater(r["k_ratio"], K_WARN)
        self.assertEqual(r["verdict"], "ok")

    def test_available_near_linear_high_k_ok(self):
        d = self._tmp()
        levels = [100 * (1.01 ** i) for i in range(15)]
        _write_equity(d, levels)
        r = build_k_ratio(d)
        self.assertTrue(r["available"])
        self.assertFalse(r["perfectly_linear"])  # float ln -> not bit-exact
        self.assertIsNotNone(r["k_ratio"])
        self.assertGreater(r["k_ratio"], 100.0)
        self.assertEqual(r["verdict"], "ok")

    def test_available_decline_fail(self):
        d = self._tmp()
        levels = [100 * (0.99 ** i) * (1 + (0.0005 if i % 2 else -0.0005))
                  for i in range(20)]
        _write_equity(d, levels)
        r = build_k_ratio(d)
        self.assertTrue(r["available"])
        self.assertLess(r["k_ratio"], K_FAIL)
        self.assertEqual(r["verdict"], "fail")

    def test_is_demo_propagated(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)], is_demo=True)
        r = build_k_ratio(d)
        self.assertEqual(r["is_demo"], True)

    def test_schema_stable_available(self):
        d = self._tmp()
        _write_equity(d, [100 * (1.005 ** i) + (i % 4) for i in range(15)])
        r = build_k_ratio(d)
        for key in ("available", "k_ratio", "regression_slope",
                    "slope_std_error", "t_stat", "intercept",
                    "perfectly_linear", "n_observations", "start_date",
                    "end_date", "verdict", "verdict_reason", "notes", "meta"):
            self.assertIn(key, r)

    def test_verdict_reason_always_present(self):
        d = self._tmp()
        _write_equity(d, [100, 101])
        r = build_k_ratio(d)
        self.assertIn("verdict_reason", r)
        self.assertTrue(r["verdict_reason"])

    def test_never_raises_on_garbage(self):
        d = self._tmp()
        (d / "equity_curve_daily.json").write_text("{ not json",
                                                   encoding="utf-8")
        r = build_k_ratio(d)
        self.assertFalse(r["available"])

    def test_start_end_dates(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)], start="2026-03-01")
        r = build_k_ratio(d)
        self.assertEqual(r["start_date"], "2026-03-01")
        self.assertTrue(r["end_date"] >= r["start_date"])


# ------------------------------------------------------------------------------
# write_status — atomic / idempotent
# ------------------------------------------------------------------------------
class TestWriteStatus(unittest.TestCase):
    def _tmp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_written_then_unchanged(self):
        d = self._tmp()
        _write_equity(d, [100 * (1.005 ** i) + (i % 3) for i in range(15)])
        r = build_k_ratio(d)
        self.assertEqual(write_status(r, d), "DATA_WRITTEN")
        r2 = build_k_ratio(d)  # fresh generated_at, same content
        self.assertEqual(write_status(r2, d), "DATA_UNCHANGED")

    def test_output_file_created(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        r = build_k_ratio(d)
        write_status(r, d)
        self.assertTrue((d / "k_ratio.json").exists())

    def test_no_tmp_left_behind(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        r = build_k_ratio(d)
        write_status(r, d)
        leftovers = list(d.glob(".tmp_k_ratio_*"))
        self.assertEqual(leftovers, [])

    def test_history_grows_on_change(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        write_status(build_k_ratio(d), d)
        # change the underlying data -> new content -> history gets prior entry
        _write_equity(d, [100 * (1.01 ** i) + (i % 2) for i in range(14)])
        write_status(build_k_ratio(d), d)
        doc = json.loads((d / "k_ratio.json").read_text(encoding="utf-8"))
        self.assertIn("history", doc)
        self.assertGreaterEqual(len(doc["history"]), 1)

    def test_fingerprint_present(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        write_status(build_k_ratio(d), d)
        doc = json.loads((d / "k_ratio.json").read_text(encoding="utf-8"))
        self.assertIn("_fingerprint", doc)

    def test_tolerates_broken_existing(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        (d / "k_ratio.json").write_text("garbage", encoding="utf-8")
        self.assertEqual(write_status(build_k_ratio(d), d), "DATA_WRITTEN")


# ------------------------------------------------------------------------------
# CLI — always exit 0
# ------------------------------------------------------------------------------
class TestCLI(unittest.TestCase):
    def _tmp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_check_default_exit0(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--data-dir", str(d)])
        self.assertEqual(rc, 0)
        self.assertNotIn("k_ratio.json", os.listdir(d))  # --check does not write

    def test_run_writes_exit0(self):
        d = self._tmp()
        _write_equity(d, [100 * (1.005 ** i) + (i % 3) for i in range(14)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--run", "--data-dir", str(d)])
        self.assertEqual(rc, 0)
        self.assertTrue((d / "k_ratio.json").exists())

    def test_run_twice_unchanged(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(13)])
        with redirect_stdout(io.StringIO()):
            main(["--run", "--data-dir", str(d)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--run", "--data-dir", str(d)])
        self.assertEqual(rc, 0)
        self.assertIn("DATA_UNCHANGED", buf.getvalue())

    def test_check_and_run_conflict_exit0(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--check", "--run"])
        self.assertEqual(rc, 0)

    def test_unknown_args_exit0(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--bogus"])
        self.assertEqual(rc, 0)

    def test_no_tmp_after_run(self):
        d = self._tmp()
        _write_equity(d, [100 + i for i in range(12)])
        with redirect_stdout(io.StringIO()):
            main(["--run", "--data-dir", str(d)])
        self.assertEqual(list(d.glob(".tmp_k_ratio_*")), [])


# ------------------------------------------------------------------------------
# Import hygiene (AST) + reuse-by-import identity
# ------------------------------------------------------------------------------
class TestImportHygiene(unittest.TestCase):
    FORBIDDEN = {
        "numpy", "pandas", "scipy", "requests", "web3", "aiohttp", "httpx",
        "socket", "subprocess", "openai", "anthropic",
    }

    def test_no_forbidden_imports(self):
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.add(node.module.split(".")[0])
        self.assertEqual(found & self.FORBIDDEN, set())

    def test_no_eval_exec_calls(self):
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "compile"})

    def test_does_not_import_forbidden_domains(self):
        # AST-level: the module must not IMPORT risk / execution / monitoring /
        # allocator / cycle_runner / golive_checker (prose mentions in the
        # docstring are fine and expected).
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    modules.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        bad_tokens = ("risk", "execution", "monitoring", "allocator",
                      "cycle_runner", "golive_checker")
        for m in modules:
            for bad in bad_tokens:
                self.assertNotIn(bad, m, f"forbidden import: {m}")

    def test_content_fingerprint_reused_by_import(self):
        from spa_core.reporting.tear_sheet import (
            content_fingerprint as canonical,
        )
        self.assertIs(kr.content_fingerprint, canonical)

    def test_extract_equity_series_reused_by_import(self):
        from spa_core.paper_trading.drawdown_analytics import (
            extract_equity_series as canonical,
        )
        self.assertIs(kr.extract_equity_series, canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
