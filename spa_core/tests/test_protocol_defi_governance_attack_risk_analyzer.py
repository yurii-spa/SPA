#!/usr/bin/env python3
"""
Tests for MP-1059: ProtocolDeFiGovernanceAttackRiskAnalyzer
Uses unittest only (no pytest). ≥90 tests.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_governance_attack_risk_analyzer
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_governance_attack_risk_analyzer import (
    ProtocolDeFiGovernanceAttackRiskAnalyzer,
    RING_BUFFER_CAP,
    attack_risk_label,
    compute_attack_cost_vs_tvl,
    compute_decentralization_score,
    compute_governance_capture_score,
    parse_multisig_threshold,
    _atomic_write_json,
    _load_json_list,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(**overrides):
    """Return valid base params with optional overrides."""
    base = {
        "protocol_name": "Compound",
        "governance_token_market_cap_usd": 500_000_000.0,
        "tvl_usd": 2_000_000_000.0,
        "token_concentration_top10_pct": 45.0,
        "timelock_hours": 48.0,
        "quorum_pct": 4.0,
        "voter_participation_pct": 8.0,
        "has_guardian": False,
        "multisig_threshold": "4/7",
        "days_since_last_proposal": 14.0,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. compute_attack_cost_vs_tvl
# ===========================================================================

class TestComputeAttackCostVsTvl(unittest.TestCase):
    def test_basic(self):
        # 500M * 0.51 / 2B = 0.1275
        result = compute_attack_cost_vs_tvl(500_000_000, 2_000_000_000)
        self.assertAlmostEqual(result, 0.1275, places=6)

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(compute_attack_cost_vs_tvl(500_000_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(compute_attack_cost_vs_tvl(500_000_000, -1), 0.0)

    def test_equal_market_cap_and_tvl(self):
        # 100M * 0.51 / 100M = 0.51
        result = compute_attack_cost_vs_tvl(100_000_000, 100_000_000)
        self.assertAlmostEqual(result, 0.51, places=6)

    def test_large_cap_small_tvl(self):
        # attack cost > TVL → ratio > 1
        result = compute_attack_cost_vs_tvl(10_000_000_000, 1_000_000_000)
        self.assertGreater(result, 1.0)

    def test_small_cap_large_tvl(self):
        result = compute_attack_cost_vs_tvl(1_000_000, 1_000_000_000)
        self.assertLess(result, 0.001)

    def test_zero_market_cap(self):
        result = compute_attack_cost_vs_tvl(0, 1_000_000)
        self.assertAlmostEqual(result, 0.0)

    def test_51_pct_multiplier(self):
        # Explicit: attack_cost = cap * 0.51
        cap = 200_000_000
        tvl = 400_000_000
        expected = (cap * 0.51) / tvl
        self.assertAlmostEqual(compute_attack_cost_vs_tvl(cap, tvl), expected, places=8)


# ===========================================================================
# 2. parse_multisig_threshold
# ===========================================================================

class TestParseMultisigThreshold(unittest.TestCase):
    def test_basic_4_of_7(self):
        self.assertEqual(parse_multisig_threshold("4/7"), (4, 7))

    def test_3_of_5(self):
        self.assertEqual(parse_multisig_threshold("3/5"), (3, 5))

    def test_2_of_3(self):
        self.assertEqual(parse_multisig_threshold("2/3"), (2, 3))

    def test_1_of_1(self):
        self.assertEqual(parse_multisig_threshold("1/1"), (1, 1))

    def test_invalid_string_returns_default(self):
        self.assertEqual(parse_multisig_threshold("none"), (0, 1))

    def test_empty_string_returns_default(self):
        self.assertEqual(parse_multisig_threshold(""), (0, 1))

    def test_zero_denominator_returns_default(self):
        self.assertEqual(parse_multisig_threshold("3/0"), (0, 1))

    def test_with_spaces(self):
        m, n = parse_multisig_threshold(" 4 / 7 ")
        self.assertEqual(m, 4)
        self.assertEqual(n, 7)

    def test_single_number_returns_default(self):
        self.assertEqual(parse_multisig_threshold("5"), (0, 1))


# ===========================================================================
# 3. compute_governance_capture_score
# ===========================================================================

class TestComputeGovernanceCaptureScore(unittest.TestCase):
    def _score(self, **kw):
        defaults = dict(
            token_concentration_top10_pct=45.0,
            timelock_hours=48.0,
            quorum_pct=4.0,
            voter_participation_pct=8.0,
            has_guardian=False,
        )
        defaults.update(kw)
        return compute_governance_capture_score(**defaults)

    def test_result_in_range(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_perfect_safety_gives_low_score(self):
        # 0% concentration, very long timelock, high quorum, high participation, with guardian
        s = self._score(
            token_concentration_top10_pct=0.0,
            timelock_hours=10000.0,
            quorum_pct=100.0,
            voter_participation_pct=100.0,
            has_guardian=True,
        )
        self.assertAlmostEqual(s, 0.0, places=3)

    def test_max_risk_gives_high_score(self):
        # 100% concentration, 0h timelock, 0% quorum, 0% participation, no guardian
        s = self._score(
            token_concentration_top10_pct=100.0,
            timelock_hours=0.0,
            quorum_pct=0.0,
            voter_participation_pct=0.0,
            has_guardian=False,
        )
        self.assertAlmostEqual(s, 100.0, places=3)

    def test_guardian_reduces_score(self):
        s_no_guardian = self._score(has_guardian=False)
        s_guardian = self._score(has_guardian=True)
        self.assertGreater(s_no_guardian, s_guardian)

    def test_high_concentration_increases_score(self):
        s_low = self._score(token_concentration_top10_pct=10.0)
        s_high = self._score(token_concentration_top10_pct=90.0)
        self.assertGreater(s_high, s_low)

    def test_longer_timelock_decreases_score(self):
        s_short = self._score(timelock_hours=0.0)
        s_long = self._score(timelock_hours=168.0)
        self.assertGreater(s_short, s_long)

    def test_higher_quorum_decreases_score(self):
        s_low = self._score(quorum_pct=0.0)
        s_high = self._score(quorum_pct=50.0)
        self.assertGreater(s_low, s_high)

    def test_higher_participation_decreases_score(self):
        s_low = self._score(voter_participation_pct=0.0)
        s_high = self._score(voter_participation_pct=50.0)
        self.assertGreater(s_low, s_high)

    def test_score_clamped_to_100(self):
        s = self._score(
            token_concentration_top10_pct=200.0,
            timelock_hours=-1.0,
            quorum_pct=-1.0,
            voter_participation_pct=-1.0,
            has_guardian=False,
        )
        self.assertLessEqual(s, 100.0)

    def test_score_clamped_to_0(self):
        s = self._score(
            token_concentration_top10_pct=0.0,
            timelock_hours=999.0,
            quorum_pct=999.0,
            voter_participation_pct=999.0,
            has_guardian=True,
        )
        self.assertGreaterEqual(s, 0.0)

    def test_timelock_168h_gives_zero_timelock_factor(self):
        # timelock_factor = max(0, 1 - 168/168) = 0
        s_with = self._score(timelock_hours=168.0, has_guardian=True,
                             token_concentration_top10_pct=0.0,
                             quorum_pct=100.0, voter_participation_pct=100.0)
        self.assertAlmostEqual(s_with, 0.0, places=3)


# ===========================================================================
# 4. compute_decentralization_score
# ===========================================================================

class TestComputeDecentralizationScore(unittest.TestCase):
    def _score(self, **kw):
        defaults = dict(
            attack_cost_vs_tvl=0.1275,
            multisig_threshold="4/7",
            timelock_hours=48.0,
            days_since_last_proposal=14.0,
        )
        defaults.update(kw)
        return compute_decentralization_score(**defaults)

    def test_result_in_range(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_high_attack_ratio_increases_score(self):
        s_low = self._score(attack_cost_vs_tvl=0.1)
        s_high = self._score(attack_cost_vs_tvl=2.0)
        self.assertGreater(s_high, s_low)

    def test_stronger_multisig_increases_score(self):
        s_weak = self._score(multisig_threshold="1/3")
        s_strong = self._score(multisig_threshold="3/3")
        self.assertGreater(s_strong, s_weak)

    def test_longer_timelock_increases_score(self):
        s_short = self._score(timelock_hours=0.0)
        s_long = self._score(timelock_hours=168.0)
        self.assertGreater(s_long, s_short)

    def test_stale_governance_increases_score(self):
        s_fresh = self._score(days_since_last_proposal=0.0)
        s_stale = self._score(days_since_last_proposal=30.0)
        self.assertGreater(s_stale, s_fresh)

    def test_zero_attack_ratio_zero_cost_score(self):
        s = self._score(attack_cost_vs_tvl=0.0)
        self.assertGreaterEqual(s, 0.0)

    def test_invalid_multisig_gives_zero_multisig_score(self):
        s_invalid = self._score(multisig_threshold="none")
        s_valid = self._score(multisig_threshold="3/5")
        self.assertGreater(s_valid, s_invalid)

    def test_score_clamped_to_100(self):
        s = self._score(
            attack_cost_vs_tvl=100.0, multisig_threshold="5/5",
            timelock_hours=10000.0, days_since_last_proposal=1000.0,
        )
        self.assertLessEqual(s, 100.0)

    def test_score_clamped_to_0(self):
        s = self._score(
            attack_cost_vs_tvl=0.0, multisig_threshold="0/1",
            timelock_hours=0.0, days_since_last_proposal=0.0,
        )
        self.assertGreaterEqual(s, 0.0)

    def test_attack_ratio_capped_at_1_for_cost_score(self):
        s_1 = self._score(attack_cost_vs_tvl=1.0)
        s_2 = self._score(attack_cost_vs_tvl=2.0)
        # Both should give same cost_ratio_score component (capped at 1.0)
        self.assertAlmostEqual(s_1, s_2, places=3)


# ===========================================================================
# 5. attack_risk_label
# ===========================================================================

class TestAttackRiskLabel(unittest.TestCase):
    def test_fortress_at_0(self):
        self.assertEqual(attack_risk_label(0.0), "GOVERNANCE_FORTRESS")

    def test_fortress_just_below_20(self):
        self.assertEqual(attack_risk_label(19.9), "GOVERNANCE_FORTRESS")

    def test_well_protected_at_20(self):
        self.assertEqual(attack_risk_label(20.0), "WELL_PROTECTED")

    def test_well_protected_at_30(self):
        self.assertEqual(attack_risk_label(30.0), "WELL_PROTECTED")

    def test_well_protected_just_below_40(self):
        self.assertEqual(attack_risk_label(39.9), "WELL_PROTECTED")

    def test_moderate_risk_at_40(self):
        self.assertEqual(attack_risk_label(40.0), "MODERATE_RISK")

    def test_moderate_risk_at_50(self):
        self.assertEqual(attack_risk_label(50.0), "MODERATE_RISK")

    def test_moderate_risk_just_below_60(self):
        self.assertEqual(attack_risk_label(59.9), "MODERATE_RISK")

    def test_high_capture_risk_at_60(self):
        self.assertEqual(attack_risk_label(60.0), "HIGH_CAPTURE_RISK")

    def test_high_capture_risk_at_70(self):
        self.assertEqual(attack_risk_label(70.0), "HIGH_CAPTURE_RISK")

    def test_high_capture_risk_just_below_80(self):
        self.assertEqual(attack_risk_label(79.9), "HIGH_CAPTURE_RISK")

    def test_critical_vulnerability_at_80(self):
        self.assertEqual(attack_risk_label(80.0), "CRITICAL_VULNERABILITY")

    def test_critical_vulnerability_at_100(self):
        self.assertEqual(attack_risk_label(100.0), "CRITICAL_VULNERABILITY")

    def test_critical_vulnerability_above_100(self):
        self.assertEqual(attack_risk_label(150.0), "CRITICAL_VULNERABILITY")


# ===========================================================================
# 6. ProtocolDeFiGovernanceAttackRiskAnalyzer.analyze()
# ===========================================================================

class TestAnalyzerAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiGovernanceAttackRiskAnalyzer(data_dir=Path(self.tmp))

    # --- output keys present ---
    def test_result_has_attack_cost_vs_tvl_ratio(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("attack_cost_vs_tvl_ratio", r)

    def test_result_has_governance_capture_score(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("governance_capture_score", r)

    def test_result_has_decentralization_score(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("decentralization_score", r)

    def test_result_has_attack_risk_label(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("attack_risk_label", r)

    def test_result_has_schema_version(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["schema_version"], 1)

    def test_result_has_mp_tag(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["mp_tag"], "MP-1059")

    def test_result_has_timestamp(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("timestamp", r)

    def test_result_has_protocol_name(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["protocol_name"], "Compound")

    def test_result_has_source(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["source"], "protocol_defi_governance_attack_risk_analyzer")

    # --- value correctness ---
    def test_attack_cost_ratio_value(self):
        r = self.analyzer.analyze(_make_params(
            governance_token_market_cap_usd=500_000_000,
            tvl_usd=2_000_000_000,
        ))
        self.assertAlmostEqual(r["attack_cost_vs_tvl_ratio"], 0.1275, places=4)

    def test_attack_cost_zero_tvl(self):
        r = self.analyzer.analyze(_make_params(tvl_usd=0.0))
        self.assertAlmostEqual(r["attack_cost_vs_tvl_ratio"], 0.0, places=6)

    def test_capture_score_in_range(self):
        r = self.analyzer.analyze(_make_params())
        self.assertGreaterEqual(r["governance_capture_score"], 0.0)
        self.assertLessEqual(r["governance_capture_score"], 100.0)

    def test_decentralization_score_in_range(self):
        r = self.analyzer.analyze(_make_params())
        self.assertGreaterEqual(r["decentralization_score"], 0.0)
        self.assertLessEqual(r["decentralization_score"], 100.0)

    def test_label_is_valid(self):
        valid = {"GOVERNANCE_FORTRESS", "WELL_PROTECTED", "MODERATE_RISK",
                 "HIGH_CAPTURE_RISK", "CRITICAL_VULNERABILITY"}
        r = self.analyzer.analyze(_make_params())
        self.assertIn(r["attack_risk_label"], valid)

    def test_guardian_lowers_capture_score(self):
        r_no = self.analyzer.analyze(_make_params(has_guardian=False))
        r_yes = self.analyzer.analyze(_make_params(has_guardian=True))
        self.assertGreater(r_no["governance_capture_score"], r_yes["governance_capture_score"])

    def test_high_concentration_increases_capture_score(self):
        r_low = self.analyzer.analyze(_make_params(token_concentration_top10_pct=5.0))
        r_high = self.analyzer.analyze(_make_params(token_concentration_top10_pct=95.0))
        self.assertGreater(r_high["governance_capture_score"], r_low["governance_capture_score"])

    def test_label_consistent_with_score(self):
        r = self.analyzer.analyze(_make_params())
        derived_label = attack_risk_label(r["governance_capture_score"])
        self.assertEqual(r["attack_risk_label"], derived_label)

    def test_no_file_written_by_analyze(self):
        log_path = Path(self.tmp) / "governance_attack_risk_log.json"
        self.analyzer.analyze(_make_params())
        self.assertFalse(log_path.exists())

    # --- validation errors ---
    def test_missing_protocol_name_raises(self):
        params = _make_params()
        del params["protocol_name"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_tvl_raises(self):
        params = _make_params()
        del params["tvl_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_market_cap_raises(self):
        params = _make_params()
        del params["governance_token_market_cap_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_concentration_raises(self):
        params = _make_params()
        del params["token_concentration_top10_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_timelock_raises(self):
        params = _make_params()
        del params["timelock_hours"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_quorum_raises(self):
        params = _make_params()
        del params["quorum_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_participation_raises(self):
        params = _make_params()
        del params["voter_participation_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_has_guardian_raises(self):
        params = _make_params()
        del params["has_guardian"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_multisig_raises(self):
        params = _make_params()
        del params["multisig_threshold"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_days_since_proposal_raises(self):
        params = _make_params()
        del params["days_since_last_proposal"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_string_numbers_coerced(self):
        r = self.analyzer.analyze(_make_params(
            governance_token_market_cap_usd="500000000",
            tvl_usd="2000000000",
        ))
        self.assertAlmostEqual(r["attack_cost_vs_tvl_ratio"], 0.1275, places=4)


# ===========================================================================
# 7. ProtocolDeFiGovernanceAttackRiskAnalyzer.analyze_and_save()
# ===========================================================================

class TestAnalyzerAnalyzeAndSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiGovernanceAttackRiskAnalyzer(data_dir=Path(self.tmp))
        self.log_path = Path(self.tmp) / "governance_attack_risk_log.json"

    def test_file_created(self):
        self.analyzer.analyze_and_save(_make_params())
        self.assertTrue(self.log_path.exists())

    def test_file_is_valid_json(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_file_has_one_entry_after_one_call(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_file_accumulates_entries(self):
        for _ in range(5):
            self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_result_has_saved_to_key(self):
        r = self.analyzer.analyze_and_save(_make_params())
        self.assertIn("saved_to", r)

    def test_saved_to_points_to_log(self):
        r = self.analyzer.analyze_and_save(_make_params())
        self.assertIn("governance_attack_risk_log.json", r["saved_to"])

    def test_ring_buffer_caps_at_100(self):
        for _ in range(RING_BUFFER_CAP + 10):
            self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_oldest_entries_dropped_in_ring_buffer(self):
        for i in range(RING_BUFFER_CAP + 5):
            self.analyzer.analyze_and_save(_make_params(protocol_name=f"Proto-{i}"))
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertNotEqual(data[0]["protocol_name"], "Proto-0")

    def test_entry_contains_attack_risk_label(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("attack_risk_label", data[0])

    def test_entry_contains_governance_capture_score(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("governance_capture_score", data[0])

    def test_different_protocols_saved(self):
        for proto in ["Aave", "MakerDAO", "Uniswap"]:
            self.analyzer.analyze_and_save(_make_params(protocol_name=proto))
        with open(self.log_path) as fh:
            data = json.load(fh)
        names = [e["protocol_name"] for e in data]
        self.assertIn("MakerDAO", names)
        self.assertIn("Uniswap", names)


# ===========================================================================
# 8. _load_json_list / _atomic_write_json
# ===========================================================================

class TestJsonHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_load_missing_file_returns_empty(self):
        p = Path(self.tmp) / "nonexistent.json"
        self.assertEqual(_load_json_list(p), [])

    def test_load_invalid_json_returns_empty(self):
        p = Path(self.tmp) / "bad.json"
        p.write_text("not-json")
        self.assertEqual(_load_json_list(p), [])

    def test_load_valid_list(self):
        p = Path(self.tmp) / "good.json"
        p.write_text(json.dumps([{"a": 1}, {"b": 2}]))
        result = _load_json_list(p)
        self.assertEqual(len(result), 2)

    def test_load_non_list_returns_empty(self):
        p = Path(self.tmp) / "obj.json"
        p.write_text(json.dumps({"key": "val"}))
        self.assertEqual(_load_json_list(p), [])

    def test_atomic_write_creates_file(self):
        p = Path(self.tmp) / "out.json"
        _atomic_write_json(p, [{"x": 1}])
        self.assertTrue(p.exists())

    def test_atomic_write_content_correct(self):
        p = Path(self.tmp) / "out.json"
        data = [{"protocol": "Test", "score": 42}]
        _atomic_write_json(p, data)
        with open(p) as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, data)

    def test_atomic_write_creates_parent_dir(self):
        p = Path(self.tmp) / "subdir" / "deep" / "out.json"
        _atomic_write_json(p, [])
        self.assertTrue(p.exists())

    def test_load_then_write_round_trip(self):
        p = Path(self.tmp) / "rt.json"
        original = [{"attack_risk_label": "MODERATE_RISK"}, {"k": 2}]
        _atomic_write_json(p, original)
        loaded = _load_json_list(p)
        self.assertEqual(loaded, original)


# ===========================================================================
# 9. Edge / boundary / integration scenarios
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiGovernanceAttackRiskAnalyzer(data_dir=Path(self.tmp))

    def test_fortress_scenario(self):
        # Very safe: 0% concentration, long timelock, high quorum, high participation, guardian
        r = self.analyzer.analyze(_make_params(
            token_concentration_top10_pct=0.0,
            timelock_hours=336.0,
            quorum_pct=80.0,
            voter_participation_pct=60.0,
            has_guardian=True,
        ))
        self.assertEqual(r["attack_risk_label"], "GOVERNANCE_FORTRESS")

    def test_critical_vulnerability_scenario(self):
        # Very unsafe: 100% concentration, 0h timelock, 0% quorum, 0% participation, no guardian
        r = self.analyzer.analyze(_make_params(
            token_concentration_top10_pct=100.0,
            timelock_hours=0.0,
            quorum_pct=0.0,
            voter_participation_pct=0.0,
            has_guardian=False,
        ))
        self.assertEqual(r["attack_risk_label"], "CRITICAL_VULNERABILITY")

    def test_all_required_outputs_present(self):
        r = self.analyzer.analyze(_make_params())
        for key in ["attack_cost_vs_tvl_ratio", "governance_capture_score",
                    "decentralization_score", "attack_risk_label"]:
            self.assertIn(key, r)

    def test_multiple_protocols_accumulate_in_log(self):
        for proto in ["Aave", "Compound", "MakerDAO"]:
            self.analyzer.analyze_and_save(_make_params(protocol_name=proto))
        log_path = Path(self.tmp) / "governance_attack_risk_log.json"
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_data_dir_created_on_save(self):
        new_dir = Path(self.tmp) / "new" / "subdir"
        analyzer = ProtocolDeFiGovernanceAttackRiskAnalyzer(data_dir=new_dir)
        analyzer.analyze_and_save(_make_params())
        self.assertTrue((new_dir / "governance_attack_risk_log.json").exists())

    def test_label_in_valid_set_across_scenarios(self):
        valid = {"GOVERNANCE_FORTRESS", "WELL_PROTECTED", "MODERATE_RISK",
                 "HIGH_CAPTURE_RISK", "CRITICAL_VULNERABILITY"}
        for conc in [0, 25, 50, 75, 100]:
            r = self.analyzer.analyze(_make_params(token_concentration_top10_pct=float(conc)))
            self.assertIn(r["attack_risk_label"], valid)

    def test_makerdao_scenario(self):
        r = self.analyzer.analyze({
            "protocol_name": "MakerDAO",
            "governance_token_market_cap_usd": 1_200_000_000.0,
            "tvl_usd": 8_000_000_000.0,
            "token_concentration_top10_pct": 52.0,
            "timelock_hours": 12.0,
            "quorum_pct": 3.0,
            "voter_participation_pct": 5.0,
            "has_guardian": False,
            "multisig_threshold": "5/9",
            "days_since_last_proposal": 3.0,
        })
        # attack_cost = 1.2B * 0.51 / 8B = 0.0765
        self.assertAlmostEqual(r["attack_cost_vs_tvl_ratio"], 0.0765, places=4)
        self.assertIn(r["attack_risk_label"], valid_labels())

    def test_uniswap_scenario(self):
        r = self.analyzer.analyze({
            "protocol_name": "Uniswap",
            "governance_token_market_cap_usd": 5_000_000_000.0,
            "tvl_usd": 6_000_000_000.0,
            "token_concentration_top10_pct": 40.0,
            "timelock_hours": 48.0,
            "quorum_pct": 4.0,
            "voter_participation_pct": 6.0,
            "has_guardian": False,
            "multisig_threshold": "4/7",
            "days_since_last_proposal": 7.0,
        })
        self.assertGreater(r["attack_cost_vs_tvl_ratio"], 0.4)

    def test_aave_guardian_scenario(self):
        r = self.analyzer.analyze(_make_params(
            protocol_name="Aave V3",
            has_guardian=True,
            timelock_hours=24.0,
        ))
        r_no_guardian = self.analyzer.analyze(_make_params(
            protocol_name="Aave V3",
            has_guardian=False,
            timelock_hours=24.0,
        ))
        self.assertLess(
            r["governance_capture_score"],
            r_no_guardian["governance_capture_score"]
        )

    def test_decentralization_increases_with_high_attack_ratio(self):
        r_cheap = self.analyzer.analyze(_make_params(
            governance_token_market_cap_usd=1_000_000,
            tvl_usd=1_000_000_000,
        ))
        r_expensive = self.analyzer.analyze(_make_params(
            governance_token_market_cap_usd=100_000_000_000,
            tvl_usd=1_000_000_000,
        ))
        self.assertGreater(
            r_expensive["decentralization_score"],
            r_cheap["decentralization_score"],
        )

    def test_stored_params_in_output(self):
        r = self.analyzer.analyze(_make_params(protocol_name="TestProto", timelock_hours=72.0))
        self.assertEqual(r["protocol_name"], "TestProto")
        self.assertEqual(r["timelock_hours"], 72.0)

    def test_independent_calls_no_state_bleed(self):
        r1 = self.analyzer.analyze(_make_params(protocol_name="P1", tvl_usd=1e9))
        r2 = self.analyzer.analyze(_make_params(protocol_name="P2", tvl_usd=5e9))
        self.assertEqual(r1["protocol_name"], "P1")
        self.assertEqual(r2["protocol_name"], "P2")
        self.assertNotEqual(r1["attack_cost_vs_tvl_ratio"], r2["attack_cost_vs_tvl_ratio"])


def valid_labels():
    return {"GOVERNANCE_FORTRESS", "WELL_PROTECTED", "MODERATE_RISK",
            "HIGH_CAPTURE_RISK", "CRITICAL_VULNERABILITY"}


if __name__ == "__main__":
    unittest.main()
