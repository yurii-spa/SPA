"""
Tests for MP-873 DeFiFundingRateArbitrageDetector.
Run: python3 -m unittest spa_core.tests.test_defi_funding_rate_arbitrage_detector -v
"""
import json
import os
import sys
import time
import unittest
import tempfile

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_funding_rate_arbitrage_detector import (
    analyze,
    _annualize_funding_rate,
    _annualize_execution_cost,
    _gross_spread,
    _net_spread,
    _estimated_profit,
    _opportunity_type,
    _risk_note,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opp(
    asset="ETH",
    funding_8h=0.05,
    spot_apy=3.5,
    spot_protocol="Aave",
    perp_protocol="dYdX",
    exec_cost=0.3,
    capital=100_000,
    holding=30,
):
    return {
        "asset": asset,
        "perp_funding_rate_pct_8h": funding_8h,
        "spot_lending_apy_pct": spot_apy,
        "spot_protocol": spot_protocol,
        "perp_protocol": perp_protocol,
        "execution_cost_pct": exec_cost,
        "capital_usd": capital,
        "holding_days": holding,
    }


# ===========================================================================
# Unit tests — helper functions
# ===========================================================================

class TestAnnualizeFundingRate(unittest.TestCase):
    def test_positive_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.05), 0.05 * 3 * 365)

    def test_zero_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.0), 0.0)

    def test_negative_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(-0.03), -0.03 * 3 * 365)

    def test_large_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(1.0), 1095.0)

    def test_small_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.001), 0.001 * 1095)


class TestAnnualizeExecutionCost(unittest.TestCase):
    def test_normal(self):
        result = _annualize_execution_cost(0.3, 30)
        self.assertAlmostEqual(result, 0.3 / 30 * 365)

    def test_zero_holding(self):
        self.assertEqual(_annualize_execution_cost(0.5, 0), 0.0)

    def test_negative_holding(self):
        self.assertEqual(_annualize_execution_cost(0.5, -5), 0.0)

    def test_zero_cost(self):
        self.assertAlmostEqual(_annualize_execution_cost(0.0, 30), 0.0)

    def test_one_day_holding(self):
        self.assertAlmostEqual(_annualize_execution_cost(1.0, 1), 365.0)

    def test_365_days(self):
        self.assertAlmostEqual(_annualize_execution_cost(2.0, 365), 2.0)


class TestGrossSpread(unittest.TestCase):
    def test_positive(self):
        self.assertAlmostEqual(_gross_spread(50.0, 3.5), 46.5)

    def test_negative(self):
        self.assertAlmostEqual(_gross_spread(2.0, 10.0), -8.0)

    def test_equal(self):
        self.assertAlmostEqual(_gross_spread(5.0, 5.0), 0.0)

    def test_both_negative(self):
        self.assertAlmostEqual(_gross_spread(-10.0, -5.0), -5.0)


class TestNetSpread(unittest.TestCase):
    def test_positive(self):
        self.assertAlmostEqual(_net_spread(10.0, 2.0), 8.0)

    def test_negative(self):
        self.assertAlmostEqual(_net_spread(2.0, 5.0), -3.0)

    def test_zero(self):
        self.assertAlmostEqual(_net_spread(0.0, 0.0), 0.0)


class TestEstimatedProfit(unittest.TestCase):
    def test_basic(self):
        profit = _estimated_profit(100_000, 10.0, 365)
        self.assertAlmostEqual(profit, 10_000.0)

    def test_zero_capital(self):
        self.assertEqual(_estimated_profit(0, 10.0, 30), 0.0)

    def test_zero_days(self):
        self.assertEqual(_estimated_profit(100_000, 10.0, 0), 0.0)

    def test_negative_capital(self):
        self.assertEqual(_estimated_profit(-1000, 10.0, 30), 0.0)

    def test_negative_spread(self):
        profit = _estimated_profit(100_000, -5.0, 30)
        self.assertAlmostEqual(profit, 100_000 * -5.0 / 100.0 * 30 / 365.0)

    def test_partial_year(self):
        profit = _estimated_profit(100_000, 10.0, 30)
        self.assertAlmostEqual(profit, 100_000 * 0.10 * 30 / 365.0)


