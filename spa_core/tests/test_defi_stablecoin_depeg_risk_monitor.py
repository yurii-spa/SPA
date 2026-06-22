"""
Tests for MP-905: DeFiStablecoinDepegRiskMonitor
Run: python3 -m unittest spa_core.tests.test_defi_stablecoin_depeg_risk_monitor -v
"""

import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.defi_stablecoin_depeg_risk_monitor import (
    DeFiStablecoinDepegRiskMonitor,
    _compute_depeg_probability,
    _compute_resilience_score,
    _compute_collateral_quality,
    _risk_label,
    _compute_flags,
    _append_log,
    MAX_ENTRIES,
    PEG_TYPE_BASE_RISK,
    PEG_TYPE_RESILIENCE_BASE,
    PEG_TYPE_COLLATERAL_BASE,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _fiat_coin(**kw):
    base = {
        "name": "USDC",
        "peg_type": "fiat_backed",
        "current_price": 1.0,
        "collateral_ratio": 1.0,
        "mint_burn_24h_usd": 0.0,
        "tvl_usd": 5_000_000_000,
        "historical_max_depeg_pct": 0.1,
        "chain": "ethereum",
        "audit_count": 3,
        "mint_mechanism": "fiat_reserve",
    }
    base.update(kw)
    return base


def _algo_coin(**kw):
    base = {
        "name": "USDD",
        "peg_type": "algo",
        "current_price": 0.99,
        "collateral_ratio": 0.8,
        "mint_burn_24h_usd": 10_000_000,
        "tvl_usd": 200_000_000,
        "historical_max_depeg_pct": 3.5,
        "chain": "tron",
        "audit_count": 1,
        "mint_mechanism": "algorithmic",
    }
    base.update(kw)
    return base


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_depeg_probability
# ─────────────────────────────────────────────────────────────────

class TestComputeDepegProbability(unittest.TestCase):

    def test_fiat_backed_stable_low_prob(self):
        p = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertLess(p, 0.08)  # fiat_backed + 1.0 ratio is standard; base only

    def test_algo_high_base_risk(self):
        p = _compute_depeg_probability("algo", 1.0, 1.2, 0.0, 0.0, 1e8)
        self.assertGreater(p, 0.30)

    def test_large_price_deviation_raises_prob(self):
        p_dev = _compute_depeg_probability("fiat_backed", 0.95, 1.0, 0.0, 0.0, 1e9)
        p_ok = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertGreater(p_dev, p_ok)

    def test_historical_depeg_over_10_adds_018(self):
        p1 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 15.0, 0.0, 1e9)
        p0 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertAlmostEqual(p1 - p0, 0.18, places=5)

    def test_historical_depeg_over_5_adds_010(self):
        p1 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 7.0, 0.0, 1e9)
        p0 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertAlmostEqual(p1 - p0, 0.10, places=5)

    def test_historical_depeg_over_2_adds_005(self):
        p1 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 3.0, 0.0, 1e9)
        p0 = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertAlmostEqual(p1 - p0, 0.05, places=5)

    def test_undercollateralised_below_100_pct(self):
        p = _compute_depeg_probability("collateralized", 1.0, 0.9, 0.0, 0.0, 1e8)
        self.assertGreater(p, 0.25)

    def test_undercollateralised_below_110_pct(self):
        p_low = _compute_depeg_probability("collateralized", 1.0, 1.05, 0.0, 0.0, 1e8)
        p_ok = _compute_depeg_probability("collateralized", 1.0, 1.50, 0.0, 0.0, 1e8)
        self.assertGreater(p_low, p_ok)

    def test_high_collateral_reduces_prob(self):
        p_high = _compute_depeg_probability("crypto_backed", 1.0, 2.5, 0.0, 0.0, 1e8)
        p_low = _compute_depeg_probability("crypto_backed", 1.0, 1.0, 0.0, 0.0, 1e8)
        self.assertLess(p_high, p_low)

    def test_large_mint_burn_raises_prob(self):
        # mint_burn = 20% of tvl_usd
        p_big = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 2e8, 1e9)
        p_ok = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertGreater(p_big, p_ok)

    def test_zero_tvl_no_mint_burn_bonus(self):
        p = _compute_depeg_probability("fiat_backed", 1.0, 1.0, 0.0, 1e8, 0.0)
        # Should not add mint_burn bonus because tvl=0 guard; base only = 0.03
        self.assertLess(p, 0.10)

    def test_clamp_upper_1(self):
        p = _compute_depeg_probability("algo", 0.50, 0.5, 99.0, 1e9, 1e6)
        self.assertLessEqual(p, 1.0)

    def test_clamp_lower_0(self):
        p = _compute_depeg_probability("fiat_backed", 1.0, 3.0, 0.0, 0.0, 1e12)
        self.assertGreaterEqual(p, 0.0)

    def test_crypto_backed_higher_than_fiat(self):
        p_c = _compute_depeg_probability("crypto_backed", 1.0, 1.2, 0.0, 0.0, 1e9)
        p_f = _compute_depeg_probability("fiat_backed", 1.0, 1.2, 0.0, 0.0, 1e9)
        self.assertGreater(p_c, p_f)

    def test_unknown_peg_type_uses_default(self):
        p = _compute_depeg_probability("exotic", 1.0, 1.0, 0.0, 0.0, 1e9)
        self.assertGreater(p, 0.0)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_resilience_score
