"""
Tests for spa_core/analytics/daily_digest.py — MP-587

Groups:
    TestDailyDigestInit             (5  tests)
    TestLoadJson                    (8  tests)
    TestCollectData                 (10 tests)
    TestExtractMonitor              (12 tests)
    TestExtractProgress             (10 tests)
    TestExtractTopOpportunities     (10 tests)
    TestExtractRiskFlags            (10 tests)
    TestExtractWorstCase            (8  tests)
    TestExtractAttribution          (8  tests)
    TestExtractWithdrawalCount      (7  tests)
    TestBuildSummary                (15 tests)
    TestFormatTelegramMessage       (12 tests)
    TestSaveDigest                  (12 tests)
    TestRun                         (7  tests)
    TestSafeFloat                   (6  tests)
    TestImportHygiene               (4  tests)

Total: ≥ 144 tests (well above the 80-test requirement)
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — ensure the repo root is importable from tests/
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.daily_digest import (
    DailyDigest,
    DIGEST_FILENAME,
    RING_BUFFER_SIZE,
    _safe_float,
    _TELEGRAM_MAX_CHARS,
    _STATUS_BREACH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_digest(tmp_path: Path) -> DailyDigest:
    return DailyDigest(data_dir=str(tmp_path))


def write_json(tmp_path: Path, filename: str, data) -> None:
    (tmp_path / filename).write_text(json.dumps(data), encoding="utf-8")


def _monitor_snapshot(
    summary_level="OK",
    equity=100_000.0,
    alerts=None,
):
    return {
        "generated_at": "2026-06-13T08:00:00+00:00",
        "equity": equity,
        "summary_level": summary_level,
        "alerts": alerts if alerts is not None else [],
    }


def _progress_data(
    paper_days=3,
    apy=3.5,
    days_to_golive=30,
    verdict="on_track",
):
    return {
        "paper_days": paper_days,
        "apy_today_pct": apy,
        "days_to_golive": days_to_golive,
        "summary_verdict": verdict,
    }


def _forecasts_data(adapters=None):
    if adapters is None:
        adapters = {
            "aave_v3": {"forecast_apy": 3.5, "confidence": "medium"},
            "compound_v3": {"forecast_apy": 4.8, "confidence": "high"},
            "morpho": {"forecast_apy": 6.5, "confidence": "high"},
        }
    return {"generated_at": "2026-06-13T00:00:00Z", "forecasts": adapters}


def _risk_budget_report(breach_ids=None):
    details = []
    for aid in (breach_ids or []):
        details.append({"adapter_id": aid, "status": "BREACH"})
    return {"history": [{"generated_at": "2026-06-13T00:00:00Z", "adapter_details": details}]}


def _scenario_report(worst_name="black_swan", worst_return=-42.0):
    return {
        "history": [
            {
                "generated_at": "2026-06-13T00:00:00Z",
                "worst_case": {
                    "scenario_name": worst_name,
                    "portfolio_return_pct": worst_return,
                },
            }
        ]
    }


def _attribution_report(available=True, total_active=0.0123):
    return {
        "history": [
            {
                "generated_at": "2026-06-13T00:00:00Z",
                "available": available,
                "total_active_return": total_active,
            }
        ]
    }


def _withdrawal_history(n=5):
    return [{"recorded_at": f"2026-06-{i+1:02d}T00:00:00Z", "amount_usd": 1000.0} for i in range(n)]


# ===========================================================================
# 1. Init tests (5)
# ===========================================================================

class TestDailyDigestInit(unittest.TestCase):

    def test_default_data_dir(self):
        dd = DailyDigest()
        self.assertEqual(str(dd.data_dir), "data")

    def test_custom_data_dir_str(self):
        dd = DailyDigest(data_dir="/tmp/spa_test_digest")
        self.assertEqual(str(dd.data_dir), "/tmp/spa_test_digest")

    def test_data_dir_is_path_object(self):
        dd = DailyDigest(data_dir="/tmp/spa_test_digest")
        self.assertIsInstance(dd.data_dir, Path)

    def test_data_dir_path_object_input(self):
        p = Path("/tmp/spa_test")
        dd = DailyDigest(data_dir=str(p))
        self.assertEqual(dd.data_dir, p)

    def test_constant_digest_filename(self):
        self.assertEqual(DIGEST_FILENAME, "daily_digest.json")


# ===========================================================================
# 2. _load_json tests (8)
# ===========================================================================

class TestLoadJson(unittest.TestCase):

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            self.assertIsNone(dd._load_json("nonexistent.json"))

    def test_valid_dict_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "test.json", {"key": "value"})
            dd = make_digest(p)
            result = dd._load_json("test.json")
            self.assertEqual(result, {"key": "value"})

    def test_valid_list_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "test.json", [1, 2, 3])
            dd = make_digest(p)
            self.assertEqual(dd._load_json("test.json"), [1, 2, 3])

    def test_empty_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "empty.json").write_text("", encoding="utf-8")
            dd = make_digest(p)
            self.assertIsNone(dd._load_json("empty.json"))

    def test_malformed_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "bad.json").write_text("{not valid json", encoding="utf-8")
            dd = make_digest(p)
            self.assertIsNone(dd._load_json("bad.json"))

    def test_unicode_content(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "unicode.json", {"name": "Ривень"})
            dd = make_digest(p)
            self.assertEqual(dd._load_json("unicode.json"), {"name": "Ривень"})

    def test_nested_structure(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            data = {"history": [{"a": 1}, {"b": 2}]}
            write_json(p, "nested.json", data)
            dd = make_digest(p)
            self.assertEqual(dd._load_json("nested.json"), data)

    def test_returns_none_for_directory_path(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            # "." is a directory — should return None gracefully
            self.assertIsNone(dd._load_json("."))


# ===========================================================================
# 3. collect_data tests (10)
# ===========================================================================

class TestCollectData(unittest.TestCase):

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.collect_data()
            self.assertIsInstance(result, dict)

    def test_all_keys_present(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.collect_data()
            expected_keys = {"date", "monitor", "forecasts", "scenario",
                             "attribution", "risk_budget", "withdrawal", "progress"}
            self.assertEqual(set(result.keys()), expected_keys)

    def test_missing_files_yield_none(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.collect_data()
            for k in ("monitor", "forecasts", "scenario", "attribution",
                      "risk_budget", "withdrawal", "progress"):
                self.assertIsNone(result[k], f"{k} should be None when file absent")

    def test_explicit_date_str(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.collect_data(date_str="2026-01-01")
            self.assertEqual(result["date"], "2026-01-01")

    def test_default_date_is_today_format(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.collect_data()
            # Should be YYYY-MM-DD
            parts = result["date"].split("-")
            self.assertEqual(len(parts), 3)
            self.assertEqual(len(parts[0]), 4)

    def test_monitor_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "monitor_snapshots.json", [_monitor_snapshot()])
            dd = make_digest(p)
            result = dd.collect_data()
            self.assertIsNotNone(result["monitor"])

    def test_forecasts_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "apy_forecasts.json", _forecasts_data())
            dd = make_digest(p)
            result = dd.collect_data()
            self.assertIsNotNone(result["forecasts"])

    def test_progress_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "progress_tracker.json", _progress_data())
            dd = make_digest(p)
            result = dd.collect_data()
            self.assertIsNotNone(result["progress"])

    def test_partial_files_no_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "progress_tracker.json", _progress_data())
            # others absent
            dd = make_digest(p)
            result = dd.collect_data()
            self.assertIsNone(result["monitor"])
            self.assertIsNotNone(result["progress"])

    def test_all_files_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "monitor_snapshots.json", [_monitor_snapshot()])
            write_json(p, "apy_forecasts.json", _forecasts_data())
            write_json(p, "scenario_report.json", _scenario_report())
            write_json(p, "attribution_report.json", _attribution_report())
            write_json(p, "risk_budget_report.json", _risk_budget_report())
            write_json(p, "withdrawal_history.json", _withdrawal_history())
            write_json(p, "progress_tracker.json", _progress_data())
            dd = make_digest(p)
            result = dd.collect_data()
            for k in ("monitor", "forecasts", "scenario", "attribution",
                      "risk_budget", "withdrawal", "progress"):
                self.assertIsNotNone(result[k])


# ===========================================================================
# 4. _extract_monitor tests (12)
# ===========================================================================

class TestExtractMonitor(unittest.TestCase):

    def _call(self, monitor_data):
        dd = DailyDigest()
        return dd._extract_monitor(monitor_data)

    def test_none_returns_defaults(self):
        health, equity, alerts = self._call(None)
        self.assertEqual(health, "UNKNOWN")
        self.assertEqual(equity, 0.0)
        self.assertEqual(alerts, 0)

    def test_empty_list_returns_defaults(self):
        health, equity, alerts = self._call([])
        self.assertEqual(health, "UNKNOWN")

    def test_health_ok(self):
        snap = _monitor_snapshot(summary_level="OK")
        health, _, _ = self._call([snap])
        self.assertEqual(health, "OK")

    def test_health_warning(self):
        snap = _monitor_snapshot(summary_level="WARNING")
        health, _, _ = self._call([snap])
        self.assertEqual(health, "WARNING")

    def test_health_critical(self):
        snap = _monitor_snapshot(summary_level="CRITICAL")
        health, _, _ = self._call([snap])
        self.assertEqual(health, "CRITICAL")

    def test_health_warn_substring(self):
        snap = _monitor_snapshot(summary_level="WARN")
        health, _, _ = self._call([snap])
        self.assertEqual(health, "WARNING")

    def test_equity_extracted(self):
        snap = _monitor_snapshot(equity=123456.78)
        _, equity, _ = self._call([snap])
        self.assertAlmostEqual(equity, 123456.78)

    def test_alerts_count_from_list(self):
        snap = _monitor_snapshot(alerts=[{"level": "WARN"}, {"level": "WARN"}])
        _, _, alerts = self._call([snap])
        self.assertEqual(alerts, 2)

    def test_alerts_zero_when_empty(self):
        snap = _monitor_snapshot(alerts=[])
        _, _, alerts = self._call([snap])
        self.assertEqual(alerts, 0)

    def test_uses_last_snapshot(self):
        snap_old = _monitor_snapshot(equity=50_000.0, summary_level="WARNING")
        snap_new = _monitor_snapshot(equity=100_000.0, summary_level="OK")
        _, equity, _ = self._call([snap_old, snap_new])
        self.assertAlmostEqual(equity, 100_000.0)

    def test_single_dict_input(self):
        snap = _monitor_snapshot(equity=99_999.0)
        _, equity, _ = self._call(snap)
        self.assertAlmostEqual(equity, 99_999.0)

    def test_invalid_equity_defaults_zero(self):
        snap = _monitor_snapshot()
        snap["equity"] = "bad"
        _, equity, _ = self._call([snap])
        self.assertEqual(equity, 0.0)


# ===========================================================================
# 5. _extract_progress tests (10)
# ===========================================================================

class TestExtractProgress(unittest.TestCase):

    def _call(self, progress_data):
        dd = DailyDigest()
        return dd._extract_progress(progress_data)

    def test_none_returns_defaults(self):
        apy, dtg, pd, sv = self._call(None)
        self.assertEqual(apy, 0.0)
        self.assertIsNone(dtg)
        self.assertEqual(pd, 0)
        self.assertEqual(sv, "unknown")

    def test_extracts_apy(self):
        apy, _, _, _ = self._call(_progress_data(apy=5.25))
        self.assertAlmostEqual(apy, 5.25)

    def test_extracts_days_to_golive(self):
        _, dtg, _, _ = self._call(_progress_data(days_to_golive=42))
        self.assertEqual(dtg, 42)

    def test_extracts_paper_days(self):
        _, _, pd, _ = self._call(_progress_data(paper_days=15))
        self.assertEqual(pd, 15)

    def test_extracts_verdict(self):
        _, _, _, sv = self._call(_progress_data(verdict="behind"))
        self.assertEqual(sv, "behind")

    def test_none_days_to_golive(self):
        data = _progress_data()
        del data["days_to_golive"]
        _, dtg, _, _ = self._call(data)
        self.assertIsNone(dtg)

    def test_invalid_apy_defaults_zero(self):
        data = _progress_data()
        data["apy_today_pct"] = "bad"
        apy, _, _, _ = self._call(data)
        self.assertEqual(apy, 0.0)

    def test_invalid_paper_days_defaults_zero(self):
        data = _progress_data()
        data["paper_days"] = None
        _, _, pd, _ = self._call(data)
        self.assertEqual(pd, 0)

    def test_string_input_returns_defaults(self):
        apy, dtg, pd, sv = self._call("not a dict")
        self.assertEqual(apy, 0.0)
        self.assertIsNone(dtg)

    def test_zero_days_to_golive(self):
        _, dtg, _, _ = self._call(_progress_data(days_to_golive=0))
        self.assertEqual(dtg, 0)


# ===========================================================================
# 6. _extract_top_opportunities tests (10)
# ===========================================================================

class TestExtractTopOpportunities(unittest.TestCase):

    def _call(self, data, n=3):
        dd = DailyDigest()
        return dd._extract_top_opportunities(data, n=n)

    def test_none_returns_empty(self):
        self.assertEqual(self._call(None), [])

    def test_missing_forecasts_key_returns_empty(self):
        self.assertEqual(self._call({"generated_at": "..."}), [])

    def test_returns_top_n(self):
        fc = _forecasts_data({
            "a": {"forecast_apy": 1.0, "confidence": "low"},
            "b": {"forecast_apy": 10.0, "confidence": "high"},
            "c": {"forecast_apy": 5.0, "confidence": "medium"},
            "d": {"forecast_apy": 20.0, "confidence": "high"},
        })
        result = self._call(fc, n=3)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0]["forecast_apy"], 20.0)

    def test_sorted_descending(self):
        fc = _forecasts_data({
            "x": {"forecast_apy": 3.0},
            "y": {"forecast_apy": 7.0},
            "z": {"forecast_apy": 1.0},
        })
        result = self._call(fc, n=3)
        apys = [r["forecast_apy"] for r in result]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_fewer_than_n_adapters(self):
        fc = _forecasts_data({"a": {"forecast_apy": 5.0}})
        result = self._call(fc, n=3)
        self.assertEqual(len(result), 1)

    def test_result_has_required_keys(self):
        fc = _forecasts_data()
        result = self._call(fc)
        for item in result:
            self.assertIn("adapter_id", item)
            self.assertIn("forecast_apy", item)
            self.assertIn("confidence", item)

    def test_invalid_apy_treated_as_zero(self):
        fc = _forecasts_data({"bad": {"forecast_apy": "xxx"}})
        result = self._call(fc)
        self.assertEqual(result[0]["forecast_apy"], 0.0)

    def test_non_dict_value_skipped(self):
        fc = {"forecasts": {"a": "not_a_dict", "b": {"forecast_apy": 5.0}}}
        result = self._call(fc)
        self.assertEqual(len(result), 1)

    def test_n_zero_returns_empty(self):
        fc = _forecasts_data()
        result = self._call(fc, n=0)
        self.assertEqual(result, [])

    def test_confidence_field_preserved(self):
        fc = _forecasts_data({"a": {"forecast_apy": 5.0, "confidence": "high"}})
        result = self._call(fc)
        self.assertEqual(result[0]["confidence"], "high")


# ===========================================================================
# 7. _extract_risk_flags tests (10)
# ===========================================================================

class TestExtractRiskFlags(unittest.TestCase):

    def _call(self, data):
        dd = DailyDigest()
        return dd._extract_risk_flags(data)

    def test_none_returns_empty(self):
        self.assertEqual(self._call(None), [])

    def test_no_breaches(self):
        data = _risk_budget_report(breach_ids=[])
        self.assertEqual(self._call(data), [])

    def test_single_breach(self):
        data = _risk_budget_report(breach_ids=["aave_v3"])
        flags = self._call(data)
        self.assertIn("aave_v3", flags)

    def test_multiple_breaches(self):
        data = _risk_budget_report(breach_ids=["aave_v3", "compound_v3"])
        flags = self._call(data)
        self.assertEqual(len(flags), 2)
        self.assertIn("aave_v3", flags)
        self.assertIn("compound_v3", flags)

    def test_warning_not_included(self):
        data = {"history": [{"adapter_details": [
            {"adapter_id": "ok_adapter", "status": "OK"},
            {"adapter_id": "warn_adapter", "status": "WARNING"},
        ]}]}
        flags = self._call(data)
        self.assertEqual(flags, [])

    def test_no_history_key_uses_root(self):
        data = {"adapter_details": [{"adapter_id": "breach_adapter", "status": "BREACH"}]}
        flags = self._call(data)
        self.assertIn("breach_adapter", flags)

    def test_empty_history_returns_empty(self):
        data = {"history": []}
        flags = self._call(data)
        self.assertEqual(flags, [])

    def test_uses_latest_history_entry(self):
        data = {"history": [
            {"adapter_details": [{"adapter_id": "old_breach", "status": "BREACH"}]},
            {"adapter_details": []},
        ]}
        flags = self._call(data)
        self.assertEqual(flags, [])

    def test_no_adapter_details_key_returns_empty(self):
        data = {"history": [{"generated_at": "2026-01-01"}]}
        flags = self._call(data)
        self.assertEqual(flags, [])

    def test_deduplicated_flags(self):
        data = {"history": [{"adapter_details": [
            {"adapter_id": "aave", "status": "BREACH"},
            {"adapter_id": "aave", "status": "BREACH"},
        ]}]}
        flags = self._call(data)
        self.assertEqual(flags.count("aave"), 1)


# ===========================================================================
# 8. _extract_worst_case tests (8)
# ===========================================================================

class TestExtractWorstCase(unittest.TestCase):

    def _call(self, data):
        dd = DailyDigest()
        return dd._extract_worst_case(data)

    def test_none_returns_empty_dict(self):
        self.assertEqual(self._call(None), {})

    def test_empty_history_returns_empty_dict(self):
        self.assertEqual(self._call({"history": []}), {})

    def test_extracts_worst_case(self):
        data = _scenario_report("black_swan", -42.0)
        result = self._call(data)
        self.assertEqual(result["scenario_name"], "black_swan")
        self.assertAlmostEqual(result["portfolio_return_pct"], -42.0)

    def test_uses_latest_history_entry(self):
        data = {"history": [
            {"worst_case": {"scenario_name": "old", "portfolio_return_pct": -10.0}},
            {"worst_case": {"scenario_name": "new", "portfolio_return_pct": -99.0}},
        ]}
        result = self._call(data)
        self.assertEqual(result["scenario_name"], "new")

    def test_missing_worst_case_returns_empty(self):
        data = {"history": [{"generated_at": "2026-01-01"}]}
        result = self._call(data)
        self.assertEqual(result, {})

    def test_direct_report_no_history(self):
        data = {"worst_case": {"scenario_name": "bear", "portfolio_return_pct": -20.0}}
        result = self._call(data)
        self.assertEqual(result["scenario_name"], "bear")

    def test_invalid_return_pct_defaults_zero(self):
        data = {"history": [{"worst_case": {"scenario_name": "x", "portfolio_return_pct": "bad"}}]}
        result = self._call(data)
        self.assertAlmostEqual(result["portfolio_return_pct"], 0.0)

    def test_result_has_required_keys(self):
        data = _scenario_report()
        result = self._call(data)
        self.assertIn("scenario_name", result)
        self.assertIn("portfolio_return_pct", result)


# ===========================================================================
# 9. _extract_attribution tests (8)
# ===========================================================================

class TestExtractAttribution(unittest.TestCase):

    def _call(self, data):
        dd = DailyDigest()
        return dd._extract_attribution(data)

    def test_none_returns_defaults(self):
        available, total = self._call(None)
        self.assertFalse(available)
        self.assertEqual(total, 0.0)

    def test_available_true(self):
        data = _attribution_report(available=True, total_active=0.05)
        available, _ = self._call(data)
        self.assertTrue(available)

    def test_available_false(self):
        data = _attribution_report(available=False)
        available, _ = self._call(data)
        self.assertFalse(available)

    def test_total_active_return_extracted(self):
        data = _attribution_report(total_active=0.0234)
        _, total = self._call(data)
        self.assertAlmostEqual(total, 0.0234)

    def test_negative_active_return(self):
        data = _attribution_report(total_active=-0.015)
        _, total = self._call(data)
        self.assertAlmostEqual(total, -0.015)

    def test_uses_latest_history(self):
        data = {"history": [
            {"available": True, "total_active_return": 0.01},
            {"available": True, "total_active_return": 0.09},
        ]}
        _, total = self._call(data)
        self.assertAlmostEqual(total, 0.09)

    def test_invalid_total_defaults_zero(self):
        data = {"history": [{"available": True, "total_active_return": "x"}]}
        _, total = self._call(data)
        self.assertEqual(total, 0.0)

    def test_no_history_key_uses_root_dict(self):
        data = {"available": True, "total_active_return": 0.007}
        available, total = self._call(data)
        self.assertTrue(available)
        self.assertAlmostEqual(total, 0.007)


# ===========================================================================
# 10. _extract_withdrawal_count tests (7)
# ===========================================================================

class TestExtractWithdrawalCount(unittest.TestCase):

    def _call(self, data):
        dd = DailyDigest()
        return dd._extract_withdrawal_count(data)

    def test_none_returns_zero(self):
        self.assertEqual(self._call(None), 0)

    def test_list_returns_len(self):
        self.assertEqual(self._call(_withdrawal_history(5)), 5)

    def test_empty_list_returns_zero(self):
        self.assertEqual(self._call([]), 0)

    def test_dict_with_history_key(self):
        data = {"history": _withdrawal_history(3)}
        self.assertEqual(self._call(data), 3)

    def test_dict_with_entries_key(self):
        data = {"entries": _withdrawal_history(4)}
        self.assertEqual(self._call(data), 4)

    def test_dict_with_count_key(self):
        data = {"count": 7}
        self.assertEqual(self._call(data), 7)

    def test_unrecognised_dict_returns_zero(self):
        data = {"something_else": "value"}
        self.assertEqual(self._call(data), 0)


# ===========================================================================
# 11. build_summary tests (15)
# ===========================================================================

class TestBuildSummary(unittest.TestCase):

    def _full_data(self, tmp_path):
        p = Path(tmp_path)
        write_json(p, "monitor_snapshots.json", [_monitor_snapshot(summary_level="OK", equity=100_000.0)])
        write_json(p, "apy_forecasts.json", _forecasts_data())
        write_json(p, "scenario_report.json", _scenario_report())
        write_json(p, "attribution_report.json", _attribution_report())
        write_json(p, "risk_budget_report.json", _risk_budget_report())
        write_json(p, "withdrawal_history.json", _withdrawal_history(3))
        write_json(p, "progress_tracker.json", _progress_data())
        dd = make_digest(p)
        return dd.collect_data()

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            dd = DailyDigest()
            summary = dd.build_summary({"date": "2026-06-13"})
            self.assertIsInstance(summary, dict)

    def test_required_keys_present(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            required = {
                "date", "generated_at", "portfolio_health", "equity_usd",
                "apy_today_pct", "top_opportunities", "risk_flags",
                "scenario_worst_case", "active_alerts", "days_to_golive",
                "attribution_active", "total_active_return",
                "withdrawal_count", "paper_days", "summary_verdict",
            }
            self.assertTrue(required.issubset(set(summary.keys())))

    def test_portfolio_health_ok(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertEqual(summary["portfolio_health"], "OK")

    def test_equity_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertAlmostEqual(summary["equity_usd"], 100_000.0)

    def test_top_opportunities_count(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertLessEqual(len(summary["top_opportunities"]), 3)

    def test_days_to_golive_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertEqual(summary["days_to_golive"], 30)

    def test_paper_days_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertEqual(summary["paper_days"], 3)

    def test_withdrawal_count_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._full_data(td)
            dd = make_digest(Path(td))
            summary = dd.build_summary(data)
            self.assertEqual(summary["withdrawal_count"], 3)

    def test_generated_at_is_iso_string(self):
        dd = DailyDigest()
        summary = dd.build_summary({"date": "2026-06-13"})
        gen = summary["generated_at"]
        self.assertIsInstance(gen, str)
        self.assertTrue(gen.endswith("+00:00") or "Z" in gen or "T" in gen)

    def test_no_data_yields_safe_defaults(self):
        dd = DailyDigest()
        summary = dd.build_summary({"date": "2026-06-13"})
        self.assertEqual(summary["portfolio_health"], "UNKNOWN")
        self.assertEqual(summary["equity_usd"], 0.0)
        self.assertEqual(summary["active_alerts"], 0)
        self.assertEqual(summary["risk_flags"], [])
        self.assertEqual(summary["top_opportunities"], [])
        self.assertEqual(summary["scenario_worst_case"], {})

    def test_risk_flags_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "risk_budget_report.json", _risk_budget_report(breach_ids=["aave_v3"]))
            dd = make_digest(p)
            data = dd.collect_data()
            summary = dd.build_summary(data)
            self.assertIn("aave_v3", summary["risk_flags"])

    def test_date_preserved(self):
        dd = DailyDigest()
        summary = dd.build_summary({"date": "2026-01-01"})
        self.assertEqual(summary["date"], "2026-01-01")

    def test_attribution_active_true(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "attribution_report.json", _attribution_report(available=True))
            dd = make_digest(p)
            data = dd.collect_data()
            summary = dd.build_summary(data)
            self.assertTrue(summary["attribution_active"])

    def test_scenario_worst_case_populated(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "scenario_report.json", _scenario_report("black_swan", -42.0))
            dd = make_digest(p)
            data = dd.collect_data()
            summary = dd.build_summary(data)
            self.assertEqual(summary["scenario_worst_case"]["scenario_name"], "black_swan")

    def test_summary_verdict_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "progress_tracker.json", _progress_data(verdict="on_track"))
            dd = make_digest(p)
            data = dd.collect_data()
            summary = dd.build_summary(data)
            self.assertEqual(summary["summary_verdict"], "on_track")


# ===========================================================================
# 12. format_telegram_message tests (12)
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):

    def _default_summary(self):
        dd = DailyDigest()
        return dd.build_summary({
            "date": "2026-06-13",
            "monitor": [_monitor_snapshot(summary_level="OK", equity=100_000.0)],
            "forecasts": _forecasts_data(),
            "scenario": _scenario_report(),
            "attribution": _attribution_report(),
            "risk_budget": _risk_budget_report(),
            "withdrawal": _withdrawal_history(2),
            "progress": _progress_data(),
        })

    def test_returns_string(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertIsInstance(msg, str)

    def test_within_telegram_limit(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_contains_date(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertIn("2026-06-13", msg)

    def test_contains_health(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertIn("OK", msg)

    def test_contains_equity(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertIn("100,000", msg)

    def test_contains_top_opportunity(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        # morpho has highest APY at 6.5%
        self.assertIn("morpho", msg)

    def test_contains_scenario_name(self):
        dd = DailyDigest()
        msg = dd.format_telegram_message(self._default_summary())
        self.assertIn("black_swan", msg)

    def test_warning_health_emoji(self):
        dd = DailyDigest()
        summary = {**self._default_summary(), "portfolio_health": "WARNING"}
        msg = dd.format_telegram_message(summary)
        self.assertIn("WARNING", msg)

    def test_critical_health_emoji(self):
        dd = DailyDigest()
        summary = {**self._default_summary(), "portfolio_health": "CRITICAL"}
        msg = dd.format_telegram_message(summary)
        self.assertIn("CRITICAL", msg)

    def test_risk_flags_shown_when_present(self):
        dd = DailyDigest()
        summary = {**self._default_summary(), "risk_flags": ["aave_v3"]}
        msg = dd.format_telegram_message(summary)
        self.assertIn("aave_v3", msg)

    def test_long_message_truncated(self):
        dd = DailyDigest()
        # Produce a very long summary by injecting huge strings
        summary = self._default_summary()
        summary["risk_flags"] = [f"adapter_{i}" for i in range(500)]
        msg = dd.format_telegram_message(summary)
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_no_data_does_not_raise(self):
        dd = DailyDigest()
        summary = dd.build_summary({"date": "2026-06-13"})
        try:
            msg = dd.format_telegram_message(summary)
        except Exception as exc:
            self.fail(f"format_telegram_message raised {exc}")
        self.assertIsInstance(msg, str)


# ===========================================================================
# 13. save_digest tests (12)
# ===========================================================================

class TestSaveDigest(unittest.TestCase):

    def _summary(self, date="2026-06-13"):
        dd = DailyDigest()
        return dd.build_summary({"date": date})

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary())
            self.assertTrue((p / DIGEST_FILENAME).exists())

    def test_returns_path_string(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            result = dd.save_digest(self._summary())
            self.assertIsInstance(result, str)
            self.assertTrue(result.endswith(DIGEST_FILENAME))

    def test_creates_data_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = Path(td) / "nested" / "data"
            dd = make_digest(new_dir)
            dd.save_digest(self._summary())
            self.assertTrue((new_dir / DIGEST_FILENAME).exists())

    def test_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary())
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)

    def test_history_key_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary())
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertIn("history", data)

    def test_digest_count_increments(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary("2026-06-13"))
            dd.save_digest(self._summary("2026-06-14"))
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertEqual(data["digest_count"], 2)

    def test_ring_buffer_trims_to_max(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            for i in range(RING_BUFFER_SIZE + 5):
                dd.save_digest(self._summary(f"2026-01-{i+1:02d}"))
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertLessEqual(len(data["history"]), RING_BUFFER_SIZE)

    def test_no_tmp_files_leftover(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary())
            tmp_files = list(p.glob(".daily_digest_tmp_*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_last_updated_key_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary())
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertIn("last_updated", data)

    def test_preserves_summary_contents(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            s = self._summary("2026-06-13")
            dd.save_digest(s)
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertEqual(data["history"][-1]["date"], "2026-06-13")

    def test_appends_to_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.save_digest(self._summary("2026-06-13"))
            dd.save_digest(self._summary("2026-06-14"))
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            dates = [h["date"] for h in data["history"]]
            self.assertIn("2026-06-13", dates)
            self.assertIn("2026-06-14", dates)

    def test_malformed_existing_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / DIGEST_FILENAME).write_text("not json at all", encoding="utf-8")
            dd = make_digest(p)
            try:
                dd.save_digest(self._summary())
            except Exception as exc:
                self.fail(f"save_digest raised on malformed file: {exc}")


# ===========================================================================
# 14. run tests (7)
# ===========================================================================

class TestRun(unittest.TestCase):

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.run()
            self.assertIsInstance(result, dict)

    def test_creates_digest_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.run()
            self.assertTrue((p / DIGEST_FILENAME).exists())

    def test_summary_has_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.run()
            self.assertIn("portfolio_health", result)
            self.assertIn("top_opportunities", result)
            self.assertIn("risk_flags", result)

    def test_date_str_passed_through(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            result = dd.run(date_str="2026-01-15")
            self.assertEqual(result["date"], "2026-01-15")

    def test_with_all_data_files(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            write_json(p, "monitor_snapshots.json", [_monitor_snapshot()])
            write_json(p, "apy_forecasts.json", _forecasts_data())
            write_json(p, "scenario_report.json", _scenario_report())
            write_json(p, "attribution_report.json", _attribution_report())
            write_json(p, "risk_budget_report.json", _risk_budget_report())
            write_json(p, "withdrawal_history.json", _withdrawal_history())
            write_json(p, "progress_tracker.json", _progress_data())
            dd = make_digest(p)
            result = dd.run()
            self.assertEqual(result["portfolio_health"], "OK")

    def test_run_twice_creates_two_history_entries(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            dd = make_digest(p)
            dd.run(date_str="2026-06-13")
            dd.run(date_str="2026-06-14")
            with open(p / DIGEST_FILENAME) as f:
                data = json.load(f)
            self.assertEqual(data["digest_count"], 2)

    def test_run_no_errors_on_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            dd = make_digest(Path(td))
            try:
                dd.run()
            except Exception as exc:
                self.fail(f"run() raised unexpectedly: {exc}")


# ===========================================================================
# 15. _safe_float tests (6)
# ===========================================================================

class TestSafeFloat(unittest.TestCase):

    def test_int_value(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float_value(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_string_number(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_returns_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_bad_string_returns_default(self):
        self.assertEqual(_safe_float("bad"), 0.0)

    def test_custom_default(self):
        self.assertEqual(_safe_float("x", default=99.9), 99.9)


# ===========================================================================
# 16. Import hygiene tests (4)
# ===========================================================================

class TestImportHygiene(unittest.TestCase):

    def _module_source(self):
        import spa_core.analytics.daily_digest as m
        return Path(m.__file__).read_text(encoding="utf-8")

    def test_no_requests_import(self):
        src = self._module_source()
        self.assertNotIn("import requests", src)

    def test_no_numpy_import(self):
        src = self._module_source()
        self.assertNotIn("import numpy", src)

    def test_no_external_sdk_import(self):
        src = self._module_source()
        self.assertNotIn("import openai", src)
        self.assertNotIn("import anthropic", src)

    def test_no_execution_import(self):
        src = self._module_source()
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("import spa_core.execution", src)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
