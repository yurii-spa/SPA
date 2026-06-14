"""
Tests for MP-961: ProtocolEmissionScheduleImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_emission_schedule_impact_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_emission_schedule_impact_analyzer import (
    ProtocolEmissionScheduleImpactAnalyzer,
    _atomic_write,
    _load_log,
)


def _base_schedule(**overrides):
    base = {
        "protocol": "CompoundV3",
        "token_name": "COMP",
        "current_price_usd": 50.0,
        "circulating_supply": 5_000_000.0,
        "max_supply": 10_000_000.0,
        "daily_emission_tokens": 2000.0,
        "emission_unlock_events": [],
        "current_buy_pressure_usd_daily": 50_000.0,
        "staking_sink_rate_pct": 10.0,
        "burn_rate_tokens_daily": 100.0,
    }
    base.update(overrides)
    return base


def _unlock_event(days_from_now=60, tokens=50000, recipient="ecosystem"):
    return {"date_days_from_now": days_from_now, "tokens_unlocked": tokens, "recipient": recipient}


class TestProtocolEmissionScheduleImpactAnalyzerBasic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "em_log.json")
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(log_path=self.log_path)

    def test_returns_dict(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertIsInstance(result, dict)

    def test_top_level_keys(self):
        result = self.analyzer.analyze([_base_schedule()])
        for k in ("timestamp", "schedule_count", "schedules", "aggregate"):
            self.assertIn(k, result)

    def test_schedule_count(self):
        result = self.analyzer.analyze([_base_schedule(), _base_schedule()])
        self.assertEqual(result["schedule_count"], 2)

    def test_empty_schedules(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["schedule_count"], 0)
        self.assertEqual(result["schedules"], [])

    def test_single_schedule_in_schedules(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertEqual(len(result["schedules"]), 1)

    def test_schedule_result_keys(self):
        result = self.analyzer.analyze([_base_schedule()])
        sched = result["schedules"][0]
        for k in ("protocol", "token_name", "net_daily_emission", "sell_pressure_usd_daily",
                  "price_impact_ratio", "inflation_rate_annual_pct", "months_to_max_supply",
                  "nearest_unlock_event", "emission_label", "flags"):
            self.assertIn(k, sched)

    def test_protocol_label(self):
        result = self.analyzer.analyze([_base_schedule(protocol="Aave")])
        self.assertEqual(result["schedules"][0]["protocol"], "Aave")

    def test_token_name_label(self):
        result = self.analyzer.analyze([_base_schedule(token_name="AAVE")])
        self.assertEqual(result["schedules"][0]["token_name"], "AAVE")

    def test_timestamp_present(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertIn("Z", result["timestamp"])


class TestNetDailyEmission(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_net_emission_basic(self):
        # daily=2000, burn=100, staking=10% of 2000=200 → net=1700
        s = _base_schedule(daily_emission_tokens=2000, burn_rate_tokens_daily=100,
                           staking_sink_rate_pct=10)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["net_daily_emission"], 1700.0, places=3)

    def test_net_emission_zero_burn_zero_staking(self):
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["net_daily_emission"], 1000.0, places=3)

    def test_net_emission_can_be_negative(self):
        # burn > emission → deflation
        s = _base_schedule(daily_emission_tokens=100, burn_rate_tokens_daily=200,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertLess(result["schedules"][0]["net_daily_emission"], 0)

    def test_staking_sink_100pct(self):
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=100)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["net_daily_emission"], 0.0, places=3)

    def test_sell_pressure_usd(self):
        # net = 1700, price = 50 → sell_pressure = 85000
        s = _base_schedule(daily_emission_tokens=2000, burn_rate_tokens_daily=100,
                           staking_sink_rate_pct=10, current_price_usd=50)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["sell_pressure_usd_daily"], 85000.0, places=1)

    def test_price_impact_ratio(self):
        # sell=85000, buy=50000 → ratio = 1.7
        s = _base_schedule(daily_emission_tokens=2000, burn_rate_tokens_daily=100,
                           staking_sink_rate_pct=10, current_price_usd=50,
                           current_buy_pressure_usd_daily=50000)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["price_impact_ratio"], 1.7, places=3)


class TestInflationRate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_inflation_rate_formula(self):
        # net=1000/day, circ=1_000_000 → annual = (1000*365/1_000_000)*100 = 36.5%
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0, circulating_supply=1_000_000)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["inflation_rate_annual_pct"], 36.5, places=2)

    def test_zero_emission_zero_inflation(self):
        s = _base_schedule(daily_emission_tokens=0, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["inflation_rate_annual_pct"], 0.0, places=3)

    def test_negative_inflation_deflationary(self):
        s = _base_schedule(daily_emission_tokens=100, burn_rate_tokens_daily=200,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertLess(result["schedules"][0]["inflation_rate_annual_pct"], 0)


class TestEmissionLabels(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def _sched_with_net(self, net_daily, circ=1_000_000):
        # net_daily = emission - burn → set burn=0, emission=net_daily
        return _base_schedule(daily_emission_tokens=max(0.0, net_daily),
                              burn_rate_tokens_daily=max(0.0, -net_daily),
                              staking_sink_rate_pct=0, circulating_supply=circ)

    def test_deflationary(self):
        s = self._sched_with_net(-100)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "DEFLATIONARY")

    def test_ultra_low(self):
        # 1% annual: net = 1_000_000 * 0.01 / 365 ≈ 27.4/day
        net = 1_000_000 * 0.01 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "ULTRA_LOW")

    def test_low_inflation(self):
        # 5% annual: net = 1_000_000 * 0.05 / 365 ≈ 136.9/day
        net = 1_000_000 * 0.05 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "LOW_INFLATION")

    def test_moderate_inflation(self):
        # 20% annual
        net = 1_000_000 * 0.20 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "MODERATE_INFLATION")

    def test_high_inflation(self):
        # 60% annual
        net = 1_000_000 * 0.60 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "HIGH_INFLATION")

    def test_hyperinflationary(self):
        # 200% annual
        net = 1_000_000 * 2.0 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "HYPERINFLATIONARY")

    def test_boundary_ultra_low_2pct(self):
        net = 1_000_000 * 0.02 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "ULTRA_LOW")

    def test_boundary_low_inflation_just_above_2pct(self):
        net = 1_000_000 * 0.0201 / 365
        s = self._sched_with_net(net)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "LOW_INFLATION")


class TestMonthsToMaxSupply(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_months_to_max_supply_computed(self):
        # remaining=5M tokens, net=1000/day → 5M/(1000*30) = 166.67 months
        s = _base_schedule(circulating_supply=5_000_000, max_supply=10_000_000,
                           daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        expected = 5_000_000 / 1000 / 30
        self.assertAlmostEqual(result["schedules"][0]["months_to_max_supply"], expected, places=1)

    def test_months_to_max_supply_none_no_max(self):
        s = _base_schedule(max_supply=0)
        result = self.analyzer.analyze([s])
        self.assertIsNone(result["schedules"][0]["months_to_max_supply"])

    def test_months_to_max_supply_zero_when_at_max(self):
        s = _base_schedule(circulating_supply=10_000_000, max_supply=10_000_000,
                           daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["months_to_max_supply"], 0.0, places=3)

    def test_months_to_max_supply_none_deflationary(self):
        # Net emission negative → no meaningful months_to_max_supply
        s = _base_schedule(circulating_supply=5_000_000, max_supply=10_000_000,
                           daily_emission_tokens=100, burn_rate_tokens_daily=200,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertIsNone(result["schedules"][0]["months_to_max_supply"])


class TestNearestUnlock(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_nearest_unlock_none_when_empty(self):
        s = _base_schedule(emission_unlock_events=[])
        result = self.analyzer.analyze([s])
        self.assertIsNone(result["schedules"][0]["nearest_unlock_event"])

    def test_nearest_unlock_picks_closest(self):
        events = [_unlock_event(90), _unlock_event(30), _unlock_event(180)]
        s = _base_schedule(emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["nearest_unlock_event"]["date_days_from_now"], 30.0)

    def test_nearest_unlock_has_recipient(self):
        events = [_unlock_event(10, recipient="team")]
        s = _base_schedule(emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["nearest_unlock_event"]["recipient"], "team")

    def test_nearest_unlock_has_tokens(self):
        events = [_unlock_event(10, tokens=500_000)]
        s = _base_schedule(emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["nearest_unlock_event"]["tokens_unlocked"], 500_000.0)

    def test_nearest_unlock_ignores_negative_days(self):
        events = [{"date_days_from_now": -5, "tokens_unlocked": 1000, "recipient": "team"},
                  _unlock_event(20)]
        s = _base_schedule(emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["nearest_unlock_event"]["date_days_from_now"], 20.0)

    def test_nearest_unlock_all_past_returns_none(self):
        events = [{"date_days_from_now": -10, "tokens_unlocked": 1000, "recipient": "team"}]
        s = _base_schedule(emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertIsNone(result["schedules"][0]["nearest_unlock_event"])


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_imminent_unlock_flag(self):
        # 25 days, 5% of 5M = 250000 tokens → IMMINENT_UNLOCK
        events = [_unlock_event(25, tokens=250_000, recipient="ecosystem")]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertIn("IMMINENT_UNLOCK", result["schedules"][0]["flags"])

    def test_no_imminent_unlock_too_far(self):
        events = [_unlock_event(60, tokens=250_000)]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertNotIn("IMMINENT_UNLOCK", result["schedules"][0]["flags"])

    def test_no_imminent_unlock_small_tokens(self):
        # < 1% of supply
        events = [_unlock_event(10, tokens=1000)]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertNotIn("IMMINENT_UNLOCK", result["schedules"][0]["flags"])

    def test_team_unlock_risk_flag(self):
        events = [_unlock_event(10, tokens=500_000, recipient="team")]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertIn("TEAM_UNLOCK_RISK", result["schedules"][0]["flags"])
        self.assertIn("IMMINENT_UNLOCK", result["schedules"][0]["flags"])

    def test_no_team_unlock_risk_ecosystem(self):
        events = [_unlock_event(10, tokens=500_000, recipient="ecosystem")]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertNotIn("TEAM_UNLOCK_RISK", result["schedules"][0]["flags"])

    def test_sell_pressure_dominates_flag(self):
        # sell > 2× buy: net=2000, price=100 → sell=200000; buy=50000 → ratio=4
        s = _base_schedule(daily_emission_tokens=2000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0, current_price_usd=100,
                           current_buy_pressure_usd_daily=50000)
        result = self.analyzer.analyze([s])
        self.assertIn("SELL_PRESSURE_DOMINATES", result["schedules"][0]["flags"])

    def test_no_sell_pressure_dominates_balanced(self):
        # sell = buy
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0, current_price_usd=50,
                           current_buy_pressure_usd_daily=50000)
        result = self.analyzer.analyze([s])
        self.assertNotIn("SELL_PRESSURE_DOMINATES", result["schedules"][0]["flags"])

    def test_burn_offsetting_flag(self):
        # burn = 600 > 50% of emission=1000
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=600,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertIn("BURN_OFFSETTING", result["schedules"][0]["flags"])

    def test_no_burn_offsetting_low_burn(self):
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=200,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertNotIn("BURN_OFFSETTING", result["schedules"][0]["flags"])

    def test_burn_offsetting_exactly_50pct(self):
        # burn = 50% of emission = borderline (> 0.5 required for flag)
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=500,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertNotIn("BURN_OFFSETTING", result["schedules"][0]["flags"])

    def test_near_max_supply_flag(self):
        # circ = 95% of max
        s = _base_schedule(circulating_supply=9_500_000, max_supply=10_000_000)
        result = self.analyzer.analyze([s])
        self.assertIn("NEAR_MAX_SUPPLY", result["schedules"][0]["flags"])

    def test_no_near_max_supply_flag(self):
        s = _base_schedule(circulating_supply=5_000_000, max_supply=10_000_000)
        result = self.analyzer.analyze([s])
        self.assertNotIn("NEAR_MAX_SUPPLY", result["schedules"][0]["flags"])

    def test_near_max_supply_boundary_90pct(self):
        # exactly 90% → NOT flagged (needs > 0.9)
        s = _base_schedule(circulating_supply=9_000_000, max_supply=10_000_000)
        result = self.analyzer.analyze([s])
        self.assertNotIn("NEAR_MAX_SUPPLY", result["schedules"][0]["flags"])

    def test_flags_is_list(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertIsInstance(result["schedules"][0]["flags"], list)

    def test_no_flags_clean_schedule(self):
        s = _base_schedule(daily_emission_tokens=100, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0,
                           current_price_usd=1, current_buy_pressure_usd_daily=1_000_000,
                           circulating_supply=5_000_000, max_supply=10_000_000,
                           emission_unlock_events=[])
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["flags"], [])

    def test_multiple_flags_simultaneously(self):
        events = [_unlock_event(10, tokens=500_000, recipient="team")]
        s = _base_schedule(circulating_supply=5_000_000, max_supply=5_500_000,
                           daily_emission_tokens=2000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0, current_price_usd=100,
                           current_buy_pressure_usd_daily=50_000,
                           emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        flags = result["schedules"][0]["flags"]
        self.assertIn("IMMINENT_UNLOCK", flags)
        self.assertIn("TEAM_UNLOCK_RISK", flags)
        self.assertIn("SELL_PRESSURE_DOMINATES", flags)
        self.assertIn("NEAR_MAX_SUPPLY", flags)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_empty_aggregate(self):
        result = self.analyzer.analyze([])
        agg = result["aggregate"]
        self.assertIsNone(agg["most_inflationary"])
        self.assertIsNone(agg["most_deflationary"])
        self.assertEqual(agg["average_inflation_rate"], 0.0)
        self.assertEqual(agg["imminent_unlock_count"], 0)
        self.assertEqual(agg["deflationary_count"], 0)

    def test_most_inflationary(self):
        s1 = _base_schedule(protocol="A", daily_emission_tokens=10000, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        s2 = _base_schedule(protocol="B", daily_emission_tokens=100, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s1, s2])
        self.assertEqual(result["aggregate"]["most_inflationary"]["protocol"], "A")

    def test_most_deflationary(self):
        s1 = _base_schedule(protocol="A", daily_emission_tokens=10000, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        s2 = _base_schedule(protocol="B", daily_emission_tokens=0, burn_rate_tokens_daily=500,
                            staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s1, s2])
        self.assertEqual(result["aggregate"]["most_deflationary"]["protocol"], "B")

    def test_average_inflation_rate(self):
        # Two schedules with 20% each → avg = 20%
        net = 5_000_000 * 0.20 / 365
        s1 = _base_schedule(protocol="A", daily_emission_tokens=net, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0, circulating_supply=5_000_000)
        s2 = _base_schedule(protocol="B", daily_emission_tokens=net, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0, circulating_supply=5_000_000)
        result = self.analyzer.analyze([s1, s2])
        self.assertAlmostEqual(result["aggregate"]["average_inflation_rate"], 20.0, places=2)

    def test_imminent_unlock_count(self):
        events = [_unlock_event(10, tokens=500_000, recipient="ecosystem")]
        s1 = _base_schedule(protocol="A", circulating_supply=5_000_000, emission_unlock_events=events)
        s2 = _base_schedule(protocol="B", emission_unlock_events=[])
        result = self.analyzer.analyze([s1, s2])
        self.assertEqual(result["aggregate"]["imminent_unlock_count"], 1)

    def test_deflationary_count(self):
        s1 = _base_schedule(protocol="A", daily_emission_tokens=0, burn_rate_tokens_daily=500,
                            staking_sink_rate_pct=0)
        s2 = _base_schedule(protocol="B", daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s1, s2])
        self.assertEqual(result["aggregate"]["deflationary_count"], 1)

    def test_single_schedule_agg(self):
        result = self.analyzer.analyze([_base_schedule()])
        agg = result["aggregate"]
        self.assertEqual(agg["most_inflationary"]["protocol"], agg["most_deflationary"]["protocol"])

    def test_aggregate_has_all_keys(self):
        result = self.analyzer.analyze([_base_schedule()])
        agg = result["aggregate"]
        for k in ("most_inflationary", "most_deflationary", "average_inflation_rate",
                  "imminent_unlock_count", "deflationary_count"):
            self.assertIn(k, agg)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "em_log.json")
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(log_path=self.log_path)

    def test_log_created(self):
        self.analyzer.analyze([_base_schedule()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.analyzer.analyze([_base_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count(self):
        self.analyzer.analyze([_base_schedule()])
        self.analyzer.analyze([_base_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_ts(self):
        self.analyzer.analyze([_base_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_schedule_count(self):
        self.analyzer.analyze([_base_schedule(), _base_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["schedule_count"], 2)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.analyzer.analyze([_base_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_disabled(self):
        self.analyzer.analyze([_base_schedule()], config={"log_enabled": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_custom_path(self):
        custom = os.path.join(self.tmpdir, "custom.json")
        self.analyzer.analyze([_base_schedule()], config={"log_path": custom})
        self.assertTrue(os.path.exists(custom))


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"x": 42})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "value")

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["v"], 2)

    def test_load_log_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            result = _load_log(os.path.join(d, "missing.json"))
        self.assertEqual(result, [])

    def test_load_log_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("{invalid}")
            result = _load_log(path)
        self.assertEqual(result, [])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolEmissionScheduleImpactAnalyzer(
            log_path=os.path.join(self.tmpdir, "log.json"))

    def test_default_protocol_name(self):
        result = self.analyzer.analyze([{}])
        self.assertEqual(result["schedules"][0]["protocol"], "unknown")

    def test_default_token_name(self):
        result = self.analyzer.analyze([{}])
        self.assertEqual(result["schedules"][0]["token_name"], "TOKEN")

    def test_many_schedules(self):
        scheds = [_base_schedule(protocol=f"P{i}") for i in range(50)]
        result = self.analyzer.analyze(scheds)
        self.assertEqual(result["schedule_count"], 50)
        self.assertEqual(len(result["schedules"]), 50)

    def test_staking_sink_clamped_above_100(self):
        s = _base_schedule(daily_emission_tokens=1000, staking_sink_rate_pct=200)
        result = self.analyzer.analyze([s])
        # Absorbed = min(200,100)/100 * 1000 = 1000
        self.assertAlmostEqual(result["schedules"][0]["staking_absorbed_daily"], 1000.0, places=3)

    def test_staking_sink_clamped_below_0(self):
        s = _base_schedule(daily_emission_tokens=1000, staking_sink_rate_pct=-10)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["staking_absorbed_daily"], 0.0, places=3)

    def test_zero_price_zero_sell_pressure(self):
        s = _base_schedule(current_price_usd=0.0, daily_emission_tokens=1000,
                           burn_rate_tokens_daily=0, staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertAlmostEqual(result["schedules"][0]["sell_pressure_usd_daily"], 0.0, places=6)

    def test_meta_fields_present(self):
        result = self.analyzer.analyze([_base_schedule()])
        sched = result["schedules"][0]
        self.assertIn("staking_absorbed_daily", sched)
        self.assertIn("burn_rate_tokens_daily", sched)
        self.assertIn("current_price_usd", sched)
        self.assertIn("circulating_supply", sched)

    def test_three_schedules_agg(self):
        s1 = _base_schedule(protocol="A", daily_emission_tokens=10000, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        s2 = _base_schedule(protocol="B", daily_emission_tokens=500, burn_rate_tokens_daily=0,
                            staking_sink_rate_pct=0)
        s3 = _base_schedule(protocol="C", daily_emission_tokens=0, burn_rate_tokens_daily=300,
                            staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s1, s2, s3])
        self.assertEqual(result["aggregate"]["most_inflationary"]["protocol"], "A")
        self.assertEqual(result["aggregate"]["most_deflationary"]["protocol"], "C")
        self.assertEqual(result["aggregate"]["deflationary_count"], 1)

    def test_near_max_supply_boundary_91pct(self):
        s = _base_schedule(circulating_supply=9_100_000, max_supply=10_000_000)
        result = self.analyzer.analyze([s])
        self.assertIn("NEAR_MAX_SUPPLY", result["schedules"][0]["flags"])

    def test_sell_pressure_ratio_boundary_exactly_2(self):
        # Ratio = exactly 2.0 → NOT flagged (needs > 2)
        s = _base_schedule(daily_emission_tokens=1000, burn_rate_tokens_daily=0,
                           staking_sink_rate_pct=0, current_price_usd=100,
                           current_buy_pressure_usd_daily=50_000)
        result = self.analyzer.analyze([s])
        self.assertNotIn("SELL_PRESSURE_DOMINATES", result["schedules"][0]["flags"])

    def test_unlock_recipient_founder_triggers_team_risk(self):
        events = [_unlock_event(10, tokens=500_000, recipient="founder")]
        s = _base_schedule(circulating_supply=5_000_000, emission_unlock_events=events)
        result = self.analyzer.analyze([s])
        self.assertIn("TEAM_UNLOCK_RISK", result["schedules"][0]["flags"])

    def test_inflation_label_in_schedule(self):
        s = _base_schedule(daily_emission_tokens=0, burn_rate_tokens_daily=100,
                           staking_sink_rate_pct=0)
        result = self.analyzer.analyze([s])
        self.assertEqual(result["schedules"][0]["emission_label"], "DEFLATIONARY")

    def test_price_impact_ratio_field_positive(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertGreater(result["schedules"][0]["price_impact_ratio"], 0)

    def test_net_emission_stored_in_result(self):
        result = self.analyzer.analyze([_base_schedule()])
        self.assertIn("net_daily_emission", result["schedules"][0])


if __name__ == "__main__":
    unittest.main()
