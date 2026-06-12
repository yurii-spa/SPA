#!/usr/bin/env python3
"""MP-103: Tests for spa_core/reporting/pdf_report.py.

Covers:
  - test_generate_pdf_creates_file    file appears on disk after generation
  - test_pdf_is_valid_pdf             magic bytes "%PDF"
  - test_generate_pdf_returns_abs     returned path is absolute
  - test_output_dir_created           data/reports/ created when absent
  - test_pdf_report_with_mock_data    full generation with realistic mock data
  - test_missing_daily_report         no daily_report_*.json → graceful, no crash
  - test_missing_analytics            no analytics_summary → graceful, no crash
  - test_missing_golive               no golive_status → graceful, no crash
  - test_generate_latest_report       picks the latest daily_report_*.json
  - test_generate_latest_no_files     FileNotFoundError when no files present
  - test_invalid_date_raises          ValueError on bad date string
  - test_period_return_pct            helper computes compound return correctly
  - test_benchmark_return_pct         5%/yr benchmark helper
  - test_golive_checks_pass           _golive_checks maps True → PASS correctly
  - test_golive_checks_fail           _golive_checks maps False → FAIL correctly
  - test_fmt_pct                      _fmt_pct formatting helper
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Ensure spa_core is importable when running from the repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.reporting.pdf_report import (
    _benchmark_return_pct,
    _fmt_pct,
    _golive_checks,
    _period_return_pct,
    generate_latest_report,
    generate_pdf_report,
)

# ─── Fixture helpers ──────────────────────────────────────────────────────────

_DATE = "2026-06-10"


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _make_daily_report(data_dir: Path, date: str = _DATE) -> None:
    _write_json(data_dir / f"daily_report_{date}.json", {
        "date": date,
        "source": "daily_report",
        "is_demo": False,
        "equity_usd": 100008.61,
        "daily_pnl_usd": 8.61,
        "daily_pnl_pct": 0.0086,
        "total_return_pct": 0.0086,
        "days_running": 1,
        "top_protocol": "aave_v3",
        "golive_status": "PRE-LIVE",
        "active_adapters": ["aave_v3", "compound_v3", "maple"],
    })


def _make_analytics(data_dir: Path) -> None:
    _write_json(data_dir / "analytics_summary.json", {
        "generated_at": "2026-06-10T18:40:35+00:00",
        "source": "analytics_runner",
        "is_demo": False,
        "num_days": 1,
        "metrics": {
            "sharpe": 1.23,
            "calmar": 0.45,
            "drawdown": {"max_drawdown_pct": 0.5, "peak_date": _DATE, "trough_date": _DATE, "current_drawdown_pct": 0.0},
            "volatility": {"daily_vol": 0.01, "annualized_vol": 0.19, "vol_30d": 0.0},
            "benchmark": {"spa_total_return": 0.0086, "benchmark_total_return": 0.005, "alpha": 0.003},
        },
    })


def _make_golive(data_dir: Path, ready: bool = False) -> None:
    _write_json(data_dir / "golive_status.json", {
        "ready": ready,
        "checks": {
            "equity_curve_real": True,
            "trades_real": False,
            "status_real": True,
            "no_demo_data": True,
            "data_fresh_48h": True,
            "cycle_runner_exists": True,
        },
        "blockers": ["trades.json: no real trades yet"],
        "timestamp": "2026-06-10T18:40:35+00:00",
    })


def _make_orch(data_dir: Path) -> None:
    _write_json(data_dir / "adapter_orchestrator_status.json", {
        "generated_at": "2026-06-10T18:40:35+00:00",
        "adapters": [
            {"protocol": "aave_v3", "tier": "T1", "apy_pct": 3.13, "tvl_usd": 2e8, "status": "ok"},
            {"protocol": "compound_v3", "tier": "T1", "apy_pct": 3.18, "tvl_usd": 4.8e7, "status": "ok"},
            {"protocol": "maple", "tier": "T2", "apy_pct": 4.72, "tvl_usd": 3.1e9, "status": "ok"},
        ],
    })


def _make_status(data_dir: Path) -> None:
    _write_json(data_dir / "paper_trading_status.json", {
        "is_demo": False,
        "source": "cycle_runner",
        "current_equity": 100008.61,
        "cash_usd": 5000.03,
        "current_positions": {
            "aave_v3": 33142.85,
            "compound_v3": 28607.13,
            "maple": 11632.64,
        },
    })


def _make_equity_doc(data_dir: Path) -> None:
    _write_json(data_dir / "equity_curve_daily.json", {
        "source": "cycle_runner",
        "is_demo": False,
        "summary": {
            "num_days": 1,
            "total_return_pct": 0.0086,
            "start_equity": 100000.0,
            "end_equity": 100008.61,
        },
        "daily": [{
            "date": _DATE,
            "open_equity": 100000.0,
            "close_equity": 100008.61,
            "equity": 100008.61,
            "daily_return_pct": 0.0086,
            "cumulative_return_pct": 0.0086,
            "positions": {"aave_v3": 33142.85, "compound_v3": 28607.13, "maple": 11632.64},
        }],
    })


def _populate_all(data_dir: Path, date: str = _DATE) -> None:
    _make_daily_report(data_dir, date)
    _make_analytics(data_dir)
    _make_golive(data_dir)
    _make_orch(data_dir)
    _make_status(data_dir)
    _make_equity_doc(data_dir)


# ─── Test cases ───────────────────────────────────────────────────────────────


class TestGeneratePdfCreatesFile(unittest.TestCase):
    """test_generate_pdf_creates_file — verifies the PDF lands on disk."""

    def test_generate_pdf_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
            self.assertTrue(
                os.path.exists(pdf_path),
                f"PDF not found at {pdf_path}",
            )
            self.assertGreater(os.path.getsize(pdf_path), 0, "PDF is empty")


class TestPdfIsValidPdf(unittest.TestCase):
    """test_pdf_is_valid_pdf — first bytes must be %PDF."""

    def test_pdf_magic_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
            with open(pdf_path, "rb") as fh:
                magic = fh.read(4)
            self.assertEqual(magic, b"%PDF", f"Bad magic bytes: {magic!r}")


class TestGeneratePdfReturnsAbsolutePath(unittest.TestCase):
    """test_generate_pdf_returns_abs — returned string must be an absolute path."""

    def test_absolute_path(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
            self.assertTrue(
                os.path.isabs(pdf_path),
                f"Expected absolute path, got: {pdf_path}",
            )


class TestOutputDirCreated(unittest.TestCase):
    """test_output_dir_created — data/reports/ is created when absent."""

    def test_reports_dir_created(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            reports_dir = ddir / "reports"
            self.assertFalse(reports_dir.exists(), "reports/ should not exist yet")
            generate_pdf_report(_DATE, data_dir=ddir)
            self.assertTrue(reports_dir.is_dir(), "reports/ should be created")


class TestPdfReportWithMockData(unittest.TestCase):
    """test_pdf_report_with_mock_data — full generation with realistic mock data."""

    def test_full_generation_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
            self.assertTrue(os.path.exists(pdf_path))
            size = os.path.getsize(pdf_path)
            self.assertGreater(size, 5_000, f"PDF suspiciously small: {size} bytes")

    def test_pdf_named_correctly(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir)
            pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
            self.assertIn(f"investor_report_{_DATE}.pdf", pdf_path)


class TestMissingDailyReport(unittest.TestCase):
    """test_missing_daily_report — no daily_report_*.json → graceful, no crash."""

    def test_no_daily_report(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            # Only analytics + golive — no daily_report_*.json
            _make_analytics(ddir)
            _make_golive(ddir)
            _make_orch(ddir)
            _make_status(ddir)
            # Should succeed gracefully (missing data → "—" fields in PDF)
            try:
                pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
                self.assertTrue(os.path.exists(pdf_path))
            except Exception as exc:
                self.fail(f"generate_pdf_report raised unexpectedly: {exc}")


class TestMissingAnalytics(unittest.TestCase):
    """test_missing_analytics — no analytics_summary.json → graceful, no crash."""

    def test_no_analytics(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _make_daily_report(ddir)
            _make_golive(ddir)
            _make_orch(ddir)
            _make_status(ddir)
            # No analytics_summary.json
            try:
                pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
                self.assertTrue(os.path.exists(pdf_path))
            except Exception as exc:
                self.fail(f"generate_pdf_report raised unexpectedly: {exc}")


class TestMissingGolive(unittest.TestCase):
    """test_missing_golive — no golive_status.json → graceful, no crash."""

    def test_no_golive(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _make_daily_report(ddir)
            _make_analytics(ddir)
            _make_orch(ddir)
            _make_status(ddir)
            # No golive_status.json
            try:
                pdf_path = generate_pdf_report(_DATE, data_dir=ddir)
                self.assertTrue(os.path.exists(pdf_path))
            except Exception as exc:
                self.fail(f"generate_pdf_report raised unexpectedly: {exc}")


class TestGenerateLatestReport(unittest.TestCase):
    """test_generate_latest_report — picks the latest daily_report_*.json."""

    def test_picks_latest(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            # Write two dated reports
            for date in ["2026-06-09", "2026-06-10"]:
                _make_daily_report(ddir, date)
            _make_analytics(ddir)
            _make_golive(ddir)
            _make_orch(ddir)
            _make_status(ddir)
            _make_equity_doc(ddir)

            pdf_path = generate_latest_report(data_dir=ddir)
            # Should be for the latest date
            self.assertIn("2026-06-10", pdf_path)
            self.assertTrue(os.path.exists(pdf_path))

    def test_single_file(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            _populate_all(ddir, date=_DATE)
            pdf_path = generate_latest_report(data_dir=ddir)
            self.assertIn(_DATE, pdf_path)
            self.assertTrue(os.path.exists(pdf_path))


class TestGenerateLatestNoFiles(unittest.TestCase):
    """test_generate_latest_no_files — FileNotFoundError when no JSON files."""

    def test_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            with self.assertRaises(FileNotFoundError):
                generate_latest_report(data_dir=ddir)


class TestInvalidDateRaises(unittest.TestCase):
    """test_invalid_date_raises — ValueError on a malformed date string."""

    def test_bad_date(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            with self.assertRaises(ValueError):
                generate_pdf_report("not-a-date", data_dir=ddir)

    def test_wrong_format(self):
        with tempfile.TemporaryDirectory() as td:
            ddir = Path(td)
            with self.assertRaises(ValueError):
                generate_pdf_report("10-06-2026", data_dir=ddir)


class TestPeriodReturnPct(unittest.TestCase):
    """test_period_return_pct — helper computes compound return correctly."""

    def _bar(self, date: str, open_eq: float, close_eq: float) -> dict:
        return {
            "date": date,
            "open_equity": open_eq,
            "close_equity": close_eq,
            "equity": close_eq,
            "daily_return_pct": round((close_eq / open_eq - 1) * 100, 6),
        }

    def test_single_bar(self):
        bars = [self._bar("2026-06-10", 100_000, 100_010)]
        result = _period_return_pct(bars, 1)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.01, places=4)

    def test_multi_bar(self):
        bars = [
            self._bar("2026-06-08", 100_000, 100_010),
            self._bar("2026-06-09", 100_010, 100_025),
            self._bar("2026-06-10", 100_025, 100_040),
        ]
        # 3-day window: 100000 → 100040
        result = _period_return_pct(bars, 3)
        expected = (100_040 / 100_000 - 1) * 100
        self.assertAlmostEqual(result, expected, places=4)

    def test_empty_bars(self):
        self.assertIsNone(_period_return_pct([], 7))

    def test_capped_at_bar_count(self):
        bars = [self._bar("2026-06-10", 100_000, 100_010)]
        # Asking for 7 days but only 1 bar → uses what's available
        result = _period_return_pct(bars, 7)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.01, places=4)


class TestBenchmarkReturnPct(unittest.TestCase):
    """test_benchmark_return_pct — 5%/yr compound benchmark helper."""

    def test_one_year(self):
        result = _benchmark_return_pct(365)
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_one_day(self):
        result = _benchmark_return_pct(1)
        expected = ((1.05 ** (1 / 365)) - 1) * 100
        self.assertAlmostEqual(result, expected, places=6)

    def test_positive(self):
        self.assertGreater(_benchmark_return_pct(30), 0)


class TestGolivChecks(unittest.TestCase):
    """test_golive_checks_pass / _fail — _golive_checks maps boolean correctly."""

    def test_all_pass(self):
        golive = {
            "ready": True,
            "checks": {k: True for k in [
                "equity_curve_real", "trades_real", "status_real",
                "no_demo_data", "data_fresh_48h", "cycle_runner_exists",
            ]},
        }
        result = _golive_checks(golive)
        self.assertEqual(len(result), 6)
        for passed, key, label in result:
            self.assertTrue(passed, f"{key} should be PASS")

    def test_all_fail(self):
        golive = {"ready": False, "checks": {}}
        result = _golive_checks(golive)
        for passed, key, label in result:
            self.assertFalse(passed, f"{key} should be FAIL")

    def test_mixed(self):
        golive = {
            "ready": False,
            "checks": {
                "equity_curve_real": True,
                "trades_real": False,
                "status_real": True,
                "no_demo_data": True,
                "data_fresh_48h": True,
                "cycle_runner_exists": True,
            },
        }
        result = _golive_checks(golive)
        passed_keys = {key for ok, key, _ in result if ok}
        failed_keys = {key for ok, key, _ in result if not ok}
        self.assertIn("equity_curve_real", passed_keys)
        self.assertIn("trades_real", failed_keys)
        self.assertEqual(len(passed_keys) + len(failed_keys), 6)

    def test_returns_six_items(self):
        result = _golive_checks({})
        self.assertEqual(len(result), 6)


class TestFmtPct(unittest.TestCase):
    """test_fmt_pct — formatting helper."""

    def test_positive(self):
        self.assertEqual(_fmt_pct(0.0086), "+0.0086%")

    def test_negative(self):
        self.assertEqual(_fmt_pct(-0.0086), "-0.0086%")

    def test_zero(self):
        self.assertEqual(_fmt_pct(0.0), "+0.0000%")

    def test_none(self):
        self.assertEqual(_fmt_pct(None), "—")

    def test_no_plus(self):
        result = _fmt_pct(1.5, plus=False)
        self.assertNotIn("+", result)
        self.assertIn("1.5", result)


if __name__ == "__main__":
    unittest.main()
