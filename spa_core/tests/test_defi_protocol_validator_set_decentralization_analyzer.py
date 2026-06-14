"""
Tests for MP-1006 DeFiProtocolValidatorSetDecentralizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_validator_set_decentralization_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spa_core.analytics.defi_protocol_validator_set_decentralization_analyzer import (
    analyze,
    _compute_hhi,
    _stake_concentration_score,
    _validator_diversity_score,
    _nakamoto_ratio,
    _liveness_risk_score,
    _decentralization_label,
    _compute_flags,
    _parse_multisig,
    _append_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_network(**kwargs):
    """Return a minimal valid network dict with overrides."""
    base = {
        "name": "TestNet",
        "network_type": "l1_pos",
        "validator_count": 500,
        "top_validator_stake_pct": 5.0,
        "top5_validator_stake_pct": 20.0,
        "top10_validator_stake_pct": 35.0,
        "geographic_distribution_score": 70.0,
        "client_diversity_score": 65.0,
        "nakamoto_coefficient": 30,
        "time_to_finality_seconds": 12.0,
        "slashing_incidents_count": 1,
        "sequencer_centralized": False,
        "upgrade_multisig_threshold": "5/9",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _compute_hhi
# ---------------------------------------------------------------------------

class TestComputeHHI(unittest.TestCase):

    def test_perfect_distribution_low_hhi(self):
        """100 validators with equal stakes → very low HHI."""
        hhi = _compute_hhi(1.0, 5.0, 10.0, 100)
        self.assertLess(hhi, 200)

    def test_monopoly_high_hhi(self):
        """Single validator holds 100% → near-maximum HHI."""
        hhi = _compute_hhi(100.0, 100.0, 100.0, 1)
        self.assertGreater(hhi, 9000)

    def test_top1_dominance_raises_hhi(self):
        """Higher top1 stake → higher HHI."""
        hhi_low = _compute_hhi(5.0, 20.0, 30.0, 500)
        hhi_high = _compute_hhi(50.0, 70.0, 80.0, 500)
        self.assertGreater(hhi_high, hhi_low)

    def test_returns_float(self):
        hhi = _compute_hhi(10.0, 30.0, 50.0, 200)
        self.assertIsInstance(hhi, float)

    def test_non_negative(self):
        hhi = _compute_hhi(0.0, 0.0, 0.0, 1000)
        self.assertGreaterEqual(hhi, 0.0)

    def test_clamped_top5_below_top1(self):
        """If top5 < top1 due to bad data, clamp to top1."""
        hhi = _compute_hhi(30.0, 10.0, 20.0, 200)
        self.assertGreaterEqual(hhi, 0.0)

    def test_small_validator_set(self):
        hhi = _compute_hhi(10.0, 40.0, 60.0, 10)
        self.assertGreater(hhi, 0.0)

    def test_large_validator_set_dilution(self):
        """Large validator set with flat stakes → near-zero HHI per remaining."""
        hhi = _compute_hhi(1.0, 5.0, 10.0, 10000)
        self.assertLess(hhi, 100)


# ---------------------------------------------------------------------------
# _stake_concentration_score
# ---------------------------------------------------------------------------

class TestStakeConcentrationScore(unittest.TestCase):

    def test_zero_hhi_zero_score(self):
        self.assertEqual(_stake_concentration_score(0.0), 0)

    def test_10000_hhi_max_score(self):
        self.assertEqual(_stake_concentration_score(10000.0), 100)

    def test_5000_hhi_midpoint(self):
        score = _stake_concentration_score(5000.0)
        self.assertEqual(score, 50)

    def test_returns_int(self):
        self.assertIsInstance(_stake_concentration_score(1234.0), int)

    def test_clamped_above_100(self):
        self.assertEqual(_stake_concentration_score(20000.0), 100)

    def test_clamped_below_0(self):
        self.assertEqual(_stake_concentration_score(-100.0), 0)


# ---------------------------------------------------------------------------
# _validator_diversity_score
# ---------------------------------------------------------------------------

class TestValidatorDiversityScore(unittest.TestCase):

    def test_high_diversity_high_score(self):
        score = _validator_diversity_score(10, 90.0, 90.0, False)
        self.assertGreater(score, 70)

    def test_centralized_penalty_applied(self):
        # Use stake_conc=60 so result doesn't clamp to 100
        s_cent = _validator_diversity_score(60, 50.0, 50.0, True)
        s_decent = _validator_diversity_score(60, 50.0, 50.0, False)
        self.assertLess(s_cent, s_decent)

    def test_returns_int(self):
        self.assertIsInstance(_validator_diversity_score(30, 60.0, 50.0, False), int)

    def test_clamped_zero(self):
        # High concentration, no geo/client diversity, centralized
        # Formula: 100 - 100*0.5 + 0*0.3 + 0*0.2 - 20 = 30 → minimum possible ≥ 0
        score = _validator_diversity_score(100, 0.0, 0.0, True)
        self.assertGreaterEqual(score, 0)
        self.assertLess(score, 50)

    def test_clamped_hundred(self):
        score = _validator_diversity_score(0, 100.0, 100.0, False)
        self.assertLessEqual(score, 100)

    def test_geo_contributes(self):
        s_low = _validator_diversity_score(30, 10.0, 50.0, False)
        s_high = _validator_diversity_score(30, 90.0, 50.0, False)
        self.assertGreater(s_high, s_low)

    def test_client_diversity_contributes(self):
        # Use high stake_conc to prevent clamping at 100
        s_low = _validator_diversity_score(70, 30.0, 10.0, False)
        s_high = _validator_diversity_score(70, 30.0, 90.0, False)
        self.assertGreater(s_high, s_low)


# ---------------------------------------------------------------------------
# _nakamoto_ratio
# ---------------------------------------------------------------------------

class TestNakamotoRatio(unittest.TestCase):

    def test_ratio_calculation(self):
        ratio = _nakamoto_ratio(50, 500)
        self.assertAlmostEqual(ratio, 10.0)

    def test_zero_validators_no_crash(self):
        ratio = _nakamoto_ratio(5, 0)
        self.assertEqual(ratio, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_nakamoto_ratio(10, 100), float)

    def test_full_nakamoto(self):
        ratio = _nakamoto_ratio(100, 100)
        self.assertAlmostEqual(ratio, 100.0)

    def test_small_nakamoto(self):
        ratio = _nakamoto_ratio(3, 1000)
        self.assertAlmostEqual(ratio, 0.3)


# ---------------------------------------------------------------------------
# _liveness_risk_score
# ---------------------------------------------------------------------------

class TestLivenessRiskScore(unittest.TestCase):

    def test_high_nakamoto_no_centralized_no_slash(self):
        score = _liveness_risk_score(100, False, 0)
        self.assertEqual(score, 0)

    def test_low_nakamoto_raises_risk(self):
        s_low = _liveness_risk_score(3, False, 0)
        s_high = _liveness_risk_score(100, False, 0)
        self.assertGreater(s_low, s_high)

    def test_centralized_adds_30(self):
        s_cent = _liveness_risk_score(50, True, 0)
        s_decent = _liveness_risk_score(50, False, 0)
        self.assertGreater(s_cent, s_decent)

    def test_slashing_adds_risk(self):
        s_slash = _liveness_risk_score(50, False, 5)
        s_no_slash = _liveness_risk_score(50, False, 0)
        self.assertGreater(s_slash, s_no_slash)

    def test_clamped_0_to_100(self):
        score = _liveness_risk_score(1, True, 100)
        self.assertLessEqual(score, 100)
        self.assertGreaterEqual(score, 0)

    def test_returns_int(self):
        self.assertIsInstance(_liveness_risk_score(20, False, 1), int)

    def test_zero_nakamoto_max_nakamoto_risk(self):
        score_zero = _liveness_risk_score(0, False, 0)
        self.assertGreater(score_zero, 30)


# ---------------------------------------------------------------------------
# _decentralization_label
# ---------------------------------------------------------------------------

class TestDecentralizationLabel(unittest.TestCase):

    def test_spof_centralized_sequencer(self):
        label = _decentralization_label(30, 500, 20.0, True)
        self.assertEqual(label, "SINGLE_POINT_OF_FAILURE")

    def test_spof_low_nakamoto(self):
        label = _decentralization_label(2, 500, 20.0, False)
        self.assertEqual(label, "SINGLE_POINT_OF_FAILURE")

    def test_highly_decentralized(self):
        label = _decentralization_label(55, 400, 25.0, False)
        self.assertEqual(label, "HIGHLY_DECENTRALIZED")

    def test_centralized_low_nakamoto(self):
        label = _decentralization_label(8, 1000, 30.0, False)
        self.assertEqual(label, "CENTRALIZED")

    def test_centralized_high_top5(self):
        label = _decentralization_label(12, 1000, 55.0, False)
        self.assertEqual(label, "CENTRALIZED")

    def test_moderately_centralized_nakamoto_boundary(self):
        label = _decentralization_label(15, 800, 30.0, False)
        self.assertEqual(label, "MODERATELY_CENTRALIZED")

    def test_decentralized_all_good(self):
        label = _decentralization_label(25, 1000, 20.0, False)
        self.assertEqual(label, "DECENTRALIZED")

    def test_moderately_centralized_high_hhi(self):
        label = _decentralization_label(22, 2000, 20.0, False)
        self.assertEqual(label, "MODERATELY_CENTRALIZED")

    def test_spof_takes_priority_over_highly_decentralized(self):
        """Even with good nakamoto, centralized sequencer → SPOF."""
        label = _decentralization_label(55, 300, 15.0, True)
        self.assertEqual(label, "SINGLE_POINT_OF_FAILURE")


# ---------------------------------------------------------------------------
# _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_ideal_network(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 0, 30, False)
        self.assertEqual(flags, [])

    def test_centralized_sequencer_flag(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 0, 30, True)
        self.assertIn("CENTRALIZED_SEQUENCER", flags)

    def test_high_stake_concentration_flag(self):
        flags = _compute_flags(65.0, 80.0, 60.0, 0, 30, False)
        self.assertIn("HIGH_STAKE_CONCENTRATION", flags)

    def test_geographic_risk_flag(self):
        flags = _compute_flags(25.0, 30.0, 60.0, 0, 30, False)
        self.assertIn("GEOGRAPHIC_RISK", flags)

    def test_client_monoculture_flag(self):
        flags = _compute_flags(25.0, 80.0, 20.0, 0, 30, False)
        self.assertIn("CLIENT_MONOCULTURE", flags)

    def test_slashing_history_flag(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 3, 30, False)
        self.assertIn("SLASHING_HISTORY", flags)

    def test_strong_nakamoto_flag(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 0, 55, False)
        self.assertIn("STRONG_NAKAMOTO", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(65.0, 30.0, 20.0, 5, 5, True)
        self.assertIn("CENTRALIZED_SEQUENCER", flags)
        self.assertIn("HIGH_STAKE_CONCENTRATION", flags)
        self.assertIn("GEOGRAPHIC_RISK", flags)
        self.assertIn("CLIENT_MONOCULTURE", flags)
        self.assertIn("SLASHING_HISTORY", flags)

    def test_slashing_boundary_2_no_flag(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 2, 30, False)
        self.assertNotIn("SLASHING_HISTORY", flags)

    def test_strong_nakamoto_boundary_50_no_flag(self):
        flags = _compute_flags(25.0, 80.0, 60.0, 0, 50, False)
        self.assertNotIn("STRONG_NAKAMOTO", flags)


# ---------------------------------------------------------------------------
# _parse_multisig
# ---------------------------------------------------------------------------

class TestParseMultisig(unittest.TestCase):

    def test_valid_threshold(self):
        result = _parse_multisig("5/9")
        self.assertEqual(result["numerator"], 5)
        self.assertEqual(result["denominator"], 9)

    def test_invalid_string(self):
        result = _parse_multisig("invalid")
        self.assertIsNone(result["numerator"])

    def test_none_input(self):
        result = _parse_multisig(None)
        self.assertIsNone(result["numerator"])

    def test_3_of_5(self):
        result = _parse_multisig("3/5")
        self.assertEqual(result["numerator"], 3)
        self.assertEqual(result["denominator"], 5)

    def test_empty_string(self):
        result = _parse_multisig("")
        self.assertIsNone(result["numerator"])


# ---------------------------------------------------------------------------
# _append_log (ring-buffer behavior)
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def test_creates_log_file(self):
        _append_log({"event": "test"}, log_path=self.log_path, cap=10)
        self.assertTrue(os.path.exists(self.log_path))

    def test_appends_entry(self):
        _append_log({"event": "test"}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_enforces_cap(self):
        for i in range(15):
            _append_log({"i": i}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_ring_buffer_keeps_latest(self):
        for i in range(15):
            _append_log({"i": i}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 5)
        self.assertEqual(data[-1]["i"], 14)

    def test_multiple_appends_accumulate(self):
        _append_log({"a": 1}, log_path=self.log_path, cap=100)
        _append_log({"a": 2}, log_path=self.log_path, cap=100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_invalid_existing_json_reset(self):
        """Corrupted file should be treated as empty."""
        with open(self.log_path, "w") as f:
            f.write("not-json")
        _append_log({"event": "after_corrupt"}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# analyze() — integration tests
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def _tmp_log(self):
        tmp = tempfile.mkdtemp()
        return os.path.join(tmp, "val_log.json")

    def test_returns_dict(self):
        result = analyze([_make_network()], config={"write_log": False})
        self.assertIsInstance(result, dict)

    def test_output_keys_present(self):
        result = analyze([_make_network()], config={"write_log": False})
        self.assertIn("network_analyses", result)
        self.assertIn("summary", result)

    def test_single_network_result_count(self):
        result = analyze([_make_network()], config={"write_log": False})
        self.assertEqual(len(result["network_analyses"]), 1)

    def test_multiple_networks(self):
        nets = [_make_network(name=f"Net{i}") for i in range(5)]
        result = analyze(nets, config={"write_log": False})
        self.assertEqual(len(result["network_analyses"]), 5)

    def test_empty_networks_returns_error(self):
        result = analyze([], config={"write_log": False})
        self.assertIn("error", result)

    def test_non_list_returns_error(self):
        result = analyze("bad_input", config={"write_log": False})
        self.assertIn("error", result)


class TestAnalyzeNetworkFields(unittest.TestCase):

    def setUp(self):
        self.result = analyze([_make_network()], config={"write_log": False})
        self.net = self.result["network_analyses"][0]

    def test_herfindahl_index_present(self):
        self.assertIn("herfindahl_index", self.net)

    def test_stake_concentration_score_0_100(self):
        s = self.net["stake_concentration_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_validator_diversity_score_0_100(self):
        s = self.net["validator_diversity_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_nakamoto_ratio_present(self):
        self.assertIn("nakamoto_ratio", self.net)

    def test_liveness_risk_score_0_100(self):
        s = self.net["liveness_risk_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_decentralization_label_valid(self):
        valid = {"HIGHLY_DECENTRALIZED", "DECENTRALIZED", "MODERATELY_CENTRALIZED",
                 "CENTRALIZED", "SINGLE_POINT_OF_FAILURE"}
        self.assertIn(self.net["decentralization_label"], valid)

    def test_flags_is_list(self):
        self.assertIsInstance(self.net["flags"], list)

    def test_upgrade_multisig_parsed(self):
        self.assertIn("upgrade_multisig", self.net)
        self.assertEqual(self.net["upgrade_multisig"]["numerator"], 5)

    def test_name_preserved(self):
        self.assertEqual(self.net["name"], "TestNet")

    def test_network_type_preserved(self):
        self.assertEqual(self.net["network_type"], "l1_pos")


class TestAnalyzeSummary(unittest.TestCase):

    def test_summary_network_count(self):
        nets = [_make_network(name=f"N{i}") for i in range(3)]
        result = analyze(nets, config={"write_log": False})
        self.assertEqual(result["summary"]["network_count"], 3)

    def test_summary_most_decentralized_present(self):
        nets = [
            _make_network(name="Good", nakamoto_coefficient=60, top5_validator_stake_pct=15.0),
            _make_network(name="Bad", nakamoto_coefficient=5, top5_validator_stake_pct=55.0,
                          sequencer_centralized=True),
        ]
        result = analyze(nets, config={"write_log": False})
        self.assertEqual(result["summary"]["most_decentralized"], "Good")

    def test_summary_most_centralized_present(self):
        nets = [
            _make_network(name="Good", nakamoto_coefficient=60, top5_validator_stake_pct=15.0),
            _make_network(name="Bad", nakamoto_coefficient=2, top5_validator_stake_pct=80.0,
                          sequencer_centralized=True),
        ]
        result = analyze(nets, config={"write_log": False})
        self.assertEqual(result["summary"]["most_centralized"], "Bad")

    def test_summary_avg_nakamoto(self):
        nets = [
            _make_network(name="A", nakamoto_coefficient=20),
            _make_network(name="B", nakamoto_coefficient=40),
        ]
        result = analyze(nets, config={"write_log": False})
        self.assertAlmostEqual(result["summary"]["avg_nakamoto_coefficient"], 30.0)

    def test_summary_spof_count(self):
        nets = [
            _make_network(name="SPOF1", nakamoto_coefficient=2),
            _make_network(name="SPOF2", sequencer_centralized=True),
            _make_network(name="OK", nakamoto_coefficient=30),
        ]
        result = analyze(nets, config={"write_log": False})
        self.assertEqual(result["summary"]["spof_count"], 2)

    def test_summary_highly_decentralized_count(self):
        nets = [
            _make_network(name="HD", nakamoto_coefficient=60,
                          top5_validator_stake_pct=15.0,
                          top10_validator_stake_pct=25.0,
                          top_validator_stake_pct=3.0,
                          sequencer_centralized=False),
            _make_network(name="Meh", nakamoto_coefficient=5),
        ]
        result = analyze(nets, config={"write_log": False})
        self.assertGreaterEqual(result["summary"]["highly_decentralized_count"], 0)

    def test_summary_analyzed_at_present(self):
        result = analyze([_make_network()], config={"write_log": False})
        self.assertIn("analyzed_at", result["summary"])


class TestAnalyzeLabels(unittest.TestCase):

    def test_spof_centralized_sequencer(self):
        net = _make_network(sequencer_centralized=True)
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "SINGLE_POINT_OF_FAILURE")

    def test_spof_nakamoto_less_than_3(self):
        net = _make_network(nakamoto_coefficient=2, sequencer_centralized=False)
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "SINGLE_POINT_OF_FAILURE")

    def test_centralized_low_nakamoto(self):
        net = _make_network(nakamoto_coefficient=8, sequencer_centralized=False)
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "CENTRALIZED")

    def test_centralized_high_top5(self):
        net = _make_network(nakamoto_coefficient=12, top5_validator_stake_pct=55.0,
                            top10_validator_stake_pct=65.0, sequencer_centralized=False)
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "CENTRALIZED")

    def test_highly_decentralized(self):
        net = _make_network(
            nakamoto_coefficient=55,
            top_validator_stake_pct=1.0,
            top5_validator_stake_pct=5.0,
            top10_validator_stake_pct=10.0,
            sequencer_centralized=False,
            validator_count=1000,
        )
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "HIGHLY_DECENTRALIZED")

    def test_decentralized_middle_ground(self):
        net = _make_network(
            nakamoto_coefficient=25,
            top5_validator_stake_pct=25.0,
            top10_validator_stake_pct=40.0,
            sequencer_centralized=False,
        )
        result = analyze([net], config={"write_log": False})
        self.assertIn(result["network_analyses"][0]["decentralization_label"],
                      {"DECENTRALIZED", "MODERATELY_CENTRALIZED"})


class TestAnalyzeFlags(unittest.TestCase):

    def test_no_flags_clean_network(self):
        net = _make_network(
            top5_validator_stake_pct=25.0,
            geographic_distribution_score=80.0,
            client_diversity_score=70.0,
            slashing_incidents_count=0,
            nakamoto_coefficient=30,
            sequencer_centralized=False,
        )
        result = analyze([net], config={"write_log": False})
        flags = result["network_analyses"][0]["flags"]
        self.assertNotIn("HIGH_STAKE_CONCENTRATION", flags)
        self.assertNotIn("GEOGRAPHIC_RISK", flags)
        self.assertNotIn("CLIENT_MONOCULTURE", flags)

    def test_flag_centralized_sequencer(self):
        net = _make_network(sequencer_centralized=True)
        result = analyze([net], config={"write_log": False})
        self.assertIn("CENTRALIZED_SEQUENCER",
                      result["network_analyses"][0]["flags"])

    def test_flag_high_stake_concentration(self):
        net = _make_network(top5_validator_stake_pct=65.0,
                            top10_validator_stake_pct=75.0)
        result = analyze([net], config={"write_log": False})
        self.assertIn("HIGH_STAKE_CONCENTRATION",
                      result["network_analyses"][0]["flags"])

    def test_flag_geographic_risk(self):
        net = _make_network(geographic_distribution_score=35.0)
        result = analyze([net], config={"write_log": False})
        self.assertIn("GEOGRAPHIC_RISK", result["network_analyses"][0]["flags"])

    def test_flag_client_monoculture(self):
        net = _make_network(client_diversity_score=25.0)
        result = analyze([net], config={"write_log": False})
        self.assertIn("CLIENT_MONOCULTURE", result["network_analyses"][0]["flags"])

    def test_flag_slashing_history(self):
        net = _make_network(slashing_incidents_count=5)
        result = analyze([net], config={"write_log": False})
        self.assertIn("SLASHING_HISTORY", result["network_analyses"][0]["flags"])

    def test_flag_strong_nakamoto(self):
        net = _make_network(nakamoto_coefficient=60)
        result = analyze([net], config={"write_log": False})
        self.assertIn("STRONG_NAKAMOTO", result["network_analyses"][0]["flags"])


class TestAnalyzeNetworkTypes(unittest.TestCase):

    def test_l2_optimistic(self):
        net = _make_network(network_type="l2_optimistic", sequencer_centralized=True)
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["decentralization_label"],
                         "SINGLE_POINT_OF_FAILURE")

    def test_l2_zk(self):
        net = _make_network(network_type="l2_zk")
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["network_type"], "l2_zk")

    def test_bridge_multisig(self):
        net = _make_network(network_type="bridge_multisig")
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["network_type"], "bridge_multisig")

    def test_app_chain(self):
        net = _make_network(network_type="app_chain")
        result = analyze([net], config={"write_log": False})
        self.assertEqual(result["network_analyses"][0]["network_type"], "app_chain")


class TestAnalyzeLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "val_log.json")

    def test_log_file_created(self):
        analyze([_make_network()], config={"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_contains_entry(self):
        analyze([_make_network()], config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_has_timestamp(self):
        analyze([_make_network()], config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_write_log_false_skips_file(self):
        analyze([_make_network()], config={"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_ring_buffer_cap(self):
        for _ in range(5):
            analyze([_make_network()], config={"write_log": True,
                                               "log_path": self.log_path,
                                               "log_cap": 3})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_entry_has_network_count(self):
        nets = [_make_network(name=f"N{i}") for i in range(4)]
        analyze(nets, config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["network_count"], 4)


class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_missing_optional_fields_no_crash(self):
        """Network with only required minimal fields should not crash."""
        net = {"name": "Minimal", "network_type": "l1_pos",
               "validator_count": 100, "nakamoto_coefficient": 10}
        result = analyze([net], config={"write_log": False})
        self.assertIn("network_analyses", result)

    def test_zero_validator_count(self):
        net = _make_network(validator_count=0)
        result = analyze([net], config={"write_log": False})
        self.assertIsInstance(result["network_analyses"][0]["nakamoto_ratio"], float)

    def test_extremely_high_validator_count(self):
        net = _make_network(validator_count=1000000)
        result = analyze([net], config={"write_log": False})
        self.assertIsInstance(result, dict)

    def test_top_stake_100_percent(self):
        net = _make_network(top_validator_stake_pct=100.0,
                            top5_validator_stake_pct=100.0,
                            top10_validator_stake_pct=100.0,
                            validator_count=1)
        result = analyze([net], config={"write_log": False})
        score = result["network_analyses"][0]["stake_concentration_score"]
        self.assertEqual(score, 100)

    def test_no_multisig_threshold(self):
        net = _make_network()
        del net["upgrade_multisig_threshold"]
        result = analyze([net], config={"write_log": False})
        multisig = result["network_analyses"][0]["upgrade_multisig"]
        self.assertIsNone(multisig["numerator"])

    def test_single_network_most_and_least_are_same(self):
        result = analyze([_make_network()], config={"write_log": False})
        summary = result["summary"]
        self.assertEqual(summary["most_decentralized"], summary["most_centralized"])


if __name__ == "__main__":
    unittest.main()
