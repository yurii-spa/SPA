"""
MP-1023 Tests: ProtocolDeFiCrossChainYieldNormalizer
≥80 tests, unittest only, stdlib only.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_cross_chain_yield_normalizer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_cross_chain_yield_normalizer import (
    ProtocolDeFiCrossChainYieldNormalizer,
    _atomic_write,
    _load_ring_buffer,
    _CHAIN_DEFAULT_RISK,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_opp(
    name="Opportunity",
    protocol="Aave V3",
    chain="ethereum",
    nominal_apy_pct=5.0,
    tvl_usd=100_000_000,
    bridge_cost_usd_one_way=0.0,
    bridge_cost_usd_return=0.0,
    bridge_time_hours=0.0,
    chain_risk_score=10,
    gas_cost_per_interaction_usd=30.0,
    interactions_per_month=4,
    position_size_usd=50_000,
    min_viable_position_usd=10_000,
):
    return {
        "name": name,
        "protocol": protocol,
        "chain": chain,
        "nominal_apy_pct": nominal_apy_pct,
        "tvl_usd": tvl_usd,
        "bridge_cost_usd_one_way": bridge_cost_usd_one_way,
        "bridge_cost_usd_return": bridge_cost_usd_return,
        "bridge_time_hours": bridge_time_hours,
        "chain_risk_score": chain_risk_score,
        "gas_cost_per_interaction_usd": gas_cost_per_interaction_usd,
        "interactions_per_month": interactions_per_month,
        "position_size_usd": position_size_usd,
        "min_viable_position_usd": min_viable_position_usd,
    }


def _eth_mainnet_opp(name="Mainnet"):
    return _make_opp(
        name=name,
        chain="ethereum",
        nominal_apy_pct=3.5,
        chain_risk_score=10,
        gas_cost_per_interaction_usd=30.0,
        interactions_per_month=4,
        bridge_cost_usd_one_way=0,
        bridge_cost_usd_return=0,
    )


def _l2_opp(name="L2Opp", chain="arbitrum"):
    return _make_opp(
        name=name,
        chain=chain,
        nominal_apy_pct=4.6,
        chain_risk_score=20,
        gas_cost_per_interaction_usd=0.5,
        interactions_per_month=4,
        bridge_cost_usd_one_way=5.0,
        bridge_cost_usd_return=5.0,
        bridge_time_hours=7 * 24,
    )


def _high_apy_superior(name="Superior"):
    return _make_opp(
        name=name,
        chain="arbitrum",
        nominal_apy_pct=25.0,
        chain_risk_score=20,
        gas_cost_per_interaction_usd=0.1,
        interactions_per_month=1,
        bridge_cost_usd_one_way=2.0,
        bridge_cost_usd_return=2.0,
        bridge_time_hours=0.5,
        position_size_usd=100_000,
        min_viable_position_usd=5_000,
    )


def _tiny_position(name="TinyPos"):
    return _make_opp(
        name=name,
        position_size_usd=100,
        min_viable_position_usd=10_000,
        nominal_apy_pct=5.0,
        bridge_cost_usd_one_way=50,
        bridge_cost_usd_return=50,
    )


class TestAtomicWriteNorm(unittest.TestCase):
    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [{"x": 1}])
            self.assertTrue(os.path.exists(path))

    def test_write_correct_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, {"chain": "arbitrum"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, {"chain": "arbitrum"})

    def test_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.json")
            _atomic_write(path, [1])
            _atomic_write(path, [2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [2, 3])

    def test_write_creates_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a", "b", "c.json")
            _atomic_write(path, {"ok": True})
            self.assertTrue(os.path.exists(path))


class TestLoadRingBufferNorm(unittest.TestCase):
    def test_empty_on_missing(self):
        with tempfile.TemporaryDirectory() as d:
            result = _load_ring_buffer(os.path.join(d, "nope.json"), 100)
            self.assertEqual(result, [])

    def test_respects_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "buf.json")
            _atomic_write(path, list(range(200)))
            result = _load_ring_buffer(path, 30)
            self.assertEqual(len(result), 30)

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("!!!not json!!!")
            result = _load_ring_buffer(path, 10)
            self.assertEqual(result, [])


class TestChainDefaultRisk(unittest.TestCase):
    def test_ethereum_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["ethereum"], 10)

    def test_arbitrum_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["arbitrum"], 20)

    def test_optimism_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["optimism"], 20)

    def test_base_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["base"], 20)

    def test_polygon_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["polygon"], 40)

    def test_bsc_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["bsc"], 60)

    def test_avalanche_risk(self):
        self.assertEqual(_CHAIN_DEFAULT_RISK["avalanche"], 40)


class TestTotalBridgeCost(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_zero_bridge(self):
        opp = _make_opp(bridge_cost_usd_one_way=0, bridge_cost_usd_return=0)
        self.assertEqual(self.n._total_bridge_cost(opp), 0.0)

    def test_basic_bridge(self):
        opp = _make_opp(bridge_cost_usd_one_way=10, bridge_cost_usd_return=8)
        self.assertAlmostEqual(self.n._total_bridge_cost(opp), 18.0)

    def test_only_one_way(self):
        opp = _make_opp(bridge_cost_usd_one_way=25, bridge_cost_usd_return=0)
        self.assertAlmostEqual(self.n._total_bridge_cost(opp), 25.0)

    def test_symmetric_bridge(self):
        opp = _make_opp(bridge_cost_usd_one_way=50, bridge_cost_usd_return=50)
        self.assertAlmostEqual(self.n._total_bridge_cost(opp), 100.0)


class TestBridgeCostAnnualized(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_zero_bridge_zero_pct(self):
        opp = _make_opp(bridge_cost_usd_one_way=0, bridge_cost_usd_return=0,
                        position_size_usd=50_000)
        self.assertAlmostEqual(self.n._bridge_cost_annualized_pct(opp, 0.0), 0.0)

    def test_basic_annualized(self):
        opp = _make_opp(position_size_usd=10_000)
        # bridge 100, position 10000 -> 100/10000 * 100 = 1%
        pct = self.n._bridge_cost_annualized_pct(opp, 100.0)
        self.assertAlmostEqual(pct, 1.0)

    def test_large_bridge_relative(self):
        opp = _make_opp(position_size_usd=1_000)
        pct = self.n._bridge_cost_annualized_pct(opp, 50.0)
        self.assertAlmostEqual(pct, 5.0)

    def test_zero_position_no_divide_by_zero(self):
        opp = _make_opp(position_size_usd=0)
        pct = self.n._bridge_cost_annualized_pct(opp, 100.0)
        self.assertEqual(pct, 0.0)


class TestMonthlyGasCost(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_basic(self):
        opp = _make_opp(gas_cost_per_interaction_usd=10, interactions_per_month=4)
        self.assertAlmostEqual(self.n._monthly_gas_cost(opp), 40.0)

    def test_zero_gas(self):
        opp = _make_opp(gas_cost_per_interaction_usd=0, interactions_per_month=100)
        self.assertEqual(self.n._monthly_gas_cost(opp), 0.0)

    def test_one_interaction(self):
        opp = _make_opp(gas_cost_per_interaction_usd=50, interactions_per_month=1)
        self.assertAlmostEqual(self.n._monthly_gas_cost(opp), 50.0)

    def test_l2_low_gas(self):
        opp = _make_opp(gas_cost_per_interaction_usd=0.25, interactions_per_month=10)
        self.assertAlmostEqual(self.n._monthly_gas_cost(opp), 2.5)


class TestTotalFriction(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_zero_friction(self):
        result = self.n._total_friction_pct(0.0, 0.0, 50_000)
        self.assertAlmostEqual(result, 0.0)

    def test_gas_only(self):
        # gas_annual = 10*12/50000*100 = 0.24%
        result = self.n._total_friction_pct(0.0, 10.0, 50_000)
        self.assertAlmostEqual(result, 0.24)

    def test_bridge_only(self):
        result = self.n._total_friction_pct(1.0, 0.0, 50_000)
        self.assertAlmostEqual(result, 1.0)

    def test_zero_position_no_error(self):
        result = self.n._total_friction_pct(0.0, 10.0, 0)
        self.assertEqual(result, 0.0)


class TestChainRiskAdjustedApy(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_ethereum_adjustment(self):
        opp = _make_opp(nominal_apy_pct=10.0, chain="ethereum", chain_risk_score=10)
        adj = self.n._chain_risk_adjusted_apy(opp)
        self.assertAlmostEqual(adj, 9.0)  # 10 * 0.9

    def test_bsc_adjustment(self):
        opp = _make_opp(nominal_apy_pct=10.0, chain="bsc", chain_risk_score=60)
        adj = self.n._chain_risk_adjusted_apy(opp)
        self.assertAlmostEqual(adj, 4.0)  # 10 * 0.4

    def test_zero_risk(self):
        opp = _make_opp(nominal_apy_pct=5.0, chain="ethereum", chain_risk_score=0)
        adj = self.n._chain_risk_adjusted_apy(opp)
        self.assertAlmostEqual(adj, 5.0)

    def test_uses_default_chain_risk(self):
        opp = _make_opp(nominal_apy_pct=10.0, chain="arbitrum")
        del opp["chain_risk_score"]
        adj = self.n._chain_risk_adjusted_apy(opp)
        # default arbitrum risk = 20 → 10 * 0.8 = 8.0
        self.assertAlmostEqual(adj, 8.0)

    def test_full_risk_gives_zero(self):
        opp = _make_opp(nominal_apy_pct=10.0, chain_risk_score=100)
        adj = self.n._chain_risk_adjusted_apy(opp)
        self.assertAlmostEqual(adj, 0.0)


class TestNetNormalizedApy(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_positive_net(self):
        self.assertAlmostEqual(self.n._net_normalized_apy(5.0, 1.0), 4.0)

    def test_negative_net(self):
        self.assertAlmostEqual(self.n._net_normalized_apy(1.0, 3.0), -2.0)

    def test_zero_net(self):
        self.assertAlmostEqual(self.n._net_normalized_apy(3.0, 3.0), 0.0)


class TestPositionViabilityScore(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_fully_viable(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000,
                        bridge_time_hours=1)
        score = self.n._position_viability_score(opp, net_apy=5.0, monthly_gas=10)
        self.assertAlmostEqual(score, 100.0)

    def test_negative_apy_loses_40(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000,
                        bridge_time_hours=1)
        score = self.n._position_viability_score(opp, net_apy=-1.0, monthly_gas=10)
        self.assertAlmostEqual(score, 60.0)

    def test_too_small_position_loses_40(self):
        opp = _make_opp(position_size_usd=100, min_viable_position_usd=10_000,
                        bridge_time_hours=1)
        score = self.n._position_viability_score(opp, net_apy=5.0, monthly_gas=10)
        self.assertAlmostEqual(score, 60.0)

    def test_slow_bridge_loses_20(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000,
                        bridge_time_hours=48)  # >24h
        score = self.n._position_viability_score(opp, net_apy=5.0, monthly_gas=10)
        self.assertAlmostEqual(score, 80.0)

    def test_all_bad_gives_zero(self):
        opp = _make_opp(position_size_usd=100, min_viable_position_usd=10_000,
                        bridge_time_hours=100)
        score = self.n._position_viability_score(opp, net_apy=-1.0, monthly_gas=10)
        self.assertAlmostEqual(score, 0.0)

    def test_score_capped_at_100(self):
        opp = _make_opp(position_size_usd=1_000_000, min_viable_position_usd=0,
                        bridge_time_hours=0)
        score = self.n._position_viability_score(opp, net_apy=99.0, monthly_gas=0)
        self.assertLessEqual(score, 100.0)


class TestNormalizedLabel(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_unviable_negative_apy(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        label = self.n._normalized_label(opp, -1.0, 1.0, 80.0, 5.0)
        self.assertEqual(label, "UNVIABLE")

    def test_unviable_position_too_small(self):
        opp = _make_opp(position_size_usd=100, min_viable_position_usd=10_000)
        label = self.n._normalized_label(opp, 5.0, 1.0, 80.0, 5.0)
        self.assertEqual(label, "UNVIABLE")

    def test_friction_dominated(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        # friction = 4.0, nominal_apy = 5.0, 4.0 > 5.0 * 0.5 = 2.5 → FRICTION_DOMINATED
        label = self.n._normalized_label(opp, 1.0, 4.0, 80.0, 5.0)
        self.assertEqual(label, "FRICTION_DOMINATED")

    def test_superior_opportunity(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        label = self.n._normalized_label(opp, 15.0, 0.5, 100.0, 20.0)
        self.assertEqual(label, "SUPERIOR_OPPORTUNITY")

    def test_attractive(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        label = self.n._normalized_label(opp, 7.0, 0.5, 100.0, 10.0)
        self.assertEqual(label, "ATTRACTIVE")

    def test_marginal(self):
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        label = self.n._normalized_label(opp, 3.0, 0.5, 100.0, 5.0)
        self.assertEqual(label, "MARGINAL")

    def test_labels_are_valid(self):
        valid = {"SUPERIOR_OPPORTUNITY", "ATTRACTIVE", "MARGINAL",
                 "FRICTION_DOMINATED", "UNVIABLE"}
        opp = _make_opp(position_size_usd=50_000, min_viable_position_usd=10_000)
        for net, friction, viability, nominal in [
            (15.0, 0.5, 100.0, 20.0),
            (7.0, 0.5, 100.0, 10.0),
            (3.0, 0.5, 100.0, 5.0),
            (1.0, 4.0, 80.0, 5.0),
            (-1.0, 1.0, 80.0, 5.0),
        ]:
            label = self.n._normalized_label(opp, net, friction, viability, nominal)
            self.assertIn(label, valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.n = ProtocolDeFiCrossChainYieldNormalizer()

    def test_l2_native_advantage(self):
        opp = _make_opp(
            chain="arbitrum",
            chain_risk_score=20,
            gas_cost_per_interaction_usd=0.01,
            interactions_per_month=1,
            bridge_cost_usd_one_way=0.5,
            bridge_cost_usd_return=0.5,
            position_size_usd=100_000,
        )
        flags = self.n._compute_flags(opp, 0.01, 1.0, 5.0)
        self.assertIn("L2_NATIVE_ADVANTAGE", flags)

    def test_bridge_heavy_flag(self):
        opp = _make_opp(position_size_usd=50_000)
        flags = self.n._compute_flags(opp, 10.0, 150.0, 5.0)
        self.assertIn("BRIDGE_HEAVY", flags)

    def test_no_bridge_heavy_below_100(self):
        opp = _make_opp(position_size_usd=50_000)
        flags = self.n._compute_flags(opp, 10.0, 50.0, 5.0)
        self.assertNotIn("BRIDGE_HEAVY", flags)

    def test_gas_intensive_flag(self):
        opp = _make_opp(gas_cost_per_interaction_usd=100, interactions_per_month=4)
        flags = self.n._compute_flags(opp, 400.0, 0.0, 5.0)
        self.assertIn("GAS_INTENSIVE", flags)

    def test_position_too_small_flag(self):
        opp = _make_opp(position_size_usd=100, min_viable_position_usd=10_000)
        flags = self.n._compute_flags(opp, 10.0, 50.0, 5.0)
        self.assertIn("POSITION_TOO_SMALL", flags)

    def test_high_chain_risk_flag(self):
        opp = _make_opp(chain="bsc", chain_risk_score=60)
        flags = self.n._compute_flags(opp, 10.0, 0.0, 5.0)
        self.assertIn("HIGH_CHAIN_RISK", flags)

    def test_no_high_chain_risk_below_50(self):
        opp = _make_opp(chain="arbitrum", chain_risk_score=20)
        flags = self.n._compute_flags(opp, 10.0, 0.0, 5.0)
        self.assertNotIn("HIGH_CHAIN_RISK", flags)

    def test_ethereum_mainnet_cost_flag(self):
        opp = _make_opp(chain="ethereum", gas_cost_per_interaction_usd=60,
                        interactions_per_month=2)
        # monthly_gas = 60*2 = 120 > 50
        flags = self.n._compute_flags(opp, 120.0, 0.0, 5.0)
        self.assertIn("ETHEREUM_MAINNET_COST", flags)

    def test_no_ethereum_mainnet_cost_for_l2(self):
        opp = _make_opp(chain="arbitrum", gas_cost_per_interaction_usd=60,
                        interactions_per_month=2)
        flags = self.n._compute_flags(opp, 120.0, 0.0, 5.0)
        self.assertNotIn("ETHEREUM_MAINNET_COST", flags)

    def test_flags_is_list(self):
        opp = _make_opp()
        flags = self.n._compute_flags(opp, 10.0, 0.0, 5.0)
        self.assertIsInstance(flags, list)


class TestNormalize(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.n = ProtocolDeFiCrossChainYieldNormalizer(data_dir=self.tmpdir)
        self.config = {"data_dir": self.tmpdir}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIsInstance(result, dict)

    def test_normalized_opportunities_key(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIn("normalized_opportunities", result)

    def test_aggregates_key(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIn("aggregates", result)

    def test_metadata_key(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIn("metadata", result)

    def test_count_matches_input(self):
        opps = [_make_opp(name=f"O{i}") for i in range(5)]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(len(result["normalized_opportunities"]), 5)

    def test_empty_input(self):
        result = self.n.normalize([], self.config)
        self.assertEqual(result["aggregates"]["avg_net_apy"], 0.0)
        self.assertEqual(result["aggregates"]["superior_count"], 0)
        self.assertEqual(result["aggregates"]["unviable_count"], 0)

    def test_log_file_created(self):
        self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_valid_json_list(self):
        self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows(self):
        self.n.normalize([_make_opp()], self.config)
        self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_cap_100(self):
        for _ in range(115):
            self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_normalized_opp_required_fields(self):
        result = self.n.normalize([_make_opp()], self.config)
        opp = result["normalized_opportunities"][0]
        for field in [
            "name", "protocol", "chain", "nominal_apy_pct", "chain_risk_score",
            "total_bridge_cost_usd", "bridge_cost_annualized_pct",
            "monthly_gas_cost_usd", "total_friction_pct",
            "chain_risk_adjusted_apy", "net_normalized_apy",
            "position_viability_score", "normalized_label", "flags",
        ]:
            self.assertIn(field, opp)

    def test_aggregates_required_fields(self):
        result = self.n.normalize([_make_opp()], self.config)
        agg = result["aggregates"]
        for field in [
            "best_normalized", "worst_normalized", "avg_net_apy",
            "superior_count", "unviable_count", "chain_comparison",
        ]:
            self.assertIn(field, agg)

    def test_metadata_mp(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertEqual(result["metadata"]["mp"], "MP-1023")

    def test_metadata_module(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertEqual(
            result["metadata"]["module"],
            "ProtocolDeFiCrossChainYieldNormalizer",
        )

    def test_metadata_timestamp(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIn("timestamp", result["metadata"])

    def test_metadata_opportunity_count(self):
        opps = [_make_opp(name=f"O{i}") for i in range(7)]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(result["metadata"]["opportunity_count"], 7)

    def test_superior_detected(self):
        opp = _high_apy_superior()
        result = self.n.normalize([opp], self.config)
        label = result["normalized_opportunities"][0]["normalized_label"]
        self.assertEqual(label, "SUPERIOR_OPPORTUNITY")

    def test_unviable_small_position(self):
        opp = _tiny_position()
        result = self.n.normalize([opp], self.config)
        label = result["normalized_opportunities"][0]["normalized_label"]
        self.assertEqual(label, "UNVIABLE")

    def test_chain_comparison_keys(self):
        opps = [
            _make_opp(name="ETH", chain="ethereum", chain_risk_score=10),
            _make_opp(name="ARB", chain="arbitrum", chain_risk_score=20),
        ]
        result = self.n.normalize(opps, self.config)
        cc = result["aggregates"]["chain_comparison"]
        self.assertIn("ethereum", cc)
        self.assertIn("arbitrum", cc)

    def test_avg_net_apy_is_float(self):
        result = self.n.normalize([_make_opp()], self.config)
        self.assertIsInstance(result["aggregates"]["avg_net_apy"], float)

    def test_superior_count_correct(self):
        opps = [_high_apy_superior(name=f"S{i}") for i in range(3)]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(result["aggregates"]["superior_count"], 3)

    def test_unviable_count_correct(self):
        opps = [_tiny_position(name=f"T{i}") for i in range(2)]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(result["aggregates"]["unviable_count"], 2)

    def test_best_normalized_is_highest_net(self):
        opps = [
            _high_apy_superior("Best"),
            _eth_mainnet_opp("Worst"),
        ]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(result["aggregates"]["best_normalized"], "Best")

    def test_worst_normalized_is_lowest_net(self):
        opps = [
            _high_apy_superior("Best"),
            _tiny_position("Worst"),
        ]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(result["aggregates"]["worst_normalized"], "Worst")

    def test_net_apy_lower_than_nominal(self):
        opp = _eth_mainnet_opp()
        result = self.n.normalize([opp], self.config)
        norm = result["normalized_opportunities"][0]
        self.assertLessEqual(norm["net_normalized_apy"], norm["nominal_apy_pct"])

    def test_l2_has_lower_friction_than_mainnet(self):
        eth = _eth_mainnet_opp("Mainnet")
        l2 = _l2_opp("L2")
        result = self.n.normalize([eth, l2], self.config)
        normed = {n["name"]: n for n in result["normalized_opportunities"]}
        self.assertGreater(
            normed["Mainnet"]["total_friction_pct"],
            normed["L2"]["total_friction_pct"],
        )

    def test_bridge_heavy_flag_on_expensive_bridge(self):
        opp = _make_opp(
            bridge_cost_usd_one_way=80,
            bridge_cost_usd_return=80,
            position_size_usd=50_000,
        )
        result = self.n.normalize([opp], self.config)
        flags = result["normalized_opportunities"][0]["flags"]
        self.assertIn("BRIDGE_HEAVY", flags)

    def test_position_too_small_flag(self):
        opp = _tiny_position()
        result = self.n.normalize([opp], self.config)
        flags = result["normalized_opportunities"][0]["flags"]
        self.assertIn("POSITION_TOO_SMALL", flags)

    def test_high_chain_risk_flag_bsc(self):
        opp = _make_opp(chain="bsc", chain_risk_score=60,
                        gas_cost_per_interaction_usd=1,
                        interactions_per_month=1,
                        position_size_usd=50_000)
        result = self.n.normalize([opp], self.config)
        flags = result["normalized_opportunities"][0]["flags"]
        self.assertIn("HIGH_CHAIN_RISK", flags)

    def test_ethereum_mainnet_cost_flag(self):
        opp = _make_opp(chain="ethereum", gas_cost_per_interaction_usd=60,
                        interactions_per_month=4,
                        position_size_usd=50_000)
        result = self.n.normalize([opp], self.config)
        flags = result["normalized_opportunities"][0]["flags"]
        self.assertIn("ETHEREUM_MAINNET_COST", flags)

    def test_no_errors_minimal_opp(self):
        minimal = {"name": "Min", "chain": "ethereum", "nominal_apy_pct": 3.0}
        result = self.n.normalize([minimal], self.config)
        self.assertIn("normalized_opportunities", result)

    def test_deterministic(self):
        opp = _make_opp()
        r1 = self.n.normalize([opp], self.config)
        r2 = self.n.normalize([opp], self.config)
        self.assertAlmostEqual(
            r1["normalized_opportunities"][0]["net_normalized_apy"],
            r2["normalized_opportunities"][0]["net_normalized_apy"],
        )

    def test_label_is_valid(self):
        valid = {"SUPERIOR_OPPORTUNITY", "ATTRACTIVE", "MARGINAL",
                 "FRICTION_DOMINATED", "UNVIABLE"}
        opps = [
            _high_apy_superior(),
            _eth_mainnet_opp(),
            _l2_opp(),
            _tiny_position(),
        ]
        result = self.n.normalize(opps, self.config)
        for n in result["normalized_opportunities"]:
            self.assertIn(n["normalized_label"], valid)

    def test_chain_comparison_avg_values(self):
        opps = [
            _make_opp(name="E1", chain="ethereum", chain_risk_score=10,
                      nominal_apy_pct=4.0,
                      gas_cost_per_interaction_usd=0, interactions_per_month=0,
                      bridge_cost_usd_one_way=0, bridge_cost_usd_return=0),
            _make_opp(name="E2", chain="ethereum", chain_risk_score=10,
                      nominal_apy_pct=6.0,
                      gas_cost_per_interaction_usd=0, interactions_per_month=0,
                      bridge_cost_usd_one_way=0, bridge_cost_usd_return=0),
        ]
        result = self.n.normalize(opps, self.config)
        cc = result["aggregates"]["chain_comparison"]
        # Both have same chain risk 10, avg net ≈ (4*0.9 + 6*0.9)/2 = (3.6+5.4)/2 = 4.5
        self.assertAlmostEqual(cc["ethereum"], 4.5, places=3)

    def test_log_entry_has_timestamp(self):
        self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[-1])

    def test_log_entry_has_avg_net_apy(self):
        self.n.normalize([_make_opp()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("avg_net_apy", data[-1])

    def test_log_entry_has_superior_count(self):
        self.n.normalize([_high_apy_superior()], self.config)
        log_path = os.path.join(self.tmpdir, "cross_chain_yield_normalized_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("superior_count", data[-1])

    def test_custom_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            normalizer = ProtocolDeFiCrossChainYieldNormalizer(data_dir=d)
            normalizer.normalize([_make_opp()], {})
            log_path = os.path.join(d, "cross_chain_yield_normalized_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_default_constructor(self):
        normalizer = ProtocolDeFiCrossChainYieldNormalizer()
        self.assertIsNotNone(normalizer.data_dir)

    def test_viability_score_in_range(self):
        result = self.n.normalize([_make_opp()], self.config)
        score = result["normalized_opportunities"][0]["position_viability_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_total_friction_in_result(self):
        opp = _make_opp(gas_cost_per_interaction_usd=0, interactions_per_month=0,
                        bridge_cost_usd_one_way=0, bridge_cost_usd_return=0)
        result = self.n.normalize([opp], self.config)
        friction = result["normalized_opportunities"][0]["total_friction_pct"]
        self.assertAlmostEqual(friction, 0.0)

    def test_100_opportunities_processed(self):
        opps = [_make_opp(name=f"O{i}") for i in range(100)]
        result = self.n.normalize(opps, self.config)
        self.assertEqual(len(result["normalized_opportunities"]), 100)

    def test_chain_risk_adj_apy_in_result(self):
        opp = _make_opp(nominal_apy_pct=10.0, chain_risk_score=10)
        result = self.n.normalize([opp], self.config)
        adj = result["normalized_opportunities"][0]["chain_risk_adjusted_apy"]
        self.assertAlmostEqual(adj, 9.0)

    def test_name_preserved_in_result(self):
        result = self.n.normalize([_make_opp(name="TestName")], self.config)
        self.assertEqual(result["normalized_opportunities"][0]["name"], "TestName")

    def test_protocol_preserved_in_result(self):
        result = self.n.normalize([_make_opp(protocol="Morpho")], self.config)
        self.assertEqual(result["normalized_opportunities"][0]["protocol"], "Morpho")

    def test_chain_preserved_in_result(self):
        result = self.n.normalize([_make_opp(chain="optimism")], self.config)
        self.assertEqual(result["normalized_opportunities"][0]["chain"], "optimism")


if __name__ == "__main__":
    unittest.main(verbosity=2)
