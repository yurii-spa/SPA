"""
Tests for MP-984: DeFiYieldSourceDiversificationScorer
Run: python3 -m unittest spa_core.tests.test_defi_yield_source_diversification_scorer -v
"""

import json
import os
import sys
import unittest
import tempfile

# Ensure project root is in path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_yield_source_diversification_scorer import (
    DeFiYieldSourceDiversificationScorer,
    _hhi,
    _group_shares,
    _diversity_label,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    name="A",
    source="lending_interest",
    protocol="Aave",
    chain="Ethereum",
    yield_pct=5.0,
    capital=10_000.0,
    correlated=False,
):
    return {
        "asset_name": name,
        "yield_source_type": source,
        "protocol": protocol,
        "chain": chain,
        "yield_pct": yield_pct,
        "capital_usd": capital,
        "correlated_with_market": correlated,
    }


def _make_diverse_portfolio():
    return [
        _pos("A", "lending_interest",  "Aave",    "Ethereum", 3.5,  30_000, False),
        _pos("B", "trading_fees",      "Uniswap", "Ethereum", 8.0,  20_000, True),
        _pos("C", "staking_rewards",   "Lido",    "Ethereum", 4.0,  20_000, True),
        _pos("D", "liquidity_mining",  "Curve",   "Arbitrum", 12.0, 15_000, True),
        _pos("E", "real_yield",        "GMX",     "Arbitrum", 15.0, 15_000, False),
    ]


class TestHHI(unittest.TestCase):
    """Unit tests for _hhi helper."""

    def test_single_source_returns_one(self):
        self.assertAlmostEqual(_hhi([100.0]), 1.0)

    def test_two_equal_sources(self):
        self.assertAlmostEqual(_hhi([50.0, 50.0]), 0.5)

    def test_four_equal_sources(self):
        self.assertAlmostEqual(_hhi([25.0, 25.0, 25.0, 25.0]), 0.25)

    def test_ten_equal_sources(self):
        self.assertAlmostEqual(_hhi([10.0] * 10), 0.1)

    def test_empty_list_returns_one(self):
        self.assertEqual(_hhi([]), 1.0)

    def test_zero_shares_returns_one(self):
        self.assertEqual(_hhi([0.0, 0.0]), 1.0)

    def test_dominant_source(self):
        hhi = _hhi([90.0, 5.0, 5.0])
        # 0.81 + 0.0025 + 0.0025 = 0.815
        self.assertGreater(hhi, 0.8)

    def test_hhi_range_always_0_to_1(self):
        for shares in [[100], [50, 50], [33, 33, 34], [10]*10]:
            v = _hhi(shares)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


class TestGroupShares(unittest.TestCase):
    """Unit tests for _group_shares helper."""

    def test_groups_by_key(self):
        items = [
            {"protocol": "Aave", "capital_usd": 10_000},
            {"protocol": "Aave", "capital_usd": 5_000},
            {"protocol": "Compound", "capital_usd": 20_000},
        ]
        result = _group_shares(items, "protocol", "capital_usd")
        self.assertAlmostEqual(result["Aave"], 15_000)
        self.assertAlmostEqual(result["Compound"], 20_000)

    def test_missing_value_treated_as_zero(self):
        items = [{"protocol": "X"}]
        result = _group_shares(items, "protocol")
        self.assertEqual(result["X"], 0.0)

    def test_unknown_key_grouped_as_unknown(self):
        items = [{"capital_usd": 100}]
        result = _group_shares(items, "protocol")
        self.assertIn("unknown", result)


class TestDiversityLabel(unittest.TestCase):
    """Unit tests for _diversity_label helper."""

    def test_above_80_is_highly_diversified(self):
        self.assertEqual(_diversity_label(85.0), "HIGHLY_DIVERSIFIED")

    def test_exactly_80_is_highly_diversified(self):
        self.assertEqual(_diversity_label(80.0), "HIGHLY_DIVERSIFIED")

    def test_60_to_79_is_diversified(self):
        self.assertEqual(_diversity_label(70.0), "DIVERSIFIED")

    def test_40_to_59_is_moderate(self):
        self.assertEqual(_diversity_label(50.0), "MODERATE")

    def test_20_to_39_is_concentrated(self):
        self.assertEqual(_diversity_label(30.0), "CONCENTRATED")

    def test_below_20_is_single_source(self):
        self.assertEqual(_diversity_label(10.0), "SINGLE_SOURCE")

    def test_zero_is_single_source(self):
        self.assertEqual(_diversity_label(0.0), "SINGLE_SOURCE")


