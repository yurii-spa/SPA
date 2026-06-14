"""
Tests for QuarterlySummaryReport (MP-643).

spa_core/tests/test_quarterly_summary_report.py

Runs under both ``python3 -m unittest`` and pytest. All I/O is confined to a
tempfile.TemporaryDirectory — the production data/ dir is never touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.quarterly_summary_report import (
    QuarterlySummaryReport,
    QuarterlySummaryReportData,
    QuarterlyStats,
    _compute_trend,
    _trend_arrow,
    _safe_float,
    _VERDICT_EXCELLENT,
    _VERDICT_GOOD,
    _VERDICT_FAIR,
    _VERDICT_POOR,
    _RING_BUFFER_MAX,
    _TELEGRAM_MAX_CHARS,
    _OUTPUT_FILENAME,
    _SOURCE_FILENAME,
)

_MODULE = "spa_core.analytics.quarterly_summary_report"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

def _make_month(
    avg_apy=5.0,
    monthly_verdict="GOOD",
    top_chain="ethereum",
    top_chain_apy=10.0,
    generated_at="2026-01-01T00:00:00+00:00",
    month_start="2025-12-01T00:00:00+00:00",
    month_end="2025-12-31T00:00:00+00:00",
):
    return {
        "generated_at": generated_at,
        "month_start": month_start,
        "month_end": month_end,
        "apy_stats": {"avg": avg_apy, "min": avg_apy, "max": avg_apy, "trend": "STABLE"},
        "monthly_verdict": monthly_verdict,
        "top_chain_this_month": top_chain,
        "top_chain_apy": top_chain_apy,
    }


def _write_monthly(data_dir, months, wrap=True):
    """Write a monthly_summary.json with given month dicts in history."""
    path = Path(data_dir) / _SOURCE_FILENAME
    if wrap:
        payload = {
            "schema_version": 1,
            "source": "monthly_summary_report",
            "history": months,
        }
    else:
        payload = months  # malformed (not a dict)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_str_number(self):
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_bool_true_is_zero(self):
        self.assertEqual(_safe_float(True), 0.0)

    def test_bool_false_is_zero(self):
        self.assertEqual(_safe_float(False), 0.0)

    def test_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_garbage_str(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_dict(self):
        self.assertEqual(_safe_float({}), 0.0)

    def test_list(self):
        self.assertEqual(_safe_float([1, 2]), 0.0)


# ---------------------------------------------------------------------------
# _compute_trend
# ---------------------------------------------------------------------------

class TestComputeTrend(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_compute_trend([]), "STABLE")

    def test_single(self):
        self.assertEqual(_compute_trend([5.0]), "STABLE")

    def test_rising(self):
        self.assertEqual(_compute_trend([5.0, 5.3]), "RISING")

    def test_falling(self):
        self.assertEqual(_compute_trend([5.3, 5.0]), "FALLING")

    def test_stable_equal(self):
        self.assertEqual(_compute_trend([5.0, 5.0]), "STABLE")

    def test_rising_boundary_exact(self):
        # last == first + 0.1 → not strictly greater → STABLE
        self.assertEqual(_compute_trend([5.0, 5.1]), "STABLE")

    def test_rising_just_over(self):
        self.assertEqual(_compute_trend([5.0, 5.11]), "RISING")

    def test_falling_boundary_exact(self):
        self.assertEqual(_compute_trend([5.1, 5.0]), "STABLE")

    def test_falling_just_under(self):
        self.assertEqual(_compute_trend([5.11, 5.0]), "FALLING")

    def test_uses_first_and_last_only(self):
        # middle high but first<last by <0.1 → STABLE
        self.assertEqual(_compute_trend([5.0, 9.0, 5.05]), "STABLE")

    def test_three_rising(self):
        self.assertEqual(_compute_trend([4.0, 5.0, 6.0]), "RISING")

    def test_three_falling(self):
        self.assertEqual(_compute_trend([6.0, 5.0, 4.0]), "FALLING")


# ---------------------------------------------------------------------------
# _trend_arrow
# ---------------------------------------------------------------------------

class TestTrendArrow(unittest.TestCase):

    def test_rising(self):
        self.assertEqual(_trend_arrow("RISING"), "↗️")

    def test_falling(self):
        self.assertEqual(_trend_arrow("FALLING"), "↘️")

    def test_stable(self):
        self.assertEqual(_trend_arrow("STABLE"), "→")

    def test_unknown(self):
        self.assertEqual(_trend_arrow("WHATEVER"), "→")


# ---------------------------------------------------------------------------
# compute_quarterly_stats
# ---------------------------------------------------------------------------

class TestComputeQuarterlyStats(unittest.TestCase):

    def setUp(self):
        self.r = QuarterlySummaryReport(data_path=tempfile.mkdtemp())

    def test_empty_values(self):
        s = self.r.compute_quarterly_stats([], "m")
        self.assertEqual(s.mean, 0.0)
        self.assertEqual(s.min, 0.0)
        self.assertEqual(s.max, 0.0)
        self.assertEqual(s.trend, "STABLE")
        self.assertEqual(s.values, [])

    def test_single_value(self):
        s = self.r.compute_quarterly_stats([5.0], "m")
        self.assertEqual(s.mean, 5.0)
        self.assertEqual(s.min, 5.0)
        self.assertEqual(s.max, 5.0)

    def test_mean(self):
        s = self.r.compute_quarterly_stats([3.0, 6.0, 9.0], "m")
        self.assertAlmostEqual(s.mean, 6.0)

    def test_min_max(self):
        s = self.r.compute_quarterly_stats([3.0, 6.0, 9.0], "m")
        self.assertEqual(s.min, 3.0)
        self.assertEqual(s.max, 9.0)

    def test_trend_rising(self):
        s = self.r.compute_quarterly_stats([3.0, 6.0, 9.0], "m")
        self.assertEqual(s.trend, "RISING")

    def test_trend_falling(self):
        s = self.r.compute_quarterly_stats([9.0, 6.0, 3.0], "m")
        self.assertEqual(s.trend, "FALLING")

    def test_metric_name_preserved(self):
        s = self.r.compute_quarterly_stats([1.0], "my_metric")
        self.assertEqual(s.metric_name, "my_metric")

    def test_values_copied(self):
        src = [1.0, 2.0]
        s = self.r.compute_quarterly_stats(src, "m")
        src.append(3.0)
        self.assertEqual(s.values, [1.0, 2.0])


# ---------------------------------------------------------------------------
# _determine_verdict (thresholds scaled x3 from monthly — same APY scale)
# ---------------------------------------------------------------------------

class TestDetermineVerdict(unittest.TestCase):

    def setUp(self):
        self.r = QuarterlySummaryReport(data_path=tempfile.mkdtemp())

    def test_excellent_boundary(self):
        self.assertEqual(self.r._determine_verdict(6.0), _VERDICT_EXCELLENT)

    def test_excellent_above(self):
        self.assertEqual(self.r._determine_verdict(7.5), _VERDICT_EXCELLENT)

    def test_good_boundary(self):
        self.assertEqual(self.r._determine_verdict(5.0), _VERDICT_GOOD)

    def test_good_just_below_excellent(self):
        self.assertEqual(self.r._determine_verdict(5.99), _VERDICT_GOOD)

    def test_fair_boundary(self):
        self.assertEqual(self.r._determine_verdict(4.0), _VERDICT_FAIR)

    def test_fair_just_below_good(self):
        self.assertEqual(self.r._determine_verdict(4.99), _VERDICT_FAIR)

    def test_poor_just_below_fair(self):
        self.assertEqual(self.r._determine_verdict(3.99), _VERDICT_POOR)

    def test_poor_zero(self):
        self.assertEqual(self.r._determine_verdict(0.0), _VERDICT_POOR)

    def test_poor_negative(self):
        self.assertEqual(self.r._determine_verdict(-1.0), _VERDICT_POOR)


# ---------------------------------------------------------------------------
# _compute_dominant_verdict
# ---------------------------------------------------------------------------

class TestDominantVerdict(unittest.TestCase):

    def setUp(self):
        self.r = QuarterlySummaryReport(data_path=tempfile.mkdtemp())

    def test_empty(self):
        self.assertEqual(self.r._compute_dominant_verdict([]), _VERDICT_POOR)

    def test_single(self):
        self.assertEqual(self.r._compute_dominant_verdict(["GOOD"]), "GOOD")

    def test_clear_majority(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["GOOD", "GOOD", "FAIR"]), "GOOD"
        )

    def test_tie_excellent_beats_good(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["EXCELLENT", "GOOD"]), _VERDICT_EXCELLENT
        )

    def test_tie_good_beats_fair(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["FAIR", "GOOD"]), _VERDICT_GOOD
        )

    def test_tie_fair_beats_poor(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["POOR", "FAIR"]), _VERDICT_FAIR
        )

    def test_tie_three_way(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["POOR", "FAIR", "GOOD"]), _VERDICT_GOOD
        )

    def test_majority_overrides_priority(self):
        # POOR has 2, EXCELLENT has 1 → POOR wins (frequency first)
        self.assertEqual(
            self.r._compute_dominant_verdict(["POOR", "POOR", "EXCELLENT"]), _VERDICT_POOR
        )

    def test_ignores_empty_strings(self):
        self.assertEqual(
            self.r._compute_dominant_verdict(["", "GOOD"]), "GOOD"
        )

    def test_all_empty_strings(self):
        self.assertEqual(self.r._compute_dominant_verdict(["", ""]), _VERDICT_POOR)

    def test_non_string_skipped(self):
        self.assertEqual(
            self.r._compute_dominant_verdict([None, "GOOD"]), "GOOD"
        )


# ---------------------------------------------------------------------------
# _extract_top_chain
# ---------------------------------------------------------------------------

class TestExtractTopChain(unittest.TestCase):

    def setUp(self):
        self.r = QuarterlySummaryReport(data_path=tempfile.mkdtemp())

    def test_empty(self):
        self.assertEqual(self.r._extract_top_chain([]), ("", 0.0))

    def test_no_chain_field(self):
        self.assertEqual(self.r._extract_top_chain([{"foo": 1}]), ("", 0.0))

    def test_single_chain(self):
        months = [_make_month(top_chain="base", top_chain_apy=8.0)]
        chain, apy = self.r._extract_top_chain(months)
        self.assertEqual(chain, "base")
        self.assertAlmostEqual(apy, 8.0)

    def test_most_frequent(self):
        months = [
            _make_month(top_chain="eth", top_chain_apy=5.0),
            _make_month(top_chain="eth", top_chain_apy=7.0),
            _make_month(top_chain="base", top_chain_apy=20.0),
        ]
        chain, apy = self.r._extract_top_chain(months)
        self.assertEqual(chain, "eth")
        self.assertAlmostEqual(apy, 6.0)

    def test_tie_break_by_apy(self):
        months = [
            _make_month(top_chain="eth", top_chain_apy=5.0),
            _make_month(top_chain="base", top_chain_apy=9.0),
        ]
        chain, _ = self.r._extract_top_chain(months)
        self.assertEqual(chain, "base")

    def test_empty_chain_name_ignored(self):
        months = [_make_month(top_chain="", top_chain_apy=5.0)]
        self.assertEqual(self.r._extract_top_chain(months), ("", 0.0))


# ---------------------------------------------------------------------------
# generate_report — no data / malformed
# ---------------------------------------------------------------------------

class TestGenerateReportNoData(unittest.TestCase):

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            self.assertFalse(rep.available)
            self.assertEqual(rep.quarterly_verdict, _VERDICT_POOR)
            self.assertEqual(rep.months_covered, 0)

    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [])
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            self.assertFalse(rep.available)

    def test_malformed_not_dict(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [1, 2, 3], wrap=False)
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            self.assertFalse(rep.available)

    def test_malformed_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / _SOURCE_FILENAME
            with open(path, "w") as fh:
                fh.write("{not valid json")
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            self.assertFalse(rep.available)

    def test_history_not_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / _SOURCE_FILENAME
            with open(path, "w") as fh:
                json.dump({"history": "oops"}, fh)
            r = QuarterlySummaryReport(data_path=d)
            self.assertEqual(r.load_monthly_history(), [])

    def test_no_data_summary_line(self):
        with tempfile.TemporaryDirectory() as d:
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            self.assertIn("no data", rep.summary_line)

    def test_history_filters_non_dict(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month(), "garbage", 42])
            r = QuarterlySummaryReport(data_path=d)
            hist = r.load_monthly_history()
            self.assertEqual(len(hist), 1)


# ---------------------------------------------------------------------------
# generate_report — happy path
# ---------------------------------------------------------------------------

class TestGenerateReportHappy(unittest.TestCase):

    def _gen(self, months):
        d = tempfile.mkdtemp()
        _write_monthly(d, months)
        r = QuarterlySummaryReport(data_path=d)
        return r.generate_report()

    def test_available_true(self):
        rep = self._gen([_make_month()])
        self.assertTrue(rep.available)

    def test_one_month(self):
        rep = self._gen([_make_month(avg_apy=5.5)])
        self.assertEqual(rep.months_covered, 1)
        self.assertAlmostEqual(rep.apy_stats.mean, 5.5)

    def test_three_months_mean(self):
        months = [
            _make_month(avg_apy=4.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=5.0, generated_at="2026-02-01T00:00:00+00:00"),
            _make_month(avg_apy=6.0, generated_at="2026-03-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertAlmostEqual(rep.apy_stats.mean, 5.0)
        self.assertEqual(rep.months_covered, 3)

    def test_only_last_three_used(self):
        months = [
            _make_month(avg_apy=1.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=4.0, generated_at="2026-02-01T00:00:00+00:00"),
            _make_month(avg_apy=5.0, generated_at="2026-03-01T00:00:00+00:00"),
            _make_month(avg_apy=6.0, generated_at="2026-04-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.months_covered, 3)
        self.assertAlmostEqual(rep.apy_stats.mean, 5.0)  # (4+5+6)/3

    def test_best_worst_month(self):
        months = [
            _make_month(avg_apy=4.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=8.0, generated_at="2026-02-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.best_month_apy, 8.0)
        self.assertEqual(rep.worst_month_apy, 4.0)

    def test_trend_rising(self):
        months = [
            _make_month(avg_apy=4.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=6.0, generated_at="2026-03-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.apy_stats.trend, "RISING")

    def test_trend_falling(self):
        months = [
            _make_month(avg_apy=6.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=4.0, generated_at="2026-03-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.apy_stats.trend, "FALLING")

    def test_verdict_excellent(self):
        rep = self._gen([_make_month(avg_apy=7.0)])
        self.assertEqual(rep.quarterly_verdict, _VERDICT_EXCELLENT)

    def test_verdict_good(self):
        rep = self._gen([_make_month(avg_apy=5.2)])
        self.assertEqual(rep.quarterly_verdict, _VERDICT_GOOD)

    def test_verdict_fair(self):
        rep = self._gen([_make_month(avg_apy=4.2)])
        self.assertEqual(rep.quarterly_verdict, _VERDICT_FAIR)

    def test_verdict_poor(self):
        rep = self._gen([_make_month(avg_apy=2.0)])
        self.assertEqual(rep.quarterly_verdict, _VERDICT_POOR)

    def test_dominant_monthly_verdict(self):
        months = [
            _make_month(monthly_verdict="GOOD", generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(monthly_verdict="GOOD", generated_at="2026-02-01T00:00:00+00:00"),
            _make_month(monthly_verdict="FAIR", generated_at="2026-03-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.dominant_monthly_verdict, "GOOD")

    def test_verdict_distribution(self):
        months = [
            _make_month(monthly_verdict="GOOD", generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(monthly_verdict="FAIR", generated_at="2026-02-01T00:00:00+00:00"),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.verdict_distribution, {"GOOD": 1, "FAIR": 1})

    def test_top_chain(self):
        months = [
            _make_month(top_chain="arbitrum", top_chain_apy=11.0),
        ]
        rep = self._gen(months)
        self.assertEqual(rep.top_chain_this_quarter, "arbitrum")

    def test_quarter_start_end(self):
        rep = self._gen([_make_month()])
        self.assertEqual(rep.quarter_start, "2025-12-01T00:00:00+00:00")
        self.assertEqual(rep.quarter_end, "2025-12-31T00:00:00+00:00")

    def test_handles_mean_key_instead_of_avg(self):
        m = _make_month()
        m["apy_stats"] = {"mean": 5.5}
        d = tempfile.mkdtemp()
        _write_monthly(d, [m])
        rep = QuarterlySummaryReport(data_path=d).generate_report()
        self.assertAlmostEqual(rep.apy_stats.mean, 5.5)

    def test_apy_stats_not_dict(self):
        m = _make_month()
        m["apy_stats"] = "broken"
        d = tempfile.mkdtemp()
        _write_monthly(d, [m])
        rep = QuarterlySummaryReport(data_path=d).generate_report()
        self.assertAlmostEqual(rep.apy_stats.mean, 0.0)

    def test_summary_line_contains_verdict(self):
        rep = self._gen([_make_month(avg_apy=7.0)])
        self.assertIn("EXCELLENT", rep.summary_line)


# ---------------------------------------------------------------------------
# get_last_3_months
# ---------------------------------------------------------------------------

class TestGetLast3Months(unittest.TestCase):

    def setUp(self):
        self.r = QuarterlySummaryReport(data_path=tempfile.mkdtemp())

    def test_empty(self):
        self.assertEqual(self.r.get_last_3_months([]), [])

    def test_fewer_than_three(self):
        months = [_make_month(), _make_month()]
        self.assertEqual(len(self.r.get_last_3_months(months)), 2)

    def test_caps_at_three(self):
        months = [_make_month(generated_at=f"2026-0{i}-01T00:00:00+00:00") for i in range(1, 6)]
        self.assertEqual(len(self.r.get_last_3_months(months)), 3)

    def test_sorted_ascending(self):
        months = [
            _make_month(avg_apy=3.0, generated_at="2026-03-01T00:00:00+00:00"),
            _make_month(avg_apy=1.0, generated_at="2026-01-01T00:00:00+00:00"),
            _make_month(avg_apy=2.0, generated_at="2026-02-01T00:00:00+00:00"),
        ]
        last3 = self.r.get_last_3_months(months)
        gens = [m["generated_at"] for m in last3]
        self.assertEqual(gens, sorted(gens))

    def test_missing_generated_at(self):
        months = [{"foo": 1}, _make_month()]
        # should not crash
        out = self.r.get_last_3_months(months)
        self.assertEqual(len(out), 2)


# ---------------------------------------------------------------------------
# save_report — atomic, ring-buffer
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            path = r.save_report()
            self.assertTrue(os.path.exists(path))

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            path = r.save_report()
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("history", data)
            self.assertIn("latest", data)

    def test_output_filename(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            path = r.save_report()
            self.assertTrue(path.endswith(_OUTPUT_FILENAME))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            for _ in range(_RING_BUFFER_MAX + 5):
                rep = r.generate_report()
                r.save_report(rep)
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["history"]), _RING_BUFFER_MAX)

    def test_report_count_matches(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            r.save_report(r.generate_report())
            r.save_report(r.generate_report())
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(data["report_count"], 2)

    def test_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            r = QuarterlySummaryReport(data_path=d)
            r.save_report()
            leftovers = list(Path(d).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_latest_is_last(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month(avg_apy=7.0)])
            r = QuarterlySummaryReport(data_path=d)
            r.save_report()
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(data["latest"]["quarterly_verdict"], _VERDICT_EXCELLENT)

    def test_corrupt_existing_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            out = Path(d) / _OUTPUT_FILENAME
            with open(out, "w") as fh:
                fh.write("{not json")
            r = QuarterlySummaryReport(data_path=d)
            r.save_report()  # must not crash
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["history"]), 1)

    def test_no_data_report_saved(self):
        with tempfile.TemporaryDirectory() as d:
            r = QuarterlySummaryReport(data_path=d)
            path = r.save_report()
            with open(path) as fh:
                data = json.load(fh)
            self.assertFalse(data["latest"]["available"])


# ---------------------------------------------------------------------------
# format_telegram_message
# ---------------------------------------------------------------------------

class TestTelegram(unittest.TestCase):

    def test_no_data_message(self):
        with tempfile.TemporaryDirectory() as d:
            r = QuarterlySummaryReport(data_path=d)
            rep = r.generate_report()
            msg = r.format_telegram_message(rep)
            self.assertIn("no data", msg)

    def test_happy_message(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month(avg_apy=7.0)])
        r = QuarterlySummaryReport(data_path=d)
        rep = r.generate_report()
        msg = r.format_telegram_message(rep)
        self.assertIn("Quarterly Summary", msg)
        self.assertIn("EXCELLENT", msg)

    def test_length_cap(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month(top_chain="x" * 4000)])
        r = QuarterlySummaryReport(data_path=d)
        rep = r.generate_report()
        msg = r.format_telegram_message(rep)
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_contains_months_covered(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month()])
        r = QuarterlySummaryReport(data_path=d)
        msg = r.format_telegram_message(r.generate_report())
        self.assertIn("Months covered", msg)

    def test_contains_top_chain(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month(top_chain="zksync", top_chain_apy=9.0)])
        r = QuarterlySummaryReport(data_path=d)
        msg = r.format_telegram_message(r.generate_report())
        self.assertIn("zksync", msg)

    def test_generates_if_none(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month()])
        r = QuarterlySummaryReport(data_path=d)
        msg = r.format_telegram_message()  # no report passed
        self.assertTrue(len(msg) > 0)


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trips
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):

    def _sample(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month(avg_apy=5.5)])
        r = QuarterlySummaryReport(data_path=d)
        return r, r.generate_report()

    def test_to_dict_keys(self):
        r, rep = self._sample()
        dd = r.to_dict(rep)
        for key in [
            "generated_at", "available", "quarter_start", "quarter_end",
            "months_covered", "apy_stats", "best_month_apy", "worst_month_apy",
            "dominant_monthly_verdict", "verdict_distribution",
            "top_chain_this_quarter", "top_chain_apy", "quarterly_verdict",
            "summary_line",
        ]:
            self.assertIn(key, dd)

    def test_to_dict_json_serializable(self):
        r, rep = self._sample()
        json.dumps(r.to_dict(rep))  # must not raise

    def test_report_round_trip(self):
        r, rep = self._sample()
        dd = rep.to_dict()
        rep2 = QuarterlySummaryReportData.from_dict(dd)
        self.assertEqual(rep2.quarterly_verdict, rep.quarterly_verdict)
        self.assertEqual(rep2.months_covered, rep.months_covered)
        self.assertAlmostEqual(rep2.apy_stats.mean, rep.apy_stats.mean)

    def test_stats_round_trip(self):
        s = QuarterlyStats("m", [1.0, 2.0], 1.5, 1.0, 2.0, "RISING")
        s2 = QuarterlyStats.from_dict(s.to_dict())
        self.assertEqual(s2.metric_name, "m")
        self.assertEqual(s2.values, [1.0, 2.0])
        self.assertEqual(s2.trend, "RISING")

    def test_from_dict_defaults(self):
        rep = QuarterlySummaryReportData.from_dict({})
        self.assertFalse(rep.available)
        self.assertEqual(rep.quarterly_verdict, _VERDICT_POOR)

    def test_from_dict_bad_distribution(self):
        rep = QuarterlySummaryReportData.from_dict({"verdict_distribution": {"GOOD": "x"}})
        self.assertEqual(rep.verdict_distribution, {})

    def test_to_dict_generates_if_none(self):
        d = tempfile.mkdtemp()
        _write_monthly(d, [_make_month()])
        r = QuarterlySummaryReport(data_path=d)
        dd = r.to_dict()  # no report passed
        self.assertIn("quarterly_verdict", dd)


# ---------------------------------------------------------------------------
# CLI via subprocess
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def _run(self, extra_args):
        repo_root = str(Path(__file__).resolve().parents[2])
        cmd = [sys.executable, "-m", _MODULE] + extra_args
        return subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True, timeout=60
        )

    def test_check_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(["--check", "--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_check_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(["--check", "--data-dir", d])
            self.assertFalse((Path(d) / _OUTPUT_FILENAME).exists())

    def test_run_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            res = self._run(["--run", "--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_run_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            self._run(["--run", "--data-dir", d])
            self.assertTrue((Path(d) / _OUTPUT_FILENAME).exists())

    def test_default_no_flag_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(["--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_run_output_valid_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            _write_monthly(d, [_make_month()])
            self._run(["--run", "--data-dir", d])
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                json.load(fh)  # must not raise


if __name__ == "__main__":
    unittest.main()
