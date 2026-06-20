"""
Tests for WeeklySummaryReport (MP-610).

python3 -m unittest spa_core.tests.test_weekly_summary_report -v
"""

import json
import os
import unittest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.analytics.weekly_summary_report import (
    WeeklySummaryReport,
    WeeklySummaryReportData,
    WeeklyStats,
    _compute_trend,
    _trend_arrow,
    _safe_float,
    _parse_timestamp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_iso(days_ago: int = 0) -> str:
    """Return an ISO UTC timestamp shifted by -days_ago days from now."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _make_day_entry(
    generated_at: str = "",
    overall_status: str = "OPERATIONAL",
    effective_apy: float = 5.0,
    best_chain: str = "ethereum",
    best_apy_overall: float = 12.0,
) -> dict:
    """Build a minimal daily ops report entry."""
    return {
        "generated_at": generated_at or _make_iso(),
        "overall_status": overall_status,
        "portfolio_summary": {
            "total_allocated_usd": 95000.0,
            "effective_apy": effective_apy,
            "daily_yield_usd": 13.0,
        },
        "chain_summary": {
            "best_chain": best_chain,
            "l2_adapters_count": 4,
        },
        "sections": [
            {
                "name": "chains",
                "status": "OK",
                "headline": f"Best chain: {best_chain} ({best_apy_overall:.1f}%)",
                "details": {
                    "best_chain": best_chain,
                    "best_apy_overall": best_apy_overall,
                    "total_adapters": 4,
                    "total_tvl_usd": 1_000_000_000.0,
                    "l2_premium_pct": None,
                },
                "data_source": "multi_chain_report.json",
                "data_fresh": True,
            }
        ],
    }


def _make_history_file(tmpdir: str, entries: list) -> str:
    """Write a daily_ops_report.json ring-buffer file and return its path."""
    data_dir = Path(tmpdir)
    payload = {
        "schema_version": 1,
        "source": "daily_operations_report",
        "ring_buffer_max": 30,
        "report_count": len(entries),
        "last_updated": entries[-1]["generated_at"] if entries else "",
        "latest": entries[-1] if entries else {},
        "history": entries,
    }
    path = data_dir / "daily_ops_report.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return str(data_dir)


# ===========================================================================
# TestWeeklyStats — 12 tests
# ===========================================================================

class TestWeeklyStats(unittest.TestCase):

    def setUp(self):
        self.reporter = WeeklySummaryReport.__new__(WeeklySummaryReport)

    def test_avg_computed_correctly(self):
        stats = self.reporter.compute_weekly_stats([5.0, 6.0, 7.0], "apy")
        self.assertAlmostEqual(stats.avg, 6.0)

    def test_min_computed_correctly(self):
        stats = self.reporter.compute_weekly_stats([3.0, 5.0, 7.0], "apy")
        self.assertAlmostEqual(stats.min, 3.0)

    def test_max_computed_correctly(self):
        stats = self.reporter.compute_weekly_stats([3.0, 5.0, 7.0], "apy")
        self.assertAlmostEqual(stats.max, 7.0)

    def test_trend_rising(self):
        stats = self.reporter.compute_weekly_stats([4.0, 4.5, 5.5], "apy")
        self.assertEqual(stats.trend, "RISING")

    def test_trend_falling(self):
        stats = self.reporter.compute_weekly_stats([6.0, 5.5, 4.5], "apy")
        self.assertEqual(stats.trend, "FALLING")

    def test_trend_stable(self):
        stats = self.reporter.compute_weekly_stats([5.0, 5.05, 5.09], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_rising_boundary_exact(self):
        # last = first + 0.1 is NOT strictly greater, so STABLE
        stats = self.reporter.compute_weekly_stats([5.0, 5.1], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_rising_boundary_above(self):
        # last = first + 0.11 → RISING
        stats = self.reporter.compute_weekly_stats([5.0, 5.11], "apy")
        self.assertEqual(stats.trend, "RISING")

    def test_trend_falling_boundary_exact(self):
        # last = first - 0.1 → STABLE (not strictly less)
        stats = self.reporter.compute_weekly_stats([5.1, 5.0], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_falling_boundary_below(self):
        # last = first - 0.11 → FALLING
        stats = self.reporter.compute_weekly_stats([5.11, 5.0], "apy")
        self.assertEqual(stats.trend, "FALLING")

    def test_empty_values_returns_zeros(self):
        stats = self.reporter.compute_weekly_stats([], "apy")
        self.assertAlmostEqual(stats.avg, 0.0)
        self.assertAlmostEqual(stats.min, 0.0)
        self.assertAlmostEqual(stats.max, 0.0)
        self.assertEqual(stats.trend, "STABLE")

    def test_single_value_stable(self):
        stats = self.reporter.compute_weekly_stats([5.5], "apy")
        self.assertAlmostEqual(stats.avg, 5.5)
        self.assertAlmostEqual(stats.min, 5.5)
        self.assertAlmostEqual(stats.max, 5.5)
        self.assertEqual(stats.trend, "STABLE")


# ===========================================================================
# TestWeeklySummaryReportData — 10 tests
# ===========================================================================

class TestWeeklySummaryReportData(unittest.TestCase):

    def setUp(self):
        self.reporter = WeeklySummaryReport.__new__(WeeklySummaryReport)

    def _make_stats(self, avg=5.0):
        return WeeklyStats(
            metric_name="effective_apy_pct",
            values=[avg],
            avg=avg,
            min=avg,
            max=avg,
            trend="STABLE",
        )

    def test_verdict_excellent(self):
        """avg APY > 6.0 and operational ≥ 5 → EXCELLENT"""
        verdict = self.reporter._determine_verdict(6.5, 5)
        self.assertEqual(verdict, "EXCELLENT")

    def test_verdict_excellent_requires_both_conditions(self):
        """avg APY > 6.0 but only 4 operational days → GOOD"""
        verdict = self.reporter._determine_verdict(6.5, 4)
        self.assertEqual(verdict, "GOOD")

    def test_verdict_good_by_apy(self):
        """avg APY > 5.0 → GOOD (regardless of operational days)"""
        verdict = self.reporter._determine_verdict(5.5, 2)
        self.assertEqual(verdict, "GOOD")

    def test_verdict_good_by_op_days(self):
        """≥ 4 operational days → GOOD (regardless of APY)"""
        verdict = self.reporter._determine_verdict(4.5, 4)
        self.assertEqual(verdict, "GOOD")

    def test_verdict_fair(self):
        """avg APY > 4.0 and < 5.0 and < 4 operational → FAIR"""
        verdict = self.reporter._determine_verdict(4.5, 3)
        self.assertEqual(verdict, "FAIR")

    def test_verdict_poor(self):
        """avg APY ≤ 4.0 and < 4 operational → POOR"""
        verdict = self.reporter._determine_verdict(3.0, 2)
        self.assertEqual(verdict, "POOR")

    def test_verdict_poor_zero_apy(self):
        verdict = self.reporter._determine_verdict(0.0, 0)
        self.assertEqual(verdict, "POOR")

    def test_summary_line_format(self):
        """summary_line contains avg, range, and operational count"""
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(6), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(5), "OPERATIONAL", 5.1),
                _make_day_entry(_make_iso(4), "OPERATIONAL", 5.2),
                _make_day_entry(_make_iso(3), "OPERATIONAL", 5.3),
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.4),
                _make_day_entry(_make_iso(1), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 5.2),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertIn("APY avg", report.summary_line)
        self.assertIn("operational", report.summary_line)

    def test_summary_line_contains_fraction(self):
        """summary_line shows X/Y operational format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(3), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(2), "DEGRADED", 5.1),
                _make_day_entry(_make_iso(1), "OPERATIONAL", 5.2),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertIn("/3 operational", report.summary_line)

    def test_summary_line_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertIn("no data", report.summary_line)


