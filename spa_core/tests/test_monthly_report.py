#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.monthly_report (SPA / MP-134).

Coverage:
  * load_report_data — missing files, equity fallback, all optional keys
  * compute_month_metrics — filtering, return calculation, max drawdown,
      Sharpe sign, empty month, single bar, multiple months
  * _compute_sharpe / _compute_sortino — edge cases
  * generate_executive_summary — positive / negative / zero return branches,
      Sharpe tiers, drawdown sentences, empty metrics
  * generate_markdown_report — all 7 sections present, no-data safe path,
      prev-month comparison, no external imports (AST lint)
  * _performance_table / _risk_table / _protocol_breakdown / _key_events /
      _outlook_section — section-level behaviour
  * save_report — file created, correct content, atomic (no .tmp leftover)
  * CLI (main) — --check prints report, --run writes file, bad args exit 0

All tests are offline and use tempdir fixtures — no network, no real data files.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Optional

# Ensure the repo root is importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading import monthly_report as mr

# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_bar(
    date: str,
    close: float,
    daily_ret_pct: float = 0.0,
    positions: Optional[dict] = None,
) -> dict:
    return {
        "date": date,
        "close_equity": close,
        "equity": close,
        "daily_return_pct": daily_ret_pct,
        "positions": positions or {},
    }


def _equity_doc(bars: List[dict]) -> dict:
    return {"daily": bars, "is_demo": False, "source": "test"}


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


