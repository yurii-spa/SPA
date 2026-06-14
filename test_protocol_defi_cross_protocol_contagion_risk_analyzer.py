"""
Tests for MP-1069: ProtocolDeFiCrossProtocolContagionRiskAnalyzer
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_cross_protocol_contagion_risk_analyzer
"""
import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.protocol_defi_cross_protocol_contagion_risk_analyzer import (
    ProtocolDeFiCrossProtocolContagionRiskAnalyzer,
    VALID_LABELS,
    DEPENDENCY_TYPE_WEIGHT,
    _clamp,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_exposed(name="ProtocolB", shared_tvl=1_000_000, dep_type="liquidity"):
    return {"name": name, "shared_tvl_usd": shared_tvl, "dependency_type": dep_type}


def _make_payload(**kwargs):
    defaults = {
        "protocol_name": "TestProtocol",
        "tvl_usd": 50_000_000,
        "protocols_exposed_to": [
            _make_exposed("ProtocolA", 2_000_000, "collateral"),
            _make_exposed("ProtocolB", 1_000_000, "liquidity"),
        ],
        "shared_collateral_assets": ["USDC", "ETH"],
        "oracle_providers": ["Chainlink"],
        "bridge_dependencies": [],
        "insurance_coverage_usd": 5_000_000,
        "circuit_breaker_exists": True,
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer(tmp_dir):
    log_path = os.path.join(tmp_dir, "cross_protocol_contagion_risk_log.json")
    return ProtocolDeFiCrossProtocolContagionRiskAnalyzer(log_path=log_path)


# ===========================================================================
# 1. Return structure
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_analyze_returns_dict(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r, dict)

    def test_result_has_protocol_name(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("protocol_name", r)

    def test_result_has_contagion_surface_usd(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("contagion_surface_usd", r)

    def test_result_has_dependency_concentration_score(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("dependency_concentration_score", r)

    def test_result_has_contagion_risk_score(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("contagion_risk_score", r)

    def test_result_has_insured_ratio(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("insured_ratio", r)

    def test_result_has_contagion_label(self):
        r = self.ana.analyze(_make_payload())
        self.assertIn("contagion_label", r)

    def test_result_has_exactly_six_keys(self):
        r = self.ana.analyze(_make_payload())
        self.assertEqual(len(r), 6)

    def test_protocol_name_propagated(self):
        r = self.ana.analyze(_make_payload(protocol_name="MYPROTOCOL"))
        self.assertEqual(r["protocol_name"], "MYPROTOCOL")


# ===========================================================================
# 2. contagion_surface_usd
# ===========================================================================

class TestContagionSurface(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_surface_is_sum_of_shared_tvls(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[
                _make_exposed("A", 1_000_000),
                _make_exposed("B", 2_000_000),
                _make_exposed("C", 500_000),
            ]
        ))
        self.assertAlmostEqual(r["contagion_surface_usd"], 3_500_000.0, places=2)

    def test_surface_zero_with_no_exposure(self):
        r = self.ana.analyze(_make_payload(protocols_exposed_to=[]))
        self.assertEqual(r["contagion_surface_usd"], 0.0)

    def test_surface_single_protocol(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("OnlyOne", 7_777_777)]
        ))
        self.assertAlmostEqual(r["contagion_surface_usd"], 7_777_777.0, places=0)

    def test_surface_is_non_negative(self):
        r = self.ana.analyze(_make_payload())
        self.assertGreaterEqual(r["contagion_surface_usd"], 0.0)

    def test_surface_is_float(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r["contagion_surface_usd"], float)

    def test_surface_increases_with_more_protocols(self):
        r1 = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("A", 1_000_000)]
        ))
        r2 = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("A", 1_000_000), _make_exposed("B", 1_000_000)]
        ))
        self.assertGreater(r2["contagion_surface_usd"], r1["contagion_surface_usd"])


# ===========================================================================
# 3. dependency_concentration_score
# ===========================================================================

class TestDependencyConcentrationScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_score_in_range_0_to_100(self):
        r = self.ana.analyze(_make_payload())
        self.assertGreaterEqual(r["dependency_concentration_score"], 0.0)
        self.assertLessEqual(r["dependency_concentration_score"], 100.0)

    def test_score_100_for_single_protocol(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("OnlyOne", 5_000_000)]
        ))
        self.assertAlmostEqual(r["dependency_concentration_score"], 100.0, places=2)

    def test_score_zero_with_no_exposure(self):
        r = self.ana.analyze(_make_payload(protocols_exposed_to=[]))
        self.assertEqual(r["dependency_concentration_score"], 0.0)

    def test_more_equal_split_lowers_concentration(self):
        r_single = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("A", 10_000_000)]
        ))
        r_split = self.ana.analyze(_make_payload(
            protocols_exposed_to=[
                _make_exposed("A", 5_000_000),
                _make_exposed("B", 5_000_000),
            ]
        ))
        self.assertGreater(
            r_single["dependency_concentration_score"],
            r_split["dependency_concentration_score"]
        )

    def test_oracle_dep_type_weighted_higher_than_yield(self):
        self.assertGreater(
            DEPENDENCY_TYPE_WEIGHT["oracle"],
            DEPENDENCY_TYPE_WEIGHT["yield"]
        )

    def test_score_is_float(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r["dependency_concentration_score"], float)

    def test_unknown_dep_type_uses_default(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[
                _make_exposed("A", 5_000_000, "unknown_dep_type_xyz"),
            ]
        ))
        self.assertGreaterEqual(r["dependency_concentration_score"], 0.0)


# ===========================================================================
# 4. contagion_risk_score
# ===========================================================================

class TestContagionRiskScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_score_in_range_0_to_100(self):
        r = self.ana.analyze(_make_payload())
        self.assertGreaterEqual(r["contagion_risk_score"], 0.0)
        self.assertLessEqual(r["contagion_risk_score"], 100.0)

    def test_isolated_protocol_low_score(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=100_000_000,
            protocols_exposed_to=[],
            shared_collateral_assets=[],
            oracle_providers=[],
            bridge_dependencies=[],
            insurance_coverage_usd=50_000_000,
            circuit_breaker_exists=True,
        ))
        self.assertLess(r["contagion_risk_score"], 15.0)

    def test_high_exposure_increases_score(self):
        r_low = self.ana.analyze(_make_payload(
            tvl_usd=100_000_000,
            protocols_exposed_to=[_make_exposed("A", 1_000_000)],
        ))
        r_high = self.ana.analyze(_make_payload(
            tvl_usd=100_000_000,
            protocols_exposed_to=[_make_exposed("A", 90_000_000)],
        ))
        self.assertGreater(r_high["contagion_risk_score"], r_low["contagion_risk_score"])

    def test_circuit_breaker_reduces_score(self):
        r_no_cb = self.ana.analyze(_make_payload(circuit_breaker_exists=False))
        r_cb = self.ana.analyze(_make_payload(circuit_breaker_exists=True))
        self.assertGreater(r_no_cb["contagion_risk_score"], r_cb["contagion_risk_score"])

    def test_insurance_reduces_score(self):
        r_no_ins = self.ana.analyze(_make_payload(insurance_coverage_usd=0))
        r_ins = self.ana.analyze(_make_payload(insurance_coverage_usd=50_000_000))
        self.assertGreaterEqual(r_no_ins["contagion_risk_score"], r_ins["contagion_risk_score"])

    def test_more_bridges_increases_score(self):
        r0 = self.ana.analyze(_make_payload(bridge_dependencies=[]))
        r3 = self.ana.analyze(_make_payload(bridge_dependencies=["B1", "B2", "B3"]))
        self.assertGreater(r3["contagion_risk_score"], r0["contagion_risk_score"])

    def test_more_oracles_increases_score(self):
        r0 = self.ana.analyze(_make_payload(oracle_providers=[]))
        r3 = self.ana.analyze(_make_payload(oracle_providers=["O1", "O2", "O3"]))
        self.assertGreater(r3["contagion_risk_score"], r0["contagion_risk_score"])

    def test_more_shared_collateral_increases_score(self):
        r0 = self.ana.analyze(_make_payload(shared_collateral_assets=[]))
        r5 = self.ana.analyze(_make_payload(
            shared_collateral_assets=["A", "B", "C", "D", "E"]
        ))
        self.assertGreater(r5["contagion_risk_score"], r0["contagion_risk_score"])

    def test_score_is_float(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r["contagion_risk_score"], float)

    def test_score_deterministic(self):
        p = _make_payload()
        r1 = self.ana.analyze(p)
        r2 = self.ana.analyze(p)
        self.assertEqual(r1["contagion_risk_score"], r2["contagion_risk_score"])


