"""Integration tests for analytics modules — MP-634.

End-to-end multi-module chains using real classes with synthetic data.
No mocking — every test exercises the actual module code paths.

Run with pytest:
    python3 -m pytest spa_core/tests/test_integration_analytics.py -v --tb=short

Run with unittest (no pytest required):
    python3 -m unittest spa_core.tests.test_integration_analytics -v
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path so imports work from any CWD
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.gas_cost_tracker import GasCostTracker
from spa_core.analytics.position_sizing_engine import PositionSizingEngine
from spa_core.analytics.protocol_risk_scorer import ProtocolRiskScorer
from spa_core.analytics.slippage_simulator import SlippageSimulator
from spa_core.analytics.liquidity_exit_simulator import LiquidityExitSimulator
from spa_core.analytics.apy_anomaly_detector import APYAnomalyDetector
from spa_core.analytics.benchmark_tracker import BenchmarkTracker
from spa_core.analytics.alert_threshold_manager import (
    AlertThresholdManager,
    ThresholdDefinition,
)


# ===========================================================================
# Test 1 — Gas Cost Tracker → Position Sizing → Net APY chain
# ===========================================================================

class TestFullPipelineGasToNetAPY(unittest.TestCase):
    """Record gas → optimize weights → compute_net_apy → assert net < gross."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_gas_to_net_apy_chain(self):
        # ── Step 1: record 5 gas entries ──────────────────────────────────
        tracker = GasCostTracker(data_dir=str(self.tmp_path))
        adapters_gas = [
            ("aave_v3",           150_000, 20.0),
            ("compound_v3",       160_000, 22.0),
            ("morpho_steakhouse", 170_000, 24.0),
            ("yearn_v3",          180_000, 26.0),
            ("euler_v2",          190_000, 28.0),
        ]
        for i, (adapter, gas_used, gas_price) in enumerate(adapters_gas):
            entry = tracker.record_gas(
                tx_hash=f"0xINTEG{i:04d}",
                adapter=adapter,
                chain="ethereum",
                gas_used=gas_used,
                gas_price_gwei=gas_price,
                eth_price_usd=3000.0,
            )
            self.assertGreater(entry.cost_usd, 0.0,
                               f"cost_usd should be positive for {adapter}")

        # ── Step 2: optimize position weights ─────────────────────────────
        engine = PositionSizingEngine(capital_usd=100_000.0, risk_budget=0.10)
        adapter_risks = {
            "aave_v3":           0.10,
            "compound_v3":       0.15,
            "morpho_steakhouse": 0.20,
            "yearn_v3":          0.25,
            "euler_v2":          0.30,
        }
        tier_map = {
            "aave_v3":           "T1",
            "compound_v3":       "T1",
            "morpho_steakhouse": "T1",
            "yearn_v3":          "T2",
            "euler_v2":          "T2",
        }
        apys = {
            "aave_v3":           3.5,
            "compound_v3":       4.8,
            "morpho_steakhouse": 6.5,
            "yearn_v3":          5.0,
            "euler_v2":          4.2,
        }
        results = engine.optimize(adapter_risks, tier_map, apys)
        self.assertEqual(len(results), len(adapter_risks))

        gross_apy = sum(r.recommended_weight * apys[r.adapter_id] for r in results)
        self.assertGreater(gross_apy, 0.0, "Gross APY must be positive")

        # ── Step 3: compute net APY after gas drag ─────────────────────────
        net_result = tracker.compute_net_apy(
            gross_apy=gross_apy,
            capital_usd=100_000.0,
            days=30,
        )
        self.assertLess(net_result["net_apy"], gross_apy,
                        f"net_apy {net_result['net_apy']:.4f}% must be < "
                        f"gross_apy {gross_apy:.4f}%")
        self.assertIn(net_result["grade"], ("A", "B", "C", "D"),
                      f"grade '{net_result['grade']}' must be one of A/B/C/D")
        self.assertGreaterEqual(net_result["gas_drag_bps"], 0.0)
        self.assertGreaterEqual(net_result["cost_usd"], 0.0)

    def test_zero_gas_yields_grade_a(self):
        """With no gas entries, drag is zero → grade A, net_apy == gross_apy."""
        tracker = GasCostTracker(data_dir=str(self.tmp_path))
        result = tracker.compute_net_apy(gross_apy=5.0, capital_usd=100_000.0, days=30)
        self.assertEqual(result["grade"], "A")
        self.assertEqual(result["gas_drag_bps"], 0.0)
        self.assertAlmostEqual(result["net_apy"], 5.0, places=5)


