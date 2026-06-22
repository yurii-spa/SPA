# spa_core/tests/test_impermanent_loss_predictor.py
# MP-845 — Tests for ImpermanentLossPredictor
# Run: python3 -m unittest spa_core.tests.test_impermanent_loss_predictor -v

import json
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import spa_core.analytics.impermanent_loss_predictor as ilp


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_pos(
    protocol="UniV2",
    pair="ETH/USDC",
    price_entry=2000.0,
    price_current=2000.0,
    value_usd=10000.0,
    fee_apy=10.0,
    days=30,
    pool_type="VOLATILE",
):
    return {
        "protocol": protocol,
        "pair": pair,
        "token_a": pair.split("/")[0],
        "token_b": pair.split("/")[1],
        "price_ratio_entry": price_entry,
        "price_ratio_current": price_current,
        "position_value_usd": value_usd,
        "fee_apy": fee_apy,
        "days_in_position": days,
        "pool_type": pool_type,
    }


def _il_pct_expected(k: float) -> float:
    if k <= 0:
        return 0.0
    return (2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestILFormula(unittest.TestCase):
    """Tests for the core IL percentage calculation."""

    def test_k_equal_one_no_loss(self):
        """No price change → zero IL."""
        self.assertAlmostEqual(ilp._il_pct_from_k(1.0), 0.0, places=9)

    def test_k_double_price(self):
        """Price doubles → ~5.72% IL."""
        result = ilp._il_pct_from_k(2.0)
        expected = (2.0 * math.sqrt(2.0) / 3.0 - 1.0) * 100.0
        self.assertAlmostEqual(result, expected, places=6)
        self.assertLess(result, 0)

    def test_k_half_price(self):
        """Price halves → ~5.72% IL (symmetric)."""
        result = ilp._il_pct_from_k(0.5)
        expected = (2.0 * math.sqrt(0.5) / 1.5 - 1.0) * 100.0
        self.assertAlmostEqual(result, expected, places=6)
        self.assertLess(result, 0)

    def test_symmetry(self):
        """IL is symmetric: k and 1/k produce the same IL%."""
        for k in [2.0, 4.0, 0.25, 1.5]:
            self.assertAlmostEqual(
                ilp._il_pct_from_k(k), ilp._il_pct_from_k(1.0 / k), places=6,
                msg=f"Symmetry failed for k={k}"
            )

    def test_k_zero_returns_zero(self):
        self.assertEqual(ilp._il_pct_from_k(0.0), 0.0)

    def test_k_negative_returns_zero(self):
        self.assertEqual(ilp._il_pct_from_k(-1.0), 0.0)

    def test_large_k(self):
        """Very large k → significant IL."""
        result = ilp._il_pct_from_k(100.0)
        self.assertLess(result, -50.0)

    def test_il_always_negative_or_zero(self):
        """IL is always <= 0."""
        for k in [0.1, 0.5, 0.9, 1.0, 1.1, 2.0, 5.0, 10.0]:
            self.assertLessEqual(ilp._il_pct_from_k(k), 0.0)

    def test_k_four_times(self):
        """Price 4x → ~20% IL."""
        result = ilp._il_pct_from_k(4.0)
        expected = (2.0 * 2.0 / 5.0 - 1.0) * 100.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_k_quarter(self):
        result = ilp._il_pct_from_k(0.25)
        expected = (2.0 * 0.5 / 1.25 - 1.0) * 100.0
        self.assertAlmostEqual(result, expected, places=6)


class TestScenarioAnalysis(unittest.TestCase):
    """Tests for _scenario_analysis."""

    def setUp(self):
        self.value = 10000.0
        self.fee_apy = 10.0
        self.scenarios = [0.5, 1.0, 2.0]

    def test_returns_correct_count(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, self.scenarios)
        self.assertEqual(len(result), 3)

    def test_k1_zero_il(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [1.0])
        self.assertAlmostEqual(result[0]["il_pct"], 0.0, places=6)
        self.assertAlmostEqual(result[0]["il_usd"], 0.0, places=6)

    def test_k1_fee_recoup_zero(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [1.0])
        self.assertEqual(result[0]["fee_recoup_days"], 0.0)

    def test_k2_il_negative(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [2.0])
        self.assertLess(result[0]["il_pct"], 0)

    def test_k2_il_usd_positive(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [2.0])
        self.assertGreater(result[0]["il_usd"], 0)

    def test_fee_recoup_days_positive(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [2.0])
        days = result[0]["fee_recoup_days"]
        self.assertIsNotNone(days)
        self.assertGreater(days, 0)

    def test_zero_fee_apy_recoup_none(self):
        result = ilp._scenario_analysis(10000.0, 0.0, [2.0])
        self.assertIsNone(result[0]["fee_recoup_days"])

    def test_value_zero_all_usd_zero(self):
        result = ilp._scenario_analysis(0.0, 10.0, [2.0])
        self.assertAlmostEqual(result[0]["il_usd"], 0.0, places=6)
        self.assertEqual(result[0]["fee_recoup_days"], 0.0)

    def test_multiplier_stored(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [0.75])
        self.assertAlmostEqual(result[0]["price_multiplier"], 0.75, places=6)

    def test_multiple_scenarios_ordered(self):
        result = ilp._scenario_analysis(self.value, self.fee_apy, [0.5, 1.0, 2.0, 4.0])
        # IL should increase (more negative) as k diverges from 1
        self.assertLess(result[0]["il_pct"], result[1]["il_pct"])  # 0.5 < 1.0
        self.assertLess(result[2]["il_pct"], result[1]["il_pct"])  # 2.0 < 1.0

    def test_il_usd_formula(self):
        result = ilp._scenario_analysis(10000.0, 10.0, [2.0])
        expected_il = abs(_il_pct_expected(2.0)) / 100.0 * 10000.0
        self.assertAlmostEqual(result[0]["il_usd"], expected_il, places=4)


class TestAnalyzeBasic(unittest.TestCase):
    """Tests for the main analyze() function."""

    def setUp(self):
        # Patch out the log writer for most tests
        self.patcher = patch.object(ilp, "_append_log")
        self.mock_log = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_empty_positions_returns_zero_totals(self):
        result = ilp.analyze([])
        self.assertEqual(result["total_il_usd"], 0.0)
        self.assertEqual(result["total_fee_income_usd"], 0.0)
        self.assertEqual(result["total_net_pnl_usd"], 0.0)
        self.assertIsNone(result["worst_position"])
        self.assertIsNone(result["best_position"])

    def test_empty_positions_positions_list_empty(self):
        result = ilp.analyze([])
        self.assertEqual(result["positions"], [])

    def test_single_position_no_price_change(self):
        pos = _make_pos()
        result = ilp.analyze([pos])
        self.assertEqual(len(result["positions"]), 1)
        p = result["positions"][0]
        self.assertAlmostEqual(p["il_pct"], 0.0, places=6)
        self.assertAlmostEqual(p["il_usd"], 0.0, places=6)

    def test_no_price_change_profitable(self):
        pos = _make_pos(fee_apy=10.0, days=30)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["verdict"], "PROFITABLE")

    def test_price_doubled_il_negative(self):
        pos = _make_pos(price_current=4000.0, price_entry=2000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertLess(p["il_pct"], 0)

    def test_price_doubled_correct_il_pct(self):
        pos = _make_pos(price_current=4000.0, price_entry=2000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        expected = _il_pct_expected(2.0)
        self.assertAlmostEqual(p["il_pct"], expected, places=4)

    def test_price_doubled_il_usd(self):
        pos = _make_pos(price_current=4000.0, price_entry=2000.0, value_usd=10000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        expected = abs(_il_pct_expected(2.0)) / 100.0 * 10000.0
        self.assertAlmostEqual(p["il_usd"], expected, places=4)

    def test_price_change_pct(self):
        pos = _make_pos(price_current=3000.0, price_entry=2000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["price_change_pct"], 50.0, places=4)

    def test_price_halved_price_change_pct(self):
        pos = _make_pos(price_current=1000.0, price_entry=2000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["price_change_pct"], -50.0, places=4)

    def test_fee_income_calculation(self):
        pos = _make_pos(fee_apy=36.5, days=10, value_usd=10000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        expected = 36.5 / 100.0 / 365.0 * 10 * 10000.0
        self.assertAlmostEqual(p["fee_income_usd"], expected, places=4)

    def test_zero_fee_apy_fee_income_zero(self):
        pos = _make_pos(fee_apy=0.0, days=30)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["fee_income_usd"], 0.0, places=6)

    def test_zero_days_fee_income_zero(self):
        pos = _make_pos(days=0, fee_apy=10.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["fee_income_usd"], 0.0, places=6)

    def test_net_pnl_is_fee_minus_il(self):
        pos = _make_pos(price_current=3000.0, fee_apy=20.0, days=60, value_usd=10000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["net_pnl_usd"], p["fee_income_usd"] - p["il_usd"], places=4)

    def test_timestamp_present(self):
        result = ilp.analyze([])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        result = ilp.analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_skips_zero_entry_price(self):
        pos = _make_pos(price_entry=0.0)
        result = ilp.analyze([pos])
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["errors"]), 1)

    def test_multiple_positions(self):
        positions = [_make_pos(pair=f"A{i}/B{i}", price_entry=100.0 * i) for i in range(1, 4)]
        result = ilp.analyze(positions)
        self.assertEqual(len(result["positions"]), 3)

    def test_total_il_usd_sum(self):
        positions = [
            _make_pos(price_current=3000.0, price_entry=2000.0, value_usd=5000.0),
            _make_pos(price_current=1500.0, price_entry=2000.0, value_usd=5000.0),
        ]
        result = ilp.analyze(positions)
        manual_sum = sum(p["il_usd"] for p in result["positions"])
        self.assertAlmostEqual(result["total_il_usd"], manual_sum, places=4)

    def test_total_fee_income_sum(self):
        positions = [
            _make_pos(fee_apy=10.0, days=30, value_usd=5000.0),
            _make_pos(fee_apy=20.0, days=60, value_usd=5000.0),
        ]
        result = ilp.analyze(positions)
        manual_sum = sum(p["fee_income_usd"] for p in result["positions"])
        self.assertAlmostEqual(result["total_fee_income_usd"], manual_sum, places=4)

    def test_default_scenarios_four_entries(self):
        pos = _make_pos()
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertEqual(len(p["scenarios"]), 4)

    def test_custom_scenarios(self):
        pos = _make_pos()
        result = ilp.analyze([pos], config={"scenarios": [1.5, 3.0]})
        p = result["positions"][0]
        self.assertEqual(len(p["scenarios"]), 2)


class TestVerdicts(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_profitable_verdict(self):
        # High fee, no price change → profitable
        pos = _make_pos(fee_apy=100.0, days=365, price_current=2000.0)
        result = ilp.analyze([pos])
        self.assertEqual(result["positions"][0]["verdict"], "PROFITABLE")

    def test_loss_verdict_moderate_il(self):
        # Big IL, short time, low fees → LOSS (il_pct > -10)
        pos = _make_pos(
            price_current=3000.0,   # k=1.5, IL≈~2%
            fee_apy=0.1,
            days=1,
            value_usd=10000.0,
        )
        result = ilp.analyze([pos])
        p = result["positions"][0]
        # net_pnl negative and il_pct > -10 → LOSS
        if p["net_pnl_usd"] < -1 and p["il_pct"] > -10:
            self.assertEqual(p["verdict"], "LOSS")

    def test_severe_loss_verdict(self):
        # Price 10x → IL > 10% → SEVERE_LOSS with low fees
        pos = _make_pos(
            price_current=20000.0,   # k=10
            price_entry=2000.0,
            fee_apy=0.0,
            days=1,
            value_usd=10000.0,
        )
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["verdict"], "SEVERE_LOSS")

    def test_breakeven_verdict_net_near_zero(self):
        # net_pnl very close to zero
        # IL for k=1 → 0, fee=0 → net=0
        pos = _make_pos(fee_apy=0.0, price_current=2000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["verdict"], "BREAKEVEN")

    def test_profitable_large_fees(self):
        pos = _make_pos(fee_apy=500.0, days=30, price_current=3000.0)
        result = ilp.analyze([pos])
        self.assertEqual(result["positions"][0]["verdict"], "PROFITABLE")

    def test_severe_loss_requires_il_pct_lte_minus_ten(self):
        """SEVERE_LOSS only when il_pct <= -10."""
        # k=2 → il≈-5.72%, not severe
        pos = _make_pos(price_current=4000.0, fee_apy=0.0, days=1)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        # il_pct is about -5.72%, so not SEVERE_LOSS
        self.assertNotEqual(p["verdict"], "SEVERE_LOSS")


class TestBreakEvenDays(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_zero_fee_break_even_none(self):
        pos = _make_pos(fee_apy=0.0, price_current=3000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertIsNone(p["break_even_days"])

    def test_no_il_break_even_zero(self):
        pos = _make_pos(fee_apy=10.0, price_current=2000.0, days=30)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["break_even_days"], 0.0, places=4)

    def test_already_recouped_break_even_zero(self):
        # Big fee, small IL, many days → already profitable → break_even=0
        pos = _make_pos(fee_apy=200.0, days=365, price_current=2100.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["break_even_days"], 0.0, places=4)

    def test_break_even_days_formula(self):
        # Construct exact values: value=10000, fee_apy=36.5% → daily=$10
        # days=0, price k=2 → il_usd ≈ 572.87
        # il_usd / daily_fee + days = 572.87 / 10 + 0 ≈ 57.287 days
        pos = _make_pos(
            fee_apy=36.5,
            days=0,
            value_usd=10000.0,
            price_current=4000.0,
            price_entry=2000.0,
        )
        result = ilp.analyze([pos])
        p = result["positions"][0]
        daily_fee = 36.5 / 100.0 / 365.0 * 10000.0
        il_usd = abs(_il_pct_expected(2.0)) / 100.0 * 10000.0
        expected = il_usd / daily_fee
        self.assertAlmostEqual(p["break_even_days"], expected, places=2)

    def test_break_even_days_with_existing_days(self):
        pos = _make_pos(
            fee_apy=36.5,
            days=10,
            value_usd=10000.0,
            price_current=4000.0,
            price_entry=2000.0,
        )
        result = ilp.analyze([pos])
        p = result["positions"][0]
        daily_fee = 36.5 / 100.0 / 365.0 * 10000.0
        fee_earned = daily_fee * 10
        il_usd = abs(_il_pct_expected(2.0)) / 100.0 * 10000.0
        remaining_il = il_usd - fee_earned
        if remaining_il > 0:
            expected = remaining_il / daily_fee + 10
            self.assertAlmostEqual(p["break_even_days"], expected, places=2)
        else:
            self.assertAlmostEqual(p["break_even_days"], 0.0, places=4)


class TestWorstBest(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_worst_position_identified(self):
        positions = [
            _make_pos(protocol="A", pair="A/B", price_current=4000.0),   # k=2 → bigger IL
            _make_pos(protocol="B", pair="B/C", price_current=2200.0),   # small IL
        ]
        result = ilp.analyze(positions)
        self.assertEqual(result["worst_position"], "A/A/B")

    def test_best_position_highest_net_pnl(self):
        positions = [
            _make_pos(protocol="A", pair="A/B", fee_apy=200.0, days=60),
            _make_pos(protocol="B", pair="B/C", fee_apy=1.0, days=1),
        ]
        result = ilp.analyze(positions)
        self.assertIn("A", result["best_position"])

    def test_single_position_worst_equals_best(self):
        pos = _make_pos()
        result = ilp.analyze([pos])
        self.assertEqual(result["worst_position"], result["best_position"])

    def test_empty_no_worst_best(self):
        result = ilp.analyze([])
        self.assertIsNone(result["worst_position"])
        self.assertIsNone(result["best_position"])


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_zero_position_value_zero_usd_metrics(self):
        pos = _make_pos(value_usd=0.0, price_current=4000.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["il_usd"], 0.0, places=6)
        self.assertAlmostEqual(p["fee_income_usd"], 0.0, places=6)
        self.assertAlmostEqual(p["net_pnl_usd"], 0.0, places=6)

    def test_zero_entry_price_skipped(self):
        pos = _make_pos(price_entry=0.0)
        result = ilp.analyze([pos])
        self.assertEqual(len(result["positions"]), 0)

    def test_error_reported_for_zero_entry(self):
        pos = _make_pos(price_entry=0.0)
        result = ilp.analyze([pos])
        self.assertTrue(len(result["errors"]) > 0)

    def test_negative_price_current_edge(self):
        # Negative current price treated as k<=0 → il_pct=0
        pos = _make_pos(price_current=-100.0, price_entry=100.0)
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["il_pct"], 0.0, places=6)

    def test_pool_type_stored(self):
        pos = _make_pos(pool_type="CONCENTRATED")
        result = ilp.analyze([pos])
        self.assertEqual(result["positions"][0]["pool_type"], "CONCENTRATED")

    def test_protocol_pair_stored(self):
        pos = _make_pos(protocol="Curve", pair="DAI/USDC")
        result = ilp.analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["protocol"], "Curve")
        self.assertEqual(p["pair"], "DAI/USDC")

    def test_none_config_uses_defaults(self):
        pos = _make_pos()
        result = ilp.analyze([pos], config=None)
        self.assertEqual(len(result["positions"][0]["scenarios"]), 4)

    def test_empty_config_uses_defaults(self):
        pos = _make_pos()
        result = ilp.analyze([pos], config={})
        self.assertEqual(len(result["positions"][0]["scenarios"]), 4)

    def test_mixed_valid_invalid(self):
        positions = [_make_pos(), _make_pos(price_entry=0.0)]
        result = ilp.analyze(positions)
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_very_high_fee_apy(self):
        pos = _make_pos(fee_apy=10000.0, days=1)
        result = ilp.analyze([pos])
        # Should not crash; fee income should be large
        self.assertGreater(result["positions"][0]["fee_income_usd"], 0)

    def test_many_days(self):
        pos = _make_pos(days=3650, fee_apy=5.0)
        result = ilp.analyze([pos])
        self.assertGreater(result["positions"][0]["fee_income_usd"], 0)

    def test_stable_pool_type_preserved(self):
        pos = _make_pos(pool_type="STABLE", price_current=1.001, price_entry=1.0)
        result = ilp.analyze([pos])
        self.assertEqual(result["positions"][0]["pool_type"], "STABLE")

    def test_aggregate_with_error_position(self):
        positions = [
            _make_pos(value_usd=5000.0, price_current=3000.0),
            _make_pos(price_entry=0.0),
        ]
        result = ilp.analyze(positions)
        # Aggregate should only reflect the valid position
        self.assertGreater(result["total_il_usd"], 0)


class TestRingBufferLog(unittest.TestCase):
    """Tests for the ring-buffer log mechanism."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_data_file = ilp.DATA_FILE
        ilp.DATA_FILE = Path(self.tmp_dir) / "il_log.json"

    def tearDown(self):
        ilp.DATA_FILE = self.orig_data_file

    def _run_analyze(self):
        pos = _make_pos()
        ilp.analyze([pos])

    def test_log_created(self):
        self._run_analyze()
        self.assertTrue(ilp.DATA_FILE.exists())

    def test_log_is_list(self):
        self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_grows_per_call(self):
        self._run_analyze()
        self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped(self):
        for _ in range(ilp.MAX_ENTRIES + 10):
            self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), ilp.MAX_ENTRIES)

    def test_log_entry_has_timestamp(self):
        self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_total_il(self):
        self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIn("total_il_usd", data[0])

    def test_log_entry_has_position_count(self):
        ilp.analyze([_make_pos(), _make_pos(pair="B/C", price_entry=100.0)])
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["position_count"], 2)

    def test_corrupted_log_recovers(self):
        ilp.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ilp.DATA_FILE, "w") as fh:
            fh.write("NOT JSON{{{")
        # Should not crash
        self._run_analyze()
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_atomic_write_no_partial_file(self):
        """tmp file should not remain after write."""
        self._run_analyze()
        tmp_path = ilp.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_log_keeps_newest_entries(self):
        """After capping, the newest entries are kept."""
        timestamps = []
        for i in range(ilp.MAX_ENTRIES + 5):
            pos = _make_pos()
            result = ilp.analyze([pos])
            if i >= ilp.MAX_ENTRIES:
                timestamps.append(result["timestamp"])
        with open(ilp.DATA_FILE) as fh:
            data = json.load(fh)
        # The last entry timestamp should match the last call
        self.assertAlmostEqual(data[-1]["timestamp"], timestamps[-1], delta=1.0)


class TestScenarioDefaults(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_default_scenario_multipliers(self):
        pos = _make_pos()
        result = ilp.analyze([pos])
        multipliers = [s["price_multiplier"] for s in result["positions"][0]["scenarios"]]
        self.assertEqual(multipliers, [0.5, 0.75, 1.25, 2.0])

    def test_scenario_0_5_il_pct(self):
        pos = _make_pos(value_usd=10000.0)
        result = ilp.analyze([pos])
        s = result["positions"][0]["scenarios"][0]
        expected = _il_pct_expected(0.5)
        self.assertAlmostEqual(s["il_pct"], expected, places=4)

    def test_scenario_2_0_il_pct(self):
        pos = _make_pos(value_usd=10000.0)
        result = ilp.analyze([pos])
        s = result["positions"][0]["scenarios"][3]
        expected = _il_pct_expected(2.0)
        self.assertAlmostEqual(s["il_pct"], expected, places=4)

    def test_scenario_il_usd_proportional_to_value(self):
        pos_a = _make_pos(value_usd=10000.0)
        pos_b = _make_pos(value_usd=20000.0)
        result_a = ilp.analyze([pos_a])
        result_b = ilp.analyze([pos_b])
        il_a = result_a["positions"][0]["scenarios"][3]["il_usd"]
        il_b = result_b["positions"][0]["scenarios"][3]["il_usd"]
        self.assertAlmostEqual(il_b, 2 * il_a, places=4)


class TestTotalNetPnl(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(ilp, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_total_net_pnl_matches_sum(self):
        positions = [
            _make_pos(fee_apy=50.0, days=30, price_current=3000.0),
            _make_pos(fee_apy=1.0, days=5, price_current=1000.0),
        ]
        result = ilp.analyze(positions)
        expected_sum = sum(p["net_pnl_usd"] for p in result["positions"])
        self.assertAlmostEqual(result["total_net_pnl_usd"], expected_sum, places=4)

    def test_all_profitable_positive_total_net(self):
        positions = [
            _make_pos(fee_apy=1000.0, days=30),
            _make_pos(fee_apy=1000.0, days=30, pair="B/C", price_entry=100.0),
        ]
        result = ilp.analyze(positions)
        self.assertGreater(result["total_net_pnl_usd"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