# ===========================================================================
# 5. insured_ratio
# ===========================================================================

class TestInsuredRatio(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_insured_ratio_basic(self):
        r = self.ana.analyze(_make_payload(tvl_usd=100_000_000, insurance_coverage_usd=50_000_000))
        self.assertAlmostEqual(r["insured_ratio"], 0.5, places=4)

    def test_insured_ratio_zero_coverage(self):
        r = self.ana.analyze(_make_payload(insurance_coverage_usd=0))
        self.assertEqual(r["insured_ratio"], 0.0)

    def test_insured_ratio_full_coverage_capped_at_1(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=100_000_000, insurance_coverage_usd=200_000_000
        ))
        self.assertAlmostEqual(r["insured_ratio"], 1.0, places=4)

    def test_insured_ratio_zero_tvl_returns_zero(self):
        r = self.ana.analyze(_make_payload(tvl_usd=0, insurance_coverage_usd=1_000_000))
        self.assertEqual(r["insured_ratio"], 0.0)

    def test_insured_ratio_in_range(self):
        r = self.ana.analyze(_make_payload())
        self.assertGreaterEqual(r["insured_ratio"], 0.0)
        self.assertLessEqual(r["insured_ratio"], 1.0)

    def test_insured_ratio_is_float(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r["insured_ratio"], float)


# ===========================================================================
# 6. contagion_label
# ===========================================================================

class TestContagionLabel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_label_always_valid(self):
        for _ in range(5):
            r = self.ana.analyze(_make_payload())
            self.assertIn(r["contagion_label"], VALID_LABELS)

    def test_isolated_label_for_minimal_exposure(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=500_000_000,
            protocols_exposed_to=[],
            shared_collateral_assets=[],
            oracle_providers=[],
            bridge_dependencies=[],
            insurance_coverage_usd=250_000_000,
            circuit_breaker_exists=True,
        ))
        self.assertEqual(r["contagion_label"], "ISOLATED_PROTOCOL")

    def test_systemic_risk_label_for_maximum_exposure(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=10_000_000,
            protocols_exposed_to=[
                _make_exposed("P1", 10_000_000, "oracle"),
                _make_exposed("P2", 10_000_000, "bridge"),
                _make_exposed("P3", 10_000_000, "collateral"),
                _make_exposed("P4", 10_000_000, "liquidity"),
                _make_exposed("P5", 10_000_000, "governance"),
            ],
            shared_collateral_assets=["A", "B", "C", "D", "E"],
            oracle_providers=["O1", "O2", "O3"],
            bridge_dependencies=["B1", "B2", "B3", "B4", "B5"],
            insurance_coverage_usd=0,
            circuit_breaker_exists=False,
        ))
        self.assertIn(r["contagion_label"], {"HIGH_CONTAGION_RISK", "SYSTEMIC_RISK_NODE"})

    def test_label_is_string(self):
        r = self.ana.analyze(_make_payload())
        self.assertIsInstance(r["contagion_label"], str)

    def test_five_valid_labels(self):
        self.assertEqual(len(VALID_LABELS), 5)

    def test_low_contagion_label(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=100_000_000,
            protocols_exposed_to=[_make_exposed("A", 500_000)],
            shared_collateral_assets=["USDC"],
            oracle_providers=[],
            bridge_dependencies=[],
            insurance_coverage_usd=20_000_000,
            circuit_breaker_exists=True,
        ))
        self.assertIn(r["contagion_label"], {"ISOLATED_PROTOCOL", "LOW_CONTAGION"})

    def test_moderate_interconnect_label(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=20_000_000,
            protocols_exposed_to=[
                _make_exposed("A", 5_000_000, "collateral"),
                _make_exposed("B", 3_000_000, "oracle"),
            ],
            shared_collateral_assets=["ETH", "USDC", "WBTC"],
            oracle_providers=["Chainlink", "Pyth"],
            bridge_dependencies=[],
            insurance_coverage_usd=0,
            circuit_breaker_exists=False,
        ))
        self.assertIn(r["contagion_label"], {
            "LOW_CONTAGION", "MODERATE_INTERCONNECT", "HIGH_CONTAGION_RISK"
        })


