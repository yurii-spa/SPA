"""
Tests for MP-1080: DeFiProtocolTreasuryDiversificationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_treasury_diversification_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.defi_protocol_treasury_diversification_analyzer import (
    DeFiProtocolTreasuryDiversificationAnalyzer,
    _clamp,
    _compute_total_treasury,
    _compute_runway_months,
    _compute_stablecoin_ratio,
    _compute_native_token_ratio,
    _compute_hhi,
    _compute_diversification_label,
    _compute_vesting_pressure,
    _compute_revenue_coverage,
    _validate_holdings,
    _analyze_single,
    _atomic_write,
    _append_log,
    LOG_CAP,
    VALID_ASSET_TYPES,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_holdings(*specs):
    """specs: list of (asset, value_usd, asset_type)"""
    return [{"asset": a, "value_usd": v, "asset_type": t} for a, v, t in specs]


def make_data(**overrides):
    base = {
        "protocol_name": "TestProtocol",
        "treasury_holdings": make_holdings(
            ("USDC", 5_000_000, "stablecoin"),
            ("ETH",  3_000_000, "eth"),
            ("TKN",  2_000_000, "native_token"),
        ),
        "monthly_burn_usd": 500_000,
        "revenue_usd_per_month": 300_000,
        "vesting_unlocks_6m_usd": 1_000_000,
    }
    base.update(overrides)
    return base


# ── _clamp ─────────────────────────────────────────────────────────────────────

class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_below_min(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_above_max(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_exact_min(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_exact_max(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 10.0, 90.0), 10.0)

    def test_custom_bounds_high(self):
        self.assertEqual(_clamp(95.0, 10.0, 90.0), 90.0)


# ── _compute_total_treasury ───────────────────────────────────────────────────

class TestComputeTotalTreasury(unittest.TestCase):

    def test_basic_sum(self):
        h = make_holdings(("USDC", 1000, "stablecoin"), ("ETH", 2000, "eth"))
        self.assertEqual(_compute_total_treasury(h), 3000.0)

    def test_empty_list(self):
        self.assertEqual(_compute_total_treasury([]), 0.0)

    def test_single_holding(self):
        h = make_holdings(("BTC", 50000, "btc"))
        self.assertEqual(_compute_total_treasury(h), 50000.0)

    def test_missing_value_defaults_zero(self):
        h = [{"asset": "X", "asset_type": "other_crypto"}]
        self.assertEqual(_compute_total_treasury(h), 0.0)

    def test_float_precision(self):
        h = make_holdings(("A", 1.1, "stablecoin"), ("B", 2.2, "eth"))
        total = _compute_total_treasury(h)
        self.assertAlmostEqual(total, 3.3, places=5)


# ── _compute_runway_months ────────────────────────────────────────────────────

class TestComputeRunwayMonths(unittest.TestCase):

    def test_basic_runway(self):
        self.assertEqual(_compute_runway_months(10_000_000, 500_000), 20.0)

    def test_zero_burn(self):
        result = _compute_runway_months(5_000_000, 0)
        self.assertEqual(result, float("inf"))

    def test_negative_burn_treated_as_zero(self):
        result = _compute_runway_months(5_000_000, -100)
        self.assertEqual(result, float("inf"))

    def test_exact_one_month(self):
        self.assertEqual(_compute_runway_months(1_000_000, 1_000_000), 1.0)

    def test_fractional_runway(self):
        result = _compute_runway_months(500_000, 200_000)
        self.assertAlmostEqual(result, 2.5, places=2)

    def test_large_burn_small_treasury(self):
        result = _compute_runway_months(100_000, 1_000_000)
        self.assertAlmostEqual(result, 0.1, places=2)


# ── _compute_stablecoin_ratio ─────────────────────────────────────────────────

class TestComputeStablecoinRatio(unittest.TestCase):

    def test_all_stablecoins(self):
        h = make_holdings(("USDC", 1000, "stablecoin"), ("DAI", 1000, "stablecoin"))
        self.assertAlmostEqual(_compute_stablecoin_ratio(h, 2000), 100.0)

    def test_no_stablecoins(self):
        h = make_holdings(("ETH", 5000, "eth"))
        self.assertEqual(_compute_stablecoin_ratio(h, 5000), 0.0)

    def test_mixed_50_50(self):
        h = make_holdings(("USDC", 500, "stablecoin"), ("ETH", 500, "eth"))
        self.assertAlmostEqual(_compute_stablecoin_ratio(h, 1000), 50.0)

    def test_zero_total(self):
        self.assertEqual(_compute_stablecoin_ratio([], 0), 0.0)

    def test_partial_stablecoin(self):
        h = make_holdings(
            ("USDC", 300, "stablecoin"),
            ("ETH", 500, "eth"),
            ("TKN", 200, "native_token"),
        )
        ratio = _compute_stablecoin_ratio(h, 1000)
        self.assertAlmostEqual(ratio, 30.0, places=2)


# ── _compute_native_token_ratio ───────────────────────────────────────────────

class TestComputeNativeTokenRatio(unittest.TestCase):

    def test_all_native(self):
        h = make_holdings(("TKN", 1000, "native_token"))
        self.assertAlmostEqual(_compute_native_token_ratio(h, 1000), 100.0)

    def test_no_native(self):
        h = make_holdings(("USDC", 1000, "stablecoin"))
        self.assertEqual(_compute_native_token_ratio(h, 1000), 0.0)

    def test_partial_native(self):
        h = make_holdings(("TKN", 600, "native_token"), ("ETH", 400, "eth"))
        ratio = _compute_native_token_ratio(h, 1000)
        self.assertAlmostEqual(ratio, 60.0)

    def test_zero_total_returns_zero(self):
        self.assertEqual(_compute_native_token_ratio([], 0), 0.0)

    def test_multiple_native_aggregated(self):
        h = make_holdings(
            ("TKN1", 300, "native_token"),
            ("TKN2", 200, "native_token"),
            ("ETH", 500, "eth"),
        )
        ratio = _compute_native_token_ratio(h, 1000)
        self.assertAlmostEqual(ratio, 50.0)


# ── _compute_hhi ──────────────────────────────────────────────────────────────

class TestComputeHHI(unittest.TestCase):

    def test_single_asset_type_max_hhi(self):
        h = make_holdings(("USDC", 1000, "stablecoin"))
        hhi = _compute_hhi(h, 1000)
        self.assertAlmostEqual(hhi, 100.0)

    def test_two_equal_types(self):
        h = make_holdings(("USDC", 500, "stablecoin"), ("ETH", 500, "eth"))
        hhi = _compute_hhi(h, 1000)
        # raw HHI = 2 * (0.5^2) * 10000 = 5000 → /100 = 50
        self.assertAlmostEqual(hhi, 50.0)

    def test_four_equal_types(self):
        h = make_holdings(
            ("USDC", 250, "stablecoin"),
            ("ETH", 250, "eth"),
            ("BTC", 250, "btc"),
            ("TKN", 250, "native_token"),
        )
        hhi = _compute_hhi(h, 1000)
        # raw HHI = 4 * (0.25^2) * 10000 = 2500 → /100 = 25
        self.assertAlmostEqual(hhi, 25.0)

    def test_empty_holdings_returns_max(self):
        self.assertEqual(_compute_hhi([], 0), 100.0)

    def test_zero_total_returns_max(self):
        h = make_holdings(("USDC", 0, "stablecoin"))
        self.assertEqual(_compute_hhi(h, 0), 100.0)

    def test_hhi_bounded_0_to_100(self):
        h = make_holdings(("A", 999, "native_token"), ("B", 1, "stablecoin"))
        hhi = _compute_hhi(h, 1000)
        self.assertGreaterEqual(hhi, 0.0)
        self.assertLessEqual(hhi, 100.0)

    def test_same_type_aggregated(self):
        # Two stablecoin entries = 100% stablecoin → HHI = 100
        h = make_holdings(("USDC", 500, "stablecoin"), ("DAI", 500, "stablecoin"))
        hhi = _compute_hhi(h, 1000)
        self.assertAlmostEqual(hhi, 100.0)

    def test_highly_diversified_low_hhi(self):
        # 6 equal types → raw 6*(1/6)^2*10000 = 1666.7 → /100 ≈ 16.67
        h = make_holdings(
            ("USDC", 100, "stablecoin"),
            ("ETH", 100, "eth"),
            ("BTC", 100, "btc"),
            ("TKN", 100, "native_token"),
            ("RWA", 100, "rwa"),
            ("ALT", 100, "other_crypto"),
        )
        hhi = _compute_hhi(h, 600)
        self.assertLess(hhi, 20.0)


# ── _compute_diversification_label ───────────────────────────────────────────

class TestComputeDiversificationLabel(unittest.TestCase):

    def test_runway_critical_overrides_all(self):
        label = _compute_diversification_label(5.0, 10.0, 6.0, 50.0)
        self.assertEqual(label, "RUNWAY_CRITICAL")

    def test_native_heavy_overrides_hhi(self):
        label = _compute_diversification_label(10.0, 80.0, 24.0, 5.0)
        self.assertEqual(label, "NATIVE_TOKEN_HEAVY")

    def test_concentrated(self):
        label = _compute_diversification_label(70.0, 10.0, 24.0, 20.0)
        self.assertEqual(label, "CONCENTRATED")

    def test_adequate(self):
        label = _compute_diversification_label(35.0, 10.0, 24.0, 30.0)
        self.assertEqual(label, "ADEQUATE")

    def test_well_diversified(self):
        label = _compute_diversification_label(15.0, 10.0, 24.0, 40.0)
        self.assertEqual(label, "WELL_DIVERSIFIED")

    def test_exactly_12_months_not_critical(self):
        # runway == 12 is NOT < 12 → not RUNWAY_CRITICAL
        label = _compute_diversification_label(70.0, 10.0, 12.0, 20.0)
        self.assertNotEqual(label, "RUNWAY_CRITICAL")

    def test_11_months_is_critical(self):
        label = _compute_diversification_label(5.0, 5.0, 11.0, 50.0)
        self.assertEqual(label, "RUNWAY_CRITICAL")

    def test_native_at_60_not_heavy(self):
        # exactly 60 → NOT > 60 → not NATIVE_TOKEN_HEAVY
        label = _compute_diversification_label(10.0, 60.0, 24.0, 10.0)
        self.assertNotEqual(label, "NATIVE_TOKEN_HEAVY")

    def test_native_at_61_is_heavy(self):
        label = _compute_diversification_label(10.0, 61.0, 24.0, 10.0)
        self.assertEqual(label, "NATIVE_TOKEN_HEAVY")


# ── _compute_vesting_pressure ─────────────────────────────────────────────────

class TestComputeVestingPressure(unittest.TestCase):

    def test_no_vesting(self):
        self.assertEqual(_compute_vesting_pressure(0, 1_000_000), 0.0)

    def test_vesting_half_treasury(self):
        self.assertAlmostEqual(_compute_vesting_pressure(500_000, 1_000_000), 0.5)

    def test_vesting_exceeds_treasury_capped_at_1(self):
        result = _compute_vesting_pressure(2_000_000, 1_000_000)
        self.assertEqual(result, 1.0)

    def test_zero_total(self):
        self.assertEqual(_compute_vesting_pressure(100_000, 0), 0.0)

    def test_small_vesting_fraction(self):
        result = _compute_vesting_pressure(100_000, 10_000_000)
        self.assertAlmostEqual(result, 0.01)


# ── _compute_revenue_coverage ─────────────────────────────────────────────────

class TestComputeRevenueCoverage(unittest.TestCase):

    def test_profitable(self):
        # revenue 600k, burn 400k → 1.5x coverage
        result = _compute_revenue_coverage(600_000, 400_000)
        self.assertAlmostEqual(result, 1.5)

    def test_zero_burn(self):
        result = _compute_revenue_coverage(100_000, 0)
        self.assertEqual(result, 10.0)  # capped at 10

    def test_revenue_exceeds_cap(self):
        result = _compute_revenue_coverage(1_000_000, 10_000)
        self.assertEqual(result, 10.0)

    def test_zero_revenue(self):
        result = _compute_revenue_coverage(0, 500_000)
        self.assertEqual(result, 0.0)

    def test_break_even(self):
        result = _compute_revenue_coverage(500_000, 500_000)
        self.assertEqual(result, 1.0)


# ── _validate_holdings ────────────────────────────────────────────────────────

class TestValidateHoldings(unittest.TestCase):

    def test_valid_holdings_pass_through(self):
        h = make_holdings(("USDC", 1000, "stablecoin"), ("ETH", 500, "eth"))
        result = _validate_holdings(h)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["asset_type"], "stablecoin")

    def test_invalid_asset_type_mapped_to_other(self):
        h = [{"asset": "WEIRD", "value_usd": 100, "asset_type": "mystery"}]
        result = _validate_holdings(h)
        self.assertEqual(result[0]["asset_type"], "other_crypto")

    def test_negative_value_clamped_to_zero(self):
        h = [{"asset": "BAD", "value_usd": -500, "asset_type": "eth"}]
        result = _validate_holdings(h)
        self.assertEqual(result[0]["value_usd"], 0.0)

    def test_missing_value_defaults_zero(self):
        h = [{"asset": "X", "asset_type": "btc"}]
        result = _validate_holdings(h)
        self.assertEqual(result[0]["value_usd"], 0.0)

    def test_missing_asset_type_mapped_to_other(self):
        h = [{"asset": "X", "value_usd": 100}]
        result = _validate_holdings(h)
        self.assertEqual(result[0]["asset_type"], "other_crypto")

    def test_all_valid_asset_types_accepted(self):
        for atype in VALID_ASSET_TYPES:
            h = [{"asset": "X", "value_usd": 100, "asset_type": atype}]
            result = _validate_holdings(h)
            self.assertEqual(result[0]["asset_type"], atype)

    def test_empty_list(self):
        self.assertEqual(_validate_holdings([]), [])

    def test_uppercase_asset_type_normalised(self):
        h = [{"asset": "ETH", "value_usd": 100, "asset_type": "ETH"}]
        result = _validate_holdings(h)
        self.assertEqual(result[0]["asset_type"], "eth")


# ── _analyze_single ──────────────────────────────────────────────────────────

class TestAnalyzeSingle(unittest.TestCase):

    def test_output_keys_present(self):
        result = _analyze_single(make_data())
        for key in [
            "protocol_name", "total_treasury_usd", "runway_months",
            "stablecoin_ratio_pct", "native_token_ratio_pct",
            "hhi_concentration_score", "diversification_label",
            "vesting_pressure_ratio", "revenue_coverage_ratio", "holding_count",
        ]:
            self.assertIn(key, result)

    def test_protocol_name_passed_through(self):
        result = _analyze_single(make_data(protocol_name="AaveDAO"))
        self.assertEqual(result["protocol_name"], "AaveDAO")

    def test_total_treasury_correct(self):
        result = _analyze_single(make_data())
        self.assertAlmostEqual(result["total_treasury_usd"], 10_000_000)

    def test_runway_correct(self):
        result = _analyze_single(make_data(monthly_burn_usd=1_000_000))
        self.assertAlmostEqual(result["runway_months"], 10.0)

    def test_runway_none_when_no_burn(self):
        result = _analyze_single(make_data(monthly_burn_usd=0))
        self.assertIsNone(result["runway_months"])

    def test_holding_count(self):
        result = _analyze_single(make_data())
        self.assertEqual(result["holding_count"], 3)

    def test_empty_holdings(self):
        result = _analyze_single(make_data(treasury_holdings=[]))
        self.assertEqual(result["total_treasury_usd"], 0.0)

    def test_stablecoin_ratio_in_range(self):
        result = _analyze_single(make_data())
        self.assertGreaterEqual(result["stablecoin_ratio_pct"], 0.0)
        self.assertLessEqual(result["stablecoin_ratio_pct"], 100.0)

    def test_native_token_ratio_in_range(self):
        result = _analyze_single(make_data())
        self.assertGreaterEqual(result["native_token_ratio_pct"], 0.0)
        self.assertLessEqual(result["native_token_ratio_pct"], 100.0)

    def test_hhi_in_range(self):
        result = _analyze_single(make_data())
        self.assertGreaterEqual(result["hhi_concentration_score"], 0.0)
        self.assertLessEqual(result["hhi_concentration_score"], 100.0)

    def test_diversification_label_valid(self):
        valid = {"WELL_DIVERSIFIED", "ADEQUATE", "CONCENTRATED",
                 "NATIVE_TOKEN_HEAVY", "RUNWAY_CRITICAL"}
        result = _analyze_single(make_data())
        self.assertIn(result["diversification_label"], valid)

    def test_critical_runway_label(self):
        # 10 months runway → RUNWAY_CRITICAL
        result = _analyze_single(make_data(monthly_burn_usd=1_100_000))
        self.assertEqual(result["diversification_label"], "RUNWAY_CRITICAL")

    def test_native_heavy_label(self):
        h = make_holdings(("TKN", 900_000, "native_token"), ("USDC", 100_000, "stablecoin"))
        result = _analyze_single(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,  # long runway
        ))
        self.assertEqual(result["diversification_label"], "NATIVE_TOKEN_HEAVY")

    def test_well_diversified_label(self):
        h = make_holdings(
            ("USDC", 200_000, "stablecoin"),
            ("ETH",  200_000, "eth"),
            ("BTC",  200_000, "btc"),
            ("TKN",  200_000, "native_token"),
            ("RWA",  100_000, "rwa"),
            ("ALT",  100_000, "other_crypto"),
        )
        result = _analyze_single(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,
        ))
        self.assertEqual(result["diversification_label"], "WELL_DIVERSIFIED")

    def test_invalid_holdings_not_a_list(self):
        result = _analyze_single(make_data(treasury_holdings=None))
        self.assertEqual(result["total_treasury_usd"], 0.0)

    def test_missing_protocol_name_defaults(self):
        d = make_data()
        del d["protocol_name"]
        result = _analyze_single(d)
        self.assertEqual(result["protocol_name"], "UNKNOWN")

    def test_vesting_pressure_ratio_in_range(self):
        result = _analyze_single(make_data())
        self.assertGreaterEqual(result["vesting_pressure_ratio"], 0.0)
        self.assertLessEqual(result["vesting_pressure_ratio"], 1.0)

    def test_revenue_coverage_ratio_in_range(self):
        result = _analyze_single(make_data())
        self.assertGreaterEqual(result["revenue_coverage_ratio"], 0.0)
        self.assertLessEqual(result["revenue_coverage_ratio"], 10.0)


# ── _atomic_write ─────────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "value")

    def test_writes_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "out.json")
            _atomic_write(path, {})
            self.assertTrue(os.path.exists(path))

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["v"], 2)


# ── _append_log ───────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def _make_result(self, label="WELL_DIVERSIFIED"):
        return {
            "protocol_name": "Test",
            "total_treasury_usd": 1_000_000,
            "runway_months": 20.0,
            "hhi_concentration_score": 20.0,
            "diversification_label": label,
        }

    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._make_result(), path)
            self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._make_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._make_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_multiple_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                _append_log(self._make_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(LOG_CAP + 10):
                _append_log(self._make_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), LOG_CAP)

    def test_recovers_from_corrupt_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                f.write("NOT JSON {{{{")
            _append_log(self._make_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_log_entry_contains_label(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._make_result("CONCENTRATED"), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["diversification_label"], "CONCENTRATED")


# ── DeFiProtocolTreasuryDiversificationAnalyzer (main class) ──────────────────

class TestDeFiProtocolTreasuryDiversificationAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolTreasuryDiversificationAnalyzer()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")
        self.cfg = {"log_path": self.log_path, "write_log": True}

    def test_returns_dict(self):
        result = self.analyzer.analyze(make_data(), self.cfg)
        self.assertIsInstance(result, dict)

    def test_raises_on_non_dict(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not a dict", self.cfg)

    def test_basic_output_keys(self):
        result = self.analyzer.analyze(make_data(), self.cfg)
        for key in ["total_treasury_usd", "runway_months", "stablecoin_ratio_pct",
                    "native_token_ratio_pct", "hhi_concentration_score",
                    "diversification_label"]:
            self.assertIn(key, result)

    def test_no_write_log_skips_file(self):
        cfg = {"log_path": self.log_path, "write_log": False}
        self.analyzer.analyze(make_data(), cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_write_log_creates_file(self):
        self.analyzer.analyze(make_data(), self.cfg)
        self.assertTrue(os.path.exists(self.log_path))

    def test_multiple_calls_accumulate_log(self):
        for _ in range(3):
            self.analyzer.analyze(make_data(), self.cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_well_diversified_protocol(self):
        h = make_holdings(
            ("USDC", 250_000, "stablecoin"),
            ("ETH",  250_000, "eth"),
            ("BTC",  250_000, "btc"),
            ("TKN",  250_000, "native_token"),
        )
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=5_000,
        ), self.cfg)
        self.assertEqual(result["diversification_label"], "WELL_DIVERSIFIED")

    def test_runway_critical_protocol(self):
        # small treasury, large burn → <12 months
        result = self.analyzer.analyze(make_data(
            monthly_burn_usd=2_000_000,
        ), self.cfg)
        self.assertEqual(result["diversification_label"], "RUNWAY_CRITICAL")

    def test_native_heavy_protocol(self):
        h = make_holdings(
            ("GOV", 9_000_000, "native_token"),
            ("USDC", 1_000_000, "stablecoin"),
        )
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=50_000,
        ), self.cfg)
        self.assertEqual(result["diversification_label"], "NATIVE_TOKEN_HEAVY")

    def test_concentrated_protocol(self):
        # two equal types → HHI=50 → CONCENTRATED
        h = make_holdings(("USDC", 5_000, "stablecoin"), ("ETH", 5_000, "eth"))
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=100,
        ), self.cfg)
        self.assertIn(result["diversification_label"], {"CONCENTRATED", "ADEQUATE"})

    def test_stablecoin_ratio_all_stable(self):
        h = make_holdings(("USDC", 1_000_000, "stablecoin"))
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,
        ), self.cfg)
        self.assertAlmostEqual(result["stablecoin_ratio_pct"], 100.0)

    def test_vesting_pressure_high(self):
        result = self.analyzer.analyze(make_data(
            vesting_unlocks_6m_usd=9_000_000,
        ), self.cfg)
        self.assertGreater(result["vesting_pressure_ratio"], 0.5)

    def test_revenue_coverage_above_1_when_profitable(self):
        result = self.analyzer.analyze(make_data(
            monthly_burn_usd=300_000,
            revenue_usd_per_month=600_000,
        ), self.cfg)
        self.assertGreater(result["revenue_coverage_ratio"], 1.0)

    def test_empty_config_uses_defaults(self):
        result = self.analyzer.analyze(make_data(), {})
        self.assertIn("diversification_label", result)

    def test_none_config_uses_defaults(self):
        result = self.analyzer.analyze(make_data())
        self.assertIn("diversification_label", result)

    def test_large_treasury(self):
        h = make_holdings(
            ("USDC", 50_000_000, "stablecoin"),
            ("ETH",  30_000_000, "eth"),
            ("BTC",  20_000_000, "btc"),
        )
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=500_000,
        ), self.cfg)
        self.assertAlmostEqual(result["total_treasury_usd"], 100_000_000)

    def test_rwa_asset_type_accepted(self):
        h = make_holdings(
            ("T-BILL", 5_000_000, "rwa"),
            ("USDC",   5_000_000, "stablecoin"),
        )
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,
        ), self.cfg)
        self.assertAlmostEqual(result["total_treasury_usd"], 10_000_000)

    def test_other_crypto_asset_type_accepted(self):
        h = make_holdings(
            ("ALT", 5_000_000, "other_crypto"),
            ("USDC", 5_000_000, "stablecoin"),
        )
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,
        ), self.cfg)
        self.assertAlmostEqual(result["total_treasury_usd"], 10_000_000)

    def test_hhi_score_single_type_is_100(self):
        h = make_holdings(("USDC", 10_000_000, "stablecoin"))
        result = self.analyzer.analyze(make_data(
            treasury_holdings=h,
            monthly_burn_usd=10_000,
        ), self.cfg)
        self.assertAlmostEqual(result["hhi_concentration_score"], 100.0)

    def test_protocol_name_in_result(self):
        result = self.analyzer.analyze(make_data(protocol_name="Compound"), self.cfg)
        self.assertEqual(result["protocol_name"], "Compound")

    def test_holding_count_matches_input(self):
        result = self.analyzer.analyze(make_data(), self.cfg)
        self.assertEqual(result["holding_count"], 3)


if __name__ == "__main__":
    unittest.main()
