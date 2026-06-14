"""
Tests for MP-1128: DeFiProtocolStakingPenaltyRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_staking_penalty_risk_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from spa_core.analytics.defi_protocol_staking_penalty_risk_analyzer import (
    DeFiProtocolStakingPenaltyRiskAnalyzer,
    _clamp,
    _compute_expected_annual_loss_pct,
    _compute_expected_annual_loss_usd,
    _compute_net_staking_apy_pct,
    _compute_probability_component,
    _compute_penalty_component,
    _compute_audit_reduction,
    _compute_diversity_reduction,
    _compute_staking_type_modifier,
    _compute_slash_risk_score,
    _compute_risk_label,
    _atomic_append_log,
    _LOG_CAP,
    _PROB_SATURATION_PCT,
    _PROB_MAX_SCORE,
    _PENALTY_SATURATION_PCT,
    _PENALTY_MAX_SCORE,
    _AUDIT_REDUCTION,
    _DIVERSITY_MAX_REDUCTION,
    _STAKING_TYPE_MODIFIERS,
)


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------

def make_data(**overrides):
    """Return a baseline valid input dict."""
    base = {
        "protocol_name": "Lido",
        "staking_type": "eth_liquid_staking",
        "slash_probability_annual_pct": 0.01,
        "slash_penalty_pct": 1.0,
        "staking_apy_pct": 3.8,
        "position_size_usd": 100_000.0,
        "protocol_audited": True,
        "client_diversity_score": 7,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_below_lo_default(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_above_hi_default(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_inside_range(self):
        self.assertAlmostEqual(_clamp(55.5), 55.5)

    def test_custom_bounds_inside(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_custom_bounds_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_custom_bounds_above(self):
        self.assertEqual(_clamp(11.0, 0.0, 10.0), 10.0)


# ---------------------------------------------------------------------------
# 2. _compute_expected_annual_loss_pct
# ---------------------------------------------------------------------------

class TestExpectedAnnualLossPct(unittest.TestCase):
    def test_zero_probability(self):
        self.assertAlmostEqual(
            _compute_expected_annual_loss_pct(0.0, 1.0), 0.0
        )

    def test_zero_penalty(self):
        self.assertAlmostEqual(
            _compute_expected_annual_loss_pct(0.01, 0.0), 0.0
        )

    def test_baseline_case(self):
        # 0.01% prob * 1.0% penalty / 100 = 0.0001%
        result = _compute_expected_annual_loss_pct(0.01, 1.0)
        self.assertAlmostEqual(result, 0.0001, places=6)

    def test_higher_probability(self):
        # 1.0% prob * 5.0% penalty = 0.05%
        result = _compute_expected_annual_loss_pct(1.0, 5.0)
        self.assertAlmostEqual(result, 0.05, places=6)

    def test_max_probability_and_penalty(self):
        # 100% prob * 100% penalty = 100%
        result = _compute_expected_annual_loss_pct(100.0, 100.0)
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_symmetry_of_inputs(self):
        # prob=2, penalty=0.5 vs prob=0.5, penalty=2 — same result
        r1 = _compute_expected_annual_loss_pct(2.0, 0.5)
        r2 = _compute_expected_annual_loss_pct(0.5, 2.0)
        self.assertAlmostEqual(r1, r2, places=6)

    def test_small_values(self):
        result = _compute_expected_annual_loss_pct(0.001, 0.5)
        self.assertAlmostEqual(result, 0.000005, places=8)

    def test_typical_eth_validator(self):
        # typical: ~0.05% prob per year, 1/32 ETH ~3.125% penalty
        result = _compute_expected_annual_loss_pct(0.05, 3.125)
        expected = (0.05 / 100.0) * 3.125
        self.assertAlmostEqual(result, expected, places=6)

    def test_returns_float(self):
        result = _compute_expected_annual_loss_pct(0.1, 2.0)
        self.assertIsInstance(result, float)

    def test_rounded_to_6_places(self):
        result = _compute_expected_annual_loss_pct(0.01, 1.0)
        # Should be 0.0001, no excessive precision
        self.assertEqual(result, round(result, 6))


# ---------------------------------------------------------------------------
# 3. _compute_expected_annual_loss_usd
# ---------------------------------------------------------------------------

class TestExpectedAnnualLossUsd(unittest.TestCase):
    def test_zero_position(self):
        self.assertAlmostEqual(_compute_expected_annual_loss_usd(0.0, 0.5), 0.0)

    def test_zero_loss_pct(self):
        self.assertAlmostEqual(
            _compute_expected_annual_loss_usd(100_000.0, 0.0), 0.0
        )

    def test_baseline(self):
        # position=100k, loss_pct=0.0001 → 0.0001/100 * 100k = 0.1 USD
        result = _compute_expected_annual_loss_usd(100_000.0, 0.0001)
        self.assertAlmostEqual(result, 0.1, places=4)

    def test_one_percent_loss(self):
        # position=50k, loss_pct=1.0 → 500 USD
        result = _compute_expected_annual_loss_usd(50_000.0, 1.0)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_total_loss(self):
        # 100% loss on 1M → 1M
        result = _compute_expected_annual_loss_usd(1_000_000.0, 100.0)
        self.assertAlmostEqual(result, 1_000_000.0, places=2)

    def test_returns_float(self):
        result = _compute_expected_annual_loss_usd(100_000.0, 0.5)
        self.assertIsInstance(result, float)

    def test_large_position(self):
        result = _compute_expected_annual_loss_usd(10_000_000.0, 0.05)
        self.assertAlmostEqual(result, 5000.0, places=2)

    def test_fractional_position(self):
        result = _compute_expected_annual_loss_usd(1000.0, 0.01)
        self.assertAlmostEqual(result, 0.1, places=4)


# ---------------------------------------------------------------------------
# 4. _compute_net_staking_apy_pct
# ---------------------------------------------------------------------------

class TestNetStakingApy(unittest.TestCase):
    def test_no_loss(self):
        self.assertAlmostEqual(_compute_net_staking_apy_pct(3.8, 0.0), 3.8)

    def test_small_loss(self):
        result = _compute_net_staking_apy_pct(3.8, 0.0001)
        self.assertAlmostEqual(result, 3.7999, places=4)

    def test_loss_exceeds_yield(self):
        # APY=1.0, loss=2.0 → net = -1.0
        result = _compute_net_staking_apy_pct(1.0, 2.0)
        self.assertAlmostEqual(result, -1.0, places=5)

    def test_zero_apy(self):
        result = _compute_net_staking_apy_pct(0.0, 0.5)
        self.assertAlmostEqual(result, -0.5, places=5)

    def test_large_apy_small_loss(self):
        result = _compute_net_staking_apy_pct(20.0, 0.001)
        self.assertAlmostEqual(result, 19.999, places=3)

    def test_exact_breakeven(self):
        result = _compute_net_staking_apy_pct(3.0, 3.0)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_returns_float(self):
        result = _compute_net_staking_apy_pct(4.0, 0.5)
        self.assertIsInstance(result, float)

    def test_typical_values(self):
        loss = _compute_expected_annual_loss_pct(0.01, 1.0)
        net = _compute_net_staking_apy_pct(3.8, loss)
        self.assertAlmostEqual(net, 3.8 - 0.0001, places=5)


# ---------------------------------------------------------------------------
# 5. _compute_probability_component
# ---------------------------------------------------------------------------

class TestProbabilityComponent(unittest.TestCase):
    def test_zero_probability(self):
        self.assertAlmostEqual(_compute_probability_component(0.0), 0.0)

    def test_at_saturation(self):
        self.assertAlmostEqual(
            _compute_probability_component(_PROB_SATURATION_PCT), _PROB_MAX_SCORE
        )

    def test_above_saturation_capped(self):
        self.assertAlmostEqual(
            _compute_probability_component(10.0), _PROB_MAX_SCORE
        )

    def test_half_saturation(self):
        result = _compute_probability_component(_PROB_SATURATION_PCT / 2)
        self.assertAlmostEqual(result, _PROB_MAX_SCORE / 2)

    def test_quarter_saturation(self):
        result = _compute_probability_component(_PROB_SATURATION_PCT / 4)
        self.assertAlmostEqual(result, _PROB_MAX_SCORE / 4)

    def test_small_probability(self):
        # 0.01% → (0.01/5) * 50 = 0.1
        result = _compute_probability_component(0.01)
        self.assertAlmostEqual(result, 0.1, places=4)

    def test_negative_prob_clamped(self):
        self.assertAlmostEqual(_compute_probability_component(-1.0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_probability_component(1.0), float)


# ---------------------------------------------------------------------------
# 6. _compute_penalty_component
# ---------------------------------------------------------------------------

class TestPenaltyComponent(unittest.TestCase):
    def test_zero_penalty(self):
        self.assertAlmostEqual(_compute_penalty_component(0.0), 0.0)

    def test_at_saturation(self):
        self.assertAlmostEqual(
            _compute_penalty_component(_PENALTY_SATURATION_PCT), _PENALTY_MAX_SCORE
        )

    def test_above_saturation_capped(self):
        self.assertAlmostEqual(
            _compute_penalty_component(100.0), _PENALTY_MAX_SCORE
        )

    def test_half_saturation(self):
        result = _compute_penalty_component(_PENALTY_SATURATION_PCT / 2)
        self.assertAlmostEqual(result, _PENALTY_MAX_SCORE / 2)

    def test_one_percent_penalty(self):
        # 1.0 / 50 * 30 = 0.6
        result = _compute_penalty_component(1.0)
        self.assertAlmostEqual(result, 0.6, places=4)

    def test_ten_percent_penalty(self):
        # 10 / 50 * 30 = 6.0
        result = _compute_penalty_component(10.0)
        self.assertAlmostEqual(result, 6.0, places=4)

    def test_negative_penalty_clamped(self):
        self.assertAlmostEqual(_compute_penalty_component(-5.0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_penalty_component(25.0), float)


# ---------------------------------------------------------------------------
# 7. _compute_audit_reduction
# ---------------------------------------------------------------------------

class TestAuditReduction(unittest.TestCase):
    def test_audited(self):
        self.assertAlmostEqual(_compute_audit_reduction(True), _AUDIT_REDUCTION)

    def test_not_audited(self):
        self.assertAlmostEqual(_compute_audit_reduction(False), 0.0)

    def test_returns_float_true(self):
        self.assertIsInstance(_compute_audit_reduction(True), float)

    def test_returns_float_false(self):
        self.assertIsInstance(_compute_audit_reduction(False), float)


# ---------------------------------------------------------------------------
# 8. _compute_diversity_reduction
# ---------------------------------------------------------------------------

class TestDiversityReduction(unittest.TestCase):
    def test_zero_diversity(self):
        self.assertAlmostEqual(_compute_diversity_reduction(0), 0.0)

    def test_max_diversity(self):
        self.assertAlmostEqual(
            _compute_diversity_reduction(10), _DIVERSITY_MAX_REDUCTION
        )

    def test_half_diversity(self):
        self.assertAlmostEqual(_compute_diversity_reduction(5), 5.0)

    def test_diversity_7(self):
        self.assertAlmostEqual(_compute_diversity_reduction(7), 7.0)

    def test_diversity_1(self):
        self.assertAlmostEqual(_compute_diversity_reduction(1), 1.0)

    def test_diversity_above_max_clamped(self):
        # score > 10 → clamped to 10 → full reduction
        self.assertAlmostEqual(
            _compute_diversity_reduction(15), _DIVERSITY_MAX_REDUCTION
        )

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(_compute_diversity_reduction(-3), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_diversity_reduction(5), float)


# ---------------------------------------------------------------------------
# 9. _compute_staking_type_modifier
# ---------------------------------------------------------------------------

class TestStakingTypeModifier(unittest.TestCase):
    def test_eth_solo_validator(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("eth_solo_validator"),
            _STAKING_TYPE_MODIFIERS["eth_solo_validator"],
        )

    def test_eth_liquid_staking(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("eth_liquid_staking"), 0.0
        )

    def test_cosmos_delegation(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("cosmos_delegation"),
            _STAKING_TYPE_MODIFIERS["cosmos_delegation"],
        )

    def test_polkadot_nomination(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("polkadot_nomination"),
            _STAKING_TYPE_MODIFIERS["polkadot_nomination"],
        )

    def test_other(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("other"), 0.0
        )

    def test_unknown_type_returns_zero(self):
        self.assertAlmostEqual(
            _compute_staking_type_modifier("unknown_protocol"), 0.0
        )

    def test_solo_higher_than_liquid(self):
        solo = _compute_staking_type_modifier("eth_solo_validator")
        liquid = _compute_staking_type_modifier("eth_liquid_staking")
        self.assertGreater(solo, liquid)


# ---------------------------------------------------------------------------
# 10. _compute_slash_risk_score
# ---------------------------------------------------------------------------

class TestSlashRiskScore(unittest.TestCase):
    def test_all_zero_no_audit_no_diversity(self):
        # prob=0, penalty=0, type=other, no audit, diversity=0 → 0
        score = _compute_slash_risk_score(0.0, 0.0, False, 0, "other")
        self.assertEqual(score, 0)

    def test_returns_int(self):
        score = _compute_slash_risk_score(0.01, 1.0, True, 7, "eth_liquid_staking")
        self.assertIsInstance(score, int)

    def test_in_range_0_to_100(self):
        for prob in [0.0, 1.0, 5.0, 10.0]:
            for penalty in [0.0, 10.0, 50.0, 100.0]:
                score = _compute_slash_risk_score(prob, penalty, False, 0, "other")
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_audit_reduces_score(self):
        score_no_audit = _compute_slash_risk_score(1.0, 10.0, False, 5, "other")
        score_audited = _compute_slash_risk_score(1.0, 10.0, True, 5, "other")
        self.assertGreater(score_no_audit, score_audited)

    def test_high_diversity_reduces_score(self):
        score_low_div = _compute_slash_risk_score(1.0, 10.0, False, 0, "other")
        score_high_div = _compute_slash_risk_score(1.0, 10.0, False, 10, "other")
        self.assertGreater(score_low_div, score_high_div)

    def test_solo_validator_higher_than_liquid(self):
        score_solo = _compute_slash_risk_score(1.0, 10.0, False, 5, "eth_solo_validator")
        score_liquid = _compute_slash_risk_score(1.0, 10.0, False, 5, "eth_liquid_staking")
        self.assertGreater(score_solo, score_liquid)

    def test_max_inputs_clamped_to_100(self):
        score = _compute_slash_risk_score(100.0, 100.0, False, 0, "eth_solo_validator")
        self.assertLessEqual(score, 100)

    def test_full_reduction_from_audit_and_diversity(self):
        # prob=0, penalty=0, type=liquid → base=0; audit+diversity reduces → 0 (clamped)
        score = _compute_slash_risk_score(0.0, 0.0, True, 10, "eth_liquid_staking")
        self.assertEqual(score, 0)

    def test_higher_prob_gives_higher_score(self):
        score_low = _compute_slash_risk_score(0.5, 5.0, False, 5, "other")
        score_high = _compute_slash_risk_score(3.0, 5.0, False, 5, "other")
        self.assertGreater(score_high, score_low)

    def test_higher_penalty_gives_higher_score(self):
        score_low = _compute_slash_risk_score(1.0, 5.0, False, 5, "other")
        score_high = _compute_slash_risk_score(1.0, 40.0, False, 5, "other")
        self.assertGreater(score_high, score_low)


# ---------------------------------------------------------------------------
# 11. _compute_risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):
    def test_score_0_negligible(self):
        self.assertEqual(_compute_risk_label(0), "NEGLIGIBLE_SLASH_RISK")

    def test_score_10_negligible(self):
        self.assertEqual(_compute_risk_label(10), "NEGLIGIBLE_SLASH_RISK")

    def test_score_11_low(self):
        self.assertEqual(_compute_risk_label(11), "LOW_SLASH_RISK")

    def test_score_25_low(self):
        self.assertEqual(_compute_risk_label(25), "LOW_SLASH_RISK")

    def test_score_26_moderate(self):
        self.assertEqual(_compute_risk_label(26), "MODERATE_SLASH_RISK")

    def test_score_50_moderate(self):
        self.assertEqual(_compute_risk_label(50), "MODERATE_SLASH_RISK")

    def test_score_51_high(self):
        self.assertEqual(_compute_risk_label(51), "HIGH_SLASH_RISK")

    def test_score_75_high(self):
        self.assertEqual(_compute_risk_label(75), "HIGH_SLASH_RISK")

    def test_score_76_unacceptable(self):
        self.assertEqual(_compute_risk_label(76), "UNACCEPTABLE_SLASH_RISK")

    def test_score_100_unacceptable(self):
        self.assertEqual(_compute_risk_label(100), "UNACCEPTABLE_SLASH_RISK")

    def test_all_valid_labels(self):
        valid = {
            "NEGLIGIBLE_SLASH_RISK",
            "LOW_SLASH_RISK",
            "MODERATE_SLASH_RISK",
            "HIGH_SLASH_RISK",
            "UNACCEPTABLE_SLASH_RISK",
        }
        for score in range(0, 101, 5):
            self.assertIn(_compute_risk_label(score), valid)


# ---------------------------------------------------------------------------
# 12. Analyzer.analyze — output structure and values
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")
        self.analyzer = DeFiProtocolStakingPenaltyRiskAnalyzer(
            log_path=self.log_path
        )

    def test_returns_dict(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIsInstance(result, dict)

    def test_all_expected_keys_present(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        expected_keys = {
            "protocol_name",
            "staking_type",
            "expected_annual_loss_pct",
            "expected_annual_loss_usd",
            "net_staking_apy_pct",
            "slash_risk_score",
            "risk_label",
            "analyzed_at",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_protocol_name_echoed(self):
        result = self.analyzer.analyze(make_data(protocol_name="TestProto"), write_log=False)
        self.assertEqual(result["protocol_name"], "TestProto")

    def test_staking_type_echoed(self):
        result = self.analyzer.analyze(
            make_data(staking_type="cosmos_delegation"), write_log=False
        )
        self.assertEqual(result["staking_type"], "cosmos_delegation")

    def test_expected_loss_pct_correct(self):
        result = self.analyzer.analyze(
            make_data(slash_probability_annual_pct=0.01, slash_penalty_pct=1.0),
            write_log=False,
        )
        expected = _compute_expected_annual_loss_pct(0.01, 1.0)
        self.assertAlmostEqual(result["expected_annual_loss_pct"], expected, places=6)

    def test_expected_loss_usd_correct(self):
        result = self.analyzer.analyze(
            make_data(
                slash_probability_annual_pct=0.01,
                slash_penalty_pct=1.0,
                position_size_usd=100_000.0,
            ),
            write_log=False,
        )
        loss_pct = _compute_expected_annual_loss_pct(0.01, 1.0)
        expected_usd = _compute_expected_annual_loss_usd(100_000.0, loss_pct)
        self.assertAlmostEqual(result["expected_annual_loss_usd"], expected_usd, places=4)

    def test_net_apy_correct(self):
        result = self.analyzer.analyze(
            make_data(
                staking_apy_pct=3.8,
                slash_probability_annual_pct=0.01,
                slash_penalty_pct=1.0,
            ),
            write_log=False,
        )
        loss = _compute_expected_annual_loss_pct(0.01, 1.0)
        expected_net = _compute_net_staking_apy_pct(3.8, loss)
        self.assertAlmostEqual(result["net_staking_apy_pct"], expected_net, places=5)

    def test_slash_risk_score_is_int(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIsInstance(result["slash_risk_score"], int)

    def test_slash_risk_score_in_range(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertGreaterEqual(result["slash_risk_score"], 0)
        self.assertLessEqual(result["slash_risk_score"], 100)

    def test_risk_label_valid(self):
        valid_labels = {
            "NEGLIGIBLE_SLASH_RISK",
            "LOW_SLASH_RISK",
            "MODERATE_SLASH_RISK",
            "HIGH_SLASH_RISK",
            "UNACCEPTABLE_SLASH_RISK",
        }
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIn(result["risk_label"], valid_labels)

    def test_analyzed_at_is_iso(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        # Should parse without error
        from datetime import datetime
        datetime.fromisoformat(result["analyzed_at"].replace("Z", "+00:00"))

    def test_write_log_true_creates_file(self):
        self.analyzer.analyze(make_data())
        self.assertTrue(os.path.exists(self.log_path))

    def test_write_log_false_no_file(self):
        self.analyzer.analyze(make_data(), write_log=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_high_risk_scenario_label(self):
        # High probability, high penalty, no audit, no diversity → unacceptable/high
        result = self.analyzer.analyze(
            make_data(
                slash_probability_annual_pct=4.0,
                slash_penalty_pct=40.0,
                protocol_audited=False,
                client_diversity_score=0,
                staking_type="eth_solo_validator",
            ),
            write_log=False,
        )
        self.assertIn(
            result["risk_label"],
            ["HIGH_SLASH_RISK", "UNACCEPTABLE_SLASH_RISK"],
        )

    def test_negligible_risk_scenario(self):
        # Very low probability, tiny penalty, audited, max diversity → negligible
        result = self.analyzer.analyze(
            make_data(
                slash_probability_annual_pct=0.001,
                slash_penalty_pct=0.1,
                protocol_audited=True,
                client_diversity_score=10,
                staking_type="eth_liquid_staking",
            ),
            write_log=False,
        )
        self.assertIn(
            result["risk_label"],
            ["NEGLIGIBLE_SLASH_RISK", "LOW_SLASH_RISK"],
        )

    def test_missing_keys_use_defaults(self):
        result = self.analyzer.analyze({}, write_log=False)
        self.assertIn("protocol_name", result)
        self.assertEqual(result["protocol_name"], "unknown")


# ---------------------------------------------------------------------------
# 13. _atomic_append_log
# ---------------------------------------------------------------------------

class TestAtomicAppendLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def test_creates_file_on_first_write(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        self.assertTrue(os.path.exists(self.log_path))

    def test_file_is_valid_json(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_entry(self):
        _atomic_append_log(self.log_path, {"a": 1})
        _atomic_append_log(self.log_path, {"b": 2})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_entry_content_preserved(self):
        entry = {"key": "value", "num": 42.5}
        _atomic_append_log(self.log_path, entry)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["key"], "value")
        self.assertAlmostEqual(data[0]["num"], 42.5)

    def test_handles_corrupted_file(self):
        with open(self.log_path, "w") as f:
            f.write("not valid json{{")
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_missing_file(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_parent_dirs(self):
        deep_path = os.path.join(self.tmp_dir, "sub1", "sub2", "log.json")
        _atomic_append_log(deep_path, {"k": "v"})
        self.assertTrue(os.path.exists(deep_path))

    def test_preserves_order(self):
        for i in range(5):
            _atomic_append_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual([d["i"] for d in data], list(range(5)))

    def test_custom_cap_enforced(self):
        for i in range(10):
            _atomic_append_log(self.log_path, {"i": i}, cap=5)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertEqual(data[0]["i"], 5)

    def test_non_list_json_replaced(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# 14. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestLogCap(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "cap_test.json")
        self.analyzer = DeFiProtocolStakingPenaltyRiskAnalyzer(
            log_path=self.log_path
        )

    def test_cap_is_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_log_never_exceeds_cap(self):
        for i in range(110):
            self.analyzer.analyze(
                make_data(protocol_name=f"P{i}")
            )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _LOG_CAP)

    def test_oldest_entries_dropped(self):
        for i in range(105):
            _atomic_append_log(self.log_path, {"idx": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["idx"], 5)

    def test_exactly_cap_entries_preserved(self):
        for i in range(_LOG_CAP):
            _atomic_append_log(self.log_path, {"idx": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)


# ---------------------------------------------------------------------------
# 15. Static method access via class
# ---------------------------------------------------------------------------

class TestStaticMethods(unittest.TestCase):
    def test_expected_annual_loss_pct_static(self):
        r = DeFiProtocolStakingPenaltyRiskAnalyzer.expected_annual_loss_pct(0.01, 1.0)
        self.assertAlmostEqual(r, 0.0001, places=6)

    def test_expected_annual_loss_usd_static(self):
        r = DeFiProtocolStakingPenaltyRiskAnalyzer.expected_annual_loss_usd(
            100_000.0, 0.0001
        )
        self.assertAlmostEqual(r, 0.1, places=4)

    def test_net_staking_apy_static(self):
        r = DeFiProtocolStakingPenaltyRiskAnalyzer.net_staking_apy(3.8, 0.0001)
        self.assertAlmostEqual(r, 3.7999, places=4)

    def test_slash_risk_score_static(self):
        r = DeFiProtocolStakingPenaltyRiskAnalyzer.slash_risk_score(
            0.01, 1.0, True, 7, "eth_liquid_staking"
        )
        self.assertIsInstance(r, int)

    def test_risk_label_static(self):
        self.assertEqual(
            DeFiProtocolStakingPenaltyRiskAnalyzer.risk_label(5),
            "NEGLIGIBLE_SLASH_RISK",
        )


# ---------------------------------------------------------------------------
# 16. Edge cases and boundary conditions
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiProtocolStakingPenaltyRiskAnalyzer(
            log_path=os.path.join(tempfile.mkdtemp(), "log.json")
        )

    def test_extreme_high_risk_score_clamped(self):
        score = _compute_slash_risk_score(
            100.0, 100.0, False, 0, "eth_solo_validator"
        )
        self.assertLessEqual(score, 100)

    def test_all_reductions_score_zero(self):
        # No risk factors + max reductions → 0 (clamped)
        score = _compute_slash_risk_score(
            0.0, 0.0, True, 10, "eth_liquid_staking"
        )
        self.assertEqual(score, 0)

    def test_cosmos_and_polkadot_equal_modifier(self):
        score_cosmos = _compute_slash_risk_score(1.0, 5.0, False, 5, "cosmos_delegation")
        score_dot = _compute_slash_risk_score(1.0, 5.0, False, 5, "polkadot_nomination")
        self.assertEqual(score_cosmos, score_dot)

    def test_label_boundary_score_10(self):
        self.assertEqual(_compute_risk_label(10), "NEGLIGIBLE_SLASH_RISK")

    def test_label_boundary_score_25(self):
        self.assertEqual(_compute_risk_label(25), "LOW_SLASH_RISK")

    def test_label_boundary_score_50(self):
        self.assertEqual(_compute_risk_label(50), "MODERATE_SLASH_RISK")

    def test_label_boundary_score_75(self):
        self.assertEqual(_compute_risk_label(75), "HIGH_SLASH_RISK")

    def test_label_boundary_score_100(self):
        self.assertEqual(_compute_risk_label(100), "UNACCEPTABLE_SLASH_RISK")

    def test_analyze_with_zero_position(self):
        result = self.analyzer.analyze(
            make_data(position_size_usd=0.0), write_log=False
        )
        self.assertEqual(result["expected_annual_loss_usd"], 0.0)

    def test_analyze_net_apy_negative_is_valid(self):
        # If slashing loss exceeds yield, net APY is negative
        result = self.analyzer.analyze(
            make_data(
                staking_apy_pct=0.5,
                slash_probability_annual_pct=5.0,
                slash_penalty_pct=50.0,
            ),
            write_log=False,
        )
        # expected_loss_pct = 5/100 * 50 = 2.5
        # net = 0.5 - 2.5 = -2.0
        self.assertAlmostEqual(result["net_staking_apy_pct"], 0.5 - 2.5, places=4)

    def test_analyze_write_then_read_back(self):
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "wb.json")
        a = DeFiProtocolStakingPenaltyRiskAnalyzer(log_path=log_path)
        r = a.analyze(make_data(protocol_name="WriteBack"))
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol_name"], "WriteBack")


if __name__ == "__main__":
    unittest.main()
