"""
MP-980: Tests for DeFiCrossProtocolYieldOptimizer
Run: python3 -m unittest spa_core.tests.test_defi_cross_protocol_yield_optimizer -v
≥80 tests, stdlib unittest only.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_cross_protocol_yield_optimizer import DeFiCrossProtocolYieldOptimizer


def _opp(**kwargs):
    """Build a minimal valid opportunity dict."""
    base = {
        "protocol": "TestProto",
        "asset": "USDC",
        "apy_pct": 10.0,
        "min_deposit_usd": 1000.0,
        "max_deposit_usd": 100_000.0,
        "gas_entry_usd": 5.0,
        "gas_exit_usd": 5.0,
        "lock_period_days": 0.0,
        "withdrawal_notice_hours": 0.0,
        "risk_score": 20.0,
        "correlation_with_others": {},
        "capacity_remaining_usd": 500_000.0,
    }
    base.update(kwargs)
    return base


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_opt_empty.json"}

    def test_empty_returns_dict(self):
        r = self.opt.optimize([], self.cfg)
        self.assertIsInstance(r, dict)

    def test_empty_opportunities_list(self):
        r = self.opt.optimize([], self.cfg)
        self.assertEqual(r["opportunities"], [])

    def test_empty_top_is_none(self):
        r = self.opt.optimize([], self.cfg)
        self.assertIsNone(r["top_opportunity"])

    def test_empty_worst_is_none(self):
        r = self.opt.optimize([], self.cfg)
        self.assertIsNone(r["worst_opportunity"])

    def test_empty_must_allocate_zero(self):
        r = self.opt.optimize([], self.cfg)
        self.assertEqual(r["must_allocate_count"], 0)

    def test_empty_recommended_summary_empty(self):
        r = self.opt.optimize([], self.cfg)
        self.assertEqual(r["recommended_allocation_summary"], [])

    def test_empty_total_capacity_zero(self):
        r = self.opt.optimize([], self.cfg)
        self.assertEqual(r["total_available_capacity_usd"], 0.0)

    def test_empty_config_preserved(self):
        r = self.opt.optimize([], self.cfg)
        self.assertIn("config_used", r)


class TestSingleOpportunityFields(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_opt_single.json"}

    def _run(self, **kwargs):
        return self.opt.optimize([_opp(**kwargs)], self.cfg)

    def test_protocol_in_output(self):
        r = self._run(protocol="Aave")
        self.assertEqual(r["opportunities"][0]["protocol"], "Aave")

    def test_asset_in_output(self):
        r = self._run(asset="DAI")
        self.assertEqual(r["opportunities"][0]["asset"], "DAI")

    def test_apy_pct_preserved(self):
        r = self._run(apy_pct=12.0)
        self.assertEqual(r["opportunities"][0]["apy_pct"], 12.0)

    def test_risk_score_preserved(self):
        r = self._run(risk_score=30.0)
        self.assertEqual(r["opportunities"][0]["risk_score"], 30.0)

    def test_annualized_gas_drag_present(self):
        r = self._run()
        self.assertIn("annualized_gas_drag_pct", r["opportunities"][0])

    def test_net_apy_present(self):
        r = self._run()
        self.assertIn("net_apy_pct", r["opportunities"][0])

    def test_risk_adjusted_present(self):
        r = self._run()
        self.assertIn("risk_adjusted_net_apy", r["opportunities"][0])

    def test_min_viable_capital_present(self):
        r = self._run()
        self.assertIn("min_viable_capital_usd", r["opportunities"][0])

    def test_efficient_allocation_pct_present(self):
        r = self._run()
        self.assertIn("efficient_allocation_pct", r["opportunities"][0])

    def test_label_present(self):
        r = self._run()
        self.assertIn("label", r["opportunities"][0])

    def test_flags_list(self):
        r = self._run()
        self.assertIsInstance(r["opportunities"][0]["flags"], list)

    def test_lock_period_in_output(self):
        r = self._run(lock_period_days=30.0)
        self.assertEqual(r["opportunities"][0]["lock_period_days"], 30.0)

    def test_capacity_in_output(self):
        r = self._run(capacity_remaining_usd=2_000_000.0)
        self.assertEqual(r["opportunities"][0]["capacity_remaining_usd"], 2_000_000.0)


class TestGasDragCalculation(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()

    def _run(self, gas_entry=10.0, gas_exit=10.0, hold_days=365, total_capital=100_000, **kw):
        cfg = {"total_capital_usd": total_capital, "position_hold_days": hold_days, "log_path": "/tmp/test_gas.json"}
        opp = _opp(gas_entry_usd=gas_entry, gas_exit_usd=gas_exit, **kw)
        return self.opt.optimize([opp], cfg)["opportunities"][0]

    def test_zero_gas_zero_drag(self):
        r = self._run(gas_entry=0.0, gas_exit=0.0)
        self.assertEqual(r["annualized_gas_drag_pct"], 0.0)

    def test_gas_drag_positive_when_gas_positive(self):
        r = self._run(gas_entry=50.0, gas_exit=50.0)
        self.assertGreater(r["annualized_gas_drag_pct"], 0.0)

    def test_net_apy_less_than_apy_when_gas_positive(self):
        r = self._run(gas_entry=50.0, gas_exit=50.0, apy_pct=10.0)
        self.assertLess(r["net_apy_pct"], 10.0)

    def test_shorter_hold_increases_gas_drag(self):
        r365 = self._run(hold_days=365)
        r30 = self._run(hold_days=30)
        self.assertGreater(r30["annualized_gas_drag_pct"], r365["annualized_gas_drag_pct"])

    def test_zero_gas_no_min_viable_capital(self):
        r = self._run(gas_entry=0.0, gas_exit=0.0)
        self.assertEqual(r["min_viable_capital_usd"], 0.0)

    def test_min_viable_capital_positive_when_gas_positive(self):
        r = self._run(gas_entry=10.0, gas_exit=10.0, apy_pct=10.0)
        self.assertGreater(r["min_viable_capital_usd"], 0.0)

    def test_min_viable_capital_none_when_zero_apy(self):
        r = self._run(gas_entry=10.0, gas_exit=10.0, apy_pct=0.0)
        self.assertIsNone(r["min_viable_capital_usd"])


class TestRiskAdjustedAPY(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_radj.json"}

    def _run(self, **kw):
        return self.opt.optimize([_opp(gas_entry_usd=0, gas_exit_usd=0, **kw)], self.cfg)["opportunities"][0]

    def test_zero_risk_full_apy(self):
        r = self._run(apy_pct=10.0, risk_score=0.0)
        self.assertAlmostEqual(r["risk_adjusted_net_apy"], 10.0, places=4)

    def test_full_risk_zero_radj(self):
        r = self._run(apy_pct=10.0, risk_score=100.0)
        self.assertAlmostEqual(r["risk_adjusted_net_apy"], 0.0, places=4)

    def test_fifty_risk_halves_apy(self):
        r = self._run(apy_pct=20.0, risk_score=50.0)
        self.assertAlmostEqual(r["risk_adjusted_net_apy"], 10.0, places=4)

    def test_risk_adj_less_than_net_apy_for_positive_risk(self):
        r = self._run(apy_pct=10.0, risk_score=30.0)
        self.assertLess(r["risk_adjusted_net_apy"], r["net_apy_pct"])


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_labels.json"}

    def _label(self, **kw):
        return self.opt.optimize([_opp(gas_entry_usd=0, gas_exit_usd=0, **kw)], self.cfg)["opportunities"][0]["label"]

    def test_must_allocate_high_radj(self):
        # risk_score=0 → radj = apy; need radj > 15%
        lbl = self._label(apy_pct=20.0, risk_score=0.0)
        self.assertEqual(lbl, "MUST_ALLOCATE")

    def test_recommended_radj_8_to_15(self):
        # risk_score=0, apy=10 → radj=10 → RECOMMENDED
        lbl = self._label(apy_pct=10.0, risk_score=0.0)
        self.assertEqual(lbl, "RECOMMENDED")

    def test_consider_radj_3_to_8(self):
        # apy=5, risk=0 → radj=5 → CONSIDER
        lbl = self._label(apy_pct=5.0, risk_score=0.0)
        self.assertEqual(lbl, "CONSIDER")

    def test_low_priority_radj_1_to_3(self):
        # apy=2, risk=0 → radj=2 → LOW_PRIORITY
        lbl = self._label(apy_pct=2.0, risk_score=0.0)
        self.assertEqual(lbl, "LOW_PRIORITY")

    def test_skip_radj_below_1(self):
        # apy=0.5, risk=0 → radj=0.5 → SKIP
        lbl = self._label(apy_pct=0.5, risk_score=0.0)
        self.assertEqual(lbl, "SKIP")

    def test_skip_zero_apy(self):
        lbl = self._label(apy_pct=0.0, risk_score=0.0)
        self.assertEqual(lbl, "SKIP")

    def test_skip_negative_radj(self):
        lbl = self._label(apy_pct=-5.0, risk_score=0.0)
        self.assertEqual(lbl, "SKIP")

    def test_gas_trap_forces_skip(self):
        # large gas relative to apy → GAS_TRAP → SKIP (bypass _label helper to pass gas)
        opp = _opp(apy_pct=5.0, risk_score=0.0,
                   gas_entry_usd=10000.0, gas_exit_usd=10000.0,
                   min_deposit_usd=100.0, max_deposit_usd=200.0)
        lbl = self.opt.optimize([opp], self.cfg)["opportunities"][0]["label"]
        self.assertEqual(lbl, "SKIP")

    def test_must_allocate_boundary(self):
        # exactly 15.0 → MUST_ALLOCATE (risk_adj > 15)
        lbl = self._label(apy_pct=15.1, risk_score=0.0)
        self.assertEqual(lbl, "MUST_ALLOCATE")

    def test_recommended_boundary_8(self):
        lbl = self._label(apy_pct=8.0, risk_score=0.0)
        self.assertEqual(lbl, "RECOMMENDED")

    def test_consider_boundary_3(self):
        lbl = self._label(apy_pct=3.0, risk_score=0.0)
        self.assertEqual(lbl, "CONSIDER")

    def test_low_priority_boundary_1(self):
        lbl = self._label(apy_pct=1.0, risk_score=0.0)
        self.assertEqual(lbl, "LOW_PRIORITY")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_flags.json"}

    def _flags(self, **kw):
        return self.opt.optimize([_opp(**kw)], self.cfg)["opportunities"][0]["flags"]

    def test_gas_trap_flag(self):
        # annualized gas > 50% of apy: huge gas on tiny position
        flags = self._flags(apy_pct=5.0, gas_entry_usd=10000, gas_exit_usd=10000,
                            min_deposit_usd=100, max_deposit_usd=200)
        self.assertIn("GAS_TRAP", flags)

    def test_no_gas_trap_flag_when_gas_small(self):
        flags = self._flags(apy_pct=10.0, gas_entry_usd=1.0, gas_exit_usd=1.0)
        self.assertNotIn("GAS_TRAP", flags)

    def test_capital_efficient_flag(self):
        # min_viable_capital < 1000: small gas, high apy
        flags = self._flags(apy_pct=20.0, gas_entry_usd=0.1, gas_exit_usd=0.1)
        self.assertIn("CAPITAL_EFFICIENT", flags)

    def test_high_capacity_flag(self):
        flags = self._flags(capacity_remaining_usd=2_000_000.0)
        self.assertIn("HIGH_CAPACITY", flags)

    def test_no_high_capacity_when_small(self):
        flags = self._flags(capacity_remaining_usd=500_000.0)
        self.assertNotIn("HIGH_CAPACITY", flags)

    def test_low_lock_flag(self):
        flags = self._flags(lock_period_days=0.0)
        self.assertIn("LOW_LOCK", flags)

    def test_no_low_lock_when_7_days(self):
        flags = self._flags(lock_period_days=7.0)
        self.assertNotIn("LOW_LOCK", flags)

    def test_low_lock_at_6_days(self):
        flags = self._flags(lock_period_days=6.0)
        self.assertIn("LOW_LOCK", flags)

    def test_diversification_benefit_no_correlations(self):
        flags = self._flags(correlation_with_others={})
        self.assertIn("DIVERSIFICATION_BENEFIT", flags)

    def test_diversification_benefit_low_corr(self):
        flags = self._flags(correlation_with_others={"P2": 0.1, "P3": 0.2})
        self.assertIn("DIVERSIFICATION_BENEFIT", flags)

    def test_no_diversification_benefit_high_corr(self):
        flags = self._flags(correlation_with_others={"P2": 0.8, "P3": 0.9})
        self.assertNotIn("DIVERSIFICATION_BENEFIT", flags)

    def test_gas_trap_with_zero_apy(self):
        flags = self._flags(apy_pct=0.0, gas_entry_usd=10.0, gas_exit_usd=10.0)
        self.assertIn("GAS_TRAP", flags)

    def test_no_gas_trap_zero_gas_zero_apy(self):
        flags = self._flags(apy_pct=0.0, gas_entry_usd=0.0, gas_exit_usd=0.0)
        self.assertNotIn("GAS_TRAP", flags)


class TestEfficientAllocation(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()

    def _run(self, opps, cfg=None):
        cfg = cfg or {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_eff.json"}
        return self.opt.optimize(opps, cfg)

    def test_single_opp_gets_100_pct(self):
        r = self._run([_opp()])
        self.assertAlmostEqual(r["opportunities"][0]["efficient_allocation_pct"], 100.0, places=1)

    def test_two_equal_risk_opps_get_50_each(self):
        opps = [_opp(protocol="A", risk_score=50.0), _opp(protocol="B", risk_score=50.0)]
        r = self._run(opps)
        pcts = [o["efficient_allocation_pct"] for o in r["opportunities"]]
        self.assertAlmostEqual(pcts[0], 50.0, places=1)
        self.assertAlmostEqual(pcts[1], 50.0, places=1)

    def test_lower_risk_gets_higher_allocation(self):
        opps = [_opp(protocol="Low", risk_score=10.0), _opp(protocol="High", risk_score=90.0)]
        r = self._run(opps)
        opps_out = {o["protocol"]: o["efficient_allocation_pct"] for o in r["opportunities"]}
        self.assertGreater(opps_out["Low"], opps_out["High"])

    def test_allocation_sums_to_100(self):
        opps = [_opp(protocol=f"P{i}", risk_score=float(10 + i * 5)) for i in range(5)]
        r = self._run(opps)
        total = sum(o["efficient_allocation_pct"] for o in r["opportunities"])
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_internal_inv_risk_removed(self):
        r = self._run([_opp()])
        self.assertNotIn("_inv_risk", r["opportunities"][0])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_agg.json"}

    def _run(self, opps):
        return self.opt.optimize(opps, self.cfg)

    def test_top_opportunity_correct(self):
        opps = [
            _opp(protocol="Best", apy_pct=30.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
            _opp(protocol="Worst", apy_pct=5.0, risk_score=80.0, gas_entry_usd=0, gas_exit_usd=0),
        ]
        r = self._run(opps)
        self.assertEqual(r["top_opportunity"], "Best")

    def test_worst_opportunity_correct(self):
        opps = [
            _opp(protocol="Best", apy_pct=30.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
            _opp(protocol="Worst", apy_pct=5.0, risk_score=80.0, gas_entry_usd=0, gas_exit_usd=0),
        ]
        r = self._run(opps)
        self.assertEqual(r["worst_opportunity"], "Worst")

    def test_must_allocate_count_correct(self):
        opps = [
            _opp(protocol="MA1", apy_pct=20.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
            _opp(protocol="MA2", apy_pct=18.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
            _opp(protocol="Skip", apy_pct=0.5, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
        ]
        r = self._run(opps)
        self.assertEqual(r["must_allocate_count"], 2)

    def test_total_capacity_sum(self):
        opps = [
            _opp(protocol="A", capacity_remaining_usd=500_000.0),
            _opp(protocol="B", capacity_remaining_usd=300_000.0),
        ]
        r = self._run(opps)
        self.assertAlmostEqual(r["total_available_capacity_usd"], 800_000.0)

    def test_recommended_summary_includes_must_allocate(self):
        opps = [_opp(protocol="MA", apy_pct=25.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0)]
        r = self._run(opps)
        protos = [x[0] for x in r["recommended_allocation_summary"]]
        self.assertIn("MA", protos)

    def test_recommended_summary_excludes_skip(self):
        opps = [_opp(protocol="Skipped", apy_pct=0.1, risk_score=90.0, gas_entry_usd=0, gas_exit_usd=0)]
        r = self._run(opps)
        protos = [x[0] for x in r["recommended_allocation_summary"]]
        self.assertNotIn("Skipped", protos)

    def test_top_risk_adj_apy_in_result(self):
        opps = [_opp(apy_pct=10.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0)]
        r = self._run(opps)
        self.assertAlmostEqual(r["top_opportunity_risk_adj_apy"], 10.0, places=4)

    def test_worst_risk_adj_apy_in_result(self):
        opps = [
            _opp(protocol="A", apy_pct=20.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0),
            _opp(protocol="B", apy_pct=2.0, risk_score=50.0, gas_entry_usd=0, gas_exit_usd=0),
        ]
        r = self._run(opps)
        self.assertLess(r["worst_opportunity_risk_adj_apy"], r["top_opportunity_risk_adj_apy"])


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.tmp = tempfile.mktemp(suffix=".json")
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": self.tmp}

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        tmp2 = self.tmp + ".tmp"
        if os.path.exists(tmp2):
            os.remove(tmp2)

    def test_log_file_created(self):
        self.opt.optimize([_opp()], self.cfg)
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_is_json_list(self):
        self.opt.optimize([_opp()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.opt.optimize([_opp()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_opportunity_count(self):
        self.opt.optimize([_opp(), _opp(protocol="B")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["opportunity_count"], 2)

    def test_log_entry_has_must_allocate_count(self):
        self.opt.optimize([_opp(apy_pct=20.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0)], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["must_allocate_count"], 1)

    def test_log_accumulates(self):
        for _ in range(3):
            self.opt.optimize([_opp()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_cap_100(self):
        for _ in range(110):
            self.opt.optimize([_opp()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_cap_keeps_latest(self):
        for i in range(105):
            cfg = dict(self.cfg)
            cfg["_note"] = i  # different config each time (no effect on log)
            self.opt.optimize([_opp(protocol=f"P{i}")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_atomic_write_no_tmp_left(self):
        self.opt.optimize([_opp()], self.cfg)
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))

    def test_log_top_opportunity_recorded(self):
        self.opt.optimize([_opp(protocol="Aave")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["top_opportunity"], "Aave")


class TestConfigDefaults(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()

    def test_default_capital_used(self):
        cfg = {"log_path": "/tmp/test_defaults.json"}
        r = self.opt.optimize([_opp()], cfg)
        self.assertEqual(r["config_used"]["total_capital_usd"], 100_000.0)

    def test_default_hold_days_used(self):
        cfg = {"log_path": "/tmp/test_defaults2.json"}
        r = self.opt.optimize([_opp()], cfg)
        self.assertEqual(r["config_used"]["position_hold_days"], 365)


class TestMultipleOpportunities(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_multi.json"}

    def test_five_opportunities_analyzed(self):
        opps = [_opp(protocol=f"P{i}", apy_pct=float(5+i)) for i in range(5)]
        r = self.opt.optimize(opps, self.cfg)
        self.assertEqual(len(r["opportunities"]), 5)

    def test_all_labels_valid(self):
        valid = {"MUST_ALLOCATE", "RECOMMENDED", "CONSIDER", "LOW_PRIORITY", "SKIP"}
        opps = [_opp(protocol=f"P{i}", apy_pct=float(i), risk_score=float(i*10 % 100),
                     gas_entry_usd=0, gas_exit_usd=0) for i in range(6)]
        r = self.opt.optimize(opps, self.cfg)
        for o in r["opportunities"]:
            self.assertIn(o["label"], valid)

    def test_all_have_efficient_allocation(self):
        opps = [_opp(protocol=f"P{i}") for i in range(4)]
        r = self.opt.optimize(opps, self.cfg)
        for o in r["opportunities"]:
            self.assertIsNotNone(o["efficient_allocation_pct"])

    def test_allocation_sum_still_100_for_many(self):
        opps = [_opp(protocol=f"P{i}", risk_score=float(10+i*3)) for i in range(10)]
        r = self.opt.optimize(opps, self.cfg)
        total = sum(o["efficient_allocation_pct"] for o in r["opportunities"])
        self.assertAlmostEqual(total, 100.0, places=1)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()
        self.cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_edge.json"}

    def _run(self, **kw):
        return self.opt.optimize([_opp(**kw)], self.cfg)["opportunities"][0]

    def test_risk_score_zero(self):
        r = self._run(risk_score=0.0, apy_pct=10.0, gas_entry_usd=0, gas_exit_usd=0)
        self.assertAlmostEqual(r["risk_adjusted_net_apy"], 10.0, places=4)

    def test_risk_score_100(self):
        r = self._run(risk_score=100.0, apy_pct=10.0, gas_entry_usd=0, gas_exit_usd=0)
        self.assertAlmostEqual(r["risk_adjusted_net_apy"], 0.0, places=4)

    def test_very_high_apy(self):
        r = self._run(apy_pct=999.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0)
        self.assertEqual(r["label"], "MUST_ALLOCATE")

    def test_very_high_capacity(self):
        r = self._run(capacity_remaining_usd=1_000_001.0)
        self.assertIn("HIGH_CAPACITY", r["flags"])

    def test_negative_apy_is_skip(self):
        r = self._run(apy_pct=-5.0, risk_score=0.0, gas_entry_usd=0, gas_exit_usd=0)
        self.assertEqual(r["label"], "SKIP")

    def test_hold_days_1_not_crash(self):
        cfg = {"total_capital_usd": 100_000, "position_hold_days": 1, "log_path": "/tmp/test_1day.json"}
        r = self.opt.optimize([_opp()], cfg)
        self.assertIn("opportunities", r)

    def test_no_correlations_gets_diversification_benefit(self):
        r = self._run(correlation_with_others={})
        self.assertIn("DIVERSIFICATION_BENEFIT", r["flags"])

    def test_high_abs_negative_correlation_no_div_benefit(self):
        r = self._run(correlation_with_others={"P2": -0.9, "P3": -0.85})
        self.assertNotIn("DIVERSIFICATION_BENEFIT", r["flags"])

    def test_string_protocol_preserved(self):
        r = self._run(protocol="compound-v3")
        self.assertEqual(r["protocol"], "compound-v3")

    def test_high_lock_no_low_lock_flag(self):
        r = self._run(lock_period_days=180.0)
        self.assertNotIn("LOW_LOCK", r["flags"])


class TestMinViableCapitalFormula(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiCrossProtocolYieldOptimizer()

    def test_min_viable_inversely_proportional_to_apy(self):
        cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_mvc.json"}
        r10 = self.opt.optimize([_opp(apy_pct=10.0, gas_entry_usd=50, gas_exit_usd=50)], cfg)["opportunities"][0]
        r20 = self.opt.optimize([_opp(apy_pct=20.0, gas_entry_usd=50, gas_exit_usd=50)], cfg)["opportunities"][0]
        self.assertGreater(r10["min_viable_capital_usd"], r20["min_viable_capital_usd"])

    def test_min_viable_proportional_to_gas(self):
        cfg = {"total_capital_usd": 100_000, "position_hold_days": 365, "log_path": "/tmp/test_mvc2.json"}
        r_lg = self.opt.optimize([_opp(apy_pct=10.0, gas_entry_usd=100, gas_exit_usd=100)], cfg)["opportunities"][0]
        r_sm = self.opt.optimize([_opp(apy_pct=10.0, gas_entry_usd=10, gas_exit_usd=10)], cfg)["opportunities"][0]
        self.assertGreater(r_lg["min_viable_capital_usd"], r_sm["min_viable_capital_usd"])


if __name__ == "__main__":
    unittest.main()