class TestOpportunityType(unittest.TestCase):
    def test_negative_spread(self):
        self.assertEqual(_opportunity_type(-1.0, 50.0, 5.0), "NEGATIVE")

    def test_neutral_below_threshold(self):
        self.assertEqual(_opportunity_type(3.0, 50.0, 5.0), "NEUTRAL")

    def test_neutral_at_zero(self):
        self.assertEqual(_opportunity_type(0.0, 50.0, 5.0), "NEUTRAL")

    def test_funding_rate_arb(self):
        self.assertEqual(_opportunity_type(10.0, 50.0, 5.0), "FUNDING_RATE_ARB")

    def test_spot_yield_dominant(self):
        self.assertEqual(_opportunity_type(10.0, -5.0, 5.0), "SPOT_YIELD_DOMINANT")

    def test_exactly_at_threshold(self):
        # net_spread == min_threshold → is_opportunity, perp>=0 → FUNDING_RATE_ARB
        self.assertEqual(_opportunity_type(5.0, 10.0, 5.0), "FUNDING_RATE_ARB")

    def test_spot_dominant_zero_funding(self):
        # perp_funding_annualized == 0 → >= 0 → FUNDING_RATE_ARB, not SPOT_YIELD_DOMINANT
        self.assertEqual(_opportunity_type(10.0, 0.0, 5.0), "FUNDING_RATE_ARB")


class TestRiskNote(unittest.TestCase):
    def test_negative(self):
        note = _risk_note("NEGATIVE", -1.0, -10.0, 5.0, "Aave", "dYdX")
        self.assertIn("negative", note.lower())

    def test_neutral(self):
        note = _risk_note("NEUTRAL", 3.0, 10.0, 5.0, "Aave", "dYdX")
        self.assertIn("3.0", note)
        self.assertIn("5.0", note)

    def test_funding_rate_arb(self):
        note = _risk_note("FUNDING_RATE_ARB", 8.5, 20.0, 5.0, "Aave", "dYdX")
        self.assertIn("Aave", note)
        self.assertIn("dYdX", note)
        self.assertIn("8.5", note)

    def test_spot_yield_dominant(self):
        note = _risk_note("SPOT_YIELD_DOMINANT", 7.0, -15.3, 5.0, "Aave", "dYdX")
        self.assertIn("-15.3", note)
        self.assertIn("short-bias", note)


