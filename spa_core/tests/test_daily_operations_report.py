"""
Tests for DailyOperationsReport (MP-606).

Groups:
    TestSafeLoad              (8)  — _safe_load edge cases
    TestIsFresh               (10) — _is_fresh timestamp logic
    TestBuildRiskSection      (8)  — _build_risk_section
    TestBuildYieldSection     (8)  — _build_yield_section
    TestBuildChainsSection    (8)  — _build_chains_section
    TestBuildStrategiesSection(6)  — _build_strategies_section
    TestBuildPegSection       (6)  — _build_peg_section
    TestDetermineOverallStatus(8)  — _determine_overall_status
    TestGenerateActionItems   (8)  — _generate_action_items
    TestGenerate              (6)  — generate()
    TestSave                  (4)  — save() atomicity + ring-buffer
    TestFormatTelegramMessage (6)  — format_telegram_message()
    TestFormatSummary         (4)  — format_summary()

Total: 90 tests.

Run:
    python3 -m unittest spa_core.tests.test_daily_operations_report -v
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.analytics.daily_operations_report import (
    DailyOperationsReport,
    DailyOpsReport,
    OpsReportSection,
    _STATUS_OK,
    _STATUS_WARNING,
    _STATUS_CRITICAL,
    _STATUS_UNKNOWN,
    _OVERALL_OPERATIONAL,
    _OVERALL_DEGRADED,
    _OVERALL_CRITICAL,
    _RING_BUFFER_MAX,
    _TELEGRAM_MAX_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(directory: str, filename: str, data: dict) -> None:
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _fresh_ts() -> str:
    """ISO timestamp that is less than 1 minute old."""
    return datetime.now(timezone.utc).isoformat()


def _stale_ts() -> str:
    """ISO timestamp that is 4 hours old (stale by default 2h threshold)."""
    return (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()


def _make_reporter(tmpdir: str) -> DailyOperationsReport:
    return DailyOperationsReport(data_path=tmpdir)


def _make_integrated_risk(level: str = "GREEN",
                           critical: int = 0,
                           warning: int = 0,
                           top_risk: str = "All systems normal",
                           ts: str | None = None) -> dict:
    return {
        "updated_at": ts or _fresh_ts(),
        "latest": {
            "generated_at": ts or _fresh_ts(),
            "overall_level": level,
            "critical_count": critical,
            "warning_count": warning,
            "top_risk": top_risk,
            "recommendations": [f"Rec for {level}"],
        },
    }


def _make_yield_tracker(allocated: float = 95000.0,
                         apy: float = 5.22,
                         daily: float = 14.30,
                         contributor: str = "compound_v3",
                         ts: str | None = None) -> dict:
    return {
        "last_updated": ts or _fresh_ts(),
        "latest": {
            "generated_at": ts or _fresh_ts(),
            "total_allocated_usd": allocated,
            "effective_apy_pct": apy,
            "total_daily_yield_usd": daily,
            "top_contributor": contributor,
        },
    }


def _make_multi_chain(best_chain: str = "ethereum",
                       best_apy: float = 12.0,
                       adapters: int = 34,
                       tvl: float = 18_000_000_000.0,
                       ts: str | None = None) -> dict:
    return {
        "generated_at": ts or _fresh_ts(),
        "latest": {
            "generated_at": ts or _fresh_ts(),
            "best_chain": best_chain,
            "best_apy_overall": best_apy,
            "total_adapters": adapters,
            "total_tvl_usd": tvl,
            "l2_premium_pct": -0.5,
        },
    }


def _make_tournament(winner: str = "S7",
                      winner_apy: float = 10.1,
                      count: int = 14,
                      ts: str | None = None) -> dict:
    strategies = [
        {
            "id": winner,
            "apy_realized": winner_apy,
            "name": f"{winner} Strategy",
        }
    ] + [{"id": f"S{i}", "apy_realized": None} for i in range(count - 1)]
    return {
        "generated_at": ts or _fresh_ts(),
        "winner": winner,
        "tournament_days": 3,
        "strategies": strategies,
    }


def _make_peg(overall: str = "GREEN",
               stable: int = 31,
               warning: int = 0,
               critical: int = 0,
               worst: str = "aave-v3",
               worst_dev: float = 0.0,
               ts: str | None = None) -> dict:
    return {
        "generated_at": ts or _fresh_ts(),
        "overall_status": overall,
        "stable": stable,
        "warning": warning,
        "critical": critical,
        "worst_adapter": worst,
        "worst_deviation_pct": worst_dev,
    }


def _make_paper_status(days: int = 24) -> dict:
    return {
        "is_demo": False,
        "days_running": days,
        "current_equity": 100000.0,
    }


# ---------------------------------------------------------------------------
# 1. TestSafeLoad (8 tests)
# ---------------------------------------------------------------------------

class TestSafeLoad(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_none(self):
        self.assertIsNone(self.reporter._safe_load("no_such_file.json"))

    def test_invalid_json_returns_none(self):
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("not valid json }{")
        self.assertIsNone(self.reporter._safe_load("bad.json"))

    def test_empty_file_returns_none(self):
        path = os.path.join(self.tmpdir, "empty.json")
        with open(path, "w") as f:
            f.write("")
        self.assertIsNone(self.reporter._safe_load("empty.json"))

    def test_json_array_returns_none(self):
        _write_json(self.tmpdir, "arr.json", [1, 2, 3])  # type: ignore[arg-type]
        # Lists are not dicts → None
        path = os.path.join(self.tmpdir, "arr.json")
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        self.assertIsNone(self.reporter._safe_load("arr.json"))

    def test_valid_dict_returns_dict(self):
        _write_json(self.tmpdir, "ok.json", {"key": "value"})
        result = self.reporter._safe_load("ok.json")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["key"], "value")

    def test_nested_dict_returned_intact(self):
        data = {"outer": {"inner": 42}}
        _write_json(self.tmpdir, "nested.json", data)
        result = self.reporter._safe_load("nested.json")
        self.assertEqual(result["outer"]["inner"], 42)

    def test_json_number_returns_none(self):
        path = os.path.join(self.tmpdir, "num.json")
        with open(path, "w") as f:
            f.write("123")
        self.assertIsNone(self.reporter._safe_load("num.json"))

    def test_json_null_returns_none(self):
        path = os.path.join(self.tmpdir, "null.json")
        with open(path, "w") as f:
            f.write("null")
        self.assertIsNone(self.reporter._safe_load("null.json"))


# ---------------------------------------------------------------------------
# 2. TestIsFresh (10 tests)
# ---------------------------------------------------------------------------

class TestIsFresh(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_none_data_returns_false(self):
        self.assertFalse(self.reporter._is_fresh(None))

    def test_fresh_generated_at_returns_true(self):
        data = {"generated_at": _fresh_ts()}
        self.assertTrue(self.reporter._is_fresh(data))

    def test_stale_generated_at_returns_false(self):
        data = {"generated_at": _stale_ts()}
        self.assertFalse(self.reporter._is_fresh(data))

    def test_fresh_updated_at_returns_true(self):
        data = {"updated_at": _fresh_ts()}
        self.assertTrue(self.reporter._is_fresh(data))

    def test_fresh_last_updated_returns_true(self):
        data = {"last_updated": _fresh_ts()}
        self.assertTrue(self.reporter._is_fresh(data))

    def test_fresh_timestamp_key_returns_true(self):
        data = {"timestamp": _fresh_ts()}
        self.assertTrue(self.reporter._is_fresh(data))

    def test_no_timestamp_key_returns_false(self):
        data = {"key": "value", "other": 123}
        self.assertFalse(self.reporter._is_fresh(data))

    def test_invalid_timestamp_string_returns_false(self):
        data = {"generated_at": "not-a-timestamp"}
        self.assertFalse(self.reporter._is_fresh(data))

    def test_latest_nested_generated_at_returns_true(self):
        data = {"latest": {"generated_at": _fresh_ts()}}
        self.assertTrue(self.reporter._is_fresh(data))

    def test_custom_max_age_hours_respected(self):
        # 30 minutes ago
        ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        data = {"generated_at": ts}
        # max_age_hours=0.25 (15 min) → stale
        self.assertFalse(self.reporter._is_fresh(data, max_age_hours=0.25))
        # max_age_hours=1.0 → fresh
        self.assertTrue(self.reporter._is_fresh(data, max_age_hours=1.0))


# ---------------------------------------------------------------------------
# 3. TestBuildRiskSection (8 tests)
# ---------------------------------------------------------------------------

class TestBuildRiskSection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_unknown(self):
        section = self.reporter._build_risk_section()
        self.assertEqual(section.name, "risk")
        self.assertEqual(section.status, _STATUS_UNKNOWN)
        self.assertFalse(section.data_fresh)

    def test_green_level_maps_to_ok(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("GREEN"))
        section = self.reporter._build_risk_section()
        self.assertEqual(section.status, _STATUS_OK)

    def test_yellow_level_maps_to_warning(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("YELLOW"))
        section = self.reporter._build_risk_section()
        self.assertEqual(section.status, _STATUS_WARNING)

    def test_orange_level_maps_to_warning(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("ORANGE"))
        section = self.reporter._build_risk_section()
        self.assertEqual(section.status, _STATUS_WARNING)

    def test_red_level_maps_to_critical(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("RED", critical=1, top_risk="depeg detected!"))
        section = self.reporter._build_risk_section()
        self.assertEqual(section.status, _STATUS_CRITICAL)

    def test_headline_contains_level(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("GREEN"))
        section = self.reporter._build_risk_section()
        self.assertIn("GREEN", section.headline)

    def test_details_have_expected_keys(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("YELLOW", warning=2, top_risk="High vol"))
        section = self.reporter._build_risk_section()
        self.assertIn("overall_level", section.details)
        self.assertIn("critical_count", section.details)
        self.assertIn("warning_count", section.details)
        self.assertIn("top_risk", section.details)
        self.assertIn("recommendations", section.details)

    def test_warning_count_in_details(self):
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("YELLOW", warning=3, top_risk="vol"))
        section = self.reporter._build_risk_section()
        self.assertEqual(section.details["warning_count"], 3)


# ---------------------------------------------------------------------------
# 4. TestBuildYieldSection (8 tests)
# ---------------------------------------------------------------------------

class TestBuildYieldSection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_unknown(self):
        section = self.reporter._build_yield_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_positive_apy_returns_ok(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker(apy=5.22))
        section = self.reporter._build_yield_section()
        self.assertEqual(section.status, _STATUS_OK)

    def test_zero_apy_positive_allocated_returns_warning(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker(apy=0.0, allocated=50000.0))
        section = self.reporter._build_yield_section()
        self.assertEqual(section.status, _STATUS_WARNING)

    def test_headline_contains_apy(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker(apy=5.22))
        section = self.reporter._build_yield_section()
        self.assertIn("5.22", section.headline)

    def test_headline_contains_daily_yield(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker(daily=14.30))
        section = self.reporter._build_yield_section()
        self.assertIn("14.30", section.headline)

    def test_details_have_expected_keys(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker())
        section = self.reporter._build_yield_section()
        for key in ("total_allocated_usd", "effective_apy_pct",
                    "total_daily_yield_usd", "top_contributor"):
            self.assertIn(key, section.details)

    def test_total_allocated_in_details(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker(allocated=94999.97))
        section = self.reporter._build_yield_section()
        self.assertAlmostEqual(section.details["total_allocated_usd"], 94999.97, places=1)

    def test_data_source_correct(self):
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker())
        section = self.reporter._build_yield_section()
        self.assertEqual(section.data_source, "yield_attribution_tracker.json")


# ---------------------------------------------------------------------------
# 5. TestBuildChainsSection (8 tests)
# ---------------------------------------------------------------------------

class TestBuildChainsSection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_unknown(self):
        section = self.reporter._build_chains_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_valid_best_chain_returns_ok(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain("ethereum"))
        section = self.reporter._build_chains_section()
        self.assertEqual(section.status, _STATUS_OK)

    def test_empty_best_chain_returns_unknown(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain(""))
        section = self.reporter._build_chains_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_headline_contains_adapters(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain(adapters=34))
        section = self.reporter._build_chains_section()
        self.assertIn("adapters", section.headline)

    def test_headline_contains_tvl(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain(tvl=18_000_000_000.0))
        section = self.reporter._build_chains_section()
        self.assertIn("TVL", section.headline)

    def test_details_total_adapters(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain(adapters=34))
        section = self.reporter._build_chains_section()
        self.assertEqual(section.details["total_adapters"], 34)

    def test_details_best_apy(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain(best_apy=12.0))
        section = self.reporter._build_chains_section()
        self.assertAlmostEqual(section.details["best_apy_overall"], 12.0)

    def test_details_l2_premium_present(self):
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain())
        section = self.reporter._build_chains_section()
        self.assertIn("l2_premium_pct", section.details)


# ---------------------------------------------------------------------------
# 6. TestBuildStrategiesSection (6 tests)
# ---------------------------------------------------------------------------

class TestBuildStrategiesSection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_unknown(self):
        section = self.reporter._build_strategies_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_winner_set_returns_ok(self):
        _write_json(self.tmpdir, "tournament_ranking.json",
                    _make_tournament("S7"))
        section = self.reporter._build_strategies_section()
        self.assertEqual(section.status, _STATUS_OK)

    def test_no_winner_returns_unknown(self):
        data = _make_tournament()
        data["winner"] = ""
        _write_json(self.tmpdir, "tournament_ranking.json", data)
        section = self.reporter._build_strategies_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_headline_contains_winner_and_apy(self):
        _write_json(self.tmpdir, "tournament_ranking.json",
                    _make_tournament("S7", winner_apy=10.115))
        section = self.reporter._build_strategies_section()
        self.assertIn("S7", section.headline)
        self.assertIn("10.1", section.headline)

    def test_active_count_correct(self):
        _write_json(self.tmpdir, "tournament_ranking.json",
                    _make_tournament(count=14))
        section = self.reporter._build_strategies_section()
        self.assertEqual(section.details["active_count"], 14)

    def test_winner_apy_extracted_from_strategies_list(self):
        _write_json(self.tmpdir, "tournament_ranking.json",
                    _make_tournament("S7", winner_apy=10.115))
        section = self.reporter._build_strategies_section()
        self.assertAlmostEqual(section.details["winner_apy"], 10.115, places=2)


# ---------------------------------------------------------------------------
# 7. TestBuildPegSection (6 tests)
# ---------------------------------------------------------------------------

class TestBuildPegSection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def test_missing_file_returns_unknown(self):
        section = self.reporter._build_peg_section()
        self.assertEqual(section.status, _STATUS_UNKNOWN)

    def test_green_overall_returns_ok(self):
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("GREEN", stable=31))
        section = self.reporter._build_peg_section()
        self.assertEqual(section.status, _STATUS_OK)

    def test_critical_count_returns_critical(self):
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("RED", stable=30, critical=1,
                               worst="frax", worst_dev=1.5))
        section = self.reporter._build_peg_section()
        self.assertEqual(section.status, _STATUS_CRITICAL)

    def test_warning_count_returns_warning(self):
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("YELLOW", stable=30, warning=1,
                               worst="dai", worst_dev=0.35))
        section = self.reporter._build_peg_section()
        self.assertEqual(section.status, _STATUS_WARNING)

    def test_headline_all_stable(self):
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("GREEN", stable=31))
        section = self.reporter._build_peg_section()
        self.assertIn("STABLE", section.headline)

    def test_headline_for_depeg_contains_adapter(self):
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("RED", critical=1, worst="frax", worst_dev=1.5))
        section = self.reporter._build_peg_section()
        self.assertIn("frax", section.headline)


# ---------------------------------------------------------------------------
# 8. TestDetermineOverallStatus (8 tests)
# ---------------------------------------------------------------------------

class TestDetermineOverallStatus(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def _make_section(self, status: str) -> OpsReportSection:
        return OpsReportSection(
            name="test", status=status, headline="h",
            details={}, data_source="x.json", data_fresh=True
        )

    def test_all_ok_returns_operational(self):
        sections = [self._make_section(_STATUS_OK)] * 3
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_OPERATIONAL
        )

    def test_one_warning_returns_degraded(self):
        sections = [
            self._make_section(_STATUS_OK),
            self._make_section(_STATUS_WARNING),
            self._make_section(_STATUS_OK),
        ]
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_DEGRADED
        )

    def test_one_critical_returns_critical(self):
        sections = [
            self._make_section(_STATUS_OK),
            self._make_section(_STATUS_CRITICAL),
        ]
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_CRITICAL
        )

    def test_critical_overrides_warning(self):
        sections = [
            self._make_section(_STATUS_WARNING),
            self._make_section(_STATUS_CRITICAL),
        ]
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_CRITICAL
        )

    def test_all_unknown_returns_operational(self):
        sections = [self._make_section(_STATUS_UNKNOWN)] * 5
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_OPERATIONAL
        )

    def test_empty_sections_returns_operational(self):
        self.assertEqual(
            self.reporter._determine_overall_status([]), _OVERALL_OPERATIONAL
        )

    def test_multiple_warnings_returns_degraded(self):
        sections = [self._make_section(_STATUS_WARNING)] * 4
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_DEGRADED
        )

    def test_critical_with_multiple_unknowns(self):
        sections = [
            self._make_section(_STATUS_UNKNOWN),
            self._make_section(_STATUS_CRITICAL),
            self._make_section(_STATUS_UNKNOWN),
        ]
        self.assertEqual(
            self.reporter._determine_overall_status(sections), _OVERALL_CRITICAL
        )


# ---------------------------------------------------------------------------
# 9. TestGenerateActionItems (8 tests)
# ---------------------------------------------------------------------------

class TestGenerateActionItems(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def _section(self, name: str, status: str, details: dict | None = None) -> OpsReportSection:
        return OpsReportSection(
            name=name, status=status,
            headline=f"{name} headline",
            details=details or {},
            data_source=f"{name}.json",
            data_fresh=True,
        )

    def test_no_issues_returns_empty(self):
        sections = [self._section("risk", _STATUS_OK),
                    self._section("peg", _STATUS_OK)]
        items = self.reporter._generate_action_items(sections)
        self.assertEqual(items, [])

    def test_peg_critical_halt_deposits(self):
        s = self._section("peg", _STATUS_CRITICAL,
                           {"worst_adapter": "frax", "worst_deviation_pct": 1.5})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(any("Halt" in i or "CRITICAL" in i for i in items))
        self.assertTrue(any("frax" in i for i in items))

    def test_risk_critical_review_immediately(self):
        s = self._section("risk", _STATUS_CRITICAL,
                           {"top_risk": "concentration alert"})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(any("CRITICAL" in i for i in items))

    def test_generic_critical_investigate(self):
        s = self._section("chains", _STATUS_CRITICAL, {})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(len(items) > 0)
        self.assertTrue(any("CRITICAL" in i for i in items))

    def test_risk_warning_review_signal(self):
        s = self._section("risk", _STATUS_WARNING,
                           {"top_risk": "watchdog down"})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(any("WARNING" in i for i in items))

    def test_peg_warning_monitor_stability(self):
        s = self._section("peg", _STATUS_WARNING,
                           {"worst_adapter": "dai", "worst_deviation_pct": 0.35})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(any("dai" in i for i in items))

    def test_yield_warning_low_yield(self):
        s = self._section("yield", _STATUS_WARNING,
                           {"effective_apy_pct": 0.0})
        items = self.reporter._generate_action_items([s])
        self.assertTrue(any("yield" in i.lower() or "WARNING" in i for i in items))

    def test_multiple_issues_multiple_items(self):
        sections = [
            self._section("risk", _STATUS_WARNING, {"top_risk": "high vol"}),
            self._section("peg", _STATUS_CRITICAL,
                          {"worst_adapter": "frax", "worst_deviation_pct": 2.0}),
        ]
        items = self.reporter._generate_action_items(sections)
        self.assertGreaterEqual(len(items), 2)


# ---------------------------------------------------------------------------
# 10. TestGenerate (6 tests)
# ---------------------------------------------------------------------------

class TestGenerate(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)
        # Write all data files
        _write_json(self.tmpdir, "integrated_risk.json",
                    _make_integrated_risk("GREEN"))
        _write_json(self.tmpdir, "yield_attribution_tracker.json",
                    _make_yield_tracker())
        _write_json(self.tmpdir, "multi_chain_report.json",
                    _make_multi_chain())
        _write_json(self.tmpdir, "tournament_ranking.json",
                    _make_tournament())
        _write_json(self.tmpdir, "peg_report.json",
                    _make_peg("GREEN"))
        _write_json(self.tmpdir, "paper_trading_status.json",
                    _make_paper_status(24))

    def test_returns_daily_ops_report_instance(self):
        report = self.reporter.generate()
        self.assertIsInstance(report, DailyOpsReport)

    def test_all_five_sections_present(self):
        report = self.reporter.generate()
        names = [s.name for s in report.sections]
        for expected in ("risk", "yield", "chains", "strategies", "peg"):
            self.assertIn(expected, names)

    def test_overall_status_computed(self):
        report = self.reporter.generate()
        self.assertIn(report.overall_status,
                      (_OVERALL_OPERATIONAL, _OVERALL_DEGRADED, _OVERALL_CRITICAL))

    def test_portfolio_summary_has_required_keys(self):
        report = self.reporter.generate()
        for key in ("total_allocated_usd", "effective_apy", "daily_yield_usd"):
            self.assertIn(key, report.portfolio_summary)

    def test_risk_summary_has_expected_keys(self):
        report = self.reporter.generate()
        self.assertIn("overall_level", report.risk_summary)
        self.assertIn("top_risk", report.risk_summary)

    def test_day_number_from_paper_status(self):
        report = self.reporter.generate()
        self.assertEqual(report.day_number, 24)


# ---------------------------------------------------------------------------
# 11. TestSave (4 tests)
# ---------------------------------------------------------------------------

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)
        # Write all data files so generate() doesn't error
        _write_json(self.tmpdir, "integrated_risk.json", _make_integrated_risk())
        _write_json(self.tmpdir, "yield_attribution_tracker.json", _make_yield_tracker())
        _write_json(self.tmpdir, "multi_chain_report.json", _make_multi_chain())
        _write_json(self.tmpdir, "tournament_ranking.json", _make_tournament())
        _write_json(self.tmpdir, "peg_report.json", _make_peg("GREEN"))
        _write_json(self.tmpdir, "paper_trading_status.json", _make_paper_status())

    def test_save_creates_file(self):
        self.reporter.generate()
        path = self.reporter.save()
        self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        self.reporter.generate()
        self.reporter.save()
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_max_enforced(self):
        """Saving >30 times keeps history ≤ 30."""
        out_path = os.path.join(self.tmpdir, "daily_ops_report.json")
        for _ in range(35):
            r = _make_reporter(self.tmpdir)
            r.generate()
            r.save(output_path=out_path)
        with open(out_path, "r") as f:
            data = json.load(f)
        self.assertLessEqual(len(data["history"]), _RING_BUFFER_MAX)

    def test_second_save_appends_to_history(self):
        out_path = os.path.join(self.tmpdir, "daily_ops_report.json")
        r1 = _make_reporter(self.tmpdir)
        r1.generate()
        r1.save(output_path=out_path)

        r2 = _make_reporter(self.tmpdir)
        r2.generate()
        r2.save(output_path=out_path)

        with open(out_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["report_count"], 2)
        self.assertEqual(len(data["history"]), 2)


# ---------------------------------------------------------------------------
# 12. TestFormatTelegramMessage (6 tests)
# ---------------------------------------------------------------------------

class TestFormatTelegramMessage(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)
        _write_json(self.tmpdir, "integrated_risk.json", _make_integrated_risk())
        _write_json(self.tmpdir, "yield_attribution_tracker.json", _make_yield_tracker())
        _write_json(self.tmpdir, "multi_chain_report.json", _make_multi_chain())
        _write_json(self.tmpdir, "tournament_ranking.json", _make_tournament())
        _write_json(self.tmpdir, "peg_report.json", _make_peg("GREEN"))
        _write_json(self.tmpdir, "paper_trading_status.json", _make_paper_status())
        self.reporter.generate()

    def test_message_within_4000_chars(self):
        msg = self.reporter.format_telegram_message()
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_message_contains_date(self):
        msg = self.reporter.format_telegram_message()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(date_str, msg)

    def test_message_contains_status(self):
        msg = self.reporter.format_telegram_message()
        self.assertTrue(
            any(s in msg for s in
                (_OVERALL_OPERATIONAL, _OVERALL_DEGRADED, _OVERALL_CRITICAL))
        )

    def test_message_contains_portfolio_info(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("APY", msg)

    def test_long_report_truncated(self):
        """Force truncation by injecting a very long action item list."""
        r = self.reporter._report
        r.action_items = ["A very long action item " * 20] * 50
        msg = self.reporter.format_telegram_message()
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_message_contains_section_names(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("Risk", msg)
        self.assertIn("Peg", msg)


# ---------------------------------------------------------------------------
# 13. TestFormatSummary (4 tests)
# ---------------------------------------------------------------------------

class TestFormatSummary(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)
        _write_json(self.tmpdir, "integrated_risk.json", _make_integrated_risk())
        _write_json(self.tmpdir, "yield_attribution_tracker.json", _make_yield_tracker())
        _write_json(self.tmpdir, "multi_chain_report.json", _make_multi_chain())
        _write_json(self.tmpdir, "tournament_ranking.json", _make_tournament())
        _write_json(self.tmpdir, "peg_report.json", _make_peg("GREEN"))
        _write_json(self.tmpdir, "paper_trading_status.json", _make_paper_status())
        self.reporter.generate()

    def test_summary_within_200_chars(self):
        summary = self.reporter.format_summary()
        self.assertLessEqual(len(summary), 200)

    def test_summary_contains_date(self):
        summary = self.reporter.format_summary()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(date_str, summary)

    def test_summary_contains_overall_status(self):
        summary = self.reporter.format_summary()
        self.assertTrue(
            any(s in summary for s in
                (_OVERALL_OPERATIONAL, _OVERALL_DEGRADED, _OVERALL_CRITICAL))
        )

    def test_summary_contains_apy(self):
        summary = self.reporter.format_summary()
        self.assertIn("APY", summary)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