# ===========================================================================
# TestLoadDailyHistory — 8 tests
# ===========================================================================

class TestLoadDailyHistory(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            result = reporter.load_daily_history()
        self.assertEqual(result, [])

    def test_empty_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily_ops_report.json"
            path.write_text("", encoding="utf-8")
            reporter = WeeklySummaryReport(data_path=tmpdir)
            result = reporter.load_daily_history()
        self.assertEqual(result, [])

    def test_non_dict_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily_ops_report.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            reporter = WeeklySummaryReport(data_path=tmpdir)
            result = reporter.load_daily_history()
        self.assertEqual(result, [])

    def test_dict_without_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "daily_ops_report.json"
            path.write_text('{"schema_version": 1}', encoding="utf-8")
            reporter = WeeklySummaryReport(data_path=tmpdir)
            result = reporter.load_daily_history()
        self.assertEqual(result, [])

    def test_valid_history_returns_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1)), _make_day_entry(_make_iso(0))]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.load_daily_history()
        self.assertEqual(len(result), 2)

    def test_non_dict_entries_filtered_out(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "schema_version": 1,
                "history": [
                    _make_day_entry(_make_iso(1)),
                    "not a dict",
                    42,
                    _make_day_entry(_make_iso(0)),
                ],
            }
            path = Path(tmpdir) / "daily_ops_report.json"
            with open(path, "w") as fh:
                json.dump(payload, fh)
            reporter = WeeklySummaryReport(data_path=tmpdir)
            result = reporter.load_daily_history()
        self.assertEqual(len(result), 2)

    def test_multiple_entries_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(i)) for i in range(5, 0, -1)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.load_daily_history()
        self.assertEqual(len(result), 5)

    def test_history_is_list_of_dicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(2)), _make_day_entry(_make_iso(1))]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.load_daily_history()
        for item in result:
            self.assertIsInstance(item, dict)


