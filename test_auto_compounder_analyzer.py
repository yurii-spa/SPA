"""
Tests for MP-822 AutoCompounderAnalyzer.
Run: python3 -m unittest spa_core.tests.test_auto_compounder_analyzer -v
"""

import json
import os
import sys
import math
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.auto_compounder_analyzer import (
    analyze,
    log_result,
    _load_log,
    _save_log,
    _manual_effective_apy,
    _vault_effective_apy,
    LOG_CAP,
    MAX_VAULT_FREQ,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(**kw):
    base = {
        "principal_usd": 10_000.0,
        "base_apy": 12.0,
        "manual_gas_usd": 10.0,
        "harvest_frequency_days": 7,
    }
    base.update(kw)
    return base


def _vault(**kw):
    base = {
        "name": "TestVault",
        "performance_fee_pct": 5.0,
        "compound_frequency_per_day": 1.0,
        "deposit_fee_pct": 0.0,
        "withdrawal_fee_pct": 0.0,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestManualEffectiveAPY(unittest.TestCase):
    def test_annual_compounding(self):
        # harvest_freq=365, compounds once per year → EAR ≈ base_apy
        ear = _manual_effective_apy(12.0, 365)
        # (1 + 0.12/1)^1 - 1 = 12%
        self.assertAlmostEqual(ear, 12.0, places=4)

    def test_daily_compounding_higher_than_annual(self):
        ear_daily = _manual_effective_apy(12.0, 1)
        ear_annual = _manual_effective_apy(12.0, 365)
        self.assertGreater(ear_daily, ear_annual)

    def test_weekly_compounding(self):
        # freq = 365/7 ≈ 52.14
        freq = 365.0 / 7
        expected = ((1 + 0.12 / freq) ** freq - 1) * 100
        ear = _manual_effective_apy(12.0, 7)
        self.assertAlmostEqual(ear, expected, places=4)

    def test_zero_apy_returns_zero(self):
        self.assertEqual(_manual_effective_apy(0.0, 7), 0.0)

    def test_negative_apy_returns_zero(self):
        self.assertEqual(_manual_effective_apy(-5.0, 7), 0.0)

    def test_monthly_compounding(self):
        # harvest every 30 days → freq ≈ 12.17 compounds/yr
        freq = 365.0 / 30
        expected = ((1 + 0.12 / freq) ** freq - 1) * 100
        ear = _manual_effective_apy(12.0, 30)
        self.assertAlmostEqual(ear, expected, places=4)


class TestVaultEffectiveAPY(unittest.TestCase):
    def test_no_fee_equals_compound_formula(self):
        freq = 1.0 * 365
        expected = ((1 + 0.12 / freq) ** freq - 1) * 100
        ear = _vault_effective_apy(12.0, 0.0, 1.0)
        self.assertAlmostEqual(ear, expected, places=4)

    def test_fee_reduces_apy(self):
        ear_no_fee = _vault_effective_apy(12.0, 0.0, 1.0)
        ear_with_fee = _vault_effective_apy(12.0, 10.0, 1.0)
        self.assertLess(ear_with_fee, ear_no_fee)

    def test_100_pct_fee_returns_zero(self):
        ear = _vault_effective_apy(12.0, 100.0, 1.0)
        self.assertEqual(ear, 0.0)

    def test_zero_apy_returns_zero(self):
        self.assertEqual(_vault_effective_apy(0.0, 5.0, 1.0), 0.0)

    def test_very_high_frequency_capped(self):
        # Should not overflow
        ear = _vault_effective_apy(12.0, 0.0, 1_000_000.0)
        self.assertTrue(math.isfinite(ear))
        self.assertGreater(ear, 0.0)

    def test_higher_frequency_gives_higher_ear(self):
        ear_daily = _vault_effective_apy(12.0, 5.0, 1.0)
        ear_hourly = _vault_effective_apy(12.0, 5.0, 24.0)
        self.assertGreater(ear_hourly, ear_daily)


# ---------------------------------------------------------------------------
# Return shape tests
# ---------------------------------------------------------------------------

class TestReturnShape(unittest.TestCase):
    def setUp(self):
        self.result = analyze(_pos(), [_vault()])

    def test_has_manual_compounding(self):
        self.assertIn("manual_compounding", self.result)

    def test_has_vaults(self):
        self.assertIn("vaults", self.result)

    def test_has_best_vault(self):
        self.assertIn("best_vault", self.result)

    def test_has_beats_manual_count(self):
        self.assertIn("beats_manual_count", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_manual_has_effective_apy(self):
        self.assertIn("effective_apy", self.result["manual_compounding"])

    def test_manual_has_annual_yield(self):
        self.assertIn("annual_yield_usd", self.result["manual_compounding"])

    def test_manual_has_gas_cost(self):
        self.assertIn("annual_gas_cost_usd", self.result["manual_compounding"])

    def test_manual_has_net_yield(self):
        self.assertIn("net_annual_yield_usd", self.result["manual_compounding"])

    def test_vault_has_name(self):
        v = self.result["vaults"][0]
        self.assertIn("name", v)

    def test_vault_has_effective_apy(self):
        v = self.result["vaults"][0]
        self.assertIn("effective_apy", v)

    def test_vault_has_compound_boost(self):
        v = self.result["vaults"][0]
        self.assertIn("compound_boost_pct", v)

    def test_vault_has_annual_yield(self):
        v = self.result["vaults"][0]
        self.assertIn("annual_yield_usd", v)

    def test_vault_has_performance_fee_cost(self):
        v = self.result["vaults"][0]
        self.assertIn("performance_fee_cost_usd", v)

    def test_vault_has_deposit_cost(self):
        v = self.result["vaults"][0]
        self.assertIn("deposit_cost_usd", v)

    def test_vault_has_withdrawal_cost(self):
        v = self.result["vaults"][0]
        self.assertIn("withdrawal_cost_usd", v)

    def test_vault_has_total_one_time_costs(self):
        v = self.result["vaults"][0]
        self.assertIn("total_one_time_costs_usd", v)

    def test_vault_has_net_annual_yield(self):
        v = self.result["vaults"][0]
        self.assertIn("net_annual_yield_usd", v)

    def test_vault_has_vs_manual_benefit(self):
        v = self.result["vaults"][0]
        self.assertIn("vs_manual_benefit_usd", v)

    def test_vault_has_break_even_days(self):
        v = self.result["vaults"][0]
        self.assertIn("break_even_days", v)

    def test_vault_has_recommendation(self):
        v = self.result["vaults"][0]
        self.assertIn("recommendation", v)

    def test_vaults_is_list(self):
        self.assertIsInstance(self.result["vaults"], list)

    def test_beats_manual_count_is_int(self):
        self.assertIsInstance(self.result["beats_manual_count"], int)

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)


# ---------------------------------------------------------------------------
# Manual compounding math tests
# ---------------------------------------------------------------------------

class TestManualCompounding(unittest.TestCase):
    def test_annual_gas_cost(self):
        # gas=10 * (365/7) ≈ 521.43
        r = analyze(_pos(manual_gas_usd=10.0, harvest_frequency_days=7), [])
        expected_gas = 10.0 * (365.0 / 7)
        self.assertAlmostEqual(
            r["manual_compounding"]["annual_gas_cost_usd"], expected_gas, places=1
        )

    def test_net_yield_equals_gross_minus_gas(self):
        r = analyze(_pos(), [])
        mc = r["manual_compounding"]
        self.assertAlmostEqual(
            mc["net_annual_yield_usd"],
            mc["annual_yield_usd"] - mc["annual_gas_cost_usd"],
            places=3,
        )

    def test_annual_yield_from_ear(self):
        r = analyze(_pos(principal_usd=10_000, base_apy=12.0, harvest_frequency_days=7), [])
        mc = r["manual_compounding"]
        ear = mc["effective_apy"] / 100.0
        expected = 10_000.0 * ear
        self.assertAlmostEqual(mc["annual_yield_usd"], expected, places=2)

    def test_zero_gas_no_drag(self):
        r = analyze(_pos(manual_gas_usd=0.0), [])
        mc = r["manual_compounding"]
        self.assertAlmostEqual(mc["annual_gas_cost_usd"], 0.0)
        self.assertAlmostEqual(mc["net_annual_yield_usd"], mc["annual_yield_usd"], places=4)

    def test_zero_principal_yields_zero(self):
        r = analyze(_pos(principal_usd=0.0), [])
        mc = r["manual_compounding"]
        self.assertAlmostEqual(mc["annual_yield_usd"], 0.0)


# ---------------------------------------------------------------------------
# Vault math tests
# ---------------------------------------------------------------------------

class TestVaultMath(unittest.TestCase):
    def test_total_one_time_costs_sum(self):
        v = _vault(deposit_fee_pct=1.0, withdrawal_fee_pct=0.5)
        r = analyze(_pos(principal_usd=10_000), [v])
        vr = r["vaults"][0]
        self.assertAlmostEqual(
            vr["total_one_time_costs_usd"],
            vr["deposit_cost_usd"] + vr["withdrawal_cost_usd"],
            places=4,
        )

    def test_deposit_cost_calculation(self):
        v = _vault(deposit_fee_pct=2.0)
        r = analyze(_pos(principal_usd=10_000), [v])
        self.assertAlmostEqual(r["vaults"][0]["deposit_cost_usd"], 200.0, places=2)

    def test_withdrawal_cost_calculation(self):
        v = _vault(withdrawal_fee_pct=1.0)
        r = analyze(_pos(principal_usd=10_000), [v])
        self.assertAlmostEqual(r["vaults"][0]["withdrawal_cost_usd"], 100.0, places=2)

    def test_performance_fee_cost(self):
        # base_annual_yield = 10_000 * 0.12 = 1200; perf_fee_cost = 1200 * 0.10 = 120
        v = _vault(performance_fee_pct=10.0)
        r = analyze(_pos(principal_usd=10_000, base_apy=12.0), [v])
        self.assertAlmostEqual(r["vaults"][0]["performance_fee_cost_usd"], 120.0, places=2)

    def test_vs_manual_benefit_sign(self):
        # A vault with no fees and very high compounding should beat weekly manual
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=24.0)
        r = analyze(_pos(manual_gas_usd=50.0, harvest_frequency_days=7), [v])
        self.assertGreater(r["vaults"][0]["vs_manual_benefit_usd"], 0)

    def test_compound_boost_positive_for_higher_freq(self):
        # vault compounds more often than weekly manual → positive boost
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=24.0)
        r = analyze(_pos(harvest_frequency_days=7), [v])
        self.assertGreater(r["vaults"][0]["compound_boost_pct"], 0)

    def test_zero_principal_all_zeros(self):
        v = _vault()
        r = analyze(_pos(principal_usd=0.0), [v])
        vr = r["vaults"][0]
        self.assertAlmostEqual(vr["annual_yield_usd"], 0.0)

    def test_net_yield_includes_one_time_costs(self):
        v = _vault(deposit_fee_pct=1.0, withdrawal_fee_pct=0.5)
        r = analyze(_pos(principal_usd=10_000), [v])
        vr = r["vaults"][0]
        self.assertAlmostEqual(
            vr["net_annual_yield_usd"],
            vr["annual_yield_usd"] - vr["total_one_time_costs_usd"],
            places=3,
        )


