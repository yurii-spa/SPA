# spa_core/tests/test_impermanent_loss_calculator.py
# MP-659 — Tests for ImpermanentLossCalculator (pure stdlib, unittest only)

import math
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.impermanent_loss_calculator import (
    ILResult,
    ImpermanentLossCalculator,
    LPPosition,
)


def _make_pos(
    pool_id="pool-A",
    token_a="ETH",
    token_b="USDC",
    entry_price=1000.0,
    current_price=1000.0,
    capital_usd=10000.0,
    fees_earned_usd=0.0,
) -> LPPosition:
    return LPPosition(
        pool_id=pool_id,
        token_a=token_a,
        token_b=token_b,
        entry_price=entry_price,
        current_price=current_price,
        capital_usd=capital_usd,
        fees_earned_usd=fees_earned_usd,
    )


class TestILRatio(unittest.TestCase):
    """Tests for the _il_ratio core formula."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    # --- k = 1 → no IL ---
    def test_k1_no_il(self):
        self.assertAlmostEqual(self.calc._il_ratio(1.0), 0.0, places=10)

    # --- k = 4 → -0.2 ---
    def test_k4_il_20pct(self):
        result = self.calc._il_ratio(4.0)
        # 2*sqrt(4)/(1+4)-1 = 2*2/5-1 = 4/5-1 = -0.2
        self.assertAlmostEqual(result, -0.2, places=10)

    # --- k = 0.25 → -0.2 (symmetric: 1/4x same as 4x) ---
    def test_k025_il_symmetric_to_k4(self):
        result = self.calc._il_ratio(0.25)
        # 2*sqrt(0.25)/(1+0.25)-1 = 2*0.5/1.25-1 = 1/1.25-1 = 0.8-1 = -0.2
        self.assertAlmostEqual(result, -0.2, places=10)

    # --- k = 0 → total loss ---
    def test_k0_total_loss(self):
        self.assertEqual(self.calc._il_ratio(0.0), -1.0)

    # --- negative ratio → total loss (guard) ---
    def test_negative_k_total_loss(self):
        self.assertEqual(self.calc._il_ratio(-1.0), -1.0)

    # --- k = 2 → ≈ -0.05719 ---
    def test_k2_approx(self):
        result = self.calc._il_ratio(2.0)
        expected = 2.0 * math.sqrt(2.0) / 3.0 - 1.0
        self.assertAlmostEqual(result, expected, places=10)

    # --- k = 9 → 2*3/10-1 = -0.4 ---
    def test_k9_il_40pct(self):
        result = self.calc._il_ratio(9.0)
        self.assertAlmostEqual(result, -0.4, places=10)

    # --- k = 0.111... (1/9) → same as 9x ---
    def test_k_one_ninth_symmetric(self):
        result = self.calc._il_ratio(1.0 / 9.0)
        self.assertAlmostEqual(result, -0.4, places=8)

    # --- k = 1.0 (boundary: exactly no divergence) ---
    def test_k1_exact_zero(self):
        self.assertEqual(self.calc._il_ratio(1.0), 0.0)

    # --- very large k → approaches -1 ---
    def test_very_large_k(self):
        result = self.calc._il_ratio(10000.0)
        self.assertLess(result, -0.9)
        self.assertGreater(result, -1.0)

    # --- small k close to 0 → approaches -1 ---
    def test_very_small_k(self):
        result = self.calc._il_ratio(0.0001)
        self.assertLess(result, -0.9)
        self.assertGreater(result, -1.0)

    # --- formula is always non-positive ---
    def test_always_non_positive(self):
        for k in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
            self.assertLessEqual(self.calc._il_ratio(k), 0.0)


class TestSeverity(unittest.TestCase):
    """Tests for _severity classification."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    def test_severity_none_exact_zero(self):
        self.assertEqual(self.calc._severity(0.0), "NONE")

    def test_severity_none_small(self):
        self.assertEqual(self.calc._severity(-0.0009), "NONE")

    def test_severity_none_boundary(self):
        # 0.001 is boundary: NONE requires abs < 0.001
        self.assertEqual(self.calc._severity(-0.0009999), "NONE")

    def test_severity_mild_at_boundary(self):
        self.assertEqual(self.calc._severity(-0.001), "MILD")

    def test_severity_mild_mid(self):
        self.assertEqual(self.calc._severity(-0.005), "MILD")

    def test_severity_mild_upper_boundary(self):
        self.assertEqual(self.calc._severity(-0.0099), "MILD")

    def test_severity_moderate_at_boundary(self):
        self.assertEqual(self.calc._severity(-0.01), "MODERATE")

    def test_severity_moderate_mid(self):
        self.assertEqual(self.calc._severity(-0.025), "MODERATE")

    def test_severity_moderate_upper(self):
        self.assertEqual(self.calc._severity(-0.0499), "MODERATE")

    def test_severity_severe_at_boundary(self):
        self.assertEqual(self.calc._severity(-0.05), "SEVERE")

    def test_severity_severe_high(self):
        self.assertEqual(self.calc._severity(-0.2), "SEVERE")

    def test_severity_severe_extreme(self):
        self.assertEqual(self.calc._severity(-0.9), "SEVERE")

    def test_severity_positive_zero(self):
        # zero IL pct → NONE (can happen at k=1)
        self.assertEqual(self.calc._severity(0.0), "NONE")


