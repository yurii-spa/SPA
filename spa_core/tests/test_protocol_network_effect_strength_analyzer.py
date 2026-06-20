"""
Tests for MP-985: ProtocolNetworkEffectStrengthAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_network_effect_strength_analyzer -v
"""

import json
import os
import sys
import unittest
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_network_effect_strength_analyzer import (
    ProtocolNetworkEffectStrengthAnalyzer,
    _pct_change,
    _clamp,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _proto(
    name="Aave",
    category="lending",
    mau=100_000,
    mau_3m=80_000,
    integrations=60,
    integrations_3m=None,
    tvl=10_000_000_000.0,
    tvl_3m=8_000_000_000.0,
    tx_count=500_000,
    avg_tx=5000.0,
    switching=70.0,
    data_ne=True,
):
    d = {
        "name": name,
        "category": category,
        "monthly_active_users": mau,
        "monthly_active_users_3m_ago": mau_3m,
        "total_integrations": integrations,
        "total_tvl_usd": tvl,
        "tvl_3m_ago_usd": tvl_3m,
        "transaction_count_30d": tx_count,
        "avg_transaction_value_usd": avg_tx,
        "switching_cost_score": switching,
        "data_network_effect": data_ne,
    }
    if integrations_3m is not None:
        d["total_integrations_3m_ago"] = integrations_3m
    return d


def _make_diverse_protocols():
    return [
        _proto("Aave",    "lending",     mau=120_000,  mau_3m=90_000,  integrations=80,  switching=75.0),
        _proto("Uniswap", "dex",         mau=300_000,  mau_3m=250_000, integrations=200, switching=35.0),
        _proto("Curve",   "dex",         mau=50_000,   mau_3m=48_000,  integrations=100, switching=55.0),
        _proto("Lido",    "staking",     mau=200_000,  mau_3m=150_000, integrations=90,  switching=80.0),
        _proto("GMX",     "derivatives", mau=30_000,   mau_3m=25_000,  integrations=20,  switching=45.0),
    ]


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestPctChange(unittest.TestCase):
    def test_positive_growth(self):
        self.assertAlmostEqual(_pct_change(120, 100), 20.0)

    def test_negative_growth(self):
        self.assertAlmostEqual(_pct_change(80, 100), -20.0)

    def test_zero_old_returns_zero(self):
        self.assertEqual(_pct_change(100, 0), 0.0)

    def test_no_change(self):
        self.assertAlmostEqual(_pct_change(100, 100), 0.0)

    def test_100_pct_growth(self):
        self.assertAlmostEqual(_pct_change(200, 100), 100.0)


class TestClamp(unittest.TestCase):
    def test_clamp_above_hi(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_clamp_below_lo(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 10.0, 20.0), 10.0)
        self.assertEqual(_clamp(25.0, 10.0, 20.0), 20.0)
        self.assertEqual(_clamp(15.0, 10.0, 20.0), 15.0)


# ---------------------------------------------------------------------------
# Basic tests
# ---------------------------------------------------------------------------

class TestAnalyzerBasic(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_empty_protocols_returns_zero_count(self):
        r = self.analyzer.analyze([], self.cfg)
        self.assertEqual(r["protocol_count"], 0)

    def test_empty_protocols_has_error_key(self):
        r = self.analyzer.analyze([], self.cfg)
        self.assertIn("error", r)

    def test_single_protocol_returns_dict(self):
        r = self.analyzer.analyze([_proto()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_protocol_count_matches_input(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertEqual(r["protocol_count"], 5)

    def test_protocols_list_length(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertEqual(len(r["protocols"]), 5)

    def test_score_in_0_100_range(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        for p in r["protocols"]:
            self.assertGreaterEqual(p["network_strength_score"], 0.0)
            self.assertLessEqual(p["network_strength_score"], 100.0)


# ---------------------------------------------------------------------------
# Required output fields
# ---------------------------------------------------------------------------

class TestAnalyzerOutputFields(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}
        self.result = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_has_protocol_count(self):
        self.assertIn("protocol_count", self.result)

    def test_has_protocols_list(self):
        self.assertIn("protocols", self.result)
        self.assertIsInstance(self.result["protocols"], list)

    def test_has_average_network_score(self):
        self.assertIn("average_network_score", self.result)

    def test_has_strongest_network(self):
        self.assertIn("strongest_network", self.result)

    def test_has_weakest_network(self):
        self.assertIn("weakest_network", self.result)

    def test_has_dominant_count(self):
        self.assertIn("dominant_count", self.result)

    def test_has_no_moat_count(self):
        self.assertIn("no_moat_count", self.result)


class TestAnalyzerPerProtocolFields(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}
        r = self.analyzer.analyze([_proto()], self.cfg)
        self.proto = r["protocols"][0]

    def test_has_name(self):
        self.assertIn("name", self.proto)

    def test_has_category(self):
        self.assertIn("category", self.proto)

    def test_has_network_strength_score(self):
        self.assertIn("network_strength_score", self.proto)

    def test_has_network_label(self):
        self.assertIn("network_label", self.proto)

    def test_has_metcalfe_value(self):
        self.assertIn("metcalfe_value", self.proto)

    def test_has_metcalfe_score(self):
        self.assertIn("metcalfe_score", self.proto)

    def test_has_user_growth_pct_3m(self):
        self.assertIn("user_growth_pct_3m", self.proto)

    def test_has_tvl_growth_pct_3m(self):
        self.assertIn("tvl_growth_pct_3m", self.proto)

    def test_has_integration_density(self):
        self.assertIn("integration_density", self.proto)

    def test_has_growth_score(self):
        self.assertIn("growth_score", self.proto)

    def test_has_integration_score(self):
        self.assertIn("integration_score", self.proto)

    def test_has_switching_cost_score(self):
        self.assertIn("switching_cost_score", self.proto)

    def test_has_data_network_effect(self):
        self.assertIn("data_network_effect", self.proto)

    def test_has_flags(self):
        self.assertIn("flags", self.proto)
        self.assertIsInstance(self.proto["flags"], list)


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------

class TestMetcalfeValue(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_metcalfe_value_is_users_squared_times_avg_tx(self):
        proto = _proto(mau=1000, avg_tx=10.0)
        r = self.analyzer.analyze([proto], self.cfg)
        # metcalfe = 1000^2 * 10 = 10_000_000
        self.assertAlmostEqual(r["protocols"][0]["metcalfe_value"], 10_000_000.0, places=0)

    def test_zero_users_gives_zero_metcalfe(self):
        proto = _proto(mau=0, avg_tx=500.0)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["metcalfe_value"], 0.0)

    def test_zero_avg_tx_gives_zero_metcalfe(self):
        proto = _proto(mau=10_000, avg_tx=0.0)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["metcalfe_value"], 0.0)

    def test_metcalfe_score_100_for_largest(self):
        """The protocol with the highest metcalfe value should get score 100."""
        big = _proto("Big", mau=1_000_000, avg_tx=10_000.0)
        small = _proto("Small", mau=100, avg_tx=10.0)
        r = self.analyzer.analyze([big, small], self.cfg)
        big_proto = next(p for p in r["protocols"] if p["name"] == "Big")
        self.assertAlmostEqual(big_proto["metcalfe_score"], 100.0, places=1)

    def test_metcalfe_score_lower_for_smaller_protocol(self):
        big = _proto("Big", mau=1_000_000, avg_tx=10_000.0)
        small = _proto("Small", mau=100, avg_tx=10.0)
        r = self.analyzer.analyze([big, small], self.cfg)
        big_p   = next(p for p in r["protocols"] if p["name"] == "Big")
        small_p = next(p for p in r["protocols"] if p["name"] == "Small")
        self.assertGreater(big_p["metcalfe_score"], small_p["metcalfe_score"])


class TestGrowthCalculations(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_user_growth_pct_calculation(self):
        proto = _proto(mau=120, mau_3m=100)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["user_growth_pct_3m"], 20.0)

    def test_tvl_growth_pct_calculation(self):
        proto = _proto(tvl=12_000_000_000, tvl_3m=10_000_000_000)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["tvl_growth_pct_3m"], 20.0)

    def test_negative_user_growth(self):
        proto = _proto(mau=80, mau_3m=100)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["user_growth_pct_3m"], -20.0)

    def test_zero_base_user_growth_returns_zero(self):
        proto = _proto(mau=100, mau_3m=0)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["user_growth_pct_3m"], 0.0)


class TestIntegrationDensity(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_single_protocol_density_equals_integrations(self):
        """n=1 in category → density = integrations / sqrt(1) = integrations."""
        proto = _proto(category="lending", integrations=50)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertAlmostEqual(
            r["protocols"][0]["integration_density"], 50.0, places=4
        )

    def test_two_same_category_density_divided_by_sqrt2(self):
        import math
        p1 = _proto("A", category="lending", integrations=50)
        p2 = _proto("B", category="lending", integrations=50)
        r = self.analyzer.analyze([p1, p2], self.cfg)
        expected = 50.0 / math.sqrt(2)
        for p in r["protocols"]:
            self.assertAlmostEqual(p["integration_density"], expected, places=4)


# ---------------------------------------------------------------------------
# Network labels
# ---------------------------------------------------------------------------

class TestNetworkLabels(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_dominant_network_requires_high_switching(self):
        # High score, low switching → not DOMINANT
        proto = _proto(switching=20.0)
        r = self.analyzer.analyze([proto], self.cfg)
        label = r["protocols"][0]["network_label"]
        self.assertNotEqual(label, "DOMINANT_NETWORK")

    def test_dominant_network_with_high_score_and_switching(self):
        # Very high growth + high switching → DOMINANT
        proto = _proto(
            mau=10_000_000, mau_3m=1_000_000,   # 900% user growth
            tvl=100_000_000_000, tvl_3m=10_000_000_000,  # 900% TVL growth
            integrations=500,
            avg_tx=50_000.0,
            switching=90.0,
        )
        r = self.analyzer.analyze([proto], self.cfg)
        label = r["protocols"][0]["network_label"]
        # Could be DOMINANT or STRONG depending on normalised scores
        self.assertIn(label, ["DOMINANT_NETWORK", "STRONG_NETWORK"])

    def test_no_moat_for_weak_protocol(self):
        proto = _proto(
            mau=10, mau_3m=10,
            tvl=100_000, tvl_3m=100_000,
            integrations=0,
            avg_tx=1.0,
            switching=0.0,
        )
        r = self.analyzer.analyze([proto], self.cfg)
        label = r["protocols"][0]["network_label"]
        self.assertIn(label, ["NO_MOAT", "WEAK_NETWORK"])

    def test_label_one_of_valid_values(self):
        valid = {"DOMINANT_NETWORK", "STRONG_NETWORK", "EMERGING_NETWORK", "WEAK_NETWORK", "NO_MOAT"}
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        for p in r["protocols"]:
            self.assertIn(p["network_label"], valid)


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def _proto_flags(self, **kwargs):
        r = self.analyzer.analyze([_proto(**kwargs)], self.cfg)
        return r["protocols"][0]["flags"]

    def test_metcalfe_scaling_flag(self):
        flags = self._proto_flags(
            mau=130, mau_3m=100,   # 30% user growth
            tvl=1.3e10, tvl_3m=1e10,  # 30% TVL growth
        )
        self.assertIn("METCALFE_SCALING", flags)

    def test_no_metcalfe_scaling_if_only_user_growth(self):
        flags = self._proto_flags(
            mau=130, mau_3m=100,   # 30% user growth
            tvl=1e10, tvl_3m=1e10, # 0% TVL growth
        )
        self.assertNotIn("METCALFE_SCALING", flags)

    def test_no_metcalfe_scaling_if_only_tvl_growth(self):
        flags = self._proto_flags(
            mau=100, mau_3m=100,   # 0% user growth
            tvl=1.3e10, tvl_3m=1e10,  # 30% TVL growth
        )
        self.assertNotIn("METCALFE_SCALING", flags)

    def test_high_switching_cost_flag(self):
        flags = self._proto_flags(switching=80.0)
        self.assertIn("HIGH_SWITCHING_COST", flags)

    def test_no_high_switching_cost_below_threshold(self):
        flags = self._proto_flags(switching=65.0)
        self.assertNotIn("HIGH_SWITCHING_COST", flags)

    def test_integration_hub_flag(self):
        flags = self._proto_flags(integrations=55)
        self.assertIn("INTEGRATION_HUB", flags)

    def test_no_integration_hub_below_threshold(self):
        flags = self._proto_flags(integrations=49)
        self.assertNotIn("INTEGRATION_HUB", flags)

    def test_user_growth_stalling_flag(self):
        flags = self._proto_flags(mau=103, mau_3m=100)  # 3% growth
        self.assertIn("USER_GROWTH_STALLING", flags)

    def test_no_user_growth_stalling_above_threshold(self):
        flags = self._proto_flags(mau=110, mau_3m=100)  # 10% growth
        self.assertNotIn("USER_GROWTH_STALLING", flags)

    def test_losing_integrations_flag(self):
        proto = _proto(integrations=50, integrations_3m=60)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertIn("LOSING_INTEGRATIONS", r["protocols"][0]["flags"])

    def test_no_losing_integrations_when_growing(self):
        proto = _proto(integrations=60, integrations_3m=50)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertNotIn("LOSING_INTEGRATIONS", r["protocols"][0]["flags"])

    def test_no_losing_integrations_when_same(self):
        proto = _proto(integrations=50, integrations_3m=50)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertNotIn("LOSING_INTEGRATIONS", r["protocols"][0]["flags"])

    def test_multiple_flags_simultaneously(self):
        proto = _proto(
            mau=130, mau_3m=100, tvl=1.3e10, tvl_3m=1e10,  # METCALFE_SCALING
            integrations=100, integrations_3m=110,           # INTEGRATION_HUB + LOSING_INTEGRATIONS
            switching=80.0,                                   # HIGH_SWITCHING_COST
        )
        r = self.analyzer.analyze([proto], self.cfg)
        flags = r["protocols"][0]["flags"]
        self.assertIn("METCALFE_SCALING", flags)
        self.assertIn("HIGH_SWITCHING_COST", flags)
        self.assertIn("INTEGRATION_HUB", flags)
        self.assertIn("LOSING_INTEGRATIONS", flags)


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_average_score_equals_mean(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        scores = [p["network_strength_score"] for p in r["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(r["average_network_score"], expected_avg, places=3)

    def test_strongest_network_has_highest_score(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        scores = {p["name"]: p["network_strength_score"] for p in r["protocols"]}
        self.assertEqual(r["strongest_network"], max(scores, key=scores.get))

    def test_weakest_network_has_lowest_score(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        scores = {p["name"]: p["network_strength_score"] for p in r["protocols"]}
        self.assertEqual(r["weakest_network"], min(scores, key=scores.get))

    def test_dominant_count_integer(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertIsInstance(r["dominant_count"], int)

    def test_no_moat_count_integer(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertIsInstance(r["no_moat_count"], int)

    def test_dominant_plus_others_le_total(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertLessEqual(r["dominant_count"] + r["no_moat_count"], r["protocol_count"])

    def test_single_protocol_strongest_equals_weakest(self):
        r = self.analyzer.analyze([_proto()], self.cfg)
        self.assertEqual(r["strongest_network"], r["weakest_network"])

    def test_two_protocols_different_strongest_weakest(self):
        big   = _proto("Big",   mau=1_000_000, avg_tx=10_000.0, switching=90.0)
        small = _proto("Small", mau=1_000,     avg_tx=10.0,     switching=0.0)
        r = self.analyzer.analyze([big, small], self.cfg)
        self.assertNotEqual(r["strongest_network"], r["weakest_network"])


# ---------------------------------------------------------------------------
# Custom config thresholds
# ---------------------------------------------------------------------------

class TestCustomConfig(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()

    def test_custom_integration_hub_threshold(self):
        proto = _proto(integrations=30)
        r = self.analyzer.analyze(
            [proto], {"disable_log": True, "integration_hub_threshold": 25}
        )
        self.assertIn("INTEGRATION_HUB", r["protocols"][0]["flags"])

    def test_custom_stalling_growth_threshold(self):
        proto = _proto(mau=108, mau_3m=100)   # 8% growth
        r = self.analyzer.analyze(
            [proto], {"disable_log": True, "stalling_growth_threshold": 10.0}
        )
        self.assertIn("USER_GROWTH_STALLING", r["protocols"][0]["flags"])

    def test_custom_metcalfe_scaling_threshold(self):
        proto = _proto(mau=115, mau_3m=100, tvl=1.15e10, tvl_3m=1e10)  # 15% growth
        r = self.analyzer.analyze(
            [proto], {"disable_log": True, "metcalfe_scaling_growth": 10.0}
        )
        self.assertIn("METCALFE_SCALING", r["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "ne_log.json")
            self.analyzer.analyze([_proto()], {"log_path": log_path})
            self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "ne_log.json")
            self.analyzer.analyze([_proto()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "ne_log.json")
            for _ in range(5):
                self.analyzer.analyze([_proto()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "ne_log.json")
            for _ in range(LOG_CAP + 15):
                self.analyzer.analyze([_proto()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), LOG_CAP)

    def test_disable_log_skips_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "ne_log.json")
            self.analyzer.analyze([_proto()], {"disable_log": True, "log_path": log_path})
            self.assertFalse(os.path.exists(log_path))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_zero_mau_does_not_crash(self):
        r = self.analyzer.analyze([_proto(mau=0, mau_3m=0)], self.cfg)
        self.assertIn("protocols", r)

    def test_zero_tvl_does_not_crash(self):
        r = self.analyzer.analyze([_proto(tvl=0.0, tvl_3m=0.0)], self.cfg)
        self.assertIn("protocols", r)

    def test_zero_integrations_does_not_crash(self):
        r = self.analyzer.analyze([_proto(integrations=0)], self.cfg)
        self.assertIn("protocols", r)

    def test_missing_optional_fields_default_gracefully(self):
        minimal = {"name": "X", "category": "dex"}
        r = self.analyzer.analyze([minimal], self.cfg)
        self.assertEqual(r["protocol_count"], 1)

    def test_100_protocols(self):
        protos = [_proto(name=f"P{i}") for i in range(100)]
        r = self.analyzer.analyze(protos, self.cfg)
        self.assertEqual(r["protocol_count"], 100)

    def test_all_same_category_integration_density(self):
        import math
        n = 4
        protos = [_proto(name=f"P{i}", category="lending", integrations=16) for i in range(n)]
        r = self.analyzer.analyze(protos, self.cfg)
        expected = 16.0 / math.sqrt(n)
        for p in r["protocols"]:
            self.assertAlmostEqual(p["integration_density"], expected, places=4)

    def test_deterministic_results(self):
        protos = _make_diverse_protocols()
        r1 = self.analyzer.analyze(protos, self.cfg)
        r2 = self.analyzer.analyze(protos, self.cfg)
        for p1, p2 in zip(r1["protocols"], r2["protocols"]):
            self.assertAlmostEqual(
                p1["network_strength_score"], p2["network_strength_score"], places=6
            )

    def test_data_network_effect_stored(self):
        proto = _proto(data_ne=True)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertTrue(r["protocols"][0]["data_network_effect"])

    def test_data_network_effect_false_stored(self):
        proto = _proto(data_ne=False)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertFalse(r["protocols"][0]["data_network_effect"])

    def test_negative_mau_clamped_to_zero(self):
        proto = _proto(mau=-100, mau_3m=-50)
        # Should not crash
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertEqual(r["protocol_count"], 1)

    def test_very_large_values_no_overflow(self):
        proto = _proto(mau=10_000_000, avg_tx=100_000.0)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertGreaterEqual(r["protocols"][0]["network_strength_score"], 0.0)

    def test_switching_cost_clamped_above_100(self):
        proto = _proto(switching=150.0)
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertLessEqual(r["protocols"][0]["switching_cost_score"], 100.0)

    def test_total_integrations_3m_defaults_to_current(self):
        """If total_integrations_3m_ago is absent, no LOSING_INTEGRATIONS flag."""
        proto = _proto(integrations=50)  # no integrations_3m → defaults to same
        r = self.analyzer.analyze([proto], self.cfg)
        self.assertNotIn("LOSING_INTEGRATIONS", r["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# Score weighting sanity
# ---------------------------------------------------------------------------

class TestScoreWeighting(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolNetworkEffectStrengthAnalyzer()
        self.cfg = {"disable_log": True}

    def test_score_increases_with_growth(self):
        low_growth  = _proto(mau=101, mau_3m=100, tvl=1.01e10, tvl_3m=1e10)
        high_growth = _proto(mau=150, mau_3m=100, tvl=1.5e10,  tvl_3m=1e10)
        r_low  = self.analyzer.analyze([low_growth],  self.cfg)
        r_high = self.analyzer.analyze([high_growth], self.cfg)
        self.assertGreater(
            r_high["protocols"][0]["network_strength_score"],
            r_low["protocols"][0]["network_strength_score"],
        )

    def test_score_increases_with_switching_cost(self):
        low_sw  = _proto(switching=10.0)
        high_sw = _proto(switching=90.0)
        # Use identical other params, same batch
        r_low  = self.analyzer.analyze([low_sw],  self.cfg)
        r_high = self.analyzer.analyze([high_sw], self.cfg)
        self.assertGreater(
            r_high["protocols"][0]["network_strength_score"],
            r_low["protocols"][0]["network_strength_score"],
        )

    def test_average_score_range(self):
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        self.assertGreaterEqual(r["average_network_score"], 0.0)
        self.assertLessEqual(r["average_network_score"], 100.0)

    def test_protocol_ordering_by_score(self):
        """Protocols can be sorted by score; highest score = strongest."""
        r = self.analyzer.analyze(_make_diverse_protocols(), self.cfg)
        scored = sorted(r["protocols"], key=lambda x: x["network_strength_score"], reverse=True)
        self.assertEqual(scored[0]["name"], r["strongest_network"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
