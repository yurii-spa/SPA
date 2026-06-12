"""Tests for spa_core/agents/reporting_agent.py (MP-305) — spec-compliant.

Covers:
  collect_pnl_data       — no files, 2+ entries, partial files, correct pnl
  validate_report_numbers — valid data, out-of-range equity, None values
  format_daily_report     — structure, incomplete flag, P&L sign
  send_daily_report_telegram(dry_run=True) — returns dict with report_text,
                                              writes reporting_status.json
  generate_monthly_pdf_report — day not 1 → None, day 1 → .txt file
  run_reporting_cycle(dry_run=True) — dict with daily_sent/monthly_generated/errors
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from spa_core.agents.reporting_agent import (
    collect_pnl_data,
    format_daily_report,
    generate_monthly_pdf_report,
    run_reporting_cycle,
    send_daily_report_telegram,
    validate_report_numbers,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _make_portfolio_track_list(n: int = 3, start: float = 100_000.0) -> list:
    entries = []
    eq = start
    for i in range(n):
        eq = round(eq * 1.00027, 2)
        entries.append({"date": f"2026-06-{i + 1:02d}", "equity_usd": eq})
    return entries


def _make_analytics(apy: float = 5.2) -> dict:
    return {"avg_apy_7d": apy}


def _make_orch(n_ok: int = 3, n_err: int = 1) -> dict:
    adapters = (
        [{"protocol": f"p{i}", "status": "ok"} for i in range(n_ok)]
        + [{"protocol": f"bad{i}", "status": "error"} for i in range(n_err)]
    )
    return {"adapters": adapters}


def _make_sentinel(cls: str = "NORMAL") -> dict:
    return {"alert_class": cls}


def _setup(tmpdir: Path, pt=None, an=None, orch=None, sent=None) -> None:
    if pt is not None:
        _write_json(tmpdir / "portfolio_track.json", pt)
    if an is not None:
        _write_json(tmpdir / "analytics_summary.json", an)
    if orch is not None:
        _write_json(tmpdir / "adapter_orchestrator_status.json", orch)
    if sent is not None:
        _write_json(tmpdir / "sentinel_status.json", sent)


# ═══════════════════════════════════════════════════════════════════════════════
# collect_pnl_data
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollectPnlData(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil; shutil.rmtree(self._d, ignore_errors=True)

    # ── no files ─────────────────────────────────────────────────────────────

    def test_no_files_data_complete_false(self):
        r = collect_pnl_data(self.data_dir)
        self.assertFalse(r["data_complete"])

    def test_no_files_equity_today_is_none(self):
        r = collect_pnl_data(self.data_dir)
        self.assertIsNone(r["equity_today"])

    def test_no_files_avg_apy_7d_is_none(self):
        r = collect_pnl_data(self.data_dir)
        self.assertIsNone(r["avg_apy_7d"])

    def test_no_files_active_adapters_is_none(self):
        r = collect_pnl_data(self.data_dir)
        self.assertIsNone(r["active_adapters"])

    def test_no_files_alert_class_is_none(self):
        r = collect_pnl_data(self.data_dir)
        self.assertIsNone(r["alert_class"])

    # ── with 2+ entries ───────────────────────────────────────────────────────

    def test_two_entries_correct_pnl_usd(self):
        pt = [
            {"date": "2026-06-10", "equity_usd": 100_000.0},
            {"date": "2026-06-11", "equity_usd": 100_200.0},
        ]
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertAlmostEqual(r["daily_pnl_usd"], 200.0)

    def test_two_entries_correct_daily_pnl_pct(self):
        pt = [
            {"date": "2026-06-10", "equity_usd": 100_000.0},
            {"date": "2026-06-11", "equity_usd": 100_100.0},
        ]
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertAlmostEqual(r["daily_pnl_pct"], 0.1, places=4)

    def test_analytics_avg_apy_7d_read(self):
        pt = _make_portfolio_track_list(2)
        _setup(self.data_dir, pt=pt, an={"avg_apy_7d": 7.77}, orch=_make_orch(), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertAlmostEqual(r["avg_apy_7d"], 7.77)

    def test_active_adapters_counts_ok_only(self):
        pt = _make_portfolio_track_list(2)
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(n_ok=4, n_err=2), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertEqual(r["active_adapters"], 4)

    def test_alert_class_read(self):
        pt = _make_portfolio_track_list(2)
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(), sent={"alert_class": "CRITICAL"})
        r = collect_pnl_data(self.data_dir)
        self.assertEqual(r["alert_class"], "CRITICAL")

    def test_dict_format_portfolio_track(self):
        pt = {"entries": _make_portfolio_track_list(3)}
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertIsNotNone(r["equity_today"])

    # ── partial files ─────────────────────────────────────────────────────────

    def test_missing_sentinel_data_complete_false(self):
        pt = _make_portfolio_track_list(2)
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch())
        # no sentinel
        r = collect_pnl_data(self.data_dir)
        self.assertFalse(r["data_complete"])

    def test_missing_analytics_data_complete_false(self):
        pt = _make_portfolio_track_list(2)
        _setup(self.data_dir, pt=pt, orch=_make_orch(), sent=_make_sentinel())
        # no analytics
        r = collect_pnl_data(self.data_dir)
        self.assertFalse(r["data_complete"])

    def test_all_files_present_data_complete_true(self):
        pt = _make_portfolio_track_list(3)
        _setup(self.data_dir, pt=pt, an=_make_analytics(), orch=_make_orch(), sent=_make_sentinel())
        r = collect_pnl_data(self.data_dir)
        self.assertTrue(r["data_complete"])


# ═══════════════════════════════════════════════════════════════════════════════
# validate_report_numbers
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateReportNumbers(unittest.TestCase):
    def _valid(self, **kw) -> dict:
        d = {
            "equity_today": 100_000.0,
            "daily_pnl_pct": 0.1,
            "avg_apy_7d": 5.2,
            "active_adapters": 3,
            "data_complete": True,
        }
        d.update(kw)
        return d

    def test_valid_data_ok_true_no_errors(self):
        ok, errors = validate_report_numbers(self._valid())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_equity_zero_fails(self):
        ok, errors = validate_report_numbers(self._valid(equity_today=0.0))
        self.assertFalse(ok)
        self.assertTrue(any("equity_today" in e for e in errors))

    def test_equity_above_10m_fails(self):
        ok, errors = validate_report_numbers(self._valid(equity_today=10_000_001.0))
        self.assertFalse(ok)

    def test_equity_none_fails(self):
        ok, errors = validate_report_numbers(self._valid(equity_today=None))
        self.assertFalse(ok)
        self.assertTrue(any("equity_today" in e for e in errors))

    def test_pnl_pct_below_minus50_fails(self):
        ok, errors = validate_report_numbers(self._valid(daily_pnl_pct=-51.0))
        self.assertFalse(ok)

    def test_pnl_pct_above_50_fails(self):
        ok, errors = validate_report_numbers(self._valid(daily_pnl_pct=51.0))
        self.assertFalse(ok)

    def test_pnl_pct_none_fails(self):
        ok, errors = validate_report_numbers(self._valid(daily_pnl_pct=None))
        self.assertFalse(ok)

    def test_apy_negative_fails(self):
        ok, errors = validate_report_numbers(self._valid(avg_apy_7d=-0.1))
        self.assertFalse(ok)

    def test_apy_above_100_fails(self):
        ok, errors = validate_report_numbers(self._valid(avg_apy_7d=100.1))
        self.assertFalse(ok)

    def test_apy_none_fails(self):
        ok, errors = validate_report_numbers(self._valid(avg_apy_7d=None))
        self.assertFalse(ok)

    def test_adapters_none_fails(self):
        ok, errors = validate_report_numbers(self._valid(active_adapters=None))
        self.assertFalse(ok)

    def test_adapters_above_100_fails(self):
        ok, errors = validate_report_numbers(self._valid(active_adapters=101))
        self.assertFalse(ok)

    def test_errors_describe_the_problem(self):
        ok, errors = validate_report_numbers(self._valid(equity_today=None, avg_apy_7d=None))
        self.assertGreaterEqual(len(errors), 2)
        for e in errors:
            self.assertIsInstance(e, str)
            self.assertGreater(len(e), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# format_daily_report
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatDailyReport(unittest.TestCase):
    def _data(self, **kw) -> dict:
        d = {
            "equity_today": 100_100.0,
            "daily_pnl_usd": 100.0,
            "daily_pnl_pct": 0.10,
            "avg_apy_7d": 5.2,
            "active_adapters": 3,
            "alert_class": "NORMAL",
            "data_complete": True,
        }
        d.update(kw)
        return d

    def test_contains_spa_daily_report(self):
        self.assertIn("SPA Daily Report", format_daily_report(self._data()))

    def test_positive_pnl_shows_plus(self):
        t = format_daily_report(self._data(daily_pnl_usd=50.0, daily_pnl_pct=0.05))
        self.assertIn("+", t)

    def test_negative_pnl_shows_minus(self):
        t = format_daily_report(self._data(daily_pnl_usd=-200.0, daily_pnl_pct=-0.2))
        self.assertIn("-", t)

    def test_incomplete_data_shows_warning(self):
        t = format_daily_report(self._data(data_complete=False))
        self.assertIn("⚠️ Incomplete", t)

    def test_complete_data_no_incomplete_warning(self):
        t = format_daily_report(self._data(data_complete=True))
        self.assertNotIn("⚠️", t)

    def test_alert_class_in_output(self):
        t = format_daily_report(self._data(alert_class="WARNING"))
        self.assertIn("WARNING", t)

    def test_none_values_do_not_raise(self):
        data = {k: None for k in ["equity_today", "daily_pnl_usd", "daily_pnl_pct",
                                   "avg_apy_7d", "active_adapters", "alert_class"]}
        data["data_complete"] = False
        t = format_daily_report(data)
        self.assertIn("SPA Daily Report", t)
        self.assertIn("⚠️ Incomplete", t)

    def test_apy_value_present(self):
        t = format_daily_report(self._data(avg_apy_7d=5.2))
        self.assertIn("5.2", t)

    def test_adapters_count_present(self):
        t = format_daily_report(self._data(active_adapters=4))
        self.assertIn("4", t)


# ═══════════════════════════════════════════════════════════════════════════════
# send_daily_report_telegram
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendDailyReportTelegram(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil; shutil.rmtree(self._d, ignore_errors=True)

    def _setup_full(self):
        _setup(
            self.data_dir,
            pt=_make_portfolio_track_list(3),
            an=_make_analytics(),
            orch=_make_orch(),
            sent=_make_sentinel(),
        )

    def test_dry_run_returns_dict(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertIsInstance(r, dict)

    def test_result_has_report_text(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertIn("report_text", r)
        self.assertIn("SPA Daily Report", r["report_text"])

    def test_result_sent_true_on_dry_run(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertTrue(r["sent"])

    def test_result_dry_run_flag_true(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertTrue(r["dry_run"])

    def test_writes_reporting_status_json(self):
        self._setup_full()
        send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertTrue((self.data_dir / "reporting_status.json").exists())

    def test_reporting_status_valid_json_with_report_text(self):
        self._setup_full()
        send_daily_report_telegram(self.data_dir, dry_run=True)
        doc = json.loads((self.data_dir / "reporting_status.json").read_text())
        self.assertIn("report_text", doc)

    def test_no_stray_tmp_files(self):
        self._setup_full()
        send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_empty_data_dir_no_raise(self):
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertIsInstance(r, dict)
        self.assertIn("report_text", r)

    def test_validation_ok_key_present(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertIn("validation_ok", r)

    def test_data_complete_key_present(self):
        self._setup_full()
        r = send_daily_report_telegram(self.data_dir, dry_run=True)
        self.assertIn("data_complete", r)


# ═══════════════════════════════════════════════════════════════════════════════
# generate_monthly_pdf_report
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateMonthlyPdfReport(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil; shutil.rmtree(self._d, ignore_errors=True)

    def test_not_day_1_returns_none(self):
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, self.data_dir)
        self.assertIsNone(r)

    def test_day_1_creates_txt_file(self):
        _write_json(self.data_dir / "portfolio_track.json", _make_portfolio_track_list(5))
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, self.data_dir)
        self.assertIsNotNone(r)
        self.assertTrue(r.endswith(".txt"))
        self.assertTrue(Path(r).exists())

    def test_day_1_filename_correct(self):
        _write_json(self.data_dir / "portfolio_track.json", _make_portfolio_track_list(5))
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, self.data_dir)
        self.assertIn("spa_monthly_2026_07", Path(r).name)

    def test_day_1_content_has_title(self):
        _write_json(self.data_dir / "portfolio_track.json", _make_portfolio_track_list(5))
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, self.data_dir)
        content = Path(r).read_text(encoding="utf-8")
        self.assertIn("SPA Monthly Report", content)

    def test_creates_output_dir_if_missing(self):
        _write_json(self.data_dir / "portfolio_track.json", _make_portfolio_track_list(3))
        out = self.data_dir / "reports"
        self.assertFalse(out.exists())
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, out)
        if r:
            self.assertTrue(out.exists())

    def test_no_portfolio_track_does_not_raise(self):
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = generate_monthly_pdf_report(self.data_dir, self.data_dir)
        self.assertTrue(r is None or isinstance(r, str))


# ═══════════════════════════════════════════════════════════════════════════════
# run_reporting_cycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunReportingCycle(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.data_dir = Path(self._d)

    def tearDown(self):
        import shutil; shutil.rmtree(self._d, ignore_errors=True)

    def _setup_full(self):
        _setup(
            self.data_dir,
            pt=_make_portfolio_track_list(3),
            an=_make_analytics(),
            orch=_make_orch(),
            sent=_make_sentinel(),
        )

    def test_returns_dict(self):
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertIsInstance(r, dict)

    def test_has_daily_sent_key(self):
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertIn("daily_sent", r)

    def test_has_monthly_generated_key(self):
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertIn("monthly_generated", r)

    def test_has_errors_key_list(self):
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertIn("errors", r)
        self.assertIsInstance(r["errors"], list)

    def test_daily_sent_true_dry_run(self):
        self._setup_full()
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertTrue(r["daily_sent"])

    def test_monthly_generated_none_on_non_day1(self):
        self._setup_full()
        with patch("spa_core.agents.reporting_agent.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
            mock_dt.strptime = datetime.strptime
            r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertIsNone(r["monthly_generated"])

    def test_empty_data_dir_no_raise(self):
        try:
            r = run_reporting_cycle(self.data_dir, dry_run=True)
        except Exception as exc:
            self.fail(f"run_reporting_cycle raised: {exc}")
        self.assertIsInstance(r, dict)

    def test_dry_run_no_telegram_api_call(self):
        self._setup_full()
        # Telegram API would raise KeychainError in sandbox; dry_run must skip it
        r = run_reporting_cycle(self.data_dir, dry_run=True)
        self.assertTrue(r["daily_sent"])


if __name__ == "__main__":
    unittest.main()