# ===========================================================================
# Integration tests — analyze()
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_opportunities_empty(self):
        self.assertEqual(self.result["opportunities"], [])

    def test_best_opportunity_none(self):
        self.assertIsNone(self.result["best_opportunity"])

    def test_total_viable_zero(self):
        self.assertEqual(self.result["total_viable_opportunities"], 0)

    def test_average_net_zero(self):
        self.assertAlmostEqual(self.result["average_net_spread_pct"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)


class TestAnalyzeSingleOpportunity(unittest.TestCase):
    """ETH with funding_8h=0.05 → ann=54.75%, spot=3.5, exec=0.3 for 30d."""

    def setUp(self):
        self.inp = _opp()  # defaults
        self.result = analyze([self.inp])
        self.opp = self.result["opportunities"][0]

    def test_perp_funding_annualized(self):
        expected = 0.05 * 3 * 365
        self.assertAlmostEqual(self.opp["perp_funding_annualized_pct"], expected, places=4)

    def test_spot_lending_apy(self):
        self.assertAlmostEqual(self.opp["spot_lending_apy_pct"], 3.5, places=4)

    def test_gross_spread(self):
        expected = 0.05 * 1095 - 3.5
        self.assertAlmostEqual(self.opp["gross_spread_pct"], expected, places=4)

    def test_execution_cost_annualized(self):
        expected = 0.3 / 30 * 365
        self.assertAlmostEqual(self.opp["execution_cost_annualized_pct"], expected, places=4)

    def test_net_spread_positive(self):
        self.assertGreater(self.opp["net_spread_pct"], 0)

    def test_is_opportunity_true(self):
        self.assertTrue(self.opp["is_opportunity"])

    def test_opportunity_type_funding_rate_arb(self):
        self.assertEqual(self.opp["opportunity_type"], "FUNDING_RATE_ARB")

    def test_estimated_profit_positive(self):
        self.assertGreater(self.opp["estimated_profit_usd"], 0)

    def test_annualized_return_equals_net_spread(self):
        self.assertAlmostEqual(
            self.opp["annualized_return_pct"],
            self.opp["net_spread_pct"],
            places=6,
        )

    def test_best_opportunity_is_eth(self):
        self.assertEqual(self.result["best_opportunity"], "ETH")

    def test_total_viable_one(self):
        self.assertEqual(self.result["total_viable_opportunities"], 1)


class TestAnalyzeNegativeSpread(unittest.TestCase):
    """Low funding rate that makes net_spread negative."""

    def setUp(self):
        inp = _opp(funding_8h=0.001, spot_apy=5.0, exec_cost=2.0, holding=5)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_opportunity_type_negative(self):
        self.assertEqual(self.opp["opportunity_type"], "NEGATIVE")

    def test_is_opportunity_false(self):
        self.assertFalse(self.opp["is_opportunity"])

    def test_best_none(self):
        self.assertIsNone(self.result["best_opportunity"])

    def test_total_viable_zero(self):
        self.assertEqual(self.result["total_viable_opportunities"], 0)


class TestAnalyzeNeutralSpread(unittest.TestCase):
    """net_spread > 0 but < 5% default threshold."""

    def setUp(self):
        # funding_ann = 0.01 * 1095 = 10.95; spot=5; exec_ann=0.5/30*365≈6.08; net≈-0.13
        # Let's engineer it: funding=0.02*3*365=21.9; spot=15; exec=0.3/30*365=3.65; net=3.25 < 5
        inp = _opp(funding_8h=0.02, spot_apy=15.0, exec_cost=0.3, holding=30)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_opportunity_type_neutral(self):
        self.assertEqual(self.opp["opportunity_type"], "NEUTRAL")

    def test_is_opportunity_false(self):
        self.assertFalse(self.opp["is_opportunity"])


class TestAnalyzeSpotYieldDominant(unittest.TestCase):
    """Negative funding + large spot yield → SPOT_YIELD_DOMINANT."""

    def setUp(self):
        # funding_8h=-0.01 → ann=-10.95; spot=5; exec_ann=0; net=-15.95 → NEGATIVE
        # We need net >= threshold=5 AND perp_funding < 0:
        # funding=-0.001 → ann=-1.095; spot=0.0; exec=0; net=-1.095 → still NEGATIVE
        # Trick: make spot_apy = -10 (lender cost?) and funding_8h = -0.03
        # Actually: SPOT_YIELD_DOMINANT means perp_funding_annualized < 0 AND net >= min
        # gross = perp_fund_ann - spot_apy; if perp_fund_ann < 0 and spot_apy is also negative
        # gross = -10.95 - (-15) = 4.05; net = 4.05 (if exec=0); < 5 → NEUTRAL
        # Let's try: funding=-0.01 ann=-10.95; spot_apy=-20 (negative = you earn when borrowing)
        # gross = -10.95 - (-20) = 9.05; exec=0; net=9.05; >= 5 AND perp_ann<0 → SPOT_YIELD_DOMINANT
        inp = _opp(funding_8h=-0.01, spot_apy=-20.0, exec_cost=0.0, holding=30)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_opportunity_type_spot_yield_dominant(self):
        self.assertEqual(self.opp["opportunity_type"], "SPOT_YIELD_DOMINANT")

    def test_is_opportunity_true(self):
        self.assertTrue(self.opp["is_opportunity"])

    def test_risk_note_contains_negative_funding(self):
        self.assertIn("short-bias", self.opp["risk_note"])


class TestAnalyzeMultipleOpportunities(unittest.TestCase):
    """Two assets: one viable, one not. Best should be the one with higher net_spread."""

    def setUp(self):
        opps = [
            _opp(asset="ETH", funding_8h=0.05, spot_apy=3.5, exec_cost=0.1, holding=30),
            _opp(asset="BTC", funding_8h=0.001, spot_apy=4.8, exec_cost=2.0, holding=5),
        ]
        self.result = analyze(opps)

    def test_two_items_in_result(self):
        self.assertEqual(len(self.result["opportunities"]), 2)

    def test_best_is_eth(self):
        self.assertEqual(self.result["best_opportunity"], "ETH")

    def test_total_viable_at_least_one(self):
        self.assertGreaterEqual(self.result["total_viable_opportunities"], 1)

    def test_average_net_spread_computed(self):
        nets = [o["net_spread_pct"] for o in self.result["opportunities"]]
        expected = sum(nets) / len(nets)
        self.assertAlmostEqual(self.result["average_net_spread_pct"], expected, places=4)


class TestAnalyzeZeroHoldingDays(unittest.TestCase):
    def setUp(self):
        inp = _opp(holding=0)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_execution_cost_annualized_zero(self):
        self.assertAlmostEqual(self.opp["execution_cost_annualized_pct"], 0.0)

    def test_profit_zero(self):
        self.assertAlmostEqual(self.opp["estimated_profit_usd"], 0.0)


class TestAnalyzeZeroCapital(unittest.TestCase):
    def setUp(self):
        inp = _opp(capital=0)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_profit_zero(self):
        self.assertAlmostEqual(self.opp["estimated_profit_usd"], 0.0)


class TestAnalyzeCustomThreshold(unittest.TestCase):
    """Custom min_annualized_spread_pct = 2.0 → more opportunities qualify."""

    def setUp(self):
        # net_spread ~ 3.25 (NEUTRAL at 5%) should be VIABLE at 2%
        inp = _opp(funding_8h=0.02, spot_apy=15.0, exec_cost=0.3, holding=30)
        self.result = analyze([inp], config={"min_annualized_spread_pct": 2.0})
        self.opp = self.result["opportunities"][0]

    def test_is_opportunity_at_low_threshold(self):
        self.assertTrue(self.opp["is_opportunity"])

    def test_type_funding_rate_arb(self):
        self.assertEqual(self.opp["opportunity_type"], "FUNDING_RATE_ARB")


class TestAnalyzeRiskNoteContent(unittest.TestCase):
    def test_negative_note(self):
        inp = _opp(funding_8h=0.001, spot_apy=5.0, exec_cost=2.0, holding=5)
        result = analyze([inp])
        self.assertIn("not profitable", result["opportunities"][0]["risk_note"].lower())

    def test_neutral_note_threshold(self):
        inp = _opp(funding_8h=0.02, spot_apy=15.0, exec_cost=0.3, holding=30)
        result = analyze([inp])
        note = result["opportunities"][0]["risk_note"]
        self.assertIn("5.0", note)

    def test_funding_arb_note_protocols(self):
        inp = _opp(spot_protocol="Morpho", perp_protocol="Hyperliquid")
        result = analyze([inp])
        note = result["opportunities"][0]["risk_note"]
        self.assertIn("Morpho", note)
        self.assertIn("Hyperliquid", note)


class TestAnalyzeOutputKeys(unittest.TestCase):
    def test_top_level_keys(self):
        result = analyze([_opp()])
        for key in [
            "opportunities",
            "best_opportunity",
            "total_viable_opportunities",
            "average_net_spread_pct",
            "timestamp",
        ]:
            self.assertIn(key, result)

    def test_opp_level_keys(self):
        result = analyze([_opp()])
        opp = result["opportunities"][0]
        for key in [
            "asset",
            "perp_funding_annualized_pct",
            "spot_lending_apy_pct",
            "gross_spread_pct",
            "net_spread_pct",
            "execution_cost_annualized_pct",
            "estimated_profit_usd",
            "annualized_return_pct",
            "is_opportunity",
            "opportunity_type",
            "risk_note",
        ]:
            self.assertIn(key, opp, f"Key '{key}' missing from opportunity")


class TestAnalyzePerfectArbitrage(unittest.TestCase):
    """Very high funding rate, zero execution cost: large profit."""

    def setUp(self):
        # funding=0.1 → ann=109.5; spot=3; exec=0; net=106.5 → big
        inp = _opp(funding_8h=0.1, spot_apy=3.0, exec_cost=0.0, holding=365)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_is_opportunity_true(self):
        self.assertTrue(self.opp["is_opportunity"])

    def test_type_funding_rate_arb(self):
        self.assertEqual(self.opp["opportunity_type"], "FUNDING_RATE_ARB")

    def test_profit_approximately_correct(self):
        net = self.opp["net_spread_pct"]
        expected = 100_000 * net / 100.0  # 365/365 = 1
        self.assertAlmostEqual(self.opp["estimated_profit_usd"], expected, places=2)


class TestAnalyzeExactlyAtThreshold(unittest.TestCase):
    """net_spread well above default threshold of 5.0 → is_opportunity = True."""

    def setUp(self):
        # funding_8h=0.01 → perp_ann≈10.95; spot=5.0; exec=0; net≈5.95 ≥ 5.0
        inp = _opp(funding_8h=0.01, spot_apy=5.0, exec_cost=0.0, holding=30)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_is_opportunity(self):
        self.assertTrue(self.opp["is_opportunity"])

    def test_viable_count(self):
        self.assertEqual(self.result["total_viable_opportunities"], 1)


class TestAnalyzeNegativeFundingOpportunity(unittest.TestCase):
    """Negative funding rate should be annualized correctly (negative value)."""

    def setUp(self):
        inp = _opp(funding_8h=-0.05)
        self.result = analyze([inp])
        self.opp = self.result["opportunities"][0]

    def test_perp_funding_negative(self):
        self.assertLess(self.opp["perp_funding_annualized_pct"], 0)

    def test_opportunity_type_negative_or_neutral(self):
        self.assertIn(
            self.opp["opportunity_type"],
            ["NEGATIVE", "NEUTRAL", "SPOT_YIELD_DOMINANT"],
        )


class TestAnalyzeTimestamp(unittest.TestCase):
    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAnalyzeAssetPassthrough(unittest.TestCase):
    def test_asset_name_preserved(self):
        inp = _opp(asset="SOL")
        result = analyze([inp])
        self.assertEqual(result["opportunities"][0]["asset"], "SOL")


class TestAnalyzeThreeOpps(unittest.TestCase):
    """Three opportunities: pick the best viable one."""

    def setUp(self):
        opps = [
            _opp(asset="LOW", funding_8h=0.001, spot_apy=5.0, exec_cost=2.0, holding=5),  # negative/neutral
            _opp(asset="MID", funding_8h=0.02, spot_apy=5.0, exec_cost=0.1, holding=30),  # ~17.65%
            _opp(asset="HIGH", funding_8h=0.05, spot_apy=3.5, exec_cost=0.1, holding=30),  # ~50.7%
        ]
        self.result = analyze(opps)

    def test_best_is_high(self):
        self.assertEqual(self.result["best_opportunity"], "HIGH")

    def test_count_three(self):
        self.assertEqual(len(self.result["opportunities"]), 3)

    def test_average_includes_all(self):
        nets = [o["net_spread_pct"] for o in self.result["opportunities"]]
        expected = sum(nets) / 3
        self.assertAlmostEqual(self.result["average_net_spread_pct"], expected, places=4)


class TestAnalyzeNoViable(unittest.TestCase):
    """All opportunities are negative → best=None, total_viable=0."""

    def setUp(self):
        opps = [
            _opp(asset="A", funding_8h=0.001, spot_apy=5.0, exec_cost=3.0, holding=10),
            _opp(asset="B", funding_8h=-0.01, spot_apy=5.0, exec_cost=0.5, holding=10),
        ]
        self.result = analyze(opps)

    def test_best_none(self):
        self.assertIsNone(self.result["best_opportunity"])

    def test_total_viable_zero(self):
        self.assertEqual(self.result["total_viable_opportunities"], 0)


# ===========================================================================
# Log management tests
# ===========================================================================

class TestInitLog(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import spa_core.analytics.defi_funding_rate_arbitrage_detector as mod
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_log.json")
            try:
                mod.init_log()
                self.assertTrue(os.path.exists(mod.LOG_PATH))
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(data, [])
            finally:
                mod.LOG_PATH = orig

    def test_does_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import spa_core.analytics.defi_funding_rate_arbitrage_detector as mod
            orig = mod.LOG_PATH
            log_path = os.path.join(tmpdir, "test_log.json")
            mod.LOG_PATH = log_path
            try:
                with open(log_path, "w") as f:
                    json.dump([{"existing": True}], f)
                mod.init_log()
                with open(log_path) as f:
                    data = json.load(f)
                self.assertEqual(data, [{"existing": True}])
            finally:
                mod.LOG_PATH = orig


class TestAppendLog(unittest.TestCase):
    def _run_with_tmp_log(self, fn):
        import spa_core.analytics.defi_funding_rate_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_log.json")
            try:
                fn(mod)
            finally:
                mod.LOG_PATH = orig

    def test_log_appends_entries(self):
        def check(mod):
            analyze([])
            analyze([])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

        self._run_with_tmp_log(check)

    def test_log_ring_buffer_100(self):
        def check(mod):
            for _ in range(105):
                analyze([])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

        self._run_with_tmp_log(check)

    def test_log_entry_has_timestamp(self):
        def check(mod):
            analyze([_opp()])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[-1])

        self._run_with_tmp_log(check)

    def test_log_is_valid_json(self):
        def check(mod):
            analyze([_opp()])
            with open(mod.LOG_PATH) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

        self._run_with_tmp_log(check)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_empty_list_no_error(self):
        result = analyze([])
        self.assertIsNotNone(result)

    def test_zero_funding_zero_spot(self):
        inp = _opp(funding_8h=0.0, spot_apy=0.0, exec_cost=0.0)
        result = analyze([inp])
        opp = result["opportunities"][0]
        self.assertAlmostEqual(opp["perp_funding_annualized_pct"], 0.0)
        self.assertAlmostEqual(opp["gross_spread_pct"], 0.0)
        self.assertAlmostEqual(opp["net_spread_pct"], 0.0)

    def test_very_high_funding_rate(self):
        inp = _opp(funding_8h=10.0)
        result = analyze([inp])
        self.assertGreater(result["opportunities"][0]["perp_funding_annualized_pct"], 1000)

    def test_default_config_none(self):
        result = analyze([_opp()], config=None)
        self.assertIsNotNone(result)

    def test_empty_config(self):
        result = analyze([_opp()], config={})
        self.assertIsNotNone(result)

    def test_string_holding_days_as_int(self):
        # holding_days should be coerced to int
        inp = {
            "asset": "ETH",
            "perp_funding_rate_pct_8h": 0.05,
            "spot_lending_apy_pct": 3.5,
            "spot_protocol": "Aave",
            "perp_protocol": "dYdX",
            "execution_cost_pct": 0.3,
            "capital_usd": 100_000,
            "holding_days": 30,
        }
        result = analyze([inp])
        self.assertIsNotNone(result)

    def test_single_zero_spread_opportunity_type(self):
        # net=0 → NEUTRAL (0 < 5 threshold)
        inp = _opp(funding_8h=0.0, spot_apy=0.0, exec_cost=0.0)
        result = analyze([inp])
        self.assertEqual(result["opportunities"][0]["opportunity_type"], "NEUTRAL")

    def test_is_opportunity_bool_type(self):
        result = analyze([_opp()])
        self.assertIsInstance(result["opportunities"][0]["is_opportunity"], bool)

    def test_multiple_same_asset(self):
        opps = [_opp(asset="ETH", funding_8h=0.05), _opp(asset="ETH", funding_8h=0.06)]
        result = analyze(opps)
        self.assertEqual(len(result["opportunities"]), 2)

    def test_result_opportunities_list_type(self):
        result = analyze([_opp()])
        self.assertIsInstance(result["opportunities"], list)

    def test_best_opportunity_string_or_none(self):
        result = analyze([_opp()])
        best = result["best_opportunity"]
        self.assertTrue(best is None or isinstance(best, str))


if __name__ == "__main__":
    unittest.main()
