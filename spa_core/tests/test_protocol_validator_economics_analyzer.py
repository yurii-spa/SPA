"""
Tests for MP-947: ProtocolValidatorEconomicsAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_validator_economics_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_validator_economics_analyzer import (
    ProtocolValidatorEconomicsAnalyzer,
    _clamp,
    _compute_gross_apy,
    _compute_net_apy,
    _compute_profit_margin,
    _compute_delegator_apy,
    _compute_marginal_cost_per_stake,
    _compute_market_share,
    _determine_label,
    _compute_flags,
    _analyze_validator,
    _compute_aggregates,
    _write_log,
    DEFAULT_CONFIG,
    LABEL_HIGHLY_PROFITABLE,
    LABEL_PROFITABLE,
    LABEL_BREAK_EVEN,
    LABEL_LOSS_MAKING,
    LABEL_UNSUSTAINABLE,
    FLAG_HIGH_SLASHING_RISK,
    FLAG_LOW_UPTIME,
    FLAG_HIGH_COMMISSION,
    FLAG_UNDERDELEGATED,
    FLAG_INFLATION_DEPENDENT,
)


def make_validator(**kwargs):
    """Create a minimal valid validator dict."""
    base = {
        "protocol": "Ethereum",
        "stake_usd": 1_000_000.0,
        "annual_reward_usd": 50_000.0,
        "operating_cost_usd_monthly": 2_000.0,
        "uptime_pct": 99.5,
        "slashing_events_count": 0,
        "commission_pct": 10.0,
        "delegated_stake_usd": 800_000.0,
        "self_stake_pct": 10.0,
        "chain_inflation_rate_pct": 5.0,
        "validator_count_total": 500,
    }
    base.update(kwargs)
    return base


class TestClamp(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_below_min(self):
        self.assertEqual(_clamp(-5.0, 0.0, 10.0), 0.0)

    def test_above_max(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_at_lower_boundary(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_at_upper_boundary(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)


class TestGrossApy(unittest.TestCase):
    def test_basic_computation(self):
        result = _compute_gross_apy(50_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_zero_stake(self):
        result = _compute_gross_apy(50_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_zero_reward(self):
        result = _compute_gross_apy(0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_high_reward(self):
        result = _compute_gross_apy(200_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 20.0, places=4)

    def test_small_stake(self):
        result = _compute_gross_apy(100.0, 1000.0)
        self.assertAlmostEqual(result, 10.0, places=4)


class TestNetApy(unittest.TestCase):
    def test_basic_computation(self):
        # 50000 reward - 2000*12=24000 costs → 26000 net on 1M
        result = _compute_net_apy(50_000.0, 2_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 2.6, places=4)

    def test_zero_stake(self):
        result = _compute_net_apy(50_000.0, 2_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_zero_cost(self):
        result = _compute_net_apy(50_000.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_negative_net(self):
        # 5000 reward - 10000*12=120000 costs → very negative
        result = _compute_net_apy(5_000.0, 10_000.0, 100_000.0)
        self.assertLess(result, 0.0)

    def test_high_cost_small_stake(self):
        result = _compute_net_apy(1_000.0, 500.0, 10_000.0)
        # (1000 - 6000) / 10000 * 100 = -50%
        self.assertAlmostEqual(result, -50.0, places=4)


class TestProfitMargin(unittest.TestCase):
    def test_profitable(self):
        # 50000 - 24000 = 26000 profit on 50000 reward = 52%
        result = _compute_profit_margin(50_000.0, 2_000.0)
        self.assertAlmostEqual(result, 52.0, places=4)

    def test_zero_reward_with_cost(self):
        result = _compute_profit_margin(0.0, 1_000.0)
        self.assertAlmostEqual(result, -100.0, places=4)

    def test_zero_reward_zero_cost(self):
        result = _compute_profit_margin(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_break_even(self):
        # 24000 reward, 2000/mo cost → 24000-24000=0 profit
        result = _compute_profit_margin(24_000.0, 2_000.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_loss_making(self):
        result = _compute_profit_margin(10_000.0, 2_000.0)
        # (10000-24000)/10000*100 = -140%
        self.assertAlmostEqual(result, -140.0, places=4)


class TestDelegatorApy(unittest.TestCase):
    def test_basic(self):
        # gross 5%, commission 10% → delegator gets 5*0.9 = 4.5%
        result = _compute_delegator_apy(5.0, 10.0)
        self.assertAlmostEqual(result, 4.5, places=4)

    def test_zero_commission(self):
        result = _compute_delegator_apy(5.0, 0.0)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_full_commission(self):
        result = _compute_delegator_apy(5.0, 100.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_high_commission(self):
        result = _compute_delegator_apy(10.0, 50.0)
        self.assertAlmostEqual(result, 5.0, places=4)


class TestMarginalCostPerStake(unittest.TestCase):
    def test_basic(self):
        # 2000/mo * 12 = 24000 annual cost on 1M stake = 2.4%
        result = _compute_marginal_cost_per_stake(2_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 2.4, places=4)

    def test_zero_stake(self):
        result = _compute_marginal_cost_per_stake(2_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_zero_cost(self):
        result = _compute_marginal_cost_per_stake(0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_high_cost_ratio(self):
        result = _compute_marginal_cost_per_stake(10_000.0, 100_000.0)
        # 120000/100000*100 = 120%
        self.assertAlmostEqual(result, 120.0, places=4)


class TestMarketShare(unittest.TestCase):
    def test_basic(self):
        result = _compute_market_share(100_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 10.0, places=4)

    def test_zero_total(self):
        result = _compute_market_share(100_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_full_market(self):
        result = _compute_market_share(1_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_small_share(self):
        result = _compute_market_share(1_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.1, places=4)


class TestDetermineLabel(unittest.TestCase):
    def test_highly_profitable(self):
        label = _determine_label(60.0, 5.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_HIGHLY_PROFITABLE)

    def test_profitable(self):
        label = _determine_label(30.0, 3.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_PROFITABLE)

    def test_break_even(self):
        label = _determine_label(5.0, 0.5, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_BREAK_EVEN)

    def test_loss_making(self):
        label = _determine_label(-20.0, -2.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_LOSS_MAKING)

    def test_unsustainable_by_margin(self):
        label = _determine_label(-80.0, -5.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_UNSUSTAINABLE)

    def test_unsustainable_by_net_apy(self):
        label = _determine_label(-20.0, -15.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_UNSUSTAINABLE)

    def test_exactly_at_highly_profitable_boundary(self):
        label = _determine_label(50.0, 5.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_HIGHLY_PROFITABLE)

    def test_exactly_at_profitable_boundary(self):
        label = _determine_label(20.0, 2.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_PROFITABLE)

    def test_exactly_at_break_even(self):
        label = _determine_label(0.0, 0.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_BREAK_EVEN)

    def test_custom_thresholds(self):
        cfg = {**DEFAULT_CONFIG, "highly_profitable_margin_pct": 80.0}
        label = _determine_label(60.0, 5.0, cfg)
        self.assertEqual(label, LABEL_PROFITABLE)


class TestComputeFlags(unittest.TestCase):
    def test_high_slashing_risk(self):
        v = make_validator(slashing_events_count=1)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertIn(FLAG_HIGH_SLASHING_RISK, flags)

    def test_no_slashing_risk(self):
        v = make_validator(slashing_events_count=0)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertNotIn(FLAG_HIGH_SLASHING_RISK, flags)

    def test_low_uptime(self):
        v = make_validator(uptime_pct=98.5)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertIn(FLAG_LOW_UPTIME, flags)

    def test_good_uptime(self):
        v = make_validator(uptime_pct=99.9)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertNotIn(FLAG_LOW_UPTIME, flags)

    def test_high_commission(self):
        v = make_validator(commission_pct=25.0)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertIn(FLAG_HIGH_COMMISSION, flags)

    def test_normal_commission(self):
        v = make_validator(commission_pct=5.0)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertNotIn(FLAG_HIGH_COMMISSION, flags)

    def test_underdelegated(self):
        # self_stake = 1M * 20% = 200k, delegated = 100k < 200k → UNDERDELEGATED
        v = make_validator(stake_usd=1_000_000.0, self_stake_pct=20.0,
                           delegated_stake_usd=100_000.0)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertIn(FLAG_UNDERDELEGATED, flags)

    def test_well_delegated(self):
        # self_stake = 1M * 10% = 100k, delegated = 800k > 100k
        v = make_validator(stake_usd=1_000_000.0, self_stake_pct=10.0,
                           delegated_stake_usd=800_000.0)
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertNotIn(FLAG_UNDERDELEGATED, flags)

    def test_inflation_dependent(self):
        # inflation_yield = 1M * 5% = 50k; reward = 45k → ratio = 0.9 > 0.8
        v = make_validator(stake_usd=1_000_000.0, chain_inflation_rate_pct=5.0)
        flags = _compute_flags(v, 45_000.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_INFLATION_DEPENDENT, flags)

    def test_not_inflation_dependent(self):
        # inflation_yield = 1M * 5% = 50k; reward = 30k → ratio = 0.6 < 0.8
        v = make_validator(stake_usd=1_000_000.0, chain_inflation_rate_pct=5.0)
        flags = _compute_flags(v, 30_000.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_INFLATION_DEPENDENT, flags)

    def test_zero_inflation_rate_no_flag(self):
        v = make_validator(chain_inflation_rate_pct=0.0)
        flags = _compute_flags(v, 50_000.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_INFLATION_DEPENDENT, flags)

    def test_multiple_flags_simultaneously(self):
        v = make_validator(
            slashing_events_count=2,
            uptime_pct=95.0,
            commission_pct=30.0,
            self_stake_pct=80.0,
            delegated_stake_usd=100_000.0,
        )
        flags = _compute_flags(v, v["annual_reward_usd"], DEFAULT_CONFIG)
        self.assertIn(FLAG_HIGH_SLASHING_RISK, flags)
        self.assertIn(FLAG_LOW_UPTIME, flags)
        self.assertIn(FLAG_HIGH_COMMISSION, flags)
        self.assertIn(FLAG_UNDERDELEGATED, flags)


class TestAnalyzeValidator(unittest.TestCase):
    def _run(self, total_stake=2_000_000.0, **kwargs):
        v = make_validator(**kwargs)
        return _analyze_validator(v, total_stake, DEFAULT_CONFIG)

    def test_returns_required_keys(self):
        result = self._run()
        for key in ["gross_apy_pct", "net_apy_pct", "profit_margin_pct",
                    "delegator_apy_pct", "marginal_cost_per_stake_usd",
                    "market_share_pct", "economics_label", "flags"]:
            self.assertIn(key, result)

    def test_gross_apy_correct(self):
        result = self._run(annual_reward_usd=50_000.0, stake_usd=1_000_000.0)
        self.assertAlmostEqual(result["gross_apy_pct"], 5.0, places=4)

    def test_net_apy_correct(self):
        result = self._run(
            annual_reward_usd=50_000.0,
            stake_usd=1_000_000.0,
            operating_cost_usd_monthly=2_000.0,
        )
        # (50000 - 24000) / 1000000 * 100 = 2.6%
        self.assertAlmostEqual(result["net_apy_pct"], 2.6, places=4)

    def test_market_share_correct(self):
        # 1M stake out of 2M total = 50%
        result = self._run(stake_usd=1_000_000.0, total_stake=2_000_000.0)
        self.assertAlmostEqual(result["market_share_pct"], 50.0, places=4)

    def test_protocol_preserved(self):
        result = self._run(protocol="Solana")
        self.assertEqual(result["protocol"], "Solana")

    def test_delegator_apy_computed(self):
        result = self._run(
            annual_reward_usd=50_000.0,
            stake_usd=1_000_000.0,
            operating_cost_usd_monthly=0.0,
            commission_pct=10.0,
        )
        # gross=5%, delegator=5*0.9=4.5%
        self.assertAlmostEqual(result["delegator_apy_pct"], 4.5, places=4)

    def test_label_assigned(self):
        result = self._run()
        self.assertIn(result["economics_label"], [
            LABEL_HIGHLY_PROFITABLE, LABEL_PROFITABLE,
            LABEL_BREAK_EVEN, LABEL_LOSS_MAKING, LABEL_UNSUSTAINABLE,
        ])

    def test_flags_is_list(self):
        result = self._run()
        self.assertIsInstance(result["flags"], list)


class TestComputeAggregates(unittest.TestCase):
    def _make_result(self, protocol, net_apy, delegator_apy):
        return {
            "protocol": protocol,
            "net_apy_pct": net_apy,
            "delegator_apy_pct": delegator_apy,
        }

    def test_empty_list(self):
        agg = _compute_aggregates([])
        self.assertIsNone(agg["most_profitable_validator"])
        self.assertIsNone(agg["least_profitable"])
        self.assertEqual(agg["profitable_count"], 0)
        self.assertAlmostEqual(agg["average_net_apy"], 0.0, places=4)
        self.assertAlmostEqual(agg["average_delegator_apy"], 0.0, places=4)

    def test_single_validator(self):
        results = [self._make_result("ETH", 3.0, 4.5)]
        agg = _compute_aggregates(results)
        self.assertEqual(agg["most_profitable_validator"], "ETH")
        self.assertEqual(agg["least_profitable"], "ETH")
        self.assertAlmostEqual(agg["average_net_apy"], 3.0, places=4)

    def test_most_and_least_profitable(self):
        results = [
            self._make_result("ETH", 5.0, 4.5),
            self._make_result("SOL", 1.0, 3.0),
            self._make_result("ADA", 3.0, 2.7),
        ]
        agg = _compute_aggregates(results)
        self.assertEqual(agg["most_profitable_validator"], "ETH")
        self.assertEqual(agg["least_profitable"], "SOL")

    def test_average_net_apy(self):
        results = [
            self._make_result("A", 4.0, 3.6),
            self._make_result("B", 2.0, 1.8),
        ]
        agg = _compute_aggregates(results)
        self.assertAlmostEqual(agg["average_net_apy"], 3.0, places=4)

    def test_average_delegator_apy(self):
        results = [
            self._make_result("A", 4.0, 4.5),
            self._make_result("B", 2.0, 3.5),
        ]
        agg = _compute_aggregates(results)
        self.assertAlmostEqual(agg["average_delegator_apy"], 4.0, places=4)

    def test_profitable_count(self):
        results = [
            self._make_result("A", 3.0, 2.7),
            self._make_result("B", -1.0, 4.0),
            self._make_result("C", 2.0, 1.8),
        ]
        agg = _compute_aggregates(results)
        self.assertEqual(agg["profitable_count"], 2)

    def test_all_loss_making(self):
        results = [
            self._make_result("A", -3.0, 4.5),
            self._make_result("B", -1.0, 3.0),
        ]
        agg = _compute_aggregates(results)
        self.assertEqual(agg["profitable_count"], 0)


class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "validator_economics_log.json")

    def test_creates_log_file(self):
        import spa_core.analytics.protocol_validator_economics_analyzer as m
        original = m.LOG_PATH
        m.LOG_PATH = self.log_path
        try:
            _write_log({"test": 1})
            self.assertTrue(os.path.exists(self.log_path))
        finally:
            m.LOG_PATH = original

    def test_appends_multiple_entries(self):
        import spa_core.analytics.protocol_validator_economics_analyzer as m
        original = m.LOG_PATH
        m.LOG_PATH = self.log_path
        try:
            _write_log({"i": 1})
            _write_log({"i": 2})
            with open(self.log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        finally:
            m.LOG_PATH = original

    def test_ring_buffer_cap(self):
        import spa_core.analytics.protocol_validator_economics_analyzer as m
        original = m.LOG_PATH
        original_cap = m.LOG_CAP
        m.LOG_PATH = self.log_path
        m.LOG_CAP = 3
        try:
            for i in range(6):
                _write_log({"i": i})
            with open(self.log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
            self.assertEqual(data[-1]["i"], 5)
        finally:
            m.LOG_PATH = original
            m.LOG_CAP = original_cap

    def test_atomic_write(self):
        import spa_core.analytics.protocol_validator_economics_analyzer as m
        original = m.LOG_PATH
        m.LOG_PATH = self.log_path
        try:
            _write_log({"atomic": True})
            self.assertFalse(os.path.exists(self.log_path + ".tmp"))
        finally:
            m.LOG_PATH = original


class TestProtocolValidatorEconomicsAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolValidatorEconomicsAnalyzer()

    def _make_validators(self, n=1):
        return [make_validator(protocol=f"Protocol{i}") for i in range(n)]

    def test_returns_dict(self):
        result = self.analyzer.analyze(self._make_validators())
        self.assertIsInstance(result, dict)

    def test_required_top_level_keys(self):
        result = self.analyzer.analyze(self._make_validators())
        for key in ["timestamp", "validator_count", "total_stake_usd",
                    "validators", "aggregates"]:
            self.assertIn(key, result)

    def test_validator_count_matches(self):
        result = self.analyzer.analyze(self._make_validators(4))
        self.assertEqual(result["validator_count"], 4)

    def test_empty_validators(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["validator_count"], 0)
        self.assertEqual(result["validators"], [])

    def test_total_stake_usd_correct(self):
        validators = [
            make_validator(protocol="A", stake_usd=500_000.0),
            make_validator(protocol="B", stake_usd=300_000.0),
        ]
        result = self.analyzer.analyze(validators)
        self.assertAlmostEqual(result["total_stake_usd"], 800_000.0, places=2)

    def test_aggregates_present(self):
        result = self.analyzer.analyze(self._make_validators(2))
        agg = result["aggregates"]
        for key in ["most_profitable_validator", "least_profitable",
                    "average_net_apy", "average_delegator_apy", "profitable_count"]:
            self.assertIn(key, agg)

    def test_per_validator_required_fields(self):
        result = self.analyzer.analyze(self._make_validators())
        val = result["validators"][0]
        for key in ["gross_apy_pct", "net_apy_pct", "profit_margin_pct",
                    "delegator_apy_pct", "marginal_cost_per_stake_usd",
                    "market_share_pct", "economics_label", "flags"]:
            self.assertIn(key, val)

    def test_highly_profitable_validator(self):
        validators = [make_validator(
            annual_reward_usd=100_000.0,
            operating_cost_usd_monthly=500.0,
            stake_usd=1_000_000.0,
        )]
        result = self.analyzer.analyze(validators)
        self.assertEqual(result["validators"][0]["economics_label"], LABEL_HIGHLY_PROFITABLE)

    def test_loss_making_validator(self):
        validators = [make_validator(
            annual_reward_usd=5_000.0,
            operating_cost_usd_monthly=2_000.0,
            stake_usd=1_000_000.0,
        )]
        result = self.analyzer.analyze(validators)
        label = result["validators"][0]["economics_label"]
        self.assertIn(label, [LABEL_LOSS_MAKING, LABEL_UNSUSTAINABLE])

    def test_unsustainable_validator(self):
        validators = [make_validator(
            annual_reward_usd=1_000.0,
            operating_cost_usd_monthly=10_000.0,
            stake_usd=1_000_000.0,
        )]
        result = self.analyzer.analyze(validators)
        self.assertEqual(result["validators"][0]["economics_label"], LABEL_UNSUSTAINABLE)

    def test_high_slashing_risk_flag(self):
        validators = [make_validator(slashing_events_count=3)]
        result = self.analyzer.analyze(validators)
        self.assertIn(FLAG_HIGH_SLASHING_RISK, result["validators"][0]["flags"])

    def test_low_uptime_flag(self):
        validators = [make_validator(uptime_pct=97.0)]
        result = self.analyzer.analyze(validators)
        self.assertIn(FLAG_LOW_UPTIME, result["validators"][0]["flags"])

    def test_high_commission_flag(self):
        validators = [make_validator(commission_pct=30.0)]
        result = self.analyzer.analyze(validators)
        self.assertIn(FLAG_HIGH_COMMISSION, result["validators"][0]["flags"])

    def test_underdelegated_flag(self):
        validators = [make_validator(
            stake_usd=1_000_000.0,
            self_stake_pct=50.0,
            delegated_stake_usd=100_000.0,
        )]
        result = self.analyzer.analyze(validators)
        self.assertIn(FLAG_UNDERDELEGATED, result["validators"][0]["flags"])

    def test_inflation_dependent_flag(self):
        validators = [make_validator(
            stake_usd=1_000_000.0,
            chain_inflation_rate_pct=5.0,
            annual_reward_usd=45_000.0,
        )]
        result = self.analyzer.analyze(validators)
        self.assertIn(FLAG_INFLATION_DEPENDENT, result["validators"][0]["flags"])

    def test_market_share_two_validators(self):
        validators = [
            make_validator(protocol="A", stake_usd=600_000.0),
            make_validator(protocol="B", stake_usd=400_000.0),
        ]
        result = self.analyzer.analyze(validators)
        a_share = result["validators"][0]["market_share_pct"]
        b_share = result["validators"][1]["market_share_pct"]
        self.assertAlmostEqual(a_share, 60.0, places=3)
        self.assertAlmostEqual(b_share, 40.0, places=3)

    def test_market_shares_sum_to_100(self):
        validators = [
            make_validator(protocol="A", stake_usd=300_000.0),
            make_validator(protocol="B", stake_usd=500_000.0),
            make_validator(protocol="C", stake_usd=200_000.0),
        ]
        result = self.analyzer.analyze(validators)
        total_share = sum(v["market_share_pct"] for v in result["validators"])
        self.assertAlmostEqual(total_share, 100.0, places=3)

    def test_most_profitable_in_aggregates(self):
        validators = [
            make_validator(protocol="Best", annual_reward_usd=100_000.0,
                           operating_cost_usd_monthly=500.0),
            make_validator(protocol="Worst", annual_reward_usd=5_000.0,
                           operating_cost_usd_monthly=2_000.0),
        ]
        result = self.analyzer.analyze(validators)
        self.assertEqual(result["aggregates"]["most_profitable_validator"], "Best")

    def test_least_profitable_in_aggregates(self):
        validators = [
            make_validator(protocol="Good", annual_reward_usd=100_000.0,
                           operating_cost_usd_monthly=500.0),
            make_validator(protocol="Bad", annual_reward_usd=1_000.0,
                           operating_cost_usd_monthly=5_000.0),
        ]
        result = self.analyzer.analyze(validators)
        self.assertEqual(result["aggregates"]["least_profitable"], "Bad")

    def test_profitable_count(self):
        validators = [
            make_validator(protocol="A", annual_reward_usd=100_000.0,
                           operating_cost_usd_monthly=500.0),
            make_validator(protocol="B", annual_reward_usd=1_000.0,
                           operating_cost_usd_monthly=5_000.0),
            make_validator(protocol="C", annual_reward_usd=50_000.0,
                           operating_cost_usd_monthly=2_000.0),
        ]
        result = self.analyzer.analyze(validators)
        # A and C are profitable, B is not
        self.assertEqual(result["aggregates"]["profitable_count"], 2)

    def test_timestamp_present(self):
        result = self.analyzer.analyze(self._make_validators())
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)

    def test_config_override_highly_profitable_threshold(self):
        # annual_reward=80000, monthly_cost=500 → annual_cost=6000
        # profit_margin = (80000-6000)/80000*100 = 92.5%
        # With threshold=95%, 92.5 < 95 → NOT HIGHLY_PROFITABLE
        validators = [make_validator(
            annual_reward_usd=80_000.0,
            operating_cost_usd_monthly=500.0,
        )]
        result = self.analyzer.analyze(validators, {"highly_profitable_margin_pct": 95.0})
        label = result["validators"][0]["economics_label"]
        self.assertNotEqual(label, LABEL_HIGHLY_PROFITABLE)

    def test_config_override_uptime_threshold(self):
        validators = [make_validator(uptime_pct=99.5)]
        result = self.analyzer.analyze(validators, {"low_uptime_threshold_pct": 99.9})
        self.assertIn(FLAG_LOW_UPTIME, result["validators"][0]["flags"])

    def test_config_override_commission_threshold(self):
        validators = [make_validator(commission_pct=15.0)]
        result = self.analyzer.analyze(validators, {"high_commission_threshold_pct": 10.0})
        self.assertIn(FLAG_HIGH_COMMISSION, result["validators"][0]["flags"])

    def test_default_config_when_none(self):
        validators = [make_validator(slashing_events_count=1)]
        result = self.analyzer.analyze(validators, None)
        self.assertIn(FLAG_HIGH_SLASHING_RISK, result["validators"][0]["flags"])

    def test_zero_stake_validator(self):
        validators = [make_validator(stake_usd=0.0)]
        result = self.analyzer.analyze(validators)
        self.assertAlmostEqual(result["validators"][0]["gross_apy_pct"], 0.0, places=4)

    def test_break_even_validator(self):
        validators = [make_validator(
            annual_reward_usd=24_000.0,
            operating_cost_usd_monthly=2_000.0,
            stake_usd=1_000_000.0,
        )]
        result = self.analyzer.analyze(validators)
        self.assertEqual(result["validators"][0]["economics_label"], LABEL_BREAK_EVEN)

    def test_multiple_validators_analysis(self):
        validators = self._make_validators(5)
        result = self.analyzer.analyze(validators)
        self.assertEqual(len(result["validators"]), 5)

    def test_no_flags_clean_validator(self):
        validators = [make_validator(
            slashing_events_count=0,
            uptime_pct=99.9,
            commission_pct=5.0,
            self_stake_pct=5.0,
            delegated_stake_usd=900_000.0,
            chain_inflation_rate_pct=3.0,
            annual_reward_usd=20_000.0,
        )]
        result = self.analyzer.analyze(validators)
        flags = result["validators"][0]["flags"]
        self.assertNotIn(FLAG_HIGH_SLASHING_RISK, flags)
        self.assertNotIn(FLAG_LOW_UPTIME, flags)
        self.assertNotIn(FLAG_HIGH_COMMISSION, flags)

    def test_marginal_cost_in_result(self):
        validators = [make_validator(
            stake_usd=1_000_000.0,
            operating_cost_usd_monthly=2_000.0,
        )]
        result = self.analyzer.analyze(validators)
        # 24000/1000000*100 = 2.4%
        self.assertAlmostEqual(
            result["validators"][0]["marginal_cost_per_stake_usd"], 2.4, places=4
        )

    def test_gross_vs_net_apy_relationship(self):
        validators = [make_validator(
            annual_reward_usd=50_000.0,
            stake_usd=1_000_000.0,
            operating_cost_usd_monthly=1_000.0,
        )]
        result = self.analyzer.analyze(validators)
        gross = result["validators"][0]["gross_apy_pct"]
        net = result["validators"][0]["net_apy_pct"]
        self.assertGreater(gross, net)

    def test_average_net_apy_in_aggregates(self):
        validators = [
            make_validator(protocol="A", annual_reward_usd=50_000.0,
                           operating_cost_usd_monthly=0.0, stake_usd=1_000_000.0),
            make_validator(protocol="B", annual_reward_usd=30_000.0,
                           operating_cost_usd_monthly=0.0, stake_usd=1_000_000.0),
        ]
        result = self.analyzer.analyze(validators)
        # A: 5.0%, B: 3.0% → avg = 4.0%
        self.assertAlmostEqual(result["aggregates"]["average_net_apy"], 4.0, places=3)

    def test_average_delegator_apy_in_aggregates(self):
        validators = [
            make_validator(protocol="A", annual_reward_usd=50_000.0,
                           stake_usd=1_000_000.0, operating_cost_usd_monthly=0.0,
                           commission_pct=0.0),
            make_validator(protocol="B", annual_reward_usd=30_000.0,
                           stake_usd=1_000_000.0, operating_cost_usd_monthly=0.0,
                           commission_pct=0.0),
        ]
        result = self.analyzer.analyze(validators)
        # gross A=5%, B=3%, both comm=0 → del_apy same as gross → avg=4%
        self.assertAlmostEqual(result["aggregates"]["average_delegator_apy"], 4.0, places=3)


if __name__ == "__main__":
    unittest.main()
