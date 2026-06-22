"""
Tests for MP-963: ProtocolDeFiDepegContagionModeler
Run: python3 -m unittest spa_core.tests.test_protocol_defi_depeg_contagion_modeler -v
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_depeg_contagion_modeler import (
    ProtocolDeFiDepegContagionModeler,
    _contagion_label,
    _clamp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fiat_stable(**kw):
    """Conservative fiat-backed stablecoin (USDC-like)."""
    base = {
        "name": "USDC",
        "peg_type": "fiat_backed",
        "current_peg_deviation_pct": 0.01,
        "collateral_ratio_pct": 100.0,
        "backing_assets": [{"asset": "USD", "pct_of_backing": 100.0}],
        "tvl_as_collateral_in_protocols_usd": 5_000_000_000,
        "protocols_exposed": ["Aave", "Compound", "MakerDAO"],
        "daily_redemption_capacity_usd": 1_000_000_000,
        "death_spiral_threshold_pct": 5.0,
        "market_cap_usd": 30_000_000_000,
    }
    base.update(kw)
    return base


def _algo_stable(**kw):
    """Algorithmic stablecoin (UST-like — high risk)."""
    base = {
        "name": "AlgoUSD",
        "peg_type": "algo",
        "current_peg_deviation_pct": 2.0,
        "collateral_ratio_pct": 10.0,
        "backing_assets": [{"asset": "LUNA", "pct_of_backing": 100.0}],
        "tvl_as_collateral_in_protocols_usd": 10_000_000_000,
        "protocols_exposed": ["Anchor", "Mirror", "Curve", "Aave", "Compound", "dYdX", "Frax"],
        "daily_redemption_capacity_usd": 50_000_000,
        "death_spiral_threshold_pct": 3.0,
        "market_cap_usd": 20_000_000_000,
    }
    base.update(kw)
    return base


def _crypto_stable(**kw):
    """Crypto-backed stablecoin (DAI-like)."""
    base = {
        "name": "DAI",
        "peg_type": "crypto_backed",
        "current_peg_deviation_pct": 0.1,
        "collateral_ratio_pct": 175.0,
        "backing_assets": [{"asset": "ETH", "pct_of_backing": 60.0},
                           {"asset": "WBTC", "pct_of_backing": 40.0}],
        "tvl_as_collateral_in_protocols_usd": 3_000_000_000,
        "protocols_exposed": ["MakerDAO", "Aave", "Compound"],
        "daily_redemption_capacity_usd": 500_000_000,
        "death_spiral_threshold_pct": 10.0,
        "market_cap_usd": 5_000_000_000,
    }
    base.update(kw)
    return base


def _make_modeler(tmp_dir):
    log = os.path.join(tmp_dir, "depeg_contagion_log.json")
    return ProtocolDeFiDepegContagionModeler(log_path=log), log


# ===========================================================================
# Tests
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(55.0), 55.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_contagion_label_contained(self):
        self.assertEqual(_contagion_label(0.0),  "CONTAINED")
        self.assertEqual(_contagion_label(19.9), "CONTAINED")

    def test_contagion_label_moderate(self):
        self.assertEqual(_contagion_label(20.0), "MODERATE_SPILLOVER")
        self.assertEqual(_contagion_label(39.9), "MODERATE_SPILLOVER")

    def test_contagion_label_significant(self):
        self.assertEqual(_contagion_label(40.0), "SIGNIFICANT_CONTAGION")
        self.assertEqual(_contagion_label(59.9), "SIGNIFICANT_CONTAGION")

    def test_contagion_label_systemic(self):
        self.assertEqual(_contagion_label(60.0), "SYSTEMIC_RISK")
        self.assertEqual(_contagion_label(79.9), "SYSTEMIC_RISK")

    def test_contagion_label_collapse(self):
        self.assertEqual(_contagion_label(80.0),  "COLLAPSE_SCENARIO")
        self.assertEqual(_contagion_label(100.0), "COLLAPSE_SCENARIO")


class TestInit(unittest.TestCase):

    def test_init_default_log_path(self):
        m = ProtocolDeFiDepegContagionModeler()
        self.assertIsNotNone(m.log_path)
        self.assertTrue(m.log_path.endswith("depeg_contagion_log.json"))

    def test_init_custom_log_path(self):
        m = ProtocolDeFiDepegContagionModeler(log_path="/tmp/custom_depeg.json")
        self.assertEqual(m.log_path, "/tmp/custom_depeg.json")


class TestModelEmpty(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_model_empty_list(self):
        out = self.modeler.model([], config=self.cfg)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["stablecoin_count"], 0)
        self.assertEqual(out["results"], [])

    def test_model_empty_aggregates(self):
        out = self.modeler.model([], config=self.cfg)
        agg = out["aggregates"]
        self.assertIsNone(agg["most_stable"])
        self.assertIsNone(agg["highest_contagion_risk"])
        self.assertEqual(agg["total_tvl_at_risk_usd"], 0.0)
        self.assertEqual(agg["systemic_risk_count"], 0)
        self.assertEqual(agg["average_stability_score"], 0.0)

    def test_model_returns_dict(self):
        out = self.modeler.model([], config=self.cfg)
        self.assertIsInstance(out, dict)

    def test_timestamp_in_output(self):
        out = self.modeler.model([], config=self.cfg)
        self.assertIn("timestamp", out)
        self.assertIsInstance(out["timestamp"], str)

    def test_stablecoin_count_in_output(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertEqual(out["stablecoin_count"], 1)


class TestStabilityScore(unittest.TestCase):

    def setUp(self):
        self.m = ProtocolDeFiDepegContagionModeler(log_path="/dev/null")

    def test_stability_score_fiat_backed_good(self):
        sc = _fiat_stable(collateral_ratio_pct=175.0, current_peg_deviation_pct=0.0,
                          daily_redemption_capacity_usd=5_000_000_000,
                          market_cap_usd=10_000_000_000)
        score = self.m.compute_stability_score(sc)
        self.assertGreater(score, 50.0)

    def test_stability_score_algo_lower(self):
        sc_fiat = _fiat_stable()
        sc_algo = _algo_stable(collateral_ratio_pct=100.0, current_peg_deviation_pct=0.0,
                               death_spiral_threshold_pct=5.0, market_cap_usd=1_000_000_000,
                               daily_redemption_capacity_usd=100_000_000)
        score_fiat = self.m.compute_stability_score(sc_fiat)
        score_algo = self.m.compute_stability_score(sc_algo)
        self.assertLess(score_algo, score_fiat)

    def test_stability_score_crypto_backed_penalty(self):
        sc_fiat   = _fiat_stable(collateral_ratio_pct=100.0)
        sc_crypto = _crypto_stable(collateral_ratio_pct=100.0, current_peg_deviation_pct=0.0)
        s_fiat   = self.m.compute_stability_score(sc_fiat)
        s_crypto = self.m.compute_stability_score(sc_crypto)
        self.assertLess(s_crypto, s_fiat)

    def test_stability_score_hybrid_penalty(self):
        sc_fiat   = _fiat_stable(collateral_ratio_pct=100.0)
        sc_hybrid = _fiat_stable(peg_type="hybrid", collateral_ratio_pct=100.0)
        s_fiat   = self.m.compute_stability_score(sc_fiat)
        s_hybrid = self.m.compute_stability_score(sc_hybrid)
        self.assertLessEqual(s_hybrid, s_fiat)

    def test_collateral_below_100_penalty(self):
        sc_full = _fiat_stable(collateral_ratio_pct=100.0)
        sc_low  = _fiat_stable(collateral_ratio_pct=80.0)
        s_full = self.m.compute_stability_score(sc_full)
        s_low  = self.m.compute_stability_score(sc_low)
        self.assertLess(s_low, s_full)

    def test_collateral_above_200_bonus(self):
        sc_100 = _fiat_stable(collateral_ratio_pct=100.0)
        sc_200 = _fiat_stable(collateral_ratio_pct=205.0)
        s_100 = self.m.compute_stability_score(sc_100)
        s_200 = self.m.compute_stability_score(sc_200)
        self.assertGreater(s_200, s_100)

    def test_collateral_above_150_bonus(self):
        sc_120 = _fiat_stable(collateral_ratio_pct=120.0)
        sc_175 = _fiat_stable(collateral_ratio_pct=175.0)
        s_120 = self.m.compute_stability_score(sc_120)
        s_175 = self.m.compute_stability_score(sc_175)
        self.assertGreaterEqual(s_175, s_120)

    def test_collateral_exact_100(self):
        sc = _fiat_stable(collateral_ratio_pct=100.0, current_peg_deviation_pct=0.0)
        score = self.m.compute_stability_score(sc)
        self.assertGreaterEqual(score, 0.0)

    def test_collateral_exact_150(self):
        sc = _fiat_stable(collateral_ratio_pct=150.0)
        score = self.m.compute_stability_score(sc)
        self.assertGreaterEqual(score, 0.0)

    def test_deviation_near_threshold_penalty(self):
        sc_ok  = _fiat_stable(current_peg_deviation_pct=0.1, death_spiral_threshold_pct=5.0)
        sc_bad = _fiat_stable(current_peg_deviation_pct=4.5, death_spiral_threshold_pct=5.0)
        s_ok  = self.m.compute_stability_score(sc_ok)
        s_bad = self.m.compute_stability_score(sc_bad)
        self.assertLess(s_bad, s_ok)

    def test_deviation_above_spiral_threshold_big_penalty(self):
        sc = _fiat_stable(current_peg_deviation_pct=4.1, death_spiral_threshold_pct=5.0)
        score = self.m.compute_stability_score(sc)
        self.assertLessEqual(score, 50.0)

    def test_deviation_zero_no_penalty(self):
        sc = _fiat_stable(current_peg_deviation_pct=0.0)
        score_zero = self.m.compute_stability_score(sc)
        sc2 = _fiat_stable(current_peg_deviation_pct=0.5)
        score_some = self.m.compute_stability_score(sc2)
        self.assertGreaterEqual(score_zero, score_some)

    def test_high_redemption_capacity_bonus(self):
        sc_low  = _fiat_stable(daily_redemption_capacity_usd=100_000,
                               market_cap_usd=100_000_000)
        sc_high = _fiat_stable(daily_redemption_capacity_usd=60_000_000,
                               market_cap_usd=100_000_000)
        s_low  = self.m.compute_stability_score(sc_low)
        s_high = self.m.compute_stability_score(sc_high)
        self.assertGreater(s_high, s_low)

    def test_low_redemption_capacity_penalty(self):
        sc = _fiat_stable(daily_redemption_capacity_usd=1_000,
                          market_cap_usd=100_000_000)
        score = self.m.compute_stability_score(sc)
        sc2 = _fiat_stable(daily_redemption_capacity_usd=50_000_000,
                           market_cap_usd=100_000_000)
        score2 = self.m.compute_stability_score(sc2)
        self.assertLessEqual(score, score2)

    def test_stability_score_range(self):
        for sc in [_fiat_stable(), _algo_stable(), _crypto_stable()]:
            s = self.m.compute_stability_score(sc)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_stability_score_max_100(self):
        sc = _fiat_stable(collateral_ratio_pct=300.0, current_peg_deviation_pct=0.0,
                          daily_redemption_capacity_usd=100_000_000_000,
                          market_cap_usd=1_000_000)
        score = self.m.compute_stability_score(sc)
        self.assertLessEqual(score, 100.0)

    def test_stability_score_min_0(self):
        sc = _algo_stable(collateral_ratio_pct=10.0, current_peg_deviation_pct=99.0,
                          death_spiral_threshold_pct=5.0, daily_redemption_capacity_usd=0.0,
                          market_cap_usd=1)
        score = self.m.compute_stability_score(sc)
        self.assertGreaterEqual(score, 0.0)


class TestContagionSpread(unittest.TestCase):

    def setUp(self):
        self.m = ProtocolDeFiDepegContagionModeler(log_path="/dev/null")

    def test_contagion_spread_equals_tvl(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=2_000_000_000)
        spread = self.m.compute_contagion_spread_usd(sc)
        self.assertAlmostEqual(spread, 2_000_000_000.0)

    def test_contagion_spread_zero(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0)
        spread = self.m.compute_contagion_spread_usd(sc)
        self.assertEqual(spread, 0.0)

    def test_contagion_spread_large(self):
        sc = _algo_stable(tvl_as_collateral_in_protocols_usd=50_000_000_000)
        spread = self.m.compute_contagion_spread_usd(sc)
        self.assertAlmostEqual(spread, 50_000_000_000.0)


class TestRedemptionRunHours(unittest.TestCase):

    def setUp(self):
        self.m = ProtocolDeFiDepegContagionModeler(log_path="/dev/null")

    def test_basic_redemption_run_hours(self):
        sc = _fiat_stable(market_cap_usd=1_000_000_000, daily_redemption_capacity_usd=1_000_000_000)
        hours = self.m.compute_redemption_run_hours(sc)
        self.assertAlmostEqual(hours, 24.0)

    def test_zero_capacity_returns_inf(self):
        sc = _fiat_stable(daily_redemption_capacity_usd=0)
        hours = self.m.compute_redemption_run_hours(sc)
        self.assertEqual(hours, float("inf"))

    def test_high_capacity_short_hours(self):
        sc = _fiat_stable(market_cap_usd=1_000_000_000,
                          daily_redemption_capacity_usd=4_000_000_000)
        hours = self.m.compute_redemption_run_hours(sc)
        self.assertAlmostEqual(hours, 6.0)

    def test_redemption_run_hours_multiple(self):
        sc = _fiat_stable(market_cap_usd=30_000_000_000, daily_redemption_capacity_usd=1_000_000_000)
        hours = self.m.compute_redemption_run_hours(sc)
        self.assertAlmostEqual(hours, 720.0)


class TestCascadeRiskScore(unittest.TestCase):

    def setUp(self):
        self.m = ProtocolDeFiDepegContagionModeler(log_path="/dev/null")

    def test_cascade_zero_tvl_zero_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0, protocols_exposed=[])
        score = self.m.compute_cascade_risk_score(sc)
        self.assertEqual(score, 0.0)

    def test_cascade_no_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=1_000_000_000,
                          protocols_exposed=[], market_cap_usd=10_000_000_000)
        score = self.m.compute_cascade_risk_score(sc)
        # 0.60*(10%*100) + 0.40*0 = 6.0
        self.assertAlmostEqual(score, 6.0)

    def test_cascade_one_protocol(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["Aave"])
        score = self.m.compute_cascade_risk_score(sc)
        # 0.60*0 + 0.40*30 = 12.0
        self.assertAlmostEqual(score, 12.0)

    def test_cascade_five_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["A", "B", "C", "D", "E"])
        score = self.m.compute_cascade_risk_score(sc)
        # 0.60*0 + 0.40*70 = 28.0
        self.assertAlmostEqual(score, 28.0)

    def test_cascade_ten_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=[f"P{i}" for i in range(10)])
        score = self.m.compute_cascade_risk_score(sc)
        # 0.60*0 + 0.40*100 = 40.0
        self.assertAlmostEqual(score, 40.0)

    def test_cascade_high_tvl_fraction(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=10_000_000_000,
                          market_cap_usd=10_000_000_000,
                          protocols_exposed=[])
        score = self.m.compute_cascade_risk_score(sc)
        # tvl_fraction = 1.0, 0.60*100 + 0.40*0 = 60.0
        self.assertAlmostEqual(score, 60.0)

    def test_cascade_risk_range(self):
        for sc in [_fiat_stable(), _algo_stable(), _crypto_stable()]:
            s = self.m.compute_cascade_risk_score(sc)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_cascade_three_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["A", "B", "C"])
        score = self.m.compute_cascade_risk_score(sc)
        # 0.60*0 + 0.40*50 = 20.0
        self.assertAlmostEqual(score, 20.0)

    def test_cascade_risk_capped_at_100(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=100_000_000_000,
                          market_cap_usd=1,
                          protocols_exposed=[f"P{i}" for i in range(20)])
        score = self.m.compute_cascade_risk_score(sc)
        self.assertLessEqual(score, 100.0)


class TestFlags(unittest.TestCase):

    def setUp(self):
        self.m = ProtocolDeFiDepegContagionModeler(log_path="/dev/null")

    def test_algo_risk_flag(self):
        sc = _algo_stable()
        flags = self.m.compute_flags(sc)
        self.assertIn("ALGO_RISK", flags)

    def test_no_algo_risk_fiat(self):
        sc = _fiat_stable()
        flags = self.m.compute_flags(sc)
        self.assertNotIn("ALGO_RISK", flags)

    def test_no_algo_risk_crypto(self):
        sc = _crypto_stable()
        flags = self.m.compute_flags(sc)
        self.assertNotIn("ALGO_RISK", flags)

    def test_no_algo_risk_hybrid(self):
        sc = _fiat_stable(peg_type="hybrid")
        flags = self.m.compute_flags(sc)
        self.assertNotIn("ALGO_RISK", flags)

    def test_over_collateralized_flag(self):
        sc = _fiat_stable(collateral_ratio_pct=200.0)
        flags = self.m.compute_flags(sc)
        self.assertIn("OVER_COLLATERALIZED", flags)

    def test_no_over_collateralized_exactly_150(self):
        sc = _fiat_stable(collateral_ratio_pct=150.0)
        flags = self.m.compute_flags(sc)
        self.assertNotIn("OVER_COLLATERALIZED", flags)

    def test_no_over_collateralized_below_150(self):
        sc = _fiat_stable(collateral_ratio_pct=120.0)
        flags = self.m.compute_flags(sc)
        self.assertNotIn("OVER_COLLATERALIZED", flags)

    def test_under_collateralized_flag(self):
        sc = _fiat_stable(collateral_ratio_pct=80.0)
        flags = self.m.compute_flags(sc)
        self.assertIn("UNDER_COLLATERALIZED", flags)

    def test_no_under_collateralized_exactly_100(self):
        sc = _fiat_stable(collateral_ratio_pct=100.0)
        flags = self.m.compute_flags(sc)
        self.assertNotIn("UNDER_COLLATERALIZED", flags)

    def test_death_spiral_imminent_flag(self):
        # deviation > threshold * 0.8
        sc = _fiat_stable(current_peg_deviation_pct=4.5, death_spiral_threshold_pct=5.0)
        flags = self.m.compute_flags(sc)
        self.assertIn("DEATH_SPIRAL_IMMINENT", flags)

    def test_no_death_spiral_imminent(self):
        sc = _fiat_stable(current_peg_deviation_pct=1.0, death_spiral_threshold_pct=5.0)
        flags = self.m.compute_flags(sc)
        self.assertNotIn("DEATH_SPIRAL_IMMINENT", flags)

    def test_death_spiral_exact_threshold(self):
        # 5.0 > 5.0 * 0.8 = 4.0  → imminent
        sc = _fiat_stable(current_peg_deviation_pct=5.0, death_spiral_threshold_pct=5.0)
        flags = self.m.compute_flags(sc)
        self.assertIn("DEATH_SPIRAL_IMMINENT", flags)

    def test_high_protocol_exposure_6(self):
        sc = _fiat_stable(protocols_exposed=["A", "B", "C", "D", "E", "F"])
        flags = self.m.compute_flags(sc)
        self.assertIn("HIGH_PROTOCOL_EXPOSURE", flags)

    def test_high_protocol_exposure_10(self):
        sc = _fiat_stable(protocols_exposed=[f"P{i}" for i in range(10)])
        flags = self.m.compute_flags(sc)
        self.assertIn("HIGH_PROTOCOL_EXPOSURE", flags)

    def test_no_high_protocol_exposure_5(self):
        sc = _fiat_stable(protocols_exposed=["A", "B", "C", "D", "E"])
        flags = self.m.compute_flags(sc)
        self.assertNotIn("HIGH_PROTOCOL_EXPOSURE", flags)

    def test_no_high_protocol_exposure_3(self):
        sc = _fiat_stable(protocols_exposed=["A", "B", "C"])
        flags = self.m.compute_flags(sc)
        self.assertNotIn("HIGH_PROTOCOL_EXPOSURE", flags)

    def test_algo_all_flags(self):
        sc = _algo_stable(
            collateral_ratio_pct=80.0,
            current_peg_deviation_pct=2.9,   # > 3.0 * 0.8 = 2.4
            death_spiral_threshold_pct=3.0,
            protocols_exposed=[f"P{i}" for i in range(6)],
        )
        flags = self.m.compute_flags(sc)
        self.assertIn("ALGO_RISK",             flags)
        self.assertIn("UNDER_COLLATERALIZED",  flags)
        self.assertIn("DEATH_SPIRAL_IMMINENT", flags)
        self.assertIn("HIGH_PROTOCOL_EXPOSURE", flags)

    def test_fiat_backed_overcollat_flags(self):
        sc = _fiat_stable(collateral_ratio_pct=160.0)
        flags = self.m.compute_flags(sc)
        self.assertIn("OVER_COLLATERALIZED", flags)
        self.assertNotIn("ALGO_RISK",            flags)
        self.assertNotIn("UNDER_COLLATERALIZED", flags)


class TestContagionLabel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_label_contained(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0, protocols_exposed=[])
        out = self.modeler.model([sc], config=self.cfg)
        self.assertEqual(out["results"][0]["contagion_label"], "CONTAINED")

    def test_label_moderate_spillover(self):
        # 3 protocols, tvl=0 → protocol_risk=50 → cascade=0.40*50=20.0 → MODERATE_SPILLOVER
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["A", "B", "C"])
        out = self.modeler.model([sc], config=self.cfg)
        self.assertEqual(out["results"][0]["contagion_label"], "MODERATE_SPILLOVER")

    def test_label_significant_contagion(self):
        # 3 protocols → cascade = 20; need 40+
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["A", "B", "C", "D", "E", "F", "G"])  # cascade = 0.40*70=28
        # Let's bump TVL: 0.60*(TVL/mktcap*100) + 0.40*70 = 40 → TVL/mktcap = 20%
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=6_000_000_000,
                          market_cap_usd=30_000_000_000,
                          protocols_exposed=["A"])  # 0.60*20 + 0.40*30 = 12 + 12 = 24
        # Need 40+: try 0.60*(X%*100) + 0.40*70 = 42 → 0.60*(X%) = 14 → X=23.3%
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=7_000_000_000,
                          market_cap_usd=30_000_000_000,
                          protocols_exposed=["A", "B", "C", "D", "E"])
        # 0.60*(7/30*100) + 0.40*70 = 0.60*23.3 + 28 = 14 + 28 = 42
        out = self.modeler.model([sc], config=self.cfg)
        self.assertIn(out["results"][0]["contagion_label"], ("SIGNIFICANT_CONTAGION", "MODERATE_SPILLOVER"))

    def test_label_systemic_risk(self):
        sc = _algo_stable(tvl_as_collateral_in_protocols_usd=15_000_000_000,
                          market_cap_usd=20_000_000_000,
                          protocols_exposed=[f"P{i}" for i in range(5)])
        out = self.modeler.model([sc], config=self.cfg)
        label = out["results"][0]["contagion_label"]
        # 0.60*(15/20*100) + 0.40*70 = 0.60*75 + 28 = 45+28 = 73
        self.assertIn(label, ("SYSTEMIC_RISK", "COLLAPSE_SCENARIO"))

    def test_label_collapse_scenario(self):
        sc = _algo_stable(tvl_as_collateral_in_protocols_usd=20_000_000_000,
                          market_cap_usd=20_000_000_000,
                          protocols_exposed=[f"P{i}" for i in range(10)])
        out = self.modeler.model([sc], config=self.cfg)
        label = out["results"][0]["contagion_label"]
        # 0.60*100 + 0.40*100 = 100
        self.assertEqual(label, "COLLAPSE_SCENARIO")


class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_most_stable(self):
        stable  = _fiat_stable(name="USDC", collateral_ratio_pct=200.0, current_peg_deviation_pct=0.0)
        riskier = _algo_stable(name="AlgoUSD")
        out = self.modeler.model([stable, riskier], config=self.cfg)
        self.assertEqual(out["aggregates"]["most_stable"], "USDC")

    def test_highest_contagion_risk(self):
        low_risk  = _fiat_stable(name="USDC", tvl_as_collateral_in_protocols_usd=0, protocols_exposed=[])
        high_risk = _algo_stable(name="AlgoUSD")
        out = self.modeler.model([low_risk, high_risk], config=self.cfg)
        self.assertEqual(out["aggregates"]["highest_contagion_risk"], "AlgoUSD")

    def test_total_tvl_at_risk(self):
        sc1 = _fiat_stable(name="A", tvl_as_collateral_in_protocols_usd=1_000_000_000)
        sc2 = _fiat_stable(name="B", tvl_as_collateral_in_protocols_usd=2_000_000_000)
        out = self.modeler.model([sc1, sc2], config=self.cfg)
        self.assertAlmostEqual(out["aggregates"]["total_tvl_at_risk_usd"], 3_000_000_000.0)

    def test_systemic_risk_count_zero(self):
        out = self.modeler.model([_fiat_stable(protocols_exposed=[], tvl_as_collateral_in_protocols_usd=0)],
                                 config=self.cfg)
        self.assertEqual(out["aggregates"]["systemic_risk_count"], 0)

    def test_systemic_risk_count_multiple(self):
        risky = _algo_stable(tvl_as_collateral_in_protocols_usd=20_000_000_000,
                             market_cap_usd=20_000_000_000,
                             protocols_exposed=[f"P{i}" for i in range(10)])
        out = self.modeler.model([risky, risky], config=self.cfg)
        # Both should be COLLAPSE_SCENARIO
        self.assertEqual(out["aggregates"]["systemic_risk_count"], 2)

    def test_average_stability_score(self):
        sc1 = _fiat_stable(name="A")
        sc2 = _fiat_stable(name="B")
        out = self.modeler.model([sc1, sc2], config=self.cfg)
        scores = [r["stability_score"] for r in out["results"]]
        expected = round(sum(scores) / 2, 2)
        self.assertAlmostEqual(out["aggregates"]["average_stability_score"], expected)

    def test_multiple_stable_aggregate_count(self):
        stables = [_fiat_stable(name=f"SC{i}") for i in range(5)]
        out = self.modeler.model(stables, config=self.cfg)
        self.assertEqual(out["stablecoin_count"], 5)


class TestResultKeys(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_result_keys_present(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        r = out["results"][0]
        for key in ("name", "peg_type", "stability_score", "contagion_spread_usd",
                    "redemption_run_hours", "cascade_risk_score", "contagion_label", "flags",
                    "current_peg_deviation_pct", "collateral_ratio_pct",
                    "tvl_as_collateral_in_protocols_usd"):
            self.assertIn(key, r)

    def test_output_keys_present(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        for key in ("timestamp", "stablecoin_count", "results", "aggregates"):
            self.assertIn(key, out)

    def test_flags_is_list(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertIsInstance(out["results"][0]["flags"], list)

    def test_backing_assets_field_in_input_handled(self):
        sc = _fiat_stable(backing_assets=[{"asset": "USD", "pct_of_backing": 100.0}])
        out = self.modeler.model([sc], config=self.cfg)
        self.assertIsNotNone(out["results"][0])

    def test_protocols_exposed_list_handled(self):
        sc = _fiat_stable(protocols_exposed=["Aave", "Compound"])
        out = self.modeler.model([sc], config=self.cfg)
        self.assertIsNotNone(out["results"][0])

    def test_none_config_defaults(self):
        log_path = os.path.join(tempfile.mkdtemp(), "default.json")
        m = ProtocolDeFiDepegContagionModeler(log_path=log_path)
        out = m.model([_fiat_stable()], config=None)
        self.assertIsInstance(out, dict)

    def test_empty_config_dict(self):
        log_path = os.path.join(tempfile.mkdtemp(), "ec.json")
        m = ProtocolDeFiDepegContagionModeler(log_path=log_path)
        out = m.model([_fiat_stable()], config={})
        self.assertIsInstance(out, dict)


class TestLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_log_created(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_list(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_added(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_multiple_entries(self):
        for _ in range(5):
            self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_ring_buffer_exact_100(self):
        for _ in range(100):
            self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_atomic_no_tmp_left(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertFalse(os.path.exists(self.log + ".tmp"))

    def test_log_custom_path_via_config(self):
        custom = os.path.join(self.tmp, "custom_depeg.json")
        self.modeler.model([_fiat_stable()], config={"log_path": custom})
        self.assertTrue(os.path.exists(custom))

    def test_log_entry_has_timestamp(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_results(self):
        self.modeler.model([_fiat_stable()], config=self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn("results", data[0])


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.modeler, self.log = _make_modeler(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_death_spiral_exactly_80pct(self):
        # 4.0 > 5.0 * 0.8 = 4.0 → NOT strictly greater, no flag
        sc = _fiat_stable(current_peg_deviation_pct=4.0, death_spiral_threshold_pct=5.0)
        flags = self.modeler.compute_flags(sc)
        self.assertNotIn("DEATH_SPIRAL_IMMINENT", flags)

    def test_death_spiral_just_above_80pct(self):
        sc = _fiat_stable(current_peg_deviation_pct=4.01, death_spiral_threshold_pct=5.0)
        flags = self.modeler.compute_flags(sc)
        self.assertIn("DEATH_SPIRAL_IMMINENT", flags)

    def test_collapse_scenario_in_systemic_count(self):
        sc = _algo_stable(tvl_as_collateral_in_protocols_usd=20_000_000_000,
                          market_cap_usd=20_000_000_000,
                          protocols_exposed=[f"P{i}" for i in range(10)])
        out = self.modeler.model([sc], config=self.cfg)
        self.assertGreater(out["aggregates"]["systemic_risk_count"], 0)

    def test_cascade_risk_1_to_4_protocols(self):
        sc = _fiat_stable(tvl_as_collateral_in_protocols_usd=0,
                          protocols_exposed=["A", "B", "C", "D"])
        score = self.modeler.compute_cascade_risk_score(sc)
        # 4 protocols → protocol_risk=50 (≥3 < 5)
        # 0.60*0 + 0.40*50 = 20
        self.assertAlmostEqual(score, 20.0)

    def test_fiat_backed_no_algo_flag_no_collapse(self):
        sc = _fiat_stable(protocols_exposed=[], tvl_as_collateral_in_protocols_usd=0)
        out = self.modeler.model([sc], config=self.cfg)
        self.assertNotIn("ALGO_RISK", out["results"][0]["flags"])

    def test_model_single_result_length(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertEqual(len(out["results"]), 1)

    def test_stability_is_float(self):
        out = self.modeler.model([_fiat_stable()], config=self.cfg)
        self.assertIsInstance(out["results"][0]["stability_score"], float)


if __name__ == "__main__":
    unittest.main()