class _TmpDir(unittest.TestCase):
    """Base class that provides a fresh temp directory for each test."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="mr_test_")
        self.data_dir = self._tmp

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── load_report_data ─────────────────────────────────────────────────────────

class TestLoadReportData(_TmpDir):

    def test_empty_dir_returns_empty_snapshots(self):
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["month"], "2026-06")

    def test_equity_curve_used_as_fallback(self):
        bars = [_make_bar("2026-06-10", 100000)]
        _write_json(Path(self.data_dir) / "equity_curve_daily.json", _equity_doc(bars))
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertEqual(len(data["snapshots"]), 1)
        self.assertEqual(data["snapshots"][0]["date"], "2026-06-10")

    def test_portfolio_snapshots_preferred_over_equity_curve(self):
        # portfolio_snapshots has 2 entries; equity_curve has 5 → prefer snapshots
        snap_doc = {"snapshots": [_make_bar("2026-06-10", 100000), _make_bar("2026-06-11", 100010)]}
        bars5 = [_make_bar(f"2026-06-{10+i:02d}", 100000 + i * 10) for i in range(5)]
        _write_json(Path(self.data_dir) / "portfolio_snapshots.json", snap_doc)
        _write_json(Path(self.data_dir) / "equity_curve_daily.json", _equity_doc(bars5))
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertEqual(len(data["snapshots"]), 2)

    def test_adapter_status_loaded(self):
        _write_json(Path(self.data_dir) / "adapter_status.json", {"adapters": []})
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertIn("adapter_status", data)

    def test_yield_attribution_loaded(self):
        _write_json(Path(self.data_dir) / "yield_attribution.json", {"breakdown": []})
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertIn("yield_attribution", data)

    def test_missing_optional_files_not_in_result(self):
        data = mr.load_report_data("2026-06", self.data_dir)
        self.assertNotIn("yield_attribution", data)
        self.assertNotIn("adapter_status", data)
        self.assertNotIn("performance_report", data)

    def test_corrupt_json_handled_gracefully(self):
        p = Path(self.data_dir) / "adapter_status.json"
        p.write_text("{not valid json", encoding="utf-8")
        data = mr.load_report_data("2026-06", self.data_dir)
        # Should not raise; adapter_status simply absent
        self.assertNotIn("adapter_status", data)

    def test_returns_month_and_data_dir(self):
        data = mr.load_report_data("2026-07", self.data_dir)
        self.assertEqual(data["month"], "2026-07")
        self.assertEqual(data["data_dir"], self.data_dir)


# ─── compute_month_metrics ────────────────────────────────────────────────────

class TestComputeMonthMetrics(unittest.TestCase):

    def _bars(self) -> List[dict]:
        return [
            _make_bar("2026-06-10", 100_000.0, 0.0),
            _make_bar("2026-06-11", 100_100.0, 0.1),
            _make_bar("2026-06-12", 100_200.0, 0.0999),
        ]

    def test_empty_snapshots_returns_empty(self):
        self.assertEqual(mr.compute_month_metrics([], "2026-06"), {})

    def test_empty_month_returns_empty(self):
        self.assertEqual(mr.compute_month_metrics(self._bars(), ""), {})

    def test_no_bars_for_month_returns_empty(self):
        self.assertEqual(mr.compute_month_metrics(self._bars(), "2026-07"), {})

    def test_correct_month_filtering(self):
        bars = [
            _make_bar("2026-05-31", 99_000.0, 0.0),
            _make_bar("2026-06-01", 100_000.0, 0.0),
            _make_bar("2026-07-01", 101_000.0, 0.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertEqual(m["trading_days"], 1)
        self.assertAlmostEqual(m["start_equity"], 100_000.0)

    def test_start_end_equity(self):
        m = mr.compute_month_metrics(self._bars(), "2026-06")
        self.assertAlmostEqual(m["start_equity"], 100_000.0)
        self.assertAlmostEqual(m["end_equity"], 100_200.0)

    def test_total_return_pct_positive(self):
        m = mr.compute_month_metrics(self._bars(), "2026-06")
        expected = (100_200 / 100_000 - 1) * 100
        self.assertAlmostEqual(m["total_return_pct"], expected, places=4)

    def test_total_return_pct_negative(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 99_000.0, -1.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertLess(m["total_return_pct"], 0)

    def test_trading_days_count(self):
        m = mr.compute_month_metrics(self._bars(), "2026-06")
        self.assertEqual(m["trading_days"], 3)

    def test_max_drawdown_zero_on_monotone_rise(self):
        m = mr.compute_month_metrics(self._bars(), "2026-06")
        self.assertEqual(m["max_drawdown_pct"], 0.0)

    def test_max_drawdown_detected(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 105_000.0),
            _make_bar("2026-06-03",  95_000.0),  # 9.5 % drawdown from peak
            _make_bar("2026-06-04", 100_000.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertLess(m["max_drawdown_pct"], 0)
        self.assertAlmostEqual(m["max_drawdown_pct"], (95_000 / 105_000 - 1) * 100, places=3)

    def test_daily_returns_length(self):
        m = mr.compute_month_metrics(self._bars(), "2026-06")
        # n bars → n-1 returns
        self.assertEqual(len(m["daily_returns"]), 2)

    def test_single_bar_returns_empty_daily_returns(self):
        bars = [_make_bar("2026-06-01", 100_000.0)]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertEqual(m["daily_returns"], [])

    def test_sharpe_sign_positive_returns(self):
        # Large positive returns → positive Sharpe
        bars = [_make_bar(f"2026-06-{i+1:02d}", 100_000 + i * 500, 0.5) for i in range(20)]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertGreater(m["sharpe"], 0)

    def test_sharpe_zero_with_one_return(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 100_050.0, 0.05),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        # Only 1 return → sharpe = 0
        self.assertEqual(m["sharpe"], 0.0)

    def test_best_day_is_max_return(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 100_100.0, 0.1),
            _make_bar("2026-06-03", 100_050.0, -0.05),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertGreater(m["best_day"], m["worst_day"])

    def test_worst_day_is_min_return(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 99_000.0, -1.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertLess(m["worst_day"], 0)

    def test_nondict_bars_skipped(self):
        snapshots = ["garbage", None, 42, _make_bar("2026-06-01", 100_000.0)]
        m = mr.compute_month_metrics(snapshots, "2026-06")
        self.assertEqual(m["trading_days"], 1)

    def test_bars_sorted_chronologically(self):
        # Provide bars out of order
        bars = [
            _make_bar("2026-06-03", 100_200.0),
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 100_100.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        self.assertAlmostEqual(m["start_equity"], 100_000.0)
        self.assertAlmostEqual(m["end_equity"], 100_200.0)


# ─── _compute_sharpe / _compute_sortino ──────────────────────────────────────

class TestRatioHelpers(unittest.TestCase):

    def test_sharpe_positive_for_good_returns(self):
        rets = [0.05] * 30  # 0.05% daily, well above rf
        self.assertGreater(mr._compute_sharpe(rets), 0)

    def test_sharpe_zero_with_insufficient_data(self):
        self.assertEqual(mr._compute_sharpe([]), 0.0)
        self.assertEqual(mr._compute_sharpe([0.1]), 0.0)

    def test_sharpe_negative_for_negative_returns(self):
        # Alternating negative returns with some variance so std > 0
        rets = [-0.05 + (i % 3) * 0.01 for i in range(30)]  # [-0.05, -0.04, -0.03, ...]
        self.assertLess(mr._compute_sharpe(rets), 0)

    def test_sortino_caps_at_ten_all_positive(self):
        rets = [0.1] * 20  # all above hurdle
        self.assertEqual(mr._compute_sortino(rets), 10.0)

    def test_sortino_zero_insufficient_data(self):
        self.assertEqual(mr._compute_sortino([0.1]), 0.0)


# ─── generate_executive_summary ──────────────────────────────────────────────

class TestGenerateExecutiveSummary(unittest.TestCase):

    def _pos_metrics(self) -> dict:
        bars = [_make_bar(f"2026-06-{i+1:02d}", 100_000 + i * 50, 0.05) for i in range(30)]
        return mr.compute_month_metrics(bars, "2026-06")

    def test_positive_return_mentions_outperforming(self):
        m = self._pos_metrics()
        summary = mr.generate_executive_summary(m, "2026-06")
        self.assertIn("outperforming", summary.lower())

    def test_negative_return_mentions_drawdown_or_underperforming(self):
        bars = [
            _make_bar("2026-06-01", 100_000.0),
            _make_bar("2026-06-02", 98_000.0, -2.0),
        ]
        m = mr.compute_month_metrics(bars, "2026-06")
        summary = mr.generate_executive_summary(m, "2026-06")
        # Should mention underperforming or drawdown
        lower = summary.lower()
        self.assertTrue(
            "underperforming" in lower or "drawdown" in lower or "loss" in lower,
            msg=f"Expected negative framing in: {summary}",
        )

    def test_empty_metrics_safe_fallback(self):
        summary = mr.generate_executive_summary({}, "2026-06")
        self.assertIn("2026", summary)
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    def test_month_label_in_summary(self):
        m = self._pos_metrics()
        summary = mr.generate_executive_summary(m, "2026-06")
        self.assertIn("June", summary)
        self.assertIn("2026", summary)

    def test_sharpe_high_tier_exceptional(self):
        # Force high Sharpe by giving uniform large returns
        bars = [_make_bar(f"2026-06-{i+1:02d}", 100_000 + i * 200, 0.2) for i in range(30)]
        m = mr.compute_month_metrics(bars, "2026-06")
        if m.get("sharpe", 0) >= 2.0:
            summary = mr.generate_executive_summary(m, "2026-06")
            self.assertIn("exceptional", summary.lower())

    def test_no_drawdown_sentence(self):
        bars = [_make_bar(f"2026-06-{i+1:02d}", 100_000 + i * 10, 0.01) for i in range(10)]
        m = mr.compute_month_metrics(bars, "2026-06")
        summary = mr.generate_executive_summary(m, "2026-06")
        self.assertIn("no drawdown", summary.lower())

    def test_returns_string(self):
        summary = mr.generate_executive_summary({}, "2026-06")
        self.assertIsInstance(summary, str)


# ─── generate_markdown_report ────────────────────────────────────────────────

class TestGenerateMarkdownReport(_TmpDir):

    def _write_equity(self, bars: List[dict]) -> None:
        _write_json(
            Path(self.data_dir) / "equity_curve_daily.json",
            _equity_doc(bars),
        )

    def _default_bars(self) -> List[dict]:
        return [_make_bar(f"2026-06-{i+10:02d}", 100_000 + i * 50, 0.05) for i in range(5)]

    def test_contains_title(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("# SPA Monthly Report", report)
        self.assertIn("June 2026", report)

    def test_contains_executive_summary_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Executive Summary", report)

    def test_contains_performance_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Performance", report)

    def test_contains_risk_metrics_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Risk Metrics", report)

    def test_contains_protocol_breakdown_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Protocol Breakdown", report)

    def test_contains_key_events_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Key Events", report)

    def test_contains_outlook_section(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("## Outlook", report)

    def test_no_data_does_not_crash(self):
        # Empty data_dir — should still return a valid string
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIsInstance(report, str)
        self.assertIn("# SPA Monthly Report", report)

    def test_returns_string(self):
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIsInstance(report, str)

    def test_generated_date_in_report(self):
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("**Generated:**", report)

    def test_strategy_line_in_report(self):
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("SPA v1.0", report)
        self.assertIn("$100,000 USDC", report)

    def test_usdc_benchmark_in_performance_table(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("USDC Benchmark", report)

    def test_prev_month_column_present(self):
        self._write_equity(self._default_bars())
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("Prev Month", report)

    def test_protocol_breakdown_uses_adapter_status_fallback(self):
        adapters = [
            {"protocol_key": "aave-v3", "name": "Aave V3", "tier": "T1",
             "mock_apy": {"ethereum": {"USDC": 4.2}}},
        ]
        _write_json(Path(self.data_dir) / "adapter_status.json", {"adapters": adapters})
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("Aave V3", report)

    def test_yield_attribution_used_in_breakdown(self):
        ya = {
            "portfolio_apy_pp": 3.5,
            "breakdown": [
                {"protocol": "aave_v3", "tier": "T1", "apy_pct": 4.2,
                 "weight_frac": 0.4, "usd": 40_000},
            ],
        }
        _write_json(Path(self.data_dir) / "yield_attribution.json", ya)
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("Aave V3", report)

    def test_advisory_disclaimer_in_footer(self):
        report = mr.generate_markdown_report("2026-06", self.data_dir)
        self.assertIn("advisory only", report.lower())


# ─── save_report ──────────────────────────────────────────────────────────────

class TestSaveReport(_TmpDir):

    def _write_equity(self, bars: List[dict]) -> None:
        _write_json(
            Path(self.data_dir) / "equity_curve_daily.json",
            _equity_doc(bars),
        )

    def test_file_created(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        path = mr.save_report("2026-06", self.data_dir)
        self.assertTrue(os.path.exists(path))

    def test_file_path_contains_month(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        path = mr.save_report("2026-06", self.data_dir)
        self.assertIn("2026-06", path)
        self.assertTrue(path.endswith(".md"))

    def test_file_content_is_valid_markdown(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        path = mr.save_report("2026-06", self.data_dir)
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("# SPA Monthly Report", content)

    def test_no_tmp_file_leftover(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        mr.save_report("2026-06", self.data_dir)
        tmp_files = [f for f in os.listdir(self.data_dir) if f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], msg=f"Temp files left behind: {tmp_files}")

    def test_returns_path_string(self):
        path = mr.save_report("2026-06", self.data_dir)
        self.assertIsInstance(path, str)

    def test_idempotent_overwrite(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        p1 = mr.save_report("2026-06", self.data_dir)
        p2 = mr.save_report("2026-06", self.data_dir)
        self.assertEqual(p1, p2)
        self.assertTrue(os.path.exists(p2))

    def test_different_months_different_files(self):
        bars_jun = [_make_bar("2026-06-10", 100_000.0)]
        bars_jul = [_make_bar("2026-07-10", 100_000.0)]
        all_bars = bars_jun + bars_jul
        _write_json(
            Path(self.data_dir) / "equity_curve_daily.json",
            _equity_doc(all_bars),
        )
        p_jun = mr.save_report("2026-06", self.data_dir)
        p_jul = mr.save_report("2026-07", self.data_dir)
        self.assertNotEqual(p_jun, p_jul)
        self.assertIn("2026-06", p_jun)
        self.assertIn("2026-07", p_jul)


# ─── CLI (main) ───────────────────────────────────────────────────────────────

class TestCLI(_TmpDir):

    def _write_equity(self, bars: List[dict]) -> None:
        _write_json(
            Path(self.data_dir) / "equity_curve_daily.json",
            _equity_doc(bars),
        )

    def _run(self, argv: List[str]):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = mr.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_check_mode_prints_report(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        rc, out, _ = self._run(["--month", "2026-06", "--check", "--data-dir", self.data_dir])
        self.assertEqual(rc, 0)
        self.assertIn("SPA Monthly Report", out)

    def test_default_mode_prints_report(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        rc, out, _ = self._run(["--month", "2026-06", "--data-dir", self.data_dir])
        self.assertEqual(rc, 0)
        self.assertIn("SPA Monthly Report", out)

    def test_run_mode_writes_file(self):
        self._write_equity([_make_bar("2026-06-10", 100_000.0)])
        rc, out, _ = self._run(["--month", "2026-06", "--run", "--data-dir", self.data_dir])
        self.assertEqual(rc, 0)
        path = Path(self.data_dir) / "monthly_report_2026-06.md"
        self.assertTrue(path.exists())

    def test_bad_args_exit_zero(self):
        rc, _, _ = self._run(["--invalid-flag"])
        self.assertEqual(rc, 0)

    def test_missing_month_arg_exit_zero(self):
        rc, _, _ = self._run(["--run", "--data-dir", self.data_dir])
        self.assertEqual(rc, 0)


# ─── AST import hygiene ───────────────────────────────────────────────────────

_STDLIB_MODULES = {
    # Standard library modules used legitimately
    "argparse", "ast", "contextlib", "datetime", "io", "json", "logging",
    "math", "os", "pathlib", "sys", "tempfile", "typing",
    "__future__",
}

_ALLOWED_INTERNAL_PREFIXES = ("spa_core.",)


class TestImportHygiene(unittest.TestCase):
    """Verify that monthly_report.py uses only stdlib — no external packages."""

    def _get_imports(self):
        src_path = Path(mr.__file__)
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])
        return imports

    def test_no_external_imports(self):
        """monthly_report.py must not import third-party packages."""
        known_external = {
            "requests", "web3", "aiohttp", "numpy", "pandas", "scipy",
            "anthropic", "openai", "langchain", "boto3", "dotenv",
        }
        imports = self._get_imports()
        bad = [m for m in imports if m in known_external]
        self.assertEqual(bad, [], msg=f"External imports found: {bad}")

    def test_all_imports_are_stdlib_or_internal(self):
        """Every imported top-level module must be stdlib or an internal spa_core module."""
        imports = self._get_imports()
        for mod in imports:
            is_stdlib   = mod in _STDLIB_MODULES
            is_internal = any(
                mod.startswith(p.rstrip(".")) for p in _ALLOWED_INTERNAL_PREFIXES
            )
            # Also allow spa_core itself
            is_spa = mod == "spa_core"
            self.assertTrue(
                is_stdlib or is_internal or is_spa,
                msg=f"Non-stdlib, non-internal import found: {mod!r}",
            )


# ─── _prev_month helper ───────────────────────────────────────────────────────

class TestPrevMonth(unittest.TestCase):

    def test_regular_month(self):
        self.assertEqual(mr._prev_month("2026-06"), "2026-05")

    def test_january_wraps_to_previous_year(self):
        self.assertEqual(mr._prev_month("2026-01"), "2025-12")

    def test_bad_input_returns_none(self):
        self.assertIsNone(mr._prev_month("not-a-month"))
        self.assertIsNone(mr._prev_month(""))

    def test_december(self):
        self.assertEqual(mr._prev_month("2026-12"), "2026-11")


# ─── _month_label helper ──────────────────────────────────────────────────────

class TestMonthLabel(unittest.TestCase):

    def test_june_2026(self):
        self.assertEqual(mr._month_label("2026-06"), "June 2026")

    def test_january_2025(self):
        self.assertEqual(mr._month_label("2025-01"), "January 2025")

    def test_bad_input_returns_input(self):
        self.assertEqual(mr._month_label("bad"), "bad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