class TestVerdict(unittest.TestCase):
    """Tests for _verdict classification."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    def test_verdict_profitable_above_1(self):
        self.assertEqual(self.calc._verdict(1.01), "PROFITABLE")

    def test_verdict_profitable_high(self):
        self.assertEqual(self.calc._verdict(100.0), "PROFITABLE")

    def test_verdict_breakeven_zero(self):
        self.assertEqual(self.calc._verdict(0.0), "BREAKEVEN")

    def test_verdict_breakeven_just_below_1(self):
        self.assertEqual(self.calc._verdict(0.99), "BREAKEVEN")

    def test_verdict_breakeven_just_above_neg1(self):
        self.assertEqual(self.calc._verdict(-0.99), "BREAKEVEN")

    def test_verdict_losing_at_neg1(self):
        self.assertEqual(self.calc._verdict(-1.0), "LOSING")

    def test_verdict_losing_large(self):
        self.assertEqual(self.calc._verdict(-500.0), "LOSING")

    def test_verdict_breakeven_boundary_exactly_1(self):
        # net_pnl > 1.0 → PROFITABLE; exactly 1.0 is NOT > 1.0 → BREAKEVEN
        self.assertEqual(self.calc._verdict(1.0), "BREAKEVEN")

    def test_verdict_breakeven_boundary_exactly_neg1(self):
        # net_pnl > -1.0 → BREAKEVEN; exactly -1.0 is NOT > -1.0 → LOSING
        self.assertEqual(self.calc._verdict(-1.0), "LOSING")


class TestCalculate(unittest.TestCase):
    """Tests for the main calculate() method."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    # --- k = 1 (no price change): zero IL ---
    def test_no_price_change_zero_il(self):
        pos = _make_pos(entry_price=1000.0, current_price=1000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.il_pct, 0.0, places=5)
        self.assertAlmostEqual(r.price_ratio, 1.0, places=5)

    def test_no_price_change_hold_eq_lp(self):
        pos = _make_pos(entry_price=2000.0, current_price=2000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.hold_value_usd, r.lp_value_usd, places=3)

    # --- k = 4: price 4x up ---
    def test_k4_il_pct(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.il_pct, -0.2, places=5)

    def test_k4_il_usd_negative(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertLess(r.il_usd, 0.0)

    def test_k4_price_ratio(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.price_ratio, 4.0, places=5)

    # --- fees offsetting IL → PROFITABLE ---
    # At k=4: hold=25000, lp=20000, il_usd=-5000 → need fees > 5001 for PROFITABLE
    def test_fees_offset_il_profitable(self):
        pos = _make_pos(
            entry_price=1000.0,
            current_price=4000.0,
            capital_usd=10000.0,
            fees_earned_usd=6000.0,  # fees > |il_usd|=5000, net_pnl = +1000 > 1 → PROFITABLE
        )
        r = self.calc.calculate(pos)
        self.assertEqual(r.verdict, "PROFITABLE")

    # --- zero fees + IL → LOSING ---
    def test_no_fees_large_il_losing(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.verdict, "LOSING")

    # --- entry_price = 0 → price_ratio = 0, il_pct = -1.0 ---
    def test_zero_entry_price(self):
        pos = _make_pos(entry_price=0.0, current_price=1000.0, capital_usd=5000.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.price_ratio, 0.0)
        self.assertAlmostEqual(r.il_pct, -1.0, places=5)

    # --- breakeven_fees = -il_usd when il_usd < 0 ---
    def test_breakeven_fees_positive_when_il_negative(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertLess(r.il_usd, 0.0)
        self.assertAlmostEqual(r.breakeven_fees_usd, -r.il_usd, places=4)

    # --- breakeven_fees = 0 when il_usd >= 0 (k=1) ---
    def test_breakeven_fees_zero_no_il(self):
        pos = _make_pos(entry_price=1000.0, current_price=1000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.breakeven_fees_usd, 0.0)

    def test_breakeven_fees_zero_attribute(self):
        pos = _make_pos(entry_price=1000.0, current_price=1000.0, capital_usd=5000.0)
        r = self.calc.calculate(pos)
        # il_usd should be ~0 at k=1
        self.assertEqual(r.breakeven_fees_usd, 0.0)

    # --- net_pnl = fees + il_usd ---
    def test_net_pnl_sum(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0, fees_earned_usd=100.0)
        r = self.calc.calculate(pos)
        expected = round(r.fees_earned_usd + r.il_usd, 4)
        self.assertAlmostEqual(r.net_pnl_usd, expected, places=3)

    # --- net_pnl_pct = net_pnl / capital ---
    def test_net_pnl_pct(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0, fees_earned_usd=50.0)
        r = self.calc.calculate(pos)
        expected = round(r.net_pnl_usd / pos.capital_usd, 6)
        self.assertAlmostEqual(r.net_pnl_pct, expected, places=5)

    # --- net_pnl_pct = 0 when capital = 0 ---
    def test_net_pnl_pct_zero_capital(self):
        pos = _make_pos(entry_price=1000.0, current_price=2000.0, capital_usd=0.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.net_pnl_pct, 0.0)

    # --- pool_id, token_a, token_b preserved ---
    def test_fields_preserved(self):
        pos = _make_pos(pool_id="myPool", token_a="WBTC", token_b="DAI")
        r = self.calc.calculate(pos)
        self.assertEqual(r.pool_id, "myPool")
        self.assertEqual(r.token_a, "WBTC")
        self.assertEqual(r.token_b, "DAI")

    # --- lp_value < hold_value when IL exists ---
    def test_lp_value_less_than_hold(self):
        pos = _make_pos(entry_price=100.0, current_price=400.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertLess(r.lp_value_usd, r.hold_value_usd)

    # --- severity matches expected for k=4 (20% IL → SEVERE) ---
    def test_severity_severe_for_k4(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.severity, "SEVERE")

    # --- severity NONE for k=1 ---
    def test_severity_none_for_k1(self):
        pos = _make_pos(entry_price=1000.0, current_price=1000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertEqual(r.severity, "NONE")

    # --- price_ratio rounded to 6 decimal places ---
    def test_price_ratio_rounded(self):
        pos = _make_pos(entry_price=3.0, current_price=7.0)
        r = self.calc.calculate(pos)
        # price_ratio = 7/3 ≈ 2.333333
        self.assertAlmostEqual(r.price_ratio, round(7.0 / 3.0, 6), places=5)

    # --- entry_price and current_price rounded to 6 places ---
    def test_prices_rounded_in_result(self):
        pos = _make_pos(entry_price=1234.56789012, current_price=2345.67890123)
        r = self.calc.calculate(pos)
        self.assertEqual(r.entry_price, round(1234.56789012, 6))
        self.assertEqual(r.current_price, round(2345.67890123, 6))

    # --- BREAKEVEN when fees exactly offset small IL ---
    def test_breakeven_verdict(self):
        pos = _make_pos(entry_price=1000.0, current_price=1020.0, capital_usd=10000.0, fees_earned_usd=0.3)
        r = self.calc.calculate(pos)
        self.assertEqual(r.verdict, "BREAKEVEN")

    # --- k = 0.25 (price drops to 25%): same IL as k=4 ---
    def test_k025_symmetric_il(self):
        pos = _make_pos(entry_price=1000.0, current_price=250.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.il_pct, -0.2, places=5)

    # --- hold_value correct at k=4 ---
    def test_hold_value_k4(self):
        # hold_value = capital * (k+1)/2 = 10000 * (4+1)/2 = 25000
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.hold_value_usd, 25000.0, places=1)

    # --- IL result is an ILResult dataclass ---
    def test_result_type(self):
        pos = _make_pos()
        r = self.calc.calculate(pos)
        self.assertIsInstance(r, ILResult)

    # --- fees_earned_usd preserved in result ---
    def test_fees_earned_preserved(self):
        pos = _make_pos(fees_earned_usd=123.45)
        r = self.calc.calculate(pos)
        self.assertAlmostEqual(r.fees_earned_usd, 123.45, places=2)


class TestCalculateBatch(unittest.TestCase):
    """Tests for calculate_batch()."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    def test_batch_empty(self):
        self.assertEqual(self.calc.calculate_batch([]), [])

    def test_batch_single(self):
        pos = _make_pos()
        results = self.calc.calculate_batch([pos])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ILResult)

    def test_batch_multiple(self):
        positions = [
            _make_pos(pool_id="p1", entry_price=1000.0, current_price=2000.0),
            _make_pos(pool_id="p2", entry_price=1000.0, current_price=4000.0),
            _make_pos(pool_id="p3", entry_price=1000.0, current_price=1000.0),
        ]
        results = self.calc.calculate_batch(positions)
        self.assertEqual(len(results), 3)

    def test_batch_preserves_order(self):
        positions = [
            _make_pos(pool_id=f"pool-{i}", entry_price=float(i + 1) * 100) for i in range(5)
        ]
        results = self.calc.calculate_batch(positions)
        for i, r in enumerate(results):
            self.assertEqual(r.pool_id, f"pool-{i}")

    def test_batch_each_is_correct(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0)
        results = self.calc.calculate_batch([pos, pos])
        for r in results:
            self.assertAlmostEqual(r.il_pct, -0.2, places=5)


class TestWorstIL(unittest.TestCase):
    """Tests for worst_il()."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    def test_worst_il_empty(self):
        self.assertIsNone(self.calc.worst_il([]))

    def test_worst_il_single(self):
        pos = _make_pos(pool_id="only", entry_price=1000.0, current_price=4000.0)
        r = self.calc.calculate(pos)
        worst = self.calc.worst_il([r])
        self.assertEqual(worst.pool_id, "only")

    def test_worst_il_picks_most_negative(self):
        positions = [
            _make_pos(pool_id="small", entry_price=1000.0, current_price=1010.0, capital_usd=10000.0),
            _make_pos(pool_id="large", entry_price=1000.0, current_price=4000.0, capital_usd=10000.0),
        ]
        results = self.calc.calculate_batch(positions)
        worst = self.calc.worst_il(results)
        self.assertEqual(worst.pool_id, "large")

    def test_worst_il_three_pools(self):
        positions = [
            _make_pos(pool_id="p1", entry_price=1000.0, current_price=2000.0, capital_usd=10000.0),
            _make_pos(pool_id="p2", entry_price=1000.0, current_price=4000.0, capital_usd=10000.0),  # worst
            _make_pos(pool_id="p3", entry_price=1000.0, current_price=1500.0, capital_usd=10000.0),
        ]
        results = self.calc.calculate_batch(positions)
        worst = self.calc.worst_il(results)
        self.assertEqual(worst.pool_id, "p2")

    def test_worst_il_returns_ilresult(self):
        pos = _make_pos()
        r = self.calc.calculate(pos)
        worst = self.calc.worst_il([r])
        self.assertIsInstance(worst, ILResult)


class TestTotalNetPnl(unittest.TestCase):
    """Tests for total_net_pnl()."""

    def setUp(self):
        self.calc = ImpermanentLossCalculator()

    def test_total_pnl_empty(self):
        self.assertEqual(self.calc.total_net_pnl([]), 0.0)

    def test_total_pnl_single(self):
        pos = _make_pos(entry_price=1000.0, current_price=1000.0, capital_usd=10000.0, fees_earned_usd=50.0)
        r = self.calc.calculate(pos)
        total = self.calc.total_net_pnl([r])
        self.assertAlmostEqual(total, r.net_pnl_usd, places=3)

    def test_total_pnl_multiple(self):
        positions = [
            _make_pos(pool_id="p1", fees_earned_usd=100.0),
            _make_pos(pool_id="p2", fees_earned_usd=200.0),
        ]
        results = self.calc.calculate_batch(positions)
        total = self.calc.total_net_pnl(results)
        expected = round(sum(r.net_pnl_usd for r in results), 4)
        self.assertAlmostEqual(total, expected, places=3)

    def test_total_pnl_negative_possible(self):
        pos = _make_pos(entry_price=1000.0, current_price=4000.0, capital_usd=10000.0, fees_earned_usd=0.0)
        r = self.calc.calculate(pos)
        total = self.calc.total_net_pnl([r])
        self.assertLess(total, 0.0)


class TestSaveLoadHistory(unittest.TestCase):
    """Tests for save_results() and load_history() with atomic writes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "data" / "il_log.json"
        self.calc = ImpermanentLossCalculator(data_file=self.data_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_history_missing_file(self):
        result = self.calc.load_history()
        self.assertEqual(result, [])

    def test_save_creates_file(self):
        pos = _make_pos()
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        self.assertTrue(self.data_file.exists())

    def test_save_and_load_round_trip(self):
        pos = _make_pos(pool_id="round-trip")
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        history = self.calc.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["pool_id"], "round-trip")

    def test_save_appends_entries(self):
        pos = _make_pos(pool_id="A")
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        pos2 = _make_pos(pool_id="B")
        r2 = self.calc.calculate(pos2)
        self.calc.save_results([r2])
        history = self.calc.load_history()
        self.assertEqual(len(history), 2)

    def test_save_ring_buffer_100(self):
        """Saving >100 entries keeps only last 100."""
        pos = _make_pos()
        r = self.calc.calculate(pos)
        # Fill with 95 entries first
        self.calc.save_results([r] * 95)
        # Save 10 more
        self.calc.save_results([r] * 10)
        history = self.calc.load_history()
        self.assertEqual(len(history), 100)

    def test_atomic_write_no_tmp_left(self):
        pos = _make_pos()
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_save_entry_has_required_fields(self):
        pos = _make_pos(pool_id="check-fields")
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        history = self.calc.load_history()
        entry = history[0]
        self.assertIn("timestamp", entry)
        self.assertIn("pool_id", entry)
        self.assertIn("il_pct", entry)
        self.assertIn("severity", entry)
        self.assertIn("net_pnl_usd", entry)
        self.assertIn("verdict", entry)

    def test_save_entry_values_correct(self):
        pos = _make_pos(pool_id="values", entry_price=1000.0, current_price=4000.0)
        r = self.calc.calculate(pos)
        self.calc.save_results([r])
        history = self.calc.load_history()
        entry = history[0]
        self.assertEqual(entry["pool_id"], "values")
        self.assertAlmostEqual(entry["il_pct"], -0.2, places=5)
        self.assertEqual(entry["severity"], "SEVERE")

    def test_load_history_corrupted_file(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("not-json{{}")
        result = self.calc.load_history()
        self.assertEqual(result, [])

    def test_save_multiple_in_one_call(self):
        positions = [_make_pos(pool_id=f"p{i}") for i in range(5)]
        results = self.calc.calculate_batch(positions)
        self.calc.save_results(results)
        history = self.calc.load_history()
        self.assertEqual(len(history), 5)


if __name__ == "__main__":
    unittest.main()