class TestScorerBasic(unittest.TestCase):
    """Basic scorer behaviour."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_empty_portfolio_returns_zero_score(self):
        r = self.scorer.score([], self.cfg)
        self.assertEqual(r["diversification_score"], 0.0)

    def test_empty_portfolio_has_error_key(self):
        r = self.scorer.score([], self.cfg)
        self.assertIn("error", r)

    def test_single_position_single_source_score(self):
        r = self.scorer.score([_pos()], self.cfg)
        self.assertGreaterEqual(r["diversification_score"], 0.0)

    def test_returns_dict(self):
        r = self.scorer.score([_pos()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_diverse_portfolio_higher_score_than_single(self):
        single = self.scorer.score([_pos()], self.cfg)
        diverse = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        self.assertGreater(
            diverse["diversification_score"],
            single["diversification_score"],
        )

    def test_score_in_0_100_range(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        self.assertGreaterEqual(r["diversification_score"], 0.0)
        self.assertLessEqual(r["diversification_score"], 100.0)


class TestScorerFields(unittest.TestCase):
    """Verify all required output fields are present."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}
        self.result = self.scorer.score(_make_diverse_portfolio(), self.cfg)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_has_position_count(self):
        self.assertEqual(self.result["position_count"], 5)

    def test_has_total_capital_usd(self):
        self.assertAlmostEqual(self.result["total_capital_usd"], 100_000.0)

    def test_has_weighted_avg_yield_pct(self):
        self.assertIn("weighted_avg_yield_pct", self.result)

    def test_has_bear_market_exposure_pct(self):
        self.assertIn("bear_market_exposure_pct", self.result)

    def test_has_source_hhi(self):
        self.assertIn("source_hhi", self.result)

    def test_has_protocol_hhi(self):
        self.assertIn("protocol_hhi", self.result)

    def test_has_chain_hhi(self):
        self.assertIn("chain_hhi", self.result)

    def test_has_source_diversity_score(self):
        self.assertIn("source_diversity_score", self.result)

    def test_has_protocol_diversity_score(self):
        self.assertIn("protocol_diversity_score", self.result)

    def test_has_chain_diversity_score(self):
        self.assertIn("chain_diversity_score", self.result)

    def test_has_diversification_score(self):
        self.assertIn("diversification_score", self.result)

    def test_has_diversity_label(self):
        self.assertIn("diversity_label", self.result)

    def test_has_flags(self):
        self.assertIn("flags", self.result)
        self.assertIsInstance(self.result["flags"], list)

    def test_has_per_type_allocation_pct(self):
        self.assertIn("per_type_allocation_pct", self.result)

    def test_has_per_type_yield_contribution_pct(self):
        self.assertIn("per_type_yield_contribution_pct", self.result)

    def test_has_protocol_allocation_pct(self):
        self.assertIn("protocol_allocation_pct", self.result)

    def test_has_chain_allocation_pct(self):
        self.assertIn("chain_allocation_pct", self.result)

    def test_has_dominant_source_type(self):
        self.assertIn("dominant_source_type", self.result)

    def test_has_dominant_protocol(self):
        self.assertIn("dominant_protocol", self.result)

    def test_has_dominant_chain(self):
        self.assertIn("dominant_chain", self.result)

    def test_has_total_portfolio_yield_pct(self):
        self.assertIn("total_portfolio_yield_pct", self.result)


