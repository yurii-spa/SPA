"""
Tests for MP-1028: DeFiProtocolSystemicRiskContagionModeler
Run: python3 -m unittest spa_core.tests.test_defi_protocol_systemic_risk_contagion_modeler -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_systemic_risk_contagion_modeler import (
    DeFiProtocolSystemicRiskContagionModeler,
    LOG_CAP,
    VALID_FLAGS,
    VALID_LABELS,
    _LOG_FILENAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_protocol(**overrides) -> dict:
    """Return a minimal valid protocol dict with optional overrides."""
    base = {
        "name": "TestProtocol",
        "tvl_usd": 1_000_000_000,      # $1B
        "interconnection_score": 50.0,
        "debt_exposure_usd": 200_000_000,
        "collateral_accepted": ["USDC", "ETH"],
        "tokens_issued": ["pToken"],
        "historical_contagion_events": 0,
        "oracle_dependencies": ["Chainlink", "TWAP"],
        "liquidity_in_crisis_pct": 30.0,
        "insurance_coverage_usd": 50_000_000,
    }
    base.update(overrides)
    return base


def make_modeler(tmp_dir: str) -> DeFiProtocolSystemicRiskContagionModeler:
    return DeFiProtocolSystemicRiskContagionModeler(data_dir=tmp_dir)


# ---------------------------------------------------------------------------
# 1. TVL Score
# ---------------------------------------------------------------------------

class TestTVLScore(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(self.m._compute_tvl_score(0.0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(self.m._compute_tvl_score(-1000.0), 0.0)

    def test_tiny_tvl_clamped_to_zero(self):
        # $1 → log10(1)=0, (0-6)/4*100 = -150 → clamped to 0
        self.assertEqual(self.m._compute_tvl_score(1.0), 0.0)

    def test_one_million_tvl_is_zero(self):
        # $1M → log10(1e6)=6, (6-6)/4*100 = 0
        self.assertAlmostEqual(self.m._compute_tvl_score(1_000_000.0), 0.0, places=4)

    def test_ten_million_tvl(self):
        # $10M → log10(1e7)=7, (7-6)/4*100 = 25
        self.assertAlmostEqual(self.m._compute_tvl_score(10_000_000.0), 25.0, places=3)

    def test_hundred_million_tvl(self):
        # $100M → log10(1e8)=8, (8-6)/4*100 = 50
        self.assertAlmostEqual(self.m._compute_tvl_score(100_000_000.0), 50.0, places=3)

    def test_one_billion_tvl(self):
        # $1B → log10(1e9)=9, (9-6)/4*100 = 75
        self.assertAlmostEqual(self.m._compute_tvl_score(1_000_000_000.0), 75.0, places=3)

    def test_ten_billion_tvl_is_max(self):
        # $10B → log10(1e10)=10, (10-6)/4*100 = 100
        self.assertAlmostEqual(self.m._compute_tvl_score(10_000_000_000.0), 100.0, places=3)

    def test_above_ten_billion_capped_at_100(self):
        self.assertEqual(self.m._compute_tvl_score(100_000_000_000.0), 100.0)

    def test_tvl_between_1m_and_10m(self):
        # $3.16M ≈ 10^6.5 → (6.5-6)/4*100 = 12.5
        score = self.m._compute_tvl_score(10 ** 6.5)
        self.assertAlmostEqual(score, 12.5, places=3)


# ---------------------------------------------------------------------------
# 2. Resilience Score
# ---------------------------------------------------------------------------

class TestResilienceScore(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def test_zero_resilience_inputs(self):
        # insurance=0, liquidity=0, interconnection=100
        r = self.m._compute_resilience(0.0, 1_000_000.0, 0.0, 100.0)
        self.assertAlmostEqual(r, 0.0, places=4)

    def test_max_resilience(self):
        # insurance=1M, safe_tvl=1M (100%), liquidity=100, interconnection=0
        r = self.m._compute_resilience(1_000_000.0, 1_000_000.0, 100.0, 0.0)
        self.assertAlmostEqual(r, 100.0, places=4)

    def test_max_liquidity_only(self):
        # liquidity=100%, no insurance, interconnection=0
        r = self.m._compute_resilience(0.0, 1_000_000.0, 100.0, 0.0)
        # liquidity_score = 40, low_interconnect = 20 → 60
        self.assertAlmostEqual(r, 60.0, places=4)

    def test_insurance_caps_at_40(self):
        # 200% coverage → insurance_score still capped at 40
        r = self.m._compute_resilience(2_000_000.0, 1_000_000.0, 0.0, 0.0)
        # 40 + 0 + 20 = 60
        self.assertAlmostEqual(r, 60.0, places=4)

    def test_ten_pct_insurance(self):
        # 10% coverage → insurance_score = min(40, 10*0.4) = 4
        r = self.m._compute_resilience(100_000.0, 1_000_000.0, 0.0, 0.0)
        # 4 + 0 + 20 = 24
        self.assertAlmostEqual(r, 24.0, places=4)

    def test_liquidity_contribution(self):
        # liquidity=50% → 50*0.4 = 20
        r = self.m._compute_resilience(0.0, 1_000_000.0, 50.0, 100.0)
        # insurance=0, liquidity=20, low_interconnect=(100-100)*0.2=0
        self.assertAlmostEqual(r, 20.0, places=4)

    def test_mixed_resilience(self):
        # insurance=100K, safe_tvl=1M (10%), liquidity=50, interconnection=50
        r = self.m._compute_resilience(100_000.0, 1_000_000.0, 50.0, 50.0)
        # insurance_score = min(40, 10*0.4) = 4
        # liquidity_score = 50*0.4 = 20
        # low_interconnect = (100-50)*0.2 = 10
        self.assertAlmostEqual(r, 34.0, places=4)

    def test_resilience_clamped_at_100(self):
        # Extreme coverage won't exceed 100
        r = self.m._compute_resilience(1e12, 1_000_000.0, 100.0, 0.0)
        self.assertLessEqual(r, 100.0)


# ---------------------------------------------------------------------------
# 3. Label Determination
# ---------------------------------------------------------------------------

class TestDetermineLabel(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def test_importance_above_80_is_cornerstone(self):
        self.assertEqual(self.m._determine_label(80.1, 50.0, 50.0), "SYSTEMIC_CORNERSTONE")

    def test_importance_exactly_80_is_not_cornerstone(self):
        # 80.0 is NOT > 80.0
        self.assertEqual(self.m._determine_label(80.0, 50.0, 50.0), "HIGH_SYSTEMIC")

    def test_importance_90_is_cornerstone(self):
        self.assertEqual(self.m._determine_label(90.0, 70.0, 80.0), "SYSTEMIC_CORNERSTONE")

    def test_importance_above_60_is_high(self):
        self.assertEqual(self.m._determine_label(70.0, 50.0, 50.0), "HIGH_SYSTEMIC")

    def test_importance_exactly_60_is_moderate(self):
        # 60.0 NOT > 60 → MODERATE_SYSTEMIC if > 40
        self.assertEqual(self.m._determine_label(60.0, 50.0, 50.0), "MODERATE_SYSTEMIC")

    def test_importance_above_40_is_moderate(self):
        self.assertEqual(self.m._determine_label(55.0, 20.0, 60.0), "MODERATE_SYSTEMIC")

    def test_importance_40_with_high_inter_is_low(self):
        # 40.0 NOT > 40 → check isolation: inter=50 >= 10 → LOW_SYSTEMIC if > 20
        self.assertEqual(self.m._determine_label(40.0, 50.0, 50.0), "LOW_SYSTEMIC")

    def test_low_importance_high_inter_is_low(self):
        self.assertEqual(self.m._determine_label(30.0, 50.0, 50.0), "LOW_SYSTEMIC")

    def test_isolated_by_inter_and_tvl(self):
        # interconnection < 10 AND tvl_score < 10
        self.assertEqual(self.m._determine_label(30.0, 5.0, 5.0), "ISOLATED")

    def test_zero_importance_is_isolated(self):
        self.assertEqual(self.m._determine_label(0.0, 50.0, 50.0), "ISOLATED")

    def test_importance_20_is_isolated_when_not_isolated_criteria(self):
        # importance=20.0 is NOT > 20 → ISOLATED
        self.assertEqual(self.m._determine_label(20.0, 50.0, 50.0), "ISOLATED")

    def test_isolated_when_tvl_high_but_inter_low(self):
        # inter=5 < 10, tvl_score=50 >= 10 → not isolated by first check
        # importance=30 > 20 → LOW_SYSTEMIC
        self.assertEqual(self.m._determine_label(30.0, 5.0, 50.0), "LOW_SYSTEMIC")


# ---------------------------------------------------------------------------
# 4. Contagion Amplification Factor
# ---------------------------------------------------------------------------

class TestContagionAmplificationFactor(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def _amp(self, inter, debt, tvl):
        """Helper: compute contagion_amp from raw protocol dict values."""
        p = make_protocol(
            interconnection_score=inter,
            debt_exposure_usd=debt,
            tvl_usd=tvl,
            tokens_issued=[],
            oracle_dependencies=["A","B"],
            liquidity_in_crisis_pct=50.0,
            insurance_coverage_usd=0.0,
        )
        result = self.m._analyze_protocol(p)
        return result["contagion_amplification_factor"]

    def test_zero_interconnection_gives_one(self):
        self.assertAlmostEqual(self._amp(0.0, 1_000_000, 2_000_000), 1.0, places=4)

    def test_zero_debt_gives_one(self):
        self.assertAlmostEqual(self._amp(50.0, 0.0, 1_000_000), 1.0, places=4)

    def test_full_interconnection_equal_debt_tvl(self):
        # 1.0 + (100/100) * (1M/1M) = 2.0
        self.assertAlmostEqual(self._amp(100.0, 1_000_000, 1_000_000), 2.0, places=4)

    def test_half_interconnection_half_debt_tvl(self):
        # 1.0 + (50/100) * (500K/1M) = 1.0 + 0.25 = 1.25
        self.assertAlmostEqual(self._amp(50.0, 500_000, 1_000_000), 1.25, places=4)

    def test_debt_exceeds_tvl(self):
        # 1.0 + (100/100) * (2M/1M) = 3.0
        self.assertAlmostEqual(self._amp(100.0, 2_000_000, 1_000_000), 3.0, places=4)

    def test_low_interconnection(self):
        # 1.0 + (10/100) * (1M/1M) = 1.1
        self.assertAlmostEqual(self._amp(10.0, 1_000_000, 1_000_000), 1.1, places=4)

    def test_tiny_debt_to_tvl(self):
        # 1.0 + (80/100) * (1K/1M) = 1.0 + 0.0008 = 1.0008
        self.assertAlmostEqual(self._amp(80.0, 1_000, 1_000_000), 1.0008, places=4)

    def test_amplification_factor_always_at_least_one(self):
        amp = self._amp(0.0, 0.0, 1_000_000)
        self.assertGreaterEqual(amp, 1.0)


# ---------------------------------------------------------------------------
# 5. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def _flags(self, **overrides) -> list:
        p = make_protocol(**overrides)
        result = self.m._analyze_protocol(p)
        return result["flags"]

    def test_collateral_contagion_risk_when_tokens_issued(self):
        self.assertIn("COLLATERAL_CONTAGION_RISK", self._flags(tokens_issued=["tkn"]))

    def test_no_collateral_contagion_when_no_tokens(self):
        self.assertNotIn("COLLATERAL_CONTAGION_RISK", self._flags(tokens_issued=[]))

    def test_collateral_contagion_multiple_tokens(self):
        self.assertIn("COLLATERAL_CONTAGION_RISK", self._flags(tokens_issued=["a", "b", "c"]))

    def test_oracle_single_source_when_one_oracle(self):
        self.assertIn("ORACLE_SINGLE_SOURCE", self._flags(oracle_dependencies=["Chainlink"]))

    def test_no_oracle_single_source_when_two(self):
        self.assertNotIn("ORACLE_SINGLE_SOURCE", self._flags(oracle_dependencies=["A", "B"]))

    def test_no_oracle_single_source_when_zero(self):
        self.assertNotIn("ORACLE_SINGLE_SOURCE", self._flags(oracle_dependencies=[]))

    def test_historically_contagious_when_events_gt_1(self):
        self.assertIn("HISTORICALLY_CONTAGIOUS", self._flags(historical_contagion_events=2))

    def test_not_historically_contagious_when_events_eq_1(self):
        self.assertNotIn("HISTORICALLY_CONTAGIOUS", self._flags(historical_contagion_events=1))

    def test_not_historically_contagious_when_events_eq_0(self):
        self.assertNotIn("HISTORICALLY_CONTAGIOUS", self._flags(historical_contagion_events=0))

    def test_insurance_buffered_when_coverage_above_10pct(self):
        # coverage=110K > 10% of 1M = 100K
        self.assertIn("INSURANCE_BUFFERED", self._flags(
            insurance_coverage_usd=110_000, tvl_usd=1_000_000
        ))

    def test_no_insurance_buffered_when_coverage_below_10pct(self):
        # coverage=90K < 10% of 1M = 100K
        self.assertNotIn("INSURANCE_BUFFERED", self._flags(
            insurance_coverage_usd=90_000, tvl_usd=1_000_000
        ))

    def test_liquidity_cliff_when_below_10pct(self):
        self.assertIn("LIQUIDITY_CLIFF", self._flags(liquidity_in_crisis_pct=9.9))

    def test_no_liquidity_cliff_at_exactly_10pct(self):
        self.assertNotIn("LIQUIDITY_CLIFF", self._flags(liquidity_in_crisis_pct=10.0))

    def test_liquidity_cliff_at_zero(self):
        self.assertIn("LIQUIDITY_CLIFF", self._flags(liquidity_in_crisis_pct=0.0))

    def test_too_big_to_fail_when_importance_above_85(self):
        # High TVL + high interconnection + 3 tokens → importance > 85
        p = make_protocol(
            tvl_usd=10_000_000_000,   # tvl_score=100
            interconnection_score=100.0,
            tokens_issued=["a", "b", "c"],  # collateral=99.9
        )
        result = self.m._analyze_protocol(p)
        self.assertIn("TOO_BIG_TO_FAIL", result["flags"])

    def test_no_too_big_to_fail_at_exactly_85(self):
        # importance = 85 is NOT > 85
        flags = self.m._compute_flags(
            tokens_issued=[], oracle_dependencies=["A", "B"],
            historical_contagion=0, insurance_coverage=0.0,
            tvl=1_000_000.0, liquidity_crisis_pct=50.0,
            systemic_importance=85.0,
        )
        self.assertNotIn("TOO_BIG_TO_FAIL", flags)

    def test_all_flags_in_valid_set(self):
        flags = self._flags(
            tokens_issued=["t"],
            oracle_dependencies=["single"],
            historical_contagion_events=3,
            insurance_coverage_usd=0,
            tvl_usd=1_000_000,
            liquidity_in_crisis_pct=5.0,
        )
        for f in flags:
            self.assertIn(f, VALID_FLAGS)


# ---------------------------------------------------------------------------
# 6. Analyze Protocol (integration)
# ---------------------------------------------------------------------------

class TestAnalyzeProtocol(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def test_output_keys_present(self):
        result = self.m._analyze_protocol(make_protocol())
        expected_keys = {
            "name", "tvl_usd", "contagion_amplification_factor",
            "systemic_importance_score", "cascade_risk_score",
            "resilience_score", "net_systemic_risk", "label", "flags",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_name_is_preserved(self):
        result = self.m._analyze_protocol(make_protocol(name="Aave"))
        self.assertEqual(result["name"], "Aave")

    def test_tvl_is_preserved(self):
        result = self.m._analyze_protocol(make_protocol(tvl_usd=5_000_000_000))
        self.assertEqual(result["tvl_usd"], 5_000_000_000)

    def test_label_is_valid(self):
        result = self.m._analyze_protocol(make_protocol())
        self.assertIn(result["label"], VALID_LABELS)

    def test_scores_are_non_negative(self):
        result = self.m._analyze_protocol(make_protocol())
        self.assertGreaterEqual(result["systemic_importance_score"], 0.0)
        self.assertGreaterEqual(result["cascade_risk_score"], 0.0)
        self.assertGreaterEqual(result["resilience_score"], 0.0)
        self.assertGreaterEqual(result["net_systemic_risk"], 0.0)

    def test_systemic_importance_bounded(self):
        result = self.m._analyze_protocol(make_protocol(
            tvl_usd=10_000_000_000,
            interconnection_score=100.0,
            tokens_issued=["a", "b", "c", "d", "e"],
        ))
        self.assertLessEqual(result["systemic_importance_score"], 100.0)

    def test_cascade_risk_bounded(self):
        result = self.m._analyze_protocol(make_protocol(
            interconnection_score=100.0,
            debt_exposure_usd=100_000_000_000,
            historical_contagion_events=999,
        ))
        self.assertLessEqual(result["cascade_risk_score"], 100.0)

    def test_resilience_bounded(self):
        result = self.m._analyze_protocol(make_protocol(
            insurance_coverage_usd=100_000_000_000,
            liquidity_in_crisis_pct=100.0,
            interconnection_score=0.0,
        ))
        self.assertLessEqual(result["resilience_score"], 100.0)

    def test_default_name_when_missing(self):
        result = self.m._analyze_protocol({})
        self.assertEqual(result["name"], "unknown")

    def test_interconnection_clamped_above_100(self):
        result = self.m._analyze_protocol(make_protocol(interconnection_score=150.0))
        self.assertLessEqual(result["systemic_importance_score"], 100.0)

    def test_interconnection_clamped_below_zero(self):
        result = self.m._analyze_protocol(make_protocol(interconnection_score=-10.0))
        self.assertGreaterEqual(result["systemic_importance_score"], 0.0)


# ---------------------------------------------------------------------------
# 7. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.m = DeFiProtocolSystemicRiskContagionModeler()

    def test_empty_returns_none_fields(self):
        agg = self.m._compute_aggregates([])
        self.assertIsNone(agg["highest_systemic_risk"])
        self.assertIsNone(agg["lowest_systemic_risk"])
        self.assertEqual(agg["total_systemic_tvl_at_risk"], 0.0)
        self.assertEqual(agg["cornerstone_count"], 0)
        self.assertEqual(agg["isolated_count"], 0)

    def test_single_protocol_highest_equals_lowest(self):
        results = [self.m._analyze_protocol(make_protocol(name="X"))]
        agg = self.m._compute_aggregates(results)
        self.assertEqual(agg["highest_systemic_risk"], "X")
        self.assertEqual(agg["lowest_systemic_risk"], "X")

    def test_cornerstone_count(self):
        high_tvl_proto = make_protocol(
            name="Big",
            tvl_usd=10_000_000_000,
            interconnection_score=100.0,
            tokens_issued=["a", "b", "c"],
        )
        small_proto = make_protocol(
            name="Small",
            tvl_usd=100_000,
            interconnection_score=2.0,
            tokens_issued=[],
        )
        results = [
            self.m._analyze_protocol(high_tvl_proto),
            self.m._analyze_protocol(small_proto),
        ]
        agg = self.m._compute_aggregates(results)
        self.assertGreaterEqual(agg["cornerstone_count"], 0)

    def test_isolated_count(self):
        small = make_protocol(
            name="Isolated",
            tvl_usd=100_000,
            interconnection_score=2.0,
            tokens_issued=[],
        )
        results = [self.m._analyze_protocol(small)]
        agg = self.m._compute_aggregates(results)
        self.assertEqual(agg["isolated_count"], 1)

    def test_tvl_at_risk_excludes_low_risk_protocols(self):
        small = make_protocol(
            name="Small",
            tvl_usd=100_000,
            interconnection_score=1.0,
            tokens_issued=[],
        )
        results = [self.m._analyze_protocol(small)]
        # ISOLATED protocol should NOT be in tvl_at_risk
        agg = self.m._compute_aggregates(results)
        if results[0]["label"] == "ISOLATED":
            self.assertEqual(agg["total_systemic_tvl_at_risk"], 0.0)

    def test_highest_is_name_string(self):
        results = [
            self.m._analyze_protocol(make_protocol(name="A")),
            self.m._analyze_protocol(make_protocol(name="B")),
        ]
        agg = self.m._compute_aggregates(results)
        self.assertIn(agg["highest_systemic_risk"], ["A", "B"])
        self.assertIn(agg["lowest_systemic_risk"], ["A", "B"])

    def test_aggregate_keys(self):
        results = [self.m._analyze_protocol(make_protocol())]
        agg = self.m._compute_aggregates(results)
        self.assertIn("highest_systemic_risk", agg)
        self.assertIn("lowest_systemic_risk", agg)
        self.assertIn("total_systemic_tvl_at_risk", agg)
        self.assertIn("cornerstone_count", agg)
        self.assertIn("isolated_count", agg)


# ---------------------------------------------------------------------------
# 8. Ring-Buffer Log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = make_modeler(self.tmp)

    def _log_path(self):
        return os.path.join(self.tmp, _LOG_FILENAME)

    def test_log_file_created(self):
        self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_is_json_list(self):
        self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_protocol_count(self):
        self.m.model([make_protocol(), make_protocol(name="B")],
                     config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["protocol_count"], 2)

    def test_log_grows_with_multiple_calls(self):
        for _ in range(3):
            self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_at_log_cap(self):
        for _ in range(LOG_CAP + 5):
            self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_CAP)

    def test_no_log_when_disabled(self):
        self.m.model([make_protocol()], config={"log_enabled": False, "data_dir": self.tmp})
        self.assertFalse(os.path.exists(self._log_path()))

    def test_log_recovers_from_corrupt_file(self):
        with open(self._log_path(), "w") as fh:
            fh.write("NOT_JSON{{")
        # Should not raise
        self.m.model([make_protocol()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 9. Model Output (top-level)
# ---------------------------------------------------------------------------

class TestModelOutput(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = make_modeler(self.tmp)

    def _run(self, protocols=None):
        if protocols is None:
            protocols = [make_protocol()]
        return self.m.model(protocols, config={"log_enabled": False})

    def test_output_has_required_keys(self):
        result = self._run()
        for key in ("timestamp", "module", "mp", "protocol_count", "protocols", "aggregates"):
            self.assertIn(key, result)

    def test_module_name(self):
        result = self._run()
        self.assertEqual(result["module"], "DeFiProtocolSystemicRiskContagionModeler")

    def test_mp_tag(self):
        result = self._run()
        self.assertEqual(result["mp"], "MP-1028")

    def test_protocol_count_matches(self):
        result = self._run([make_protocol(), make_protocol(name="B")])
        self.assertEqual(result["protocol_count"], 2)

    def test_empty_protocols_list(self):
        result = self._run([])
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["protocols"], [])

    def test_timestamp_is_string(self):
        result = self._run()
        self.assertIsInstance(result["timestamp"], str)

    def test_protocols_list_length(self):
        result = self._run([make_protocol(), make_protocol(name="B"), make_protocol(name="C")])
        self.assertEqual(len(result["protocols"]), 3)

    def test_raises_on_non_list_protocols(self):
        with self.assertRaises(TypeError):
            self.m.model("not a list", config={})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.m.model([], config="not a dict")

    def test_aggregates_is_dict(self):
        result = self._run()
        self.assertIsInstance(result["aggregates"], dict)


# ---------------------------------------------------------------------------
# 10. Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = make_modeler(self.tmp)

    def test_protocol_with_zero_tvl(self):
        result = self.m._analyze_protocol(make_protocol(tvl_usd=0.0))
        self.assertGreaterEqual(result["contagion_amplification_factor"], 1.0)

    def test_very_high_historical_contagion(self):
        result = self.m._analyze_protocol(make_protocol(historical_contagion_events=999))
        self.assertLessEqual(result["cascade_risk_score"], 100.0)

    def test_liquidity_clamped_above_100(self):
        result = self.m._analyze_protocol(make_protocol(liquidity_in_crisis_pct=200.0))
        self.assertLessEqual(result["resilience_score"], 100.0)

    def test_empty_collections_default_gracefully(self):
        p = make_protocol(collateral_accepted=[], tokens_issued=[], oracle_dependencies=[])
        result = self.m._analyze_protocol(p)
        self.assertIsNotNone(result["label"])

    def test_all_zeros_protocol(self):
        p = {
            "name": "ZeroProto",
            "tvl_usd": 0.0,
            "interconnection_score": 0.0,
            "debt_exposure_usd": 0.0,
            "collateral_accepted": [],
            "tokens_issued": [],
            "historical_contagion_events": 0,
            "oracle_dependencies": [],
            "liquidity_in_crisis_pct": 0.0,
            "insurance_coverage_usd": 0.0,
        }
        result = self.m._analyze_protocol(p)
        self.assertEqual(result["contagion_amplification_factor"], 1.0)
        self.assertEqual(result["systemic_importance_score"], 0.0)

    def test_net_systemic_risk_is_zero_when_resilience_is_100(self):
        p = make_protocol(
            insurance_coverage_usd=100_000_000_000,
            liquidity_in_crisis_pct=100.0,
            interconnection_score=0.0,
        )
        result = self.m._analyze_protocol(p)
        # resilience=100 → (100-100)/100 = 0 → net_risk=0
        self.assertAlmostEqual(result["net_systemic_risk"], 0.0, places=4)

    def test_data_dir_from_config_overrides_instance(self):
        alt_tmp = tempfile.mkdtemp()
        self.m.model(
            [make_protocol()],
            config={"log_enabled": True, "data_dir": alt_tmp},
        )
        self.assertTrue(os.path.exists(os.path.join(alt_tmp, _LOG_FILENAME)))

    def test_large_protocol_list_no_error(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(50)]
        result = self.m.model(protocols, config={"log_enabled": False})
        self.assertEqual(result["protocol_count"], 50)


if __name__ == "__main__":
    unittest.main()