# ===========================================================================
# Test 2 — Protocol Risk Scorer → Position Sizing (risk-parity) chain
# ===========================================================================

class TestProtocolRiskFeedsPositionSizing(unittest.TestCase):
    """score_all() → compute_risk_parity() → weights sum to 1 and ≤ caps."""

    def test_risk_parity_weights_from_scorer(self):
        scorer = ProtocolRiskScorer()
        scores = scorer.score_all()
        self.assertGreater(len(scores), 0,
                           "KNOWN_PROTOCOLS must contain at least one entry")

        top5 = dict(list(scores.items())[:5])
        adapter_risks = {aid: result.total_score for aid, result in top5.items()}

        engine = PositionSizingEngine(capital_usd=100_000.0)
        weights = engine.compute_risk_parity(adapter_risks)

        self.assertEqual(len(weights), len(adapter_risks),
                         "One weight per adapter")
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=9,
                               msg=f"Weights must sum to 1.0, got {total:.10f}")
        for adapter_id, w in weights.items():
            self.assertGreaterEqual(w, 0.0,
                                    f"Weight for {adapter_id} must be non-negative")
            self.assertLessEqual(w, 1.0,
                                 f"Weight for {adapter_id} must be ≤ 1.0")

    def test_tier_caps_applied_after_risk_parity(self):
        """After apply_tier_caps, no T1 adapter exceeds 40%, no T2 exceeds 25%."""
        scorer = ProtocolRiskScorer()
        scores = scorer.score_all()

        adapter_ids = list(scores.keys())[:6]
        adapter_risks = {aid: scores[aid].total_score for aid in adapter_ids}
        tier_map = {
            aid: ("T1" if i < 3 else "T2")
            for i, aid in enumerate(adapter_ids)
        }

        engine = PositionSizingEngine(capital_usd=100_000.0)
        rp_weights = engine.compute_risk_parity(adapter_risks)
        capped = engine.apply_tier_caps(rp_weights, tier_map)

        for aid, w in capped.items():
            tier = tier_map.get(aid, "T1")
            cap = 0.40 if tier == "T1" else 0.25
            self.assertLessEqual(w, cap + 1e-9,
                                 f"{aid} (tier={tier}) weight {w:.4f} exceeds cap {cap}")

        total = sum(capped.values())
        self.assertAlmostEqual(total, 1.0, places=5,
                               msg=f"Capped weights must sum to ~1.0, got {total}")


# ===========================================================================
# Test 3 — Slippage Simulator → effective APY chain
# ===========================================================================

