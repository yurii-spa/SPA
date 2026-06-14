"""Tests for DataFeedHealthScoreboard (MP-623).

Pure-stdlib unittest suite.  Uses tempfile.TemporaryDirectory for all I/O so
production data/ is never touched, and injects ``now`` to control staleness.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.analytics.data_feed_health_scoreboard import (
    CHECK_REGISTRY,
    CRITICAL_THRESHOLD,
    DEGRADED_THRESHOLD,
    STALENESS_HOURS,
    CheckStatus,
    DataFeedHealthScoreboard,
    ScoreboardReport,
    _parse_timestamp,
    _safe_float,
    _safe_int,
)

# A fixed "now" for deterministic staleness.
NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _fresh_ts() -> str:
    """Timestamp 1h before NOW -> not stale."""
    return (NOW - timedelta(hours=1)).isoformat()


def _stale_ts() -> str:
    """Timestamp 48h before NOW -> stale."""
    return (NOW - timedelta(hours=48)).isoformat()


def _write_state(data_dir: Path, filename: str, payload) -> None:
    (data_dir / filename).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_full_registry(data_dir: Path, consecutive: int = 0,
                         ts: str = None) -> None:
    """Write all 8 registry files with the given counter and timestamp."""
    if ts is None:
        ts = _fresh_ts()
    for entry in CHECK_REGISTRY:
        _write_state(
            data_dir,
            entry["filename"],
            {
                entry["counter_key"]: consecutive,
                "last_alerted_cycle": 0,
                "updated_at": ts,
            },
        )


# ===========================================================================
# Helpers
# ===========================================================================


class TestSafeHelpers(unittest.TestCase):
    def test_safe_int_basic(self):
        self.assertEqual(_safe_int(5), 5)
        self.assertEqual(_safe_int(0), 0)
        self.assertEqual(_safe_int(3.9), 3)

    def test_safe_int_bool_is_zero(self):
        self.assertEqual(_safe_int(True), 0)
        self.assertEqual(_safe_int(False), 0)

    def test_safe_int_none(self):
        self.assertEqual(_safe_int(None), 0)

    def test_safe_int_string_numeric(self):
        self.assertEqual(_safe_int("7"), 7)
        self.assertEqual(_safe_int("7.5"), 7)

    def test_safe_int_string_garbage(self):
        self.assertEqual(_safe_int("abc"), 0)
        self.assertEqual(_safe_int(""), 0)

    def test_safe_int_nan_inf(self):
        self.assertEqual(_safe_int(float("nan")), 0)
        self.assertEqual(_safe_int(float("inf")), 0)
        self.assertEqual(_safe_int(float("-inf")), 0)

    def test_safe_int_list_dict(self):
        self.assertEqual(_safe_int([1, 2]), 0)
        self.assertEqual(_safe_int({"a": 1}), 0)

    def test_safe_int_negative(self):
        self.assertEqual(_safe_int(-3), -3)

    def test_safe_float_basic(self):
        self.assertEqual(_safe_float(2.5), 2.5)
        self.assertEqual(_safe_float(0), 0.0)
        self.assertEqual(_safe_float(4), 4.0)

    def test_safe_float_bool_is_zero(self):
        self.assertEqual(_safe_float(True), 0.0)
        self.assertEqual(_safe_float(False), 0.0)

    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_safe_float_string_numeric(self):
        self.assertEqual(_safe_float("3.14"), 3.14)

    def test_safe_float_string_garbage(self):
        self.assertEqual(_safe_float("xyz"), 0.0)

    def test_safe_float_nan_inf(self):
        self.assertEqual(_safe_float(float("nan")), 0.0)
        self.assertEqual(_safe_float(float("inf")), 0.0)
        self.assertEqual(_safe_float(float("-inf")), 0.0)

    def test_safe_float_returns_float_type(self):
        self.assertIsInstance(_safe_float(3), float)


class TestParseTimestamp(unittest.TestCase):
    def test_parse_with_z(self):
        dt = _parse_timestamp("2026-06-10T08:57:04Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.year, 2026)

    def test_parse_with_offset(self):
        dt = _parse_timestamp("2026-06-10T08:57:04+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_with_nonzero_offset(self):
        dt = _parse_timestamp("2026-06-10T11:57:04+03:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 8)  # normalised to UTC

    def test_parse_naive_assumed_utc(self):
        dt = _parse_timestamp("2026-06-10T08:57:04")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_invalid(self):
        self.assertIsNone(_parse_timestamp("not-a-date"))

    def test_parse_none(self):
        self.assertIsNone(_parse_timestamp(None))

    def test_parse_empty(self):
        self.assertIsNone(_parse_timestamp(""))

    def test_parse_non_string(self):
        self.assertIsNone(_parse_timestamp(12345))
        self.assertIsNone(_parse_timestamp([]))


# ===========================================================================
# Classify
# ===========================================================================


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.cls = DataFeedHealthScoreboard._classify

    def test_zero_healthy(self):
        self.assertEqual(self.cls(0, False), "HEALTHY")

    def test_one_degraded(self):
        self.assertEqual(self.cls(1, False), "DEGRADED")

    def test_two_degraded(self):
        self.assertEqual(self.cls(2, False), "DEGRADED")

    def test_three_critical(self):
        self.assertEqual(self.cls(3, False), "CRITICAL")

    def test_four_critical(self):
        self.assertEqual(self.cls(4, False), "CRITICAL")

    def test_large_critical(self):
        self.assertEqual(self.cls(99, False), "CRITICAL")

    def test_stale_promotes_healthy_to_degraded(self):
        self.assertEqual(self.cls(0, True), "DEGRADED")

    def test_stale_does_not_downgrade_critical(self):
        self.assertEqual(self.cls(5, True), "CRITICAL")

    def test_stale_keeps_degraded(self):
        self.assertEqual(self.cls(1, True), "DEGRADED")

    def test_boundary_degraded_threshold(self):
        self.assertEqual(self.cls(DEGRADED_THRESHOLD, False), "DEGRADED")

    def test_boundary_critical_threshold(self):
        self.assertEqual(self.cls(CRITICAL_THRESHOLD, False), "CRITICAL")

    def test_just_below_critical(self):
        self.assertEqual(self.cls(CRITICAL_THRESHOLD - 1, False), "DEGRADED")


# ===========================================================================
# CheckStatus dataclass
# ===========================================================================


class TestCheckStatus(unittest.TestCase):
    def _make(self, **kw):
        base = dict(
            check_name="feed_freshness",
            filename="apy_feed_health_state.json",
            consecutive_count=2,
            last_alerted_cycle=1,
            updated_at="2026-06-10T08:57:04Z",
            age_hours=3.5,
            is_stale=False,
            status="DEGRADED",
            note="x",
        )
        base.update(kw)
        return CheckStatus(**base)

    def test_fields(self):
        c = self._make()
        self.assertEqual(c.check_name, "feed_freshness")
        self.assertEqual(c.consecutive_count, 2)
        self.assertEqual(c.status, "DEGRADED")

    def test_to_dict_keys(self):
        c = self._make()
        d = c.to_dict()
        for k in ("check_name", "filename", "consecutive_count",
                  "last_alerted_cycle", "updated_at", "age_hours",
                  "is_stale", "status", "note"):
            self.assertIn(k, d)

    def test_to_dict_json_serializable(self):
        c = self._make()
        json.dumps(c.to_dict())  # must not raise

    def test_to_dict_age_none(self):
        c = self._make(age_hours=None)
        self.assertIsNone(c.to_dict()["age_hours"])

    def test_to_dict_age_rounded(self):
        c = self._make(age_hours=3.123456789)
        self.assertEqual(c.to_dict()["age_hours"], 3.1235)


# ===========================================================================
# ScoreboardReport dataclass
# ===========================================================================


class TestScoreboardReport(unittest.TestCase):
    def _make(self, checks=None):
        if checks is None:
            checks = []
        return ScoreboardReport(
            generated_at="2026-06-13T12:00:00+00:00",
            checks_total=len(checks),
            healthy_count=sum(1 for c in checks if c.status == "HEALTHY"),
            degraded_count=sum(1 for c in checks if c.status == "DEGRADED"),
            critical_count=sum(1 for c in checks if c.status == "CRITICAL"),
            stale_count=0,
            overall_status="HEALTHY",
            worst_check="",
            health_score=1.0,
            checks=checks,
            summary="x",
        )

    def test_fields(self):
        r = self._make()
        self.assertEqual(r.overall_status, "HEALTHY")
        self.assertEqual(r.health_score, 1.0)

    def test_to_dict_keys(self):
        r = self._make()
        d = r.to_dict()
        for k in ("generated_at", "checks_total", "healthy_count",
                  "degraded_count", "critical_count", "stale_count",
                  "overall_status", "worst_check", "health_score",
                  "checks", "summary"):
            self.assertIn(k, d)

    def test_to_dict_checks_are_dicts(self):
        c = CheckStatus(
            check_name="anomaly", filename="f.json", consecutive_count=0,
            last_alerted_cycle=0, updated_at=None, age_hours=None,
            is_stale=False, status="HEALTHY", note="",
        )
        r = self._make(checks=[c])
        d = r.to_dict()
        self.assertIsInstance(d["checks"], list)
        self.assertIsInstance(d["checks"][0], dict)

    def test_to_dict_json_serializable(self):
        r = self._make()
        json.dumps(r.to_dict())

    def test_health_score_rounded(self):
        r = self._make()
        r.health_score = 0.333333333
        self.assertEqual(r.to_dict()["health_score"], 0.3333)


# ===========================================================================
# load_check
# ===========================================================================


class TestLoadCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.board = DataFeedHealthScoreboard(
            data_path=str(self.data_dir), now=NOW
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file(self):
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.consecutive_count, 0)
        self.assertIn("missing", c.note)
        self.assertEqual(c.status, "HEALTHY")

    def test_corrupt_json(self):
        (self.data_dir / "apy_feed_health_state.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.consecutive_count, 0)
        self.assertIn("unreadable", c.note)

    def test_non_dict_json(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", [1, 2, 3])
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.consecutive_count, 0)
        self.assertIn("not a JSON object", c.note)

    def test_valid_counter_extracted(self):
        _write_state(self.data_dir, "apy_feed_anomaly_health_state.json", {
            "consecutive_anomalies": 2,
            "last_alerted_cycle": 5,
            "updated_at": _fresh_ts(),
        })
        c = self.board.load_check("anomaly",
                                  "apy_feed_anomaly_health_state.json",
                                  "consecutive_anomalies")
        self.assertEqual(c.consecutive_count, 2)
        self.assertEqual(c.last_alerted_cycle, 5)
        self.assertEqual(c.status, "DEGRADED")

    def test_wrong_counter_key_yields_zero(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 4,
            "updated_at": _fresh_ts(),
        })
        # Asking for a key not present
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "nonexistent_key")
        self.assertEqual(c.consecutive_count, 0)

    def test_fresh_not_stale(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0,
            "updated_at": _fresh_ts(),
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertFalse(c.is_stale)
        self.assertEqual(c.status, "HEALTHY")

    def test_old_is_stale(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0,
            "updated_at": _stale_ts(),
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertTrue(c.is_stale)
        self.assertEqual(c.status, "DEGRADED")
        self.assertIsNotNone(c.age_hours)
        self.assertGreater(c.age_hours, STALENESS_HOURS)

    def test_z_suffix_parsed(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0,
            "updated_at": "2026-06-10T08:57:04Z",
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.updated_at, "2026-06-10T08:57:04Z")
        self.assertIsNotNone(c.age_hours)

    def test_missing_updated_at(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0,
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertIsNone(c.updated_at)
        self.assertFalse(c.is_stale)
        self.assertIsNone(c.age_hours)
        self.assertIn("no updated_at", c.note)

    def test_unparseable_updated_at(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0,
            "updated_at": "garbage",
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertIsNone(c.updated_at)
        self.assertFalse(c.is_stale)
        self.assertIn("unparseable", c.note)

    def test_bool_counter_is_zero(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": True,
            "updated_at": _fresh_ts(),
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.consecutive_count, 0)

    def test_critical_counter(self):
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 5,
            "updated_at": _fresh_ts(),
        })
        c = self.board.load_check("feed_freshness",
                                  "apy_feed_health_state.json",
                                  "consecutive_stale")
        self.assertEqual(c.status, "CRITICAL")


# ===========================================================================
# generate_report
# ===========================================================================


class TestGenerateReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _board(self):
        return DataFeedHealthScoreboard(data_path=str(self.data_dir), now=NOW)

    def test_all_healthy(self):
        _write_full_registry(self.data_dir, consecutive=0)
        r = self._board().generate_report()
        self.assertEqual(r.overall_status, "HEALTHY")
        self.assertEqual(r.health_score, 1.0)
        self.assertEqual(r.worst_check, "")
        self.assertEqual(r.healthy_count, 8)
        self.assertEqual(r.critical_count, 0)

    def test_checks_total_is_eight(self):
        _write_full_registry(self.data_dir, consecutive=0)
        r = self._board().generate_report()
        self.assertEqual(r.checks_total, 8)
        self.assertEqual(len(r.checks), 8)

    def test_one_critical(self):
        _write_full_registry(self.data_dir, consecutive=0)
        # bump one file to critical
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 4,
            "updated_at": _fresh_ts(),
        })
        r = self._board().generate_report()
        self.assertEqual(r.overall_status, "CRITICAL")
        self.assertEqual(r.critical_count, 1)
        self.assertEqual(r.worst_check, "tvl_drop")

    def test_mixed_degraded(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_anomaly_health_state.json", {
            "consecutive_anomalies": 1,
            "updated_at": _fresh_ts(),
        })
        r = self._board().generate_report()
        self.assertEqual(r.overall_status, "DEGRADED")
        self.assertEqual(r.degraded_count, 1)
        self.assertEqual(r.critical_count, 0)

    def test_counts_consistent(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 5, "updated_at": _fresh_ts(),
        })
        _write_state(self.data_dir, "apy_feed_anomaly_health_state.json", {
            "consecutive_anomalies": 1, "updated_at": _fresh_ts(),
        })
        r = self._board().generate_report()
        self.assertEqual(
            r.healthy_count + r.degraded_count + r.critical_count,
            r.checks_total,
        )

    def test_worst_check_max_consecutive(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 2, "updated_at": _fresh_ts(),
        })
        _write_state(self.data_dir, "apy_feed_anomaly_health_state.json", {
            "consecutive_anomalies": 7, "updated_at": _fresh_ts(),
        })
        r = self._board().generate_report()
        self.assertEqual(r.worst_check, "anomaly")

    def test_worst_check_tie_first_by_registry(self):
        _write_full_registry(self.data_dir, consecutive=0)
        # feed_freshness is first in registry; both = 3
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 3, "updated_at": _fresh_ts(),
        })
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 3, "updated_at": _fresh_ts(),
        })
        r = self._board().generate_report()
        self.assertEqual(r.worst_check, "feed_freshness")

    def test_stale_count(self):
        _write_full_registry(self.data_dir, consecutive=0, ts=_stale_ts())
        r = self._board().generate_report()
        self.assertEqual(r.stale_count, 8)
        self.assertEqual(r.overall_status, "DEGRADED")

    def test_all_missing_files(self):
        # No files written -> all consecutive=0, no timestamps -> HEALTHY
        r = self._board().generate_report()
        self.assertEqual(r.checks_total, 8)
        self.assertEqual(r.overall_status, "HEALTHY")
        self.assertEqual(r.health_score, 1.0)

    def test_summary_format(self):
        _write_full_registry(self.data_dir, consecutive=0)
        r = self._board().generate_report()
        self.assertIn("Feeds:", r.summary)
        self.assertIn("overall=HEALTHY", r.summary)

    def test_generated_at_uses_injected_now(self):
        _write_full_registry(self.data_dir, consecutive=0)
        r = self._board().generate_report()
        self.assertTrue(r.generated_at.startswith("2026-06-13T12:00:00"))


# ===========================================================================
# save_report
# ===========================================================================


class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        _write_full_registry(self.data_dir, consecutive=0)
        self.board = DataFeedHealthScoreboard(
            data_path=str(self.data_dir), now=NOW
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_file(self):
        path = self.board.save_report()
        self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        self.board.save_report()
        leftovers = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_valid_json_structure(self):
        path = self.board.save_report()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["source"], "data_feed_health_scoreboard")
        self.assertIn("latest", data)
        self.assertIn("history", data)
        self.assertIn("last_updated", data)

    def test_latest_is_report_dict(self):
        path = self.board.save_report()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertIn("overall_status", data["latest"])
        self.assertIn("checks", data["latest"])

    def test_append_history(self):
        self.board.save_report()
        self.board.save_report()
        path = self.data_dir / "data_feed_health_scoreboard.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["history"]), 2)

    def test_ring_buffer_capped(self):
        for _ in range(50):
            self.board.save_report()
        path = self.data_dir / "data_feed_health_scoreboard.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertLessEqual(len(data["history"]), 48)
        self.assertEqual(len(data["history"]), 48)

    def test_returns_path(self):
        path = self.board.save_report()
        self.assertTrue(str(path).endswith("data_feed_health_scoreboard.json"))


# ===========================================================================
# format_telegram_message
# ===========================================================================


class TestFormatTelegram(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _board(self):
        return DataFeedHealthScoreboard(data_path=str(self.data_dir), now=NOW)

    def test_length_cap(self):
        _write_full_registry(self.data_dir, consecutive=5)
        msg = self._board().format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_title(self):
        _write_full_registry(self.data_dir, consecutive=0)
        msg = self._board().format_telegram_message()
        self.assertIn("Data Feed Health", msg)

    def test_healthy_shows_checkmark(self):
        _write_full_registry(self.data_dir, consecutive=0)
        msg = self._board().format_telegram_message()
        self.assertIn("✅", msg)
        self.assertIn("All feeds healthy", msg)

    def test_critical_shows_red(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 5, "updated_at": _fresh_ts(),
        })
        msg = self._board().format_telegram_message()
        self.assertIn("🔴", msg)

    def test_degraded_shows_yellow(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_anomaly_health_state.json", {
            "consecutive_anomalies": 1, "updated_at": _fresh_ts(),
        })
        msg = self._board().format_telegram_message()
        self.assertIn("🟡", msg)

    def test_overall_in_header(self):
        _write_full_registry(self.data_dir, consecutive=0)
        msg = self._board().format_telegram_message()
        self.assertIn("HEALTHY", msg)


# ===========================================================================
# to_dict
# ===========================================================================


class TestToDict(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        _write_full_registry(self.data_dir, consecutive=0)
        self.board = DataFeedHealthScoreboard(
            data_path=str(self.data_dir), now=NOW
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_serializable(self):
        json.dumps(self.board.to_dict())

    def test_required_keys(self):
        d = self.board.to_dict()
        for k in ("generated_at", "checks_total", "overall_status",
                  "health_score", "checks", "summary", "worst_check"):
            self.assertIn(k, d)

    def test_checks_is_list_of_dict(self):
        d = self.board.to_dict()
        self.assertEqual(len(d["checks"]), 8)
        for c in d["checks"]:
            self.assertIsInstance(c, dict)


# ===========================================================================
# Integration
# ===========================================================================


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_end_to_end_healthy(self):
        _write_full_registry(self.data_dir, consecutive=0)
        board = DataFeedHealthScoreboard(data_path=str(self.data_dir), now=NOW)
        report = board.generate_report()
        path = board.save_report(report)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["latest"]["overall_status"], "HEALTHY")
        self.assertEqual(data["latest"]["checks_total"], 8)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_end_to_end_mixed(self):
        _write_full_registry(self.data_dir, consecutive=0)
        _write_state(self.data_dir, "apy_feed_tvl_health_state.json", {
            "consecutive_drops": 4, "updated_at": _fresh_ts(),
        })
        _write_state(self.data_dir, "apy_feed_bounds_health_state.json", {
            "consecutive_bounds": 2, "updated_at": _stale_ts(),
        })
        board = DataFeedHealthScoreboard(data_path=str(self.data_dir), now=NOW)
        report = board.generate_report()
        self.assertEqual(report.overall_status, "CRITICAL")
        self.assertGreaterEqual(report.degraded_count, 1)
        self.assertGreaterEqual(report.stale_count, 1)
        path = board.save_report(report)
        self.assertTrue(os.path.exists(path))

    def test_real_data_smoke(self):
        # Smoke against a hand-built realistic registry matching prod shapes.
        _write_state(self.data_dir, "apy_feed_health_state.json", {
            "consecutive_stale": 0, "last_alerted_cycle": 0,
            "updated_at": "2026-06-10T08:57:04Z",
        })
        for entry in CHECK_REGISTRY[1:]:
            _write_state(self.data_dir, entry["filename"], {
                entry["counter_key"]: 1, "last_alerted_cycle": 1,
                "updated_at": "2026-06-10T08:57:04Z",
            })
        board = DataFeedHealthScoreboard(data_path=str(self.data_dir), now=NOW)
        report = board.generate_report()
        # old timestamps -> stale -> at least DEGRADED overall
        self.assertIn(report.overall_status, ("DEGRADED", "CRITICAL"))


if __name__ == "__main__":
    unittest.main()
