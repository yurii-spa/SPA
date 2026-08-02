"""Honesty tests for the cycle-gap alert (`spa_core/paper_trading/cycle_gap_monitor.py`).

Owner card (inbox 2026-07-30, source=telegram): «Задача решить проблему
🚨 Пропущен ежедневный цикл» — the owner forwarded this alert body::

    📅 Last cycle: unknown (999.0h ago)
    🕐 Expected: daily ~08:00 UTC
    ❌ Today's cycle appears to have MISSED
    Track record: Day 24 / go-live 32d
    ⚡ Action: check launchd com.spa.daily_cycle status

Every numeric claim in those five lines is either **unmeasured** or **wrong**:

1. ``unknown (999.0h ago)`` — self-contradictory. When the timestamp cannot be
   resolved the monitor measured NOTHING, yet it published a specific age
   (999.0h) and asserted the cycle "MISSED".  Same class as the fail-OPEN
   monitors closed in cycles #29/#31/#35/#36/#37/#38/#40, mirrored: instead of
   claiming health it never checked, it claims a *measurement* it never made.
   Fail-CLOSED (alert anyway) is correct — the fabricated number is not.
2. ``Expected: daily ~08:00 UTC`` — launchd schedules ``com.spa.daily_cycle``
   with ``StartCalendarInterval Hour=8`` in **local** time (06:00 UTC in summer).
   The owner is told to check a schedule the system never promised.
3. ``go-live 32d`` — derived from a hard-coded decision date that has since
   passed, so today the same code prints ``go-live 0d`` for every alert.
4. ``Track record: Day 24`` — calendar days since paper start, published under
   the name of the metric the project actually tracks (evidenced days: 37 vs 51
   calendar on 2026-07-30).

Hermetic: no network, no live ``data/``, every path under ``tmp_path``.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from spa_core.paper_trading import cycle_gap_monitor as cgm
from spa_core.paper_trading.cycle_gap_monitor import (
    GAP_STATE_FILENAME,
    STATUS_FILENAME,
    _UNKNOWN_HOURS,
    _compute_days_to_golive,
    _compute_paper_days,
    _format_alert_message,
    run_cycle_gap_monitor,
)


def _utc(y, m, d, hour=12) -> datetime:
    return datetime(y, m, d, hour, 0, 0, tzinfo=timezone.utc)


class _TmpData(unittest.TestCase):
    """Base: a hermetic data dir under a TemporaryDirectory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ddir = Path(self._tmp.name) / "data"
        self.ddir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _run_capturing_alert(self, now):
        """Run the monitor (non-dry) capturing the message instead of pushing."""
        captured: dict = {}

        def _fake_send(message, title=None):
            captured["message"] = message
            captured["title"] = title
            return True

        with patch.object(cgm, "_send_telegram_alert", _fake_send):
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        return result, captured


# ── 1. "unknown" must never be published as a measured age ───────────────────


class TestUnknownIsNotAMeasurement(_TmpData):

    def test_message_for_unknown_ts_has_no_fabricated_hours(self):
        """No status file → the alert must not print '999.0h ago'."""
        msg = _format_alert_message(
            None, _UNKNOWN_HOURS, 7, 0,
            unknown_reason="paper_trading_status.json not found",
        )
        self.assertNotIn("999", msg)
        self.assertNotIn("h ago", msg)

    def test_message_for_unknown_ts_does_not_assert_a_miss(self):
        """'appears to have MISSED' is a claim; unmeasured means unmeasured."""
        msg = _format_alert_message(
            None, _UNKNOWN_HOURS, 7, 0,
            unknown_reason="paper_trading_status.json not found",
        )
        self.assertNotIn("MISSED", msg)
        self.assertIn("NOT MEASURED", msg.upper())

    def test_message_for_unknown_ts_quotes_the_reason_verbatim(self):
        reason = "no usable 'last_cycle_ts' in paper_trading_status.json (value: None)"
        msg = _format_alert_message(None, _UNKNOWN_HOURS, 7, 0, unknown_reason=reason)
        self.assertIn(reason, msg)

    def test_run_reports_measured_false_when_status_file_missing(self):
        result, captured = self._run_capturing_alert(_utc(2026, 6, 12, 12))
        self.assertTrue(result["gap_detected"], "fail-CLOSED: still alerts")
        self.assertFalse(result["measured"])
        self.assertIn("paper_trading_status.json", result["unknown_reason"])
        self.assertNotIn("999", captured["message"])

    def test_run_reports_measured_false_when_ts_unparseable(self):
        (self.ddir / STATUS_FILENAME).write_text(
            json.dumps({"last_cycle_ts": "not-a-date"}), encoding="utf-8"
        )
        result, captured = self._run_capturing_alert(_utc(2026, 6, 12, 12))
        self.assertFalse(result["measured"])
        self.assertIn("not-a-date", result["unknown_reason"])
        self.assertIn("not-a-date", captured["message"])

    def test_run_reports_measured_false_when_status_corrupt(self):
        (self.ddir / STATUS_FILENAME).write_text("NOT JSON", encoding="utf-8")
        result, _ = self._run_capturing_alert(_utc(2026, 6, 12, 12))
        self.assertFalse(result["measured"])
        self.assertTrue(result["unknown_reason"])

    def test_state_file_records_measured_flag_and_reason(self):
        self._run_capturing_alert(_utc(2026, 6, 12, 12))
        state = json.loads((self.ddir / GAP_STATE_FILENAME).read_text())
        self.assertFalse(state["measured"])
        self.assertTrue(state["unknown_reason"])
        # additive only — the pre-existing observability keys survive
        for key in ("last_check_ts", "gap_detected", "hours_since", "alert_sent"):
            self.assertIn(key, state)

    def test_unmeasured_alert_uses_a_distinct_title(self):
        _, captured = self._run_capturing_alert(_utc(2026, 6, 12, 12))
        self.assertIsNotNone(captured["title"])
        self.assertNotEqual(captured["title"], "SPA — Cycle Gap Detected")

    def test_measured_gap_keeps_the_original_title(self):
        now = _utc(2026, 6, 12, 12)
        (self.ddir / STATUS_FILENAME).write_text(
            json.dumps({"last_cycle_ts": (now - timedelta(hours=30)).isoformat()}),
            encoding="utf-8",
        )
        result, captured = self._run_capturing_alert(now)
        self.assertTrue(result["measured"])
        self.assertEqual(captured["title"], "SPA — Cycle Gap Detected")


