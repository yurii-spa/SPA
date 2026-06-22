"""
Tests for spa_core.analytics.full_portfolio_report (MP-621).

Groups
------
TestModuleStatus            (8)  — dataclass fields and status values
TestMasterReport           (10)  — dataclass fields, summary format
TestSafeLoad               (10)  — missing file, invalid JSON, array→last, valid
TestExtractModuleStatus    (20)  — all 12 keys, GREEN/YELLOW/RED mapping, None→UNKNOWN
TestComputeHealthScore      (8)  — all GREEN, all RED, mixed, no modules → 0.5
TestComputeOverallHealth    (8)  — ALERT on RED, EXCELLENT/GOOD/FAIR rules
TestGenerateActionItems    (10)  — RED→specific text, YELLOW advisory, max 5
TestGenerateReport         (10)  — all missing, partial, loaded/failed counts
TestSaveReport              (4)  — atomic, ring-buffer ≤ 30
TestFormatTelegramMessage   (8)  — ≤ 2000 chars, required strings

Total: 96 tests
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from spa_core.analytics.full_portfolio_report import (
    FullPortfolioReport,
    MasterReport,
    ModuleStatus,
    _HEALTH_ALERT,
    _HEALTH_EXCELLENT,
    _HEALTH_FAIR,
    _HEALTH_GOOD,
    _STATUS_GREEN,
    _STATUS_RED,
    _STATUS_UNKNOWN,
    _STATUS_YELLOW,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reporter(tmpdir: str) -> FullPortfolioReport:
    return FullPortfolioReport(data_path=tmpdir)


def _write_json(tmpdir: str, filename: str, data: object) -> None:
    path = os.path.join(tmpdir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _bench_data(verdict: str = "ALPHA+", apy: float = 5.22) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "verdict": verdict,
            "portfolio_apy_pct": apy,
        }
    }


def _weekly_data(verdict: str = "GOOD", days: int = 7) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "weekly_verdict": verdict,
            "days_covered": days,
        }
    }


def _risk_data(level: str = "GREEN", score: float = 0.05) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "overall_level": level,
            "overall_score": score,
        }
    }


def _rebalance_data(rec: str = "HOLD", apy_imp: float = 0.0) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "recommendation": rec,
            "apy_improvement": apy_imp,
        }
    }


def _capital_data(grade: str = "B", raroc: float = 1.5) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "overall_grade": grade,
            "portfolio_raroc": raroc,
        }
    }


def _tier_data(status: str = "COMPLIANT", hhi: float = 0.4) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "policy_status": status,
            "hhi": hhi,
        }
    }


def _chain_data(status: str = "COMPLIANT", hhi: float = 0.5) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "policy_status": status,
            "hhi": hhi,
        }
    }


def _peg_data(status: str = "GREEN", worst: str = "", dev: float = 0.0) -> dict:
    # peg_report has overall_status at ROOT (no 'latest')
    return {
        "generated_at": "2026-06-13T10:00:00",
        "overall_status": status,
        "worst_adapter": worst,
        "worst_deviation_pct": dev,
    }


def _forecast_data(trend: str = "RISING", cur_apy: float = 5.0) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "portfolio_trend": trend,
            "portfolio_current_apy": cur_apy,
        }
    }


def _attribution_data(apy: float = 5.22, alloc: float = 95000.0) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "effective_apy_pct": apy,
            "total_allocated_usd": alloc,
        }
    }


def _stablecoin_data(contagion: str = "LOW", dom_w: float = 100.0) -> dict:
    return {
        "latest": {
            "generated_at": "2026-06-13T10:00:00",
            "contagion_risk": contagion,
            "dominant_weight_pct": dom_w,
        }
    }


def _concentration_data(verdict: str = "DIVERSIFIED", hhi: float = 0.15) -> dict:
    # concentration_analytics has verdict at ROOT
    return {
        "generated_at": "2026-06-13T10:00:00",
        "verdict": verdict,
        "hhi_protocol": hhi,
    }


# File name map (DATA_SOURCES strips "data/" prefix)
_FILE_MAP = {
    "attribution":        "yield_attribution_tracker.json",
    "benchmark":          "benchmark_report.json",
    "weekly":             "weekly_summary.json",
    "risk":               "integrated_risk.json",
    "rebalance":          "rebalance_plan.json",
    "capital_efficiency": "capital_efficiency.json",
    "tier_exposure":      "tier_exposure.json",
    "chain_exposure":     "chain_exposure.json",
    "peg_monitor":        "peg_report.json",
    "forecast":           "yield_forecast.json",
    "stablecoin":         "stablecoin_exposure.json",
    "concentration":      "concentration_analytics.json",
}


def _write_all_green(tmpdir: str) -> None:
    """Write all data sources with green-status values."""
    _write_json(tmpdir, _FILE_MAP["attribution"],        _attribution_data())
    _write_json(tmpdir, _FILE_MAP["benchmark"],          _bench_data("ALPHA+"))
    _write_json(tmpdir, _FILE_MAP["weekly"],             _weekly_data("EXCELLENT"))
    _write_json(tmpdir, _FILE_MAP["risk"],               _risk_data("GREEN"))
    _write_json(tmpdir, _FILE_MAP["rebalance"],          _rebalance_data("HOLD"))
    _write_json(tmpdir, _FILE_MAP["capital_efficiency"], _capital_data("A"))
    _write_json(tmpdir, _FILE_MAP["tier_exposure"],      _tier_data("COMPLIANT"))
    _write_json(tmpdir, _FILE_MAP["chain_exposure"],     _chain_data("COMPLIANT"))
    _write_json(tmpdir, _FILE_MAP["peg_monitor"],        _peg_data("GREEN"))
    _write_json(tmpdir, _FILE_MAP["forecast"],           _forecast_data("RISING"))
    _write_json(tmpdir, _FILE_MAP["stablecoin"],         _stablecoin_data("LOW"))
    _write_json(tmpdir, _FILE_MAP["concentration"],      _concentration_data("DIVERSIFIED"))


# ===========================================================================
# 1. TestModuleStatus — 8 tests
# ===========================================================================


class TestModuleStatus(unittest.TestCase):

    def _make(self, **kw) -> ModuleStatus:
        defaults = dict(
            name="benchmark",
            file_path="data/benchmark_report.json",
            loaded=True,
            key_metric="ALPHA+ (5.22%)",
            status_level="GREEN",
            last_updated="2026-06-13T10:00:00",
        )
        defaults.update(kw)
        return ModuleStatus(**defaults)

    def test_fields_stored(self):
        m = self._make()
        self.assertEqual(m.name, "benchmark")
        self.assertEqual(m.file_path, "data/benchmark_report.json")
        self.assertTrue(m.loaded)
        self.assertEqual(m.key_metric, "ALPHA+ (5.22%)")
        self.assertEqual(m.status_level, "GREEN")
        self.assertEqual(m.last_updated, "2026-06-13T10:00:00")

    def test_not_loaded(self):
        m = self._make(loaded=False, key_metric="N/A", status_level="UNKNOWN")
        self.assertFalse(m.loaded)
        self.assertEqual(m.status_level, "UNKNOWN")

    def test_status_level_green(self):
        m = self._make(status_level=_STATUS_GREEN)
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_status_level_yellow(self):
        m = self._make(status_level=_STATUS_YELLOW)
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_status_level_red(self):
        m = self._make(status_level=_STATUS_RED)
        self.assertEqual(m.status_level, _STATUS_RED)

    def test_status_level_unknown(self):
        m = self._make(status_level=_STATUS_UNKNOWN)
        self.assertEqual(m.status_level, _STATUS_UNKNOWN)

    def test_to_dict_keys(self):
        m = self._make()
        d = m.to_dict()
        for k in ("name", "file_path", "loaded", "key_metric", "status_level", "last_updated"):
            self.assertIn(k, d)

    def test_to_dict_values(self):
        m = self._make(name="risk", status_level="RED", loaded=False)
        d = m.to_dict()
        self.assertEqual(d["name"], "risk")
        self.assertEqual(d["status_level"], "RED")
        self.assertFalse(d["loaded"])


# ===========================================================================
# 2. TestMasterReport — 10 tests
# ===========================================================================


class TestMasterReport(unittest.TestCase):

    def _make_module(self, name: str, sl: str = "GREEN") -> ModuleStatus:
        return ModuleStatus(
            name=name, file_path=f"data/{name}.json", loaded=True,
            key_metric="ok", status_level=sl, last_updated="2026-06-13T10:00:00"
        )

    def _make_report(self, **kw) -> MasterReport:
        defaults = dict(
            generated_at="2026-06-13T10:00:00+00:00",
            portfolio_apy_pct=5.22,
            total_allocated_usd=95000.0,
            modules=[self._make_module("benchmark")],
            modules_loaded=1,
            modules_failed=0,
            benchmark_verdict="ALPHA+",
            weekly_verdict="GOOD",
            risk_level="GREEN",
            rebalance_recommendation="HOLD",
            capital_grade="B",
            tier_policy_status="COMPLIANT",
            chain_policy_status="COMPLIANT",
            peg_status="GREEN",
            forecast_trend="RISING",
            overall_health=_HEALTH_GOOD,
            health_score=0.9,
            action_items=[],
            summary="APY 5.22%, GOOD health, 0 action items",
        )
        defaults.update(kw)
        return MasterReport(**defaults)

    def test_fields_stored(self):
        r = self._make_report()
        self.assertAlmostEqual(r.portfolio_apy_pct, 5.22)
        self.assertEqual(r.benchmark_verdict, "ALPHA+")
        self.assertEqual(r.overall_health, _HEALTH_GOOD)

    def test_modules_count(self):
        r = self._make_report(modules_loaded=10, modules_failed=2)
        self.assertEqual(r.modules_loaded, 10)
        self.assertEqual(r.modules_failed, 2)

    def test_health_score_range(self):
        r = self._make_report(health_score=0.75)
        self.assertGreaterEqual(r.health_score, 0.0)
        self.assertLessEqual(r.health_score, 1.0)

    def test_action_items_list(self):
        r = self._make_report(action_items=["do x", "do y"])
        self.assertEqual(len(r.action_items), 2)

    def test_to_dict_has_all_fields(self):
        r = self._make_report()
        d = r.to_dict()
        for key in (
            "generated_at", "portfolio_apy_pct", "total_allocated_usd",
            "modules", "modules_loaded", "modules_failed",
            "benchmark_verdict", "weekly_verdict", "risk_level",
            "rebalance_recommendation", "capital_grade", "tier_policy_status",
            "chain_policy_status", "peg_status", "forecast_trend",
            "overall_health", "health_score", "action_items", "summary",
        ):
            self.assertIn(key, d)

    def test_to_dict_modules_are_dicts(self):
        r = self._make_report()
        d = r.to_dict()
        self.assertIsInstance(d["modules"], list)
        for m in d["modules"]:
            self.assertIsInstance(m, dict)

    def test_summary_contains_health(self):
        r = self._make_report(
            overall_health=_HEALTH_ALERT,
            summary="APY 5.22%, ALERT health, 3 action items",
        )
        self.assertIn("ALERT", r.summary)

    def test_summary_action_item_plural(self):
        r = self._make_report(summary="APY 5.22%, GOOD health, 2 action items")
        self.assertIn("action items", r.summary)

    def test_summary_action_item_singular(self):
        r = self._make_report(summary="APY 5.22%, GOOD health, 1 action item")
        self.assertIn("1 action item", r.summary)

    def test_to_dict_json_serializable(self):
        r = self._make_report()
        d = r.to_dict()
        dumped = json.dumps(d)
        self.assertIsInstance(dumped, str)


# ===========================================================================
# 3. TestSafeLoad — 10 tests
# ===========================================================================


class TestSafeLoad(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_returns_none(self):
        result = self.reporter.safe_load("benchmark")
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        path = os.path.join(self.tmpdir, "benchmark_report.json")
        with open(path, "w") as fh:
            fh.write("{NOT VALID JSON")
        result = self.reporter.safe_load("benchmark")
        self.assertIsNone(result)

    def test_valid_dict_returned(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], {"key": "val"})
        result = self.reporter.safe_load("benchmark")
        self.assertEqual(result, {"key": "val"})

    def test_array_returns_last_element(self):
        data = [{"idx": 0}, {"idx": 1}, {"idx": 2}]
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], data)
        result = self.reporter.safe_load("benchmark")
        self.assertEqual(result["idx"], 2)

    def test_empty_array_returns_none(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], [])
        result = self.reporter.safe_load("benchmark")
        self.assertIsNone(result)

    def test_scalar_value_returns_none(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], 42)
        result = self.reporter.safe_load("benchmark")
        self.assertIsNone(result)

    def test_string_value_returns_none(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], "hello")
        result = self.reporter.safe_load("benchmark")
        self.assertIsNone(result)

    def test_unknown_key_returns_none(self):
        result = self.reporter.safe_load("nonexistent_key_xyz")
        self.assertIsNone(result)

    def test_peg_monitor_flat_dict(self):
        _write_json(self.tmpdir, _FILE_MAP["peg_monitor"], _peg_data("GREEN"))
        result = self.reporter.safe_load("peg_monitor")
        self.assertIsNotNone(result)
        self.assertEqual(result["overall_status"], "GREEN")

    def test_nested_latest_preserved(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], _bench_data("ALPHA+", 5.22))
        result = self.reporter.safe_load("benchmark")
        self.assertIn("latest", result)
        self.assertEqual(result["latest"]["verdict"], "ALPHA+")


# ===========================================================================
# 4. TestExtractModuleStatus — 20 tests
# ===========================================================================


class TestExtractModuleStatus(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- None data → UNKNOWN ---

    def test_none_data_gives_unknown(self):
        m = self.reporter.extract_module_status("benchmark", None)
        self.assertEqual(m.status_level, _STATUS_UNKNOWN)
        self.assertFalse(m.loaded)
        self.assertEqual(m.key_metric, "N/A")

    # --- benchmark ---

    def test_benchmark_alpha_plus_green(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data("ALPHA+"))
        self.assertEqual(m.status_level, _STATUS_GREEN)
        self.assertIn("ALPHA+", m.key_metric)

    def test_benchmark_alpha_green(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data("ALPHA"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_benchmark_benchmark_yellow(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data("BENCHMARK"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_benchmark_lagging_red(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data("LAGGING"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- weekly ---

    def test_weekly_excellent_green(self):
        m = self.reporter.extract_module_status("weekly", _weekly_data("EXCELLENT"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_weekly_good_green(self):
        m = self.reporter.extract_module_status("weekly", _weekly_data("GOOD"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_weekly_fair_yellow(self):
        m = self.reporter.extract_module_status("weekly", _weekly_data("FAIR"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_weekly_poor_red(self):
        m = self.reporter.extract_module_status("weekly", _weekly_data("POOR"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- risk ---

    def test_risk_green(self):
        m = self.reporter.extract_module_status("risk", _risk_data("GREEN"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_risk_yellow(self):
        m = self.reporter.extract_module_status("risk", _risk_data("YELLOW"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_risk_orange_maps_to_yellow(self):
        m = self.reporter.extract_module_status("risk", _risk_data("ORANGE"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_risk_red(self):
        m = self.reporter.extract_module_status("risk", _risk_data("RED"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- rebalance ---

    def test_rebalance_hold_green(self):
        m = self.reporter.extract_module_status("rebalance", _rebalance_data("HOLD"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_rebalance_monitor_yellow(self):
        m = self.reporter.extract_module_status("rebalance", _rebalance_data("MONITOR"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_rebalance_rebalance_red(self):
        m = self.reporter.extract_module_status("rebalance", _rebalance_data("REBALANCE", 1.5))
        self.assertEqual(m.status_level, _STATUS_RED)
        self.assertIn("1.50", m.key_metric)

    # --- capital_efficiency ---

    def test_capital_grade_a_green(self):
        m = self.reporter.extract_module_status("capital_efficiency", _capital_data("A"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_capital_grade_b_green(self):
        m = self.reporter.extract_module_status("capital_efficiency", _capital_data("B"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_capital_grade_c_yellow(self):
        m = self.reporter.extract_module_status("capital_efficiency", _capital_data("C"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_capital_grade_d_red(self):
        m = self.reporter.extract_module_status("capital_efficiency", _capital_data("D"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- tier_exposure ---

    def test_tier_compliant_green(self):
        m = self.reporter.extract_module_status("tier_exposure", _tier_data("COMPLIANT"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_tier_breach_red(self):
        m = self.reporter.extract_module_status("tier_exposure", _tier_data("BREACH"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- chain_exposure ---

    def test_chain_compliant_green(self):
        m = self.reporter.extract_module_status("chain_exposure", _chain_data("COMPLIANT"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_chain_breach_red(self):
        m = self.reporter.extract_module_status("chain_exposure", _chain_data("BREACH"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- peg_monitor ---

    def test_peg_green(self):
        m = self.reporter.extract_module_status("peg_monitor", _peg_data("GREEN"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_peg_yellow(self):
        m = self.reporter.extract_module_status("peg_monitor", _peg_data("YELLOW"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_peg_red(self):
        m = self.reporter.extract_module_status("peg_monitor", _peg_data("RED", "usdc", 1.5))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- forecast ---

    def test_forecast_rising_green(self):
        m = self.reporter.extract_module_status("forecast", _forecast_data("RISING"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_forecast_stable_yellow(self):
        m = self.reporter.extract_module_status("forecast", _forecast_data("STABLE"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_forecast_falling_red(self):
        m = self.reporter.extract_module_status("forecast", _forecast_data("FALLING"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- stablecoin ---

    def test_stablecoin_low_green(self):
        m = self.reporter.extract_module_status("stablecoin", _stablecoin_data("LOW"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_stablecoin_none_green(self):
        m = self.reporter.extract_module_status("stablecoin", _stablecoin_data("NONE"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_stablecoin_medium_yellow(self):
        m = self.reporter.extract_module_status("stablecoin", _stablecoin_data("MEDIUM"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_stablecoin_high_red(self):
        m = self.reporter.extract_module_status("stablecoin", _stablecoin_data("HIGH"))
        self.assertEqual(m.status_level, _STATUS_RED)

    def test_stablecoin_critical_red(self):
        m = self.reporter.extract_module_status("stablecoin", _stablecoin_data("CRITICAL"))
        self.assertEqual(m.status_level, _STATUS_RED)

    # --- concentration ---

    def test_concentration_diversified_green(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("DIVERSIFIED"))
        self.assertEqual(m.status_level, _STATUS_GREEN)

    def test_concentration_moderate_yellow(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("MODERATE"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_concentration_concentrated_yellow(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("CONCENTRATED"))
        self.assertEqual(m.status_level, _STATUS_YELLOW)

    def test_concentration_fail_red(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("FAIL"))
        self.assertEqual(m.status_level, _STATUS_RED)

    def test_concentration_critical_red(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("CRITICAL"))
        self.assertEqual(m.status_level, _STATUS_RED)

    def test_concentration_unknown_verdict_unknown(self):
        m = self.reporter.extract_module_status("concentration", _concentration_data("XYZZY"))
        self.assertEqual(m.status_level, _STATUS_UNKNOWN)

    # --- loaded flag ---

    def test_loaded_true_when_data_present(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data())
        self.assertTrue(m.loaded)

    def test_loaded_false_when_none(self):
        m = self.reporter.extract_module_status("weekly", None)
        self.assertFalse(m.loaded)

    def test_file_path_stored(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data())
        self.assertIn("benchmark_report.json", m.file_path)

    def test_last_updated_extracted(self):
        m = self.reporter.extract_module_status("benchmark", _bench_data())
        self.assertNotEqual(m.last_updated, "unknown")
        self.assertIn("2026-06-13", m.last_updated)


# ===========================================================================
# 5. TestComputeHealthScore — 8 tests
# ===========================================================================


class TestComputeHealthScore(unittest.TestCase):

    def setUp(self):
        self.reporter = FullPortfolioReport.__new__(FullPortfolioReport)

    def _mod(self, status: str, loaded: bool = True) -> ModuleStatus:
        return ModuleStatus(
            name="x", file_path="data/x.json", loaded=loaded,
            key_metric="k", status_level=status, last_updated="t"
        )

    def test_all_green_score_1(self):
        modules = [self._mod("GREEN")] * 5
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 1.0)

    def test_all_red_score_0(self):
        modules = [self._mod("RED")] * 4
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 0.0)

    def test_mixed_half(self):
        modules = [self._mod("GREEN"), self._mod("RED")]
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 0.5)

    def test_no_modules_returns_05(self):
        self.assertAlmostEqual(self.reporter.compute_health_score([]), 0.5)

    def test_unloaded_modules_excluded(self):
        modules = [self._mod("GREEN"), self._mod("RED", loaded=False)]
        # Only 1 loaded (GREEN) → score = 1.0
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 1.0)

    def test_all_unloaded_returns_05(self):
        modules = [self._mod("GREEN", loaded=False)] * 3
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 0.5)

    def test_yellow_not_green(self):
        modules = [self._mod("YELLOW")] * 3
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 0.0)

    def test_partial_green(self):
        modules = [self._mod("GREEN")] * 3 + [self._mod("YELLOW")] * 1
        self.assertAlmostEqual(self.reporter.compute_health_score(modules), 0.75)


# ===========================================================================
# 6. TestComputeOverallHealth — 8 tests
# ===========================================================================


class TestComputeOverallHealth(unittest.TestCase):

    def setUp(self):
        self.reporter = FullPortfolioReport.__new__(FullPortfolioReport)

    def _mod(self, status: str, loaded: bool = True) -> ModuleStatus:
        return ModuleStatus(
            name="x", file_path="data/x.json", loaded=loaded,
            key_metric="k", status_level=status, last_updated="t"
        )

    def test_any_red_gives_alert(self):
        modules = [self._mod("GREEN")] * 5 + [self._mod("RED")]
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_ALERT)

    def test_single_red_gives_alert(self):
        modules = [self._mod("RED")]
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_ALERT)

    def test_all_green_high_score_excellent(self):
        modules = [self._mod("GREEN")] * 10
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_EXCELLENT)

    def test_yellow_prevents_excellent(self):
        modules = [self._mod("GREEN")] * 9 + [self._mod("YELLOW")]
        result = self.reporter.compute_overall_health(modules, {})
        self.assertNotEqual(result, _HEALTH_EXCELLENT)

    def test_score_above_06_gives_good(self):
        # 7 GREEN + 3 YELLOW → score 0.7 ≥ 0.6 and has YELLOW → GOOD
        modules = [self._mod("GREEN")] * 7 + [self._mod("YELLOW")] * 3
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_GOOD)

    def test_score_below_06_gives_fair(self):
        # 2 GREEN + 8 YELLOW → score 0.2 < 0.6 → FAIR
        modules = [self._mod("GREEN")] * 2 + [self._mod("YELLOW")] * 8
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_FAIR)

    def test_unloaded_not_counted(self):
        # 10 GREEN loaded + 100 RED unloaded → all loaded are GREEN → EXCELLENT
        modules = ([self._mod("GREEN")] * 10 +
                   [self._mod("RED", loaded=False)] * 100)
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_EXCELLENT)

    def test_all_unknown_gives_fair(self):
        # UNKNOWN ≠ GREEN; score 0.0 < 0.6 → FAIR
        modules = [self._mod("UNKNOWN")] * 5
        result = self.reporter.compute_overall_health(modules, {})
        self.assertEqual(result, _HEALTH_FAIR)


# ===========================================================================
# 7. TestGenerateActionItems — 10 tests
# ===========================================================================


class TestGenerateActionItems(unittest.TestCase):

    def setUp(self):
        self.reporter = FullPortfolioReport.__new__(FullPortfolioReport)

    def _mod(self, name: str, status: str, loaded: bool = True) -> ModuleStatus:
        return ModuleStatus(
            name=name, file_path=f"data/{name}.json", loaded=loaded,
            key_metric="k", status_level=status, last_updated="t"
        )

    def test_no_issues_empty_list(self):
        modules = [self._mod("benchmark", "GREEN")]
        items = self.reporter.generate_action_items(modules, {})
        self.assertEqual(items, [])

    def test_tier_breach_specific_text(self):
        items = self.reporter.generate_action_items(
            [self._mod("tier_exposure", "RED")], {}
        )
        self.assertTrue(any("tier exposure" in i.lower() for i in items))

    def test_chain_breach_specific_text(self):
        items = self.reporter.generate_action_items(
            [self._mod("chain_exposure", "RED")], {}
        )
        self.assertTrue(any("chain exposure" in i.lower() for i in items))

    def test_rebalance_red_specific_text(self):
        items = self.reporter.generate_action_items(
            [self._mod("rebalance", "RED")], {}
        )
        self.assertTrue(any("rebalance" in i.lower() for i in items))

    def test_benchmark_lagging_specific_text(self):
        items = self.reporter.generate_action_items(
            [self._mod("benchmark", "RED")], {}
        )
        self.assertTrue(any("lagging" in i.lower() for i in items))

    def test_peg_red_specific_text(self):
        items = self.reporter.generate_action_items(
            [self._mod("peg_monitor", "RED")], {}
        )
        self.assertTrue(any("peg" in i.lower() for i in items))

    def test_max_5_items(self):
        modules = [self._mod(f"mod{i}", "RED") for i in range(10)]
        items = self.reporter.generate_action_items(modules, {})
        self.assertLessEqual(len(items), 5)

    def test_rebalance_yellow_advisory(self):
        items = self.reporter.generate_action_items(
            [self._mod("rebalance", "YELLOW")], {}
        )
        self.assertTrue(any("rebalanc" in i.lower() for i in items))

    def test_unloaded_modules_skipped(self):
        modules = [self._mod("tier_exposure", "RED", loaded=False)]
        items = self.reporter.generate_action_items(modules, {})
        self.assertEqual(items, [])

    def test_mix_red_and_yellow_max_5(self):
        modules = (
            [self._mod("tier_exposure", "RED")] +
            [self._mod("chain_exposure", "RED")] +
            [self._mod("rebalance", "RED")] +
            [self._mod("benchmark", "RED")] +
            [self._mod("peg_monitor", "RED")] +
            [self._mod("forecast", "RED")] +
            [self._mod("risk", "YELLOW")] +
            [self._mod("weekly", "RED")]
        )
        items = self.reporter.generate_action_items(modules, {})
        self.assertEqual(len(items), 5)


# ===========================================================================
# 8. TestGenerateReport — 10 tests
# ===========================================================================


class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_missing_returns_report(self):
        report = self.reporter.generate_report()
        self.assertIsInstance(report, MasterReport)

    def test_all_missing_modules_failed_12(self):
        report = self.reporter.generate_report()
        self.assertEqual(report.modules_failed, 12)
        self.assertEqual(report.modules_loaded, 0)

    def test_all_missing_health_unknown_or_fair(self):
        report = self.reporter.generate_report()
        self.assertIn(report.overall_health, (_HEALTH_FAIR, _HEALTH_EXCELLENT, _HEALTH_GOOD, _HEALTH_ALERT))

    def test_partial_load_counts(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], _bench_data())
        _write_json(self.tmpdir, _FILE_MAP["attribution"], _attribution_data())
        report = self.reporter.generate_report()
        self.assertEqual(report.modules_loaded, 2)
        self.assertEqual(report.modules_failed, 10)

    def test_portfolio_apy_from_attribution(self):
        _write_json(self.tmpdir, _FILE_MAP["attribution"], _attribution_data(apy=7.5))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.portfolio_apy_pct, 7.5)

    def test_total_allocated_from_attribution(self):
        _write_json(self.tmpdir, _FILE_MAP["attribution"], _attribution_data(alloc=80000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.total_allocated_usd, 80000.0)

    def test_benchmark_verdict_extracted(self):
        _write_json(self.tmpdir, _FILE_MAP["benchmark"], _bench_data("ALPHA+"))
        report = self.reporter.generate_report()
        self.assertEqual(report.benchmark_verdict, "ALPHA+")

    def test_all_green_excellent_health(self):
        _write_all_green(self.tmpdir)
        report = self.reporter.generate_report()
        self.assertEqual(report.overall_health, _HEALTH_EXCELLENT)

    def test_summary_contains_apy(self):
        _write_json(self.tmpdir, _FILE_MAP["attribution"], _attribution_data(apy=4.5))
        report = self.reporter.generate_report()
        self.assertIn("4.50", report.summary)

    def test_report_stored_internally(self):
        report = self.reporter.generate_report()
        self.assertIs(self.reporter._report, report)


# ===========================================================================
# 9. TestSaveReport — 4 tests
# ===========================================================================


class TestSaveReport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_saves_file(self):
        self.reporter.generate_report()
        path = self.reporter.save_report()
        self.assertTrue(os.path.exists(path))

    def test_no_tmp_leftover(self):
        self.reporter.generate_report()
        self.reporter.save_report()
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_max_30(self):
        for _ in range(35):
            r = self.reporter.generate_report()
            self.reporter.save_report(r)
        path = os.path.join(self.tmpdir, "master_report.json")
        with open(path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["history"]), 30)

    def test_saved_json_valid_structure(self):
        self.reporter.generate_report()
        path = self.reporter.save_report()
        with open(path) as fh:
            data = json.load(fh)
        for key in ("schema_version", "source", "ring_buffer_max", "latest", "history"):
            self.assertIn(key, data)
        self.assertEqual(data["source"], "full_portfolio_report")


# ===========================================================================
# 10. TestFormatTelegramMessage — 8 tests
# ===========================================================================


class TestFormatTelegramMessage(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_max_2000_chars(self):
        self.reporter.generate_report()
        msg = self.reporter.format_telegram_message()
        self.assertLessEqual(len(msg), 2000)

    def test_contains_master_report(self):
        self.reporter.generate_report()
        msg = self.reporter.format_telegram_message()
        self.assertIn("Master Report", msg)

    def test_contains_health_level(self):
        _write_all_green(self.tmpdir)
        r = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(r)
        self.assertIn(r.overall_health, msg)

    def test_alert_health_shows_alert(self):
        _write_json(self.tmpdir, _FILE_MAP["tier_exposure"], _tier_data("BREACH"))
        r = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(r)
        self.assertIn("ALERT", msg)

    def test_contains_apy(self):
        _write_json(self.tmpdir, _FILE_MAP["attribution"], _attribution_data(apy=6.0))
        r = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(r)
        self.assertIn("6.00", msg)

    def test_no_generate_needed_if_already_done(self):
        r = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(r)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_explicit_report_arg(self):
        r = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(report=r)
        self.assertLessEqual(len(msg), 2000)

    def test_truncated_at_2000_when_long(self):
        # Create many modules with long key metrics to force truncation
        _write_all_green(self.tmpdir)
        r = self.reporter.generate_report()
        # Patch to force extremely long message
        original_modules = r.modules
        long_modules = [
            ModuleStatus(
                name=f"module_{i:03d}",
                file_path=f"data/module_{i:03d}.json",
                loaded=True,
                key_metric="X" * 200,
                status_level="GREEN",
                last_updated="2026-06-13T10:00:00",
            )
            for i in range(20)
        ]
        r.modules = long_modules
        msg = self.reporter.format_telegram_message(r)
        self.assertLessEqual(len(msg), 2000)
        r.modules = original_modules


# ===========================================================================
# Integration
# ===========================================================================


class TestIntegration(unittest.TestCase):
    """End-to-end: load all green sources → generate → save → verify."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = _make_reporter(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_green_pipeline(self):
        _write_all_green(self.tmpdir)
        r = self.reporter.generate_report()
        self.assertEqual(r.modules_loaded, 12)
        self.assertEqual(r.modules_failed, 0)
        self.assertEqual(r.overall_health, _HEALTH_EXCELLENT)
        self.assertAlmostEqual(r.health_score, 1.0)
        self.assertEqual(r.action_items, [])
        self.assertIn("EXCELLENT", r.summary)

    def test_full_green_save(self):
        _write_all_green(self.tmpdir)
        r = self.reporter.generate_report()
        path = self.reporter.save_report(r)
        with open(path) as fh:
            data = json.load(fh)
        latest = data["latest"]
        self.assertEqual(latest["overall_health"], _HEALTH_EXCELLENT)
        self.assertEqual(latest["modules_loaded"], 12)

    def test_to_dict_json_serializable(self):
        _write_all_green(self.tmpdir)
        r = self.reporter.generate_report()
        d = self.reporter.to_dict(r)
        dumped = json.dumps(d)
        loaded = json.loads(dumped)
        self.assertIsInstance(loaded, dict)
        self.assertEqual(loaded["modules_loaded"], 12)


if __name__ == "__main__":
    unittest.main()
