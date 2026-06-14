"""
Tests for MP-1068: DeFiProtocolTokenUnlockPriceImpactEstimator
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_token_unlock_price_impact_estimator
"""
import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.defi_protocol_token_unlock_price_impact_estimator import (
    DeFiProtocolTokenUnlockPriceImpactEstimator,
    VALID_LABELS,
    SELL_PRESSURE_BY_RECIPIENT,
    _clamp,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_payload(**kwargs):
    defaults = {
        "token_name": "TestToken",
        "current_price_usd": 2.00,
        "current_market_cap_usd": 50_000_000,
        "unlock_amount_tokens": 1_000_000,
        "unlock_date_days_from_now": 30,
        "avg_daily_volume_usd": 2_000_000,
        "recipient_type": "community",
        "vesting_cliff_months": 0,
        "protocol_revenue_usd_per_month": 0,
        "staking_locked_pct": 0.0,
    }
    defaults.update(kwargs)
    return defaults


def _make_estimator(tmp_dir):
    log_path = os.path.join(tmp_dir, "token_unlock_price_impact_log.json")
    return DeFiProtocolTokenUnlockPriceImpactEstimator(log_path=log_path)


# ===========================================================================
# 1. Return structure
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_estimate_returns_dict(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r, dict)

    def test_result_has_token_name(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("token_name", r)

    def test_result_has_unlock_value_usd(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("unlock_value_usd", r)

    def test_result_has_volume_ratio(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("volume_ratio", r)

    def test_result_has_estimated_sell_pressure_pct(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("estimated_sell_pressure_pct", r)

    def test_result_has_price_impact_pct(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("price_impact_pct", r)

    def test_result_has_unlock_risk_label(self):
        r = self.est.estimate(_make_payload())
        self.assertIn("unlock_risk_label", r)

    def test_token_name_propagated(self):
        r = self.est.estimate(_make_payload(token_name="MYTOKEN"))
        self.assertEqual(r["token_name"], "MYTOKEN")

    def test_result_has_exactly_six_keys(self):
        r = self.est.estimate(_make_payload())
        self.assertEqual(len(r), 6)


# ===========================================================================
# 2. unlock_value_usd computation
# ===========================================================================

class TestUnlockValueUsd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_basic_unlock_value(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=1.0, unlock_amount_tokens=500_000
        ))
        self.assertAlmostEqual(r["unlock_value_usd"], 500_000.0, places=2)

    def test_zero_price_gives_zero_value(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=0.0, unlock_amount_tokens=1_000_000
        ))
        self.assertEqual(r["unlock_value_usd"], 0.0)

    def test_zero_tokens_gives_zero_value(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=5.0, unlock_amount_tokens=0
        ))
        self.assertEqual(r["unlock_value_usd"], 0.0)

    def test_large_unlock_value(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=100.0, unlock_amount_tokens=10_000_000
        ))
        self.assertAlmostEqual(r["unlock_value_usd"], 1_000_000_000.0, places=0)

    def test_fractional_tokens(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=2.0, unlock_amount_tokens=0.5
        ))
        self.assertAlmostEqual(r["unlock_value_usd"], 1.0, places=4)

    def test_unlock_value_is_float(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r["unlock_value_usd"], float)


# ===========================================================================
# 3. volume_ratio computation
# ===========================================================================

class TestVolumeRatio(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_volume_ratio_is_positive(self):
        r = self.est.estimate(_make_payload())
        self.assertGreaterEqual(r["volume_ratio"], 0.0)

    def test_volume_ratio_zero_when_no_unlock(self):
        r = self.est.estimate(_make_payload(
            current_price_usd=1.0, unlock_amount_tokens=0
        ))
        self.assertEqual(r["volume_ratio"], 0.0)

    def test_volume_ratio_proportional_to_unlock_value(self):
        r1 = self.est.estimate(_make_payload(
            current_price_usd=1.0, unlock_amount_tokens=1_000_000,
            avg_daily_volume_usd=1_000_000
        ))
        r2 = self.est.estimate(_make_payload(
            current_price_usd=1.0, unlock_amount_tokens=2_000_000,
            avg_daily_volume_usd=1_000_000
        ))
        self.assertGreater(r2["volume_ratio"], r1["volume_ratio"])

    def test_volume_ratio_decreases_with_higher_volume(self):
        r1 = self.est.estimate(_make_payload(avg_daily_volume_usd=500_000))
        r2 = self.est.estimate(_make_payload(avg_daily_volume_usd=5_000_000))
        self.assertGreater(r1["volume_ratio"], r2["volume_ratio"])

    def test_volume_ratio_zero_volume_returns_zero(self):
        r = self.est.estimate(_make_payload(avg_daily_volume_usd=0))
        self.assertEqual(r["volume_ratio"], 0.0)

    def test_volume_ratio_is_float(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r["volume_ratio"], float)


# ===========================================================================
# 4. estimated_sell_pressure_pct
# ===========================================================================

class TestSellPressure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_sell_pressure_in_range_zero_to_one(self):
        for rt in ["team", "investor", "community", "ecosystem"]:
            with self.subTest(rt=rt):
                r = self.est.estimate(_make_payload(recipient_type=rt))
                self.assertGreaterEqual(r["estimated_sell_pressure_pct"], 0.0)
                self.assertLessEqual(r["estimated_sell_pressure_pct"], 1.0)

    def test_team_higher_sell_than_community(self):
        r_team = self.est.estimate(_make_payload(recipient_type="team", staking_locked_pct=0))
        r_comm = self.est.estimate(_make_payload(recipient_type="community", staking_locked_pct=0))
        self.assertGreater(
            r_team["estimated_sell_pressure_pct"],
            r_comm["estimated_sell_pressure_pct"]
        )

    def test_investor_higher_sell_than_ecosystem(self):
        r_inv = self.est.estimate(_make_payload(recipient_type="investor", staking_locked_pct=0))
        r_eco = self.est.estimate(_make_payload(recipient_type="ecosystem", staking_locked_pct=0))
        self.assertGreater(
            r_inv["estimated_sell_pressure_pct"],
            r_eco["estimated_sell_pressure_pct"]
        )

    def test_cliff_reduces_sell_pressure(self):
        r0 = self.est.estimate(_make_payload(vesting_cliff_months=0))
        r12 = self.est.estimate(_make_payload(vesting_cliff_months=24))
        self.assertGreaterEqual(r0["estimated_sell_pressure_pct"], r12["estimated_sell_pressure_pct"])

    def test_staking_reduces_sell_pressure(self):
        r0 = self.est.estimate(_make_payload(staking_locked_pct=0))
        r80 = self.est.estimate(_make_payload(staking_locked_pct=80))
        self.assertGreater(r0["estimated_sell_pressure_pct"], r80["estimated_sell_pressure_pct"])

    def test_unknown_recipient_uses_default(self):
        r = self.est.estimate(_make_payload(recipient_type="unknown_xyz"))
        self.assertGreater(r["estimated_sell_pressure_pct"], 0.0)

    def test_sell_pressure_is_float(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r["estimated_sell_pressure_pct"], float)

    def test_advisor_has_high_sell_pressure(self):
        r = self.est.estimate(_make_payload(recipient_type="advisor", staking_locked_pct=0))
        self.assertGreater(r["estimated_sell_pressure_pct"], 0.5)

    def test_public_has_low_sell_pressure(self):
        r = self.est.estimate(_make_payload(recipient_type="public", staking_locked_pct=0))
        self.assertLess(r["estimated_sell_pressure_pct"], 0.4)

    def test_treasury_has_low_sell_pressure(self):
        r = self.est.estimate(_make_payload(recipient_type="treasury", staking_locked_pct=0))
        self.assertLess(r["estimated_sell_pressure_pct"], 0.2)


# ===========================================================================
# 5. price_impact_pct
# ===========================================================================

class TestPriceImpact(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_price_impact_non_negative(self):
        r = self.est.estimate(_make_payload())
        self.assertGreaterEqual(r["price_impact_pct"], 0.0)

    def test_price_impact_max_100(self):
        r = self.est.estimate(_make_payload(
            unlock_amount_tokens=1_000_000_000,
            current_price_usd=1_000.0,
            current_market_cap_usd=1.0,
            avg_daily_volume_usd=1.0,
            recipient_type="team",
        ))
        self.assertLessEqual(r["price_impact_pct"], 100.0)

    def test_larger_unlock_higher_impact(self):
        r1 = self.est.estimate(_make_payload(unlock_amount_tokens=100_000))
        r2 = self.est.estimate(_make_payload(unlock_amount_tokens=10_000_000))
        self.assertGreaterEqual(r2["price_impact_pct"], r1["price_impact_pct"])

    def test_larger_market_cap_lowers_impact(self):
        r1 = self.est.estimate(_make_payload(current_market_cap_usd=1_000_000))
        r2 = self.est.estimate(_make_payload(current_market_cap_usd=1_000_000_000))
        self.assertGreater(r1["price_impact_pct"], r2["price_impact_pct"])

    def test_high_revenue_reduces_impact(self):
        r_no_rev = self.est.estimate(_make_payload(protocol_revenue_usd_per_month=0))
        r_hi_rev = self.est.estimate(_make_payload(protocol_revenue_usd_per_month=10_000_000))
        self.assertGreaterEqual(r_no_rev["price_impact_pct"], r_hi_rev["price_impact_pct"])

    def test_zero_unlock_zero_impact(self):
        r = self.est.estimate(_make_payload(unlock_amount_tokens=0))
        self.assertEqual(r["price_impact_pct"], 0.0)

    def test_price_impact_is_float(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r["price_impact_pct"], float)

    def test_team_unlock_higher_impact_than_community(self):
        r_team = self.est.estimate(_make_payload(recipient_type="team"))
        r_comm = self.est.estimate(_make_payload(recipient_type="community"))
        self.assertGreater(r_team["price_impact_pct"], r_comm["price_impact_pct"])


# ===========================================================================
# 6. unlock_risk_label
# ===========================================================================

class TestRiskLabel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_label_always_valid(self):
        for rt in ["team", "investor", "community", "ecosystem", "treasury"]:
            r = self.est.estimate(_make_payload(recipient_type=rt))
            self.assertIn(r["unlock_risk_label"], VALID_LABELS)

    def test_negligible_label_for_tiny_unlock(self):
        r = self.est.estimate(_make_payload(
            unlock_amount_tokens=1,
            current_price_usd=0.001,
            current_market_cap_usd=500_000_000,
            avg_daily_volume_usd=50_000_000,
            recipient_type="community",
            staking_locked_pct=90,
        ))
        self.assertEqual(r["unlock_risk_label"], "NEGLIGIBLE_IMPACT")

    def test_extreme_label_for_massive_unlock(self):
        r = self.est.estimate(_make_payload(
            unlock_amount_tokens=100_000_000,
            current_price_usd=1.0,
            current_market_cap_usd=1_000_000,
            avg_daily_volume_usd=10_000,
            recipient_type="team",
            staking_locked_pct=0,
        ))
        self.assertEqual(r["unlock_risk_label"], "EXTREME_SELL_PRESSURE")

    def test_label_is_string(self):
        r = self.est.estimate(_make_payload())
        self.assertIsInstance(r["unlock_risk_label"], str)

    def test_low_impact_label(self):
        # Moderate-size unlock, low sell pressure
        r = self.est.estimate(_make_payload(
            unlock_amount_tokens=50_000,
            current_price_usd=1.0,
            current_market_cap_usd=100_000_000,
            avg_daily_volume_usd=10_000_000,
            recipient_type="community",
            staking_locked_pct=50,
        ))
        self.assertIn(r["unlock_risk_label"], {"NEGLIGIBLE_IMPACT", "LOW_IMPACT"})

    def test_significant_drop_risk(self):
        r = self.est.estimate(_make_payload(
            unlock_amount_tokens=5_000_000,
            current_price_usd=2.0,
            current_market_cap_usd=10_000_000,
            avg_daily_volume_usd=300_000,
            recipient_type="investor",
            staking_locked_pct=0,
        ))
        self.assertIn(r["unlock_risk_label"], {
            "SIGNIFICANT_DROP_RISK", "EXTREME_SELL_PRESSURE", "MODERATE_IMPACT"
        })

    def test_five_valid_labels_exist(self):
        self.assertEqual(len(VALID_LABELS), 5)


# ===========================================================================
# 7. estimate_batch
# ===========================================================================

class TestEstimateBatch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_batch_returns_list(self):
        results = self.est.estimate_batch([_make_payload(), _make_payload()])
        self.assertIsInstance(results, list)

    def test_batch_length_matches_input(self):
        payloads = [_make_payload() for _ in range(5)]
        results = self.est.estimate_batch(payloads)
        self.assertEqual(len(results), 5)

    def test_batch_empty_list(self):
        results = self.est.estimate_batch([])
        self.assertEqual(results, [])

    def test_batch_none_input(self):
        results = self.est.estimate_batch(None)
        self.assertEqual(results, [])

    def test_batch_each_element_is_dict(self):
        results = self.est.estimate_batch([_make_payload(), _make_payload()])
        for r in results:
            self.assertIsInstance(r, dict)

    def test_batch_each_has_label(self):
        results = self.est.estimate_batch([_make_payload(recipient_type=rt)
                                           for rt in ["team", "community", "ecosystem"]])
        for r in results:
            self.assertIn("unlock_risk_label", r)


# ===========================================================================
# 8. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "token_unlock_price_impact_log.json")
        self.est = DeFiProtocolTokenUnlockPriceImpactEstimator(log_path=self.log_path)

    def test_log_file_created_on_estimate(self):
        self.est.estimate(_make_payload())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_on_multiple_calls(self):
        for _ in range(3):
            self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        est = DeFiProtocolTokenUnlockPriceImpactEstimator(log_path=self.log_path, log_cap=5)
        for _ in range(10):
            est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_log_entry_has_ts(self):
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_token_name(self):
        self.est.estimate(_make_payload(token_name="LOGTEST"))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["token_name"], "LOGTEST")

    def test_log_entry_has_price_impact_pct(self):
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("price_impact_pct", data[0])

    def test_log_entry_has_unlock_risk_label(self):
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("unlock_risk_label", data[0])

    def test_log_entry_has_unlock_value_usd(self):
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("unlock_value_usd", data[0])

    def test_log_atomic_write_no_tmp_leftover(self):
        self.est.estimate(_make_payload())
        tmp_path = self.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))

    def test_corrupted_log_resets_gracefully(self):
        with open(self.log_path, "w") as f:
            f.write("NOT_JSON{{")
        # should not raise
        self.est.estimate(_make_payload())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_batch_creates_multiple_entries(self):
        self.est.estimate_batch([_make_payload() for _ in range(4)])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)