# ── 2. the published schedule must match launchd ─────────────────────────────


class TestPublishedScheduleIsTrue(unittest.TestCase):

    def test_message_does_not_claim_a_utc_schedule(self):
        """launchd StartCalendarInterval Hour=8 is LOCAL, not UTC."""
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertNotIn("08:00 UTC", msg)

    def test_message_names_local_time_and_the_agent(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertIn("local", msg.lower())
        self.assertIn("com.spa.daily_cycle", msg)

    def test_expected_hour_constant_matches_the_published_text(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertIn(f"{cgm.EXPECTED_CYCLE_LOCAL_HOUR:02d}:00", msg)


# ── 3. no countdown derived from an elapsed hard-coded date ──────────────────


class TestGoLiveCountdownNotFabricated(unittest.TestCase):

    def test_zero_days_prints_no_countdown(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 0)
        self.assertNotIn("go-live 0d", msg)

    def test_positive_days_still_printed(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertIn("go-live 33d", msg)

    def test_docstring_agrees_with_the_constant(self):
        """The helper documented 2026-07-21 while the constant said 2026-07-15."""
        doc = _compute_days_to_golive.__doc__ or ""
        self.assertIn(cgm._GOLIVE_DATE.strftime("%Y-%m-%d"), doc)


# ── 4. calendar days must not be published as "track record" ─────────────────


class TestTrackDayLabelledHonestly(unittest.TestCase):

    def test_day_line_says_it_is_calendar_days(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 7, 33)
        self.assertIn("Day 7", msg)          # unchanged for the reader
        self.assertIn("calendar", msg.lower())

    def test_missing_paper_start_is_unknown_not_a_default_date(self):
        """A status doc without paper_start_date must not invent 2026-05-20."""
        self.assertEqual(_compute_paper_days({}, _utc(2026, 7, 30)), 0)

    def test_unknown_day_count_prints_no_day_line(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 0, 33)
        self.assertNotIn("Day 0", msg)

    def test_explicit_start_date_still_counted(self):
        days = _compute_paper_days({"paper_start_date": "2026-06-10"}, _utc(2026, 6, 12))
        self.assertEqual(days, 3)


# ── 5. positive controls — the measured path is not damaged ──────────────────


class TestMeasuredPathUnchanged(_TmpData):

    def test_measured_message_still_carries_the_facts(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 7, 33)
        self.assertIn("28.5h ago", msg)
        self.assertIn("2026-06-11T08:00:00Z", msg)
        self.assertIn("Day 7", msg)
        self.assertIn("go-live 33d", msg)
        self.assertIn("MISSED", msg)

    def test_healthy_cycle_still_silent(self):
        now = _utc(2026, 6, 12, 12)
        (self.ddir / STATUS_FILENAME).write_text(
            json.dumps({"last_cycle_ts": (now - timedelta(hours=3)).isoformat()}),
            encoding="utf-8",
        )
        result, captured = self._run_capturing_alert(now)
        self.assertFalse(result["gap_detected"])
        self.assertTrue(result["measured"])
        self.assertNotIn("message", captured)

    def test_measured_gap_still_alerts(self):
        now = _utc(2026, 6, 12, 12)
        (self.ddir / STATUS_FILENAME).write_text(
            json.dumps({"last_cycle_ts": (now - timedelta(hours=30)).isoformat()}),
            encoding="utf-8",
        )
        result, captured = self._run_capturing_alert(now)
        self.assertTrue(result["gap_detected"])
        self.assertTrue(result["alert_sent"])
        self.assertIn("30.0h ago", captured["message"])

    def test_before_alert_hour_still_no_alert(self):
        """The hour>=8 UTC condition holds — before it, no alert.
        Updated 2026-07-23 (owner Variant B): threshold 10→8; test hour 9→7 (still < threshold)."""
        now = _utc(2026, 6, 12, 7)
        result, captured = self._run_capturing_alert(now)
        self.assertFalse(result["gap_detected"])
        self.assertNotIn("message", captured)


# ── 6. the plain-Russian layer knows both titles ─────────────────────────────


class TestHumanizeCoversBothTitles(unittest.TestCase):

    def test_measured_title_translated(self):
        from spa_core.telegram.humanize import humanize_title
        self.assertEqual(
            humanize_title("SPA — Cycle Gap Detected"), "Пропущен ежедневный цикл"
        )

    def test_unmeasured_title_translated(self):
        from spa_core.telegram.humanize import humanize_title
        out = humanize_title(cgm.UNMEASURED_ALERT_TITLE)
        self.assertNotEqual(out, cgm.UNMEASURED_ALERT_TITLE)
        self.assertTrue(any("Ѐ" <= ch <= "ӿ" for ch in out))


if __name__ == "__main__":
    unittest.main()
