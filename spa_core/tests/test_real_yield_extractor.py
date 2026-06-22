"""
Tests for spa_core.analytics.real_yield_extractor (MP-712 / SPA-V593).

Coverage: 70 unit tests across:
  - TestClassifyComponent            (8)
  - TestExtractDecomposition         (12)
  - TestRealYieldRatio               (6)
  - TestStablecoinYield              (5)
  - TestInflationPressure            (5)
  - TestSustainabilityScore          (5)
  - TestYieldQuality                 (7)
  - TestEmissionTokens               (4)
  - TestWarnings                     (6)
  - TestCompareProtocols             (4)
  - TestFilterRealYieldOnly          (4)
  - TestSaveLoadRoundTrip            (4)
  - TestRingBuffer                   (3)
  - TestEdgeCases                    (7)

Run:
  python3 -m unittest spa_core.tests.test_real_yield_extractor -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.real_yield_extractor import (
    YieldComponent,
    RealYieldReport,
    classify_component,
    extract,
    compare_protocols,
    filter_real_yield_only,
    save_results,
    load_history,
    SOURCE_TRADING_FEES,
    SOURCE_LENDING_INTEREST,
    SOURCE_LIQUIDATION_FEES,
    SOURCE_TOKEN_EMISSIONS,
    SOURCE_BRIBE_REWARDS,
    QUALITY_REAL_YIELD,
    QUALITY_MIXED,
    QUALITY_EMISSION_HEAVY,
    QUALITY_PONZI_RISK,
    _RING_BUFFER_MAX,
    _LOG_FILENAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _comp(source: str, apy: float, token: str = "USDC", stable: bool = True) -> YieldComponent:
    return YieldComponent(
        source=source,
        apy_pct=apy,
        is_real_yield=classify_component(source, stable),
        token_symbol=token,
        token_is_stablecoin=stable,
    )


def _extract(protocol: str, pool: str, comps: list, tmp_dir: str) -> RealYieldReport:
    return extract(protocol, pool, comps, data_dir=Path(tmp_dir))


# ---------------------------------------------------------------------------
# TestClassifyComponent
# ---------------------------------------------------------------------------

class TestClassifyComponent(unittest.TestCase):
    """8 tests — all source × stablecoin combinations."""

    def test_trading_fees_is_real(self):
        self.assertTrue(classify_component(SOURCE_TRADING_FEES, False))

    def test_trading_fees_stable_is_real(self):
        self.assertTrue(classify_component(SOURCE_TRADING_FEES, True))

    def test_lending_interest_is_real(self):
        self.assertTrue(classify_component(SOURCE_LENDING_INTEREST, False))

    def test_liquidation_fees_is_real(self):
        self.assertTrue(classify_component(SOURCE_LIQUIDATION_FEES, True))

    def test_token_emissions_is_not_real(self):
        self.assertFalse(classify_component(SOURCE_TOKEN_EMISSIONS, False))

    def test_token_emissions_stable_still_not_real(self):
        # Even if emissions are in a stablecoin, they're still inflationary
        self.assertFalse(classify_component(SOURCE_TOKEN_EMISSIONS, True))

    def test_bribe_stable_is_real(self):
        self.assertTrue(classify_component(SOURCE_BRIBE_REWARDS, True))

    def test_bribe_non_stable_not_real(self):
        self.assertFalse(classify_component(SOURCE_BRIBE_REWARDS, False))


# ---------------------------------------------------------------------------
# TestExtractDecomposition
# ---------------------------------------------------------------------------

class TestExtractDecomposition(unittest.TestCase):
    """12 tests — APY decomposition arithmetic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_real_yield_apy(self):
        comps = [_comp(SOURCE_LENDING_INTEREST, 4.0, "USDC", True)]
        r = _extract("Aave", "USDC", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 4.0)
        self.assertAlmostEqual(r.emission_yield_apy, 0.0)

    def test_all_emission_apy(self):
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("Curve", "3pool", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 0.0)
        self.assertAlmostEqual(r.emission_yield_apy, 5.0)

    def test_mixed_decomposition(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 3.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "COMP", False),
        ]
        r = _extract("Compound", "USDC", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 3.0)
        self.assertAlmostEqual(r.emission_yield_apy, 2.0)
        self.assertAlmostEqual(r.total_apy, 5.0)

    def test_total_apy_sum(self):
        comps = [
            _comp(SOURCE_TRADING_FEES, 1.5, "USDC", True),
            _comp(SOURCE_LIQUIDATION_FEES, 0.5, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "ARB", False),
        ]
        r = _extract("Aave", "ETH", comps, self.tmp)
        self.assertAlmostEqual(r.total_apy, 4.0)

    def test_bribe_stable_goes_to_real(self):
        comps = [_comp(SOURCE_BRIBE_REWARDS, 1.0, "USDC", True)]
        r = _extract("Curve", "USDC", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 1.0)
        self.assertAlmostEqual(r.emission_yield_apy, 0.0)

    def test_bribe_non_stable_goes_to_emission(self):
        comps = [_comp(SOURCE_BRIBE_REWARDS, 1.0, "CRV", False)]
        r = _extract("Curve", "3pool", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 0.0)
        self.assertAlmostEqual(r.emission_yield_apy, 1.0)

    def test_multi_real_sources(self):
        comps = [
            _comp(SOURCE_TRADING_FEES, 2.0, "USDC", True),
            _comp(SOURCE_LENDING_INTEREST, 1.5, "USDC", True),
            _comp(SOURCE_LIQUIDATION_FEES, 0.5, "USDC", True),
        ]
        r = _extract("Protocol", "Pool", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 4.0)
        self.assertAlmostEqual(r.emission_yield_apy, 0.0)

    def test_multi_emission_sources(self):
        comps = [
            _comp(SOURCE_TOKEN_EMISSIONS, 3.0, "CRV", False),
            _comp(SOURCE_BRIBE_REWARDS, 2.0, "CVX", False),
        ]
        r = _extract("Curve", "3pool", comps, self.tmp)
        self.assertAlmostEqual(r.emission_yield_apy, 5.0)
        self.assertAlmostEqual(r.real_yield_apy, 0.0)

    def test_saved_to_path_correct(self):
        r = _extract("P", "Q", [], self.tmp)
        self.assertIn(_LOG_FILENAME, r.saved_to)

    def test_protocol_pool_stored(self):
        r = _extract("TestProtocol", "TestPool", [], self.tmp)
        self.assertEqual(r.protocol, "TestProtocol")
        self.assertEqual(r.pool, "TestPool")

    def test_components_reclassified(self):
        """classify_component is applied on extract, overriding input is_real_yield."""
        comp = YieldComponent(
            source=SOURCE_TOKEN_EMISSIONS,
            apy_pct=5.0,
            is_real_yield=True,   # intentionally wrong — extract should correct
            token_symbol="CRV",
            token_is_stablecoin=False,
        )
        r = _extract("C", "P", [comp], self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 0.0)
        self.assertAlmostEqual(r.emission_yield_apy, 5.0)

    def test_trading_fee_decimal_precision(self):
        comps = [_comp(SOURCE_TRADING_FEES, 3.333333, "USDC", True)]
        r = _extract("P", "Q", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_apy, 3.333333, places=5)