# ─────────────────────────────────────────────────────────────────

class TestComputeResilienceScore(unittest.TestCase):

    def test_fiat_backed_high_tvl_audits_returns_high(self):
        s = _compute_resilience_score("fiat_backed", 1.5, 0.0, 5e9, 4, 0.0)
        self.assertGreater(s, 80)

    def test_algo_low_tvl_no_audit_returns_low(self):
        s = _compute_resilience_score("algo", 0.9, 5.0, 500_000, 0, 0.0)
        self.assertLess(s, 30)

    def test_score_clamped_0_100(self):
        s_high = _compute_resilience_score("fiat_backed", 3.0, 0.0, 1e12, 10, 0.0)
        s_low = _compute_resilience_score("algo", 0.5, 50.0, 0.0, 0, 1e9)
        self.assertLessEqual(s_high, 100)
        self.assertGreaterEqual(s_low, 0)

    def test_high_collateral_adds_bonus(self):
        s_high = _compute_resilience_score("collateralized", 2.5, 0.0, 1e8, 1, 0.0)
        s_low = _compute_resilience_score("collateralized", 1.0, 0.0, 1e8, 1, 0.0)
        self.assertGreater(s_high, s_low)

    def test_low_collateral_subtracts_20(self):
        s_low = _compute_resilience_score("collateralized", 1.05, 0.0, 1e8, 1, 0.0)
        s_ok = _compute_resilience_score("collateralized", 1.50, 0.0, 1e8, 1, 0.0)
        self.assertLess(s_low, s_ok)

    def test_historical_depeg_over_10_subtracts_25(self):
        # Use tvl=1e8 so base=82+6+8=96 (no clamping); delta = 25
        s1 = _compute_resilience_score("fiat_backed", 1.0, 15.0, 1e8, 2, 0.0)
        s0 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e8, 2, 0.0)
        self.assertEqual(s0 - s1, 25)

    def test_historical_depeg_over_5_subtracts_15(self):
        # Use tvl=1e8 to avoid clamping
        s1 = _compute_resilience_score("fiat_backed", 1.0, 7.0, 1e8, 2, 0.0)
        s0 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e8, 2, 0.0)
        self.assertEqual(s0 - s1, 15)

    def test_historical_depeg_over_2_subtracts_8(self):
        # Use tvl=1e8 to avoid clamping
        s1 = _compute_resilience_score("fiat_backed", 1.0, 3.0, 1e8, 2, 0.0)
        s0 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e8, 2, 0.0)
        self.assertEqual(s0 - s1, 8)

    def test_tvl_over_1b_adds_12(self):
        s1 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 2e9, 0, 0.0)
        s0 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 50e6, 0, 0.0)
        self.assertGreater(s1, s0)

    def test_tvl_under_1m_subtracts_10(self):
        s_low = _compute_resilience_score("fiat_backed", 1.0, 0.0, 500_000, 0, 0.0)
        s_ok = _compute_resilience_score("fiat_backed", 1.0, 0.0, 5e8, 0, 0.0)
        self.assertLess(s_low, s_ok)

    def test_audit_count_caps_at_15(self):
        s5 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e9, 5, 0.0)
        s10 = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e9, 10, 0.0)
        # Both should be capped at +15 audit bonus
        self.assertEqual(s5, s10)

    def test_large_mint_burn_penalty(self):
        # mint_burn = 20% of tvl → exceeds 10% threshold
        s_big = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e9, 2, 2e8)
        s_ok = _compute_resilience_score("fiat_backed", 1.0, 0.0, 1e9, 2, 0.0)
        self.assertLess(s_big, s_ok)

    def test_unknown_peg_type_uses_default(self):
        s = _compute_resilience_score("exotic", 1.0, 0.0, 1e9, 2, 0.0)
        self.assertGreaterEqual(s, 0)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_collateral_quality