class TestSlippageAffectsEffectiveAPY(unittest.TestCase):
    """estimate_slippage for 5 adapters → compute_effective_apy → effective < gross."""

    ADAPTERS = [
        ("aave_v3",           50_000.0,  2_000_000_000.0),
        ("compound_v3",       30_000.0,    500_000_000.0),
        ("morpho_steakhouse", 20_000.0,     80_000_000.0),
        ("yearn_v3",          10_000.0,     10_000_000.0),
        ("maple",              5_000.0,      1_000_000.0),
    ]

    def test_effective_apy_always_below_gross(self):
        sim = SlippageSimulator()
        gross_apy = 0.07  # 7%

        for adapter_id, trade_size, tvl in self.ADAPTERS:
            estimate = sim.estimate_slippage(adapter_id, trade_size, tvl)
            effective = sim.compute_effective_apy(
                gross_apy=gross_apy,
                slippage_bps=estimate.slippage_bps,
            )
            self.assertLess(effective, gross_apy,
                            f"{adapter_id}: effective_apy {effective:.6f} should be < "
                            f"gross_apy {gross_apy} (slippage_bps={estimate.slippage_bps:.4f})")

    def test_higher_tvl_means_lower_slippage(self):
        """Larger TVL → lower slippage for the same trade size."""
        sim = SlippageSimulator()
        small_tvl = sim.estimate_slippage("proto_low",  10_000.0,  1_000_000.0)
        large_tvl = sim.estimate_slippage("proto_high", 10_000.0, 1_000_000_000.0)
        self.assertLess(large_tvl.slippage_bps, small_tvl.slippage_bps,
                        "Larger TVL should produce lower slippage")

    def test_portfolio_slippage_report_structure(self):
        sim = SlippageSimulator()
        trades  = {aid: ts  for aid, ts, _  in self.ADAPTERS}
        tvl_map = {aid: tvl for aid, _,  tvl in self.ADAPTERS}
        report = sim.generate_report(trades, tvl_map)

        self.assertIn("estimates", report)
        self.assertEqual(len(report["estimates"]), len(self.ADAPTERS))
        self.assertIsNotNone(report["worst_adapter"])
        self.assertIsNotNone(report["best_adapter"])


# ===========================================================================
# Test 4 — Liquidity Exit Simulator: worst-case ranking + risk score
# ===========================================================================

class TestExitRiskRanksScenarios(unittest.TestCase):
    """estimate_portfolio_exit → worst_case has max blocks → score in [0,100]."""

    POSITIONS = {
        "aave_v3":           10_000.0,
        "compound_v3":       30_000.0,
        "morpho_steakhouse": 20_000.0,
        "yearn_v3":          50_000.0,
        "maple":             40_000.0,
    }
    TVL_MAP = {
        "aave_v3":           2_000_000_000.0,
        "compound_v3":         500_000_000.0,
        "morpho_steakhouse":    80_000_000.0,
        "yearn_v3":              5_000_000.0,
        "maple":                   500_000.0,  # very low TVL → RISKY
    }

    def _make_sim(self):
        return LiquidityExitSimulator(data_dir=None)

    def test_worst_case_has_maximum_blocks(self):
        sim = self._make_sim()
        scenarios = sim.estimate_portfolio_exit(self.POSITIONS, self.TVL_MAP)
        self.assertEqual(len(scenarios), len(self.POSITIONS))

        worst = sim.get_worst_case_exit(scenarios)
        self.assertIsNotNone(worst)
        for s in scenarios:
            self.assertGreaterEqual(
                worst.estimated_exit_blocks, s.estimated_exit_blocks,
                f"worst ({worst.adapter_id}, {worst.estimated_exit_blocks} blocks) "
                f"< {s.adapter_id} ({s.estimated_exit_blocks} blocks)")

    def test_exit_risk_score_range(self):
        sim = self._make_sim()
        scenarios = sim.estimate_portfolio_exit(self.POSITIONS, self.TVL_MAP)
        score = sim.compute_exit_risk_score(scenarios)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0,
                             f"risk_score {score} not in [0, 100]")

    def test_low_tvl_adapter_is_slow(self):
        """Low-TVL adapter: capacity < position/20 → blocks > 20 → SLOW feasibility.
        TVL=$50k, pos=$40k: capacity=1000, blocks=40 → SLOW."""
        sim = self._make_sim()
        # TVL=$50k: capacity_per_block = 50_000 * 0.02 = 1_000
        # blocks = ceil(40_000 / 1_000) = 40 → SLOW (20 < blocks ≤ 100)
        scenario = sim.estimate_exit("low_tvl_proto", 40_000.0, 50_000.0)
        self.assertIn(scenario.exit_feasibility, ("RISKY", "SLOW"),
                      f"Expected RISKY/SLOW for low-TVL adapter, "
                      f"got {scenario.exit_feasibility} "
                      f"(blocks={scenario.estimated_exit_blocks})")

    def test_deep_tvl_adapter_instant(self):
        """aave_v3 (TVL=$2B, pos=$10k) must be INSTANT."""
        sim = self._make_sim()
        scenario = sim.estimate_exit("aave_v3", 10_000.0, 2_000_000_000.0)
        self.assertEqual(scenario.exit_feasibility, "INSTANT")
        self.assertTrue(scenario.can_exit_in_one_block)

    def test_empty_scenarios_return_safe_defaults(self):
        sim = self._make_sim()
        self.assertEqual(sim.compute_exit_risk_score([]), 0.0)
        self.assertIsNone(sim.get_worst_case_exit([]))


