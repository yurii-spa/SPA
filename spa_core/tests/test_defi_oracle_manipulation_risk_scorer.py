"""
Tests for MP-962: DeFiOracleManipulationRiskScorer
Run: python3 -m unittest spa_core.tests.test_defi_oracle_manipulation_risk_scorer -v
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_oracle_manipulation_risk_scorer import (
    DeFiOracleManipulationRiskScorer,
    _risk_label,
    _clamp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _chainlink_oracle(**kw):
    base = {
        "name": "ETH/USD Chainlink",
        "protocol": "Aave",
        "oracle_type": "chainlink",
        "twap_window_seconds": 0,
        "deviation_threshold_pct": 0.5,
        "heartbeat_seconds": 3600,
        "num_price_sources": 20,
        "min_sources_required": 3,
        "liquidity_of_underlying_usd": 100_000_000,
        "market_cap_usd": 500_000_000_000,
        "has_circuit_breaker": True,
        "manipulation_incidents_count": 0,
        "audited": True,
        "last_update_seconds_ago": 600,
    }
    base.update(kw)
    return base


def _twap_oracle(**kw):
    base = {
        "name": "USDC/ETH TWAP",
        "protocol": "Uniswap",
        "oracle_type": "uniswap_twap",
        "twap_window_seconds": 1800,
        "deviation_threshold_pct": 1.0,
        "heartbeat_seconds": 3600,
        "num_price_sources": 1,
        "min_sources_required": 1,
        "liquidity_of_underlying_usd": 5_000_000,
        "market_cap_usd": 1_000_000_000,
        "has_circuit_breaker": False,
        "manipulation_incidents_count": 0,
        "audited": True,
        "last_update_seconds_ago": 300,
    }
    base.update(kw)
    return base


def _risky_oracle(**kw):
    """Oracle designed to score CRITICAL."""
    base = {
        "name": "Custom Risky Oracle",
        "protocol": "UnknownProtocol",
        "oracle_type": "custom",
        "twap_window_seconds": 0,
        "deviation_threshold_pct": 2.0,
        "heartbeat_seconds": 600,
        "num_price_sources": 1,
        "min_sources_required": 1,
        "liquidity_of_underlying_usd": 100_000,
        "market_cap_usd": 500_000,
        "has_circuit_breaker": False,
        "manipulation_incidents_count": 3,
        "audited": False,
        "last_update_seconds_ago": 7200,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_scorer(tmp_dir):
    log = os.path.join(tmp_dir, "oracle_manipulation_log.json")
    return DeFiOracleManipulationRiskScorer(log_path=log), log


# ===========================================================================
# Tests
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(110.0), 100.0)

    def test_risk_label_safe(self):
        self.assertEqual(_risk_label(0.0),  "SAFE")
        self.assertEqual(_risk_label(19.9), "SAFE")

    def test_risk_label_low_risk(self):
        self.assertEqual(_risk_label(20.0), "LOW_RISK")
        self.assertEqual(_risk_label(39.9), "LOW_RISK")

    def test_risk_label_moderate_risk(self):
        self.assertEqual(_risk_label(40.0), "MODERATE_RISK")
        self.assertEqual(_risk_label(59.9), "MODERATE_RISK")

    def test_risk_label_high_risk(self):
        self.assertEqual(_risk_label(60.0), "HIGH_RISK")
        self.assertEqual(_risk_label(79.9), "HIGH_RISK")

    def test_risk_label_critical(self):
        self.assertEqual(_risk_label(80.0), "CRITICAL")
        self.assertEqual(_risk_label(100.0), "CRITICAL")


class TestInit(unittest.TestCase):

    def test_init_default_log_path(self):
        s = DeFiOracleManipulationRiskScorer()
        self.assertIsNotNone(s.log_path)
        self.assertTrue(s.log_path.endswith("oracle_manipulation_log.json"))

    def test_init_custom_log_path(self):
        s = DeFiOracleManipulationRiskScorer(log_path="/tmp/custom.json")
        self.assertEqual(s.log_path, "/tmp/custom.json")


class TestScoreEmpty(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log = _make_scorer(self.tmp)

    def test_score_empty_list(self):
        out = self.scorer.score([], config={"log_path": self.log})
        self.assertIsInstance(out, dict)
        self.assertEqual(out["oracle_count"], 0)
        self.assertEqual(out["results"], [])

    def test_score_empty_aggregates_none(self):
        out = self.scorer.score([], config={"log_path": self.log})
        agg = out["aggregates"]
        self.assertIsNone(agg["highest_risk"])
        self.assertIsNone(agg["lowest_risk"])
        self.assertEqual(agg["average_risk_score"], 0.0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["safe_count"], 0)

    def test_score_returns_dict(self):
        out = self.scorer.score([], config={"log_path": self.log})
        self.assertIsInstance(out, dict)

    def test_score_timestamp_present(self):
        out = self.scorer.score([], config={"log_path": self.log})
        self.assertIn("timestamp", out)
        self.assertIsInstance(out["timestamp"], str)

    def test_oracle_count_matches_input(self):
        oracles = [_chainlink_oracle(), _twap_oracle()]
        out = self.scorer.score(oracles, config={"log_path": self.log})
        self.assertEqual(out["oracle_count"], 2)


class TestManipulationCost(unittest.TestCase):

    def setUp(self):
        self.s = DeFiOracleManipulationRiskScorer(log_path="/dev/null")

    def test_chainlink_cost_10pct_liquidity(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=10_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 1_000_000.0)

    def test_twap_300s_window_factor_1(self):
        o = _twap_oracle(twap_window_seconds=300, liquidity_of_underlying_usd=1_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 100_000.0)  # 1M * 0.10 * (300/300=1)

    def test_twap_1800s_window_factor_6(self):
        o = _twap_oracle(twap_window_seconds=1800, liquidity_of_underlying_usd=1_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 600_000.0)  # 1M * 0.10 * 6

    def test_twap_3600s_window_factor_12(self):
        o = _twap_oracle(twap_window_seconds=3600, liquidity_of_underlying_usd=1_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 1_200_000.0)  # 1M * 0.10 * 12

    def test_zero_liquidity(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=0)
        cost = self.s.compute_manipulation_cost(o)
        self.assertEqual(cost, 0.0)

    def test_large_liquidity(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=1_000_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 100_000_000.0)

    def test_band_oracle_no_twap_factor(self):
        o = _chainlink_oracle(oracle_type="band", liquidity_of_underlying_usd=1_000_000, twap_window_seconds=3600)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 100_000.0)

    def test_custom_type_no_twap_factor(self):
        o = _chainlink_oracle(oracle_type="custom", liquidity_of_underlying_usd=2_000_000, twap_window_seconds=7200)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 200_000.0)

    def test_twap_zero_window_no_factor(self):
        """TWAP type but zero window — no factor applied (window=0 excluded)."""
        o = _twap_oracle(twap_window_seconds=0, liquidity_of_underlying_usd=1_000_000)
        cost = self.s.compute_manipulation_cost(o)
        self.assertAlmostEqual(cost, 100_000.0)


class TestSourceDiversityScore(unittest.TestCase):

    def setUp(self):
        self.s = DeFiOracleManipulationRiskScorer(log_path="/dev/null")

    def test_single_source_score(self):
        o = _chainlink_oracle(num_price_sources=1, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 5.0)

    def test_two_sources_score(self):
        o = _chainlink_oracle(num_price_sources=2, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 35.0)

    def test_three_sources_score(self):
        o = _chainlink_oracle(num_price_sources=3, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 60.0)

    def test_five_sources_score(self):
        o = _chainlink_oracle(num_price_sources=5, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 80.0)

    def test_seven_sources_score(self):
        o = _chainlink_oracle(num_price_sources=7, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 95.0)

    def test_chainlink_bonus_applied(self):
        o = _chainlink_oracle(num_price_sources=3, oracle_type="chainlink")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 70.0)  # 60 + 10

    def test_pyth_bonus_applied(self):
        o = _chainlink_oracle(num_price_sources=3, oracle_type="pyth")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 70.0)

    def test_band_no_bonus(self):
        o = _chainlink_oracle(num_price_sources=3, oracle_type="band")
        score = self.s.compute_source_diversity_score(o)
        self.assertEqual(score, 60.0)

    def test_score_capped_at_100(self):
        o = _chainlink_oracle(num_price_sources=7, oracle_type="chainlink")
        score = self.s.compute_source_diversity_score(o)
        self.assertLessEqual(score, 100.0)

    def test_score_non_negative(self):
        o = _chainlink_oracle(num_price_sources=0, oracle_type="custom")
        score = self.s.compute_source_diversity_score(o)
        self.assertGreaterEqual(score, 0.0)


class TestFreshnessScore(unittest.TestCase):

    def setUp(self):
        self.s = DeFiOracleManipulationRiskScorer(log_path="/dev/null")

    def test_fresh_data_score_100(self):
        o = _chainlink_oracle(last_update_seconds_ago=100, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 100.0)

    def test_at_heartbeat_score_100(self):
        o = _chainlink_oracle(last_update_seconds_ago=3600, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 100.0)

    def test_1_25x_heartbeat_score_80(self):
        o = _chainlink_oracle(last_update_seconds_ago=4500, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 80.0)

    def test_2x_heartbeat_score_50(self):
        o = _chainlink_oracle(last_update_seconds_ago=7200, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 50.0)

    def test_very_stale_score_near_zero(self):
        o = _chainlink_oracle(last_update_seconds_ago=100_000, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 0.0)

    def test_stale_3x_heartbeat_score_decreasing(self):
        o = _chainlink_oracle(last_update_seconds_ago=10800, heartbeat_seconds=3600)
        score = self.s.compute_freshness_score(o)
        self.assertGreaterEqual(score, 0.0)
        self.assertLess(score, 50.0)

    def test_zero_heartbeat_defaults_to_3600(self):
        o = _chainlink_oracle(last_update_seconds_ago=3600, heartbeat_seconds=0)
        score = self.s.compute_freshness_score(o)
        self.assertEqual(score, 100.0)

    def test_freshness_score_range(self):
        for secs in [0, 1800, 3600, 7200, 14400, 100000]:
            o = _chainlink_oracle(last_update_seconds_ago=secs, heartbeat_seconds=3600)
            s = self.s.compute_freshness_score(o)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


class TestFlags(unittest.TestCase):

    def setUp(self):
        self.s = DeFiOracleManipulationRiskScorer(log_path="/dev/null")

    def test_single_source_flag(self):
        o = _chainlink_oracle(num_price_sources=1)
        flags = self.s.compute_flags(o)
        self.assertIn("SINGLE_SOURCE", flags)

    def test_no_single_source_flag_two_sources(self):
        o = _chainlink_oracle(num_price_sources=2)
        flags = self.s.compute_flags(o)
        self.assertNotIn("SINGLE_SOURCE", flags)

    def test_stale_data_flag(self):
        o = _chainlink_oracle(last_update_seconds_ago=8000, heartbeat_seconds=3600)
        flags = self.s.compute_flags(o)
        self.assertIn("STALE_DATA", flags)

    def test_no_stale_data_flag_fresh(self):
        o = _chainlink_oracle(last_update_seconds_ago=600, heartbeat_seconds=3600)
        flags = self.s.compute_flags(o)
        self.assertNotIn("STALE_DATA", flags)

    def test_short_twap_flag_uniswap(self):
        o = _twap_oracle(oracle_type="uniswap_twap", twap_window_seconds=600)
        flags = self.s.compute_flags(o)
        self.assertIn("SHORT_TWAP", flags)

    def test_no_short_twap_flag_long_window(self):
        o = _twap_oracle(oracle_type="uniswap_twap", twap_window_seconds=1800)
        flags = self.s.compute_flags(o)
        self.assertNotIn("SHORT_TWAP", flags)

    def test_no_short_twap_flag_chainlink_type(self):
        o = _chainlink_oracle(oracle_type="chainlink", twap_window_seconds=300)
        flags = self.s.compute_flags(o)
        self.assertNotIn("SHORT_TWAP", flags)

    def test_low_liquidity_flag(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=100_000)
        flags = self.s.compute_flags(o)
        self.assertIn("LOW_LIQUIDITY_RISK", flags)

    def test_no_low_liquidity_flag(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=1_000_000)
        flags = self.s.compute_flags(o)
        self.assertNotIn("LOW_LIQUIDITY_RISK", flags)

    def test_prior_manipulation_flag(self):
        o = _chainlink_oracle(manipulation_incidents_count=2)
        flags = self.s.compute_flags(o)
        self.assertIn("PRIOR_MANIPULATION", flags)

    def test_no_prior_manipulation_flag(self):
        o = _chainlink_oracle(manipulation_incidents_count=0)
        flags = self.s.compute_flags(o)
        self.assertNotIn("PRIOR_MANIPULATION", flags)

    def test_no_circuit_breaker_flag(self):
        o = _chainlink_oracle(has_circuit_breaker=False)
        flags = self.s.compute_flags(o)
        self.assertIn("NO_CIRCUIT_BREAKER", flags)

    def test_has_circuit_breaker_no_flag(self):
        o = _chainlink_oracle(has_circuit_breaker=True)
        flags = self.s.compute_flags(o)
        self.assertNotIn("NO_CIRCUIT_BREAKER", flags)

    def test_no_flags_perfect_oracle(self):
        o = _chainlink_oracle(
            num_price_sources=20,
            last_update_seconds_ago=100,
            heartbeat_seconds=3600,
            liquidity_of_underlying_usd=100_000_000,
            manipulation_incidents_count=0,
            has_circuit_breaker=True,
            oracle_type="chainlink",
            twap_window_seconds=0,
        )
        flags = self.s.compute_flags(o)
        self.assertEqual(flags, [])

    def test_all_flags_risky_oracle(self):
        o = _risky_oracle(oracle_type="uniswap_twap", twap_window_seconds=300, num_price_sources=1,
                          liquidity_of_underlying_usd=100_000, manipulation_incidents_count=2,
                          has_circuit_breaker=False, last_update_seconds_ago=5000, heartbeat_seconds=600)
        flags = self.s.compute_flags(o)
        self.assertIn("SINGLE_SOURCE",         flags)
        self.assertIn("STALE_DATA",            flags)
        self.assertIn("SHORT_TWAP",            flags)
        self.assertIn("LOW_LIQUIDITY_RISK",    flags)
        self.assertIn("PRIOR_MANIPULATION",    flags)
        self.assertIn("NO_CIRCUIT_BREAKER",    flags)


class TestCompositeRiskScore(unittest.TestCase):

    def setUp(self):
        self.s = DeFiOracleManipulationRiskScorer(log_path="/dev/null")

    def test_range_always_0_to_100(self):
        for o in [_chainlink_oracle(), _twap_oracle(), _risky_oracle()]:
            score = self.s.compute_composite_risk_score(
                self.s.compute_manipulation_cost(o),
                self.s.compute_source_diversity_score(o),
                self.s.compute_freshness_score(o),
                self.s.compute_flags(o),
                o,
            )
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_safe_oracle_low_score(self):
        o = _chainlink_oracle()
        score = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o),
            self.s.compute_source_diversity_score(o),
            self.s.compute_freshness_score(o),
            self.s.compute_flags(o),
            o,
        )
        self.assertLess(score, 50.0)

    def test_risky_oracle_high_score(self):
        o = _risky_oracle()
        score = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o),
            self.s.compute_source_diversity_score(o),
            self.s.compute_freshness_score(o),
            self.s.compute_flags(o),
            o,
        )
        self.assertGreater(score, 50.0)

    def test_incident_raises_score(self):
        o_no = _chainlink_oracle(manipulation_incidents_count=0)
        o_yes = _chainlink_oracle(manipulation_incidents_count=2)
        score_no  = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_no),
            self.s.compute_source_diversity_score(o_no),
            self.s.compute_freshness_score(o_no),
            self.s.compute_flags(o_no), o_no)
        score_yes = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_yes),
            self.s.compute_source_diversity_score(o_yes),
            self.s.compute_freshness_score(o_yes),
            self.s.compute_flags(o_yes), o_yes)
        self.assertGreater(score_yes, score_no)

    def test_no_circuit_breaker_raises_score(self):
        o_cb    = _chainlink_oracle(has_circuit_breaker=True)
        o_no_cb = _chainlink_oracle(has_circuit_breaker=False)
        score_cb    = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_cb),
            self.s.compute_source_diversity_score(o_cb),
            self.s.compute_freshness_score(o_cb),
            self.s.compute_flags(o_cb), o_cb)
        score_no_cb = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_no_cb),
            self.s.compute_source_diversity_score(o_no_cb),
            self.s.compute_freshness_score(o_no_cb),
            self.s.compute_flags(o_no_cb), o_no_cb)
        self.assertGreater(score_no_cb, score_cb)

    def test_not_audited_raises_score(self):
        o_aud  = _chainlink_oracle(audited=True,  has_circuit_breaker=True)
        o_naud = _chainlink_oracle(audited=False, has_circuit_breaker=True)
        s_aud  = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_aud),
            self.s.compute_source_diversity_score(o_aud),
            self.s.compute_freshness_score(o_aud),
            self.s.compute_flags(o_aud), o_aud)
        s_naud = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o_naud),
            self.s.compute_source_diversity_score(o_naud),
            self.s.compute_freshness_score(o_naud),
            self.s.compute_flags(o_naud), o_naud)
        self.assertGreater(s_naud, s_aud)

    def test_high_incident_penalty_capped(self):
        o = _chainlink_oracle(manipulation_incidents_count=100)
        score = self.s.compute_composite_risk_score(
            self.s.compute_manipulation_cost(o),
            self.s.compute_source_diversity_score(o),
            self.s.compute_freshness_score(o),
            self.s.compute_flags(o),
            o,
        )
        self.assertLessEqual(score, 100.0)


class TestScoreFullRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log = _make_scorer(self.tmp)

    def test_result_keys_present(self):
        out = self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        r = out["results"][0]
        for key in ("name", "protocol", "oracle_type",
                    "manipulation_cost_estimate_usd",
                    "source_diversity_score", "freshness_score",
                    "composite_risk_score", "risk_label", "flags"):
            self.assertIn(key, r)

    def test_output_keys_present(self):
        out = self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        for key in ("timestamp", "oracle_count", "results", "aggregates"):
            self.assertIn(key, out)

    def test_manipulation_cost_in_result(self):
        out = self.scorer.score([_chainlink_oracle(liquidity_of_underlying_usd=10_000_000)],
                                config={"log_path": self.log})
        r = out["results"][0]
        self.assertAlmostEqual(r["manipulation_cost_estimate_usd"], 1_000_000.0)

    def test_source_diversity_in_result(self):
        out = self.scorer.score([_chainlink_oracle(num_price_sources=5, oracle_type="custom")],
                                config={"log_path": self.log})
        self.assertEqual(out["results"][0]["source_diversity_score"], 80.0)

    def test_freshness_score_in_result(self):
        out = self.scorer.score([_chainlink_oracle(last_update_seconds_ago=100, heartbeat_seconds=3600)],
                                config={"log_path": self.log})
        self.assertEqual(out["results"][0]["freshness_score"], 100.0)

    def test_risk_label_safe(self):
        out = self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        self.assertIn(out["results"][0]["risk_label"], ("SAFE", "LOW_RISK", "MODERATE_RISK"))

    def test_risk_label_critical(self):
        out = self.scorer.score([_risky_oracle()], config={"log_path": self.log})
        self.assertIn(out["results"][0]["risk_label"], ("HIGH_RISK", "CRITICAL"))

    def test_multiple_oracles_count(self):
        oracles = [_chainlink_oracle(), _twap_oracle(), _risky_oracle()]
        out = self.scorer.score(oracles, config={"log_path": self.log})
        self.assertEqual(len(out["results"]), 3)

    def test_aggregates_highest_risk(self):
        out = self.scorer.score([_chainlink_oracle(name="A"), _risky_oracle(name="B")],
                                config={"log_path": self.log})
        self.assertEqual(out["aggregates"]["highest_risk"], "B")

    def test_aggregates_lowest_risk(self):
        out = self.scorer.score([_chainlink_oracle(name="A"), _risky_oracle(name="B")],
                                config={"log_path": self.log})
        self.assertEqual(out["aggregates"]["lowest_risk"], "A")

    def test_aggregates_average_risk_score(self):
        out = self.scorer.score([_chainlink_oracle(name="A"), _chainlink_oracle(name="B")],
                                config={"log_path": self.log})
        scores = [r["composite_risk_score"] for r in out["results"]]
        expected = round(sum(scores) / 2, 2)
        self.assertAlmostEqual(out["aggregates"]["average_risk_score"], expected)

    def test_aggregates_critical_count(self):
        out = self.scorer.score([_risky_oracle(name="R1"), _risky_oracle(name="R2"), _chainlink_oracle(name="C")],
                                config={"log_path": self.log})
        critical_labels = [r["risk_label"] for r in out["results"] if r["risk_label"] == "CRITICAL"]
        self.assertEqual(out["aggregates"]["critical_count"], len(critical_labels))

    def test_aggregates_safe_count(self):
        out = self.scorer.score([_chainlink_oracle(name="A"), _chainlink_oracle(name="B")],
                                config={"log_path": self.log})
        safe = [r for r in out["results"] if r["risk_label"] == "SAFE"]
        self.assertEqual(out["aggregates"]["safe_count"], len(safe))

    def test_none_config_defaults(self):
        log_path = os.path.join(self.tmp, "default.json")
        s = DeFiOracleManipulationRiskScorer(log_path=log_path)
        out = s.score([_chainlink_oracle()], config=None)
        self.assertIsInstance(out, dict)

    def test_empty_config_dict(self):
        log_path = os.path.join(self.tmp, "ec.json")
        s = DeFiOracleManipulationRiskScorer(log_path=log_path)
        out = s.score([_chainlink_oracle()], config={})
        self.assertIsInstance(out, dict)


class TestOracleTypes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log = _make_scorer(self.tmp)
        self.cfg = {"log_path": self.log}

    def _score_type(self, oracle_type, **kw):
        o = _chainlink_oracle(oracle_type=oracle_type, **kw)
        return self.scorer.score([o], config=self.cfg)["results"][0]

    def test_chainlink_type(self):
        r = self._score_type("chainlink")
        self.assertEqual(r["oracle_type"], "chainlink")

    def test_uniswap_twap_type(self):
        r = self._score_type("uniswap_twap", twap_window_seconds=1800)
        self.assertEqual(r["oracle_type"], "uniswap_twap")

    def test_band_type(self):
        r = self._score_type("band")
        self.assertEqual(r["oracle_type"], "band")

    def test_pyth_type(self):
        r = self._score_type("pyth")
        self.assertEqual(r["oracle_type"], "pyth")

    def test_api3_type(self):
        r = self._score_type("api3")
        self.assertEqual(r["oracle_type"], "api3")

    def test_custom_type(self):
        r = self._score_type("custom")
        self.assertEqual(r["oracle_type"], "custom")


class TestLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log = _make_scorer(self.tmp)

    def test_log_created(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_list(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_added(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_multiple_entries(self):
        for _ in range(3):
            self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_ring_buffer_exact_100(self):
        for _ in range(100):
            self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_atomic_write_no_tmp_left(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        self.assertFalse(os.path.exists(self.log + ".tmp"))

    def test_log_custom_path_via_config(self):
        custom = os.path.join(self.tmp, "custom_log.json")
        self.scorer.score([_chainlink_oracle()], config={"log_path": custom})
        self.assertTrue(os.path.exists(custom))

    def test_log_entry_has_timestamp(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_results(self):
        self.scorer.score([_chainlink_oracle()], config={"log_path": self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn("results", data[0])


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log = _make_scorer(self.tmp)
        self.cfg = {"log_path": self.log}

    def test_twap_900s_no_short_twap(self):
        o = _twap_oracle(oracle_type="uniswap_twap", twap_window_seconds=900)
        flags = self.scorer.compute_flags(o)
        self.assertNotIn("SHORT_TWAP", flags)

    def test_twap_899s_short_twap(self):
        o = _twap_oracle(oracle_type="uniswap_twap", twap_window_seconds=899)
        flags = self.scorer.compute_flags(o)
        self.assertIn("SHORT_TWAP", flags)

    def test_liquidity_exactly_500k_no_flag(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=500_000)
        flags = self.scorer.compute_flags(o)
        self.assertNotIn("LOW_LIQUIDITY_RISK", flags)

    def test_liquidity_499999_flag(self):
        o = _chainlink_oracle(liquidity_of_underlying_usd=499_999)
        flags = self.scorer.compute_flags(o)
        self.assertIn("LOW_LIQUIDITY_RISK", flags)

    def test_score_single_oracle_result_list_length_1(self):
        out = self.scorer.score([_chainlink_oracle()], config=self.cfg)
        self.assertEqual(len(out["results"]), 1)

    def test_composite_score_is_float(self):
        out = self.scorer.score([_chainlink_oracle()], config=self.cfg)
        self.assertIsInstance(out["results"][0]["composite_risk_score"], float)

    def test_flags_is_list(self):
        out = self.scorer.score([_chainlink_oracle()], config=self.cfg)
        self.assertIsInstance(out["results"][0]["flags"], list)


if __name__ == "__main__":
    unittest.main()