# ===========================================================================
# TestGetLast7Days — 10 tests
# ===========================================================================

class TestGetLast7Days(unittest.TestCase):

    def setUp(self):
        self.reporter = WeeklySummaryReport.__new__(WeeklySummaryReport)

    def test_empty_history_returns_empty(self):
        result = self.reporter.get_last_7_days([])
        self.assertEqual(result, [])

    def test_less_than_7_returns_all(self):
        entries = [_make_day_entry(_make_iso(i)) for i in range(3, 0, -1)]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 3)

    def test_exactly_7_returns_all(self):
        entries = [_make_day_entry(_make_iso(i)) for i in range(7, 0, -1)]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 7)

    def test_more_than_7_returns_last_7(self):
        entries = [_make_day_entry(_make_iso(i)) for i in range(10, 0, -1)]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 7)

    def test_sorted_ascending_by_generated_at(self):
        # Provide in random order, expect sorted ascending
        ts_list = [_make_iso(i) for i in range(5, 0, -1)]
        entries = [_make_day_entry(ts) for ts in ts_list]
        # Shuffle
        import random
        random.shuffle(entries)
        result = self.reporter.get_last_7_days(entries)
        timestamps = [r["generated_at"] for r in result]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_result_is_newest_7(self):
        """With 10 entries, result should contain the 7 most recent."""
        entries = [_make_day_entry(_make_iso(i)) for i in range(10, 0, -1)]
        result = self.reporter.get_last_7_days(entries)
        # The newest is days_ago=1, oldest is days_ago=7
        newest_in_result = result[-1]["generated_at"]
        newest_overall = max(e["generated_at"] for e in entries)
        self.assertEqual(newest_in_result, newest_overall)

    def test_single_entry_returns_list_of_one(self):
        entries = [_make_day_entry(_make_iso(0))]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 1)

    def test_missing_generated_at_handled(self):
        """Entries without generated_at should not crash."""
        entries = [
            {"overall_status": "OPERATIONAL"},
            _make_day_entry(_make_iso(1)),
        ]
        result = self.reporter.get_last_7_days(entries)
        self.assertIsInstance(result, list)

    def test_all_same_timestamp_returns_up_to_7(self):
        ts = _make_iso(0)
        entries = [_make_day_entry(ts) for _ in range(5)]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 5)

    def test_14_entries_returns_exactly_7(self):
        entries = [_make_day_entry(_make_iso(i)) for i in range(14, 0, -1)]
        result = self.reporter.get_last_7_days(entries)
        self.assertEqual(len(result), 7)


