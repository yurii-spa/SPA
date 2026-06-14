"""
Tests for MP-1101 ProtocolDeFiPointsProgramValueEstimator.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_points_program_value_estimator -v
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

from spa_core.analytics.protocol_defi_points_program_value_estimator import (
    ProtocolDeFiPointsProgramValueEstimator,
    estimate,
    estimate_and_log,
    init_log,
    LOG_FILENAME,
    LOG_MAX_ENTRIES,
    _compute_total_points_at_tge,
    _compute_user_points_share_pct,
    _compute_tokens_received,
    _compute_scenario_value,
    _compute_implied_apy,
    _classify_points,
    _append_log,
    _read_log,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _default_kwargs(**overrides):
    base = dict(
        points_earned_per_day=1_000.0,
        days_until_tge=180,
        total_protocol_points_issued=1_000_000_000.0,
        airdrop_allocation_pct=10.0,
        total_token_supply=1_000_000_000.0,
        conservative_tge_price_usd=0.05,
        base_tge_price_usd=0.15,
        bull_tge_price_usd=0.50,
        position_size_usd=50_000.0,
        protocol_name="Eigenlayer",
    )
    base.update(overrides)
    return base


# ===========================================================================
# 1. _compute_total_points_at_tge
# ===========================================================================

class TestComputeTotalPointsAtTge(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_compute_total_points_at_tge(1_000.0, 180), 180_000.0)

    def test_zero_days(self):
        self.assertAlmostEqual(_compute_total_points_at_tge(1_000.0, 0), 0.0)

    def test_negative_days(self):
        self.assertAlmostEqual(_compute_total_points_at_tge(1_000.0, -5), 0.0)

    def test_zero_points_per_day(self):
        self.assertAlmostEqual(_compute_total_points_at_tge(0.0, 180), 0.0)

    def test_one_day(self):
        self.assertAlmostEqual(_compute_total_points_at_tge(500.0, 1), 500.0)

    def test_large_values(self):
        result = _compute_total_points_at_tge(1_000_000.0, 365)
        self.assertAlmostEqual(result, 365_000_000.0)

    def test_fractional_points_per_day(self):
        result = _compute_total_points_at_tge(0.5, 10)
        self.assertAlmostEqual(result, 5.0)

    def test_returns_float(self):
        result = _compute_total_points_at_tge(1_000.0, 180)
        self.assertIsInstance(result, float)

    def test_proportional_to_days(self):
        r1 = _compute_total_points_at_tge(100.0, 10)
        r2 = _compute_total_points_at_tge(100.0, 20)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_proportional_to_rate(self):
        r1 = _compute_total_points_at_tge(100.0, 30)
        r2 = _compute_total_points_at_tge(200.0, 30)
        self.assertAlmostEqual(r2, r1 * 2)


# ===========================================================================
# 2. _compute_user_points_share_pct
# ===========================================================================

class TestComputeUserPointsSharePct(unittest.TestCase):

    def test_basic(self):
        # 180000 / 1000000000 * 100 = 0.018%
        result = _compute_user_points_share_pct(180_000.0, 1_000_000_000.0)
        self.assertAlmostEqual(result, 0.018)

    def test_zero_total_returns_zero(self):
        result = _compute_user_points_share_pct(180_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_total_returns_zero(self):
        result = _compute_user_points_share_pct(180_000.0, -100.0)
        self.assertAlmostEqual(result, 0.0)

    def test_equal_points_gives_100_pct(self):
        result = _compute_user_points_share_pct(1_000.0, 1_000.0)
        self.assertAlmostEqual(result, 100.0)

    def test_half_gives_50_pct(self):
        result = _compute_user_points_share_pct(500.0, 1_000.0)
        self.assertAlmostEqual(result, 50.0)

    def test_zero_user_points_gives_zero(self):
        result = _compute_user_points_share_pct(0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0)

    def test_returns_float(self):
        result = _compute_user_points_share_pct(100.0, 1_000.0)
        self.assertIsInstance(result, float)

    def test_large_user_more_than_total_exceeds_100(self):
        # Edge case: user could have more points than "total" if total is stale
        result = _compute_user_points_share_pct(2_000.0, 1_000.0)
        self.assertAlmostEqual(result, 200.0)


# ===========================================================================
# 3. _compute_tokens_received
# ===========================================================================

class TestComputeTokensReceived(unittest.TestCase):

    def test_basic(self):
        # share=0.018%, alloc=10%, supply=1B
        # = 0.018/100 * 10/100 * 1e9 = 18000
        result = _compute_tokens_received(0.018, 10.0, 1_000_000_000.0)
        self.assertAlmostEqual(result, 18_000.0)

    def test_zero_supply_returns_zero(self):
        result = _compute_tokens_received(0.018, 10.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_supply_returns_zero(self):
        result = _compute_tokens_received(0.018, 10.0, -1_000.0)
        self.assertAlmostEqual(result, 0.0)

    def test_zero_share_returns_zero(self):
        result = _compute_tokens_received(0.0, 10.0, 1_000_000_000.0)
        self.assertAlmostEqual(result, 0.0)

    def test_full_share_full_allocation(self):
        # 100% share, 100% allocation → all tokens
        result = _compute_tokens_received(100.0, 100.0, 1_000_000.0)
        self.assertAlmostEqual(result, 1_000_000.0)

    def test_proportional_to_share(self):
        r1 = _compute_tokens_received(1.0, 10.0, 1_000_000.0)
        r2 = _compute_tokens_received(2.0, 10.0, 1_000_000.0)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_proportional_to_allocation(self):
        r1 = _compute_tokens_received(1.0, 5.0, 1_000_000.0)
        r2 = _compute_tokens_received(1.0, 10.0, 1_000_000.0)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_returns_float(self):
        result = _compute_tokens_received(0.5, 10.0, 1_000_000.0)
        self.assertIsInstance(result, float)


# ===========================================================================
# 4. _compute_scenario_value
# ===========================================================================

class TestComputeScenarioValue(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_compute_scenario_value(18_000.0, 0.15), 2_700.0)

    def test_zero_tokens_returns_zero(self):
        self.assertAlmostEqual(_compute_scenario_value(0.0, 0.15), 0.0)

    def test_zero_price_returns_zero(self):
        self.assertAlmostEqual(_compute_scenario_value(18_000.0, 0.0), 0.0)

    def test_negative_price_returns_zero(self):
        self.assertAlmostEqual(_compute_scenario_value(18_000.0, -0.10), 0.0)

    def test_negative_tokens_returns_zero(self):
        self.assertAlmostEqual(_compute_scenario_value(-100.0, 0.15), 0.0)

    def test_proportional_to_price(self):
        r1 = _compute_scenario_value(1_000.0, 0.10)
        r2 = _compute_scenario_value(1_000.0, 0.20)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_proportional_to_tokens(self):
        r1 = _compute_scenario_value(1_000.0, 0.10)
        r2 = _compute_scenario_value(2_000.0, 0.10)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_returns_float(self):
        result = _compute_scenario_value(1_000.0, 0.10)
        self.assertIsInstance(result, float)

    def test_large_values(self):
        result = _compute_scenario_value(1_000_000.0, 10.0)
        self.assertAlmostEqual(result, 10_000_000.0)


# ===========================================================================
# 5. _compute_implied_apy
# ===========================================================================

class TestComputeImpliedApy(unittest.TestCase):

    def test_basic(self):
        # value=2700, pos=50000, days=180 → 2700/50000 * 365/180 * 100
        expected = 2_700 / 50_000 * (365 / 180) * 100
        result = _compute_implied_apy(2_700.0, 50_000.0, 180)
        self.assertAlmostEqual(result, expected)

    def test_zero_position_returns_zero(self):
        self.assertAlmostEqual(_compute_implied_apy(2_700.0, 0.0, 180), 0.0)

    def test_zero_days_returns_zero(self):
        self.assertAlmostEqual(_compute_implied_apy(2_700.0, 50_000.0, 0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertAlmostEqual(_compute_implied_apy(2_700.0, 50_000.0, -10), 0.0)

    def test_zero_value_returns_zero(self):
        self.assertAlmostEqual(_compute_implied_apy(0.0, 50_000.0, 180), 0.0)

    def test_365_days_equals_simple_ratio(self):
        # 365 days → APY = (value / pos) * 100
        result = _compute_implied_apy(5_000.0, 100_000.0, 365)
        self.assertAlmostEqual(result, 5.0)

    def test_shorter_duration_higher_apy(self):
        r90 = _compute_implied_apy(1_000.0, 50_000.0, 90)
        r180 = _compute_implied_apy(1_000.0, 50_000.0, 180)
        self.assertGreater(r90, r180)

    def test_larger_value_higher_apy(self):
        r1 = _compute_implied_apy(1_000.0, 50_000.0, 180)
        r2 = _compute_implied_apy(2_000.0, 50_000.0, 180)
        self.assertAlmostEqual(r2, r1 * 2)

    def test_returns_float(self):
        result = _compute_implied_apy(1_000.0, 50_000.0, 180)
        self.assertIsInstance(result, float)


# ===========================================================================
# 6. _classify_points
# ===========================================================================

class TestClassifyPoints(unittest.TestCase):

    def test_exceptional_airdrop(self):
        self.assertEqual(_classify_points(100.1), "EXCEPTIONAL_AIRDROP")

    def test_exceptional_airdrop_very_high(self):
        self.assertEqual(_classify_points(500.0), "EXCEPTIONAL_AIRDROP")

    def test_good_airdrop_exactly_30(self):
        self.assertEqual(_classify_points(30.0), "GOOD_AIRDROP")

    def test_good_airdrop_upper_boundary(self):
        self.assertEqual(_classify_points(99.9), "GOOD_AIRDROP")

    def test_modest_airdrop_exactly_10(self):
        self.assertEqual(_classify_points(10.0), "MODEST_AIRDROP")

    def test_modest_airdrop_upper_boundary(self):
        self.assertEqual(_classify_points(29.9), "MODEST_AIRDROP")

    def test_minimal_value_exactly_2(self):
        self.assertEqual(_classify_points(2.0), "MINIMAL_VALUE")

    def test_minimal_value_upper_boundary(self):
        self.assertEqual(_classify_points(9.9), "MINIMAL_VALUE")

    def test_diluted_out_exactly_0(self):
        self.assertEqual(_classify_points(0.0), "DILUTED_OUT")

    def test_diluted_out_negative(self):
        self.assertEqual(_classify_points(-10.0), "DILUTED_OUT")

    def test_diluted_out_just_below_2(self):
        self.assertEqual(_classify_points(1.99), "DILUTED_OUT")

    def test_exactly_100_is_good_airdrop(self):
        # > 100 → EXCEPTIONAL; exactly 100 is not > 100 → GOOD_AIRDROP
        self.assertEqual(_classify_points(100.0), "GOOD_AIRDROP")

    def test_valid_labels_for_range(self):
        valid = {
            "EXCEPTIONAL_AIRDROP", "GOOD_AIRDROP", "MODEST_AIRDROP",
            "MINIMAL_VALUE", "DILUTED_OUT"
        }
        for apy in [-5, 0, 1, 2, 5, 10, 15, 30, 50, 100, 100.001, 200]:
            with self.subTest(apy=apy):
                label = _classify_points(apy)
                self.assertIn(label, valid)


# ===========================================================================
# 7. estimate() — core function
# ===========================================================================

class TestEstimate(unittest.TestCase):

    def _run(self, **overrides):
        return estimate(**_default_kwargs(**overrides))

    def test_returns_dict(self):
        result = self._run()
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        result = self._run()
        required = [
            "protocol_name", "points_earned_per_day", "days_until_tge",
            "total_protocol_points_issued", "airdrop_allocation_pct",
            "total_token_supply", "conservative_tge_price_usd",
            "base_tge_price_usd", "bull_tge_price_usd", "position_size_usd",
            "total_points_at_tge", "user_points_share_pct", "tokens_received",
            "conservative_value_usd", "base_value_usd", "bull_value_usd",
            "implied_apy_pct", "points_label", "timestamp",
        ]
        for key in required:
            with self.subTest(key=key):
                self.assertIn(key, result)

    def test_protocol_name_preserved(self):
        result = self._run(protocol_name="Morpho")
        self.assertEqual(result["protocol_name"], "Morpho")

    def test_total_points_at_tge_correct(self):
        result = self._run(points_earned_per_day=1_000.0, days_until_tge=180)
        self.assertAlmostEqual(result["total_points_at_tge"], 180_000.0)

    def test_user_points_share_correct(self):
        result = self._run(
            points_earned_per_day=1_000.0,
            days_until_tge=180,
            total_protocol_points_issued=1_000_000_000.0,
        )
        self.assertAlmostEqual(result["user_points_share_pct"], 0.018)

    def test_tokens_received_correct(self):
        result = self._run(
            points_earned_per_day=1_000.0,
            days_until_tge=180,
            total_protocol_points_issued=1_000_000_000.0,
            airdrop_allocation_pct=10.0,
            total_token_supply=1_000_000_000.0,
        )
        # share=0.018%, tokens = 0.018/100 * 10/100 * 1e9 = 18000
        self.assertAlmostEqual(result["tokens_received"], 18_000.0)

    def test_base_value_usd_correct(self):
        result = self._run(
            points_earned_per_day=1_000.0,
            days_until_tge=180,
            total_protocol_points_issued=1_000_000_000.0,
            airdrop_allocation_pct=10.0,
            total_token_supply=1_000_000_000.0,
            base_tge_price_usd=0.15,
        )
        self.assertAlmostEqual(result["base_value_usd"], 18_000.0 * 0.15)

    def test_conservative_less_than_base(self):
        result = self._run()
        self.assertLessEqual(result["conservative_value_usd"], result["base_value_usd"])

    def test_base_less_than_bull(self):
        result = self._run()
        self.assertLessEqual(result["base_value_usd"], result["bull_value_usd"])

    def test_implied_apy_correct(self):
        result = self._run()
        base_value = result["base_value_usd"]
        pos = result["position_size_usd"]
        days = result["days_until_tge"]
        expected = base_value / pos * (365 / days) * 100
        self.assertAlmostEqual(result["implied_apy_pct"], expected)

    def test_points_label_is_string(self):
        result = self._run()
        self.assertIsInstance(result["points_label"], str)

    def test_points_label_valid(self):
        result = self._run()
        self.assertIn(result["points_label"], {
            "EXCEPTIONAL_AIRDROP", "GOOD_AIRDROP", "MODEST_AIRDROP",
            "MINIMAL_VALUE", "DILUTED_OUT"
        })

    def test_timestamp_recent(self):
        before = time.time()
        result = self._run()
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_zero_days_until_tge(self):
        result = self._run(days_until_tge=0)
        self.assertAlmostEqual(result["total_points_at_tge"], 0.0)
        self.assertAlmostEqual(result["tokens_received"], 0.0)
        self.assertEqual(result["implied_apy_pct"], 0.0)

    def test_high_points_rate_exceptional_airdrop(self):
        result = self._run(
            points_earned_per_day=10_000_000.0,
            days_until_tge=365,
            total_protocol_points_issued=1_000_000_000.0,
            airdrop_allocation_pct=20.0,
            total_token_supply=1_000_000_000.0,
            base_tge_price_usd=1.0,
            position_size_usd=10_000.0,
        )
        self.assertEqual(result["points_label"], "EXCEPTIONAL_AIRDROP")

    def test_heavily_diluted_minimal_value(self):
        # Very small share → DILUTED_OUT
        result = self._run(
            points_earned_per_day=1.0,
            days_until_tge=90,
            total_protocol_points_issued=1_000_000_000_000.0,  # 1 trillion points
            airdrop_allocation_pct=1.0,
            total_token_supply=1_000_000_000.0,
            base_tge_price_usd=0.001,
            position_size_usd=100_000.0,
        )
        self.assertIn(result["points_label"], {"DILUTED_OUT", "MINIMAL_VALUE"})

    def test_inputs_echoed(self):
        kwargs = _default_kwargs()
        result = estimate(**kwargs)
        self.assertEqual(result["protocol_name"], kwargs["protocol_name"])
        self.assertAlmostEqual(result["points_earned_per_day"], kwargs["points_earned_per_day"])
        self.assertEqual(result["days_until_tge"], kwargs["days_until_tge"])

    def test_identical_calls_give_same_outputs(self):
        kwargs = _default_kwargs()
        r1 = estimate(**kwargs)
        r2 = estimate(**kwargs)
        for key in ["total_points_at_tge", "user_points_share_pct", "tokens_received",
                    "base_value_usd", "implied_apy_pct", "points_label"]:
            with self.subTest(key=key):
                self.assertEqual(r1[key], r2[key])

    def test_zero_position_size(self):
        result = self._run(position_size_usd=0.0)
        self.assertAlmostEqual(result["implied_apy_pct"], 0.0)

    def test_apy_increases_with_higher_price(self):
        r_low = self._run(base_tge_price_usd=0.10)
        r_high = self._run(base_tge_price_usd=0.50)
        self.assertGreater(r_high["implied_apy_pct"], r_low["implied_apy_pct"])

    def test_apy_decreases_with_more_total_points(self):
        r_small = self._run(total_protocol_points_issued=1_000_000.0)
        r_large = self._run(total_protocol_points_issued=1_000_000_000.0)
        self.assertGreater(r_small["implied_apy_pct"], r_large["implied_apy_pct"])


# ===========================================================================
# 8. estimate_and_log()
# ===========================================================================

class TestEstimateAndLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_single_entry_appended(self):
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_entries_accumulated(self):
        for _ in range(3):
            estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_returns_same_keys_as_estimate(self):
        result_log = estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        result_pure = estimate(**_default_kwargs())
        for key in result_pure:
            with self.subTest(key=key):
                self.assertIn(key, result_log)

    def test_ring_buffer_caps_at_max(self):
        for _ in range(LOG_MAX_ENTRIES + 15):
            estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            estimate_and_log(**_default_kwargs(protocol_name=f"proto_{i}"), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol_name"], f"proto_{LOG_MAX_ENTRIES + 4}")

    def test_log_entry_has_required_keys(self):
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            entry = json.load(f)[0]
        for key in ["points_label", "implied_apy_pct", "tokens_received"]:
            with self.subTest(key=key):
                self.assertIn(key, entry)

    def test_data_values_in_log_correct(self):
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            entry = json.load(f)[0]
        self.assertAlmostEqual(entry["total_points_at_tge"], 180_000.0)


# ===========================================================================
# 9. init_log()
# ===========================================================================

class TestInitLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_empty_list_file(self):
        init_log(self.tmp)
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_does_not_overwrite_existing_data(self):
        estimate_and_log(**_default_kwargs(), data_dir=self.tmp)
        init_log(self.tmp)
        with open(os.path.join(self.tmp, LOG_FILENAME)) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_data_dir_if_missing(self):
        new_dir = os.path.join(self.tmp, "newsubdir")
        self.assertFalse(os.path.exists(new_dir))
        init_log(new_dir)
        self.assertTrue(os.path.exists(new_dir))

    def test_log_file_is_valid_json(self):
        init_log(self.tmp)
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])


# ===========================================================================
# 10. _read_log / _append_log internals
# ===========================================================================

class TestReadAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_missing_file_returns_empty_list(self):
        path = os.path.join(self.tmp, "missing.json")
        self.assertEqual(_read_log(path), [])

    def test_read_corrupt_file_returns_empty_list(self):
        path = os.path.join(self.tmp, LOG_FILENAME)
        with open(path, "w") as f:
            f.write("{{{NOT JSON")
        self.assertEqual(_read_log(path), [])

    def test_read_non_list_json_returns_empty(self):
        path = os.path.join(self.tmp, LOG_FILENAME)
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)
        self.assertEqual(_read_log(path), [])

    def test_append_increments_count(self):
        entry = {"proto": "test"}
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        _append_log(entry, self.tmp)
        _append_log(entry, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_exactly_at_max(self):
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        for i in range(LOG_MAX_ENTRIES):
            _append_log({"i": i}, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)

    def test_ring_buffer_one_over_max(self):
        log_path = os.path.join(self.tmp, LOG_FILENAME)
        for i in range(LOG_MAX_ENTRIES + 1):
            _append_log({"i": i}, self.tmp)
        data = _read_log(log_path)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)
        # Oldest dropped, newest at end
        self.assertEqual(data[-1]["i"], LOG_MAX_ENTRIES)


# ===========================================================================
# 11. ProtocolDeFiPointsProgramValueEstimator class
# ===========================================================================

class TestEstimatorClass(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.estimator = ProtocolDeFiPointsProgramValueEstimator(data_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_instantiate_with_data_dir(self):
        self.assertIsNotNone(self.estimator)

    def test_instantiate_default(self):
        e = ProtocolDeFiPointsProgramValueEstimator()
        self.assertIsNotNone(e)

    def test_estimate_returns_dict(self):
        result = self.estimator.estimate(**_default_kwargs())
        self.assertIsInstance(result, dict)

    def test_estimate_has_points_label(self):
        result = self.estimator.estimate(**_default_kwargs())
        self.assertIn("points_label", result)

    def test_estimate_and_log_creates_file(self):
        self.estimator.estimate_and_log(**_default_kwargs())
        self.assertTrue(os.path.exists(self.estimator.log_path))

    def test_estimate_and_log_returns_dict(self):
        result = self.estimator.estimate_and_log(**_default_kwargs())
        self.assertIsInstance(result, dict)

    def test_init_log_creates_empty_file(self):
        self.estimator.init_log()
        with open(self.estimator.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_log_path_in_data_dir(self):
        self.assertIn(self.tmp, self.estimator.log_path)

    def test_estimate_consistent_with_module_function(self):
        kwargs = _default_kwargs()
        r_class = self.estimator.estimate(**kwargs)
        r_func = estimate(**kwargs)
        for key in ["total_points_at_tge", "user_points_share_pct",
                    "tokens_received", "points_label", "implied_apy_pct"]:
            with self.subTest(key=key):
                self.assertEqual(r_class[key], r_func[key])

    def test_multiple_estimates_independent(self):
        r1 = self.estimator.estimate(**_default_kwargs(points_earned_per_day=100.0))
        r2 = self.estimator.estimate(**_default_kwargs(points_earned_per_day=10_000.0))
        self.assertNotEqual(r1["total_points_at_tge"], r2["total_points_at_tge"])

    def test_log_max_entries_constant(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)

    def test_log_filename_constant(self):
        self.assertEqual(LOG_FILENAME, "points_program_value_log.json")


# ===========================================================================
# 12. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_zero_total_protocol_points(self):
        result = estimate(**_default_kwargs(total_protocol_points_issued=0.0))
        self.assertAlmostEqual(result["user_points_share_pct"], 0.0)
        self.assertAlmostEqual(result["tokens_received"], 0.0)

    def test_zero_airdrop_allocation(self):
        result = estimate(**_default_kwargs(airdrop_allocation_pct=0.0))
        self.assertAlmostEqual(result["tokens_received"], 0.0)
        self.assertAlmostEqual(result["base_value_usd"], 0.0)

    def test_100_percent_allocation(self):
        result = estimate(**_default_kwargs(
            points_earned_per_day=1_000_000_000.0,
            days_until_tge=1,
            total_protocol_points_issued=1_000_000_000.0,
            airdrop_allocation_pct=100.0,
            total_token_supply=1_000_000_000.0,
            base_tge_price_usd=1.0,
        ))
        self.assertAlmostEqual(result["tokens_received"], 1_000_000_000.0)

    def test_zero_base_price_gives_zero_apy(self):
        result = estimate(**_default_kwargs(base_tge_price_usd=0.0))
        self.assertAlmostEqual(result["implied_apy_pct"], 0.0)
        self.assertEqual(result["points_label"], "DILUTED_OUT")

    def test_equal_all_prices(self):
        # All scenario values should be equal when prices are equal
        result = estimate(**_default_kwargs(
            conservative_tge_price_usd=0.10,
            base_tge_price_usd=0.10,
            bull_tge_price_usd=0.10,
        ))
        self.assertAlmostEqual(result["conservative_value_usd"], result["base_value_usd"])
        self.assertAlmostEqual(result["base_value_usd"], result["bull_value_usd"])

    def test_protocol_name_empty_string(self):
        result = estimate(**_default_kwargs(protocol_name=""))
        self.assertEqual(result["protocol_name"], "")

    def test_protocol_name_special_characters(self):
        name = "Protocol-v2 (USDC/ETH) [beta]"
        result = estimate(**_default_kwargs(protocol_name=name))
        self.assertEqual(result["protocol_name"], name)

    def test_very_large_position_size(self):
        result = estimate(**_default_kwargs(position_size_usd=1_000_000_000.0))
        # Just verify no crash
        self.assertIsInstance(result["implied_apy_pct"], float)

    def test_single_day_tge(self):
        result = estimate(**_default_kwargs(days_until_tge=1))
        self.assertAlmostEqual(result["total_points_at_tge"], 1_000.0)

    def test_long_duration_tge(self):
        result = estimate(**_default_kwargs(days_until_tge=1825))  # 5 years
        self.assertAlmostEqual(result["total_points_at_tge"], 1_000.0 * 1825)

    def test_very_small_points_per_day(self):
        result = estimate(**_default_kwargs(points_earned_per_day=0.001))
        self.assertAlmostEqual(result["total_points_at_tge"], 0.001 * 180)


# ===========================================================================
# 13. Label consistency integration
# ===========================================================================

class TestLabelConsistency(unittest.TestCase):

    def test_exceptional_airdrop_label_matches_apy(self):
        result = estimate(**_default_kwargs(
            points_earned_per_day=1_000_000.0,
            total_protocol_points_issued=1_000_000.0,  # 100% share
            airdrop_allocation_pct=50.0,
            total_token_supply=1_000_000_000.0,
            base_tge_price_usd=1.0,
            position_size_usd=10_000.0,
        ))
        if result["implied_apy_pct"] > 100:
            self.assertEqual(result["points_label"], "EXCEPTIONAL_AIRDROP")

    def test_diluted_out_implies_low_apy(self):
        result = estimate(**_default_kwargs(
            points_earned_per_day=1.0,
            total_protocol_points_issued=1_000_000_000_000.0,
            base_tge_price_usd=0.0001,
            position_size_usd=100_000.0,
        ))
        if result["points_label"] == "DILUTED_OUT":
            self.assertLess(result["implied_apy_pct"], 2.0)

    def test_exactly_100_apy_is_good_airdrop(self):
        # implied_apy = 100 exactly → GOOD_AIRDROP (not > 100)
        self.assertEqual(_classify_points(100.0), "GOOD_AIRDROP")

    def test_just_above_100_apy_is_exceptional(self):
        self.assertEqual(_classify_points(100.001), "EXCEPTIONAL_AIRDROP")

    def test_exactly_30_apy_is_good_airdrop(self):
        self.assertEqual(_classify_points(30.0), "GOOD_AIRDROP")

    def test_just_below_30_apy_is_modest(self):
        self.assertEqual(_classify_points(29.999), "MODEST_AIRDROP")

    def test_exactly_10_apy_is_modest(self):
        self.assertEqual(_classify_points(10.0), "MODEST_AIRDROP")

    def test_exactly_2_apy_is_minimal(self):
        self.assertEqual(_classify_points(2.0), "MINIMAL_VALUE")

    def test_just_below_2_is_diluted(self):
        self.assertEqual(_classify_points(1.999), "DILUTED_OUT")


if __name__ == "__main__":
    unittest.main()
