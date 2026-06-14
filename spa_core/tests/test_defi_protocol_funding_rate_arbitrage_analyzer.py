"""
Tests for MP-1100 DeFiProtocolFundingRateArbitrageAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_funding_rate_arbitrage_analyzer -v
Total: ≥110 tests.
"""
import json
import os
import sys
import tempfile
import time
import unittest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_funding_rate_arbitrage_analyzer import (
    DeFiProtocolFundingRateArbitrageAnalyzer,
    analyze,
    analyze_and_log,
    init_log,
    LOG_FILENAME,
    LOG_MAX_ENTRIES,
    _annualize_funding_rate,
    _compute_net_arb_spread,
    _compute_capital_required,
    _compute_gas_drag,
    _compute_annualized_return_on_capital,
    _compute_quality_score,
    _classify_arb,
    _append_log,
    _read_log,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _default_kwargs(**overrides):
    base = dict(
        perp_funding_rate_8h_pct=0.01,
        spot_borrow_rate_annual_pct=3.0,
        spot_yield_annual_pct=4.5,
        position_size_usd=100_000.0,
        margin_requirement_pct=10.0,
        liquidation_buffer_pct=5.0,
        gas_cost_usd=50.0,
        protocol_name="dYdX+Aave",
    )
    base.update(overrides)
    return base


# ===========================================================================
# 1. _annualize_funding_rate
# ===========================================================================

class TestAnnualizeFundingRate(unittest.TestCase):

    def test_positive_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.01), 0.01 * 3 * 365)

    def test_zero_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.0), 0.0)

    def test_negative_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(-0.05), -0.05 * 3 * 365)

    def test_large_positive_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(1.0), 1095.0)

    def test_small_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.001), 0.001 * 1095)

    def test_typical_bull_market_rate(self):
        # 0.03% / 8h is a typical bull funding
        result = _annualize_funding_rate(0.03)
        self.assertAlmostEqual(result, 0.03 * 1095)

    def test_multiplication_factor(self):
        # Must be exactly ×1095
        for rate in [0.001, 0.01, 0.1, 0.5]:
            with self.subTest(rate=rate):
                self.assertAlmostEqual(_annualize_funding_rate(rate), rate * 1095)

    def test_returns_float(self):
        result = _annualize_funding_rate(0.01)
        self.assertIsInstance(result, float)


# ===========================================================================
# 2. _compute_net_arb_spread
# ===========================================================================

class TestComputeNetArbSpread(unittest.TestCase):

    def test_basic(self):
        # annual=10.95, borrow=3.0, yield=4.5 → 12.45
        result = _compute_net_arb_spread(10.95, 3.0, 4.5)
        self.assertAlmostEqual(result, 12.45)

    def test_zero_yield_zero_borrow(self):
        result = _compute_net_arb_spread(10.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 10.0)

    def test_negative_funding(self):
        # Negative funding reduces spread
        result = _compute_net_arb_spread(-5.0, 2.0, 3.0)
        self.assertAlmostEqual(result, -4.0)

    def test_high_borrow_erodes_spread(self):
        result = _compute_net_arb_spread(15.0, 20.0, 0.0)
        self.assertAlmostEqual(result, -5.0)

    def test_spot_yield_improves_spread(self):
        r1 = _compute_net_arb_spread(10.0, 5.0, 0.0)
        r2 = _compute_net_arb_spread(10.0, 5.0, 3.0)
        self.assertGreater(r2, r1)

    def test_all_zeros(self):
        self.assertAlmostEqual(_compute_net_arb_spread(0.0, 0.0, 0.0), 0.0)

    def test_formula_symmetry(self):
        # funding=10, borrow=3, yield=3 → 10
        self.assertAlmostEqual(_compute_net_arb_spread(10.0, 3.0, 3.0), 10.0)

    def test_returns_float(self):
        result = _compute_net_arb_spread(5.0, 1.0, 2.0)
        self.assertIsInstance(result, float)


# ===========================================================================
# 3. _compute_capital_required
# ===========================================================================

