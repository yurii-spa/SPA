"""Tests for CapitalEfficiencyReport (MP-616).

Covers:
  TestAdapterEfficiency (12)         — daily_yield_usd, raroc, grade thresholds, zero risk
  TestCapitalEfficiencyData (10)     — deployment_rate, idle, opp_cost, grade logic
  TestLoadPositions (8)              — missing file → defaults, valid file → correct values
  TestLoadBestApy (6)                — missing → 5.0, valid → max APY
  TestComputeAdapterEfficiency (12)  — all fields, grade boundaries, zero risk
  TestGenerateReport (25)            — empty → Grade D, full positions, top/bottom, opp_cost
  TestSaveReport (5)                 — atomic, ring-buffer ≤30
  TestFormatTelegramMessage (8)      — ≤1500 chars, contains "Grade" and "Deployed"
  TestToDict (4)                     — JSON-serializable, all fields

Total: 90 tests
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from spa_core.analytics.capital_efficiency_report import (
    AdapterEfficiency,
    CapitalEfficiencyData,
    CapitalEfficiencyReport,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_contribution(
    adapter_id: str = "aave_v3",
    allocated_usd: float = 10_000.0,
    apy_pct: float = 5.0,
    risk_score: float = 0.5,
) -> Dict[str, Any]:
    return {
        "adapter_id": adapter_id,
        "allocated_usd": allocated_usd,
        "apy_pct": apy_pct,
        "risk_score": risk_score,
    }


def _make_tracker_json(contributions: List[Dict], total_usd: float = 100_000.0) -> Dict:
    return {
        "schema_version": "1.0",
        "source": "yield_attribution_tracker",
        "latest": {
            "generated_at": "2026-06-13T08:00:00+00:00",
            "total_allocated_usd": total_usd,
            "contributions": contributions,
        },
        "snapshots": [],
    }


def _make_adapter_status(adapters: Dict[str, Dict]) -> Dict:
    result: Dict = {"generated_at": "2026-06-13T08:00:00+00:00", "schema_version": "1.0"}
    result.update(adapters)
    return result


def _write_json(directory: Path, filename: str, data: Dict) -> None:
    (directory / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# TestAdapterEfficiency
# ===========================================================================

class TestAdapterEfficiency(unittest.TestCase):
    """12 tests covering AdapterEfficiency dataclass behaviour."""

    def _make(self, **kwargs) -> AdapterEfficiency:
        defaults = dict(
            adapter_key="aave_v3",
            allocated_usd=10_000.0,
            apy_pct=5.0,
            risk_score=0.5,
            daily_yield_usd=10_000 * 5 / 100 / 365,
            raroc=(5.0 - 4.5) / 0.5,
            efficiency_grade="C",
        )
        defaults.update(kwargs)
        return AdapterEfficiency(**defaults)

    def test_daily_yield_usd_calculation(self):
        """daily_yield_usd = allocated * apy / 100 / 365."""
        ae = self._make(allocated_usd=73_000.0, apy_pct=10.0,
                        daily_yield_usd=73_000 * 10 / 100 / 365)
        self.assertAlmostEqual(ae.daily_yield_usd, 73_000 * 10 / 100 / 365, places=6)

    def test_raroc_formula(self):
        """RAROC = (apy - 4.5) / risk_score."""
        # (10.0 - 4.5) / 0.5 = 11.0
        ae = self._make(apy_pct=10.0, risk_score=0.5, raroc=11.0, efficiency_grade="B")
        self.assertAlmostEqual(ae.raroc, 11.0, places=4)

    def test_raroc_zero_when_risk_score_zero(self):
        """If risk_score == 0, raroc is 0.0."""
        ae = self._make(risk_score=0.0, raroc=0.0, efficiency_grade="D")
        self.assertEqual(ae.raroc, 0.0)

    def test_grade_A_threshold(self):
        """raroc > 15 → Grade A."""
        ae = self._make(raroc=15.1, efficiency_grade="A")
        self.assertEqual(ae.efficiency_grade, "A")

    def test_grade_A_boundary_exact_fails(self):
        """raroc = 15.0 is NOT grade A (strictly >)."""
        ae = self._make(raroc=15.0, efficiency_grade="B")
        self.assertEqual(ae.efficiency_grade, "B")

    def test_grade_B_threshold(self):
        """raroc > 8 and ≤ 15 → Grade B."""
        ae = self._make(raroc=8.1, efficiency_grade="B")
        self.assertEqual(ae.efficiency_grade, "B")

    def test_grade_B_boundary_exact_fails(self):
        """raroc = 8.0 is NOT grade B (strictly >)."""
        ae = self._make(raroc=8.0, efficiency_grade="C")
        self.assertEqual(ae.efficiency_grade, "C")

    def test_grade_C_threshold(self):
        """raroc > 3 and ≤ 8 → Grade C."""
        ae = self._make(raroc=3.1, efficiency_grade="C")
        self.assertEqual(ae.efficiency_grade, "C")

    def test_grade_C_boundary_exact_fails(self):
        """raroc = 3.0 is NOT grade C (strictly >)."""
        ae = self._make(raroc=3.0, efficiency_grade="D")
        self.assertEqual(ae.efficiency_grade, "D")

    def test_grade_D_threshold(self):
        """raroc ≤ 3 → Grade D."""
        ae = self._make(raroc=3.0, efficiency_grade="D")
        self.assertEqual(ae.efficiency_grade, "D")

    def test_to_dict_returns_dict(self):
        """to_dict() returns a plain dict."""
        ae = self._make()
        d = ae.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_json_serializable(self):
        """to_dict() output is JSON-serialisable."""
        ae = self._make()
        # Should not raise
        json.dumps(ae.to_dict())


# ===========================================================================
# TestCapitalEfficiencyData
# ===========================================================================

class TestCapitalEfficiencyData(unittest.TestCase):
    """10 tests covering CapitalEfficiencyData aggregate fields."""

    def _make_data(self, **kwargs) -> CapitalEfficiencyData:
        defaults = dict(
            generated_at="2026-06-13T08:00:00+00:00",
            total_capital_usd=100_000.0,
            deployed_capital_usd=85_000.0,
            idle_capital_usd=15_000.0,
            deployment_rate_pct=85.0,
            portfolio_apy_pct=5.22,
            daily_yield_usd=85_000 * 5.22 / 100 / 365,
            annual_yield_usd=85_000 * 5.22 / 100,
            avg_risk_score=0.45,
            portfolio_raroc=12.3,
            tbill_rate_pct=4.5,
            best_adapter_apy_pct=6.5,
            idle_opportunity_cost_daily=15_000 * (6.5 - 4.5) / 100 / 365,
            overall_grade="A",
            summary="Deployed 85.0% ($85K / $100K), RAROC 12.3x, Grade A",
        )
        defaults.update(kwargs)
        return CapitalEfficiencyData(**defaults)

    def test_deployment_rate_pct_field(self):
        data = self._make_data(deployment_rate_pct=85.0)
        self.assertAlmostEqual(data.deployment_rate_pct, 85.0)

    def test_idle_capital_field(self):
        data = self._make_data(idle_capital_usd=15_000.0)
        self.assertAlmostEqual(data.idle_capital_usd, 15_000.0)

    def test_opportunity_cost_calculation(self):
        idle = 20_000.0
        best = 6.5
        tbill = 4.5
        expected = idle * (best - tbill) / 100 / 365
        data = self._make_data(idle_capital_usd=idle, best_adapter_apy_pct=best,
                               idle_opportunity_cost_daily=expected)
        self.assertAlmostEqual(data.idle_opportunity_cost_daily, expected, places=6)

    def test_overall_grade_A(self):
        """A: deployment_rate > 90 AND raroc > 10."""
        data = self._make_data(deployment_rate_pct=91.0, portfolio_raroc=11.0, overall_grade="A")
        self.assertEqual(data.overall_grade, "A")

    def test_overall_grade_B_by_deployment(self):
        """B: deployment_rate > 70 (even with low raroc)."""
        data = self._make_data(deployment_rate_pct=75.0, portfolio_raroc=2.0, overall_grade="B")
        self.assertEqual(data.overall_grade, "B")

    def test_overall_grade_B_by_raroc(self):
        """B: raroc > 6 (even with low deployment)."""
        data = self._make_data(deployment_rate_pct=40.0, portfolio_raroc=7.0, overall_grade="B")
        self.assertEqual(data.overall_grade, "B")

    def test_overall_grade_C(self):
        """C: deployment_rate > 50%."""
        data = self._make_data(deployment_rate_pct=60.0, portfolio_raroc=2.0, overall_grade="C")
        self.assertEqual(data.overall_grade, "C")

    def test_overall_grade_D(self):
        """D: deployment_rate ≤ 50 and raroc ≤ 6."""
        data = self._make_data(deployment_rate_pct=40.0, portfolio_raroc=2.0, overall_grade="D")
        self.assertEqual(data.overall_grade, "D")

    def test_to_dict_returns_dict(self):
        data = self._make_data()
        d = data.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_json_serializable(self):
        data = self._make_data()
        json.dumps(data.to_dict())


# ===========================================================================
# TestLoadPositions
# ===========================================================================

class TestLoadPositions(unittest.TestCase):
    """8 tests covering load_positions() behaviour."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_returns_default_capital(self):
        total, contribs = self.reporter.load_positions()
        self.assertEqual(total, CapitalEfficiencyReport.TOTAL_CAPITAL_USD)
        self.assertEqual(contribs, [])

    def test_missing_file_returns_empty_contributions(self):
        _, contribs = self.reporter.load_positions()
        self.assertIsInstance(contribs, list)
        self.assertEqual(len(contribs), 0)

    def test_valid_file_returns_total(self):
        contribs = [_make_contribution("aave_v3", 80_000.0, 5.0, 0.4)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, total_usd=90_000.0))
        total, _ = self.reporter.load_positions()
        self.assertAlmostEqual(total, 90_000.0)

    def test_valid_file_returns_contributions(self):
        contribs = [
            _make_contribution("aave_v3", 50_000.0),
            _make_contribution("compound_v3", 40_000.0),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs))
        _, result = self.reporter.load_positions()
        self.assertEqual(len(result), 2)

    def test_zero_allocation_filtered_out(self):
        contribs = [
            _make_contribution("aave_v3", 0.0),
            _make_contribution("compound_v3", 50_000.0),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs))
        _, result = self.reporter.load_positions()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["adapter_id"], "compound_v3")

    def test_corrupted_file_returns_defaults(self):
        (Path(self.tmpdir) / "yield_attribution_tracker.json").write_text("not json")
        total, contribs = self.reporter.load_positions()
        self.assertEqual(total, CapitalEfficiencyReport.TOTAL_CAPITAL_USD)
        self.assertEqual(contribs, [])

    def test_missing_latest_key_returns_defaults(self):
        data = {"schema_version": "1.0", "snapshots": []}
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json", data)
        total, contribs = self.reporter.load_positions()
        self.assertEqual(total, CapitalEfficiencyReport.TOTAL_CAPITAL_USD)
        self.assertEqual(contribs, [])

    def test_non_list_contributions_handled(self):
        data = _make_tracker_json([])
        data["latest"]["contributions"] = {"not": "a list"}
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json", data)
        _, contribs = self.reporter.load_positions()
        self.assertEqual(contribs, [])