# ─────────────────────────────────────────────────────────────────

class TestComputeCollateralQuality(unittest.TestCase):

    def test_fiat_backed_high_quality(self):
        q = _compute_collateral_quality("fiat_backed", 1.0, 3)
        self.assertGreater(q, 90)  # base=90, no penalty for 1:1 fiat, +9 audit = 99

    def test_algo_low_quality(self):
        q = _compute_collateral_quality("algo", 0.8, 0)
        self.assertLess(q, 25)

    def test_high_collateral_ratio_adds_bonus(self):
        q_high = _compute_collateral_quality("crypto_backed", 2.5, 0)
        q_low = _compute_collateral_quality("crypto_backed", 1.0, 0)
        self.assertGreater(q_high, q_low)

    def test_undercollateralised_subtracts(self):
        q_low = _compute_collateral_quality("collateralized", 1.05, 0)
        q_ok = _compute_collateral_quality("collateralized", 1.5, 0)
        self.assertLess(q_low, q_ok)

    def test_audit_count_caps_at_10(self):
        q3 = _compute_collateral_quality("fiat_backed", 1.0, 4)  # 4*3=12 > 10
        q10 = _compute_collateral_quality("fiat_backed", 1.0, 10)  # 10*3=30 > 10
        self.assertEqual(q3, q10)

    def test_clamped_0_100(self):
        q_high = _compute_collateral_quality("fiat_backed", 3.0, 10)
        q_low = _compute_collateral_quality("algo", 0.0, 0)
        self.assertLessEqual(q_high, 100)
        self.assertGreaterEqual(q_low, 0)

    def test_unknown_peg_type_uses_default(self):
        q = _compute_collateral_quality("exotic", 1.0, 0)
        self.assertGreaterEqual(q, 0)


# ─────────────────────────────────────────────────────────────────
# Tests: _risk_label
# ─────────────────────────────────────────────────────────────────

