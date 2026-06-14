"""
Tests for MP-1012 DeFiProtocolCrossAssetCorrelationRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_cross_asset_correlation_risk_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_cross_asset_correlation_risk_analyzer import (
    DeFiProtocolCrossAssetCorrelationRiskAnalyzer,
    _compute_portfolio_volatility,
    _compute_weighted_vol_sum,
    _compute_effective_diversification_ratio,
    _compute_herfindahl_concentration,
    _compute_exposure_hhi,
    _compute_correlation_risk_score,
    _risk_label,
    _compute_flags,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_position(asset="USDC", weight=25.0, vol=2.0, corr_row=None):
    if corr_row is None:
        corr_row = {}
    return {
        "asset": asset,
        "weight_pct": weight,
        "volatility_30d_pct": vol,
        "correlation_matrix_row": corr_row,
    }


def _make_portfolio(name="TestPortfolio", positions=None,
                    protocol_exposure=None, chain_exposure=None,
                    stablecoin_pct=10.0, eth_correlated_pct=40.0):
    if positions is None:
        positions = [
            _make_position("USDC", 50.0, 0.1, {"WETH": 0.1, "WBTC": 0.05}),
            _make_position("WETH", 30.0, 8.0, {"USDC": 0.1, "WBTC": 0.7}),
            _make_position("WBTC", 20.0, 7.0, {"USDC": 0.05, "WETH": 0.7}),
        ]
    if protocol_exposure is None:
        protocol_exposure = {"Aave": 50.0, "Compound": 30.0, "Morpho": 20.0}
    if chain_exposure is None:
        chain_exposure = {"Ethereum": 70.0, "Arbitrum": 30.0}
    return {
        "name": name,
        "positions": positions,
        "protocol_exposure": protocol_exposure,
        "chain_exposure": chain_exposure,
        "stablecoin_pct": stablecoin_pct,
        "eth_correlated_pct": eth_correlated_pct,
    }


def _well_diversified_portfolio():
    """Portfolio expected to be WELL_DIVERSIFIED."""
    positions = [
        _make_position("A", 25.0, 2.0, {"B": 0.0, "C": 0.0, "D": 0.0}),
        _make_position("B", 25.0, 2.0, {"A": 0.0, "C": 0.0, "D": 0.0}),
        _make_position("C", 25.0, 2.0, {"A": 0.0, "B": 0.0, "D": 0.0}),
        _make_position("D", 25.0, 2.0, {"A": 0.0, "B": 0.0, "C": 0.0}),
    ]
    return _make_portfolio(
        name="WellDiversified",
        positions=positions,
        chain_exposure={"Ethereum": 40.0, "Arbitrum": 30.0, "Polygon": 30.0},
        protocol_exposure={"Aave": 25.0, "Compound": 25.0, "Morpho": 25.0, "Euler": 25.0},
        stablecoin_pct=25.0,
        eth_correlated_pct=20.0,
    )


def _dangerous_portfolio():
    """Portfolio with single position >50% → DANGEROUS_CONCENTRATION."""
    positions = [
        _make_position("WETH", 75.0, 10.0, {"WBTC": 0.9}),
        _make_position("WBTC", 25.0, 9.0, {"WETH": 0.9}),
    ]
    return _make_portfolio(
        name="DangerousPortfolio",
        positions=positions,
        protocol_exposure={"Aave": 90.0, "Morpho": 10.0},
        chain_exposure={"Ethereum": 100.0},
        stablecoin_pct=0.0,
        eth_correlated_pct=90.0,
    )


# ---------------------------------------------------------------------------
# 1. Test _compute_portfolio_volatility
# ---------------------------------------------------------------------------

class TestComputePortfolioVolatility(unittest.TestCase):

    def test_single_position(self):
        """Single-asset portfolio: port_vol = weight * vol."""
        pos = [_make_position("A", 100.0, 5.0)]
        result = _compute_portfolio_volatility(pos)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_two_uncorrelated(self):
        """Two equal-weight uncorrelated assets."""
        pos = [
            _make_position("A", 50.0, 4.0, {"B": 0.0}),
            _make_position("B", 50.0, 4.0, {"A": 0.0}),
        ]
        # variance = 0.5^2 * (4/100)^2 + 0.5^2 * (4/100)^2 = 2*(0.0008) = 0.0008
        result = _compute_portfolio_volatility(pos)
        expected = math.sqrt(2 * (0.5 * 0.04) ** 2) * 100
        self.assertAlmostEqual(result, expected, places=4)

    def test_two_perfectly_correlated(self):
        """Two equal-weight perfectly correlated assets → vol = weighted avg."""
        pos = [
            _make_position("A", 50.0, 4.0, {"B": 1.0}),
            _make_position("B", 50.0, 4.0, {"A": 1.0}),
        ]
        result = _compute_portfolio_volatility(pos)
        self.assertAlmostEqual(result, 4.0, places=4)

    def test_non_negative_result(self):
        """Volatility is always non-negative."""
        pos = [_make_position("A", 60.0, 5.0, {"B": -0.5}),
               _make_position("B", 40.0, 5.0, {"A": -0.5})]
        result = _compute_portfolio_volatility(pos)
        self.assertGreaterEqual(result, 0.0)

    def test_missing_corr_defaults_to_zero(self):
        """Missing correlation entry defaults to 0."""
        pos = [
            _make_position("A", 50.0, 4.0, {}),  # no entry for B
            _make_position("B", 50.0, 4.0, {}),  # no entry for A
        ]
        result = _compute_portfolio_volatility(pos)
        self.assertGreater(result, 0.0)

    def test_returns_float(self):
        pos = [_make_position("X", 100.0, 3.0)]
        self.assertIsInstance(_compute_portfolio_volatility(pos), float)


# ---------------------------------------------------------------------------
# 2. Test _compute_weighted_vol_sum
# ---------------------------------------------------------------------------

class TestComputeWeightedVolSum(unittest.TestCase):

    def test_single_full_weight(self):
        pos = [_make_position("A", 100.0, 5.0)]
        self.assertAlmostEqual(_compute_weighted_vol_sum(pos), 5.0, places=6)

    def test_two_positions(self):
        pos = [
            _make_position("A", 60.0, 10.0),
            _make_position("B", 40.0, 5.0),
        ]
        # 0.6*10 + 0.4*5 = 6 + 2 = 8
        self.assertAlmostEqual(_compute_weighted_vol_sum(pos), 8.0, places=6)

    def test_zero_volatility(self):
        pos = [_make_position("A", 100.0, 0.0)]
        self.assertAlmostEqual(_compute_weighted_vol_sum(pos), 0.0, places=6)

    def test_equal_weights(self):
        pos = [_make_position("A", 25.0, 4.0)] * 4
        self.assertAlmostEqual(_compute_weighted_vol_sum(pos), 4.0, places=6)


# ---------------------------------------------------------------------------
# 3. Test _compute_effective_diversification_ratio
# ---------------------------------------------------------------------------

class TestEffectiveDiversificationRatio(unittest.TestCase):

    def test_uncorrelated_ratio_gt_1(self):
        pos = [
            _make_position("A", 50.0, 4.0, {"B": 0.0}),
            _make_position("B", 50.0, 4.0, {"A": 0.0}),
        ]
        ratio = _compute_effective_diversification_ratio(pos)
        self.assertGreater(ratio, 1.0)

    def test_perfectly_correlated_ratio_approx_1(self):
        pos = [
            _make_position("A", 50.0, 4.0, {"B": 1.0}),
            _make_position("B", 50.0, 4.0, {"A": 1.0}),
        ]
        ratio = _compute_effective_diversification_ratio(pos)
        self.assertAlmostEqual(ratio, 1.0, places=4)

    def test_single_position(self):
        pos = [_make_position("A", 100.0, 5.0)]
        ratio = _compute_effective_diversification_ratio(pos)
        self.assertAlmostEqual(ratio, 1.0, places=4)

    def test_returns_float(self):
        pos = [_make_position("A", 50.0, 2.0, {"B": 0.3}),
               _make_position("B", 50.0, 2.0, {"A": 0.3})]
        self.assertIsInstance(_compute_effective_diversification_ratio(pos), float)

    def test_negative_correlation_increases_ratio(self):
        pos_neg = [
            _make_position("A", 50.0, 4.0, {"B": -0.5}),
            _make_position("B", 50.0, 4.0, {"A": -0.5}),
        ]
        pos_pos = [
            _make_position("A", 50.0, 4.0, {"B": 0.5}),
            _make_position("B", 50.0, 4.0, {"A": 0.5}),
        ]
        r_neg = _compute_effective_diversification_ratio(pos_neg)
        r_pos = _compute_effective_diversification_ratio(pos_pos)
        self.assertGreater(r_neg, r_pos)


# ---------------------------------------------------------------------------
# 4. Test _compute_herfindahl_concentration
# ---------------------------------------------------------------------------

class TestHerfindahlConcentration(unittest.TestCase):

    def test_equal_four_positions(self):
        pos = [_make_position(weight=25.0)] * 4
        # HHI = 4*(25^2)/100 = 4*6.25 = 25
        self.assertAlmostEqual(_compute_herfindahl_concentration(pos), 25.0, places=4)

    def test_single_position(self):
        pos = [_make_position(weight=100.0)]
        # HHI = 100^2/100 = 100
        self.assertAlmostEqual(_compute_herfindahl_concentration(pos), 100.0, places=4)

    def test_two_positions_70_30(self):
        pos = [_make_position(weight=70.0), _make_position(weight=30.0)]
        # (70^2 + 30^2)/100 = (4900+900)/100 = 58
        self.assertAlmostEqual(_compute_herfindahl_concentration(pos), 58.0, places=4)

    def test_highly_concentrated_single_75pct(self):
        pos = [_make_position(weight=75.0), _make_position(weight=25.0)]
        hhi = _compute_herfindahl_concentration(pos)
        self.assertGreater(hhi, 50.0)

    def test_returns_float(self):
        pos = [_make_position(weight=50.0), _make_position(weight=50.0)]
        self.assertIsInstance(_compute_herfindahl_concentration(pos), float)


# ---------------------------------------------------------------------------
# 5. Test _compute_exposure_hhi
# ---------------------------------------------------------------------------

class TestExposureHHI(unittest.TestCase):

    def test_single_chain(self):
        exposure = {"Ethereum": 100.0}
        # (100/100 * 100)^2 / 100 = 100
        self.assertAlmostEqual(_compute_exposure_hhi(exposure), 100.0, places=2)

    def test_two_equal_chains(self):
        exposure = {"Ethereum": 50.0, "Arbitrum": 50.0}
        # each 50/100*100=50; HHI = (50^2+50^2)/100 = 50
        self.assertAlmostEqual(_compute_exposure_hhi(exposure), 50.0, places=2)

    def test_empty_exposure(self):
        self.assertEqual(_compute_exposure_hhi({}), 0.0)

    def test_three_chains(self):
        exposure = {"Ethereum": 60.0, "Arbitrum": 30.0, "Polygon": 10.0}
        result = _compute_exposure_hhi(exposure)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 100.0)

    def test_zero_total_returns_zero(self):
        exposure = {"Ethereum": 0.0}
        self.assertEqual(_compute_exposure_hhi(exposure), 0.0)


# ---------------------------------------------------------------------------
# 6. Test _compute_correlation_risk_score
# ---------------------------------------------------------------------------

class TestCorrelationRiskScore(unittest.TestCase):

    def test_low_eth_high_diversification(self):
        score = _compute_correlation_risk_score(10.0, 2.5)
        self.assertLess(score, 30.0)

    def test_high_eth_low_diversification(self):
        score = _compute_correlation_risk_score(90.0, 1.0)
        self.assertGreater(score, 70.0)

    def test_max_eth_min_div(self):
        score = _compute_correlation_risk_score(100.0, 1.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreater(score, 60.0)

    def test_zero_eth(self):
        score = _compute_correlation_risk_score(0.0, 2.0)
        self.assertGreaterEqual(score, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_correlation_risk_score(50.0, 1.5), float)

    def test_score_range(self):
        for eth in [0, 30, 60, 90, 100]:
            for div in [1.0, 1.5, 2.0, 2.5]:
                score = _compute_correlation_risk_score(eth, div)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_higher_eth_means_higher_score(self):
        s1 = _compute_correlation_risk_score(30.0, 1.5)
        s2 = _compute_correlation_risk_score(80.0, 1.5)
        self.assertGreater(s2, s1)


# ---------------------------------------------------------------------------
# 7. Test _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def _positions_with_max_weight(self, max_w):
        rest = 100.0 - max_w
        return [
            _make_position("A", max_w),
            _make_position("B", rest * 0.5),
            _make_position("C", rest * 0.5),
        ]

    def test_dangerous_single_position_gt_50(self):
        positions = self._positions_with_max_weight(60.0)
        label = _risk_label(positions, 1000, 1000, 1.5, 50.0)
        self.assertEqual(label, "DANGEROUS_CONCENTRATION")

    def test_dangerous_corr_risk_gt_80(self):
        positions = self._positions_with_max_weight(30.0)
        label = _risk_label(positions, 1000, 1000, 1.2, 85.0)
        self.assertEqual(label, "DANGEROUS_CONCENTRATION")

    def test_highly_concentrated_hhi(self):
        positions = self._positions_with_max_weight(40.0)
        label = _risk_label(positions, 3500, 2000, 1.3, 50.0)
        self.assertEqual(label, "HIGHLY_CONCENTRATED")

    def test_highly_concentrated_chain(self):
        positions = self._positions_with_max_weight(40.0)
        label = _risk_label(positions, 2000, 5500, 1.3, 50.0)
        self.assertEqual(label, "HIGHLY_CONCENTRATED")

    def test_well_diversified(self):
        positions = self._positions_with_max_weight(20.0)
        label = _risk_label(positions, 500, 500, 2.0, 25.0)
        self.assertEqual(label, "WELL_DIVERSIFIED")

    def test_adequately_diversified(self):
        positions = self._positions_with_max_weight(30.0)
        label = _risk_label(positions, 1000, 1000, 1.6, 35.0)
        self.assertEqual(label, "ADEQUATELY_DIVERSIFIED")

    def test_moderately_concentrated(self):
        positions = self._positions_with_max_weight(35.0)
        label = _risk_label(positions, 2000, 2000, 1.2, 55.0)
        self.assertEqual(label, "MODERATELY_CONCENTRATED")


# ---------------------------------------------------------------------------
# 8. Test _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def _base_positions(self):
        return [_make_position("A", 30.0), _make_position("B", 70.0)]

    def test_eth_correlated_dominance(self):
        flags = _compute_flags(
            self._base_positions(), 1.5, 80.0,
            {"Ethereum": 50.0}, {"Aave": 30.0}, 10.0
        )
        self.assertIn("ETH_CORRELATED_DOMINANCE", flags)

    def test_no_eth_correlated_dominance(self):
        flags = _compute_flags(
            self._base_positions(), 1.5, 40.0,
            {"Ethereum": 50.0}, {"Aave": 30.0}, 10.0
        )
        self.assertNotIn("ETH_CORRELATED_DOMINANCE", flags)

    def test_single_chain_risk(self):
        flags = _compute_flags(
            self._base_positions(), 1.5, 40.0,
            {"Ethereum": 80.0}, {"Aave": 30.0}, 10.0
        )
        self.assertIn("SINGLE_CHAIN_RISK", flags)

    def test_protocol_concentration(self):
        flags = _compute_flags(
            self._base_positions(), 1.5, 40.0,
            {"Ethereum": 50.0}, {"Aave": 50.0}, 10.0
        )
        self.assertIn("PROTOCOL_CONCENTRATION", flags)

    def test_stablecoin_buffer(self):
        flags = _compute_flags(
            self._base_positions(), 1.5, 40.0,
            {"Ethereum": 50.0}, {"Aave": 30.0}, 30.0
        )
        self.assertIn("STABLECOIN_BUFFER", flags)

    def test_effective_diversification(self):
        flags = _compute_flags(
            self._base_positions(), 2.0, 40.0,
            {"Ethereum": 50.0}, {"Aave": 30.0}, 10.0
        )
        self.assertIn("EFFECTIVE_DIVERSIFICATION", flags)

    def test_extreme_concentration(self):
        pos = [_make_position("A", 60.0), _make_position("B", 40.0)]
        flags = _compute_flags(
            pos, 1.5, 40.0,
            {"Ethereum": 50.0}, {"Aave": 30.0}, 10.0
        )
        self.assertIn("EXTREME_CONCENTRATION", flags)

    def test_no_flags_baseline(self):
        pos = [_make_position("A", 25.0)] * 4
        flags = _compute_flags(
            pos, 2.0, 20.0,
            {"Ethereum": 50.0, "Arbitrum": 50.0},
            {"Aave": 25.0, "Compound": 25.0, "Morpho": 25.0, "Euler": 25.0},
            10.0
        )
        self.assertNotIn("ETH_CORRELATED_DOMINANCE", flags)
        self.assertNotIn("SINGLE_CHAIN_RISK", flags)
        self.assertNotIn("PROTOCOL_CONCENTRATION", flags)


# ---------------------------------------------------------------------------
# 9. Test _analyze_one
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):

    def test_returns_expected_keys(self):
        portfolio = _make_portfolio()
        result = _analyze_one(portfolio)
        for key in ["name", "portfolio_volatility_pct", "effective_diversification_ratio",
                    "herfindahl_concentration", "chain_concentration_score",
                    "protocol_concentration_score", "correlation_risk_score",
                    "risk_label", "flags", "position_count", "stablecoin_pct",
                    "eth_correlated_pct"]:
            self.assertIn(key, result)

    def test_position_count(self):
        portfolio = _make_portfolio()
        result = _analyze_one(portfolio)
        self.assertEqual(result["position_count"], len(portfolio["positions"]))

    def test_stablecoin_pct_preserved(self):
        portfolio = _make_portfolio(stablecoin_pct=15.0)
        result = _analyze_one(portfolio)
        self.assertAlmostEqual(result["stablecoin_pct"], 15.0)

    def test_well_diversified_portfolio(self):
        portfolio = _well_diversified_portfolio()
        result = _analyze_one(portfolio)
        self.assertEqual(result["risk_label"], "WELL_DIVERSIFIED")

    def test_dangerous_portfolio(self):
        portfolio = _dangerous_portfolio()
        result = _analyze_one(portfolio)
        self.assertEqual(result["risk_label"], "DANGEROUS_CONCENTRATION")

    def test_eth_correlated_preserved(self):
        portfolio = _make_portfolio(eth_correlated_pct=55.0)
        result = _analyze_one(portfolio)
        self.assertAlmostEqual(result["eth_correlated_pct"], 55.0)


# ---------------------------------------------------------------------------
# 10. Test DeFiProtocolCrossAssetCorrelationRiskAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolCrossAssetCorrelationRiskAnalyzer()

    def test_single_portfolio(self):
        result = self.analyzer.analyze([_make_portfolio()])
        self.assertIn("portfolios", result)
        self.assertEqual(len(result["portfolios"]), 1)

    def test_multiple_portfolios(self):
        portfolios = [
            _make_portfolio("P1"),
            _make_portfolio("P2"),
            _well_diversified_portfolio(),
            _dangerous_portfolio(),
        ]
        result = self.analyzer.analyze(portfolios)
        self.assertEqual(len(result["portfolios"]), 4)

    def test_result_keys(self):
        result = self.analyzer.analyze([_make_portfolio()])
        for key in ["portfolios", "most_diversified", "most_concentrated",
                    "avg_correlation_risk", "dangerous_count", "well_diversified_count",
                    "analyzed_at"]:
            self.assertIn(key, result)

    def test_dangerous_count(self):
        result = self.analyzer.analyze([_dangerous_portfolio(), _well_diversified_portfolio()])
        self.assertEqual(result["dangerous_count"], 1)

    def test_well_diversified_count(self):
        result = self.analyzer.analyze([_well_diversified_portfolio(), _make_portfolio()])
        self.assertGreaterEqual(result["well_diversified_count"], 1)

    def test_most_diversified_is_string(self):
        result = self.analyzer.analyze([_make_portfolio("P1"), _well_diversified_portfolio()])
        self.assertIsInstance(result["most_diversified"], str)

    def test_most_concentrated_is_string(self):
        result = self.analyzer.analyze([_make_portfolio("P1"), _dangerous_portfolio()])
        self.assertIsInstance(result["most_concentrated"], str)

    def test_avg_correlation_risk_range(self):
        result = self.analyzer.analyze([_make_portfolio(), _well_diversified_portfolio()])
        self.assertGreaterEqual(result["avg_correlation_risk"], 0.0)
        self.assertLessEqual(result["avg_correlation_risk"], 100.0)

    def test_analyzed_at_format(self):
        result = self.analyzer.analyze([_make_portfolio()])
        ts = result["analyzed_at"]
        self.assertIn("T", ts)
        self.assertTrue(ts.endswith("Z"))

    def test_empty_portfolios_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze([])

    def test_non_list_raises(self):
        with self.assertRaises((ValueError, TypeError, AttributeError)):
            self.analyzer.analyze("not a list")

    def test_missing_name_raises(self):
        p = _make_portfolio()
        del p["name"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze([p])

    def test_missing_positions_raises(self):
        p = _make_portfolio()
        del p["positions"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze([p])

    def test_missing_position_asset_raises(self):
        p = _make_portfolio()
        del p["positions"][0]["asset"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze([p])

    def test_config_none_ok(self):
        result = self.analyzer.analyze([_make_portfolio()], config=None)
        self.assertIn("portfolios", result)

    def test_config_empty_ok(self):
        result = self.analyzer.analyze([_make_portfolio()], config={})
        self.assertIn("portfolios", result)

    def test_portfolios_list_in_result_has_risk_labels(self):
        result = self.analyzer.analyze([_make_portfolio()])
        labels = {r["risk_label"] for r in result["portfolios"]}
        valid = {"WELL_DIVERSIFIED", "ADEQUATELY_DIVERSIFIED", "MODERATELY_CONCENTRATED",
                 "HIGHLY_CONCENTRATED", "DANGEROUS_CONCENTRATION"}
        self.assertTrue(labels.issubset(valid))

    def test_portfolios_list_in_result_has_flags(self):
        result = self.analyzer.analyze([_make_portfolio()])
        for r in result["portfolios"]:
            self.assertIsInstance(r["flags"], list)

    def test_module_level_analyze_function(self):
        result = analyze([_make_portfolio()])
        self.assertIn("portfolios", result)

    def test_three_portfolios_various_concentrations(self):
        portfolios = [
            _well_diversified_portfolio(),
            _make_portfolio("Mid"),
            _dangerous_portfolio(),
        ]
        result = self.analyzer.analyze(portfolios)
        self.assertEqual(len(result["portfolios"]), 3)
        self.assertGreaterEqual(result["dangerous_count"], 1)

    def test_single_position_portfolio(self):
        pos = [_make_position("USDC", 100.0, 0.1, {})]
        p = _make_portfolio(positions=pos)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["portfolios"][0]["position_count"], 1)

    def test_portfolio_volatility_non_negative(self):
        result = self.analyzer.analyze([_make_portfolio()])
        for r in result["portfolios"]:
            self.assertGreaterEqual(r["portfolio_volatility_pct"], 0.0)

    def test_hhi_range(self):
        result = self.analyzer.analyze([_make_portfolio()])
        for r in result["portfolios"]:
            self.assertGreaterEqual(r["herfindahl_concentration"], 0.0)
            self.assertLessEqual(r["herfindahl_concentration"], 10000.0)

    def test_most_concentrated_is_dangerous_when_only_one(self):
        result = self.analyzer.analyze([_dangerous_portfolio()])
        self.assertEqual(result["most_concentrated"], "DangerousPortfolio")


# ---------------------------------------------------------------------------
# 11. Test ring-buffer log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self.tmp.close()
        self.log_path = self.tmp.name

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_init_log_empty_file(self):
        with open(self.log_path, "w") as f:
            f.write("")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_invalid_json(self):
        with open(self.log_path, "w") as f:
            f.write("{not valid json}")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_nonexistent(self):
        result = _init_log("/tmp/nonexistent_spa_test_12345.json")
        self.assertEqual(result, [])

    def test_append_log_creates_entry(self):
        mock_result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "portfolios": [{"name": "P1"}],
            "avg_correlation_risk": 45.0,
            "dangerous_count": 0,
            "well_diversified_count": 1,
            "most_concentrated": "P1",
            "most_diversified": "P1",
        }
        _append_log(mock_result, log_path=self.log_path)
        entries = _init_log(self.log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ts"], "2026-01-01T00:00:00Z")

    def test_append_log_ring_buffer_cap(self):
        for i in range(105):
            mock_result = {
                "analyzed_at": f"2026-01-{i+1:02d}T00:00:00Z" if i < 31 else "2026-02-01T00:00:00Z",
                "portfolios": [],
                "avg_correlation_risk": float(i),
                "dangerous_count": 0,
                "well_diversified_count": 0,
                "most_concentrated": None,
                "most_diversified": None,
            }
            _append_log(mock_result, log_path=self.log_path)
        entries = _init_log(self.log_path)
        self.assertLessEqual(len(entries), 100)

    def test_atomic_write_creates_file(self):
        path = self.log_path + "_atomic_test.json"
        try:
            _atomic_write(path, {"test": True})
            with open(path) as f:
                data = json.load(f)
            self.assertTrue(data["test"])
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_log_written_by_analyzer(self):
        analyzer = DeFiProtocolCrossAssetCorrelationRiskAnalyzer()
        # Just verify analyze() completes (log goes to real data/ dir)
        result = analyzer.analyze([_make_portfolio()])
        self.assertIn("portfolios", result)


# ---------------------------------------------------------------------------
# 12. Test iso_now
# ---------------------------------------------------------------------------

class TestIsoNow(unittest.TestCase):

    def test_format(self):
        ts = _iso_now()
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_length(self):
        self.assertEqual(len(_iso_now()), 20)


# ---------------------------------------------------------------------------
# 13. Edge cases & additional coverage
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_chain_exposure(self):
        p = _make_portfolio(chain_exposure={})
        result = analyze([p])
        self.assertIn("portfolios", result)

    def test_empty_protocol_exposure(self):
        p = _make_portfolio(protocol_exposure={})
        result = analyze([p])
        self.assertIn("portfolios", result)

    def test_zero_eth_correlated(self):
        p = _make_portfolio(eth_correlated_pct=0.0)
        result = analyze([p])
        self.assertGreaterEqual(result["portfolios"][0]["correlation_risk_score"], 0.0)

    def test_full_eth_correlated(self):
        p = _make_portfolio(eth_correlated_pct=100.0)
        result = analyze([p])
        self.assertGreater(result["portfolios"][0]["correlation_risk_score"], 50.0)

    def test_five_equal_weight_positions(self):
        positions = [_make_position(f"A{i}", 20.0) for i in range(5)]
        p = _make_portfolio(positions=positions)
        result = analyze([p])
        hhi = result["portfolios"][0]["herfindahl_concentration"]
        self.assertAlmostEqual(hhi, 20.0, places=1)

    def test_high_stablecoin_flag(self):
        p = _make_portfolio(stablecoin_pct=50.0)
        result = analyze([p])
        self.assertIn("STABLECOIN_BUFFER", result["portfolios"][0]["flags"])

    def test_most_diversified_vs_most_concentrated(self):
        result = analyze([_well_diversified_portfolio(), _dangerous_portfolio()])
        self.assertNotEqual(result["most_diversified"], result["most_concentrated"])

    def test_avg_corr_risk_single(self):
        result = analyze([_make_portfolio(eth_correlated_pct=50.0)])
        self.assertGreaterEqual(result["avg_correlation_risk"], 0.0)

    def test_corr_row_with_negative_correlation(self):
        positions = [
            _make_position("A", 50.0, 5.0, {"B": -0.8}),
            _make_position("B", 50.0, 5.0, {"A": -0.8}),
        ]
        p = _make_portfolio(positions=positions)
        result = analyze([p])
        # negative correlation → very low portfolio vol → high diversification ratio
        self.assertGreater(
            result["portfolios"][0]["effective_diversification_ratio"], 1.5
        )

    def test_large_number_of_portfolios(self):
        portfolios = [_make_portfolio(f"Portfolio_{i}") for i in range(10)]
        result = analyze(portfolios)
        self.assertEqual(len(result["portfolios"]), 10)

    def test_portfolio_name_preserved(self):
        p = _make_portfolio(name="MySpecialPortfolio")
        result = analyze([p])
        self.assertEqual(result["portfolios"][0]["name"], "MySpecialPortfolio")

    def test_concentration_score_positive(self):
        p = _make_portfolio(protocol_exposure={"Aave": 80.0, "Compound": 20.0})
        result = analyze([p])
        self.assertGreater(result["portfolios"][0]["protocol_concentration_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
