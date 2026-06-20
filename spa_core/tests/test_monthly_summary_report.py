"""
Tests for MonthlySummaryReport (MP-614).

python3 -m unittest spa_core.tests.test_monthly_summary_report -v
"""

import json
import os
import random
import unittest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.analytics.monthly_summary_report import (
    MonthlySummaryReport,
    MonthlySummaryReportData,
    MonthlyStats,
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


def _make_week_entry(
    generated_at: str = "",
    week_start: str = "",
    week_end: str = "",
    apy_avg: float = 5.0,
    apy_min: float = 4.5,
    apy_max: float = 5.5,
    trend: str = "STABLE",
    operational_days: int = 5,
    degraded_days: int = 1,
    critical_days: int = 1,
    weekly_verdict: str = "GOOD",
    top_chain_this_week: str = "ethereum",
    top_chain_apy: float = 12.0,
) -> dict:
    """Build a minimal weekly summary report entry."""
    gen = generated_at or _make_iso()
    return {
        "generated_at": gen,
        "week_start": week_start or gen,
        "week_end": week_end or gen,
        "days_covered": 7,
        "apy_stats": {
            "metric_name": "effective_apy_pct",
            "values": [apy_avg],
            "avg": apy_avg,
            "min": apy_min,
            "max": apy_max,
            "trend": trend,
        },
        "operational_days": operational_days,
        "degraded_days": degraded_days,
        "critical_days": critical_days,
        "best_day_apy": apy_max,
        "worst_day_apy": apy_min,
        "top_chain_this_week": top_chain_this_week,
        "top_chain_apy": top_chain_apy,
        "weekly_verdict": weekly_verdict,
        "summary_line": "Week: ...",
    }


def _make_weekly_file(tmpdir: str, entries: list) -> str:
    """Write a weekly_summary.json ring-buffer file and return its data dir."""
    data_dir = Path(tmpdir)
    payload = {
        "schema_version": 1,
        "source": "weekly_summary_report",
        "ring_buffer_max": 12,
        "report_count": len(entries),
        "last_updated": entries[-1]["generated_at"] if entries else "",
        "latest": entries[-1] if entries else {},
        "history": entries,
    }
    path = data_dir / "weekly_summary.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return str(data_dir)


# ===========================================================================
# TestMonthlyStats
# ===========================================================================

class TestMonthlyStats(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_avg_computed_correctly(self):
        stats = self.reporter.compute_monthly_stats([5.0, 6.0, 7.0], "apy")
        self.assertAlmostEqual(stats.avg, 6.0)

    def test_min_computed_correctly(self):
        stats = self.reporter.compute_monthly_stats([3.0, 5.0, 7.0], "apy")
        self.assertAlmostEqual(stats.min, 3.0)

    def test_max_computed_correctly(self):
        stats = self.reporter.compute_monthly_stats([3.0, 5.0, 7.0], "apy")
        self.assertAlmostEqual(stats.max, 7.0)

    def test_avg_multiple_values(self):
        stats = self.reporter.compute_monthly_stats([1.0, 2.0, 3.0, 4.0], "apy")
        self.assertAlmostEqual(stats.avg, 2.5)

    def test_trend_rising(self):
        stats = self.reporter.compute_monthly_stats([4.0, 4.5, 5.5], "apy")
        self.assertEqual(stats.trend, "RISING")

    def test_trend_falling(self):
        stats = self.reporter.compute_monthly_stats([6.0, 5.5, 4.5], "apy")
        self.assertEqual(stats.trend, "FALLING")

    def test_trend_stable(self):
        stats = self.reporter.compute_monthly_stats([5.0, 5.05, 5.09], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_rising_boundary_exact(self):
        # last = first + 0.1 is NOT strictly greater → STABLE
        stats = self.reporter.compute_monthly_stats([5.0, 5.1], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_rising_boundary_above(self):
        # last = first + 0.11 → RISING
        stats = self.reporter.compute_monthly_stats([5.0, 5.11], "apy")
        self.assertEqual(stats.trend, "RISING")

    def test_trend_falling_boundary_exact(self):
        # last = first - 0.1 → STABLE
        stats = self.reporter.compute_monthly_stats([5.1, 5.0], "apy")
        self.assertEqual(stats.trend, "STABLE")

    def test_trend_falling_boundary_below(self):
        # last = first - 0.11 → FALLING
        stats = self.reporter.compute_monthly_stats([5.11, 5.0], "apy")
        self.assertEqual(stats.trend, "FALLING")

    def test_empty_values_returns_zeros(self):
        stats = self.reporter.compute_monthly_stats([], "apy")
        self.assertAlmostEqual(stats.avg, 0.0)
        self.assertAlmostEqual(stats.min, 0.0)
        self.assertAlmostEqual(stats.max, 0.0)
        self.assertEqual(stats.trend, "STABLE")

    def test_single_value_stable(self):
        stats = self.reporter.compute_monthly_stats([5.5], "apy")
        self.assertAlmostEqual(stats.avg, 5.5)
        self.assertAlmostEqual(stats.min, 5.5)
        self.assertAlmostEqual(stats.max, 5.5)
        self.assertEqual(stats.trend, "STABLE")

    def test_metric_name_preserved(self):
        stats = self.reporter.compute_monthly_stats([5.0], "weekly_apy_avg_pct")
        self.assertEqual(stats.metric_name, "weekly_apy_avg_pct")

    def test_values_list_preserved(self):
        values = [4.5, 5.0, 5.5]
        stats = self.reporter.compute_monthly_stats(values, "x")
        self.assertEqual(stats.values, values)

    def test_returns_monthlystats_type(self):
        stats = self.reporter.compute_monthly_stats([5.0], "x")
        self.assertIsInstance(stats, MonthlyStats)

    def test_to_dict_keys(self):
        stats = self.reporter.compute_monthly_stats([5.0, 6.0], "x")
        d = stats.to_dict()
        for k in ("metric_name", "values", "avg", "min", "max", "trend"):
            self.assertIn(k, d)

    def test_to_dict_serializable(self):
        stats = self.reporter.compute_monthly_stats([5.0, 6.0], "x")
        s = json.dumps(stats.to_dict())
        self.assertIsInstance(s, str)


# ===========================================================================
# TestDetermineVerdict
# ===========================================================================

class TestDetermineVerdict(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_excellent(self):
        self.assertEqual(self.reporter._determine_verdict(6.5, 20), "EXCELLENT")

    def test_excellent_requires_both(self):
        # APY > 6 but only 19 op days → GOOD (by apy)
        self.assertEqual(self.reporter._determine_verdict(6.5, 19), "GOOD")

    def test_excellent_apy_boundary_exact(self):
        # avg == 6.0 is NOT > 6.0 → not EXCELLENT; falls to GOOD by op_days
        self.assertEqual(self.reporter._determine_verdict(6.0, 20), "GOOD")

    def test_excellent_op_days_boundary_exact(self):
        # op_days == 20 is >= 20 → EXCELLENT when apy > 6
        self.assertEqual(self.reporter._determine_verdict(6.1, 20), "EXCELLENT")

    def test_excellent_op_days_below_boundary(self):
        # op_days == 19 < 20 → not EXCELLENT
        self.assertEqual(self.reporter._determine_verdict(6.1, 19), "GOOD")

    def test_good_by_apy(self):
        self.assertEqual(self.reporter._determine_verdict(5.5, 2), "GOOD")

    def test_good_by_op_days(self):
        self.assertEqual(self.reporter._determine_verdict(4.5, 16), "GOOD")

    def test_good_apy_boundary_exact(self):
        # avg == 5.0 not > 5.0, op_days 10 < 16 → falls to FAIR
        self.assertEqual(self.reporter._determine_verdict(5.0, 10), "FAIR")

    def test_good_apy_boundary_above(self):
        self.assertEqual(self.reporter._determine_verdict(5.01, 10), "GOOD")

    def test_good_op_days_boundary_exact(self):
        # op_days == 16 >= 16 → GOOD
        self.assertEqual(self.reporter._determine_verdict(4.5, 16), "GOOD")

    def test_good_op_days_below_boundary(self):
        # op_days == 15 < 16, apy 4.5 → FAIR
        self.assertEqual(self.reporter._determine_verdict(4.5, 15), "FAIR")

    def test_fair(self):
        self.assertEqual(self.reporter._determine_verdict(4.5, 3), "FAIR")

    def test_fair_apy_boundary_exact(self):
        # avg == 4.0 not > 4.0 → POOR
        self.assertEqual(self.reporter._determine_verdict(4.0, 3), "POOR")

    def test_fair_apy_boundary_above(self):
        self.assertEqual(self.reporter._determine_verdict(4.01, 3), "FAIR")

    def test_poor(self):
        self.assertEqual(self.reporter._determine_verdict(3.0, 2), "POOR")

    def test_poor_zero(self):
        self.assertEqual(self.reporter._determine_verdict(0.0, 0), "POOR")

    def test_excellent_not_when_apy_low(self):
        # 30 op days but apy 4.5 → GOOD (op_days), not EXCELLENT
        self.assertEqual(self.reporter._determine_verdict(4.5, 30), "GOOD")


# ===========================================================================
# TestComputeDominantVerdict
# ===========================================================================

class TestComputeDominantVerdict(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_empty_returns_poor(self):
        self.assertEqual(self.reporter._compute_dominant_verdict([]), "POOR")

    def test_single_verdict(self):
        self.assertEqual(self.reporter._compute_dominant_verdict(["GOOD"]), "GOOD")

    def test_clear_majority(self):
        v = ["GOOD", "GOOD", "FAIR", "GOOD"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "GOOD")

    def test_clear_majority_excellent(self):
        v = ["EXCELLENT", "EXCELLENT", "GOOD"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "EXCELLENT")

    def test_tie_prefers_excellent_over_good(self):
        v = ["EXCELLENT", "GOOD"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "EXCELLENT")

    def test_tie_prefers_good_over_fair(self):
        v = ["GOOD", "FAIR"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "GOOD")

    def test_tie_prefers_fair_over_poor(self):
        v = ["FAIR", "POOR"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "FAIR")

    def test_tie_three_way_prefers_excellent(self):
        v = ["EXCELLENT", "GOOD", "FAIR"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "EXCELLENT")

    def test_tie_two_each_prefers_better(self):
        v = ["GOOD", "GOOD", "EXCELLENT", "EXCELLENT"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "EXCELLENT")

    def test_all_poor(self):
        v = ["POOR", "POOR", "POOR"]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "POOR")

    def test_ignores_empty_strings(self):
        v = ["", "GOOD", ""]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "GOOD")

    def test_only_empty_strings_returns_poor(self):
        v = ["", ""]
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "POOR")

    def test_unknown_verdict_does_not_crash(self):
        v = ["WEIRD", "WEIRD", "GOOD"]
        # WEIRD has count 2, but is not in priority list (sorts last);
        # still it's the most frequent → returned.
        self.assertEqual(self.reporter._compute_dominant_verdict(v), "WEIRD")


# ===========================================================================
# TestLoadWeeklyHistory
# ===========================================================================

class TestLoadWeeklyHistory(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_empty_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "weekly_summary.json").write_text("", encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "weekly_summary.json").write_text("{not json", encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_non_dict_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "weekly_summary.json").write_text("[1, 2, 3]", encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_dict_without_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "weekly_summary.json").write_text('{"schema_version": 1}', encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_history_not_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "weekly_summary.json").write_text('{"history": {}}', encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(reporter.load_weekly_history(), [])

    def test_valid_history_returns_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_week_entry(_make_iso(14)), _make_week_entry(_make_iso(7))]
            dp = _make_weekly_file(tmpdir, entries)
            reporter = MonthlySummaryReport(data_path=dp)
            self.assertEqual(len(reporter.load_weekly_history()), 2)

    def test_non_dict_entries_filtered_out(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "schema_version": 1,
                "history": [
                    _make_week_entry(_make_iso(14)),
                    "not a dict",
                    42,
                    None,
                    _make_week_entry(_make_iso(7)),
                ],
            }
            (Path(tmpdir) / "weekly_summary.json").write_text(json.dumps(payload), encoding="utf-8")
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertEqual(len(reporter.load_weekly_history()), 2)

    def test_all_entries_are_dicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_week_entry(_make_iso(i)) for i in (21, 14, 7)]
            dp = _make_weekly_file(tmpdir, entries)
            reporter = MonthlySummaryReport(data_path=dp)
            for item in reporter.load_weekly_history():
                self.assertIsInstance(item, dict)

    def test_multiple_entries_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_week_entry(_make_iso(i * 7)) for i in range(5, 0, -1)]
            dp = _make_weekly_file(tmpdir, entries)
            reporter = MonthlySummaryReport(data_path=dp)
            self.assertEqual(len(reporter.load_weekly_history()), 5)


# ===========================================================================
# TestGetLast4Weeks
# ===========================================================================

class TestGetLast4Weeks(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_empty_returns_empty(self):
        self.assertEqual(self.reporter.get_last_4_weeks([]), [])

    def test_less_than_4_returns_all(self):
        entries = [_make_week_entry(_make_iso(i * 7)) for i in (3, 2, 1)]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 3)

    def test_exactly_4_returns_all(self):
        entries = [_make_week_entry(_make_iso(i * 7)) for i in (4, 3, 2, 1)]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 4)

    def test_more_than_4_returns_last_4(self):
        entries = [_make_week_entry(_make_iso(i * 7)) for i in range(8, 0, -1)]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 4)

    def test_single_entry(self):
        entries = [_make_week_entry(_make_iso(0))]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 1)

    def test_sorted_ascending(self):
        ts_list = [_make_iso(i * 7) for i in range(6, 0, -1)]
        entries = [_make_week_entry(ts) for ts in ts_list]
        random.shuffle(entries)
        result = self.reporter.get_last_4_weeks(entries)
        timestamps = [r["generated_at"] for r in result]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_result_is_newest_4(self):
        entries = [_make_week_entry(_make_iso(i * 7)) for i in range(8, 0, -1)]
        result = self.reporter.get_last_4_weeks(entries)
        newest_in_result = result[-1]["generated_at"]
        newest_overall = max(e["generated_at"] for e in entries)
        self.assertEqual(newest_in_result, newest_overall)

    def test_missing_generated_at_no_crash(self):
        entries = [
            {"weekly_verdict": "GOOD"},
            _make_week_entry(_make_iso(7)),
        ]
        result = self.reporter.get_last_4_weeks(entries)
        self.assertIsInstance(result, list)

    def test_12_entries_returns_4(self):
        entries = [_make_week_entry(_make_iso(i * 7)) for i in range(12, 0, -1)]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 4)

    def test_all_same_timestamp_returns_up_to_4(self):
        ts = _make_iso(0)
        entries = [_make_week_entry(ts) for _ in range(6)]
        self.assertEqual(len(self.reporter.get_last_4_weeks(entries)), 4)


