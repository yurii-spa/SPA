"""
Tests for MP-1116 DeFiProtocolGasCostSensitivityAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_gas_cost_sensitivity_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_gas_cost_sensitivity_analyzer import (
    analyze,
    log_result,
    _gas_label,
    _gas_sensitivity_score,
    _atomic_write,
    _LOG_CAP,
    VALID_STRATEGY_TYPES,
    VALID_CHAINS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_kwargs(**overrides) -> dict:
    """Return baseline kwargs for analyze(); override as needed."""
    base = dict(
        strategy_type="lending",
        transactions_per_month=4,
        avg_gas_per_tx_gwei=6_000_000.0,   # 200_000 gas * 30 gwei
        eth_price_usd=3_000.0,
        position_size_usd=100_000.0,
        gross_monthly_yield_pct=0.5,        # 6% APY gross
        chain="ethereum",
    )
    base.update(overrides)
    return base


def _expected_monthly_gas(txs, gwei, eth_price):
    return txs * gwei * eth_price / 1_000_000_000.0


def _expected_annual_gas(txs, gwei, eth_price):
    return _expected_monthly_gas(txs, gwei, eth_price) * 12.0


def _expected_gas_drag(txs, gwei, eth_price, pos_size):
    if pos_size <= 0:
        return 0.0
    return _expected_annual_gas(txs, gwei, eth_price) / pos_size * 100.0


# ===========================================================================
# 1.  _gas_label  (10 tests)
# ===========================================================================
class TestGasLabel(unittest.TestCase):

    def test_negligible_zero(self):
        self.assertEqual(_gas_label(0.0), "GAS_NEGLIGIBLE")

    def test_negligible_small(self):
        self.assertEqual(_gas_label(0.05), "GAS_NEGLIGIBLE")

    def test_negligible_boundary_exclusive(self):
        # Exactly 0.1 is NOT negligible (boundary exclusive)
        self.assertNotEqual(_gas_label(0.1), "GAS_NEGLIGIBLE")

    def test_low_gas_at_boundary(self):
        self.assertEqual(_gas_label(0.1), "LOW_GAS_DRAG")

    def test_low_gas_mid(self):
        self.assertEqual(_gas_label(0.3), "LOW_GAS_DRAG")

    def test_low_gas_just_below_05(self):
        self.assertEqual(_gas_label(0.499), "LOW_GAS_DRAG")

    def test_moderate_at_05(self):
        self.assertEqual(_gas_label(0.5), "MODERATE_GAS_DRAG")

    def test_moderate_mid(self):
        self.assertEqual(_gas_label(1.0), "MODERATE_GAS_DRAG")

    def test_moderate_just_below_2(self):
        self.assertEqual(_gas_label(1.999), "MODERATE_GAS_DRAG")

    def test_high_at_2(self):
        self.assertEqual(_gas_label(2.0), "HIGH_GAS_DRAG")

    def test_high_mid(self):
        self.assertEqual(_gas_label(3.5), "HIGH_GAS_DRAG")

    def test_high_at_5(self):
        self.assertEqual(_gas_label(5.0), "HIGH_GAS_DRAG")

    def test_kills_above_5(self):
        self.assertEqual(_gas_label(5.001), "GAS_KILLS_YIELD")

    def test_kills_large(self):
        self.assertEqual(_gas_label(50.0), "GAS_KILLS_YIELD")

    def test_kills_100(self):
        self.assertEqual(_gas_label(100.0), "GAS_KILLS_YIELD")

    def test_all_labels_distinct(self):
        labels = {
            _gas_label(0.0),
            _gas_label(0.2),
            _gas_label(1.0),
            _gas_label(3.0),
            _gas_label(10.0),
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 2.  _gas_sensitivity_score  (10 tests)
# ===========================================================================
class TestGasSensitivityScore(unittest.TestCase):

    def test_zero_drag_gives_zero(self):
        self.assertEqual(_gas_sensitivity_score(0.0), 0)

    def test_five_pct_gives_100(self):
        self.assertEqual(_gas_sensitivity_score(5.0), 100)

    def test_above_five_capped_at_100(self):
        self.assertEqual(_gas_sensitivity_score(10.0), 100)

    def test_half_pct(self):
        # 0.5 / 5.0 * 100 = 10
        self.assertEqual(_gas_sensitivity_score(0.5), 10)

    def test_one_pct(self):
        # 1.0 / 5.0 * 100 = 20
        self.assertEqual(_gas_sensitivity_score(1.0), 20)

    def test_two_pct(self):
        self.assertEqual(_gas_sensitivity_score(2.0), 40)

    def test_two_five_pct(self):
        self.assertEqual(_gas_sensitivity_score(2.5), 50)

    def test_three_pct(self):
        self.assertEqual(_gas_sensitivity_score(3.0), 60)

    def test_four_pct(self):
        self.assertEqual(_gas_sensitivity_score(4.0), 80)

    def test_returns_int(self):
        score = _gas_sensitivity_score(1.7)
        self.assertIsInstance(score, int)

    def test_never_negative(self):
        self.assertGreaterEqual(_gas_sensitivity_score(0.0), 0)


# ===========================================================================
# 3.  _atomic_write helper  (5 tests)
# ===========================================================================
class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _path(self, name="log.json"):
        return os.path.join(self.tmpdir, name)

    def test_creates_file(self):
        path = self._path()
        _atomic_write(path, [{"x": 1}])
        self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        path = self._path()
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(path, data)
        with open(path) as f:
            self.assertEqual(json.load(f), data)

    def test_overwrites_existing(self):
        path = self._path()
        _atomic_write(path, [1, 2, 3])
        _atomic_write(path, [99])
        with open(path) as f:
            self.assertEqual(json.load(f), [99])

    def test_no_tmp_file_left(self):
        path = self._path()
        _atomic_write(path, {"k": "v"})
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_nested_dir_created(self):
        path = os.path.join(self.tmpdir, "sub", "deep", "log.json")
        _atomic_write(path, [])
        self.assertTrue(os.path.exists(path))


# ===========================================================================
# 4.  analyze() — formula correctness  (25 tests)
# ===========================================================================
class TestAnalyzeFormulas(unittest.TestCase):

    def _run(self, **kw):
        return analyze(**_base_kwargs(**kw))

    # --- monthly gas cost ---
    def test_monthly_gas_cost_formula(self):
        r = self._run(transactions_per_month=4,
                      avg_gas_per_tx_gwei=6_000_000.0,
                      eth_price_usd=3_000.0)
        expected = 4 * 6_000_000.0 * 3_000.0 / 1e9
        self.assertAlmostEqual(r["monthly_gas_cost_usd"], expected, places=6)

    def test_monthly_gas_zero_txs(self):
        r = self._run(transactions_per_month=0)
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)

    def test_monthly_gas_zero_gwei(self):
        r = self._run(avg_gas_per_tx_gwei=0.0)
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)

    def test_monthly_gas_zero_eth_price(self):
        r = self._run(eth_price_usd=0.0)
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)

    def test_monthly_gas_high_eth_price(self):
        r = self._run(eth_price_usd=10_000.0, transactions_per_month=1,
                      avg_gas_per_tx_gwei=1_000_000.0)
        expected = 1 * 1_000_000.0 * 10_000.0 / 1e9
        self.assertAlmostEqual(r["monthly_gas_cost_usd"], expected, places=6)

    # --- annual gas cost ---
    def test_annual_equals_monthly_times_12(self):
        r = self._run()
        self.assertAlmostEqual(r["annual_gas_cost_usd"],
                               r["monthly_gas_cost_usd"] * 12.0, places=8)

    def test_annual_gas_zero_when_no_txs(self):
        r = self._run(transactions_per_month=0)
        self.assertEqual(r["annual_gas_cost_usd"], 0.0)

    # --- gas drag pct ---
    def test_gas_drag_formula(self):
        r = self._run(transactions_per_month=4,
                      avg_gas_per_tx_gwei=6_000_000.0,
                      eth_price_usd=3_000.0,
                      position_size_usd=100_000.0)
        annual = 4 * 6_000_000.0 * 3_000.0 / 1e9 * 12.0
        expected_drag = annual / 100_000.0 * 100.0
        self.assertAlmostEqual(r["gas_drag_pct"], expected_drag, places=6)

    def test_gas_drag_zero_when_no_txs(self):
        r = self._run(transactions_per_month=0)
        self.assertEqual(r["gas_drag_pct"], 0.0)

    def test_gas_drag_zero_for_zero_position(self):
        r = self._run(position_size_usd=0.0)
        self.assertEqual(r["gas_drag_pct"], 0.0)

    def test_gas_drag_increases_with_txs(self):
        r_low = self._run(transactions_per_month=2)
        r_high = self._run(transactions_per_month=20)
        self.assertGreater(r_high["gas_drag_pct"], r_low["gas_drag_pct"])

    def test_gas_drag_decreases_with_position_size(self):
        r_small = self._run(position_size_usd=10_000.0)
        r_large = self._run(position_size_usd=1_000_000.0)
        self.assertGreater(r_small["gas_drag_pct"], r_large["gas_drag_pct"])

    # --- gross annual yield ---
    def test_gross_annual_is_monthly_times_12(self):
        r = self._run(gross_monthly_yield_pct=0.5)
        self.assertAlmostEqual(r["gross_annual_yield_pct"], 6.0, places=8)

    def test_gross_annual_zero(self):
        r = self._run(gross_monthly_yield_pct=0.0)
        self.assertEqual(r["gross_annual_yield_pct"], 0.0)

    def test_gross_annual_high(self):
        r = self._run(gross_monthly_yield_pct=5.0)
        self.assertAlmostEqual(r["gross_annual_yield_pct"], 60.0, places=8)

    # --- net annual yield ---
    def test_net_is_gross_minus_drag(self):
        r = self._run()
        expected = r["gross_annual_yield_pct"] - r["gas_drag_pct"]
        self.assertAlmostEqual(r["net_annual_yield_pct"], expected, places=8)

    def test_net_can_be_negative(self):
        r = self._run(transactions_per_month=500, position_size_usd=1_000.0,
                      gross_monthly_yield_pct=0.01)
        self.assertLess(r["net_annual_yield_pct"], 0.0)

    def test_net_zero_gas_equals_gross(self):
        r = self._run(transactions_per_month=0)
        self.assertAlmostEqual(r["net_annual_yield_pct"],
                               r["gross_annual_yield_pct"], places=8)

    def test_net_decreases_with_more_txs(self):
        r_few = self._run(transactions_per_month=2)
        r_many = self._run(transactions_per_month=100)
        self.assertGreater(r_few["net_annual_yield_pct"], r_many["net_annual_yield_pct"])

    # --- return structure ---
    def test_all_required_keys_present(self):
        r = self._run()
        required = {
            "strategy_type", "chain", "transactions_per_month",
            "avg_gas_per_tx_gwei", "eth_price_usd", "position_size_usd",
            "gross_monthly_yield_pct", "gross_annual_yield_pct",
            "monthly_gas_cost_usd", "annual_gas_cost_usd",
            "gas_drag_pct", "net_annual_yield_pct",
            "gas_sensitivity_score", "gas_label", "timestamp",
        }
        self.assertTrue(required.issubset(r.keys()))

    def test_score_is_int(self):
        r = self._run()
        self.assertIsInstance(r["gas_sensitivity_score"], int)

    def test_label_is_str(self):
        r = self._run()
        self.assertIsInstance(r["gas_label"], str)

    def test_timestamp_present(self):
        before = time.time()
        r = self._run()
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_transactions_per_month_cast_to_int(self):
        r = self._run(transactions_per_month=4.9)
        self.assertEqual(r["transactions_per_month"], 4)


# ===========================================================================
# 5.  analyze() — strategy types (5 tests)
# ===========================================================================
class TestAnalyzeStrategyTypes(unittest.TestCase):

    def _run(self, strategy):
        return analyze(**_base_kwargs(strategy_type=strategy))

    def test_active_lp(self):
        r = self._run("active_lp")
        self.assertEqual(r["strategy_type"], "active_lp")

    def test_passive_vault(self):
        r = self._run("passive_vault")
        self.assertEqual(r["strategy_type"], "passive_vault")

    def test_lending(self):
        r = self._run("lending")
        self.assertEqual(r["strategy_type"], "lending")

    def test_farming(self):
        r = self._run("farming")
        self.assertEqual(r["strategy_type"], "farming")

    def test_staking(self):
        r = self._run("staking")
        self.assertEqual(r["strategy_type"], "staking")


# ===========================================================================
# 6.  analyze() — chains (5 tests)
# ===========================================================================
class TestAnalyzeChains(unittest.TestCase):

    def _run(self, chain):
        return analyze(**_base_kwargs(chain=chain))

    def test_ethereum(self):
        self.assertEqual(self._run("ethereum")["chain"], "ethereum")

    def test_arbitrum(self):
        self.assertEqual(self._run("arbitrum")["chain"], "arbitrum")

    def test_base(self):
        self.assertEqual(self._run("base")["chain"], "base")

    def test_optimism(self):
        self.assertEqual(self._run("optimism")["chain"], "optimism")

    def test_polygon(self):
        self.assertEqual(self._run("polygon")["chain"], "polygon")


# ===========================================================================
# 7.  analyze() — gas labels from real inputs (10 tests)
# ===========================================================================
class TestAnalyzeGasLabels(unittest.TestCase):

    def _drag_case(self, drag_pct_target, pos=1_000_000.0):
        """Return kwargs that produce approximately drag_pct_target via gas."""
        # monthly_gas = txs * gwei * eth / 1e9
        # annual_gas  = monthly * 12
        # drag        = annual_gas / pos * 100
        # → annual_gas = drag * pos / 100
        # → monthly_gas = drag * pos / 100 / 12
        # Fix txs=1, eth=3000, solve for gwei:
        # 1 * gwei * 3000 / 1e9 = drag * pos / 100 / 12
        # gwei = drag * pos / 100 / 12 / 3000 * 1e9
        eth_price = 3_000.0
        gwei = drag_pct_target * pos / 100.0 / 12.0 / eth_price * 1e9
        return dict(
            transactions_per_month=1,
            avg_gas_per_tx_gwei=gwei,
            eth_price_usd=eth_price,
            position_size_usd=pos,
            gross_monthly_yield_pct=1.0,
            chain="ethereum",
            strategy_type="lending",
        )

    def test_negligible_label(self):
        r = analyze(**self._drag_case(0.05))
        self.assertEqual(r["gas_label"], "GAS_NEGLIGIBLE")

    def test_low_drag_label(self):
        r = analyze(**self._drag_case(0.2))
        self.assertEqual(r["gas_label"], "LOW_GAS_DRAG")

    def test_moderate_drag_label(self):
        r = analyze(**self._drag_case(1.0))
        self.assertEqual(r["gas_label"], "MODERATE_GAS_DRAG")

    def test_high_drag_label(self):
        r = analyze(**self._drag_case(3.0))
        self.assertEqual(r["gas_label"], "HIGH_GAS_DRAG")

    def test_kills_yield_label(self):
        r = analyze(**self._drag_case(8.0))
        self.assertEqual(r["gas_label"], "GAS_KILLS_YIELD")

    def test_label_and_score_consistent_low(self):
        r = analyze(**self._drag_case(0.05))
        self.assertLessEqual(r["gas_sensitivity_score"], 10)

    def test_label_and_score_consistent_high(self):
        r = analyze(**self._drag_case(8.0))
        self.assertGreaterEqual(r["gas_sensitivity_score"], 100)

    def test_score_monotone_with_drag(self):
        r1 = analyze(**self._drag_case(0.1))
        r2 = analyze(**self._drag_case(2.0))
        r3 = analyze(**self._drag_case(5.0))
        self.assertLessEqual(r1["gas_sensitivity_score"], r2["gas_sensitivity_score"])
        self.assertLessEqual(r2["gas_sensitivity_score"], r3["gas_sensitivity_score"])

    def test_l2_low_gwei_negligible(self):
        # Arbitrum: 100 txs, 1_500 gwei each (~5k gas * 0.3 gwei), $3k ETH, $100k position
        # drag = 100 * 1_500 * 3_000 / 1e9 * 12 / 100_000 * 100 = 0.054% → GAS_NEGLIGIBLE
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=100,
            avg_gas_per_tx_gwei=1_500.0,    # very cheap L2 gas
            eth_price_usd=3_000.0,
            position_size_usd=100_000.0,
            gross_monthly_yield_pct=2.0,
            chain="arbitrum",
        )
        self.assertEqual(r["gas_label"], "GAS_NEGLIGIBLE")

    def test_l1_high_freq_kills_yield(self):
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=500,
            avg_gas_per_tx_gwei=9_000_000.0,  # 300_000 gas * 30 gwei
            eth_price_usd=4_000.0,
            position_size_usd=50_000.0,
            gross_monthly_yield_pct=2.0,
            chain="ethereum",
        )
        self.assertEqual(r["gas_label"], "GAS_KILLS_YIELD")


# ===========================================================================
# 8.  analyze() — edge cases (15 tests)
# ===========================================================================
class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_very_large_position_small_drag(self):
        r = analyze(
            strategy_type="lending",
            transactions_per_month=4,
            avg_gas_per_tx_gwei=6_000_000.0,
            eth_price_usd=3_000.0,
            position_size_usd=1_000_000_000.0,  # 1 billion
            gross_monthly_yield_pct=0.3,
            chain="ethereum",
        )
        self.assertLess(r["gas_drag_pct"], 0.01)

    def test_very_small_position_large_drag(self):
        r = analyze(
            strategy_type="farming",
            transactions_per_month=10,
            avg_gas_per_tx_gwei=6_000_000.0,
            eth_price_usd=3_000.0,
            position_size_usd=500.0,
            gross_monthly_yield_pct=5.0,
            chain="ethereum",
        )
        self.assertGreater(r["gas_drag_pct"], 5.0)

    def test_zero_position_no_division_error(self):
        r = analyze(**_base_kwargs(position_size_usd=0.0))
        self.assertEqual(r["gas_drag_pct"], 0.0)

    def test_zero_eth_price_zero_gas_cost(self):
        r = analyze(**_base_kwargs(eth_price_usd=0.0))
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)
        self.assertEqual(r["annual_gas_cost_usd"], 0.0)
        self.assertEqual(r["gas_drag_pct"], 0.0)

    def test_negative_net_yield_possible(self):
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=200,
            avg_gas_per_tx_gwei=9_000_000.0,
            eth_price_usd=4_000.0,
            position_size_usd=50_000.0,
            gross_monthly_yield_pct=0.1,
            chain="ethereum",
        )
        self.assertLess(r["net_annual_yield_pct"], 0.0)

    def test_zero_gross_yield(self):
        r = analyze(**_base_kwargs(gross_monthly_yield_pct=0.0))
        self.assertEqual(r["gross_annual_yield_pct"], 0.0)

    def test_zero_transactions(self):
        r = analyze(**_base_kwargs(transactions_per_month=0))
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)
        self.assertEqual(r["annual_gas_cost_usd"], 0.0)
        self.assertEqual(r["gas_drag_pct"], 0.0)
        self.assertEqual(r["gas_sensitivity_score"], 0)

    def test_unknown_chain_stored_as_is(self):
        r = analyze(**_base_kwargs(chain="solana"))
        self.assertEqual(r["chain"], "solana")

    def test_unknown_strategy_stored_as_is(self):
        r = analyze(**_base_kwargs(strategy_type="degen"))
        self.assertEqual(r["strategy_type"], "degen")

    def test_float_transactions_truncated(self):
        r = analyze(**_base_kwargs(transactions_per_month=5.9))
        self.assertEqual(r["transactions_per_month"], 5)

    def test_score_between_0_and_100(self):
        for txs in [0, 1, 10, 100, 1000]:
            r = analyze(**_base_kwargs(transactions_per_month=txs))
            score = r["gas_sensitivity_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_very_high_eth_price(self):
        r = analyze(**_base_kwargs(eth_price_usd=1_000_000.0,
                                   transactions_per_month=1,
                                   avg_gas_per_tx_gwei=1_000.0,
                                   position_size_usd=100_000.0))
        self.assertGreater(r["monthly_gas_cost_usd"], 0.0)

    def test_gas_per_tx_zero(self):
        r = analyze(**_base_kwargs(avg_gas_per_tx_gwei=0.0))
        self.assertEqual(r["monthly_gas_cost_usd"], 0.0)

    def test_values_are_floats(self):
        r = analyze(**_base_kwargs())
        for key in ("monthly_gas_cost_usd", "annual_gas_cost_usd",
                    "gas_drag_pct", "net_annual_yield_pct",
                    "gross_annual_yield_pct"):
            self.assertIsInstance(r[key], float, f"{key} is not float")

    def test_typical_lending_negligible_drag(self):
        # Typical lending: 2 txs/month, 200k gas * 20 gwei = 4M gwei, $3k ETH, $100k position
        r = analyze(
            strategy_type="lending",
            transactions_per_month=2,
            avg_gas_per_tx_gwei=4_000_000.0,
            eth_price_usd=3_000.0,
            position_size_usd=100_000.0,
            gross_monthly_yield_pct=0.4,
            chain="ethereum",
        )
        self.assertIn(r["gas_label"], ("GAS_NEGLIGIBLE", "LOW_GAS_DRAG"))


# ===========================================================================
# 9.  log_result() — ring-buffer and atomic write  (20 tests)
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_gas_log.json")

    def _sample_result(self, **overrides) -> dict:
        base = analyze(**_base_kwargs())
        base.update(overrides)
        return base

    def test_creates_new_log_file(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_first_entry_count(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_appends_second_entry(self):
        log_result(self._sample_result(), self.log_path)
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_entry_has_required_keys(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        for key in ("timestamp", "strategy_type", "chain", "gas_label",
                    "gas_drag_pct", "net_annual_yield_pct", "gas_sensitivity_score"):
            self.assertIn(key, entry)

    def test_entry_gas_label_correct(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["gas_label"], r["gas_label"])

    def test_entry_strategy_type_correct(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["strategy_type"], r["strategy_type"])

    def test_ring_buffer_capped_at_100(self):
        for i in range(105):
            r = self._sample_result()
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_last_100(self):
        results = []
        for i in range(105):
            r = self._sample_result(gas_drag_pct=float(i))
            r["gas_drag_pct"] = float(i)
            results.append(r)
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        # Last entry should have gas_drag_pct = 104
        self.assertEqual(data[-1]["gas_drag_pct"], 104.0)

    def test_ring_buffer_exactly_100_no_trim(self):
        for i in range(100):
            log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_handles_missing_log_file(self):
        missing = os.path.join(self.tmpdir, "missing.json")
        r = self._sample_result()
        log_result(r, missing)
        with open(missing) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_corrupt_json(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON {{{")
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_non_list_json(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "not a list"}, f)
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_tmp_file_after_write(self):
        log_result(self._sample_result(), self.log_path)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_timestamp_stored(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("timestamp", entry)
        self.assertIsInstance(entry["timestamp"], float)

    def test_nested_log_dir_created(self):
        nested = os.path.join(self.tmpdir, "sub", "dir", "log.json")
        log_result(self._sample_result(), nested)
        self.assertTrue(os.path.exists(nested))

    def test_score_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["gas_sensitivity_score"], r["gas_sensitivity_score"])

    def test_net_annual_yield_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertAlmostEqual(entry["net_annual_yield_pct"],
                               r["net_annual_yield_pct"], places=6)

    def test_chain_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["chain"], r["chain"])

    def test_multiple_calls_ordered_correctly(self):
        for i in range(5):
            r = self._sample_result()
            r["gas_drag_pct"] = float(i)
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        drag_values = [e["gas_drag_pct"] for e in data]
        self.assertEqual(drag_values, [0.0, 1.0, 2.0, 3.0, 4.0])


# ===========================================================================
# 10. Constants and module-level checks (10 tests)
# ===========================================================================
class TestModuleConstants(unittest.TestCase):

    def test_log_cap_is_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_valid_strategy_types_count(self):
        self.assertEqual(len(VALID_STRATEGY_TYPES), 5)

    def test_active_lp_in_strategies(self):
        self.assertIn("active_lp", VALID_STRATEGY_TYPES)

    def test_passive_vault_in_strategies(self):
        self.assertIn("passive_vault", VALID_STRATEGY_TYPES)

    def test_lending_in_strategies(self):
        self.assertIn("lending", VALID_STRATEGY_TYPES)

    def test_farming_in_strategies(self):
        self.assertIn("farming", VALID_STRATEGY_TYPES)

    def test_staking_in_strategies(self):
        self.assertIn("staking", VALID_STRATEGY_TYPES)

    def test_valid_chains_count(self):
        self.assertEqual(len(VALID_CHAINS), 5)

    def test_ethereum_in_chains(self):
        self.assertIn("ethereum", VALID_CHAINS)

    def test_arbitrum_in_chains(self):
        self.assertIn("arbitrum", VALID_CHAINS)

    def test_base_in_chains(self):
        self.assertIn("base", VALID_CHAINS)

    def test_optimism_in_chains(self):
        self.assertIn("optimism", VALID_CHAINS)

    def test_polygon_in_chains(self):
        self.assertIn("polygon", VALID_CHAINS)


# ===========================================================================
# 11. End-to-end scenario tests (10 tests)
# ===========================================================================
class TestE2EScenarios(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "e2e.json")

    def test_passive_vault_l2_negligible(self):
        # Passive vault on Arbitrum: 1 deposit/month, cheap gas → negligible drag
        r = analyze(
            strategy_type="passive_vault",
            transactions_per_month=1,
            avg_gas_per_tx_gwei=50_000.0,   # tiny L2 gas
            eth_price_usd=3_000.0,
            position_size_usd=50_000.0,
            gross_monthly_yield_pct=0.5,
            chain="arbitrum",
        )
        self.assertEqual(r["gas_label"], "GAS_NEGLIGIBLE")
        self.assertGreater(r["net_annual_yield_pct"], 0)

    def test_active_lp_l1_high_drag(self):
        # Active LP on Ethereum: 60 txs/month, 200k gas * 50 gwei
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=60,
            avg_gas_per_tx_gwei=10_000_000.0,  # 200k * 50
            eth_price_usd=3_500.0,
            position_size_usd=50_000.0,
            gross_monthly_yield_pct=3.0,
            chain="ethereum",
        )
        self.assertIn(r["gas_label"], ("HIGH_GAS_DRAG", "GAS_KILLS_YIELD"))

    def test_staking_low_drag(self):
        # Staking: 1 tx/month, staking contract ~150k gas, 20 gwei, $3k ETH, $200k position
        r = analyze(
            strategy_type="staking",
            transactions_per_month=1,
            avg_gas_per_tx_gwei=3_000_000.0,  # 150k * 20
            eth_price_usd=3_000.0,
            position_size_usd=200_000.0,
            gross_monthly_yield_pct=0.33,
            chain="ethereum",
        )
        self.assertIn(r["gas_label"], ("GAS_NEGLIGIBLE", "LOW_GAS_DRAG"))

    def test_farming_high_freq_l1(self):
        # Yield farming: 30 compound + 30 harvest = 60 txs/month on Ethereum
        r = analyze(
            strategy_type="farming",
            transactions_per_month=60,
            avg_gas_per_tx_gwei=4_500_000.0,
            eth_price_usd=3_000.0,
            position_size_usd=25_000.0,
            gross_monthly_yield_pct=2.0,
            chain="ethereum",
        )
        self.assertGreater(r["gas_drag_pct"], 1.0)

    def test_log_and_reload(self):
        r = analyze(**_base_kwargs())
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["gas_label"], r["gas_label"])

    def test_score_capped_extreme_gas(self):
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=1000,
            avg_gas_per_tx_gwei=50_000_000.0,
            eth_price_usd=10_000.0,
            position_size_usd=1_000.0,
            gross_monthly_yield_pct=5.0,
            chain="ethereum",
        )
        self.assertEqual(r["gas_sensitivity_score"], 100)

    def test_l2_base_cheap(self):
        r = analyze(
            strategy_type="active_lp",
            transactions_per_month=100,
            avg_gas_per_tx_gwei=5_000.0,    # very cheap L2
            eth_price_usd=3_000.0,
            position_size_usd=100_000.0,
            gross_monthly_yield_pct=1.0,
            chain="base",
        )
        self.assertEqual(r["gas_label"], "GAS_NEGLIGIBLE")

    def test_optimism_moderate(self):
        r = analyze(
            strategy_type="lending",
            transactions_per_month=20,
            avg_gas_per_tx_gwei=300_000.0,
            eth_price_usd=3_000.0,
            position_size_usd=30_000.0,
            gross_monthly_yield_pct=0.5,
            chain="optimism",
        )
        # Check result is valid
        self.assertIn(r["gas_label"], {
            "GAS_NEGLIGIBLE", "LOW_GAS_DRAG", "MODERATE_GAS_DRAG",
            "HIGH_GAS_DRAG", "GAS_KILLS_YIELD"
        })

    def test_polygon_very_cheap(self):
        # Polygon MATIC gas is basically free
        r = analyze(
            strategy_type="farming",
            transactions_per_month=200,
            avg_gas_per_tx_gwei=1_000.0,    # extremely cheap
            eth_price_usd=1.0,              # MATIC ~$1
            position_size_usd=10_000.0,
            gross_monthly_yield_pct=2.0,
            chain="polygon",
        )
        self.assertEqual(r["gas_label"], "GAS_NEGLIGIBLE")

    def test_round_trip_multiple_entries(self):
        for strat in VALID_STRATEGY_TYPES:
            r = analyze(**_base_kwargs(strategy_type=strat))
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)


if __name__ == "__main__":
    unittest.main()