class TestRiskLabel(unittest.TestCase):

    def test_price_below_097_is_depegged(self):
        self.assertEqual(_risk_label(0.96, 0.0, 100), "DEPEGGED")

    def test_price_above_103_is_depegged(self):
        self.assertEqual(_risk_label(1.04, 0.0, 100), "DEPEGGED")

    def test_exactly_097_not_depegged(self):
        label = _risk_label(0.97, 0.05, 80)
        self.assertNotEqual(label, "DEPEGGED")

    def test_exactly_103_not_depegged(self):
        label = _risk_label(1.03, 0.05, 80)
        self.assertNotEqual(label, "DEPEGGED")

    def test_high_prob_gives_danger(self):
        self.assertEqual(_risk_label(1.0, 0.60, 50), "DANGER")

    def test_very_low_resilience_gives_danger(self):
        self.assertEqual(_risk_label(1.0, 0.05, 15), "DANGER")

    def test_medium_prob_gives_warning(self):
        self.assertEqual(_risk_label(1.0, 0.40, 50), "WARNING")

    def test_low_resilience_gives_warning(self):
        self.assertEqual(_risk_label(1.0, 0.05, 35), "WARNING")

    def test_moderate_prob_gives_watch(self):
        self.assertEqual(_risk_label(1.0, 0.20, 60), "WATCH")

    def test_low_resilience_gives_watch(self):
        self.assertEqual(_risk_label(1.0, 0.10, 50), "WATCH")

    def test_low_prob_decent_resilience_gives_stable(self):
        self.assertEqual(_risk_label(1.0, 0.09, 65), "STABLE")

    def test_very_stable(self):
        self.assertEqual(_risk_label(1.0, 0.01, 90), "VERY_STABLE")

    def test_depegged_takes_priority_over_high_resilience(self):
        # Even if resilience is perfect, DEPEGGED should win
        self.assertEqual(_risk_label(0.50, 0.0, 100), "DEPEGGED")


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_for_stable_fiat(self):
        flags = _compute_flags("fiat_backed", 1.5, 0.0, 5e9, 0.5)
        self.assertEqual(flags, [])

    def test_algo_risk_flag(self):
        flags = _compute_flags("algo", 1.5, 0.0, 5e9, 0.5)
        self.assertIn("ALGO_RISK", flags)

    def test_undercollateralised_flag_below_110(self):
        flags = _compute_flags("collateralized", 1.05, 0.0, 5e9, 0.5)
        self.assertIn("UNDERCOLLATERALIZED", flags)

    def test_not_undercollateralised_at_110(self):
        flags = _compute_flags("collateralized", 1.10, 0.0, 5e9, 0.5)
        self.assertNotIn("UNDERCOLLATERALIZED", flags)

    def test_large_mint_burn_flag(self):
        # mint_burn = 15% of tvl
        flags = _compute_flags("fiat_backed", 1.5, 1.5e8, 1e9, 0.5)
        self.assertIn("LARGE_MINT_BURN", flags)

    def test_no_large_mint_burn_below_threshold(self):
        # mint_burn = 5% of tvl
        flags = _compute_flags("fiat_backed", 1.5, 5e7, 1e9, 0.5)
        self.assertNotIn("LARGE_MINT_BURN", flags)

    def test_historical_depeg_flag(self):
        flags = _compute_flags("fiat_backed", 1.5, 0.0, 5e9, 3.0)
        self.assertIn("HISTORICAL_DEPEG", flags)

    def test_no_historical_depeg_at_2pct(self):
        flags = _compute_flags("fiat_backed", 1.5, 0.0, 5e9, 2.0)
        self.assertNotIn("HISTORICAL_DEPEG", flags)

    def test_low_tvl_flag(self):
        flags = _compute_flags("fiat_backed", 1.5, 0.0, 500_000, 0.5)
        self.assertIn("LOW_TVL", flags)

    def test_no_low_tvl_at_1m(self):
        flags = _compute_flags("fiat_backed", 1.5, 0.0, 1_000_000, 0.5)
        self.assertNotIn("LOW_TVL", flags)

    def test_zero_tvl_no_large_mint_burn(self):
        # tvl=0 guard prevents division
        flags = _compute_flags("algo", 1.0, 1e9, 0.0, 0.5)
        self.assertNotIn("LARGE_MINT_BURN", flags)

    def test_multiple_flags_combined(self):
        flags = _compute_flags("algo", 1.05, 2e8, 1e9, 5.0)
        self.assertIn("ALGO_RISK", flags)
        self.assertIn("UNDERCOLLATERALIZED", flags)
        self.assertIn("LARGE_MINT_BURN", flags)
        self.assertIn("HISTORICAL_DEPEG", flags)


# ─────────────────────────────────────────────────────────────────
# Tests: DeFiStablecoinDepegRiskMonitor.monitor()
# ─────────────────────────────────────────────────────────────────