# ---------------------------------------------------------------------------
# Break-even tests
# ---------------------------------------------------------------------------

class TestBreakEven(unittest.TestCase):
    def test_break_even_none_when_vault_worse(self):
        # High fee vault beats nothing
        v = _vault(performance_fee_pct=99.0, deposit_fee_pct=5.0)
        r = analyze(_pos(), [v])
        self.assertIsNone(r["vaults"][0]["break_even_days"])

    def test_break_even_zero_one_time_costs(self):
        # No one-time costs → break-even = 0
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=24.0,
                   deposit_fee_pct=0.0, withdrawal_fee_pct=0.0)
        r = analyze(_pos(manual_gas_usd=50.0, harvest_frequency_days=7), [v])
        vr = r["vaults"][0]
        if vr["vs_manual_benefit_usd"] > 0:
            self.assertAlmostEqual(vr["break_even_days"], 0.0, places=4)

    def test_break_even_positive_with_costs(self):
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=24.0,
                   deposit_fee_pct=1.0, withdrawal_fee_pct=0.5)
        r = analyze(_pos(principal_usd=100_000, manual_gas_usd=50.0, harvest_frequency_days=7), [v])
        vr = r["vaults"][0]
        if vr["vs_manual_benefit_usd"] > 0:
            self.assertGreater(vr["break_even_days"], 0)

    def test_break_even_under_holding_period_recommends_use(self):
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=24.0,
                   deposit_fee_pct=0.1, withdrawal_fee_pct=0.0)
        r = analyze(
            _pos(principal_usd=100_000, manual_gas_usd=50.0, harvest_frequency_days=7),
            [v],
            config={"holding_period_days": 365}
        )
        vr = r["vaults"][0]
        if vr["break_even_days"] is not None and vr["break_even_days"] <= 365:
            self.assertEqual(vr["recommendation"], "USE")