# ===========================================================================
# TestComputeMonthlyStats
# ===========================================================================

class TestComputeMonthlyStats(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_avg_single(self):
        self.assertAlmostEqual(self.reporter.compute_monthly_stats([4.2], "x").avg, 4.2)

    def test_avg_multiple(self):
        self.assertAlmostEqual(
            self.reporter.compute_monthly_stats([1.0, 2.0, 3.0, 4.0], "x").avg, 2.5
        )

    def test_min(self):
        self.assertAlmostEqual(
            self.reporter.compute_monthly_stats([7.0, 3.0, 5.0], "x").min, 3.0
        )

    def test_max(self):
        self.assertAlmostEqual(
            self.reporter.compute_monthly_stats([7.0, 3.0, 5.0], "x").max, 7.0
        )

    def test_trend_rising(self):
        self.assertEqual(self.reporter.compute_monthly_stats([4.0, 5.0], "x").trend, "RISING")

    def test_trend_falling(self):
        self.assertEqual(self.reporter.compute_monthly_stats([5.0, 4.0], "x").trend, "FALLING")

    def test_trend_stable(self):
        self.assertEqual(self.reporter.compute_monthly_stats([5.0, 5.05], "x").trend, "STABLE")

    def test_empty_avg_zero(self):
        self.assertAlmostEqual(self.reporter.compute_monthly_stats([], "x").avg, 0.0)

    def test_empty_trend_stable(self):
        self.assertEqual(self.reporter.compute_monthly_stats([], "x").trend, "STABLE")

    def test_empty_values_list(self):
        self.assertEqual(self.reporter.compute_monthly_stats([], "x").values, [])


# ===========================================================================
# TestExtractTopChain
# ===========================================================================

class TestExtractTopChain(unittest.TestCase):

    def setUp(self):
        self.reporter = MonthlySummaryReport.__new__(MonthlySummaryReport)

    def test_empty_returns_fallback(self):
        self.assertEqual(self.reporter._extract_top_chain([]), ("", 0.0))

    def test_single_week(self):
        weeks = [_make_week_entry(top_chain_this_week="arbitrum", top_chain_apy=8.0)]
        chain, apy = self.reporter._extract_top_chain(weeks)
        self.assertEqual(chain, "arbitrum")
        self.assertAlmostEqual(apy, 8.0)

    def test_highest_avg_wins(self):
        weeks = [
            _make_week_entry(top_chain_this_week="ethereum", top_chain_apy=12.0),
            _make_week_entry(top_chain_this_week="ethereum", top_chain_apy=12.0),
            _make_week_entry(top_chain_this_week="arbitrum", top_chain_apy=8.0),
        ]
        chain, apy = self.reporter._extract_top_chain(weeks)
        self.assertEqual(chain, "ethereum")
        self.assertAlmostEqual(apy, 12.0)

    def test_averages_across_weeks(self):
        weeks = [
            _make_week_entry(top_chain_this_week="base", top_chain_apy=10.0),
            _make_week_entry(top_chain_this_week="base", top_chain_apy=20.0),
        ]
        chain, apy = self.reporter._extract_top_chain(weeks)
        self.assertEqual(chain, "base")
        self.assertAlmostEqual(apy, 15.0)

    def test_skips_empty_chain_names(self):
        weeks = [
            _make_week_entry(top_chain_this_week="", top_chain_apy=99.0),
            _make_week_entry(top_chain_this_week="optimism", top_chain_apy=7.0),
        ]
        chain, apy = self.reporter._extract_top_chain(weeks)
        self.assertEqual(chain, "optimism")

    def test_all_empty_returns_fallback(self):
        weeks = [
            _make_week_entry(top_chain_this_week=""),
            _make_week_entry(top_chain_this_week=""),
        ]
        self.assertEqual(self.reporter._extract_top_chain(weeks), ("", 0.0))


# ===========================================================================
# TestGenerateReport
# ===========================================================================

class TestGenerateReport(unittest.TestCase):

    def test_no_history_returns_poor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertEqual(report.monthly_verdict, "POOR")

    def test_no_history_zero_weeks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertEqual(report.weeks_covered, 0)

    def test_no_history_zero_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertAlmostEqual(report.apy_stats.avg, 0.0)

    def test_no_history_dominant_poor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertEqual(report.dominant_verdict, "POOR")

    def test_no_history_summary_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertIn("no data", report.summary_line)

    def test_return_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            report = reporter.generate_report()
        self.assertIsInstance(report, MonthlySummaryReportData)

    def _build_4_weeks(self, tmpdir, **overrides):
        entries = [
            _make_week_entry(generated_at=_make_iso(28), week_start=_make_iso(35),
                             week_end=_make_iso(28), apy_avg=5.0,
                             operational_days=5, degraded_days=1, critical_days=1,
                             weekly_verdict="GOOD"),
            _make_week_entry(generated_at=_make_iso(21), week_start=_make_iso(28),
                             week_end=_make_iso(21), apy_avg=5.5,
                             operational_days=6, degraded_days=1, critical_days=0,
                             weekly_verdict="GOOD"),
            _make_week_entry(generated_at=_make_iso(14), week_start=_make_iso(21),
                             week_end=_make_iso(14), apy_avg=6.0,
                             operational_days=4, degraded_days=2, critical_days=1,
                             weekly_verdict="FAIR"),
            _make_week_entry(generated_at=_make_iso(7), week_start=_make_iso(14),
                             week_end=_make_iso(7), apy_avg=4.5,
                             operational_days=5, degraded_days=1, critical_days=1,
                             weekly_verdict="GOOD"),
        ]
        return _make_weekly_file(tmpdir, entries)

    def test_4_weeks_weeks_covered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.weeks_covered, 4)

    def test_4_weeks_operational_sum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.total_operational_days, 20)

    def test_4_weeks_degraded_sum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.total_degraded_days, 5)

    def test_4_weeks_critical_sum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.total_critical_days, 3)

    def test_4_weeks_best_week(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertAlmostEqual(report.best_week_apy, 6.0)

    def test_4_weeks_worst_week(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertAlmostEqual(report.worst_week_apy, 4.5)

    def test_4_weeks_apy_avg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertAlmostEqual(report.apy_stats.avg, (5.0 + 5.5 + 6.0 + 4.5) / 4)

    def test_4_weeks_verdict_distribution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.verdict_distribution.get("GOOD"), 3)
        self.assertEqual(report.verdict_distribution.get("FAIR"), 1)

    def test_4_weeks_dominant_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.dominant_verdict, "GOOD")

    def test_4_weeks_top_chain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.top_chain_this_month, "ethereum")

    def test_4_weeks_top_chain_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertAlmostEqual(report.top_chain_apy, 12.0)

    def test_4_weeks_month_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_first = _make_iso(35)
            entries = [
                _make_week_entry(generated_at=_make_iso(28), week_start=ws_first,
                                 week_end=_make_iso(28)),
                _make_week_entry(generated_at=_make_iso(7), week_start=_make_iso(14),
                                 week_end=_make_iso(7)),
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.month_start, ws_first)

    def test_4_weeks_month_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            we_last = _make_iso(7)
            entries = [
                _make_week_entry(generated_at=_make_iso(28), week_start=_make_iso(35),
                                 week_end=_make_iso(28)),
                _make_week_entry(generated_at=_make_iso(7), week_start=_make_iso(14),
                                 week_end=we_last),
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.month_end, we_last)

    def test_summary_line_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertIn("APY avg", report.summary_line)
        self.assertIn("weeks", report.summary_line)
        self.assertIn("operational days", report.summary_line)

    def test_summary_line_weeks_fraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = self._build_4_weeks(tmpdir)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertIn("4/4 weeks", report.summary_line)

    def test_verdict_excellent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=7.0,
                                 operational_days=6, degraded_days=0, critical_days=0,
                                 weekly_verdict="EXCELLENT")
                for i in range(4)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        # avg 7.0 > 6.0 and op_days 24 >= 20 → EXCELLENT
        self.assertEqual(report.monthly_verdict, "EXCELLENT")

    def test_verdict_good_by_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=5.5,
                                 operational_days=2, degraded_days=3, critical_days=2,
                                 weekly_verdict="GOOD")
                for i in range(3)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        # avg 5.5 > 5.0 → GOOD
        self.assertEqual(report.monthly_verdict, "GOOD")

    def test_verdict_good_by_op_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=4.5,
                                 operational_days=6, degraded_days=1, critical_days=0,
                                 weekly_verdict="FAIR")
                for i in range(3)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        # op_days 18 >= 16 → GOOD
        self.assertEqual(report.monthly_verdict, "GOOD")

    def test_verdict_fair(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=4.5,
                                 operational_days=3, degraded_days=2, critical_days=2,
                                 weekly_verdict="FAIR")
                for i in range(3)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        # avg 4.5 > 4.0, op_days 9 < 16 → FAIR
        self.assertEqual(report.monthly_verdict, "FAIR")

    def test_verdict_poor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=3.0,
                                 operational_days=2, degraded_days=2, critical_days=3,
                                 weekly_verdict="POOR")
                for i in range(3)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.monthly_verdict, "POOR")

    def test_single_week(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [_make_week_entry(apy_avg=5.5, operational_days=5,
                                        weekly_verdict="GOOD")]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.weeks_covered, 1)
        self.assertAlmostEqual(report.apy_stats.avg, 5.5)

    def test_more_than_4_weeks_uses_last_4(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(i * 7), apy_avg=float(i))
                for i in range(8, 0, -1)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertEqual(report.weeks_covered, 4)

    def test_handles_missing_apy_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = _make_week_entry()
            del entry["apy_stats"]
            dp = _make_weekly_file(tmpdir, [entry])
            report = MonthlySummaryReport(data_path=dp).generate_report()
        self.assertAlmostEqual(report.apy_stats.avg, 0.0)