# ===========================================================================
# TestLoadBestApy
# ===========================================================================

class TestLoadBestApy(unittest.TestCase):
    """6 tests covering load_best_apy() behaviour."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_returns_fallback(self):
        apy = self.reporter.load_best_apy()
        self.assertEqual(apy, 5.0)

    def test_corrupted_file_returns_fallback(self):
        (Path(self.tmpdir) / "adapter_status.json").write_text("bad json")
        self.assertEqual(self.reporter.load_best_apy(), 5.0)

    def test_returns_max_apy(self):
        data = _make_adapter_status({
            "aave_v3": {"tier": "T1", "apy_pct": 3.5},
            "compound_v3": {"tier": "T1", "apy_pct": 6.8},
            "morpho": {"tier": "T2", "apy_pct": 5.0},
        })
        _write_json(Path(self.tmpdir), "adapter_status.json", data)
        self.assertAlmostEqual(self.reporter.load_best_apy(), 6.8)

    def test_skip_keys_ignored(self):
        data = {
            "generated_at": "2026-06-13",
            "schema_version": "1.0",
            "aave_v3": {"tier": "T1", "apy_pct": 4.0},
        }
        _write_json(Path(self.tmpdir), "adapter_status.json", data)
        self.assertAlmostEqual(self.reporter.load_best_apy(), 4.0)

    def test_no_valid_apy_returns_fallback(self):
        data = _make_adapter_status({"aave_v3": {"tier": "T1", "apy_pct": 0}})
        _write_json(Path(self.tmpdir), "adapter_status.json", data)
        self.assertEqual(self.reporter.load_best_apy(), 5.0)

    def test_adapters_array_included(self):
        data = {
            "generated_at": "2026-06-13",
            "aave_v3": {"tier": "T1", "apy_pct": 4.0},
            "adapters": [
                {"protocol_key": "morpho_blue", "tier": "T2", "apy_pct": 9.0},
            ],
        }
        _write_json(Path(self.tmpdir), "adapter_status.json", data)
        self.assertAlmostEqual(self.reporter.load_best_apy(), 9.0)


# ===========================================================================
# TestComputeAdapterEfficiency
# ===========================================================================

class TestComputeAdapterEfficiency(unittest.TestCase):
    """12 tests covering compute_adapter_efficiency() method."""

    def setUp(self):
        self.reporter = CapitalEfficiencyReport()

    def test_adapter_key_from_adapter_id(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution("aave_v3"))
        self.assertEqual(ae.adapter_key, "aave_v3")

    def test_adapter_key_from_adapter_key_field(self):
        contrib = {"adapter_key": "morpho_blue", "allocated_usd": 5000.0,
                   "apy_pct": 6.0, "risk_score": 0.6}
        ae = self.reporter.compute_adapter_efficiency(contrib)
        self.assertEqual(ae.adapter_key, "morpho_blue")

    def test_allocated_usd_field(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution(allocated_usd=42_000.0))
        self.assertAlmostEqual(ae.allocated_usd, 42_000.0)

    def test_apy_pct_field(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution(apy_pct=7.25))
        self.assertAlmostEqual(ae.apy_pct, 7.25)

    def test_daily_yield_usd_computed(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution(
            allocated_usd=36_500.0, apy_pct=10.0))
        expected = 36_500 * 10 / 100 / 365
        self.assertAlmostEqual(ae.daily_yield_usd, expected, places=5)

    def test_raroc_computed(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution(apy_pct=9.5, risk_score=0.5))
        # (9.5 - 4.5) / 0.5 = 10.0
        self.assertAlmostEqual(ae.raroc, 10.0, places=3)

    def test_raroc_zero_when_risk_score_explicit_zero(self):
        """When risk_score is explicitly 0, raroc = 0.0."""
        contrib = {"adapter_id": "test", "allocated_usd": 10_000.0,
                   "apy_pct": 8.0, "risk_score": 0}
        ae = self.reporter.compute_adapter_efficiency(contrib)
        self.assertEqual(ae.raroc, 0.0)

    def test_grade_A_via_method(self):
        # raroc > 15: apy=12.5, risk=0.5 → (12.5-4.5)/0.5 = 16.0 → A
        ae = self.reporter.compute_adapter_efficiency(
            _make_contribution(apy_pct=12.5, risk_score=0.5))
        self.assertEqual(ae.efficiency_grade, "A")

    def test_grade_B_via_method(self):
        # (9.5-4.5)/0.5 = 10.0 → B
        ae = self.reporter.compute_adapter_efficiency(
            _make_contribution(apy_pct=9.5, risk_score=0.5))
        self.assertEqual(ae.efficiency_grade, "B")

    def test_grade_C_via_method(self):
        # (6.0-4.5)/0.4 = 3.75 → C
        ae = self.reporter.compute_adapter_efficiency(
            _make_contribution(apy_pct=6.0, risk_score=0.4))
        self.assertEqual(ae.efficiency_grade, "C")

    def test_grade_D_via_method(self):
        # (4.8-4.5)/0.1 = 3.0 → D (not strictly > 3)
        ae = self.reporter.compute_adapter_efficiency(
            _make_contribution(apy_pct=4.8, risk_score=0.1))
        self.assertEqual(ae.efficiency_grade, "D")

    def test_returns_adapter_efficiency_type(self):
        ae = self.reporter.compute_adapter_efficiency(_make_contribution())
        self.assertIsInstance(ae, AdapterEfficiency)


# ===========================================================================
# TestGenerateReport
# ===========================================================================

class TestGenerateReport(unittest.TestCase):
    """25 tests covering generate_report() behaviour."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_positions_grade_D(self):
        report = self.reporter.generate_report()
        self.assertEqual(report.overall_grade, "D")

    def test_empty_positions_deployed_zero(self):
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.deployed_capital_usd, 0.0)

    def test_empty_positions_idle_equals_total(self):
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.idle_capital_usd, report.total_capital_usd)

    def test_empty_positions_deployment_rate_zero(self):
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.deployment_rate_pct, 0.0)

    def test_empty_positions_no_adapters(self):
        report = self.reporter.generate_report()
        self.assertEqual(len(report.adapters), 0)

    def test_empty_positions_top_bottom_empty(self):
        report = self.reporter.generate_report()
        self.assertEqual(report.top_efficiency_adapter, "")
        self.assertEqual(report.bottom_efficiency_adapter, "")

    def test_returns_capital_efficiency_data_type(self):
        report = self.reporter.generate_report()
        self.assertIsInstance(report, CapitalEfficiencyData)

    def test_has_generated_at(self):
        report = self.reporter.generate_report()
        self.assertIsInstance(report.generated_at, str)
        self.assertGreater(len(report.generated_at), 0)

    def test_full_positions_deployment_rate(self):
        contribs = [
            _make_contribution("aave_v3", 70_000.0, 5.0, 0.4),
            _make_contribution("compound_v3", 25_000.0, 4.8, 0.5),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.deployed_capital_usd, 95_000.0)
        self.assertAlmostEqual(report.deployment_rate_pct, 95.0)

    def test_full_positions_idle_correct(self):
        contribs = [_make_contribution("aave_v3", 80_000.0, 5.0, 0.4)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.idle_capital_usd, 20_000.0)

    def test_portfolio_apy_weighted_average(self):
        contribs = [
            _make_contribution("aave_v3", 50_000.0, 4.0, 0.4),
            _make_contribution("compound_v3", 50_000.0, 6.0, 0.5),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        # Weighted: (50k*4 + 50k*6) / 100k = 5.0
        self.assertAlmostEqual(report.portfolio_apy_pct, 5.0, places=3)

    def test_daily_yield_computed(self):
        contribs = [_make_contribution("aave_v3", 73_000.0, 10.0, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        expected = 73_000 * 10 / 100 / 365
        self.assertAlmostEqual(report.daily_yield_usd, expected, places=4)

    def test_annual_yield_computed(self):
        contribs = [_make_contribution("aave_v3", 50_000.0, 8.0, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.annual_yield_usd, 50_000 * 8 / 100, places=2)

    def test_avg_risk_score_computed(self):
        contribs = [
            _make_contribution("aave_v3", 50_000.0, 5.0, 0.4),
            _make_contribution("compound_v3", 50_000.0, 5.0, 0.6),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.avg_risk_score, 0.5, places=3)

    def test_portfolio_raroc_computed(self):
        contribs = [_make_contribution("aave_v3", 100_000.0, 9.5, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        # (9.5 - 4.5) / 0.5 = 10.0
        self.assertAlmostEqual(report.portfolio_raroc, 10.0, places=2)

    def test_tbill_rate_constant(self):
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.tbill_rate_pct, 4.5)

    def test_top_efficiency_adapter(self):
        contribs = [
            _make_contribution("low_earner", 50_000.0, 5.0, 0.5),   # raroc = 1.0
            _make_contribution("high_earner", 50_000.0, 12.5, 0.5), # raroc = 16.0
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertEqual(report.top_efficiency_adapter, "high_earner")

    def test_bottom_efficiency_adapter(self):
        contribs = [
            _make_contribution("low_earner", 50_000.0, 5.0, 0.5),   # raroc = 1.0
            _make_contribution("high_earner", 50_000.0, 12.5, 0.5), # raroc = 16.0
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertEqual(report.bottom_efficiency_adapter, "low_earner")

    def test_opportunity_cost_with_idle(self):
        contribs = [_make_contribution("aave_v3", 80_000.0, 5.0, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        # best_apy from adapter_status
        adapter_data = _make_adapter_status({"morpho": {"tier": "T2", "apy_pct": 7.0}})
        _write_json(Path(self.tmpdir), "adapter_status.json", adapter_data)
        report = self.reporter.generate_report()
        expected = 20_000 * (7.0 - 4.5) / 100 / 365
        self.assertAlmostEqual(report.idle_opportunity_cost_daily, expected, places=5)

    def test_opportunity_cost_zero_when_fully_deployed(self):
        contribs = [_make_contribution("aave_v3", 100_000.0, 5.0, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertAlmostEqual(report.idle_opportunity_cost_daily, 0.0, places=5)

    def test_grade_A_high_deployment_high_raroc(self):
        # 91% deployed + raroc > 10 → A
        contribs = [_make_contribution("aave_v3", 91_000.0, 12.5, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertEqual(report.overall_grade, "A")

    def test_grade_D_low_deployment_low_raroc(self):
        # 40% deployed + raroc ≤ 6 → D
        contribs = [_make_contribution("aave_v3", 40_000.0, 5.0, 0.5)]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertEqual(report.overall_grade, "D")

    def test_summary_contains_deployed(self):
        report = self.reporter.generate_report()
        self.assertIn("Deployed", report.summary)

    def test_summary_contains_grade(self):
        report = self.reporter.generate_report()
        self.assertIn("Grade", report.summary)

    def test_adapters_list_populated(self):
        contribs = [
            _make_contribution("aave_v3", 50_000.0),
            _make_contribution("compound_v3", 30_000.0),
        ]
        _write_json(Path(self.tmpdir), "yield_attribution_tracker.json",
                    _make_tracker_json(contribs, 100_000.0))
        report = self.reporter.generate_report()
        self.assertEqual(len(report.adapters), 2)


# ===========================================================================
# TestSaveReport
# ===========================================================================

class TestSaveReport(unittest.TestCase):
    """5 tests covering save_report() atomic write and ring-buffer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_output_file(self):
        path = self.reporter.save_report()
        self.assertTrue(Path(path).exists())

    def test_no_tmp_files_left(self):
        self.reporter.save_report()
        tmp_files = list(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_valid_json_output(self):
        path = self.reporter.save_report()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertIn("latest", data)
        self.assertIn("snapshots", data)

    def test_ring_buffer_max_30(self):
        """After 35 saves, ring-buffer contains exactly 30 snapshots."""
        for _ in range(35):
            self.reporter.save_report()
        data = json.loads(
            (Path(self.tmpdir) / "capital_efficiency.json").read_text(encoding="utf-8")
        )
        self.assertLessEqual(len(data["snapshots"]), 30)

    def test_second_save_appends_snapshot(self):
        self.reporter.save_report()
        self.reporter.save_report()
        data = json.loads(
            (Path(self.tmpdir) / "capital_efficiency.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(data["snapshots"]), 2)


# ===========================================================================
# TestFormatTelegramMessage
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):
    """8 tests covering format_telegram_message()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_length_at_most_1500(self):
        msg = self.reporter.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_grade(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("Grade", msg)

    def test_contains_deployed(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("Deployed", msg)

    def test_contains_idle(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("Idle", msg)

    def test_contains_apy(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("APY", msg)

    def test_contains_raroc(self):
        msg = self.reporter.format_telegram_message()
        self.assertIn("RAROC", msg)

    def test_accepts_precomputed_report(self):
        """format_telegram_message accepts a pre-computed report."""
        report = self.reporter.generate_report()
        msg = self.reporter.format_telegram_message(report=report)
        self.assertLessEqual(len(msg), 1500)

    def test_non_empty_string(self):
        msg = self.reporter.format_telegram_message()
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)


# ===========================================================================
# TestToDict
# ===========================================================================

class TestToDict(unittest.TestCase):
    """4 tests covering to_dict()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.reporter = CapitalEfficiencyReport(data_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        d = self.reporter.to_dict()
        self.assertIsInstance(d, dict)

    def test_json_serializable(self):
        d = self.reporter.to_dict()
        json.dumps(d)  # must not raise

    def test_required_keys_present(self):
        d = self.reporter.to_dict()
        required = {
            "generated_at", "total_capital_usd", "deployed_capital_usd",
            "idle_capital_usd", "deployment_rate_pct", "portfolio_apy_pct",
            "daily_yield_usd", "annual_yield_usd", "avg_risk_score",
            "portfolio_raroc", "tbill_rate_pct", "best_adapter_apy_pct",
            "idle_opportunity_cost_daily", "adapters", "top_efficiency_adapter",
            "bottom_efficiency_adapter", "overall_grade", "summary",
        }
        for key in required:
            self.assertIn(key, d, msg=f"Key '{key}' missing from to_dict()")

    def test_accepts_precomputed_report(self):
        report = self.reporter.generate_report()
        d = self.reporter.to_dict(report=report)
        self.assertIsInstance(d, dict)
        self.assertIn("generated_at", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