# ===========================================================================
# 9. Helper functions
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-5.0, 0.0, 100.0), 0.0)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_clamp_at_min(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_clamp_at_max(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)

    def test_safe_float_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_safe_float_string(self):
        self.assertEqual(_safe_float("3.14"), 3.14)

    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_safe_float_bad_string(self):
        self.assertEqual(_safe_float("abc", -1.0), -1.0)

    def test_safe_float_empty_string(self):
        self.assertEqual(_safe_float("", 0.0), 0.0)

    def test_sell_pressure_recipient_team(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["team"], 0.60)

    def test_sell_pressure_recipient_investor(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["investor"], 0.70)

    def test_sell_pressure_recipient_community(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["community"], 0.20)

    def test_sell_pressure_recipient_ecosystem(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["ecosystem"], 0.25)

    def test_sell_pressure_recipient_treasury(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["treasury"], 0.10)

    def test_sell_pressure_recipient_advisor(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["advisor"], 0.65)

    def test_sell_pressure_recipient_public(self):
        self.assertEqual(SELL_PRESSURE_BY_RECIPIENT["public"], 0.15)


# ===========================================================================
# 10. Internal method unit tests
# ===========================================================================

class TestInternalMethods(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_sell_pressure_for_recipient_team(self):
        self.assertAlmostEqual(
            self.est._sell_pressure_for_recipient("team"), 0.60, places=5
        )

    def test_sell_pressure_for_recipient_uppercase(self):
        # should normalize to lower
        self.assertAlmostEqual(
            self.est._sell_pressure_for_recipient("TEAM"), 0.60, places=5
        )

    def test_staking_absorption_factor_zero(self):
        self.assertAlmostEqual(
            self.est._staking_absorption_factor(0.0), 1.0, places=5
        )

    def test_staking_absorption_factor_100(self):
        self.assertAlmostEqual(
            self.est._staking_absorption_factor(100.0), 0.5, places=5
        )

    def test_staking_absorption_factor_50(self):
        self.assertAlmostEqual(
            self.est._staking_absorption_factor(50.0), 0.75, places=5
        )

    def test_cliff_multiplier_zero(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(0), 1.0, places=5)

    def test_cliff_multiplier_3months(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(3), 0.90, places=5)

    def test_cliff_multiplier_6months(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(6), 0.85, places=5)

    def test_cliff_multiplier_12months(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(12), 0.80, places=5)

    def test_cliff_multiplier_24months(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(24), 0.70, places=5)

    def test_cliff_multiplier_negative_treated_as_zero(self):
        self.assertAlmostEqual(self.est._cliff_multiplier(-5), 1.0, places=5)

    def test_compute_unlock_value_usd(self):
        p = _make_payload(current_price_usd=3.0, unlock_amount_tokens=200_000)
        self.assertAlmostEqual(self.est._compute_unlock_value_usd(p), 600_000.0, places=2)

    def test_compute_volume_ratio_basic(self):
        ratio = self.est._compute_volume_ratio(3_000_000, 1_000_000)
        # 3_000_000 / (1_000_000 * 30) = 0.1
        self.assertAlmostEqual(ratio, 0.1, places=6)

    def test_compute_volume_ratio_zero_volume(self):
        self.assertEqual(self.est._compute_volume_ratio(1_000, 0), 0.0)

    def test_compute_sell_pressure_community(self):
        p = _make_payload(recipient_type="community", vesting_cliff_months=0, staking_locked_pct=0)
        self.assertAlmostEqual(
            self.est._compute_estimated_sell_pressure_pct(p), 0.20, places=4
        )

    def test_assign_label_negligible(self):
        self.assertEqual(self.est._assign_label(0.0), "NEGLIGIBLE_IMPACT")

    def test_assign_label_low(self):
        self.assertEqual(self.est._assign_label(2.0), "LOW_IMPACT")

    def test_assign_label_moderate(self):
        self.assertEqual(self.est._assign_label(8.0), "MODERATE_IMPACT")

    def test_assign_label_significant(self):
        self.assertEqual(self.est._assign_label(20.0), "SIGNIFICANT_DROP_RISK")

    def test_assign_label_extreme(self):
        self.assertEqual(self.est._assign_label(50.0), "EXTREME_SELL_PRESSURE")

    def test_assign_label_boundary_exactly_1(self):
        # exactly 1.0 → LOW_IMPACT (≥1.0 threshold crossed)
        self.assertEqual(self.est._assign_label(1.0), "LOW_IMPACT")

    def test_assign_label_boundary_exactly_5(self):
        self.assertEqual(self.est._assign_label(5.0), "MODERATE_IMPACT")

    def test_assign_label_boundary_exactly_15(self):
        self.assertEqual(self.est._assign_label(15.0), "SIGNIFICANT_DROP_RISK")

    def test_assign_label_boundary_exactly_30(self):
        self.assertEqual(self.est._assign_label(30.0), "EXTREME_SELL_PRESSURE")


# ===========================================================================
# 11. Edge cases & robustness
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.est = _make_estimator(self.tmp)

    def test_missing_token_name_defaults_to_empty(self):
        payload = _make_payload()
        del payload["token_name"]
        r = self.est.estimate(payload)
        self.assertEqual(r["token_name"], "")

    def test_negative_price_clamped_to_zero_value(self):
        r = self.est.estimate(_make_payload(current_price_usd=-1.0))
        self.assertEqual(r["unlock_value_usd"], 0.0)

    def test_very_high_staking_reduces_impact(self):
        r_low = self.est.estimate(_make_payload(staking_locked_pct=0))
        r_hi = self.est.estimate(_make_payload(staking_locked_pct=99))
        self.assertGreaterEqual(r_low["price_impact_pct"], r_hi["price_impact_pct"])

    def test_all_recipient_types_produce_valid_label(self):
        for rt in ["team", "investor", "community", "ecosystem", "treasury", "advisor", "public"]:
            with self.subTest(rt=rt):
                r = self.est.estimate(_make_payload(recipient_type=rt))
                self.assertIn(r["unlock_risk_label"], VALID_LABELS)

    def test_price_impact_non_negative_all_recipients(self):
        for rt in ["team", "investor", "community", "ecosystem", "treasury"]:
            with self.subTest(rt=rt):
                r = self.est.estimate(_make_payload(recipient_type=rt))
                self.assertGreaterEqual(r["price_impact_pct"], 0.0)

    def test_volume_ratio_nonneg_all_recipients(self):
        for rt in ["team", "investor", "community"]:
            with self.subTest(rt=rt):
                r = self.est.estimate(_make_payload(recipient_type=rt))
                self.assertGreaterEqual(r["volume_ratio"], 0.0)

    def test_large_cliff_still_returns_valid_label(self):
        r = self.est.estimate(_make_payload(vesting_cliff_months=120))
        self.assertIn(r["unlock_risk_label"], VALID_LABELS)

    def test_zero_market_cap_handled(self):
        # Should not raise, market cap clamped to 1
        r = self.est.estimate(_make_payload(current_market_cap_usd=0))
        self.assertIsInstance(r, dict)
        self.assertLessEqual(r["price_impact_pct"], 100.0)

    def test_result_is_deterministic(self):
        p = _make_payload()
        r1 = self.est.estimate(p)
        r2 = self.est.estimate(p)
        self.assertEqual(r1["price_impact_pct"], r2["price_impact_pct"])
        self.assertEqual(r1["unlock_risk_label"], r2["unlock_risk_label"])

    def test_staking_pct_exactly_100(self):
        r = self.est.estimate(_make_payload(staking_locked_pct=100))
        self.assertLessEqual(r["estimated_sell_pressure_pct"], 0.5)

    def test_staking_pct_over_100_clamped(self):
        r = self.est.estimate(_make_payload(staking_locked_pct=200))
        self.assertGreaterEqual(r["estimated_sell_pressure_pct"], 0.0)

    def test_float_inputs_as_strings_handled(self):
        r = self.est.estimate(_make_payload(
            current_price_usd="2.5",
            unlock_amount_tokens="1000",
        ))
        self.assertAlmostEqual(r["unlock_value_usd"], 2500.0, places=2)


if __name__ == "__main__":
    unittest.main()