# ===========================================================================
# TestComputeWeeklyStats — 12 tests
# ===========================================================================

class TestComputeWeeklyStats(unittest.TestCase):

    def setUp(self):
        self.reporter = WeeklySummaryReport.__new__(WeeklySummaryReport)

    def test_avg_single_value(self):
        stats = self.reporter.compute_weekly_stats([4.2], "x")
        self.assertAlmostEqual(stats.avg, 4.2)

    def test_avg_multiple_values(self):
        stats = self.reporter.compute_weekly_stats([1.0, 2.0, 3.0, 4.0], "x")
        self.assertAlmostEqual(stats.avg, 2.5)

    def test_min_value(self):
        stats = self.reporter.compute_weekly_stats([7.0, 3.0, 5.0], "x")
        self.assertAlmostEqual(stats.min, 3.0)

    def test_max_value(self):
        stats = self.reporter.compute_weekly_stats([7.0, 3.0, 5.0], "x")
        self.assertAlmostEqual(stats.max, 7.0)

    def test_trend_rising_by_more_than_01(self):
        stats = self.reporter.compute_weekly_stats([4.0, 5.0], "x")
        self.assertEqual(stats.trend, "RISING")

    def test_trend_falling_by_more_than_01(self):
        stats = self.reporter.compute_weekly_stats([5.0, 4.0], "x")
        self.assertEqual(stats.trend, "FALLING")

    def test_trend_stable_within_01(self):
        stats = self.reporter.compute_weekly_stats([5.0, 5.05], "x")
        self.assertEqual(stats.trend, "STABLE")

    def test_metric_name_preserved(self):
        stats = self.reporter.compute_weekly_stats([5.0], "effective_apy_pct")
        self.assertEqual(stats.metric_name, "effective_apy_pct")

    def test_values_list_preserved(self):
        values = [4.5, 5.0, 5.5]
        stats = self.reporter.compute_weekly_stats(values, "x")
        self.assertEqual(stats.values, values)

    def test_empty_returns_stable_trend(self):
        stats = self.reporter.compute_weekly_stats([], "x")
        self.assertEqual(stats.trend, "STABLE")

    def test_empty_returns_zero_avg(self):
        stats = self.reporter.compute_weekly_stats([], "x")
        self.assertAlmostEqual(stats.avg, 0.0)

    def test_returns_weekystats_type(self):
        stats = self.reporter.compute_weekly_stats([5.0], "x")
        self.assertIsInstance(stats, WeeklyStats)


# ===========================================================================
# TestGenerateReport — 18 tests
# ===========================================================================

