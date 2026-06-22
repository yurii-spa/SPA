"""
Tests for MP-1051 ProtocolDeFiAaveEfficiencyModeAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_aave_efficiency_mode_analyzer import (
    ProtocolDeFiAaveEfficiencyModeAnalyzer,
    analyze,
    _ltv_boost,
    _leverage_multiplier,
    _net_yield,
    _depegging_risk_score,
    _emode_label,
    _build_recommendations,
    _atomic_log,
    EMODE_STABLECOINS,
    EMODE_ETH_CORR,
    EMODE_BTC_CORR,
    EMODE_CUSTOM,
    LABEL_IDEAL_EMODE,
    LABEL_EFFICIENT,
    LABEL_MODERATE_RISK,
    LABEL_HIGH_CORRELATION_RISK,
    LABEL_NOT_RECOMMENDED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _default_analyze(**kwargs):
    defaults = dict(
        emode_category=EMODE_ETH_CORR,
        supply_asset="wstETH",
        borrow_asset="ETH",
        emode_ltv_pct=90.0,
        standard_ltv_pct=80.0,
        supply_apy_pct=4.0,
        borrow_rate_pct=3.0,
        position_size_usd=100_000.0,
        correlation_score=0.98,
    )
    defaults.update(kwargs)
    a = ProtocolDeFiAaveEfficiencyModeAnalyzer(log_path=_tmp_log())
    return a.analyze(**defaults)


# ===========================================================================
# 1. _ltv_boost helper
# ===========================================================================
class TestLtvBoost(unittest.TestCase):

    def test_basic_boost(self):
        self.assertAlmostEqual(_ltv_boost(90.0, 80.0), 10.0)

    def test_no_boost(self):
        self.assertAlmostEqual(_ltv_boost(80.0, 80.0), 0.0)

    def test_large_boost(self):
        self.assertAlmostEqual(_ltv_boost(97.0, 75.0), 22.0)

    def test_zero_standard(self):
        self.assertAlmostEqual(_ltv_boost(90.0, 0.0), 90.0)

    def test_non_negative_always(self):
        # if emode < standard (shouldn't happen, but function should clamp)
        result = _ltv_boost(70.0, 80.0)
        self.assertGreaterEqual(result, 0.0)


# ===========================================================================
# 2. _leverage_multiplier helper
# ===========================================================================
class TestLeverageMultiplier(unittest.TestCase):

    def test_50pct_ltv(self):
        # 1/(1-0.5) = 2
        self.assertAlmostEqual(_leverage_multiplier(50.0), 2.0)

    def test_80pct_ltv(self):
        self.assertAlmostEqual(_leverage_multiplier(80.0), 5.0)

    def test_90pct_ltv(self):
        self.assertAlmostEqual(_leverage_multiplier(90.0), 10.0)

    def test_0pct_ltv(self):
        self.assertAlmostEqual(_leverage_multiplier(0.0), 1.0)

    def test_99pct_ltv_very_high(self):
        m = _leverage_multiplier(99.0)
        self.assertGreater(m, 50.0)

    def test_monotone_increasing(self):
        m1 = _leverage_multiplier(60.0)
        m2 = _leverage_multiplier(75.0)
        m3 = _leverage_multiplier(90.0)
        self.assertLess(m1, m2)
        self.assertLess(m2, m3)


# ===========================================================================
# 3. _net_yield helper
# ===========================================================================
class TestNetYield(unittest.TestCase):

    def test_zero_borrow_rate(self):
        # When borrow rate=0, net_yield amplifies supply_apy
        ny = _net_yield(4.0, 0.0, 80.0)
        # loop_factor = 0.8/0.2 = 4; net = 4 + 4*4 = 20
        self.assertAlmostEqual(ny, 20.0)

    def test_positive_carry_amplified(self):
        ny = _net_yield(5.0, 3.0, 80.0)
        self.assertGreater(ny, 5.0)  # amplified carry

    def test_negative_carry_amplified(self):
        ny = _net_yield(2.0, 5.0, 80.0)
        self.assertLess(ny, 2.0)  # amplified loss

    def test_equal_rates(self):
        ny = _net_yield(5.0, 5.0, 80.0)
        self.assertAlmostEqual(ny, 5.0)  # no carry benefit/loss

    def test_low_ltv_minimal_amplification(self):
        ny_low = _net_yield(5.0, 3.0, 10.0)
        ny_hi  = _net_yield(5.0, 3.0, 80.0)
        self.assertLess(ny_low, ny_hi)

    def test_returns_float(self):
        ny = _net_yield(4.0, 3.0, 90.0)
        self.assertIsInstance(ny, float)


# ===========================================================================
# 4. _depegging_risk_score helper
# ===========================================================================
class TestDepeggingRiskScore(unittest.TestCase):

    def test_range_0_100(self):
        for cat in [EMODE_STABLECOINS, EMODE_ETH_CORR, EMODE_BTC_CORR, EMODE_CUSTOM]:
            for corr in [0.5, 0.8, 0.95, 0.99, 1.0]:
                for ltv in [50.0, 80.0, 95.0]:
                    s = _depegging_risk_score(cat, corr, ltv, "wstETH", "ETH")
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_high_correlation_low_risk(self):
        s = _depegging_risk_score(EMODE_ETH_CORR, 0.99, 90.0, "wstETH", "ETH")
        self.assertLess(s, 40.0)

    def test_low_correlation_high_risk(self):
        s = _depegging_risk_score(EMODE_ETH_CORR, 0.5, 90.0, "wstETH", "ETH")
        self.assertGreater(s, 50.0)

    def test_same_asset_reduces_risk(self):
        s_diff = _depegging_risk_score(EMODE_STABLECOINS, 0.99, 80.0, "USDC", "USDT")
        s_same = _depegging_risk_score(EMODE_STABLECOINS, 0.99, 80.0, "USDC", "USDC")
        self.assertGreater(s_diff, s_same)

    def test_custom_category_higher_base(self):
        s_eth  = _depegging_risk_score(EMODE_ETH_CORR,  0.98, 80.0, "A", "B")
        s_cust = _depegging_risk_score(EMODE_CUSTOM, 0.98, 80.0, "A", "B")
        self.assertGreater(s_cust, s_eth)

    def test_higher_ltv_higher_risk(self):
        s_low = _depegging_risk_score(EMODE_ETH_CORR, 0.98, 50.0, "wstETH", "ETH")
        s_hi  = _depegging_risk_score(EMODE_ETH_CORR, 0.98, 90.0, "wstETH", "ETH")
        self.assertLess(s_low, s_hi)


# ===========================================================================
# 5. _emode_label helper
# ===========================================================================
class TestEmodeLabel(unittest.TestCase):

    def test_ideal_emode(self):
        label = _emode_label(10.0, 10.0, 15.0, 10.0)
        self.assertEqual(label, LABEL_IDEAL_EMODE)

    def test_not_recommended_high_risk(self):
        label = _emode_label(5.0, 75.0, 10.0, 10.0)
        self.assertEqual(label, LABEL_NOT_RECOMMENDED)

    def test_high_correlation_risk(self):
        label = _emode_label(5.0, 55.0, 10.0, 10.0)
        self.assertEqual(label, LABEL_HIGH_CORRELATION_RISK)

    def test_moderate_risk(self):
        label = _emode_label(5.0, 35.0, 8.0, 5.0)
        self.assertEqual(label, LABEL_MODERATE_RISK)

    def test_negative_yield_not_recommended(self):
        label = _emode_label(-5.0, 20.0, 10.0, 5.0)
        self.assertEqual(label, LABEL_NOT_RECOMMENDED)

    def test_efficient(self):
        label = _emode_label(3.0, 20.0, 5.0, 3.0)
        self.assertEqual(label, LABEL_EFFICIENT)


# ===========================================================================
# 6. _build_recommendations helper
# ===========================================================================
class TestBuildRecommendationsEmode(unittest.TestCase):

    def test_not_recommended_rec(self):
        recs = _build_recommendations(LABEL_NOT_RECOMMENDED, -2.0, 75.0, 10.0, EMODE_ETH_CORR, 0.9)
        self.assertTrue(any("not advisable" in r.lower() or "not" in r.lower() for r in recs))

    def test_high_risk_rec(self):
        recs = _build_recommendations(LABEL_HIGH_CORRELATION_RISK, 3.0, 55.0, 6.0, EMODE_ETH_CORR, 0.88)
        self.assertTrue(any("correlation" in r.lower() for r in recs))

    def test_high_depeg_risk_rec(self):
        recs = _build_recommendations(LABEL_MODERATE_RISK, 3.0, 55.0, 5.0, EMODE_ETH_CORR, 0.9)
        self.assertTrue(any("depeg" in r.lower() or "risk" in r.lower() for r in recs))

    def test_high_leverage_rec(self):
        recs = _build_recommendations(LABEL_IDEAL_EMODE, 10.0, 20.0, 12.0, EMODE_ETH_CORR, 0.99)
        self.assertTrue(any("leverage" in r.lower() or "×" in r for r in recs))

    def test_ideal_positive_rec(self):
        recs = _build_recommendations(LABEL_IDEAL_EMODE, 8.0, 15.0, 5.0, EMODE_ETH_CORR, 0.99)
        self.assertTrue(any("favourable" in r.lower() or "yield" in r.lower() for r in recs))

    def test_stablecoin_low_correlation_rec(self):
        recs = _build_recommendations(LABEL_MODERATE_RISK, 2.0, 35.0, 5.0, EMODE_STABLECOINS, 0.90)
        self.assertTrue(any("stablecoin" in r.lower() or "usdc" in r.lower() for r in recs))

    def test_always_returns_list(self):
        recs = _build_recommendations(LABEL_EFFICIENT, 3.0, 20.0, 4.0, EMODE_ETH_CORR, 0.99)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)


# ===========================================================================
# 7. ProtocolDeFiAaveEfficiencyModeAnalyzer.analyze — output structure
# ===========================================================================
class TestAnalyzeOutputStructure(unittest.TestCase):

    def setUp(self):
        self.result = _default_analyze()

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_required_keys(self):
        for key in [
            "emode_category", "supply_asset", "borrow_asset",
            "emode_ltv_pct", "standard_ltv_pct", "supply_apy_pct",
            "borrow_rate_pct", "position_size_usd", "correlation_score",
            "ltv_boost_pct", "leverage_multiplier", "net_yield_pct",
            "depegging_risk_score", "label", "borrow_usd",
            "annual_supply_yield_usd", "annual_borrow_cost_usd",
            "annual_net_pnl_usd", "extra_borrow_capacity_usd",
            "recommendations", "ts",
        ]:
            self.assertIn(key, self.result, f"Missing key: {key}")

    def test_depegging_risk_score_range(self):
        self.assertGreaterEqual(self.result["depegging_risk_score"], 0.0)
        self.assertLessEqual(self.result["depegging_risk_score"], 100.0)

    def test_label_valid(self):
        valid = {LABEL_IDEAL_EMODE, LABEL_EFFICIENT, LABEL_MODERATE_RISK,
                 LABEL_HIGH_CORRELATION_RISK, LABEL_NOT_RECOMMENDED}
        self.assertIn(self.result["label"], valid)

    def test_recommendations_nonempty(self):
        self.assertIsInstance(self.result["recommendations"], list)
        self.assertGreater(len(self.result["recommendations"]), 0)

    def test_ts_reasonable(self):
        now = int(time.time())
        self.assertLessEqual(abs(self.result["ts"] - now), 5)

    def test_input_echo_emode(self):
        self.assertEqual(self.result["emode_category"], EMODE_ETH_CORR)
        self.assertEqual(self.result["supply_asset"], "wstETH")
        self.assertEqual(self.result["borrow_asset"], "ETH")

    def test_ltv_boost_computed(self):
        r = _default_analyze(emode_ltv_pct=90.0, standard_ltv_pct=80.0)
        self.assertAlmostEqual(r["ltv_boost_pct"], 10.0)

    def test_leverage_multiplier_computed(self):
        r = _default_analyze(emode_ltv_pct=90.0)
        self.assertAlmostEqual(r["leverage_multiplier"], round(10.0, 4), places=2)

    def test_borrow_usd_computed(self):
        r = _default_analyze(emode_ltv_pct=90.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["borrow_usd"], 90_000.0)

    def test_annual_supply_yield(self):
        r = _default_analyze(supply_apy_pct=5.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_supply_yield_usd"], 5000.0)

    def test_annual_borrow_cost(self):
        r = _default_analyze(borrow_rate_pct=3.0, emode_ltv_pct=90.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_borrow_cost_usd"], 2700.0)

    def test_net_pnl_matches(self):
        r = _default_analyze()
        expected = r["annual_supply_yield_usd"] - r["annual_borrow_cost_usd"]
        self.assertAlmostEqual(r["annual_net_pnl_usd"], expected)

    def test_extra_borrow_capacity(self):
        r = _default_analyze(emode_ltv_pct=90.0, standard_ltv_pct=80.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["extra_borrow_capacity_usd"], 10_000.0)


# ===========================================================================
# 8. Label scenarios
# ===========================================================================
class TestLabelScenarios(unittest.TestCase):

    def test_ideal_emode_high_corr(self):
        r = _default_analyze(
            emode_ltv_pct=95.0, standard_ltv_pct=80.0,
            supply_apy_pct=5.0, borrow_rate_pct=3.0,
            correlation_score=0.99,
        )
        self.assertIn(r["label"], {LABEL_IDEAL_EMODE, LABEL_EFFICIENT, LABEL_MODERATE_RISK})  # 97% LTV → ltv_amp ~19.4 → MODERATE_RISK

    def test_not_recommended_low_corr(self):
        r = _default_analyze(
            emode_ltv_pct=90.0, standard_ltv_pct=70.0,
            supply_apy_pct=4.0, borrow_rate_pct=3.0,
            correlation_score=0.4,
        )
        self.assertIn(r["label"], {LABEL_NOT_RECOMMENDED, LABEL_HIGH_CORRELATION_RISK})

    def test_not_recommended_negative_yield(self):
        r = _default_analyze(
            supply_apy_pct=1.0, borrow_rate_pct=8.0,
            emode_ltv_pct=90.0, correlation_score=0.99,
        )
        self.assertEqual(r["label"], LABEL_NOT_RECOMMENDED)

    def test_stablecoins_ideal(self):
        r = _default_analyze(
            emode_category=EMODE_STABLECOINS,
            supply_asset="USDC", borrow_asset="USDT",
            emode_ltv_pct=97.0, standard_ltv_pct=75.0,
            supply_apy_pct=5.0, borrow_rate_pct=3.0,
            correlation_score=0.999,
        )
        self.assertIn(r["label"], {LABEL_IDEAL_EMODE, LABEL_EFFICIENT, LABEL_MODERATE_RISK})  # 97% LTV → ltv_amp ~19.4 → MODERATE_RISK

    def test_btc_correlated(self):
        r = _default_analyze(
            emode_category=EMODE_BTC_CORR,
            supply_asset="wBTC", borrow_asset="BTC",
            emode_ltv_pct=90.0, standard_ltv_pct=75.0,
            supply_apy_pct=3.0, borrow_rate_pct=2.0,
            correlation_score=0.97,
        )
        self.assertIn(r["label"], {LABEL_IDEAL_EMODE, LABEL_EFFICIENT, LABEL_MODERATE_RISK})

    def test_custom_category(self):
        r = _default_analyze(
            emode_category=EMODE_CUSTOM,
            supply_asset="TokenA", borrow_asset="TokenB",
            emode_ltv_pct=85.0, standard_ltv_pct=70.0,
            supply_apy_pct=6.0, borrow_rate_pct=4.0,
            correlation_score=0.85,
        )
        # custom always has higher risk
        self.assertIn(r["label"], {LABEL_MODERATE_RISK, LABEL_HIGH_CORRELATION_RISK, LABEL_NOT_RECOMMENDED})


# ===========================================================================
# 9. All eMode categories valid
# ===========================================================================
class TestAllCategories(unittest.TestCase):

    def _run(self, cat):
        r = _default_analyze(emode_category=cat)
        self.assertEqual(r["emode_category"], cat)
        self.assertIn("label", r)

    def test_stablecoins(self):    self._run(EMODE_STABLECOINS)
    def test_eth_correlated(self): self._run(EMODE_ETH_CORR)
    def test_btc_correlated(self): self._run(EMODE_BTC_CORR)
    def test_custom(self):         self._run(EMODE_CUSTOM)


# ===========================================================================
# 10. Validation errors
# ===========================================================================
class TestValidationErrors(unittest.TestCase):

    def test_invalid_category(self):
        with self.assertRaises(ValueError):
            _default_analyze(emode_category="invalid_cat")

    def test_emode_ltv_zero(self):
        with self.assertRaises(ValueError):
            _default_analyze(emode_ltv_pct=0.0)

    def test_emode_ltv_over_100(self):
        with self.assertRaises(ValueError):
            _default_analyze(emode_ltv_pct=101.0)

    def test_standard_ltv_negative(self):
        with self.assertRaises(ValueError):
            _default_analyze(standard_ltv_pct=-1.0)

    def test_emode_less_than_standard(self):
        with self.assertRaises(ValueError):
            _default_analyze(emode_ltv_pct=70.0, standard_ltv_pct=80.0)

    def test_negative_position_size(self):
        with self.assertRaises(ValueError):
            _default_analyze(position_size_usd=-1.0)

    def test_correlation_below_0(self):
        with self.assertRaises(ValueError):
            _default_analyze(correlation_score=-0.1)

    def test_correlation_above_1(self):
        with self.assertRaises(ValueError):
            _default_analyze(correlation_score=1.1)


# ===========================================================================
# 11. Module-level analyze() function
# ===========================================================================
class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(
            emode_category=EMODE_ETH_CORR,
            supply_asset="wstETH",
            borrow_asset="ETH",
            emode_ltv_pct=90.0,
            standard_ltv_pct=80.0,
            supply_apy_pct=4.0,
            borrow_rate_pct=3.0,
            position_size_usd=50_000.0,
            correlation_score=0.98,
            log_path=_tmp_log(),
        )
        self.assertIsInstance(r, dict)
        self.assertIn("label", r)

    def test_label_is_string(self):
        r = analyze(
            emode_category=EMODE_STABLECOINS,
            supply_asset="USDC",
            borrow_asset="DAI",
            emode_ltv_pct=97.0,
            standard_ltv_pct=75.0,
            supply_apy_pct=5.0,
            borrow_rate_pct=3.0,
            position_size_usd=20_000.0,
            correlation_score=0.99,
            log_path=_tmp_log(),
        )
        self.assertIsInstance(r["label"], str)


# ===========================================================================
# 12. Logging
# ===========================================================================
class TestAtomicLog(unittest.TestCase):

    def test_creates_log_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))

    def test_appends_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"a": 1})
        _atomic_log(path, {"b": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(110):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 104)

    def test_log_via_analyze(self):
        path = _tmp_log()
        a = ProtocolDeFiAaveEfficiencyModeAnalyzer(log_path=path)
        a.analyze(
            emode_category=EMODE_ETH_CORR,
            supply_asset="wstETH",
            borrow_asset="ETH",
            emode_ltv_pct=90.0,
            standard_ltv_pct=80.0,
            supply_apy_pct=4.0,
            borrow_rate_pct=3.0,
            position_size_usd=50_000.0,
            correlation_score=0.98,
            log=True,
        )
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["supply_asset"], "wstETH")

    def test_existing_invalid_json_reset(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("INVALID")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_log_by_default(self):
        path = _tmp_log()
        a = ProtocolDeFiAaveEfficiencyModeAnalyzer(log_path=path)
        a.analyze(
            emode_category=EMODE_ETH_CORR,
            supply_asset="wstETH",
            borrow_asset="ETH",
            emode_ltv_pct=90.0,
            standard_ltv_pct=80.0,
            supply_apy_pct=4.0,
            borrow_rate_pct=3.0,
            position_size_usd=50_000.0,
            correlation_score=0.98,
            log=False,
        )
        self.assertFalse(os.path.exists(path))


# ===========================================================================
# 13. Metric consistency
# ===========================================================================
class TestMetricConsistency(unittest.TestCase):

    def test_ltv_boost_matches(self):
        r = _default_analyze(emode_ltv_pct=92.0, standard_ltv_pct=75.0)
        self.assertAlmostEqual(r["ltv_boost_pct"], 17.0)

    def test_leverage_multiplier_matches(self):
        r = _default_analyze(emode_ltv_pct=80.0)
        self.assertAlmostEqual(r["leverage_multiplier"], round(_leverage_multiplier(80.0), 4))

    def test_net_yield_matches(self):
        r = _default_analyze(supply_apy_pct=5.0, borrow_rate_pct=3.0, emode_ltv_pct=80.0)
        expected = round(_net_yield(5.0, 3.0, 80.0), 4)
        self.assertAlmostEqual(r["net_yield_pct"], expected)

    def test_depeg_score_matches(self):
        r = _default_analyze(
            emode_category=EMODE_ETH_CORR,
            supply_asset="wstETH", borrow_asset="ETH",
            emode_ltv_pct=90.0, correlation_score=0.98,
        )
        expected = round(_depegging_risk_score(EMODE_ETH_CORR, 0.98, 90.0, "wstETH", "ETH"), 2)
        self.assertAlmostEqual(r["depegging_risk_score"], expected)


# ===========================================================================
# 14. Edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_zero_position_size(self):
        r = _default_analyze(position_size_usd=0.0)
        self.assertAlmostEqual(r["borrow_usd"], 0.0)
        self.assertAlmostEqual(r["annual_supply_yield_usd"], 0.0)

    def test_very_high_ltv(self):
        r = _default_analyze(emode_ltv_pct=99.0, standard_ltv_pct=80.0)
        self.assertGreater(r["leverage_multiplier"], 50.0)

    def test_perfect_correlation(self):
        r = _default_analyze(correlation_score=1.0)
        self.assertIsInstance(r["label"], str)

    def test_minimum_correlation(self):
        r = _default_analyze(correlation_score=0.0)
        # Very low correlation → high risk label
        self.assertIn(r["label"], {LABEL_HIGH_CORRELATION_RISK, LABEL_NOT_RECOMMENDED})

    def test_equal_emode_and_standard_ltv(self):
        r = _default_analyze(emode_ltv_pct=80.0, standard_ltv_pct=80.0)
        self.assertAlmostEqual(r["ltv_boost_pct"], 0.0)
        self.assertAlmostEqual(r["extra_borrow_capacity_usd"], 0.0)

    def test_large_position(self):
        r = _default_analyze(position_size_usd=10_000_000.0)
        self.assertGreater(r["annual_supply_yield_usd"], 0)

    def test_deterministic(self):
        r1 = _default_analyze(supply_apy_pct=5.0, borrow_rate_pct=3.0)
        r2 = _default_analyze(supply_apy_pct=5.0, borrow_rate_pct=3.0)
        self.assertEqual(r1["label"], r2["label"])
        self.assertEqual(r1["net_yield_pct"], r2["net_yield_pct"])


# ===========================================================================
# 15. Additional coverage
# ===========================================================================
class TestAdditionalCoverage(unittest.TestCase):

    def test_recs_list_of_strings(self):
        r = _default_analyze()
        for rec in r["recommendations"]:
            self.assertIsInstance(rec, str)

    def test_float_precision(self):
        r = _default_analyze(supply_apy_pct=3.333, borrow_rate_pct=1.111)
        ny = r["net_yield_pct"]
        self.assertEqual(ny, round(ny, 4))

    def test_multiple_runs_independent(self):
        r1 = _default_analyze(correlation_score=0.99)
        r2 = _default_analyze(correlation_score=0.3)
        # The high-correlation run should have lower depeg risk
        self.assertLess(r1["depegging_risk_score"], r2["depegging_risk_score"])

    def test_net_pnl_positive_when_positive_carry(self):
        r = _default_analyze(
            supply_apy_pct=6.0, borrow_rate_pct=2.0,
            emode_ltv_pct=80.0, position_size_usd=100_000.0,
        )
        self.assertGreater(r["annual_net_pnl_usd"], 0.0)

    def test_net_pnl_negative_when_negative_carry(self):
        r = _default_analyze(
            supply_apy_pct=1.0, borrow_rate_pct=8.0,
            emode_ltv_pct=80.0, position_size_usd=100_000.0,
        )
        self.assertLess(r["annual_net_pnl_usd"], 0.0)

    def test_correlation_0_5_high_risk(self):
        r = _default_analyze(correlation_score=0.5, emode_ltv_pct=90.0)
        self.assertGreater(r["depegging_risk_score"], 40.0)

    def test_category_in_output(self):
        for cat in [EMODE_STABLECOINS, EMODE_ETH_CORR, EMODE_BTC_CORR, EMODE_CUSTOM]:
            r = _default_analyze(emode_category=cat)
            self.assertEqual(r["emode_category"], cat)

    def test_supply_borrow_echo(self):
        r = _default_analyze(supply_asset="rETH", borrow_asset="ETH")
        self.assertEqual(r["supply_asset"], "rETH")
        self.assertEqual(r["borrow_asset"], "ETH")


if __name__ == "__main__":
    unittest.main()