# ===========================================================================
# TestSaveReport
# ===========================================================================

class TestSaveReport(unittest.TestCase):

    def _setup(self, tmpdir):
        entries = [_make_week_entry(apy_avg=5.0)]
        dp = _make_weekly_file(tmpdir, entries)
        return MonthlySummaryReport(data_path=dp)

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            self.assertTrue(os.path.exists(path))

    def test_path_is_monthly_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            self.assertTrue(path.endswith("monthly_summary.json"))

    def test_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            reporter.save_report()
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        self.assertIn("history", data)
        self.assertIn("latest", data)

    def test_schema_keys_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        for k in ("schema_version", "source", "ring_buffer_max",
                  "report_count", "last_updated", "latest", "history"):
            self.assertIn(k, data)

    def test_source_is_monthly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        self.assertEqual(data["source"], "monthly_summary_report")

    def test_ring_buffer_max_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        self.assertEqual(data["ring_buffer_max"], 12)

    def test_ring_buffer_capped_at_12(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            for _ in range(15):
                reporter._report = None
                reporter.save_report()
            out_path = Path(tmpdir) / "monthly_summary.json"
            with open(out_path) as fh:
                data = json.load(fh)
        self.assertLessEqual(len(data["history"]), 12)

    def test_append_increments_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            reporter.save_report()
            reporter._report = None
            reporter.save_report()
            out_path = Path(tmpdir) / "monthly_summary.json"
            with open(out_path) as fh:
                data = json.load(fh)
        self.assertEqual(data["report_count"], 2)

    def test_15_iterations_count_capped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            for _ in range(15):
                reporter._report = None
                reporter.save_report()
            out_path = Path(tmpdir) / "monthly_summary.json"
            with open(out_path) as fh:
                data = json.load(fh)
        self.assertEqual(data["report_count"], 12)

    def test_latest_matches_last(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            path = reporter.save_report()
            with open(path) as fh:
                data = json.load(fh)
        self.assertEqual(data["latest"], data["history"][-1])

    def test_save_accepts_explicit_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            report = reporter.generate_report()
            path = reporter.save_report(report)
            self.assertTrue(os.path.exists(path))


# ===========================================================================
# TestFormatTelegramMessage
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):

    def _setup(self, tmpdir, apy=5.5, verdict="GOOD", op_days=5):
        entries = [
            _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=apy,
                             operational_days=op_days, weekly_verdict=verdict)
            for i in range(4)
        ]
        dp = _make_weekly_file(tmpdir, entries)
        return MonthlySummaryReport(data_path=dp)

    def test_length_le_1500(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            self.assertLessEqual(len(reporter.format_telegram_message()), 1500)

    def test_contains_verdict_excellent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7), apy_avg=7.0,
                                 operational_days=6, weekly_verdict="EXCELLENT")
                for i in range(4)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            reporter = MonthlySummaryReport(data_path=dp)
            self.assertIn("EXCELLENT", reporter.format_telegram_message())

    def test_contains_avg_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir, apy=5.5)
            self.assertIn("5.50", reporter.format_telegram_message())

    def test_contains_monthly_summary_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            self.assertIn("Monthly Summary", reporter.format_telegram_message())

    def test_contains_dominant_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir, verdict="GOOD")
            self.assertIn("Dominant verdict", reporter.format_telegram_message())

    def test_no_data_still_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            msg = reporter.format_telegram_message()
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_truncated_with_ellipsis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                _make_week_entry(generated_at=_make_iso(28 - i * 7),
                                 top_chain_this_week="a" * 600, top_chain_apy=12.0)
                for i in range(4)
            ]
            dp = _make_weekly_file(tmpdir, entries)
            reporter = MonthlySummaryReport(data_path=dp)
            self.assertLessEqual(len(reporter.format_telegram_message()), 1500)

    def test_contains_top_chain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            self.assertIn("Top chain", reporter.format_telegram_message())


