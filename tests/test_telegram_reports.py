"""tests/test_telegram_reports.py — 30 unit tests for the enhanced Telegram
reporting modules:

* spa_core/reporting/daily_telegram_report.py
* spa_core/reporting/weekly_telegram_report.py
* spa_core/reporting/alert_on_milestone.py

Coverage:
  * report format functions produce the correct strings/fields
  * milestones trigger at the right thresholds and never re-fire
  * NO actual Telegram calls — the sender (`_post_message`) is always mocked

stdlib only; every test uses a temporary data directory for isolation.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.reporting import daily_telegram_report as daily  # noqa: E402
from spa_core.reporting import weekly_telegram_report as weekly  # noqa: E402
from spa_core.reporting import alert_on_milestone as milestone  # noqa: E402

# Path that all three modules import for the actual network send.
_SENDER = "spa_core.alerts.telegram_client._post_message"


# ───────────────────────── fixtures ─────────────────────────────────────────


def _write(ddir: Path, name: str, obj) -> None:
    (ddir / name).write_text(json.dumps(obj), encoding="utf-8")


def _equity_doc() -> dict:
    daily_bars = []
    # 8 days so the 7-day trailing average has a window to slice.
    base = 100000.0
    for i in range(8):
        day = 10 + i  # 2026-06-10 .. 2026-06-17
        open_eq = base + i * 10
        close_eq = open_eq + 10
        daily_bars.append(
            {
                "date": f"2026-06-{day:02d}",
                "open_equity": open_eq,
                "close_equity": close_eq,
                "equity": close_eq,
                "apy_today": 4.0 + i * 0.1,
                "positions": {
                    "aave_v3": 40000.0,
                    "compound_v3": 35000.0,
                    "yearn_v3": 15000.0,
                },
            }
        )
    return {"is_demo": False, "daily": daily_bars}


def _status_doc(**over) -> dict:
    doc = {
        "is_demo": False,
        "paper_start_date": "2026-06-10",
        "days_running": 11,
        "current_equity": 100121.33,
        "apy_today_pct": 4.82,
        "daily_yield_usd": 13.2,
        "last_cycle_status": "ok",
        "risk_policy_approved": True,
        "current_positions": {"aave_v3": 40000.0, "compound_v3": 35000.0},
    }
    doc.update(over)
    return doc


def _golive_doc(passed=25, total=26) -> dict:
    return {"ready": passed >= total, "passed": passed, "total": total, "blockers": []}


def _adapter_doc() -> dict:
    return {
        "adapters": {
            "aave_v3": {"display_name": "Aave V3", "apy": 3.8},
            "compound_v3": {"display_name": "Compound", "apy": 4.2},
            "yearn_v3": {"display_name": "Yearn V3", "apy": 5.1},
        }
    }


def _tournament_doc() -> dict:
    return {
        "strategies": [
            {"strategy_id": "S7", "net_apy": 5.2, "is_active": True},
            {"strategy_id": "S11", "net_apy": 4.8, "is_active": True},
            {"strategy_id": "S0", "net_apy": 4.1, "is_active": True},
            {"strategy_id": "S9", "net_apy": 9.9, "is_active": False},
        ]
    }


def _full_data_dir() -> Path:
    ddir = Path(tempfile.mkdtemp())
    _write(ddir, "equity_curve_daily.json", _equity_doc())
    _write(ddir, "paper_trading_status.json", _status_doc())
    _write(ddir, "golive_status.json", _golive_doc())
    _write(ddir, "adapter_status.json", _adapter_doc())
    _write(ddir, "tournament_results.json", _tournament_doc())
    _write(ddir, "trades.json", [
        {"trade_id": "T1", "ts": "2026-06-16T10:00:00+00:00", "type": "rebalance"},
        {"trade_id": "T2", "ts": "2026-06-17T10:00:00+00:00", "type": "rebalance"},
        {"trade_id": "T3", "ts": "2026-06-01T10:00:00+00:00", "type": "rebalance"},
    ])
    _write(ddir, "risk_policy_blocks.json", [
        {"ts": "2026-06-17T10:00:00+00:00", "date": "2026-06-17", "violations": ["x"]},
    ])
    return ddir


# ───────────────────────── daily report ─────────────────────────────────────


class TestDailyReport(unittest.TestCase):
    def setUp(self):
        self.ddir = _full_data_dir()

    def test_build_returns_dict(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertIsInstance(data, dict)

    def test_day_number_is_one_based(self):
        # 2026-06-10 is day 1, so 2026-06-17 is day 8.
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertEqual(data["day_number"], 8)

    def test_equity_and_pnl_from_bar(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        # bar i=7: open 100070, close 100080.
        self.assertAlmostEqual(data["equity_usd"], 100080.0)
        self.assertAlmostEqual(data["daily_pnl_usd"], 10.0)

    def test_seven_day_avg_present(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertIsInstance(data["apy_7day_avg_pct"], float)

    def test_best_strategy_picks_active_max(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertEqual(data["best_strategy"]["strategy_id"], "S7")

    def test_message_has_header_and_money(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        msg = daily.format_daily_message(data)
        self.assertIn("SPA Daily Report", msg)
        self.assertIn("Day 8", msg)
        self.assertIn("Portfolio:", msg)

    def test_message_lists_positions_with_display_names(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        msg = daily.format_daily_message(data)
        self.assertIn("Aave V3", msg)
        self.assertIn("Compound", msg)

    def test_message_shows_golive_score(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        msg = daily.format_daily_message(data)
        self.assertIn("GoLive: 25/26", msg)

    def test_risk_block_count_reflected(self):
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertEqual(data["risk_blocks_today"], 1)
        msg = daily.format_daily_message(data)
        self.assertIn("block event", msg)

    def test_risk_gate_clear_when_no_blocks(self):
        data = daily.build_report_data("2026-06-16", data_dir=self.ddir)
        msg = daily.format_daily_message(data)
        self.assertIn("within limits", msg)

    def test_position_cap_collapses_remainder(self):
        # 12 positions → capped to MAX_POSITION_LINES + a "+N more" line.
        pos = {f"p{i}": 1000.0 * (12 - i) for i in range(12)}
        bar = {
            "date": "2026-06-17", "open_equity": 100.0, "close_equity": 110.0,
            "equity": 110.0, "apy_today": 4.0, "positions": pos,
        }
        _write(self.ddir, "equity_curve_daily.json", {"is_demo": False, "daily": [bar]})
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        msg = daily.format_daily_message(data)
        self.assertIn("more:", msg)

    def test_missing_files_degrade_gracefully(self):
        empty = Path(tempfile.mkdtemp())
        data = daily.build_report_data("2026-06-17", data_dir=empty)
        msg = daily.format_daily_message(data)
        self.assertIsInstance(msg, str)
        self.assertIn("SPA Daily Report", msg)

    def test_corrupt_json_does_not_raise(self):
        (self.ddir / "equity_curve_daily.json").write_text("{not json", encoding="utf-8")
        data = daily.build_report_data("2026-06-17", data_dir=self.ddir)
        self.assertIsInstance(data, dict)

    def test_run_does_not_send_when_send_false(self):
        with patch(_SENDER) as m:
            res = daily.run_daily_report("2026-06-17", data_dir=self.ddir, send=False)
            m.assert_not_called()
        self.assertFalse(res["sent"])
        self.assertIn("SPA Daily Report", res["message"])

    def test_run_sends_via_mocked_sender(self):
        with patch(_SENDER, return_value=True) as m:
            res = daily.run_daily_report("2026-06-17", data_dir=self.ddir, send=True)
            m.assert_called_once()
        self.assertTrue(res["sent"])

    def test_send_failure_recorded(self):
        with patch(_SENDER, return_value=False):
            res = daily.run_daily_report("2026-06-17", data_dir=self.ddir, send=True)
        self.assertFalse(res["sent"])
        self.assertIsNotNone(res["error"])


# ───────────────────────── weekly report ────────────────────────────────────


class TestWeeklyReport(unittest.TestCase):
    def setUp(self):
        self.ddir = _full_data_dir()

    def test_window_is_seven_days_inclusive(self):
        start, end = weekly._window_dates("2026-06-21")
        self.assertEqual(start, "2026-06-15")
        self.assertEqual(end, "2026-06-21")

    def test_range_label_same_month(self):
        self.assertEqual(weekly._format_range("2026-06-15", "2026-06-21"),
                         "June 15-21, 2026")

    def test_week_number(self):
        # 2026-06-10 day1 → 2026-06-17 is within week 2.
        self.assertEqual(weekly._week_number("2026-06-17", "2026-06-10"), 2)

    def test_build_computes_week_pnl(self):
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        self.assertIsInstance(data["week_pnl_usd"], float)
        self.assertIsInstance(data["start_equity"], float)
        self.assertIsInstance(data["end_equity"], float)

    def test_rebalances_counted_in_window(self):
        # window 2026-06-11..06-17 includes T1 & T2, excludes T3 (06-01).
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        self.assertEqual(data["rebalances"], 2)

    def test_risk_blocks_counted_in_window(self):
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        self.assertEqual(data["risk_blocks"], 1)

    def test_strategy_ranking_excludes_inactive_and_zero(self):
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        ids = [s["strategy_id"] for s in data["top_strategies"]]
        self.assertEqual(ids, ["S7", "S11", "S0"])
        self.assertNotIn("S9", ids)  # inactive

    def test_message_contains_sections(self):
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        msg = weekly.format_weekly_message(data)
        self.assertIn("SPA Weekly Summary", msg)
        self.assertIn("Week performance", msg)
        self.assertIn("Strategy ranking", msg)
        self.assertIn("Rebalances:", msg)
        self.assertIn("GoLive progress", msg)

    def test_message_named_strategies(self):
        data = weekly.build_weekly_data("2026-06-17", data_dir=self.ddir)
        msg = weekly.format_weekly_message(data)
        self.assertIn("S7 Hybrid", msg)

    def test_run_sends_via_mocked_sender(self):
        with patch(_SENDER, return_value=True) as m:
            res = weekly.run_weekly_report("2026-06-17", data_dir=self.ddir, send=True)
            m.assert_called_once()
        self.assertTrue(res["sent"])

    def test_missing_files_degrade_gracefully(self):
        empty = Path(tempfile.mkdtemp())
        with patch(_SENDER) as m:
            res = weekly.run_weekly_report("2026-06-17", data_dir=empty, send=False)
            m.assert_not_called()
        self.assertIn("SPA Weekly Summary", res["message"])


# ───────────────────────── milestone alerts ─────────────────────────────────


class TestMilestoneAlerts(unittest.TestCase):
    def setUp(self):
        self.ddir = _full_data_dir()

    def test_no_milestone_before_day_14(self):
        res = milestone.check_milestones(days=11, apy=4.8, passed=25, total=26, notified=[])
        ids = [m["id"] for m in res]
        self.assertEqual(ids, [])

    def test_halfway_at_day_14(self):
        res = milestone.check_milestones(days=14, apy=4.8, passed=25, total=26, notified=[])
        ids = [m["id"] for m in res]
        self.assertIn("track_day_14", ids)
        self.assertNotIn("track_day_30", ids)

    def test_track_complete_at_day_30(self):
        res = milestone.check_milestones(days=30, apy=4.8, passed=25, total=26, notified=[])
        ids = [m["id"] for m in res]
        self.assertIn("track_day_30", ids)
        self.assertIn("track_day_14", ids)

    def test_apy_milestone_strictly_above_6(self):
        below = milestone.check_milestones(days=5, apy=6.0, passed=1, total=26, notified=[])
        self.assertNotIn("apy_above_6", [m["id"] for m in below])
        above = milestone.check_milestones(days=5, apy=6.01, passed=1, total=26, notified=[])
        self.assertIn("apy_above_6", [m["id"] for m in above])

    def test_golive_all_systems_go(self):
        res = milestone.check_milestones(days=5, apy=4.0, passed=26, total=26, notified=[])
        self.assertIn("golive_26_26", [m["id"] for m in res])

    def test_already_notified_not_refired(self):
        res = milestone.check_milestones(
            days=30, apy=7.0, passed=26, total=26,
            notified=["track_day_14", "track_day_30", "apy_above_6", "golive_26_26"],
        )
        self.assertEqual(res, [])

    def test_run_sends_and_persists_state(self):
        _write(self.ddir, "paper_trading_status.json", _status_doc(days_running=30, apy_today_pct=7.0))
        _write(self.ddir, "golive_status.json", _golive_doc(26, 26))
        with patch(_SENDER, return_value=True) as m:
            res = milestone.run_milestone_alerts(self.ddir, send=True)
            self.assertTrue(m.called)
        self.assertTrue(res["sent"])
        state = json.loads((self.ddir / "milestone_telegram_state.json").read_text())
        self.assertIn("golive_26_26", state["notified"])

    def test_run_idempotent_second_call_silent(self):
        _write(self.ddir, "paper_trading_status.json", _status_doc(days_running=30, apy_today_pct=7.0))
        _write(self.ddir, "golive_status.json", _golive_doc(26, 26))
        with patch(_SENDER, return_value=True):
            milestone.run_milestone_alerts(self.ddir, send=True)
        with patch(_SENDER, return_value=True) as m2:
            res2 = milestone.run_milestone_alerts(self.ddir, send=True)
            m2.assert_not_called()
        self.assertEqual(res2["sent"], [])

    def test_demo_data_skipped(self):
        _write(self.ddir, "paper_trading_status.json", _status_doc(is_demo=True, days_running=30))
        with patch(_SENDER) as m:
            res = milestone.run_milestone_alerts(self.ddir, send=True)
            m.assert_not_called()
        self.assertEqual(res["new"], [])

    def test_check_mode_does_not_send(self):
        _write(self.ddir, "paper_trading_status.json", _status_doc(days_running=30, apy_today_pct=7.0))
        with patch(_SENDER) as m:
            res = milestone.run_milestone_alerts(self.ddir, send=False)
            m.assert_not_called()
        self.assertIn("track_day_30", res["new"])
        # send=False must not persist state.
        self.assertFalse((self.ddir / "milestone_telegram_state.json").exists())

    def test_milestone_message_is_html(self):
        res = milestone.check_milestones(days=30, apy=4.0, passed=1, total=26, notified=[])
        msg = next(m["message"] for m in res if m["id"] == "track_day_30")
        self.assertIn("<b>", msg)


if __name__ == "__main__":
    unittest.main()