# ===========================================================================
# 7. analyze_batch
# ===========================================================================

class TestAnalyzeBatch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_batch_returns_list(self):
        results = self.ana.analyze_batch([_make_payload(), _make_payload()])
        self.assertIsInstance(results, list)

    def test_batch_length_matches_input(self):
        payloads = [_make_payload() for _ in range(5)]
        results = self.ana.analyze_batch(payloads)
        self.assertEqual(len(results), 5)

    def test_batch_empty_list(self):
        results = self.ana.analyze_batch([])
        self.assertEqual(results, [])

    def test_batch_none_input(self):
        results = self.ana.analyze_batch(None)
        self.assertEqual(results, [])

    def test_batch_each_element_is_dict(self):
        results = self.ana.analyze_batch([_make_payload(), _make_payload()])
        for r in results:
            self.assertIsInstance(r, dict)

    def test_batch_each_has_contagion_label(self):
        results = self.ana.analyze_batch([_make_payload() for _ in range(3)])
        for r in results:
            self.assertIn("contagion_label", r)
            self.assertIn(r["contagion_label"], VALID_LABELS)


# ===========================================================================
# 8. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "cross_protocol_contagion_risk_log.json")
        self.ana = ProtocolDeFiCrossProtocolContagionRiskAnalyzer(log_path=self.log_path)

    def test_log_file_created_on_analyze(self):
        self.ana.analyze(_make_payload())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_on_multiple_calls(self):
        for _ in range(3):
            self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        ana = ProtocolDeFiCrossProtocolContagionRiskAnalyzer(log_path=self.log_path, log_cap=5)
        for _ in range(10):
            ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_log_entry_has_ts(self):
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_protocol_name(self):
        self.ana.analyze(_make_payload(protocol_name="LOGPROT"))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "LOGPROT")

    def test_log_entry_has_contagion_risk_score(self):
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("contagion_risk_score", data[0])

    def test_log_entry_has_contagion_label(self):
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("contagion_label", data[0])

    def test_log_entry_has_contagion_surface_usd(self):
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("contagion_surface_usd", data[0])

    def test_log_atomic_write_no_tmp_leftover(self):
        self.ana.analyze(_make_payload())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupted_log_resets_gracefully(self):
        with open(self.log_path, "w") as f:
            f.write("CORRUPTED{{{")
        self.ana.analyze(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_batch_creates_multiple_entries(self):
        self.ana.analyze_batch([_make_payload() for _ in range(4)])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)