# ===========================================================================
# TestToDict
# ===========================================================================

class TestToDict(unittest.TestCase):

    def _setup(self, tmpdir):
        entries = [_make_week_entry(apy_avg=5.0)]
        dp = _make_weekly_file(tmpdir, entries)
        return MonthlySummaryReport(data_path=dp)

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            self.assertIsInstance(reporter.to_dict(), dict)

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            self.assertIsInstance(json.dumps(reporter.to_dict()), str)

    def test_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            result = reporter.to_dict()
        required = [
            "generated_at", "month_start", "month_end", "weeks_covered",
            "apy_stats", "total_operational_days", "total_degraded_days",
            "total_critical_days", "best_week_apy", "worst_week_apy",
            "dominant_verdict", "verdict_distribution", "top_chain_this_month",
            "top_chain_apy", "monthly_verdict", "summary_line",
        ]
        for k in required:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_apy_stats_is_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            result = reporter.to_dict()
        self.assertIsInstance(result["apy_stats"], dict)
        for k in ("metric_name", "values", "avg", "min", "max", "trend"):
            self.assertIn(k, result["apy_stats"], f"Missing apy_stats key: {k}")

    def test_verdict_distribution_is_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = self._setup(tmpdir)
            result = reporter.to_dict()
        self.assertIsInstance(result["verdict_distribution"], dict)

    def test_no_data_to_dict_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = MonthlySummaryReport(data_path=tmpdir)
            self.assertIsInstance(json.dumps(reporter.to_dict()), str)