# ===========================================================================
# Test 5 — APY Anomaly Detector on synthetic data
# ===========================================================================

class TestAnomalyDetectionOnSyntheticData(unittest.TestCase):
    """normal + SPIKE + NEGATIVE → ≥2 anomalies found, ≥1 CRITICAL."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_spike_and_negative_detected(self):
        # No history in tmp_path → SPIKE needs history, so use:
        #   outlier_adapter at 0.60 (>0.50 max_apy)  → OUTLIER/CRITICAL
        #   negative_adapter at -0.05 (<-0.01 min_apy) → NEGATIVE/CRITICAL
        # Both trigger without any history data.
        detector = APYAnomalyDetector(data_dir=str(self.tmp_path))
        apy_map = {
            "normal_adapter":   0.05,   # 5%  — within normal range
            "outlier_adapter":  0.60,   # 60% — OUTLIER (> 50% ceiling) → CRITICAL
            "negative_adapter": -0.05,  # -5% — NEGATIVE (< -1% floor)  → CRITICAL
        }
        anomalies = detector.scan_all_adapters(apy_map)

        self.assertGreaterEqual(len(anomalies), 2,
                                f"Expected ≥2 anomalies, got {len(anomalies)}: "
                                f"{[(a.adapter_id, a.anomaly_type) for a in anomalies]}")
        critical = [a for a in anomalies if a.severity == "CRITICAL"]
        self.assertGreaterEqual(len(critical), 1,
                                f"Expected ≥1 CRITICAL, got severities: "
                                f"{[a.severity for a in anomalies]}")

    def test_negative_apy_always_critical(self):
        """APY below -1% (min_apy=-0.01) must produce a CRITICAL NEGATIVE anomaly."""
        detector = APYAnomalyDetector(data_dir=str(self.tmp_path))
        # min_apy = -0.01; need strictly < -0.01 to trigger NEGATIVE
        anomalies = detector.scan_all_adapters({"bad_protocol": -0.05})
        critical = [a for a in anomalies if a.severity == "CRITICAL"]
        self.assertGreaterEqual(len(critical), 1,
                                "APY below min_apy should produce CRITICAL")

    def test_normal_range_produces_no_critical(self):
        """Adapters with normal APY values should not produce CRITICAL anomalies."""
        detector = APYAnomalyDetector(data_dir=str(self.tmp_path))
        apy_map = {
            "aave_v3":           0.035,
            "compound_v3":       0.048,
            "morpho_steakhouse": 0.065,
        }
        anomalies = detector.scan_all_adapters(apy_map)
        critical = [a for a in anomalies if a.severity == "CRITICAL"]
        self.assertEqual(len(critical), 0,
                         f"Normal APY should not produce CRITICAL anomalies, got: "
                         f"{[(a.adapter_id, a.anomaly_type, a.reported_apy) for a in critical]}")

    def test_generate_report_structure(self):
        """generate_report() returns valid structure with all required keys."""
        detector = APYAnomalyDetector(data_dir=str(self.tmp_path))
        apy_map = {"p1": 0.05, "p2": -0.02, "p3": 0.40}
        report = detector.generate_report(apy_map)

        for key in ("generated_at", "anomalies", "critical_count",
                    "warning_count", "info_count", "clean_adapters", "advisory"):
            self.assertIn(key, report, f"Missing key '{key}' in anomaly report")
        self.assertGreaterEqual(report["critical_count"], 0)
        self.assertIsInstance(report["anomalies"], list)


# ===========================================================================
# Test 6 — Benchmark Tracker vs portfolio
# ===========================================================================

class TestBenchmarkVsPortfolio(unittest.TestCase):
    """Portfolio at 5.5% → outperforms all benchmarks → valid verdict string."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_outperforming_all_benchmarks(self):
        tracker = BenchmarkTracker(data_path=str(self.tmp_path))
        portfolio_apy = 5.5  # > T-Bill(4.5), USDC(4.0), ETH(3.5), BestAdapter(5.0)

        benchmarks = [
            tracker.compute_benchmark("T-Bill",       4.5, portfolio_apy),
            tracker.compute_benchmark("USDC Hold",    4.0, portfolio_apy),
            tracker.compute_benchmark("ETH Staking",  3.5, portfolio_apy),
            tracker.compute_benchmark("Best Adapter", 5.0, portfolio_apy),
        ]
        for result in benchmarks:
            self.assertTrue(result.outperforming,
                            f"Expected outperforming for {result.name} "
                            f"(bench={result.apy_pct}%, portfolio={portfolio_apy}%)")
            self.assertGreater(result.excess_return_pct, 0.0)

    def test_verdict_valid_values(self):
        tracker = BenchmarkTracker(data_path=str(self.tmp_path))
        valid = {"ALPHA+", "ALPHA", "BENCHMARK", "LAGGING"}

        cases = [
            (2.0,  "ALPHA+"),
            (1.0,  "ALPHA"),
            (0.1,  "BENCHMARK"),
            (-1.0, "LAGGING"),
        ]
        for excess, expected in cases:
            verdict = tracker._determine_verdict(excess)
            self.assertIn(verdict, valid, f"Verdict '{verdict}' not in {valid}")
            self.assertEqual(verdict, expected,
                             f"excess={excess}%: expected '{expected}', got '{verdict}'")

    def test_lagging_below_all_benchmarks(self):
        tracker = BenchmarkTracker(data_path=str(self.tmp_path))
        excess = 2.0 - 4.5   # portfolio 2% vs T-Bill 4.5% = -2.5%
        verdict = tracker._determine_verdict(excess)
        self.assertEqual(verdict, "LAGGING",
                         f"Expected LAGGING for excess=-2.5%, got {verdict}")


