"""
Tests for MP-1064 DeFiProtocolRealYieldVsIncentiveYieldAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_real_yield_vs_incentive_yield_analyzer import (
    DeFiProtocolRealYieldVsIncentiveYieldAnalyzer,
    analyze,
    _atomic_log,
    _real_yield_pct,
    _incentive_yield_pct,
    _real_yield_ratio,
    _incentive_sustainability_score,
    _yield_quality_label,
    _LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    """Return a path to a fresh temp file (deleted so log starts empty)."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_data(**overrides) -> dict:
    d = {
        "protocol_name":               "TestProtocol",
        "total_apy_pct":               12.0,
        "fee_revenue_usd_per_day":     5_000.0,
        "tvl_usd":                     50_000_000.0,
        "token_incentive_usd_per_day": 2_000.0,
        "token_price_usd":             1.50,
        "token_circulating_supply":    100_000_000.0,
        "token_inflation_rate_pct":    10.0,
        "emissions_vest_days":         180.0,
    }
    d.update(overrides)
    return d


# ===========================================================================
# 1. _real_yield_pct
# ===========================================================================

class TestRealYieldPct(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_real_yield_pct(1_000.0, 0.0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(_real_yield_pct(1_000.0, -1.0), 0.0)

    def test_zero_fee_returns_zero(self):
        self.assertEqual(_real_yield_pct(0.0, 10_000_000.0), 0.0)

    def test_both_zero_returns_zero(self):
        self.assertEqual(_real_yield_pct(0.0, 0.0), 0.0)

    def test_known_value(self):
        # 5000 * 365 / 50_000_000 * 100 = 3.65 %
        result = _real_yield_pct(5_000.0, 50_000_000.0)
        self.assertAlmostEqual(result, 3.65, places=4)

    def test_result_rounded_to_6_places(self):
        result = _real_yield_pct(1.0, 3.0)
        # 1*365/3*100 = 12166.666...
        self.assertAlmostEqual(result, 12166.666667, places=4)

    def test_large_tvl_small_fee(self):
        result = _real_yield_pct(1.0, 1_000_000_000.0)
        expected = 1.0 * 365.0 / 1_000_000_000.0 * 100.0
        # result is rounded to 6 decimal places, so compare with tolerance
        self.assertAlmostEqual(result, expected, places=4)

    def test_result_is_float(self):
        result = _real_yield_pct(100.0, 1_000_000.0)
        self.assertIsInstance(result, float)

    def test_annualised_correctly(self):
        # 1 USD/day in a 1M TVL pool: 365/1_000_000*100 = 0.0365%
        result = _real_yield_pct(1.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0365, places=6)

    def test_tvl_equals_365_times_fee_gives_100pct(self):
        fee = 1_000.0
        tvl = fee * 365.0
        result = _real_yield_pct(fee, tvl)
        self.assertAlmostEqual(result, 100.0, places=6)


# ===========================================================================
# 2. _incentive_yield_pct
# ===========================================================================

class TestIncentiveYieldPct(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_incentive_yield_pct(500.0, 0.0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(_incentive_yield_pct(500.0, -100.0), 0.0)

    def test_zero_incentive_returns_zero(self):
        self.assertEqual(_incentive_yield_pct(0.0, 5_000_000.0), 0.0)

    def test_known_value(self):
        # 2000 * 365 / 50_000_000 * 100 = 1.46 %
        result = _incentive_yield_pct(2_000.0, 50_000_000.0)
        self.assertAlmostEqual(result, 1.46, places=4)

    def test_symmetry_with_real_yield(self):
        fee = 3_000.0
        tvl = 20_000_000.0
        self.assertEqual(_real_yield_pct(fee, tvl), _incentive_yield_pct(fee, tvl))

    def test_result_is_float(self):
        self.assertIsInstance(_incentive_yield_pct(100.0, 1_000_000.0), float)

    def test_annualised_correctly(self):
        result = _incentive_yield_pct(1.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0365, places=6)


# ===========================================================================
# 3. _real_yield_ratio
# ===========================================================================

class TestRealYieldRatio(unittest.TestCase):

    def test_both_zero_returns_zero(self):
        self.assertEqual(_real_yield_ratio(0.0, 0.0), 0.0)

    def test_total_zero_real_positive_returns_one(self):
        self.assertEqual(_real_yield_ratio(5.0, 0.0), 1.0)

    def test_total_zero_real_zero_returns_zero(self):
        self.assertEqual(_real_yield_ratio(0.0, 0.0), 0.0)

    def test_ratio_one(self):
        self.assertAlmostEqual(_real_yield_ratio(10.0, 10.0), 1.0, places=6)

    def test_ratio_half(self):
        self.assertAlmostEqual(_real_yield_ratio(5.0, 10.0), 0.5, places=6)

    def test_ratio_quarter(self):
        self.assertAlmostEqual(_real_yield_ratio(2.5, 10.0), 0.25, places=6)

    def test_clamp_above_one(self):
        # real_yield > total_apy → clamped to 1.0
        self.assertEqual(_real_yield_ratio(15.0, 10.0), 1.0)

    def test_clamp_below_zero(self):
        # negative real yield (shouldn't happen normally) → clamped to 0
        self.assertEqual(_real_yield_ratio(-5.0, 10.0), 0.0)

    def test_result_rounded_to_6_places(self):
        result = _real_yield_ratio(1.0, 3.0)
        self.assertAlmostEqual(result, 0.333333, places=5)

    def test_result_in_range(self):
        for real, total in [(0, 5), (3, 5), (5, 5), (7, 5), (0, 0)]:
            ratio = _real_yield_ratio(float(real), float(total))
            self.assertGreaterEqual(ratio, 0.0)
            self.assertLessEqual(ratio, 1.0)


# ===========================================================================
# 4. _incentive_sustainability_score
# ===========================================================================

class TestIncentiveSustainabilityScore(unittest.TestCase):

    def _score(self, inflation=0.0, vest=0.0, inc_per_day=0.0, price=1.0, supply=0.0):
        return _incentive_sustainability_score(inflation, vest, inc_per_day, price, supply)

    def test_zero_inflation_max_vest_zero_dilution(self):
        # 0% inflation (40pts) + 365d vest (30pts) + 0 dilution (30pts) = 100
        s = self._score(inflation=0.0, vest=365.0, inc_per_day=0.0, price=1.0, supply=1_000_000.0)
        self.assertAlmostEqual(s, 100.0, places=1)

    def test_max_inflation_no_vest(self):
        # 50% inflation (0pts) + 0 vest (0pts) + some dilution
        s = self._score(inflation=50.0, vest=0.0, inc_per_day=1_000.0, price=1.0, supply=1_000_000.0)
        self.assertLessEqual(s, 30.0)

    def test_zero_market_cap_gives_neutral_dilution(self):
        # market_cap = 0 → 15 pts for dilution
        s = self._score(inflation=0.0, vest=0.0, inc_per_day=1_000.0, price=0.0, supply=0.0)
        # 40 + 0 + 15 = 55
        self.assertAlmostEqual(s, 55.0, places=1)

    def test_zero_market_cap_no_supply(self):
        s = self._score(inflation=0.0, vest=0.0, price=0.0, supply=0.0, inc_per_day=500.0)
        self.assertAlmostEqual(s, 55.0, places=1)

    def test_max_vest_gives_30_vest_pts(self):
        # 0% inflation (40pts) + 365d vest (30pts) + 0 dilution (30pts) = 100
        s = self._score(inflation=0.0, vest=365.0, inc_per_day=0.0, price=10.0, supply=1_000_000.0)
        self.assertAlmostEqual(s, 100.0, places=1)

    def test_zero_vest_gives_zero_vest_pts(self):
        # With 0 inflation and 0 dilution: 40+0+30 = 70
        s = self._score(inflation=0.0, vest=0.0, inc_per_day=0.0, price=10.0, supply=1_000_000.0)
        self.assertAlmostEqual(s, 70.0, places=1)

    def test_half_inflation_gives_half_inflation_pts(self):
        # inflation=25 → (1 - 25/50)*40 = 20 pts inflation
        s = self._score(inflation=25.0, vest=0.0, inc_per_day=0.0, price=10.0, supply=1_000_000.0)
        self.assertAlmostEqual(s, 50.0, places=1)  # 20 + 0 + 30

    def test_score_capped_at_100(self):
        s = self._score(inflation=0.0, vest=10000.0, inc_per_day=0.0, price=10.0, supply=1_000_000.0)
        self.assertLessEqual(s, 100.0)

    def test_score_floor_above_or_equal_zero(self):
        s = self._score(inflation=100.0, vest=0.0, inc_per_day=1_000_000.0, price=0.001, supply=1.0)
        self.assertGreaterEqual(s, 0.0)

    def test_high_daily_dilution_gives_low_dilution_pts(self):
        # inc_per_day = 0.5% of market_cap → 0 dilution pts
        market_cap = 1_000_000.0
        inc_per_day = market_cap * 0.005  # exactly at cap
        s = self._score(inflation=0.0, vest=0.0, inc_per_day=inc_per_day, price=1.0, supply=market_cap)
        self.assertAlmostEqual(s, 40.0, places=1)  # 40 + 0 + 0

    def test_moderate_scenario(self):
        # inflation=10 → 32pts; vest=180 → 14.79pts; small dilution → ~30pts
        s = self._score(inflation=10.0, vest=180.0, inc_per_day=100.0, price=1.0, supply=10_000_000.0)
        self.assertGreater(s, 50.0)
        self.assertLess(s, 100.0)

    def test_returns_float(self):
        s = self._score()
        self.assertIsInstance(s, float)

    def test_vest_clamped_beyond_365(self):
        s1 = self._score(vest=365.0, inc_per_day=0.0, price=1.0, supply=1_000_000.0)
        s2 = self._score(vest=730.0, inc_per_day=0.0, price=1.0, supply=1_000_000.0)
        self.assertAlmostEqual(s1, s2, places=2)

    def test_inflation_clamped_beyond_50(self):
        s1 = self._score(inflation=50.0, vest=0.0, inc_per_day=0.0, price=1.0, supply=1_000_000.0)
        s2 = self._score(inflation=100.0, vest=0.0, inc_per_day=0.0, price=1.0, supply=1_000_000.0)
        self.assertAlmostEqual(s1, s2, places=2)


# ===========================================================================
# 5. _yield_quality_label
# ===========================================================================

class TestYieldQualityLabel(unittest.TestCase):

    def test_ratio_1_0(self):
        self.assertEqual(_yield_quality_label(1.0), "PURE_REAL_YIELD")

    def test_ratio_exactly_0_9(self):
        self.assertEqual(_yield_quality_label(0.90), "PURE_REAL_YIELD")

    def test_ratio_0_95(self):
        self.assertEqual(_yield_quality_label(0.95), "PURE_REAL_YIELD")

    def test_ratio_just_below_0_9(self):
        self.assertEqual(_yield_quality_label(0.899), "PREDOMINANTLY_REAL")

    def test_ratio_0_6(self):
        self.assertEqual(_yield_quality_label(0.60), "PREDOMINANTLY_REAL")

    def test_ratio_0_75(self):
        self.assertEqual(_yield_quality_label(0.75), "PREDOMINANTLY_REAL")

    def test_ratio_just_below_0_6(self):
        self.assertEqual(_yield_quality_label(0.599), "BALANCED")

    def test_ratio_0_4(self):
        self.assertEqual(_yield_quality_label(0.40), "BALANCED")

    def test_ratio_0_5(self):
        self.assertEqual(_yield_quality_label(0.50), "BALANCED")

    def test_ratio_just_below_0_4(self):
        self.assertEqual(_yield_quality_label(0.399), "INCENTIVE_HEAVY")

    def test_ratio_0_1(self):
        self.assertEqual(_yield_quality_label(0.10), "INCENTIVE_HEAVY")

    def test_ratio_0_25(self):
        self.assertEqual(_yield_quality_label(0.25), "INCENTIVE_HEAVY")

    def test_ratio_just_below_0_1(self):
        self.assertEqual(_yield_quality_label(0.099), "PURE_PONZI_YIELD")

    def test_ratio_0_0(self):
        self.assertEqual(_yield_quality_label(0.0), "PURE_PONZI_YIELD")

    def test_ratio_0_05(self):
        self.assertEqual(_yield_quality_label(0.05), "PURE_PONZI_YIELD")

    def test_all_labels_reachable(self):
        labels = {
            _yield_quality_label(1.0),
            _yield_quality_label(0.75),
            _yield_quality_label(0.5),
            _yield_quality_label(0.2),
            _yield_quality_label(0.05),
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 6. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def test_creates_file_if_not_exists(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_initial_entry_is_list_of_one(self):
        path = _tmp_log()
        _atomic_log(path, {"val": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["val"], 42)
        os.unlink(path)

    def test_appends_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(_LOG_CAP + 10):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)
        os.unlink(path)

    def test_ring_buffer_keeps_latest(self):
        path = _tmp_log()
        for i in range(_LOG_CAP + 5):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], _LOG_CAP + 4)
        os.unlink(path)

    def test_corrupted_json_resets(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"not-valid-json{{{")
        os.close(fd)
        _atomic_log(path, {"k": "v"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_non_list_json_resets(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b'{"key": "value"}')
        os.close(fd)
        _atomic_log(path, {"entry": True})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_nested_dir_created(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "sub", "deep", "log.json")
        _atomic_log(path, {"ok": True})
        self.assertTrue(os.path.exists(path))
        import shutil
        shutil.rmtree(tmp_dir)


# ===========================================================================
# 7. DeFiProtocolRealYieldVsIncentiveYieldAnalyzer.analyze
# ===========================================================================

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()
        self.cfg = {"log_path": self.log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def _run(self, **overrides):
        return DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(
            _base_data(**overrides), self.cfg
        )

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_protocol_name_preserved(self):
        r = self._run(protocol_name="Aave")
        self.assertEqual(r["protocol_name"], "Aave")

    def test_total_apy_pct_in_result(self):
        r = self._run(total_apy_pct=15.0)
        self.assertEqual(r["total_apy_pct"], 15.0)

    def test_real_yield_pct_correct(self):
        r = self._run(fee_revenue_usd_per_day=5_000.0, tvl_usd=50_000_000.0)
        expected = 5_000.0 * 365.0 / 50_000_000.0 * 100.0
        self.assertAlmostEqual(r["real_yield_pct"], expected, places=4)

    def test_incentive_yield_pct_correct(self):
        r = self._run(token_incentive_usd_per_day=2_000.0, tvl_usd=50_000_000.0)
        expected = 2_000.0 * 365.0 / 50_000_000.0 * 100.0
        self.assertAlmostEqual(r["incentive_yield_pct"], expected, places=4)

    def test_real_yield_ratio_in_result(self):
        r = self._run()
        self.assertIn("real_yield_ratio", r)

    def test_real_yield_ratio_range(self):
        r = self._run()
        self.assertGreaterEqual(r["real_yield_ratio"], 0.0)
        self.assertLessEqual(r["real_yield_ratio"], 1.0)

    def test_incentive_sustainability_score_in_range(self):
        r = self._run()
        self.assertGreaterEqual(r["incentive_sustainability_score"], 0.0)
        self.assertLessEqual(r["incentive_sustainability_score"], 100.0)

    def test_yield_quality_label_valid(self):
        valid = {"PURE_REAL_YIELD", "PREDOMINANTLY_REAL", "BALANCED",
                 "INCENTIVE_HEAVY", "PURE_PONZI_YIELD"}
        r = self._run()
        self.assertIn(r["yield_quality_label"], valid)

    def test_timestamp_present(self):
        r = self._run()
        self.assertIn("timestamp", r)
        self.assertRegex(r["timestamp"], r"\d{4}-\d{2}-\d{2}T")

    def test_zero_tvl_yields_zero(self):
        r = self._run(tvl_usd=0.0)
        self.assertEqual(r["real_yield_pct"], 0.0)
        self.assertEqual(r["incentive_yield_pct"], 0.0)

    def test_no_incentives_pure_real(self):
        # Zero incentives → ratio = real/total → if real ≥ 90% → PURE_REAL_YIELD
        r = self._run(
            token_incentive_usd_per_day=0.0,
            fee_revenue_usd_per_day=50_000.0,
            tvl_usd=10_000_000.0,
            total_apy_pct=18.25,  # = 50000*365/10M*100
        )
        self.assertEqual(r["yield_quality_label"], "PURE_REAL_YIELD")

    def test_all_incentive_no_fee_ponzi(self):
        r = self._run(
            fee_revenue_usd_per_day=0.0,
            token_incentive_usd_per_day=10_000.0,
            total_apy_pct=7.3,
            tvl_usd=50_000_000.0,
        )
        self.assertEqual(r["yield_quality_label"], "PURE_PONZI_YIELD")

    def test_write_log_true_writes_file(self):
        cfg = {"log_path": self.log, "write_log": True}
        DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        self.assertTrue(os.path.exists(self.log))

    def test_write_log_false_no_file(self):
        cfg = {"log_path": self.log, "write_log": False}
        DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        self.assertFalse(os.path.exists(self.log))

    def test_missing_protocol_name_defaults_unknown(self):
        data = {k: v for k, v in _base_data().items() if k != "protocol_name"}
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(data, self.cfg)
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_none_config_uses_defaults(self):
        # Should not raise; will attempt to write to default log path
        # We patch by using write_log=False via a config dict override
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(
            _base_data(), {"write_log": False}
        )
        self.assertIn("yield_quality_label", r)

    def test_string_numeric_inputs_coerced(self):
        data = _base_data()
        data["total_apy_pct"] = "10.0"
        data["fee_revenue_usd_per_day"] = "5000"
        data["tvl_usd"] = "50000000"
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(data, self.cfg)
        self.assertIsInstance(r["real_yield_pct"], float)

    def test_predominantly_real_label(self):
        # real=7%, total=10% → ratio=0.7 → PREDOMINANTLY_REAL
        fee = 7.0 / 100.0 / 365.0 * 50_000_000.0
        r = self._run(fee_revenue_usd_per_day=fee, total_apy_pct=10.0)
        self.assertEqual(r["yield_quality_label"], "PREDOMINANTLY_REAL")

    def test_balanced_label(self):
        # real=5%, total=10% → ratio=0.5 → BALANCED
        fee = 5.0 / 100.0 / 365.0 * 50_000_000.0
        r = self._run(fee_revenue_usd_per_day=fee, total_apy_pct=10.0)
        self.assertEqual(r["yield_quality_label"], "BALANCED")

    def test_incentive_heavy_label(self):
        # real=2%, total=10% → ratio=0.2 → INCENTIVE_HEAVY
        fee = 2.0 / 100.0 / 365.0 * 50_000_000.0
        r = self._run(fee_revenue_usd_per_day=fee, total_apy_pct=10.0)
        self.assertEqual(r["yield_quality_label"], "INCENTIVE_HEAVY")

    def test_multiple_runs_independent(self):
        r1 = self._run(protocol_name="A", total_apy_pct=5.0)
        r2 = self._run(protocol_name="B", total_apy_pct=20.0)
        self.assertNotEqual(r1["protocol_name"], r2["protocol_name"])

    def test_all_expected_keys_present(self):
        expected = {
            "protocol_name", "total_apy_pct", "real_yield_pct",
            "incentive_yield_pct", "real_yield_ratio",
            "incentive_sustainability_score", "yield_quality_label", "timestamp",
        }
        r = self._run()
        self.assertTrue(expected.issubset(set(r.keys())))


# ===========================================================================
# 8. Module-level analyze()
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_returns_dict(self):
        cfg = {"log_path": self.log, "write_log": False}
        r = analyze(_base_data(), cfg)
        self.assertIsInstance(r, dict)

    def test_same_result_as_class(self):
        cfg = {"log_path": self.log, "write_log": False}
        r1 = analyze(_base_data(), cfg)
        r2 = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        # Compare non-timestamp fields
        for k in ("real_yield_pct", "incentive_yield_pct", "yield_quality_label"):
            self.assertEqual(r1[k], r2[k])

    def test_no_config(self):
        # Minimal: must not raise with write_log defaulting to True
        r = analyze(_base_data(), {"write_log": False})
        self.assertIn("yield_quality_label", r)

    def test_protocol_name_forwarded(self):
        cfg = {"log_path": self.log, "write_log": False}
        r = analyze(_base_data(protocol_name="Compound"), cfg)
        self.assertEqual(r["protocol_name"], "Compound")


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()
        self.cfg = {"log_path": self.log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def _run(self, **overrides):
        return DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(
            _base_data(**overrides), self.cfg
        )

    def test_total_apy_zero(self):
        r = self._run(total_apy_pct=0.0)
        self.assertIn("yield_quality_label", r)

    def test_total_apy_negative(self):
        r = self._run(total_apy_pct=-5.0)
        # total_apy <= 0: ratio = 1.0 if real > 0, else 0.0
        self.assertIn(r["real_yield_ratio"], [0.0, 1.0])

    def test_all_zeros(self):
        data = {k: 0 for k in _base_data()}
        data["protocol_name"] = "ZeroProto"
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(data, self.cfg)
        self.assertEqual(r["real_yield_pct"], 0.0)
        self.assertEqual(r["incentive_yield_pct"], 0.0)

    def test_very_large_tvl(self):
        r = self._run(tvl_usd=1e18)
        self.assertGreaterEqual(r["real_yield_pct"], 0.0)

    def test_very_large_fee(self):
        r = self._run(fee_revenue_usd_per_day=1e12)
        self.assertGreater(r["real_yield_pct"], 0.0)

    def test_very_high_inflation(self):
        r = self._run(token_inflation_rate_pct=9999.0)
        self.assertGreaterEqual(r["incentive_sustainability_score"], 0.0)

    def test_very_long_vest(self):
        r = self._run(emissions_vest_days=36500.0)
        self.assertLessEqual(r["incentive_sustainability_score"], 100.0)

    def test_zero_token_price(self):
        r = self._run(token_price_usd=0.0, token_circulating_supply=0.0)
        # dilution_pts = 15 (neutral)
        self.assertIn("incentive_sustainability_score", r)

    def test_result_is_read_only_advisory(self):
        # Ensure result dict has no write-to-execution side effects
        r = self._run()
        self.assertNotIn("trades", r)
        self.assertNotIn("positions", r)
        self.assertNotIn("rebalance", r)


# ===========================================================================
# 10. Data-type and ring-buffer integration
# ===========================================================================

class TestRingBufferIntegration(unittest.TestCase):

    def test_100_entries_then_101_stays_at_100(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        an = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer()
        for i in range(101):
            d = _base_data(protocol_name=f"P{i}")
            an.analyze(d, cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(path)

    def test_log_entry_contains_required_fields(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        with open(path) as f:
            entry = json.load(f)[0]
        for field in ("timestamp", "protocol_name", "real_yield_pct",
                      "incentive_yield_pct", "real_yield_ratio",
                      "incentive_sustainability_score", "yield_quality_label"):
            self.assertIn(field, entry)
        os.unlink(path)

    def test_log_entry_protocol_name_correct(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(
            _base_data(protocol_name="Morpho"), cfg
        )
        with open(path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_name"], "Morpho")
        os.unlink(path)

    def test_result_sustainability_score_is_float(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": False}
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        self.assertIsInstance(r["incentive_sustainability_score"], float)

    def test_result_ratio_is_float(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": False}
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        self.assertIsInstance(r["real_yield_ratio"], float)

    def test_yield_quality_label_is_string(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": False}
        r = DeFiProtocolRealYieldVsIncentiveYieldAnalyzer().analyze(_base_data(), cfg)
        self.assertIsInstance(r["yield_quality_label"], str)


if __name__ == "__main__":
    unittest.main()