# ===========================================================================
# TestHelpers
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

    def test_safe_float_int(self):
        self.assertAlmostEqual(_safe_float(7), 7.0)

    def test_safe_float_invalid_string(self):
        self.assertAlmostEqual(_safe_float("abc"), 0.0)

    # _parse_timestamp
    def test_parse_timestamp_z_suffix(self):
        dt = _parse_timestamp("2026-06-13T08:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_timestamp_with_offset(self):
        self.assertIsNotNone(_parse_timestamp("2026-06-13T08:00:00+00:00"))

    def test_parse_timestamp_naive_gets_utc(self):
        dt = _parse_timestamp("2026-06-13T08:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_timestamp_invalid_returns_none(self):
        self.assertIsNone(_parse_timestamp("not-a-date"))

    # _compute_trend
    def test_compute_trend_single(self):
        self.assertEqual(_compute_trend([5.0]), "STABLE")

    def test_compute_trend_empty(self):
        self.assertEqual(_compute_trend([]), "STABLE")

    def test_compute_trend_rising(self):
        self.assertEqual(_compute_trend([4.0, 5.0]), "RISING")

    def test_compute_trend_falling(self):
        self.assertEqual(_compute_trend([5.0, 4.0]), "FALLING")

    # _trend_arrow
    def test_trend_arrow_rising(self):
        self.assertIn("↗", _trend_arrow("RISING"))

    def test_trend_arrow_falling(self):
        self.assertIn("↘", _trend_arrow("FALLING"))

    def test_trend_arrow_stable(self):
        self.assertIsInstance(_trend_arrow("STABLE"), str)


if __name__ == "__main__":
    unittest.main()