# ===========================================================================
# Test 7 — Alert Threshold Manager integration
# ===========================================================================

class TestAlertThresholdManagerIntegration(unittest.TestCase):
    """Custom thresholds with synthetic JSON → ≥1 WARNING, all_clear=False."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_chain_concentration_triggers_warning(self):
        # dominant_weight_pct = 100 → triggers "chain_concentration" (gt 70%)
        chain_file = self.tmp_path / "chain_exposure.json"
        chain_file.write_text(json.dumps({"dominant_weight_pct": 100.0}))

        thresholds = [
            ThresholdDefinition(
                name="chain_concentration",
                metric_path=str(chain_file),   # absolute → used directly
                operator="gt",
                threshold_value=70.0,
                severity="WARNING",
                message_template=(
                    "Chain concentration {value:.1f}% exceeds policy {threshold:.1f}%"
                ),
            ),
        ]
        manager = AlertThresholdManager(
            data_path=str(self.tmp_path), thresholds=thresholds
        )
        report = manager.run_all_checks()

        self.assertFalse(report.all_clear,
                         "all_clear should be False with active alert")
        self.assertGreaterEqual(report.alerts_active, 1)
        warnings = [e for e in report.events if e.severity == "WARNING" and e.is_active]
        self.assertGreaterEqual(len(warnings), 1,
                                f"Expected ≥1 WARNING, got: "
                                f"{[(e.threshold_name, e.severity) for e in report.events]}")

    def test_multiple_thresholds_compound(self):
        """Two triggered thresholds → all_clear=False, warning_count ≥ 2."""
        chain_file = self.tmp_path / "chain_exposure.json"
        chain_file.write_text(json.dumps({"dominant_weight_pct": 95.0}))

        risk_file = self.tmp_path / "integrated_risk.json"
        risk_file.write_text(json.dumps({"overall_score": 0.60}))

        thresholds = [
            ThresholdDefinition(
                "chain_concentration", str(chain_file),
                "gt", 70.0, "WARNING",
                "Chain concentration {value:.1f}% exceeds {threshold:.1f}%",
            ),
            ThresholdDefinition(
                "risk_score_warning", str(risk_file),
                "gt", 0.25, "WARNING",
                "Risk score {value:.2f} exceeds {threshold:.2f}",
            ),
        ]
        manager = AlertThresholdManager(
            data_path=str(self.tmp_path), thresholds=thresholds
        )
        report = manager.run_all_checks()

        self.assertFalse(report.all_clear)
        self.assertGreaterEqual(report.warning_count, 2,
                                f"Expected ≥2 WARNINGs, got {report.warning_count}")

    def test_all_clear_when_below_threshold(self):
        """Below-threshold values → all_clear=True."""
        chain_file = self.tmp_path / "chain_exposure.json"
        chain_file.write_text(json.dumps({"dominant_weight_pct": 30.0}))  # < 70

        thresholds = [
            ThresholdDefinition(
                "chain_concentration", str(chain_file),
                "gt", 70.0, "WARNING",
                "Chain concentration {value:.1f}% exceeds {threshold:.1f}%",
            ),
        ]
        manager = AlertThresholdManager(
            data_path=str(self.tmp_path), thresholds=thresholds
        )
        report = manager.run_all_checks()

        self.assertTrue(report.all_clear,
                        f"Expected all_clear=True, got events: "
                        f"{[(e.threshold_name, e.current_value) for e in report.events]}")

    def test_missing_data_file_does_not_raise(self):
        """Missing metric file → threshold skipped gracefully, no exception."""
        thresholds = [
            ThresholdDefinition(
                "chain_concentration",
                str(self.tmp_path / "nonexistent_file.json"),
                "gt", 70.0, "WARNING",
                "Chain concentration {value:.1f}% exceeds {threshold:.1f}%",
            ),
        ]
        manager = AlertThresholdManager(
            data_path=str(self.tmp_path), thresholds=thresholds
        )
        # Must not raise; missing file → metric None → threshold skipped → all_clear
        report = manager.run_all_checks()
        self.assertTrue(report.all_clear)


# ===========================================================================
# Smoke tests — all 7 modules instantiable
# ===========================================================================

class TestModuleImports(unittest.TestCase):
    """All 7 analytics modules can be imported and instantiated without error."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_all_modules_importable(self):
        for cls in (GasCostTracker, PositionSizingEngine, ProtocolRiskScorer,
                    SlippageSimulator, LiquidityExitSimulator, APYAnomalyDetector,
                    BenchmarkTracker, AlertThresholdManager):
            self.assertIsNotNone(cls)

    def test_all_modules_instantiable(self):
        tmp = str(self.tmp_path)
        GasCostTracker(data_dir=tmp)
        PositionSizingEngine(capital_usd=50_000.0)
        ProtocolRiskScorer()
        SlippageSimulator()
        LiquidityExitSimulator(data_dir=None)
        APYAnomalyDetector(data_dir=tmp)
        BenchmarkTracker(data_path=tmp)
        AlertThresholdManager(data_path=tmp, thresholds=[])


if __name__ == "__main__":
    unittest.main(verbosity=2)
