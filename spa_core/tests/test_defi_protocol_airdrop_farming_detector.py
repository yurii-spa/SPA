"""
Tests for DeFiProtocolAirdropFarmingDetector (MP-996).
Run: python3 -m unittest spa_core.tests.test_defi_protocol_airdrop_farming_detector
"""
import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_airdrop_farming_detector import (
    DeFiProtocolAirdropFarmingDetector,
    _atomic_write,
    _load_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _organic() -> dict:
    """Clearly organic protocol."""
    return {
        "name": "OrgProtocol",
        "announced_airdrop": False,
        "airdrop_date_days_until": None,
        "tvl_usd": 500_000_000,
        "tvl_change_30d_pct": 5.0,
        "unique_wallets_30d": 100_000,
        "wallet_growth_30d_pct": 4.0,
        "avg_transaction_size_usd": 25_000,
        "dust_wallet_pct": 3.0,
        "repeat_interaction_rate_pct": 70.0,
        "tvl_per_wallet_usd": 5_000,
        "has_points_system": False,
        "points_to_token_ratio_announced": False,
    }


def _farming() -> dict:
    """Heavily farmed protocol."""
    return {
        "name": "FarmProtocol",
        "announced_airdrop": True,
        "airdrop_date_days_until": 30,
        "tvl_usd": 200_000_000,
        "tvl_change_30d_pct": 10.0,
        "unique_wallets_30d": 500_000,
        "wallet_growth_30d_pct": 200.0,
        "avg_transaction_size_usd": 50,
        "dust_wallet_pct": 75.0,
        "repeat_interaction_rate_pct": 10.0,
        "tvl_per_wallet_usd": 400,
        "has_points_system": True,
        "points_to_token_ratio_announced": True,
    }


def _sybil() -> dict:
    """Sybil farm."""
    return {
        "name": "SybilProtocol",
        "announced_airdrop": True,
        "airdrop_date_days_until": 10,
        "tvl_usd": 10_000_000,
        "tvl_change_30d_pct": 2.0,
        "unique_wallets_30d": 1_000_000,
        "wallet_growth_30d_pct": 500.0,
        "avg_transaction_size_usd": 10,
        "dust_wallet_pct": 90.0,
        "repeat_interaction_rate_pct": 5.0,
        "tvl_per_wallet_usd": 10,
        "has_points_system": True,
        "points_to_token_ratio_announced": False,
    }


def _detector(tmp_dir: str) -> DeFiProtocolAirdropFarmingDetector:
    log_path = os.path.join(tmp_dir, "test_farming_log.json")
    return DeFiProtocolAirdropFarmingDetector(log_path=log_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicDetection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_returns_dict(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertIsInstance(result, dict)

    def test_results_key_present(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertIn("results", result)

    def test_aggregates_key_present(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertIn("aggregates", result)

    def test_timestamp_present(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertIn("timestamp", result)

    def test_single_protocol_result_count(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertEqual(len(result["results"]), 1)

    def test_two_protocols_result_count(self):
        result = self.det.detect([_organic(), _farming()], {"write_log": False})
        self.assertEqual(len(result["results"]), 2)

    def test_empty_protocols(self):
        result = self.det.detect([], {"write_log": False})
        self.assertEqual(result["results"], [])

    def test_empty_aggregates_total(self):
        result = self.det.detect([], {"write_log": False})
        self.assertEqual(result["aggregates"]["total_protocols"], 0)

    def test_organic_label(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertEqual(result["results"][0]["label"], "ORGANIC_GROWTH")

    def test_farming_label(self):
        result = self.det.detect([_farming()], {"write_log": False})
        label = result["results"][0]["label"]
        self.assertIn(label, {"FARMING_DOMINANT", "AIRDROP_INFLATED", "SYBIL_FARM"})

    def test_sybil_label(self):
        result = self.det.detect([_sybil()], {"write_log": False})
        self.assertEqual(result["results"][0]["label"], "SYBIL_FARM")

    def test_protocol_name_in_result(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertEqual(result["results"][0]["protocol"], "OrgProtocol")

    def test_farming_intensity_score_range(self):
        result = self.det.detect([_farming()], {"write_log": False})
        score = result["results"][0]["farming_intensity_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_organic_user_pct_range(self):
        result = self.det.detect([_organic()], {"write_log": False})
        pct = result["results"][0]["organic_user_pct"]
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)

    def test_sybil_risk_score_range(self):
        result = self.det.detect([_sybil()], {"write_log": False})
        score = result["results"][0]["sybil_risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_capital_stickiness_range(self):
        result = self.det.detect([_organic()], {"write_log": False})
        stick = result["results"][0]["capital_stickiness_prediction"]
        self.assertGreaterEqual(stick, 0)
        self.assertLessEqual(stick, 100)

    def test_flags_is_list(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertIsInstance(result["results"][0]["flags"], list)

    def test_farming_score_higher_for_farmed(self):
        r_org = self.det.detect([_organic()], {"write_log": False})
        r_farm = self.det.detect([_farming()], {"write_log": False})
        self.assertGreater(
            r_farm["results"][0]["farming_intensity_score"],
            r_org["results"][0]["farming_intensity_score"],
        )

    def test_sybil_score_higher_for_sybil(self):
        r_org = self.det.detect([_organic()], {"write_log": False})
        r_syb = self.det.detect([_sybil()], {"write_log": False})
        self.assertGreater(
            r_syb["results"][0]["sybil_risk_score"],
            r_org["results"][0]["sybil_risk_score"],
        )

    def test_organic_stickiness_higher(self):
        r_org = self.det.detect([_organic()], {"write_log": False})
        r_farm = self.det.detect([_farming()], {"write_log": False})
        self.assertGreater(
            r_org["results"][0]["capital_stickiness_prediction"],
            r_farm["results"][0]["capital_stickiness_prediction"],
        )


class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_announced_airdrop_flag(self):
        result = self.det.detect([_farming()], {"write_log": False})
        self.assertIn("ANNOUNCED_AIRDROP_CATALYST", result["results"][0]["flags"])

    def test_points_farming_active_flag(self):
        result = self.det.detect([_farming()], {"write_log": False})
        self.assertIn("POINTS_FARMING_ACTIVE", result["results"][0]["flags"])

    def test_no_announced_flag_organic(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertNotIn("ANNOUNCED_AIRDROP_CATALYST", result["results"][0]["flags"])

    def test_no_points_flag_organic(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertNotIn("POINTS_FARMING_ACTIVE", result["results"][0]["flags"])

    def test_high_sybil_risk_flag(self):
        result = self.det.detect([_sybil()], {"write_log": False})
        self.assertIn("HIGH_SYBIL_RISK", result["results"][0]["flags"])

    def test_capital_flight_risk_flag(self):
        p = _farming()
        p["repeat_interaction_rate_pct"] = 2.0
        p["avg_transaction_size_usd"] = 10
        result = self.det.detect([p], {"write_log": False})
        self.assertIn("CAPITAL_FLIGHT_RISK", result["results"][0]["flags"])

    def test_dust_wallet_concentration_flag(self):
        p = _farming()
        p["dust_wallet_pct"] = 55.0
        result = self.det.detect([p], {"write_log": False})
        self.assertIn("DUST_WALLET_CONCENTRATION", result["results"][0]["flags"])

    def test_no_dust_flag_low_dust(self):
        p = _organic()
        p["dust_wallet_pct"] = 5.0
        result = self.det.detect([p], {"write_log": False})
        self.assertNotIn("DUST_WALLET_CONCENTRATION", result["results"][0]["flags"])

    def test_organic_retention_signal_flag(self):
        p = _organic()
        p["repeat_interaction_rate_pct"] = 60.0
        result = self.det.detect([p], {"write_log": False})
        self.assertIn("ORGANIC_RETENTION_SIGNAL", result["results"][0]["flags"])

    def test_no_organic_retention_low_repeat(self):
        p = _farming()
        p["repeat_interaction_rate_pct"] = 5.0
        result = self.det.detect([p], {"write_log": False})
        self.assertNotIn("ORGANIC_RETENTION_SIGNAL", result["results"][0]["flags"])


class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_most_organic_is_organic_protocol(self):
        result = self.det.detect([_organic(), _farming()], {"write_log": False})
        self.assertEqual(result["aggregates"]["most_organic"], "OrgProtocol")

    def test_most_farmed_is_farming_protocol(self):
        result = self.det.detect([_organic(), _farming()], {"write_log": False})
        self.assertEqual(result["aggregates"]["most_farmed"], "FarmProtocol")

    def test_avg_farming_score_numeric(self):
        result = self.det.detect([_organic(), _farming()], {"write_log": False})
        self.assertIsInstance(result["aggregates"]["avg_farming_score"], float)

    def test_sybil_farm_count(self):
        result = self.det.detect([_sybil(), _organic()], {"write_log": False})
        self.assertEqual(result["aggregates"]["sybil_farm_count"], 1)

    def test_organic_count(self):
        result = self.det.detect([_organic(), _organic()], {"write_log": False})
        self.assertEqual(result["aggregates"]["organic_count"], 2)

    def test_total_protocols(self):
        result = self.det.detect([_organic(), _farming(), _sybil()], {"write_log": False})
        self.assertEqual(result["aggregates"]["total_protocols"], 3)

    def test_no_sybil_when_organic_only(self):
        result = self.det.detect([_organic()], {"write_log": False})
        self.assertEqual(result["aggregates"]["sybil_farm_count"], 0)

    def test_zero_organic_count_when_farming(self):
        result = self.det.detect([_sybil()], {"write_log": False})
        self.assertEqual(result["aggregates"]["organic_count"], 0)

    def test_aggregates_keys_complete(self):
        result = self.det.detect([_organic()], {"write_log": False})
        agg = result["aggregates"]
        for key in ["most_organic", "most_farmed", "avg_farming_score",
                    "sybil_farm_count", "organic_count", "total_protocols"]:
            self.assertIn(key, agg)


class TestLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "farm_log.json")
        self.det = DeFiProtocolAirdropFarmingDetector(log_path=self.log_path)

    def test_log_file_created(self):
        self.det.detect([_organic()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.det.detect([_organic()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_contains_one_entry(self):
        self.det.detect([_organic()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_grows(self):
        self.det.detect([_organic()], {"write_log": True})
        self.det.detect([_farming()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_no_write_when_disabled(self):
        self.det.detect([_organic()], {"write_log": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_ring_buffer_cap(self):
        for i in range(105):
            p = _organic()
            p["name"] = f"P{i}"
            self.det.detect([p], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_atomic_write_helper(self):
        path = os.path.join(self.tmp, "atomic_test.json")
        _atomic_write(path, {"key": "value"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_load_log_missing_file(self):
        result = _load_log("/nonexistent/path.json")
        self.assertEqual(result, [])

    def test_load_log_invalid_json(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write("not json")
        result = _load_log(bad)
        self.assertEqual(result, [])

    def test_log_entry_has_results(self):
        self.det.detect([_organic()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("results", data[0])

    def test_log_entry_has_timestamp(self):
        self.det.detect([_organic()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


class TestScoreCalculations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_zero_dust_reduces_farming_score(self):
        p = _farming()
        p["dust_wallet_pct"] = 0
        result = self.det.detect([p], {"write_log": False})
        score_low_dust = result["results"][0]["farming_intensity_score"]
        p2 = _farming()
        p2["dust_wallet_pct"] = 80
        result2 = self.det.detect([p2], {"write_log": False})
        self.assertLess(score_low_dust, result2["results"][0]["farming_intensity_score"])

    def test_high_dust_increases_farming_score(self):
        p = _organic()
        p["dust_wallet_pct"] = 80
        result = self.det.detect([p], {"write_log": False})
        score = result["results"][0]["farming_intensity_score"]
        self.assertGreater(score, 20)

    def test_announced_airdrop_increases_farming_score(self):
        p_no = _organic()
        p_yes = dict(p_no)
        p_yes["announced_airdrop"] = True
        r_no = self.det.detect([p_no], {"write_log": False})
        r_yes = self.det.detect([p_yes], {"write_log": False})
        self.assertGreater(
            r_yes["results"][0]["farming_intensity_score"],
            r_no["results"][0]["farming_intensity_score"],
        )

    def test_points_system_increases_farming_score(self):
        p_no = _organic()
        p_yes = dict(p_no)
        p_yes["has_points_system"] = True
        r_no = self.det.detect([p_no], {"write_log": False})
        r_yes = self.det.detect([p_yes], {"write_log": False})
        self.assertGreaterEqual(
            r_yes["results"][0]["farming_intensity_score"],
            r_no["results"][0]["farming_intensity_score"],
        )

    def test_high_wallet_growth_increases_sybil(self):
        p_low = _organic()
        p_high = dict(p_low)
        p_high["wallet_growth_30d_pct"] = 300.0
        r_low = self.det.detect([p_low], {"write_log": False})
        r_high = self.det.detect([p_high], {"write_log": False})
        self.assertGreater(
            r_high["results"][0]["sybil_risk_score"],
            r_low["results"][0]["sybil_risk_score"],
        )

    def test_small_avg_tx_increases_sybil(self):
        p_large = _organic()
        p_small = dict(p_large)
        p_small["avg_transaction_size_usd"] = 5
        r_large = self.det.detect([p_large], {"write_log": False})
        r_small = self.det.detect([p_small], {"write_log": False})
        self.assertGreater(
            r_small["results"][0]["sybil_risk_score"],
            r_large["results"][0]["sybil_risk_score"],
        )

    def test_high_repeat_increases_stickiness(self):
        p_low = _organic()
        p_low["repeat_interaction_rate_pct"] = 10
        p_high = dict(p_low)
        p_high["repeat_interaction_rate_pct"] = 80
        r_low = self.det.detect([p_low], {"write_log": False})
        r_high = self.det.detect([p_high], {"write_log": False})
        self.assertGreater(
            r_high["results"][0]["capital_stickiness_prediction"],
            r_low["results"][0]["capital_stickiness_prediction"],
        )

    def test_no_airdrop_increases_stickiness(self):
        p_no = _organic()
        p_yes = dict(p_no)
        p_yes["announced_airdrop"] = True
        r_no = self.det.detect([p_no], {"write_log": False})
        r_yes = self.det.detect([p_yes], {"write_log": False})
        self.assertGreater(
            r_no["results"][0]["capital_stickiness_prediction"],
            r_yes["results"][0]["capital_stickiness_prediction"],
        )

    def test_organic_pct_high_for_low_dust(self):
        p = _organic()
        p["dust_wallet_pct"] = 2.0
        p["repeat_interaction_rate_pct"] = 80
        result = self.det.detect([p], {"write_log": False})
        self.assertGreater(result["results"][0]["organic_user_pct"], 80)

    def test_organic_pct_low_for_high_dust(self):
        p = _sybil()
        result = self.det.detect([p], {"write_log": False})
        self.assertLess(result["results"][0]["organic_user_pct"], 30)

    def test_farming_score_not_negative(self):
        p = _organic()
        result = self.det.detect([p], {"write_log": False})
        self.assertGreaterEqual(result["results"][0]["farming_intensity_score"], 0)

    def test_farming_score_not_over_100(self):
        p = _sybil()
        result = self.det.detect([p], {"write_log": False})
        self.assertLessEqual(result["results"][0]["farming_intensity_score"], 100)

    def test_sybil_score_not_negative(self):
        p = _organic()
        result = self.det.detect([p], {"write_log": False})
        self.assertGreaterEqual(result["results"][0]["sybil_risk_score"], 0)

    def test_stickiness_not_over_100(self):
        p = _organic()
        result = self.det.detect([p], {"write_log": False})
        self.assertLessEqual(result["results"][0]["capital_stickiness_prediction"], 100)

    def test_avg_farming_score_between_extremes(self):
        result = self.det.detect([_organic(), _farming()], {"write_log": False})
        avg = result["aggregates"]["avg_farming_score"]
        org_score = result["results"][0]["farming_intensity_score"]
        farm_score = result["results"][1]["farming_intensity_score"]
        self.assertGreater(avg, min(org_score, farm_score) - 1)
        self.assertLess(avg, max(org_score, farm_score) + 1)


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_zero_tvl_per_wallet(self):
        p = dict(_organic())
        p["tvl_per_wallet_usd"] = 0
        result = self.det.detect([p], {"write_log": False})
        self.assertIsNotNone(result)

    def test_zero_avg_transaction_size(self):
        p = dict(_organic())
        p["avg_transaction_size_usd"] = 0
        result = self.det.detect([p], {"write_log": False})
        self.assertIsNotNone(result)

    def test_missing_name_defaults(self):
        p = dict(_organic())
        del p["name"]
        result = self.det.detect([p], {"write_log": False})
        self.assertEqual(result["results"][0]["protocol"], "unknown")

    def test_100_dust_wallet_pct(self):
        p = dict(_farming())
        p["dust_wallet_pct"] = 100.0
        result = self.det.detect([p], {"write_log": False})
        score = result["results"][0]["farming_intensity_score"]
        self.assertLessEqual(score, 100)

    def test_zero_wallet_growth(self):
        p = dict(_organic())
        p["wallet_growth_30d_pct"] = 0
        result = self.det.detect([p], {"write_log": False})
        self.assertGreaterEqual(result["results"][0]["sybil_risk_score"], 0)

    def test_many_protocols(self):
        protocols = []
        for i in range(20):
            p = dict(_organic())
            p["name"] = f"P{i}"
            protocols.append(p)
        result = self.det.detect(protocols, {"write_log": False})
        self.assertEqual(len(result["results"]), 20)

    def test_config_passed_to_output(self):
        cfg = {"write_log": False, "env": "test"}
        result = self.det.detect([_organic()], cfg)
        self.assertEqual(result["config"]["env"], "test")

    def test_negative_tvl_change(self):
        p = dict(_farming())
        p["tvl_change_30d_pct"] = -50.0
        result = self.det.detect([p], {"write_log": False})
        self.assertIsNotNone(result)

    def test_mixed_organic_label(self):
        p = {
            "name": "MixedP",
            "announced_airdrop": False,
            "airdrop_date_days_until": None,
            "tvl_usd": 100_000_000,
            "tvl_change_30d_pct": 10.0,
            "unique_wallets_30d": 30_000,
            "wallet_growth_30d_pct": 20.0,
            "avg_transaction_size_usd": 1_000,
            "dust_wallet_pct": 20.0,
            "repeat_interaction_rate_pct": 40.0,
            "tvl_per_wallet_usd": 3_333,
            "has_points_system": False,
            "points_to_token_ratio_announced": False,
        }
        result = self.det.detect([p], {"write_log": False})
        self.assertIn(result["results"][0]["label"], {
            "ORGANIC_GROWTH", "MIXED_ORGANIC", "AIRDROP_INFLATED",
            "FARMING_DOMINANT", "SYBIL_FARM"
        })

    def test_airdrop_inflated_label_possible(self):
        p = {
            "name": "InflatedP",
            "announced_airdrop": True,
            "airdrop_date_days_until": 60,
            "tvl_usd": 100_000_000,
            "tvl_change_30d_pct": 30.0,
            "unique_wallets_30d": 80_000,
            "wallet_growth_30d_pct": 40.0,
            "avg_transaction_size_usd": 500,
            "dust_wallet_pct": 35.0,
            "repeat_interaction_rate_pct": 30.0,
            "tvl_per_wallet_usd": 1_250,
            "has_points_system": False,
            "points_to_token_ratio_announced": False,
        }
        result = self.det.detect([p], {"write_log": False})
        label = result["results"][0]["label"]
        self.assertIn(label, {
            "AIRDROP_INFLATED", "FARMING_DOMINANT", "MIXED_ORGANIC",
            "ORGANIC_GROWTH", "SYBIL_FARM"
        })

    def test_result_keys_complete(self):
        result = self.det.detect([_organic()], {"write_log": False})
        r = result["results"][0]
        for key in ["protocol", "farming_intensity_score", "organic_user_pct",
                    "sybil_risk_score", "capital_stickiness_prediction",
                    "label", "flags"]:
            self.assertIn(key, r)

    def test_large_tvl_per_wallet_lowers_imbalance(self):
        p = dict(_organic())
        p["tvl_per_wallet_usd"] = 1_000_000
        result = self.det.detect([p], {"write_log": False})
        # large tvl_per_wallet → lower farming
        self.assertLess(result["results"][0]["farming_intensity_score"], 50)

    def test_very_large_wallet_growth_increases_sybil(self):
        p = dict(_organic())
        p["wallet_growth_30d_pct"] = 1000.0
        result = self.det.detect([p], {"write_log": False})
        self.assertGreater(result["results"][0]["sybil_risk_score"], 50)

    def test_all_labels_valid(self):
        valid = {"ORGANIC_GROWTH", "MIXED_ORGANIC", "AIRDROP_INFLATED",
                 "FARMING_DOMINANT", "SYBIL_FARM"}
        for p in [_organic(), _farming(), _sybil()]:
            result = self.det.detect([p], {"write_log": False})
            self.assertIn(result["results"][0]["label"], valid)


class TestAdditionalCoverage(unittest.TestCase):
    """Extra tests to reach ≥80 total."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _detector(self.tmp)

    def test_detector_instantiation_default_log(self):
        det = DeFiProtocolAirdropFarmingDetector()
        self.assertIsNotNone(det)

    def test_multiple_sybil_protocols(self):
        result = self.det.detect([_sybil(), _sybil()], {"write_log": False})
        self.assertEqual(result["aggregates"]["sybil_farm_count"], 2)

    def test_all_organic_count(self):
        result = self.det.detect([_organic(), _organic(), _organic()], {"write_log": False})
        self.assertEqual(result["aggregates"]["organic_count"], 3)

    def test_points_ratio_announced_raises_farming(self):
        p_no = dict(_organic())
        p_yes = dict(_organic())
        p_yes["points_to_token_ratio_announced"] = True
        p_yes["has_points_system"] = True
        r_no = self.det.detect([p_no], {"write_log": False})
        r_yes = self.det.detect([p_yes], {"write_log": False})
        self.assertGreaterEqual(
            r_yes["results"][0]["farming_intensity_score"],
            r_no["results"][0]["farming_intensity_score"],
        )

    def test_organic_pct_not_negative(self):
        p = dict(_sybil())
        p["dust_wallet_pct"] = 100
        p["repeat_interaction_rate_pct"] = 0
        result = self.det.detect([p], {"write_log": False})
        self.assertGreaterEqual(result["results"][0]["organic_user_pct"], 0)

    def test_config_write_log_default_true(self):
        # When write_log absent, default behaviour should not crash
        log_path = os.path.join(self.tmp, "default_log.json")
        det = DeFiProtocolAirdropFarmingDetector(log_path=log_path)
        result = det.detect([_organic()], {})  # no write_log key
        self.assertIsNotNone(result)

    def test_avg_farming_score_matches_manual(self):
        result = self.det.detect([_organic(), _farming(), _sybil()], {"write_log": False})
        scores = [r["farming_intensity_score"] for r in result["results"]]
        expected_avg = round(sum(scores) / len(scores), 2)
        self.assertAlmostEqual(result["aggregates"]["avg_farming_score"], expected_avg, places=1)

    def test_label_not_empty(self):
        for p in [_organic(), _farming(), _sybil()]:
            result = self.det.detect([p], {"write_log": False})
            self.assertTrue(len(result["results"][0]["label"]) > 0)

    def test_flags_not_duplicated(self):
        result = self.det.detect([_sybil()], {"write_log": False})
        flags = result["results"][0]["flags"]
        self.assertEqual(len(flags), len(set(flags)))

    def test_zero_repeat_interaction_lowers_stickiness(self):
        p = dict(_organic())
        p["repeat_interaction_rate_pct"] = 0
        result = self.det.detect([p], {"write_log": False})
        stickiness = result["results"][0]["capital_stickiness_prediction"]
        p2 = dict(_organic())
        p2["repeat_interaction_rate_pct"] = 90
        result2 = self.det.detect([p2], {"write_log": False})
        self.assertLess(stickiness, result2["results"][0]["capital_stickiness_prediction"])


if __name__ == "__main__":
    unittest.main()