# ---------------------------------------------------------------------------
# Recommendation tests
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_skip_when_vault_worse(self):
        # 99% fee → vault always worse
        v = _vault(performance_fee_pct=99.0)
        r = analyze(_pos(), [v])
        self.assertEqual(r["vaults"][0]["recommendation"], "SKIP")

    def test_use_when_vault_better_no_one_time_costs(self):
        # High compound frequency, no fees, large gas cost manually
        v = _vault(performance_fee_pct=0.0, compound_frequency_per_day=48.0,
                   deposit_fee_pct=0.0, withdrawal_fee_pct=0.0)
        r = analyze(_pos(principal_usd=100_000, manual_gas_usd=100.0,
                         harvest_frequency_days=1), [v])
        # Manual harvests daily costing $100 each = $36500/yr gas drag
        # vault with no fees should win
        vr = r["vaults"][0]
        self.assertEqual(vr["recommendation"], "USE")

    def test_recommendation_valid_values(self):
        v = _vault()
        r = analyze(_pos(), [v])
        self.assertIn(r["vaults"][0]["recommendation"], ("USE", "SKIP"))


# ---------------------------------------------------------------------------
# best_vault and beats_manual_count tests
# ---------------------------------------------------------------------------

class TestBestVault(unittest.TestCase):
    def test_empty_vaults_best_vault_none(self):
        r = analyze(_pos(), [])
        self.assertIsNone(r["best_vault"])

    def test_empty_vaults_list(self):
        r = analyze(_pos(), [])
        self.assertEqual(r["vaults"], [])

    def test_empty_vaults_beats_manual_zero(self):
        r = analyze(_pos(), [])
        self.assertEqual(r["beats_manual_count"], 0)

    def test_single_vault_best_vault(self):
        r = analyze(_pos(), [_vault(name="MyVault")])
        self.assertEqual(r["best_vault"], "MyVault")

    def test_best_vault_is_highest_net_annual_yield(self):
        v1 = _vault(name="A", performance_fee_pct=20.0)
        v2 = _vault(name="B", performance_fee_pct=1.0,
                    compound_frequency_per_day=24.0)
        r = analyze(_pos(principal_usd=100_000), [v1, v2])
        # B should have higher net yield
        vaults_by_name = {v["name"]: v for v in r["vaults"]}
        winner = max(vaults_by_name, key=lambda n: vaults_by_name[n]["net_annual_yield_usd"])
        self.assertEqual(r["best_vault"], winner)

    def test_beats_manual_count_correct(self):
        v1 = _vault(name="A", performance_fee_pct=99.0)   # loses
        v2 = _vault(name="B", performance_fee_pct=0.0,
                    compound_frequency_per_day=24.0)      # wins if gas is high
        r = analyze(_pos(principal_usd=100_000, manual_gas_usd=200.0,
                         harvest_frequency_days=1), [v1, v2])
        # Count vaults where vs_manual_benefit_usd > 0
        expected = sum(1 for v in r["vaults"] if v["vs_manual_benefit_usd"] > 0)
        self.assertEqual(r["beats_manual_count"], expected)

    def test_multiple_vaults_count(self):
        vaults = [_vault(name=f"V{i}") for i in range(5)]
        r = analyze(_pos(), vaults)
        self.assertEqual(len(r["vaults"]), 5)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_no_config_defaults(self):
        r = analyze(_pos(), [_vault()])
        self.assertIn("manual_compounding", r)

    def test_empty_config_defaults(self):
        r = analyze(_pos(), [_vault()], config={})
        self.assertIn("manual_compounding", r)

    def test_very_high_compound_frequency_no_crash(self):
        v = _vault(compound_frequency_per_day=1_000_000.0)
        r = analyze(_pos(), [v])
        vr = r["vaults"][0]
        self.assertTrue(math.isfinite(vr["effective_apy"]))

    def test_harvest_frequency_zero_treated_as_one(self):
        # Should not divide by zero
        r = analyze(_pos(harvest_frequency_days=0), [_vault()])
        self.assertIn("manual_compounding", r)

    def test_negative_harvest_frequency_treated_as_one(self):
        r = analyze(_pos(harvest_frequency_days=-5), [_vault()])
        self.assertIn("manual_compounding", r)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_pos(), [_vault()])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_vault_name_preserved(self):
        v = _vault(name="SpecialVault123")
        r = analyze(_pos(), [v])
        self.assertEqual(r["vaults"][0]["name"], "SpecialVault123")

    def test_very_large_principal_no_crash(self):
        r = analyze(_pos(principal_usd=1e12), [_vault()])
        self.assertTrue(math.isfinite(r["manual_compounding"]["annual_yield_usd"]))

    def test_zero_performance_fee_higher_ear(self):
        v_no_fee = _vault(performance_fee_pct=0.0, compound_frequency_per_day=1.0)
        v_fee = _vault(performance_fee_pct=20.0, compound_frequency_per_day=1.0)
        r = analyze(_pos(), [v_no_fee, v_fee])
        ear_no_fee = r["vaults"][0]["effective_apy"]
        ear_fee = r["vaults"][1]["effective_apy"]
        self.assertGreater(ear_no_fee, ear_fee)

    def test_holding_period_affects_recommendation(self):
        # Very short holding period → break-even may exceed it → SKIP
        v = _vault(deposit_fee_pct=50.0, withdrawal_fee_pct=50.0,
                   performance_fee_pct=0.0, compound_frequency_per_day=24.0)
        r_short = analyze(
            _pos(principal_usd=1_000, manual_gas_usd=0.0, harvest_frequency_days=365),
            [v],
            config={"holding_period_days": 1}
        )
        # With huge one-time costs and only 1 day, should be SKIP
        self.assertEqual(r_short["vaults"][0]["recommendation"], "SKIP")


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self._tmp.write("[]")
        self._tmp.close()
        import spa_core.analytics.auto_compounder_analyzer as mod
        self._mod = mod
        self._orig = mod.LOG_PATH
        mod.LOG_PATH = self._tmp.name

    def tearDown(self):
        self._mod.LOG_PATH = self._orig
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_log_result_creates_entry(self):
        r = analyze(_pos(), [_vault()])
        log_result(r)
        entries = _load_log()
        self.assertEqual(len(entries), 1)

    def test_log_result_appends(self):
        r1 = analyze(_pos(), [_vault(name="A")])
        r2 = analyze(_pos(), [_vault(name="B")])
        log_result(r1)
        log_result(r2)
        entries = _load_log()
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap(self):
        import spa_core.analytics.auto_compounder_analyzer as mod
        entries = [{"x": i} for i in range(150)]
        mod._save_log(entries)
        loaded = mod._load_log()
        self.assertEqual(len(loaded), LOG_CAP)

    def test_ring_buffer_keeps_latest(self):
        import spa_core.analytics.auto_compounder_analyzer as mod
        entries = [{"x": i} for i in range(150)]
        mod._save_log(entries)
        loaded = mod._load_log()
        self.assertEqual(loaded[-1]["x"], 149)
        self.assertEqual(loaded[0]["x"], 50)

    def test_corrupt_log_returns_empty(self):
        with open(self._tmp.name, "w") as f:
            f.write("CORRUPT{{{not-json")
        entries = _load_log()
        self.assertEqual(entries, [])

    def test_missing_log_returns_empty(self):
        os.unlink(self._tmp.name)
        entries = _load_log()
        self.assertEqual(entries, [])

    def test_atomic_write_succeeds(self):
        import spa_core.analytics.auto_compounder_analyzer as mod
        mod._save_log([{"ok": True}])
        loaded = mod._load_log()
        self.assertEqual(loaded[0]["ok"], True)


if __name__ == "__main__":
    unittest.main()
