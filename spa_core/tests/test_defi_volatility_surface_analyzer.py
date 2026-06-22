"""
Tests for MP-934 DeFiVolatilitySurfaceAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_volatility_surface_analyzer -v
"""

import json
import os
import sys
import unittest
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_volatility_surface_analyzer import (
    DeFiVolatilitySurfaceAnalyzer,
    _clamp,
    _atomic_log,
    _vol_label,
    _moneyness,
    _intrinsic_value,
    _bid_ask_spread_pct,
    _vol_premium_pct,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(protocol="Lyra", underlying="ETH", strike=2000.0, current=2100.0,
          expiry_days=30.0, implied_vol_pct=80.0, bid=200.0, ask=220.0,
          delta=0.55, gamma=0.05, theta_daily=-5.0, open_interest_usd=500_000.0) -> dict:
    return {
        "protocol": protocol, "underlying": underlying,
        "strike_price_usd": strike, "current_price_usd": current,
        "expiry_days": expiry_days, "option_type": "call",
        "implied_vol_pct": implied_vol_pct, "bid_usd": bid, "ask_usd": ask,
        "delta": delta, "gamma": gamma, "theta_daily_usd": theta_daily,
        "open_interest_usd": open_interest_usd,
    }


def _put(protocol="Lyra", underlying="ETH", strike=2000.0, current=1900.0,
         expiry_days=30.0, implied_vol_pct=90.0, bid=180.0, ask=200.0,
         delta=-0.45, gamma=0.05, theta_daily=-4.5, open_interest_usd=300_000.0) -> dict:
    return {
        "protocol": protocol, "underlying": underlying,
        "strike_price_usd": strike, "current_price_usd": current,
        "expiry_days": expiry_days, "option_type": "put",
        "implied_vol_pct": implied_vol_pct, "bid_usd": bid, "ask_usd": ask,
        "delta": delta, "gamma": gamma, "theta_daily_usd": theta_daily,
        "open_interest_usd": open_interest_usd,
    }


# ===========================================================================
# 1. Utility helpers
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_clamp_within(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_clamp_custom_range(self):
        self.assertEqual(_clamp(150.0, 0.0, 200.0), 150.0)

    def test_clamp_boundary_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_boundary_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)


class TestVolLabel(unittest.TestCase):
    def test_very_low(self):
        self.assertEqual(_vol_label(10.0), "VERY_LOW")

    def test_low_boundary(self):
        self.assertEqual(_vol_label(20.0), "LOW")

    def test_low(self):
        self.assertEqual(_vol_label(35.0), "LOW")

    def test_normal_boundary(self):
        self.assertEqual(_vol_label(40.0), "NORMAL")

    def test_normal(self):
        self.assertEqual(_vol_label(60.0), "NORMAL")

    def test_high_boundary(self):
        self.assertEqual(_vol_label(80.0), "HIGH")

    def test_high(self):
        self.assertEqual(_vol_label(120.0), "HIGH")

    def test_extreme_boundary(self):
        self.assertEqual(_vol_label(150.0), "EXTREME")

    def test_extreme(self):
        self.assertEqual(_vol_label(300.0), "EXTREME")


class TestMoneyness(unittest.TestCase):
    def test_call_itm(self):
        self.assertEqual(_moneyness("call", 2000.0, 2200.0), "ITM")

    def test_call_otm(self):
        self.assertEqual(_moneyness("call", 2000.0, 1800.0), "OTM")

    def test_call_atm(self):
        self.assertEqual(_moneyness("call", 2000.0, 2005.0), "ATM")

    def test_put_itm(self):
        self.assertEqual(_moneyness("put", 2000.0, 1800.0), "ITM")

    def test_put_otm(self):
        self.assertEqual(_moneyness("put", 2000.0, 2200.0), "OTM")

    def test_put_atm(self):
        self.assertEqual(_moneyness("put", 2000.0, 1995.0), "ATM")

    def test_zero_strike_returns_atm(self):
        self.assertEqual(_moneyness("call", 0.0, 2000.0), "ATM")

    def test_zero_price_returns_atm(self):
        self.assertEqual(_moneyness("put", 2000.0, 0.0), "ATM")

    def test_atm_within_1pct(self):
        self.assertEqual(_moneyness("call", 2000.0, 2010.0), "ATM")

    def test_call_just_outside_atm(self):
        self.assertEqual(_moneyness("call", 2000.0, 2025.0), "ITM")


class TestIntrinsicValue(unittest.TestCase):
    def test_call_itm(self):
        self.assertAlmostEqual(_intrinsic_value("call", 2000.0, 2300.0), 300.0)

    def test_call_otm(self):
        self.assertAlmostEqual(_intrinsic_value("call", 2000.0, 1800.0), 0.0)

    def test_put_itm(self):
        self.assertAlmostEqual(_intrinsic_value("put", 2000.0, 1700.0), 300.0)

    def test_put_otm(self):
        self.assertAlmostEqual(_intrinsic_value("put", 2000.0, 2200.0), 0.0)

    def test_call_atm(self):
        self.assertAlmostEqual(_intrinsic_value("call", 2000.0, 2000.0), 0.0)


class TestBidAskSpread(unittest.TestCase):
    def test_normal(self):
        # mid = 210, spread = 20/210*100 ≈ 9.52
        spread = _bid_ask_spread_pct(200.0, 220.0)
        self.assertAlmostEqual(spread, (20.0 / 210.0) * 100.0, places=4)

    def test_zero_mid(self):
        self.assertEqual(_bid_ask_spread_pct(0.0, 0.0), 0.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(_bid_ask_spread_pct(100.0, 100.0), 0.0, places=4)

    def test_wide_spread(self):
        spread = _bid_ask_spread_pct(10.0, 30.0)
        self.assertGreater(spread, 10.0)


class TestVolPremium(unittest.TestCase):
    def test_positive_premium(self):
        vp = _vol_premium_pct(120.0, 60.0)
        self.assertAlmostEqual(vp, 100.0, places=4)

    def test_zero_premium(self):
        vp = _vol_premium_pct(60.0, 60.0)
        self.assertAlmostEqual(vp, 0.0, places=4)

    def test_negative_premium(self):
        vp = _vol_premium_pct(30.0, 60.0)
        self.assertAlmostEqual(vp, -50.0, places=4)

    def test_zero_hist_vol(self):
        vp = _vol_premium_pct(80.0, 0.0)
        self.assertEqual(vp, 0.0)


# ===========================================================================
# 2. Instantiation
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_create(self):
        a = DeFiVolatilitySurfaceAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_callable(self):
        self.assertTrue(callable(DeFiVolatilitySurfaceAnalyzer().analyze))

    def test_empty_list_returns_dict(self):
        result = DeFiVolatilitySurfaceAnalyzer().analyze([], NO_LOG)
        self.assertIsInstance(result, dict)

    def test_raises_typeerror(self):
        with self.assertRaises(TypeError):
            DeFiVolatilitySurfaceAnalyzer().analyze("bad", NO_LOG)

    def test_result_keys(self):
        result = DeFiVolatilitySurfaceAnalyzer().analyze([], NO_LOG)
        for k in ("results", "summary", "aggregates", "timestamp"):
            self.assertIn(k, result)

    def test_timestamp_positive(self):
        result = DeFiVolatilitySurfaceAnalyzer().analyze([], NO_LOG)
        self.assertGreater(result["timestamp"], 0)


# ===========================================================================
# 3. Per-option fields
# ===========================================================================

class TestPerOptionFields(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiVolatilitySurfaceAnalyzer()
        self.result = self.analyzer.analyze([_call()], NO_LOG)
        self.opt = self.result["results"][0]

    def test_protocol_preserved(self):
        self.assertEqual(self.opt["protocol"], "Lyra")

    def test_underlying_preserved(self):
        self.assertEqual(self.opt["underlying"], "ETH")

    def test_moneyness_present(self):
        self.assertIn("moneyness", self.opt)

    def test_bid_ask_spread_pct_present(self):
        self.assertIn("bid_ask_spread_pct", self.opt)

    def test_vol_premium_pct_present(self):
        self.assertIn("vol_premium_pct", self.opt)

    def test_intrinsic_value_present(self):
        self.assertIn("intrinsic_value_usd", self.opt)

    def test_time_value_present(self):
        self.assertIn("time_value_usd", self.opt)

    def test_vol_label_present(self):
        self.assertIn("vol_label", self.opt)

    def test_flags_list(self):
        self.assertIsInstance(self.opt["flags"], list)

    def test_call_itm_moneyness(self):
        # current=2100 > strike=2000 → ITM for call
        self.assertEqual(self.opt["moneyness"], "ITM")

    def test_intrinsic_positive_for_itm_call(self):
        self.assertAlmostEqual(self.opt["intrinsic_value_usd"], 100.0)

    def test_time_value_nonnegative(self):
        self.assertGreaterEqual(self.opt["time_value_usd"], 0.0)

    def test_spread_pct_calc(self):
        # bid=200, ask=220, mid=210
        expected = (20.0 / 210.0) * 100.0
        self.assertAlmostEqual(self.opt["bid_ask_spread_pct"], expected, places=3)


# ===========================================================================
# 4. Moneyness classification
# ===========================================================================

class TestMoneynessClassification(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def test_otm_call(self):
        opt = _call(strike=2500.0, current=2000.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["moneyness"], "OTM")

    def test_atm_call(self):
        opt = _call(strike=2000.0, current=2005.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["moneyness"], "ATM")

    def test_itm_put(self):
        opt = _put(strike=2000.0, current=1700.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["moneyness"], "ITM")

    def test_otm_put(self):
        opt = _put(strike=2000.0, current=2300.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["moneyness"], "OTM")


# ===========================================================================
# 5. Vol labels
# ===========================================================================

class TestVolLabels(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def _opt_with_iv(self, iv):
        return _call(implied_vol_pct=iv)

    def test_very_low_label(self):
        r = self.a.analyze([self._opt_with_iv(10.0)], NO_LOG)["results"][0]
        self.assertEqual(r["vol_label"], "VERY_LOW")

    def test_low_label(self):
        r = self.a.analyze([self._opt_with_iv(30.0)], NO_LOG)["results"][0]
        self.assertEqual(r["vol_label"], "LOW")

    def test_normal_label(self):
        r = self.a.analyze([self._opt_with_iv(60.0)], NO_LOG)["results"][0]
        self.assertEqual(r["vol_label"], "NORMAL")

    def test_high_label(self):
        r = self.a.analyze([self._opt_with_iv(100.0)], NO_LOG)["results"][0]
        self.assertEqual(r["vol_label"], "HIGH")

    def test_extreme_label(self):
        r = self.a.analyze([self._opt_with_iv(200.0)], NO_LOG)["results"][0]
        self.assertEqual(r["vol_label"], "EXTREME")


# ===========================================================================
# 6. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def test_wide_spread_flag(self):
        opt = _call(bid=100.0, ask=130.0)  # mid=115, spread≈26%
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("WIDE_SPREAD", r["flags"])

    def test_no_wide_spread_flag(self):
        opt = _call(bid=200.0, ask=204.0)  # mid=202, spread≈2%
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("WIDE_SPREAD", r["flags"])

    def test_deep_itm_flag_call(self):
        opt = _call(strike=1000.0, current=2000.0)  # 100% ITM
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("DEEP_ITM", r["flags"])

    def test_no_deep_itm_flag_slight_itm(self):
        opt = _call(strike=2000.0, current=2050.0)  # only 2.5% ITM
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("DEEP_ITM", r["flags"])

    def test_expiring_soon_flag(self):
        opt = _call(expiry_days=2.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("EXPIRING_SOON", r["flags"])

    def test_no_expiring_soon_flag(self):
        opt = _call(expiry_days=30.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("EXPIRING_SOON", r["flags"])

    def test_high_gamma_risk_flag(self):
        opt = _call(gamma=0.5)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("HIGH_GAMMA_RISK", r["flags"])

    def test_no_high_gamma_flag(self):
        opt = _call(gamma=0.01)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("HIGH_GAMMA_RISK", r["flags"])

    def test_vol_premium_flag(self):
        # historical_vol default 60, IV=200 > 2*60=120 → VOL_PREMIUM
        opt = _call(implied_vol_pct=200.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("VOL_PREMIUM", r["flags"])

    def test_no_vol_premium_flag(self):
        opt = _call(implied_vol_pct=80.0)  # 80 < 120
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("VOL_PREMIUM", r["flags"])

    def test_custom_gamma_threshold(self):
        opt = _call(gamma=0.15)
        r = self.a.analyze([opt], {**NO_LOG, "gamma_threshold": 0.20})["results"][0]
        self.assertNotIn("HIGH_GAMMA_RISK", r["flags"])

    def test_vol_premium_respects_custom_hist_vol(self):
        opt = _call(implied_vol_pct=80.0)
        # historical_vol=20, so 80 > 2*20=40 → VOL_PREMIUM
        r = self.a.analyze([opt], {**NO_LOG, "historical_vol_pct": 20.0})["results"][0]
        self.assertIn("VOL_PREMIUM", r["flags"])


# ===========================================================================
# 7. Summary surface
# ===========================================================================

class TestSummary(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def test_vol_smile_keys(self):
        opts = [_call(strike=1800.0, implied_vol_pct=90.0),
                _call(strike=2000.0, implied_vol_pct=80.0),
                _call(strike=2200.0, implied_vol_pct=85.0)]
        s = self.a.analyze(opts, NO_LOG)["summary"]["vol_smile"]
        self.assertIn("1800.0", s)
        self.assertIn("2000.0", s)
        self.assertIn("2200.0", s)

    def test_vol_term_structure_keys(self):
        opts = [_call(expiry_days=7.0, implied_vol_pct=120.0),
                _call(expiry_days=30.0, implied_vol_pct=80.0),
                _call(expiry_days=90.0, implied_vol_pct=70.0)]
        ts = self.a.analyze(opts, NO_LOG)["summary"]["vol_term_structure"]
        self.assertIn("7.0", ts)
        self.assertIn("30.0", ts)
        self.assertIn("90.0", ts)

    def test_put_call_skew(self):
        opts = [
            _call(strike=2000.0, implied_vol_pct=80.0),
            _put(strike=2000.0, current=1900.0, implied_vol_pct=95.0),
        ]
        skew = self.a.analyze(opts, NO_LOG)["summary"]["put_call_skew"]
        self.assertIn("2000.0", skew)
        self.assertAlmostEqual(skew["2000.0"], 15.0, places=2)

    def test_put_call_skew_empty_without_pairs(self):
        opts = [_call(strike=2000.0)]
        skew = self.a.analyze(opts, NO_LOG)["summary"]["put_call_skew"]
        self.assertEqual(skew, {})

    def test_vol_smile_averages_same_strike(self):
        opts = [_call(strike=2000.0, implied_vol_pct=80.0),
                _call(strike=2000.0, implied_vol_pct=100.0)]
        smile = self.a.analyze(opts, NO_LOG)["summary"]["vol_smile"]
        self.assertAlmostEqual(smile["2000.0"], 90.0, places=2)

    def test_empty_surfaces_for_no_options(self):
        result = self.a.analyze([], NO_LOG)
        self.assertEqual(result["summary"]["vol_smile"], {})
        self.assertEqual(result["summary"]["vol_term_structure"], {})
        self.assertEqual(result["summary"]["put_call_skew"], {})


# ===========================================================================
# 8. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def test_empty_aggregates(self):
        agg = self.a.analyze([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["highest_iv_option"])
        self.assertIsNone(agg["lowest_iv_option"])
        self.assertEqual(agg["total_open_interest_usd"], 0.0)
        self.assertEqual(agg["average_iv"], 0.0)
        self.assertEqual(agg["put_call_ratio"], 0.0)

    def test_highest_iv(self):
        opts = [_call(protocol="A", implied_vol_pct=50.0),
                _call(protocol="B", implied_vol_pct=200.0)]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertEqual(agg["highest_iv_option"]["protocol"], "B")

    def test_lowest_iv(self):
        opts = [_call(protocol="A", implied_vol_pct=50.0),
                _call(protocol="B", implied_vol_pct=200.0)]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertEqual(agg["lowest_iv_option"]["protocol"], "A")

    def test_total_open_interest(self):
        opts = [_call(open_interest_usd=100_000.0),
                _call(open_interest_usd=200_000.0)]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertAlmostEqual(agg["total_open_interest_usd"], 300_000.0)

    def test_average_iv(self):
        opts = [_call(implied_vol_pct=60.0), _call(implied_vol_pct=100.0)]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertAlmostEqual(agg["average_iv"], 80.0, places=2)

    def test_put_call_ratio(self):
        opts = [_call(), _call(), _put()]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertAlmostEqual(agg["put_call_ratio"], 0.5, places=4)

    def test_put_call_ratio_no_calls(self):
        opts = [_put(), _put()]
        agg = self.a.analyze(opts, NO_LOG)["aggregates"]
        self.assertEqual(agg["put_call_ratio"], 0.0)


# ===========================================================================
# 9. Ring-buffer log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            _atomic_log(p, {"a": 1})
            self.assertTrue(os.path.exists(p))

    def test_content_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            _atomic_log(p, {"a": 1})
            with open(p) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_entry_appended(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            _atomic_log(p, {"x": 42})
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(data[0]["x"], 42)

    def test_cap_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            for i in range(105):
                _atomic_log(p, {"i": i})
            with open(p) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_multiple_entries(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            _atomic_log(p, {"n": 1})
            _atomic_log(p, {"n": 2})
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_write_log_false_no_file(self):
        a = DeFiVolatilitySurfaceAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "no_log.json")
            a.analyze([_call()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_write_log_true_creates_file(self):
        a = DeFiVolatilitySurfaceAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_call()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))


# ===========================================================================
# 10. Edge cases & robustness
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiVolatilitySurfaceAnalyzer()

    def test_missing_fields_use_defaults(self):
        r = self.a.analyze([{}], NO_LOG)
        self.assertIsInstance(r["results"][0], dict)

    def test_zero_bid_ask(self):
        opt = _call(bid=0.0, ask=0.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["bid_ask_spread_pct"], 0.0)

    def test_zero_strike(self):
        opt = _call(strike=0.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertEqual(r["moneyness"], "ATM")

    def test_expiry_exactly_3_no_flag(self):
        opt = _call(expiry_days=3.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertNotIn("EXPIRING_SOON", r["flags"])

    def test_expiry_just_under_3_has_flag(self):
        opt = _call(expiry_days=2.9)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertIn("EXPIRING_SOON", r["flags"])

    def test_large_batch(self):
        opts = [_call(strike=float(1000 + i * 100), implied_vol_pct=float(50 + i))
                for i in range(20)]
        r = self.a.analyze(opts, NO_LOG)
        self.assertEqual(len(r["results"]), 20)

    def test_single_option(self):
        r = self.a.analyze([_call()], NO_LOG)
        self.assertEqual(len(r["results"]), 1)

    def test_none_config_defaults(self):
        r = DeFiVolatilitySurfaceAnalyzer().analyze([_call()], None)
        # Should not raise and return dict
        self.assertIsInstance(r, dict)

    def test_all_puts(self):
        opts = [_put(strike=2000.0, current=1900.0) for _ in range(3)]
        r = self.a.analyze(opts, NO_LOG)
        self.assertEqual(r["aggregates"]["put_call_ratio"], 0.0)

    def test_all_calls(self):
        opts = [_call() for _ in range(3)]
        r = self.a.analyze(opts, NO_LOG)
        self.assertAlmostEqual(r["aggregates"]["put_call_ratio"], 0.0, places=4)

    def test_iv_preserved_in_result(self):
        opt = _call(implied_vol_pct=77.5)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["implied_vol_pct"], 77.5)

    def test_oi_preserved(self):
        opt = _call(open_interest_usd=12345.0)
        r = self.a.analyze([opt], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["open_interest_usd"], 12345.0)


if __name__ == "__main__":
    unittest.main()