class TestGenerateReport(unittest.TestCase):

    def test_no_history_returns_poor_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertEqual(report.weekly_verdict, "POOR")

    def test_no_history_returns_zero_days_covered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertEqual(report.days_covered, 0)

    def test_no_history_returns_zero_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.apy_stats.avg, 0.0)

    def test_7_days_all_operational(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(i), "OPERATIONAL", 5.5) for i in range(7, 0, -1)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.days_covered, 7)
        self.assertEqual(report.operational_days, 7)

    def test_operational_days_counted_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(3), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(2), "DEGRADED", 4.5),
                _make_day_entry(_make_iso(1), "CRITICAL", 3.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 5.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.operational_days, 2)

    def test_degraded_days_counted_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(1), "DEGRADED", 4.5),
                _make_day_entry(_make_iso(0), "DEGRADED", 4.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.degraded_days, 2)

    def test_critical_days_counted_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(1), "CRITICAL", 3.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 5.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.critical_days, 1)

    def test_best_day_apy_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(1), "OPERATIONAL", 6.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 4.5),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.best_day_apy, 6.0)

    def test_worst_day_apy_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.0),
                _make_day_entry(_make_iso(1), "OPERATIONAL", 6.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 4.5),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.worst_day_apy, 4.5)

    def test_top_chain_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.0, "ethereum", 12.0),
                _make_day_entry(_make_iso(1), "OPERATIONAL", 5.0, "ethereum", 12.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 5.0, "arbitrum", 8.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.top_chain_this_week, "ethereum")

    def test_top_chain_apy_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(1), "OPERATIONAL", 5.0, "ethereum", 12.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 5.0, "ethereum", 12.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.top_chain_apy, 12.0)

    def test_week_start_is_oldest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            t1 = _make_iso(3)
            t2 = _make_iso(0)
            entries = [_make_day_entry(t1), _make_day_entry(t2)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.week_start, t1)

    def test_week_end_is_newest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            t1 = _make_iso(3)
            t2 = _make_iso(0)
            entries = [_make_day_entry(t1), _make_day_entry(t2)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.week_end, t2)

    def test_excellent_verdict_when_conditions_met(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(i), "OPERATIONAL", 7.0) for i in range(7, 0, -1)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.weekly_verdict, "EXCELLENT")

    def test_good_verdict_by_apy(self):
        """avg APY > 5.0 but only 2 operational days → GOOD (by apy)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "OPERATIONAL", 5.5),
                _make_day_entry(_make_iso(1), "DEGRADED", 5.5),
                _make_day_entry(_make_iso(0), "DEGRADED", 5.5),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.weekly_verdict, "GOOD")

    def test_fair_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(2), "DEGRADED", 4.5),
                _make_day_entry(_make_iso(1), "DEGRADED", 4.5),
                _make_day_entry(_make_iso(0), "DEGRADED", 4.5),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertEqual(report.weekly_verdict, "FAIR")

    def test_apy_avg_computed_from_portfolio_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_day_entry(_make_iso(1), "OPERATIONAL", 4.0),
                _make_day_entry(_make_iso(0), "OPERATIONAL", 6.0),
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.apy_stats.avg, 5.0)

    def test_return_type_is_weekly_summary_report_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertIsInstance(report, WeeklySummaryReportData)


# ===========================================================================
# TestSaveReport — 5 tests
# ===========================================================================

class TestSaveReport(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            path = reporter.save_report()
            self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            reporter.save_report()
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_max_12(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            # Save 15 times
            for _ in range(15):
                reporter._report = None  # reset to regenerate
                reporter.save_report()
            out_path = Path(tmpdir) / "weekly_summary.json"
            with open(out_path) as fh:
                data = json.load(fh)
        self.assertLessEqual(len(data["history"]), 12)

    def test_atomic_write_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        self.assertIn("history", data)

    def test_second_save_appends_to_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            reporter.save_report()
            reporter._report = None
            reporter.save_report()
            out_path = Path(tmpdir) / "weekly_summary.json"
            with open(out_path) as fh:
                data = json.load(fh)
        self.assertEqual(data["report_count"], 2)


# ===========================================================================
# TestFormatTelegramMessage — 6 tests
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):

    def _make_report_with_days(self, tmpdir, apy=5.5, op_days=7):
        statuses = ["OPERATIONAL"] * op_days + ["DEGRADED"] * (7 - op_days)
        entries = [
            _make_day_entry(_make_iso(7 - i), statuses[i], apy)
            for i in range(7)
        ]
        data_path = _make_history_file(tmpdir, entries)
        reporter = WeeklySummaryReport(data_path=data_path)
        return reporter

    def test_message_length_le_1500(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._make_report_with_days(tmpdir, 5.5, 7)
            msg = reporter.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_message_contains_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(i), "OPERATIONAL", 7.0) for i in range(7, 0, -1)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            msg = reporter.format_telegram_message()
        self.assertIn("EXCELLENT", msg)

    def test_message_contains_avg_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._make_report_with_days(tmpdir, 5.5, 7)
            msg = reporter.format_telegram_message()
        self.assertIn("5.50", msg)

    def test_message_truncated_with_ellipsis(self):
        """Build a message that would exceed 1500 chars and confirm truncation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a chain name that is very long
            entries = [
                _make_day_entry(_make_iso(i), "OPERATIONAL", 5.0, "a" * 500, 12.0)
                for i in range(7, 0, -1)
            ]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            msg = reporter.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_message_contains_weekly_summary_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._make_report_with_days(tmpdir, 5.5, 7)
            msg = reporter.format_telegram_message()
        self.assertIn("Weekly Summary", msg)

    def test_message_no_data_still_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = WeeklySummaryReport(data_path=tmpdir)
            msg = reporter.format_telegram_message()
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)