class TestScorerAllocationMath(unittest.TestCase):
    """Verify allocation percentages sum to ~100."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_type_allocation_sums_to_100(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        total = sum(r["per_type_allocation_pct"].values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_protocol_allocation_sums_to_100(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        total = sum(r["protocol_allocation_pct"].values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_chain_allocation_sums_to_100(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        total = sum(r["chain_allocation_pct"].values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_yield_contribution_sums_to_100(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        total = sum(r["per_type_yield_contribution_pct"].values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_single_type_allocation_is_100(self):
        portfolio = [_pos(), _pos("B", capital=20_000.0)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(
            r["per_type_allocation_pct"]["lending_interest"], 100.0, places=2
        )


class TestScorerWeightedYield(unittest.TestCase):
    """Verify weighted average yield calculation."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_equal_capital_yields_avg(self):
        portfolio = [
            _pos("A", yield_pct=4.0, capital=10_000.0),
            _pos("B", yield_pct=6.0, capital=10_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["weighted_avg_yield_pct"], 5.0, places=4)

    def test_unequal_capital_weighted_correctly(self):
        portfolio = [
            _pos("A", yield_pct=10.0, capital=90_000.0),
            _pos("B", yield_pct=0.0,  capital=10_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        # 90k*10 + 10k*0 = 900k / 100k = 9.0
        self.assertAlmostEqual(r["weighted_avg_yield_pct"], 9.0, places=4)

    def test_zero_yield_all_positions(self):
        portfolio = [_pos(yield_pct=0.0), _pos("B", yield_pct=0.0)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["weighted_avg_yield_pct"], 0.0, places=4)


class TestScorerBearExposure(unittest.TestCase):
    """Bear-market exposure calculations."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_all_correlated_is_100pct(self):
        portfolio = [
            _pos(correlated=True, capital=50_000.0),
            _pos("B", correlated=True, capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["bear_market_exposure_pct"], 100.0, places=2)

    def test_none_correlated_is_0pct(self):
        portfolio = [
            _pos(correlated=False, capital=50_000.0),
            _pos("B", correlated=False, capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["bear_market_exposure_pct"], 0.0, places=2)

    def test_half_correlated_is_50pct(self):
        portfolio = [
            _pos("A", correlated=True,  capital=50_000.0),
            _pos("B", correlated=False, capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["bear_market_exposure_pct"], 50.0, places=2)


class TestScorerFlags(unittest.TestCase):
    """Flag detection tests."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_single_chain_flag(self):
        portfolio = [
            _pos("A", chain="Ethereum"),
            _pos("B", chain="Ethereum"),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("SINGLE_CHAIN", r["flags"])

    def test_no_single_chain_flag_two_chains(self):
        portfolio = [
            _pos("A", chain="Ethereum"),
            _pos("B", chain="Arbitrum"),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertNotIn("SINGLE_CHAIN", r["flags"])

    def test_protocol_concentrated_flag(self):
        portfolio = [
            _pos("A", protocol="Aave", capital=80_000.0),
            _pos("B", protocol="Compound", capital=20_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("PROTOCOL_CONCENTRATED", r["flags"])

    def test_no_protocol_concentrated_flag(self):
        # Exactly 50% each → not *greater than* 50 → no flag
        portfolio = [
            _pos("A", protocol="Aave",     capital=50_000.0),
            _pos("B", protocol="Compound", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertNotIn("PROTOCOL_CONCENTRATED", r["flags"])

    def test_real_yield_heavy_flag(self):
        portfolio = [
            _pos("A", source="real_yield", capital=50_000.0),
            _pos("B", source="lending_interest", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("REAL_YIELD_HEAVY", r["flags"])

    def test_no_real_yield_heavy_flag_below_threshold(self):
        portfolio = [
            _pos("A", source="real_yield",       capital=10_000.0),
            _pos("B", source="lending_interest", capital=90_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertNotIn("REAL_YIELD_HEAVY", r["flags"])

    def test_points_heavy_flag(self):
        portfolio = [
            _pos("A", source="points",           capital=50_000.0),
            _pos("B", source="lending_interest", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("POINTS_HEAVY", r["flags"])

    def test_no_points_heavy_flag_below_threshold(self):
        portfolio = [
            _pos("A", source="points",           capital=10_000.0),
            _pos("B", source="lending_interest", capital=90_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertNotIn("POINTS_HEAVY", r["flags"])

    def test_bear_market_exposed_flag(self):
        portfolio = [
            _pos("A", correlated=True,  capital=70_000.0),
            _pos("B", correlated=False, capital=30_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("BEAR_MARKET_EXPOSED", r["flags"])

    def test_no_bear_market_exposed_flag(self):
        portfolio = [
            _pos("A", correlated=True,  capital=30_000.0),
            _pos("B", correlated=False, capital=70_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertNotIn("BEAR_MARKET_EXPOSED", r["flags"])

    def test_multiple_flags_simultaneously(self):
        portfolio = [
            _pos("A", source="points", chain="Ethereum", protocol="X",
                 correlated=True, capital=70_000.0),
            _pos("B", source="points", chain="Ethereum", protocol="X",
                 correlated=True, capital=30_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        # SINGLE_CHAIN, PROTOCOL_CONCENTRATED, POINTS_HEAVY, BEAR_MARKET_EXPOSED
        self.assertIn("SINGLE_CHAIN", r["flags"])
        self.assertIn("PROTOCOL_CONCENTRATED", r["flags"])
        self.assertIn("POINTS_HEAVY", r["flags"])
        self.assertIn("BEAR_MARKET_EXPOSED", r["flags"])

    def test_custom_threshold_points_heavy(self):
        portfolio = [
            _pos("A", source="points",           capital=35_000.0),
            _pos("B", source="lending_interest", capital=65_000.0),
        ]
        # default threshold is 30; 35% > 30 → flag
        r = self.scorer.score(portfolio, {**self.cfg})
        self.assertIn("POINTS_HEAVY", r["flags"])

    def test_custom_threshold_points_heavy_raised(self):
        portfolio = [
            _pos("A", source="points",           capital=35_000.0),
            _pos("B", source="lending_interest", capital=65_000.0),
        ]
        # raise threshold to 40 → no flag
        r = self.scorer.score(portfolio, {**self.cfg, "points_heavy_threshold": 40.0})
        self.assertNotIn("POINTS_HEAVY", r["flags"])


class TestScorerDominants(unittest.TestCase):
    """Dominant type / protocol / chain detection."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_dominant_source_type(self):
        portfolio = [
            _pos("A", source="lending_interest", capital=60_000.0),
            _pos("B", source="trading_fees",     capital=40_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["dominant_source_type"], "lending_interest")

    def test_dominant_protocol(self):
        portfolio = [
            _pos("A", protocol="Aave",     capital=70_000.0),
            _pos("B", protocol="Compound", capital=30_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["dominant_protocol"], "Aave")

    def test_dominant_chain(self):
        portfolio = [
            _pos("A", chain="Ethereum", capital=80_000.0),
            _pos("B", chain="Arbitrum", capital=20_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["dominant_chain"], "Ethereum")


class TestScorerDiversityLabel(unittest.TestCase):
    """Label logic based on score."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_single_source_yields_single_source_label(self):
        r = self.scorer.score([_pos()], self.cfg)
        self.assertEqual(r["diversity_label"], "SINGLE_SOURCE")

    def test_highly_diversified_label_for_diverse_portfolio(self):
        # 5 unique sources, 5 unique protocols, 2 chains
        portfolio = [
            _pos("A", "lending_interest", "Aave",     "Ethereum", capital=20_000.0),
            _pos("B", "trading_fees",     "Uniswap",  "Ethereum", capital=20_000.0),
            _pos("C", "staking_rewards",  "Lido",     "Ethereum", capital=20_000.0),
            _pos("D", "liquidity_mining", "Curve",    "Arbitrum", capital=20_000.0),
            _pos("E", "real_yield",       "GMX",      "Arbitrum", capital=20_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn(
            r["diversity_label"],
            ["HIGHLY_DIVERSIFIED", "DIVERSIFIED", "MODERATE"],
        )


class TestScorerZeroCapital(unittest.TestCase):
    """Edge case: all positions have zero capital."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_zero_capital_returns_error(self):
        portfolio = [_pos(capital=0.0), _pos("B", capital=0.0)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("error", r)

    def test_zero_capital_score_is_zero(self):
        portfolio = [_pos(capital=0.0)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["diversification_score"], 0.0)


class TestScorerSingleProtocol(unittest.TestCase):
    """Single protocol, multiple source types."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_multiple_sources_one_protocol(self):
        portfolio = [
            _pos("A", "lending_interest", "Aave", capital=50_000.0),
            _pos("B", "staking_rewards",  "Aave", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["protocol_hhi"], 1.0)
        self.assertAlmostEqual(r["protocol_diversity_score"], 0.0)

    def test_single_protocol_forces_protocol_concentrated(self):
        portfolio = [
            _pos("A", "lending_interest", "Aave", capital=50_000.0),
            _pos("B", "staking_rewards",  "Aave", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertIn("PROTOCOL_CONCENTRATED", r["flags"])


class TestScorerHHIBounds(unittest.TestCase):
    """HHI values are always in [0, 1]."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_source_hhi_bounds(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        self.assertGreaterEqual(r["source_hhi"], 0.0)
        self.assertLessEqual(r["source_hhi"], 1.0)

    def test_protocol_hhi_bounds(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        self.assertGreaterEqual(r["protocol_hhi"], 0.0)
        self.assertLessEqual(r["protocol_hhi"], 1.0)

    def test_chain_hhi_bounds(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        self.assertGreaterEqual(r["chain_hhi"], 0.0)
        self.assertLessEqual(r["chain_hhi"], 1.0)


class TestScorerLogging(unittest.TestCase):
    """Ring-buffer log tests."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "yield_div.json")
            self.scorer.score([_pos()], {"log_path": log_path})
            self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "yield_div.json")
            self.scorer.score([_pos()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "yield_div.json")
            for _ in range(3):
                self.scorer.score([_pos()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "yield_div.json")
            for _ in range(LOG_CAP + 10):
                self.scorer.score([_pos()], {"log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), LOG_CAP)

    def test_disable_log_skips_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "yield_div.json")
            self.scorer.score([_pos()], {"disable_log": True, "log_path": log_path})
            self.assertFalse(os.path.exists(log_path))


class TestScorerEdgeCases(unittest.TestCase):
    """Miscellaneous edge cases."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_missing_fields_default_gracefully(self):
        # Position with no fields at all
        r = self.scorer.score([{}], self.cfg)
        self.assertIn("diversification_score", r)

    def test_very_large_capital(self):
        r = self.scorer.score(
            [_pos(capital=1e12), _pos("B", capital=1e12)], self.cfg
        )
        self.assertGreaterEqual(r["diversification_score"], 0.0)

    def test_negative_yield_handled(self):
        r = self.scorer.score([_pos(yield_pct=-2.0)], self.cfg)
        self.assertIn("weighted_avg_yield_pct", r)

    def test_100_positions(self):
        portfolio = [_pos(str(i), protocol=f"P{i}", chain=f"C{i%5}") for i in range(100)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["position_count"], 100)

    def test_all_source_types_present(self):
        sources = [
            "trading_fees", "lending_interest", "staking_rewards",
            "liquidity_mining", "real_yield", "points", "basis_trade",
        ]
        portfolio = [_pos(f"P{i}", s, capital=10_000.0) for i, s in enumerate(sources)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(len(r["per_type_allocation_pct"]), 7)

    def test_score_deterministic(self):
        portfolio = _make_diverse_portfolio()
        r1 = self.scorer.score(portfolio, self.cfg)
        r2 = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(
            r1["diversification_score"],
            r2["diversification_score"],
            places=6,
        )

    def test_config_none_defaults_correctly(self):
        # Should not raise
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "log.json")
            self.scorer.score([_pos()], {"log_path": log_path})

    def test_correlated_flag_false_by_default(self):
        portfolio = [{"asset_name": "X", "capital_usd": 10_000.0}]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertAlmostEqual(r["bear_market_exposure_pct"], 0.0, places=2)

    def test_score_increases_with_more_sources(self):
        one = self.scorer.score([_pos()], self.cfg)
        two = self.scorer.score(
            [_pos(), _pos("B", source="trading_fees", protocol="Uni")], self.cfg
        )
        self.assertGreaterEqual(
            two["diversification_score"],
            one["diversification_score"],
        )

    def test_position_count_matches_input(self):
        portfolio = [_pos(str(i)) for i in range(7)]
        r = self.scorer.score(portfolio, self.cfg)
        self.assertEqual(r["position_count"], 7)


class TestScorerScoreWeights(unittest.TestCase):
    """Verify score weighting (40% source + 35% protocol + 25% chain)."""

    def setUp(self):
        self.scorer = DeFiYieldSourceDiversificationScorer()
        self.cfg = {"disable_log": True}

    def test_weight_components_reconstruct_score(self):
        r = self.scorer.score(_make_diverse_portfolio(), self.cfg)
        expected = (
            0.40 * r["source_diversity_score"]
            + 0.35 * r["protocol_diversity_score"]
            + 0.25 * r["chain_diversity_score"]
        )
        self.assertAlmostEqual(r["diversification_score"], expected, places=3)

    def test_equal_split_seven_sources_high_source_score(self):
        sources = [
            "trading_fees", "lending_interest", "staking_rewards",
            "liquidity_mining", "real_yield", "points", "basis_trade",
        ]
        portfolio = [
            _pos(f"P{i}", s, protocol=f"Proto{i}", chain="Ethereum", capital=10_000.0)
            for i, s in enumerate(sources)
        ]
        r = self.scorer.score(portfolio, self.cfg)
        # 7 equal sources → HHI = 1/7 → source_score = (1 - 1/7)*100 ≈ 85.7
        self.assertGreater(r["source_diversity_score"], 80.0)

    def test_chain_diversity_contributes(self):
        # Same source + protocol but different chains
        portfolio = [
            _pos("A", chain="Ethereum", capital=50_000.0),
            _pos("B", chain="Arbitrum", capital=50_000.0),
        ]
        r = self.scorer.score(portfolio, self.cfg)
        # 2 equal chains → HHI = 0.5 → chain_score = 50
        self.assertAlmostEqual(r["chain_hhi"], 0.5, places=4)
        self.assertAlmostEqual(r["chain_diversity_score"], 50.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