class TestMonitorBasic(unittest.TestCase):

    def setUp(self):
        self.monitor = DeFiStablecoinDepegRiskMonitor()
        self._td = tempfile.TemporaryDirectory()
        self._orig_data_file = None
        # Patch DATA_FILE to a temp path
        import spa_core.analytics.defi_stablecoin_depeg_risk_monitor as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "stablecoin_depeg_log.json"

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def _run(self, coins=None, config=None):
        if coins is None:
            coins = [_fiat_coin()]
        return self.monitor.monitor(coins, config or {})

    def test_returns_dict_with_required_keys(self):
        result = self._run()
        for k in ("stablecoins", "most_stable", "highest_risk",
                   "depegged_count", "danger_count",
                   "average_resilience", "timestamp"):
            self.assertIn(k, result)

    def test_empty_input_returns_none_aggregates(self):
        result = self._run(coins=[])
        self.assertIsNone(result["most_stable"])
        self.assertIsNone(result["highest_risk"])
        self.assertEqual(result["depegged_count"], 0)
        self.assertEqual(result["danger_count"], 0)
        self.assertEqual(result["average_resilience"], 0.0)

    def test_single_coin_result_list_length(self):
        result = self._run([_fiat_coin()])
        self.assertEqual(len(result["stablecoins"]), 1)

    def test_per_coin_keys(self):
        result = self._run([_fiat_coin()])
        coin = result["stablecoins"][0]
        for k in ("name", "peg_type", "current_price", "collateral_ratio",
                   "tvl_usd", "chain", "mint_mechanism",
                   "depeg_probability", "resilience_score", "collateral_quality",
                   "risk_label", "flags"):
            self.assertIn(k, coin)

    def test_depeg_probability_range(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        for c in result["stablecoins"]:
            self.assertGreaterEqual(c["depeg_probability"], 0.0)
            self.assertLessEqual(c["depeg_probability"], 1.0)

    def test_resilience_score_range(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        for c in result["stablecoins"]:
            self.assertGreaterEqual(c["resilience_score"], 0)
            self.assertLessEqual(c["resilience_score"], 100)

    def test_collateral_quality_range(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        for c in result["stablecoins"]:
            self.assertGreaterEqual(c["collateral_quality"], 0)
            self.assertLessEqual(c["collateral_quality"], 100)

    def test_risk_label_is_valid(self):
        coins = [
            _fiat_coin(),
            _algo_coin(),
            _fiat_coin(name="X", current_price=0.95),
        ]
        result = self._run(coins)
        valid = {"VERY_STABLE", "STABLE", "WATCH", "WARNING", "DANGER", "DEPEGGED"}
        for c in result["stablecoins"]:
            self.assertIn(c["risk_label"], valid)

    def test_flags_is_list(self):
        result = self._run([_algo_coin()])
        self.assertIsInstance(result["stablecoins"][0]["flags"], list)

    def test_fiat_coin_no_flags(self):
        result = self._run([_fiat_coin(
            collateral_ratio=1.5,
            tvl_usd=5e9,
            mint_burn_24h_usd=1e6,
            historical_max_depeg_pct=0.1,
        )])
        self.assertEqual(result["stablecoins"][0]["flags"], [])

    def test_algo_coin_has_algo_risk_flag(self):
        result = self._run([_algo_coin(collateral_ratio=1.5)])
        self.assertIn("ALGO_RISK", result["stablecoins"][0]["flags"])

    def test_depegged_coin_below_097(self):
        result = self._run([_fiat_coin(name="BAD", current_price=0.95)])
        self.assertEqual(result["stablecoins"][0]["risk_label"], "DEPEGGED")
        self.assertEqual(result["depegged_count"], 1)

    def test_depegged_coin_above_103(self):
        result = self._run([_fiat_coin(name="HIGH", current_price=1.04)])
        self.assertEqual(result["stablecoins"][0]["risk_label"], "DEPEGGED")

    def test_depegged_count_multiple(self):
        coins = [
            _fiat_coin(name="A", current_price=0.94),
            _fiat_coin(name="B", current_price=1.05),
            _fiat_coin(name="C"),
        ]
        result = self._run(coins)
        self.assertEqual(result["depegged_count"], 2)

    def test_danger_count_includes_depegged(self):
        coins = [
            _fiat_coin(name="D", current_price=0.94),  # DEPEGGED → counts
            _algo_coin(name="E", collateral_ratio=0.5, historical_max_depeg_pct=20.0),
        ]
        result = self._run(coins)
        self.assertGreaterEqual(result["danger_count"], 1)

    def test_most_stable_is_string_or_none(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        self.assertIsNotNone(result["most_stable"])

    def test_highest_risk_is_string_or_none(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        self.assertIsNotNone(result["highest_risk"])

    def test_average_resilience_computed(self):
        result = self._run([_fiat_coin(), _algo_coin()])
        self.assertGreater(result["average_resilience"], 0.0)

    def test_timestamp_present_and_recent(self):
        import time
        result = self._run()
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5)

    def test_most_stable_differs_from_highest_risk(self):
        result = self._run([_fiat_coin(), _algo_coin(name="ALGO2")])
        self.assertNotEqual(result["most_stable"], result["highest_risk"])

    def test_many_coins_all_present(self):
        coins = [_fiat_coin(name=f"USD{i}") for i in range(10)]
        result = self._run(coins)
        self.assertEqual(len(result["stablecoins"]), 10)

    def test_config_none_accepted(self):
        result = self.monitor.monitor([_fiat_coin()], None)
        self.assertIn("stablecoins", result)

    def test_default_missing_fields_handled(self):
        result = self.monitor.monitor([{"name": "BARE"}])
        self.assertEqual(len(result["stablecoins"]), 1)

    def test_undercollateralised_flag_present(self):
        result = self._run([_fiat_coin(collateral_ratio=1.05)])
        self.assertIn("UNDERCOLLATERALIZED", result["stablecoins"][0]["flags"])

    def test_low_tvl_flag(self):
        result = self._run([_fiat_coin(tvl_usd=500_000)])
        self.assertIn("LOW_TVL", result["stablecoins"][0]["flags"])

    def test_large_mint_burn_flag(self):
        # 20% of TVL
        result = self._run([_fiat_coin(mint_burn_24h_usd=2e8, tvl_usd=1e9)])
        self.assertIn("LARGE_MINT_BURN", result["stablecoins"][0]["flags"])

    def test_historical_depeg_flag(self):
        result = self._run([_fiat_coin(historical_max_depeg_pct=5.0)])
        self.assertIn("HISTORICAL_DEPEG", result["stablecoins"][0]["flags"])


# ─────────────────────────────────────────────────────────────────
# Tests: ring-buffer log
# ─────────────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        import spa_core.analytics.defi_stablecoin_depeg_risk_monitor as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "stablecoin_depeg_log.json"

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def test_log_file_created_on_first_write(self):
        _append_log({"x": 1})
        self.assertTrue(self._mod.DATA_FILE.exists())

    def test_log_file_is_json_list(self):
        _append_log({"x": 1})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_entry_appended(self):
        _append_log({"x": 1})
        _append_log({"x": 2})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for i in range(MAX_ENTRIES + 5):
            _append_log({"i": i})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        for i in range(MAX_ENTRIES + 5):
            _append_log({"i": i})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        # Last entry should be the most recent one
        self.assertEqual(data[-1]["i"], MAX_ENTRIES + 4)

    def test_atomic_write_tmp_removed(self):
        _append_log({"x": 1})
        tmp = self._mod.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_monitor_writes_to_log(self):
        monitor = DeFiStablecoinDepegRiskMonitor()
        monitor.monitor([_fiat_coin()])
        self.assertTrue(self._mod.DATA_FILE.exists())

    def test_corrupt_log_resets_gracefully(self):
        self._mod.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._mod.DATA_FILE, "w") as f:
            f.write("not valid json")
        _append_log({"x": 1})  # Should not raise
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_log_resets_gracefully(self):
        self._mod.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._mod.DATA_FILE, "w") as f:
            json.dump({"bad": "object"}, f)
        _append_log({"y": 2})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_monitor_multiple_calls_accumulate(self):
        monitor = DeFiStablecoinDepegRiskMonitor()
        for _ in range(5):
            monitor.monitor([_fiat_coin()])
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)


# ─────────────────────────────────────────────────────────────────
# Tests: edge cases & misc
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        import spa_core.analytics.defi_stablecoin_depeg_risk_monitor as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "stablecoin_depeg_log.json"
        self.monitor = DeFiStablecoinDepegRiskMonitor()

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def test_zero_audit_count_handled(self):
        r = self.monitor.monitor([_fiat_coin(audit_count=0)])
        self.assertIsNotNone(r)

    def test_very_high_audit_count_capped(self):
        r = self.monitor.monitor([_fiat_coin(audit_count=100)])
        self.assertLessEqual(r["stablecoins"][0]["resilience_score"], 100)
        self.assertLessEqual(r["stablecoins"][0]["collateral_quality"], 100)

    def test_zero_collateral_ratio_handled(self):
        r = self.monitor.monitor([_algo_coin(collateral_ratio=0.0)])
        self.assertIsNotNone(r)
        flags = r["stablecoins"][0]["flags"]
        self.assertIn("UNDERCOLLATERALIZED", flags)

    def test_extreme_tvl_handled(self):
        r = self.monitor.monitor([_fiat_coin(tvl_usd=1e15)])
        self.assertLessEqual(r["stablecoins"][0]["resilience_score"], 100)

    def test_price_exactly_097_not_depegged(self):
        r = self.monitor.monitor([_fiat_coin(name="EDGE", current_price=0.97)])
        self.assertNotEqual(r["stablecoins"][0]["risk_label"], "DEPEGGED")

    def test_price_exactly_103_not_depegged(self):
        r = self.monitor.monitor([_fiat_coin(name="EDGE", current_price=1.03)])
        self.assertNotEqual(r["stablecoins"][0]["risk_label"], "DEPEGGED")

    def test_collateralized_type_processed(self):
        coin = _fiat_coin(peg_type="collateralized")
        r = self.monitor.monitor([coin])
        self.assertEqual(r["stablecoins"][0]["peg_type"], "collateralized")

    def test_crypto_backed_type_processed(self):
        coin = _fiat_coin(peg_type="crypto_backed")
        r = self.monitor.monitor([coin])
        self.assertEqual(r["stablecoins"][0]["peg_type"], "crypto_backed")

    def test_name_preserved_in_output(self):
        r = self.monitor.monitor([_fiat_coin(name="MYTHING")])
        self.assertEqual(r["stablecoins"][0]["name"], "MYTHING")

    def test_chain_preserved_in_output(self):
        r = self.monitor.monitor([_fiat_coin(chain="optimism")])
        self.assertEqual(r["stablecoins"][0]["chain"], "optimism")

    def test_mint_mechanism_preserved_in_output(self):
        r = self.monitor.monitor([_fiat_coin(mint_mechanism="vault")])
        self.assertEqual(r["stablecoins"][0]["mint_mechanism"], "vault")

    def test_depeg_probability_is_float(self):
        r = self.monitor.monitor([_fiat_coin()])
        self.assertIsInstance(r["stablecoins"][0]["depeg_probability"], float)

    def test_two_stable_coins_aggregates(self):
        coins = [
            _fiat_coin(name="A"),
            _fiat_coin(name="B"),
        ]
        r = self.monitor.monitor(coins)
        self.assertIn(r["most_stable"], ("A", "B"))
        self.assertIn(r["highest_risk"], ("A", "B"))

    def test_single_coin_most_stable_equals_highest_risk(self):
        r = self.monitor.monitor([_fiat_coin(name="SOLO")])
        self.assertEqual(r["most_stable"], "SOLO")
        self.assertEqual(r["highest_risk"], "SOLO")

    def test_average_resilience_is_float(self):
        r = self.monitor.monitor([_fiat_coin()])
        self.assertIsInstance(r["average_resilience"], float)

    def test_algo_upper_case_normalized(self):
        coin = _fiat_coin(peg_type="ALGO")
        r = self.monitor.monitor([coin])
        self.assertIn("ALGO_RISK", r["stablecoins"][0]["flags"])

    def test_peg_type_stored_lowercase(self):
        coin = _fiat_coin(peg_type="FIAT_BACKED")
        r = self.monitor.monitor([coin])
        self.assertEqual(r["stablecoins"][0]["peg_type"], "fiat_backed")


# ─────────────────────────────────────────────────────────────────
# Tests: constants integrity
# ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_max_entries_positive(self):
        self.assertGreater(MAX_ENTRIES, 0)

    def test_all_peg_types_in_base_risk(self):
        for pt in ("algo", "fiat_backed", "collateralized", "crypto_backed"):
            self.assertIn(pt, PEG_TYPE_BASE_RISK)

    def test_all_peg_types_in_resilience_base(self):
        for pt in ("algo", "fiat_backed", "collateralized", "crypto_backed"):
            self.assertIn(pt, PEG_TYPE_RESILIENCE_BASE)

    def test_all_peg_types_in_collateral_base(self):
        for pt in ("algo", "fiat_backed", "collateralized", "crypto_backed"):
            self.assertIn(pt, PEG_TYPE_COLLATERAL_BASE)

    def test_algo_highest_base_risk(self):
        self.assertEqual(
            max(PEG_TYPE_BASE_RISK.values()),
            PEG_TYPE_BASE_RISK["algo"],
        )

    def test_fiat_lowest_base_risk(self):
        self.assertEqual(
            min(PEG_TYPE_BASE_RISK.values()),
            PEG_TYPE_BASE_RISK["fiat_backed"],
        )

    def test_fiat_highest_resilience(self):
        self.assertEqual(
            max(PEG_TYPE_RESILIENCE_BASE.values()),
            PEG_TYPE_RESILIENCE_BASE["fiat_backed"],
        )

    def test_algo_lowest_resilience(self):
        self.assertEqual(
            min(PEG_TYPE_RESILIENCE_BASE.values()),
            PEG_TYPE_RESILIENCE_BASE["algo"],
        )

    def test_fiat_highest_collateral_base(self):
        self.assertEqual(
            max(PEG_TYPE_COLLATERAL_BASE.values()),
            PEG_TYPE_COLLATERAL_BASE["fiat_backed"],
        )

    def test_algo_lowest_collateral_base(self):
        self.assertEqual(
            min(PEG_TYPE_COLLATERAL_BASE.values()),
            PEG_TYPE_COLLATERAL_BASE["algo"],
        )


if __name__ == "__main__":
    unittest.main()