# ===========================================================================
# TestToDict — 4 tests
# ===========================================================================

class TestToDict(unittest.TestCase):

    def test_to_dict_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.to_dict()
        self.assertIsInstance(result, dict)

    def test_to_dict_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.to_dict()
            serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    def test_to_dict_contains_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.to_dict()
        required_keys = [
            "generated_at", "week_start", "week_end", "days_covered",
            "apy_stats", "operational_days", "degraded_days", "critical_days",
            "best_day_apy", "worst_day_apy", "top_chain_this_week", "top_chain_apy",
            "weekly_verdict", "summary_line",
        ]
        for key in required_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_to_dict_apy_stats_is_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_day_entry(_make_iso(1), "OPERATIONAL", 5.0)]
            data_path = _make_history_file(tmpdir, entries)
            reporter = WeeklySummaryReport(data_path=data_path)
            result = reporter.to_dict()
        self.assertIsInstance(result["apy_stats"], dict)
        for key in ("metric_name", "values", "avg", "min", "max", "trend"):
            self.assertIn(key, result["apy_stats"], f"Missing apy_stats key: {key}")


# ===========================================================================
# Additional helper function tests
# ===========================================================================

class TestHelpers(unittest.TestCase):

    # _safe_float
    def test_safe_float_bool_returns_zero(self):
        self.assertAlmostEqual(_safe_float(True), 0.0)
        self.assertAlmostEqual(_safe_float(False), 0.0)

    def test_safe_float_string_number(self):
        self.assertAlmostEqual(_safe_float("5.5"), 5.5)

    def test_safe_float_none_returns_zero(self):
        self.assertAlmostEqual(_safe_float(None), 0.0)

    def test_safe_float_valid_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    # _parse_timestamp
    def test_parse_timestamp_z_suffix(self):
        ts = "2026-06-13T08:00:00Z"
        dt = _parse_timestamp(ts)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_timestamp_iso_with_offset(self):
        ts = "2026-06-13T08:00:00+00:00"
        dt = _parse_timestamp(ts)
        self.assertIsNotNone(dt)

    def test_parse_timestamp_invalid_returns_none(self):
        dt = _parse_timestamp("not-a-date")
        self.assertIsNone(dt)

    # _compute_trend
    def test_compute_trend_single_value(self):
        trend = _compute_trend([5.0])
        self.assertEqual(trend, "STABLE")

    def test_compute_trend_empty(self):
        trend = _compute_trend([])
        self.assertEqual(trend, "STABLE")

    # _trend_arrow
    def test_trend_arrow_rising(self):
        self.assertIn("↗", _trend_arrow("RISING"))

    def test_trend_arrow_falling(self):
        self.assertIn("↘", _trend_arrow("FALLING"))

    def test_trend_arrow_stable(self):
        arrow = _trend_arrow("STABLE")
        self.assertIsInstance(arrow, str)


if __name__ == "__main__":
    unittest.main()