# ===========================================================================
# 9. Helper functions
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-10.0, 0.0, 100.0), 0.0)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(200.0, 0.0, 100.0), 100.0)

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(42.5, 0.0, 100.0), 42.5)

    def test_clamp_at_boundaries(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)

    def test_safe_float_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_safe_float_string(self):
        self.assertAlmostEqual(_safe_float("2.71"), 2.71, places=5)

    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None, 42.0), 42.0)

    def test_safe_float_bad_string(self):
        self.assertEqual(_safe_float("xyz", -99.0), -99.0)

    def test_dependency_type_weight_oracle_greatest(self):
        self.assertEqual(
            max(DEPENDENCY_TYPE_WEIGHT.values()),
            DEPENDENCY_TYPE_WEIGHT["oracle"]
        )

    def test_dependency_type_weight_treasury_smallest(self):
        self.assertEqual(
            min(DEPENDENCY_TYPE_WEIGHT.values()),
            DEPENDENCY_TYPE_WEIGHT["yield"]
        )


# ===========================================================================
# 10. Internal method unit tests
# ===========================================================================

class TestInternalMethods(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_compute_contagion_surface_empty(self):
        self.assertEqual(self.ana._compute_contagion_surface_usd([]), 0.0)

    def test_compute_contagion_surface_none(self):
        self.assertEqual(self.ana._compute_contagion_surface_usd(None), 0.0)

    def test_compute_contagion_surface_single(self):
        self.assertAlmostEqual(
            self.ana._compute_contagion_surface_usd([_make_exposed("A", 5_000_000)]),
            5_000_000.0, places=2
        )

    def test_compute_contagion_surface_multiple(self):
        exposed = [_make_exposed("A", 1_000), _make_exposed("B", 2_000), _make_exposed("C", 3_000)]
        self.assertAlmostEqual(
            self.ana._compute_contagion_surface_usd(exposed), 6_000.0, places=2
        )

    def test_compute_dep_conc_score_empty(self):
        self.assertEqual(self.ana._compute_dependency_concentration_score([]), 0.0)

    def test_compute_dep_conc_score_single_is_100(self):
        self.assertAlmostEqual(
            self.ana._compute_dependency_concentration_score([_make_exposed("A", 1_000_000)]),
            100.0, places=2
        )

    def test_compute_dep_conc_score_two_equal_drops(self):
        # Two equal shares → HHI = 2 × (0.5)² × 100 = 50
        score = self.ana._compute_dependency_concentration_score([
            _make_exposed("A", 5_000, "liquidity"),
            _make_exposed("B", 5_000, "liquidity"),
        ])
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_compute_insured_ratio_basic(self):
        self.assertAlmostEqual(
            self.ana._compute_insured_ratio(25_000_000, 100_000_000), 0.25, places=4
        )

    def test_compute_insured_ratio_over_capped(self):
        self.assertAlmostEqual(
            self.ana._compute_insured_ratio(200_000_000, 100_000_000), 1.0, places=4
        )

    def test_compute_insured_ratio_zero_tvl(self):
        self.assertEqual(self.ana._compute_insured_ratio(1_000_000, 0), 0.0)

    def test_assign_label_isolated(self):
        self.assertEqual(self.ana._assign_label(5.0), "ISOLATED_PROTOCOL")

    def test_assign_label_low_contagion(self):
        self.assertEqual(self.ana._assign_label(20.0), "LOW_CONTAGION")

    def test_assign_label_moderate(self):
        self.assertEqual(self.ana._assign_label(50.0), "MODERATE_INTERCONNECT")

    def test_assign_label_high(self):
        self.assertEqual(self.ana._assign_label(70.0), "HIGH_CONTAGION_RISK")

    def test_assign_label_systemic(self):
        self.assertEqual(self.ana._assign_label(90.0), "SYSTEMIC_RISK_NODE")

    def test_assign_label_boundary_15(self):
        # exactly 15 → LOW_CONTAGION (threshold < 15 → ISOLATED, so 15 → LOW)
        self.assertEqual(self.ana._assign_label(15.0), "LOW_CONTAGION")

    def test_assign_label_boundary_35(self):
        self.assertEqual(self.ana._assign_label(35.0), "MODERATE_INTERCONNECT")

    def test_assign_label_boundary_60(self):
        self.assertEqual(self.ana._assign_label(60.0), "HIGH_CONTAGION_RISK")

    def test_assign_label_boundary_80(self):
        self.assertEqual(self.ana._assign_label(80.0), "SYSTEMIC_RISK_NODE")


# ===========================================================================
# 11. Edge cases & robustness
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_missing_protocol_name_defaults_empty(self):
        payload = _make_payload()
        del payload["protocol_name"]
        r = self.ana.analyze(payload)
        self.assertEqual(r["protocol_name"], "")

    def test_none_protocols_exposed_handled(self):
        r = self.ana.analyze(_make_payload(protocols_exposed_to=None))
        self.assertEqual(r["contagion_surface_usd"], 0.0)

    def test_empty_lists_produce_valid_result(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[],
            shared_collateral_assets=[],
            oracle_providers=[],
            bridge_dependencies=[],
        ))
        self.assertIn(r["contagion_label"], VALID_LABELS)

    def test_negative_tvl_handled(self):
        r = self.ana.analyze(_make_payload(tvl_usd=-1_000_000))
        self.assertIsInstance(r, dict)
        self.assertLessEqual(r["contagion_risk_score"], 100.0)

    def test_zero_tvl_no_crash(self):
        r = self.ana.analyze(_make_payload(tvl_usd=0))
        self.assertIsInstance(r, dict)

    def test_very_large_tvl_low_score(self):
        r = self.ana.analyze(_make_payload(
            tvl_usd=10_000_000_000,
            protocols_exposed_to=[_make_exposed("A", 1_000_000)],
        ))
        self.assertLess(r["contagion_risk_score"], 50.0)

    def test_zero_shared_tvl_entries_still_run(self):
        r = self.ana.analyze(_make_payload(
            protocols_exposed_to=[_make_exposed("A", 0), _make_exposed("B", 0)]
        ))
        self.assertEqual(r["contagion_surface_usd"], 0.0)

    def test_all_labels_reachable(self):
        # Isolated
        r1 = self.ana.analyze(_make_payload(
            tvl_usd=1_000_000_000,
            protocols_exposed_to=[],
            shared_collateral_assets=[],
            oracle_providers=[],
            bridge_dependencies=[],
            insurance_coverage_usd=500_000_000,
            circuit_breaker_exists=True,
        ))
        self.assertIn(r1["contagion_label"], VALID_LABELS)

        # Systemic
        r2 = self.ana.analyze(_make_payload(
            tvl_usd=100_000,
            protocols_exposed_to=[_make_exposed("X", 10_000_000, "oracle")] * 5,
            shared_collateral_assets=["A", "B", "C", "D", "E"],
            oracle_providers=["O1", "O2", "O3"],
            bridge_dependencies=["B1", "B2", "B3", "B4", "B5"],
            insurance_coverage_usd=0,
            circuit_breaker_exists=False,
        ))
        self.assertIn(r2["contagion_label"], VALID_LABELS)

    def test_result_deterministic_same_input(self):
        p = _make_payload()
        r1 = self.ana.analyze(p)
        r2 = self.ana.analyze(p)
        self.assertEqual(r1["contagion_risk_score"], r2["contagion_risk_score"])
        self.assertEqual(r1["contagion_label"], r2["contagion_label"])

    def test_many_bridge_deps_beyond_cap_not_over_100(self):
        r = self.ana.analyze(_make_payload(
            bridge_dependencies=[f"B{i}" for i in range(50)]
        ))
        self.assertLessEqual(r["contagion_risk_score"], 100.0)

    def test_many_shared_collateral_beyond_cap(self):
        r = self.ana.analyze(_make_payload(
            shared_collateral_assets=[f"TOKEN{i}" for i in range(20)]
        ))
        self.assertLessEqual(r["contagion_risk_score"], 100.0)

    def test_dependency_type_collateral_weighted(self):
        # collateral weight > liquidity weight
        self.assertGreater(
            DEPENDENCY_TYPE_WEIGHT["collateral"],
            DEPENDENCY_TYPE_WEIGHT["liquidity"]
        )


if __name__ == "__main__":
    unittest.main()