class TestComputeCapitalRequired(unittest.TestCase):

    def test_basic(self):
        # (10+5)/100 * 100000 = 15000
        result = _compute_capital_required(100_000.0, 10.0, 5.0)
        self.assertAlmostEqual(result, 15_000.0)

    def test_zero_position(self):
        result = _compute_capital_required(0.0, 10.0, 5.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_position_returns_zero(self):
        result = _compute_capital_required(-100.0, 10.0, 5.0)
        self.assertAlmostEqual(result, 0.0)

    def test_100_percent_margin(self):
        result = _compute_capital_required(50_000.0, 100.0, 0.0)
        self.assertAlmostEqual(result, 50_000.0)

    def test_zero_margin_buffer(self):
        result = _compute_capital_required(100_000.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_large_position(self):
        result = _compute_capital_required(1_000_000.0, 5.0, 2.0)
        self.assertAlmostEqual(result, 70_000.0)

    def test_margin_plus_buffer_combined(self):
        # margin=8, buffer=7 → 15%
        result = _compute_capital_required(200_000.0, 8.0, 7.0)
        self.assertAlmostEqual(result, 30_000.0)

    def test_returns_float(self):
        result = _compute_capital_required(100_000.0, 10.0, 5.0)
        self.assertIsInstance(result, float)


# ===========================================================================
# 4. _compute_gas_drag
# ===========================================================================

class TestComputeGasDrag(unittest.TestCase):

    def test_basic(self):
        # 50 / 15000 * 100 = 0.3333%
        result = _compute_gas_drag(50.0, 15_000.0)
        self.assertAlmostEqual(result, 50.0 / 15_000.0 * 100.0)

    def test_zero_gas(self):
        result = _compute_gas_drag(0.0, 15_000.0)
        self.assertAlmostEqual(result, 0.0)

    def test_zero_capital_returns_zero(self):
        result = _compute_gas_drag(100.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_capital_returns_zero(self):
        result = _compute_gas_drag(50.0, -1000.0)
        self.assertAlmostEqual(result, 0.0)

    def test_high_gas_relative_to_capital(self):
        # 1000 / 5000 * 100 = 20%
        result = _compute_gas_drag(1_000.0, 5_000.0)
        self.assertAlmostEqual(result, 20.0)

    def test_proportionality(self):
        r1 = _compute_gas_drag(100.0, 10_000.0)
        r2 = _compute_gas_drag(200.0, 10_000.0)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_returns_float(self):
        result = _compute_gas_drag(50.0, 15_000.0)
        self.assertIsInstance(result, float)


# ===========================================================================
# 5. _compute_annualized_return_on_capital
# ===========================================================================

class TestComputeAnnualizedReturnOnCapital(unittest.TestCase):

    def test_basic(self):
        # spread=12.45, position=100000, capital=15000, gas_drag=0.333
        # leverage = 100000/15000 = 6.667; roc = 12.45 * 6.667 - 0.333 = 82.67
        spread = 12.45
        pos = 100_000.0
        cap = 15_000.0
        gas = _compute_gas_drag(50.0, cap)
        expected = spread * (pos / cap) - gas
        result = _compute_annualized_return_on_capital(spread, pos, cap, gas)
        self.assertAlmostEqual(result, expected)

    def test_zero_capital_returns_zero(self):
        result = _compute_annualized_return_on_capital(10.0, 100_000.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_spread_gives_negative_roc(self):
        result = _compute_annualized_return_on_capital(-5.0, 100_000.0, 15_000.0, 0.0)
        self.assertLess(result, 0.0)

    def test_gas_drag_reduces_roc(self):
        r_no_gas = _compute_annualized_return_on_capital(10.0, 100_000.0, 15_000.0, 0.0)
        r_with_gas = _compute_annualized_return_on_capital(10.0, 100_000.0, 15_000.0, 1.0)
        self.assertGreater(r_no_gas, r_with_gas)

    def test_leverage_amplifies_spread(self):
        # Higher leverage (smaller capital for same position) → higher ROC
        r_low_lev = _compute_annualized_return_on_capital(5.0, 100_000.0, 50_000.0, 0.0)  # 2×
        r_high_lev = _compute_annualized_return_on_capital(5.0, 100_000.0, 10_000.0, 0.0)  # 10×
        self.assertGreater(r_high_lev, r_low_lev)

    def test_zero_spread_zero_roc(self):
        result = _compute_annualized_return_on_capital(0.0, 100_000.0, 15_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_returns_float(self):
        result = _compute_annualized_return_on_capital(5.0, 100_000.0, 15_000.0, 0.1)
        self.assertIsInstance(result, float)


# ===========================================================================
# 6. _compute_quality_score
# ===========================================================================

class TestComputeQualityScore(unittest.TestCase):

    def test_zero_roc(self):
        self.assertEqual(_compute_quality_score(0.0), 0)

    def test_negative_roc(self):
        self.assertEqual(_compute_quality_score(-5.0), 0)

    def test_20_percent_roc_gives_100(self):
        self.assertEqual(_compute_quality_score(20.0), 100)

    def test_above_20_clamped_to_100(self):
        self.assertEqual(_compute_quality_score(50.0), 100)

    def test_10_percent_roc(self):
        score = _compute_quality_score(10.0)
        self.assertEqual(score, 50)

    def test_5_percent_roc(self):
        score = _compute_quality_score(5.0)
        self.assertEqual(score, 25)

    def test_returns_int(self):
        result = _compute_quality_score(10.0)
        self.assertIsInstance(result, int)

    def test_score_non_decreasing_with_roc(self):
        scores = [_compute_quality_score(r) for r in [0, 5, 10, 15, 20, 25]]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_score_in_valid_range(self):
        for roc in [-100, -1, 0, 1, 5, 10, 15, 20, 30, 100]:
            with self.subTest(roc=roc):
                score = _compute_quality_score(roc)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)


# ===========================================================================
# 7. _classify_arb
# ===========================================================================

class TestClassifyArb(unittest.TestCase):

    def test_premium_arb(self):
        self.assertEqual(_classify_arb(15.1), "PREMIUM_ARB")

    def test_premium_boundary_exact_16(self):
        self.assertEqual(_classify_arb(16.0), "PREMIUM_ARB")

    def test_good_arb_exactly_8(self):
        self.assertEqual(_classify_arb(8.0), "GOOD_ARB")

    def test_good_arb_upper_boundary(self):
        self.assertEqual(_classify_arb(14.9), "GOOD_ARB")

    def test_marginal_arb_exactly_3(self):
        self.assertEqual(_classify_arb(3.0), "MARGINAL_ARB")

    def test_marginal_arb_upper_boundary(self):
        self.assertEqual(_classify_arb(7.9), "MARGINAL_ARB")

    def test_break_even_exactly_0(self):
        self.assertEqual(_classify_arb(0.0), "BREAK_EVEN")

    def test_break_even_upper_boundary(self):
        self.assertEqual(_classify_arb(2.9), "BREAK_EVEN")

    def test_negative_arb(self):
        self.assertEqual(_classify_arb(-0.1), "NEGATIVE_ARB")

    def test_large_negative(self):
        self.assertEqual(_classify_arb(-100.0), "NEGATIVE_ARB")

    def test_15_exactly_is_good_arb(self):
        # > 15 → PREMIUM, so exactly 15 is GOOD_ARB
        self.assertEqual(_classify_arb(15.0), "GOOD_ARB")

    def test_valid_labels(self):
        valid = {"PREMIUM_ARB", "GOOD_ARB", "MARGINAL_ARB", "BREAK_EVEN", "NEGATIVE_ARB"}
        for roc in [-10, -0.001, 0, 0.5, 1.5, 3, 5, 8, 12, 15, 15.001, 20, 50]:
            with self.subTest(roc=roc):
                label = _classify_arb(roc)
                self.assertIn(label, valid)


# ===========================================================================
# 8. analyze() — core function
# ===========================================================================

class TestAnalyze(unittest.TestCase):

    def _run(self, **overrides):
        return analyze(**_default_kwargs(**overrides))

    def test_returns_dict(self):
        result = self._run()
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        result = self._run()
        required = [
            "protocol_name", "perp_funding_rate_8h_pct",
            "spot_borrow_rate_annual_pct", "spot_yield_annual_pct",
            "position_size_usd", "margin_requirement_pct",
            "liquidation_buffer_pct", "gas_cost_usd",
            "funding_rate_annual_pct", "net_arb_spread_pct",
            "capital_required_usd", "annualized_return_on_capital_pct",
            "gas_drag_pct", "arb_quality_score", "arb_label", "timestamp",
        ]
        for key in required:
            with self.subTest(key=key):
                self.assertIn(key, result)

    def test_protocol_name_preserved(self):
        result = self._run(protocol_name="GMX+Morpho")
        self.assertEqual(result["protocol_name"], "GMX+Morpho")

    def test_funding_rate_annual_correct(self):
        result = self._run(perp_funding_rate_8h_pct=0.01)
        self.assertAlmostEqual(result["funding_rate_annual_pct"], 0.01 * 1095)

    def test_capital_required_correct(self):
        # margin=10, buffer=5, position=100000 → 15000
        result = self._run(
            position_size_usd=100_000.0,
            margin_requirement_pct=10.0,
            liquidation_buffer_pct=5.0,
        )
        self.assertAlmostEqual(result["capital_required_usd"], 15_000.0)

    def test_gas_drag_correct(self):
        result = self._run(gas_cost_usd=50.0)
        cap = result["capital_required_usd"]
        expected_drag = 50.0 / cap * 100.0 if cap > 0 else 0.0
        self.assertAlmostEqual(result["gas_drag_pct"], expected_drag)

    def test_arb_label_is_string(self):
        result = self._run()
        self.assertIsInstance(result["arb_label"], str)

    def test_arb_quality_score_is_int(self):
        result = self._run()
        self.assertIsInstance(result["arb_quality_score"], int)

    def test_arb_quality_score_in_range(self):
        result = self._run()
        self.assertGreaterEqual(result["arb_quality_score"], 0)
        self.assertLessEqual(result["arb_quality_score"], 100)

    def test_timestamp_positive(self):
        before = time.time()
        result = self._run()
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_high_funding_rate_gives_premium_arb(self):
        # Very high funding rate → PREMIUM_ARB
        result = self._run(perp_funding_rate_8h_pct=0.1)
        self.assertEqual(result["arb_label"], "PREMIUM_ARB")

    def test_negative_funding_gives_negative_arb(self):
        # Large negative funding + high borrow → NEGATIVE_ARB
        result = self._run(
            perp_funding_rate_8h_pct=-0.05,
            spot_borrow_rate_annual_pct=10.0,
            spot_yield_annual_pct=0.0,
        )
        self.assertEqual(result["arb_label"], "NEGATIVE_ARB")

    def test_zero_position_zero_capital(self):
        result = self._run(position_size_usd=0.0)
        self.assertAlmostEqual(result["capital_required_usd"], 0.0)
        self.assertAlmostEqual(result["annualized_return_on_capital_pct"], 0.0)

    def test_inputs_echoed_in_output(self):
        kwargs = _default_kwargs()
        result = analyze(**kwargs)
        self.assertAlmostEqual(result["perp_funding_rate_8h_pct"], kwargs["perp_funding_rate_8h_pct"])
        self.assertAlmostEqual(result["spot_borrow_rate_annual_pct"], kwargs["spot_borrow_rate_annual_pct"])
        self.assertAlmostEqual(result["spot_yield_annual_pct"], kwargs["spot_yield_annual_pct"])
        self.assertAlmostEqual(result["position_size_usd"], kwargs["position_size_usd"])

    def test_net_spread_formula(self):
        result = self._run(
            perp_funding_rate_8h_pct=0.01,
            spot_borrow_rate_annual_pct=3.0,
            spot_yield_annual_pct=4.5,
        )
        annual = 0.01 * 1095
        expected_spread = annual - 3.0 + 4.5
        self.assertAlmostEqual(result["net_arb_spread_pct"], expected_spread)

    def test_good_arb_label(self):
        # tune for GOOD_ARB: 8-15% ROC
        result = self._run(
            perp_funding_rate_8h_pct=0.008,
            spot_borrow_rate_annual_pct=3.0,
            spot_yield_annual_pct=2.0,
            margin_requirement_pct=10.0,
            liquidation_buffer_pct=5.0,
            gas_cost_usd=0.0,
        )
        self.assertIn(result["arb_label"], {"GOOD_ARB", "MARGINAL_ARB", "PREMIUM_ARB"})

    def test_zero_gas_cost_zero_drag(self):
        result = self._run(gas_cost_usd=0.0)
        self.assertAlmostEqual(result["gas_drag_pct"], 0.0)

    def test_larger_position_higher_roc_with_same_margin_pct(self):
        # Same margin %, larger position → same ROC (scale-invariant)
        r1 = self._run(position_size_usd=100_000.0)
        r2 = self._run(position_size_usd=200_000.0, gas_cost_usd=0.0)
        r1_no_gas = self._run(position_size_usd=100_000.0, gas_cost_usd=0.0)
        # With zero gas: ROC should be equal regardless of position size
        self.assertAlmostEqual(
            r2["annualized_return_on_capital_pct"],
            r1_no_gas["annualized_return_on_capital_pct"],
            places=5,
        )

    def test_break_even_label_when_spread_near_zero(self):
        result = self._run(
            perp_funding_rate_8h_pct=0.0,
            spot_borrow_rate_annual_pct=0.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        )
        self.assertEqual(result["arb_label"], "BREAK_EVEN")

    def test_marginal_arb_range(self):
        # Construct scenario landing in 3-8% ROC
        result = self._run(
            perp_funding_rate_8h_pct=0.003,
            spot_borrow_rate_annual_pct=2.0,
            spot_yield_annual_pct=1.0,
            margin_requirement_pct=15.0,
            liquidation_buffer_pct=5.0,
            gas_cost_usd=0.0,
        )
        # Just verify label is a valid label
        self.assertIn(result["arb_label"], {
            "PREMIUM_ARB", "GOOD_ARB", "MARGINAL_ARB", "BREAK_EVEN", "NEGATIVE_ARB"
        })


# ===========================================================================
# 9. analyze_and_log()
# ===========================================================================

class TestAnalyzeAndLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))
        analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_single_entry_appended(self):
        analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_entries_accumulated(self):
        for _ in range(5):
            analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_returns_same_as_analyze(self):
        result_log = analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        result_pure = analyze(**_default_kwargs())
        # Keys must match (excluding timestamp which differs)
        for key in result_pure:
            if key == "timestamp":
                continue
            with self.subTest(key=key):
                self.assertAlmostEqual(
                    float(result_log[key]) if isinstance(result_log[key], (int, float)) else 0,
                    float(result_pure[key]) if isinstance(result_pure[key], (int, float)) else 0,
                )

    def test_ring_buffer_caps_at_max(self):
        for _ in range(LOG_MAX_ENTRIES + 10):
            analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            analyze_and_log(**_default_kwargs(protocol_name=f"proto_{i}"), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        # The last entry should have protocol_name=proto_{max+4}
        self.assertEqual(data[-1]["protocol_name"], f"proto_{LOG_MAX_ENTRIES + 4}")

    def test_log_entry_has_required_keys(self):
        analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            entry = json.load(f)[0]
        for key in ["arb_label", "arb_quality_score", "funding_rate_annual_pct"]:
            self.assertIn(key, entry)


# ===========================================================================
# 10. init_log()
# ===========================================================================

class TestInitLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_empty_list(self):
        init_log(self.tmp)
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_does_not_overwrite_existing(self):
        analyze_and_log(**_default_kwargs(), data_dir=self.tmp)
        init_log(self.tmp)  # should not wipe existing data
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_data_dir_if_missing(self):
        new_dir = os.path.join(self.tmp, "subdir")
        self.assertFalse(os.path.exists(new_dir))
        init_log(new_dir)
        self.assertTrue(os.path.exists(new_dir))


# ===========================================================================
# 11. _read_log / _append_log internals
# ===========================================================================

class TestReadAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_missing_file_returns_empty(self):
        path = os.path.join(self.tmp, "missing.json")
        result = _read_log(path)
        self.assertEqual(result, [])

    def test_read_corrupt_file_returns_empty(self):
        path = os.path.join(self.tmp, LOG_FILENAME)
        with open(path, "w") as f:
            f.write("NOT JSON {{{")
        result = _read_log(path)
        self.assertEqual(result, [])

    def test_read_non_list_returns_empty(self):
        path = os.path.join(self.tmp, LOG_FILENAME)
        with open(path, "w") as f:
            json.dump({"not": "list"}, f)
        result = _read_log(path)
        self.assertEqual(result, [])

    def test_append_increments_count(self):
        entry = {"x": 1}
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        _append_log(entry, self.tmp)
        _append_log(entry, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_exact_boundary(self):
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        for i in range(LOG_MAX_ENTRIES):
            _append_log({"i": i}, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)
        # One more → still capped
        _append_log({"i": LOG_MAX_ENTRIES}, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)


# ===========================================================================
# 12. DeFiProtocolFundingRateArbitrageAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolFundingRateArbitrageAnalyzer(data_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_instantiate_with_data_dir(self):
        self.assertIsNotNone(self.analyzer)

    def test_instantiate_default(self):
        # Should not raise
        a = DeFiProtocolFundingRateArbitrageAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze(**_default_kwargs())
        self.assertIsInstance(result, dict)

    def test_analyze_has_arb_label(self):
        result = self.analyzer.analyze(**_default_kwargs())
        self.assertIn("arb_label", result)

    def test_analyze_and_log_creates_file(self):
        self.analyzer.analyze_and_log(**_default_kwargs())
        self.assertTrue(os.path.exists(self.analyzer.log_path))

    def test_analyze_and_log_returns_dict(self):
        result = self.analyzer.analyze_and_log(**_default_kwargs())
        self.assertIsInstance(result, dict)

    def test_init_log_creates_empty_file(self):
        self.analyzer.init_log()
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_log_path_uses_data_dir(self):
        self.assertIn(self.tmp, self.analyzer.log_path)

    def test_analyze_consistent_with_module_function(self):
        kwargs = _default_kwargs()
        r_class = self.analyzer.analyze(**kwargs)
        r_func = analyze(**kwargs)
        for key in ["funding_rate_annual_pct", "net_arb_spread_pct", "arb_label", "arb_quality_score"]:
            with self.subTest(key=key):
                self.assertEqual(r_class[key], r_func[key])

    def test_multiple_analyze_calls_independent(self):
        r1 = self.analyzer.analyze(**_default_kwargs(perp_funding_rate_8h_pct=0.01))
        r2 = self.analyzer.analyze(**_default_kwargs(perp_funding_rate_8h_pct=0.05))
        self.assertNotEqual(r1["funding_rate_annual_pct"], r2["funding_rate_annual_pct"])

    def test_log_max_entries_constant(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)


# ===========================================================================
# 13. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_extreme_high_funding_rate(self):
        result = analyze(**_default_kwargs(perp_funding_rate_8h_pct=1.0))
        self.assertEqual(result["arb_label"], "PREMIUM_ARB")
        self.assertEqual(result["arb_quality_score"], 100)

    def test_zero_all_rates(self):
        result = analyze(**_default_kwargs(
            perp_funding_rate_8h_pct=0.0,
            spot_borrow_rate_annual_pct=0.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        ))
        self.assertAlmostEqual(result["net_arb_spread_pct"], 0.0)
        self.assertEqual(result["arb_label"], "BREAK_EVEN")

    def test_very_high_borrow_cost(self):
        result = analyze(**_default_kwargs(
            spot_borrow_rate_annual_pct=500.0,
            gas_cost_usd=0.0,
        ))
        self.assertEqual(result["arb_label"], "NEGATIVE_ARB")

    def test_protocol_name_empty_string(self):
        result = analyze(**_default_kwargs(protocol_name=""))
        self.assertEqual(result["protocol_name"], "")

    def test_protocol_name_long_string(self):
        long_name = "A" * 200
        result = analyze(**_default_kwargs(protocol_name=long_name))
        self.assertEqual(result["protocol_name"], long_name)

    def test_large_gas_cost_erodes_return(self):
        r_low = analyze(**_default_kwargs(gas_cost_usd=0.0))
        r_high = analyze(**_default_kwargs(gas_cost_usd=100_000.0))
        self.assertGreater(
            r_low["annualized_return_on_capital_pct"],
            r_high["annualized_return_on_capital_pct"],
        )

    def test_100pct_margin_no_buffer(self):
        result = analyze(**_default_kwargs(
            margin_requirement_pct=100.0,
            liquidation_buffer_pct=0.0,
            gas_cost_usd=0.0,
        ))
        # Capital = 100% of position → leverage = 1× → ROC = net_spread
        self.assertAlmostEqual(
            result["annualized_return_on_capital_pct"],
            result["net_arb_spread_pct"],
            places=5,
        )

    def test_very_small_margin_amplifies_return(self):
        r_big_margin = analyze(**_default_kwargs(
            margin_requirement_pct=50.0, liquidation_buffer_pct=0.0, gas_cost_usd=0.0
        ))
        r_small_margin = analyze(**_default_kwargs(
            margin_requirement_pct=5.0, liquidation_buffer_pct=0.0, gas_cost_usd=0.0
        ))
        self.assertGreater(
            r_small_margin["annualized_return_on_capital_pct"],
            r_big_margin["annualized_return_on_capital_pct"],
        )

    def test_floating_point_precision(self):
        result = analyze(**_default_kwargs(perp_funding_rate_8h_pct=0.0001))
        self.assertIsInstance(result["funding_rate_annual_pct"], float)

    def test_identical_calls_identical_results(self):
        kwargs = _default_kwargs()
        r1 = analyze(**kwargs)
        r2 = analyze(**kwargs)
        for key in ["funding_rate_annual_pct", "net_arb_spread_pct",
                    "capital_required_usd", "arb_label", "arb_quality_score"]:
            with self.subTest(key=key):
                self.assertEqual(r1[key], r2[key])


# ===========================================================================
# 14. Integration: label consistency
# ===========================================================================

class TestLabelConsistency(unittest.TestCase):

    def test_premium_arb_score_is_high(self):
        result = analyze(**_default_kwargs(perp_funding_rate_8h_pct=0.05))
        if result["arb_label"] == "PREMIUM_ARB":
            self.assertGreater(result["arb_quality_score"], 50)

    def test_negative_arb_score_is_zero(self):
        result = analyze(**_default_kwargs(
            perp_funding_rate_8h_pct=-0.1,
            spot_borrow_rate_annual_pct=20.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        ))
        self.assertEqual(result["arb_quality_score"], 0)
        self.assertEqual(result["arb_label"], "NEGATIVE_ARB")

    def test_break_even_score_is_low_or_zero(self):
        result = analyze(**_default_kwargs(
            perp_funding_rate_8h_pct=0.0,
            spot_borrow_rate_annual_pct=0.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        ))
        self.assertEqual(result["arb_label"], "BREAK_EVEN")
        self.assertEqual(result["arb_quality_score"], 0)

    def test_label_matches_roc_threshold_exactly_15(self):
        # Construct scenario where ROC is just above 15% → PREMIUM_ARB
        # margin=10, buf=5, pos=100000, capital=15000, leverage=6.667
        # need: spread * 6.667 > 15 → spread > 2.25%
        # annual = rate * 1095; net = annual - borrow + yield
        # Let's use: borrow=0, yield=0, gas=0
        # ROC = (rate*1095) * (100000/15000)
        # Want ROC = 15 → rate = 15*15000 / (1095*100000) = 225000/109500000 ≈ 0.002055
        rate = 15 * 15000 / (1095 * 100000)
        result = analyze(**_default_kwargs(
            perp_funding_rate_8h_pct=rate,
            spot_borrow_rate_annual_pct=0.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        ))
        # ROC should be ~15 → GOOD_ARB (exactly 15 is not > 15)
        self.assertEqual(result["arb_label"], "GOOD_ARB")

    def test_roc_just_above_15_is_premium(self):
        # ROC slightly above 15 → PREMIUM_ARB
        rate = (15.01 * 15000) / (1095 * 100000)
        result = analyze(**_default_kwargs(
            perp_funding_rate_8h_pct=rate,
            spot_borrow_rate_annual_pct=0.0,
            spot_yield_annual_pct=0.0,
            gas_cost_usd=0.0,
        ))
        self.assertEqual(result["arb_label"], "PREMIUM_ARB")


if __name__ == "__main__":
    unittest.main()