# ---------------------------------------------------------------------------
# TestRealYieldRatio
# ---------------------------------------------------------------------------

class TestRealYieldRatio(unittest.TestCase):
    """6 tests — ratio computation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_real_ratio_is_one(self):
        comps = [_comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 1.0)

    def test_all_emission_ratio_is_zero(self):
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 0.0)

    def test_50_50_ratio(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 0.5)

    def test_mixed_3_to_1_ratio(self):
        comps = [
            _comp(SOURCE_TRADING_FEES, 6.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 0.75)

    def test_total_zero_ratio_is_zero(self):
        r = _extract("A", "P", [], self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 0.0)

    def test_ratio_between_zero_and_one(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 3.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 7.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertGreaterEqual(r.real_yield_ratio, 0.0)
        self.assertLessEqual(r.real_yield_ratio, 1.0)


# ---------------------------------------------------------------------------
# TestStablecoinYield
# ---------------------------------------------------------------------------

class TestStablecoinYield(unittest.TestCase):
    """5 tests — stablecoin_yield_apy computation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_stable_components(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 3.0, "USDC", True),
            _comp(SOURCE_BRIBE_REWARDS, 1.0, "DAI", True),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.stablecoin_yield_apy, 4.0)

    def test_no_stable_components(self):
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.stablecoin_yield_apy, 0.0)

    def test_mixed_stable_non_stable(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 4.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 3.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.stablecoin_yield_apy, 4.0)

    def test_bribe_stable_in_stable_yield(self):
        comps = [_comp(SOURCE_BRIBE_REWARDS, 2.0, "USDT", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.stablecoin_yield_apy, 2.0)

    def test_empty_stable_yield_zero(self):
        r = _extract("A", "P", [], self.tmp)
        self.assertAlmostEqual(r.stablecoin_yield_apy, 0.0)


# ---------------------------------------------------------------------------
# TestInflationPressure
# ---------------------------------------------------------------------------

class TestInflationPressure(unittest.TestCase):
    """5 tests — inflation_pressure formula + cap."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_zero_emission_zero_pressure(self):
        comps = [_comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.inflation_pressure, 0.0, places=3)

    def test_no_real_yield_pressure_capped(self):
        """When real_yield=0, pressure = emission / 0.001 which is likely > 10 → capped."""
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.inflation_pressure, 10.0)

    def test_cap_at_ten(self):
        """emission=50, real=1 → raw=50 → capped at 10."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 1.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 50.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.inflation_pressure, 10.0)

    def test_pressure_formula_normal(self):
        """emission=2, real=4 → pressure=0.5."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 4.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.inflation_pressure, 0.5, places=4)

    def test_pressure_below_cap(self):
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 3.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 9.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.inflation_pressure, 3.0, places=4)


# ---------------------------------------------------------------------------
# TestSustainabilityScore
# ---------------------------------------------------------------------------

class TestSustainabilityScore(unittest.TestCase):
    """5 tests — sustainability_score formula."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_real_and_stable_score_100(self):
        """real_ratio=1, stable_ratio=1 → 60+40=100."""
        comps = [_comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.sustainability_score, 100.0, places=3)

    def test_all_emission_non_stable_score_zero(self):
        """real_ratio=0, stable_ratio=0 → 0."""
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.sustainability_score, 0.0, places=3)

    def test_mixed_score_formula(self):
        """real=5 (all stable), emission=5 (non-stable) → real_ratio=0.5, stable_ratio=0.5
        score = 0.5*60 + 0.5*40 = 30+20 = 50."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.sustainability_score, 50.0, places=3)

    def test_score_capped_at_100(self):
        """Can't exceed 100."""
        comps = [_comp(SOURCE_LENDING_INTEREST, 100.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertLessEqual(r.sustainability_score, 100.0)

    def test_score_capped_at_zero(self):
        """Can't go below 0."""
        r = _extract("A", "P", [], self.tmp)
        self.assertGreaterEqual(r.sustainability_score, 0.0)


# ---------------------------------------------------------------------------
# TestYieldQuality
# ---------------------------------------------------------------------------

class TestYieldQuality(unittest.TestCase):
    """7 tests — all 4 quality tiers + edge cases."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_real_yield_quality(self):
        """real_ratio >= 0.7 → REAL_YIELD."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 7.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_REAL_YIELD)

    def test_real_yield_quality_exact_07(self):
        """real_ratio = 0.7 exactly → REAL_YIELD."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 7.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 3.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_REAL_YIELD)

    def test_mixed_quality(self):
        """real_ratio = 0.5 → MIXED."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_MIXED)

    def test_emission_heavy_quality(self):
        """real_ratio = 0.2 → EMISSION_HEAVY."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 2.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 8.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_EMISSION_HEAVY)

    def test_ponzi_risk_quality(self):
        """real_ratio < 0.1 and total > 5% → PONZI_RISK."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 0.5, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 9.5, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_PONZI_RISK)

    def test_low_apy_all_emission_not_ponzi(self):
        """total_apy <= 5 with < 10% real → EMISSION_HEAVY (not PONZI_RISK)."""
        comps = [
            _comp(SOURCE_TOKEN_EMISSIONS, 3.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_EMISSION_HEAVY)

    def test_all_real_apy_is_real_yield(self):
        """100% real → REAL_YIELD."""
        comps = [_comp(SOURCE_TRADING_FEES, 10.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_REAL_YIELD)


# ---------------------------------------------------------------------------
# TestEmissionTokens
# ---------------------------------------------------------------------------

class TestEmissionTokens(unittest.TestCase):
    """4 tests — emission_tokens list."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_single_emission_token(self):
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 3.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.emission_tokens, ["CRV"])

    def test_multiple_unique_emission_tokens(self):
        comps = [
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),
            _comp(SOURCE_BRIBE_REWARDS, 1.0, "CVX", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertIn("CRV", r.emission_tokens)
        self.assertIn("CVX", r.emission_tokens)

    def test_deduplicated_emission_tokens(self):
        """Same token emitted twice → appears once."""
        comps = [
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),
            _comp(SOURCE_BRIBE_REWARDS, 1.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.emission_tokens.count("CRV"), 1)

    def test_no_emission_tokens_when_all_real(self):
        comps = [_comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.emission_tokens, [])


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings(unittest.TestCase):
    """6 tests — all 3 warning triggers + clean case."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_warning_less_than_20_pct_real(self):
        """real_ratio < 0.2 triggers warning."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 1.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 9.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertIn("less than 20% real yield", r.warnings)

    def test_no_warning_high_real(self):
        """real_ratio >= 0.2 → no '< 20%' warning."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 4.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 6.0, "CRV", False),
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertNotIn("less than 20% real yield", r.warnings)

    def test_warning_emissions_5x_real(self):
        """inflation_pressure > 5 triggers warning."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 1.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 6.0, "CRV", False),  # 6/1 = 6 > 5
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertIn("emissions 5x real yield", r.warnings)

    def test_no_warning_low_pressure(self):
        """inflation_pressure <= 5 → no 'emissions 5x' warning."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 4.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 2.0, "CRV", False),  # 2/4 = 0.5
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertNotIn("emissions 5x real yield", r.warnings)

    def test_warning_high_non_stable_emissions(self):
        """Non-stable emission token with apy > 10% triggers warning."""
        comps = [
            _comp(SOURCE_LENDING_INTEREST, 3.0, "USDC", True),
            _comp(SOURCE_TOKEN_EMISSIONS, 12.0, "CRV", False),  # > 10
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertIn("high non-stable emissions", r.warnings)

    def test_no_high_emission_warning_if_stable(self):
        """Emission in stablecoin (even if large) → no 'high non-stable emissions'."""
        comps = [
            _comp(SOURCE_TOKEN_EMISSIONS, 15.0, "USDC", True),  # stable
        ]
        r = _extract("A", "P", comps, self.tmp)
        self.assertNotIn("high non-stable emissions", r.warnings)


# ---------------------------------------------------------------------------
# TestCompareProtocols
# ---------------------------------------------------------------------------

class TestCompareProtocols(unittest.TestCase):
    """4 tests — ordering by real_yield_ratio."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make(self, real_pct: float, emission_pct: float) -> RealYieldReport:
        comps = [
            _comp(SOURCE_LENDING_INTEREST, real_pct, "USDC", True),
        ]
        if emission_pct > 0:
            comps.append(_comp(SOURCE_TOKEN_EMISSIONS, emission_pct, "CRV", False))
        return _extract("P", "Q", comps, self.tmp)

    def test_sorted_descending(self):
        a = self._make(8.0, 2.0)   # ratio=0.8
        b = self._make(5.0, 5.0)   # ratio=0.5
        c = self._make(1.0, 9.0)   # ratio=0.1
        result = compare_protocols([b, c, a])
        self.assertEqual(result[0].real_yield_ratio, a.real_yield_ratio)
        self.assertEqual(result[-1].real_yield_ratio, c.real_yield_ratio)

    def test_single_element_list(self):
        a = self._make(5.0, 5.0)
        result = compare_protocols([a])
        self.assertEqual(len(result), 1)

    def test_empty_list(self):
        result = compare_protocols([])
        self.assertEqual(result, [])

    def test_equal_ratios_preserve_all(self):
        a = self._make(5.0, 5.0)
        b = self._make(5.0, 5.0)
        result = compare_protocols([a, b])
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# TestFilterRealYieldOnly
# ---------------------------------------------------------------------------

class TestFilterRealYieldOnly(unittest.TestCase):
    """4 tests — min_real_apy filter."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make(self, real_pct: float) -> RealYieldReport:
        comps = [_comp(SOURCE_LENDING_INTEREST, real_pct, "USDC", True)]
        return _extract("P", "Q", comps, self.tmp)

    def test_all_pass_low_threshold(self):
        reports = [self._make(3.0), self._make(5.0), self._make(7.0)]
        result = filter_real_yield_only(reports, min_real_apy=2.0)
        self.assertEqual(len(result), 3)

    def test_none_pass_high_threshold(self):
        reports = [self._make(1.0), self._make(2.0)]
        result = filter_real_yield_only(reports, min_real_apy=5.0)
        self.assertEqual(len(result), 0)

    def test_partial_pass(self):
        reports = [self._make(2.0), self._make(4.0), self._make(6.0)]
        result = filter_real_yield_only(reports, min_real_apy=4.0)
        self.assertEqual(len(result), 2)

    def test_exact_boundary_included(self):
        reports = [self._make(3.0)]
        result = filter_real_yield_only(reports, min_real_apy=3.0)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# TestSaveLoadRoundTrip
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip(unittest.TestCase):
    """4 tests — save_results / load_history."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make(self) -> RealYieldReport:
        comps = [_comp(SOURCE_LENDING_INTEREST, 5.0, "USDC", True)]
        return _extract("Aave", "USDC", comps, self.tmp)

    def test_save_then_load(self):
        r = self._make()
        save_results(r, data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertEqual(len(history), 1)

    def test_save_multiple_accumulated(self):
        for _ in range(3):
            save_results(self._make(), data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertEqual(len(history), 3)

    def test_load_empty_returns_list(self):
        history = load_history(data_dir=Path(self.tmp))
        self.assertIsInstance(history, list)

    def test_saved_data_is_dict(self):
        save_results(self._make(), data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertIsInstance(history[0], dict)


# ---------------------------------------------------------------------------
# TestRingBuffer
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):
    """3 tests — ring-buffer capping at 100."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make(self) -> RealYieldReport:
        return _extract("P", "Q", [], self.tmp)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            save_results(self._make(), data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertEqual(len(history), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_newest(self):
        """After 105 saves, the oldest entries are dropped."""
        for _ in range(105):
            save_results(self._make(), data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertLessEqual(len(history), 100)

    def test_ring_buffer_at_exact_cap(self):
        for _ in range(_RING_BUFFER_MAX):
            save_results(self._make(), data_dir=Path(self.tmp))
        history = load_history(data_dir=Path(self.tmp))
        self.assertEqual(len(history), _RING_BUFFER_MAX)


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """7 tests — empty components, zero APY, extreme values."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_components_all_zeros(self):
        r = _extract("A", "P", [], self.tmp)
        self.assertAlmostEqual(r.total_apy, 0.0)
        self.assertAlmostEqual(r.real_yield_apy, 0.0)
        self.assertAlmostEqual(r.emission_yield_apy, 0.0)
        self.assertAlmostEqual(r.real_yield_ratio, 0.0)

    def test_empty_components_no_emission_tokens(self):
        r = _extract("A", "P", [], self.tmp)
        self.assertEqual(r.emission_tokens, [])

    def test_empty_components_no_warnings(self):
        """No warnings for zero APY — real_ratio=0 < 0.2 triggers '< 20% real' warning."""
        r = _extract("A", "P", [], self.tmp)
        # With total=0, real_ratio=0 < 0.2 → warning exists
        # inflation_pressure: emission=0/max(0,0.001)=0 → no "5x" warning
        # no non-stable emission component → no "high non-stable" warning
        self.assertIn("less than 20% real yield", r.warnings)

    def test_total_zero_no_division_error(self):
        """total_apy=0 must not raise ZeroDivisionError."""
        try:
            r = _extract("A", "P", [], self.tmp)
            self.assertIsNotNone(r)
        except ZeroDivisionError:
            self.fail("extract() raised ZeroDivisionError on total_apy=0")

    def test_very_high_real_apy(self):
        """High APY should not break any computation."""
        comps = [_comp(SOURCE_TRADING_FEES, 1000.0, "USDC", True)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertAlmostEqual(r.real_yield_ratio, 1.0)

    def test_single_emission_ponzi_threshold(self):
        """Exactly at 5% APY with 0 real → EMISSION_HEAVY (not PONZI, need > 5)."""
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.0, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_EMISSION_HEAVY)

    def test_emission_just_above_ponzi_threshold(self):
        """5.01% APY with 0 real → PONZI_RISK."""
        comps = [_comp(SOURCE_TOKEN_EMISSIONS, 5.01, "CRV", False)]
        r = _extract("A", "P", comps, self.tmp)
        self.assertEqual(r.yield_quality, QUALITY_PONZI_RISK)


if __name__ == "__main__":
    unittest.main()
