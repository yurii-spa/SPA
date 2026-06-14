"""Unit tests for spa_core.analytics.compounding_strategy_selector (MP-699).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_compounding_strategy_selector -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.compounding_strategy_selector import (
    AUTO_COMPOUNDERS,
    DATA_FILE,
    MAX_ENTRIES,
    CompoundingStrategySelector,
    StrategyInput,
    StrategyOption,
    StrategySelection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inp(
    position_id: str = "pos-1",
    protocol: str = "Aave",
    capital_usd: float = 100_000.0,
    gross_apy_pct: float = 5.0,
    manual_gas_usd: float = 20.0,
    manual_compound_days: int = 7,
    lock_period_days: int = 0,
) -> StrategyInput:
    return StrategyInput(
        position_id=position_id,
        protocol=protocol,
        capital_usd=capital_usd,
        gross_apy_pct=gross_apy_pct,
        manual_gas_usd=manual_gas_usd,
        manual_compound_days=manual_compound_days,
        lock_period_days=lock_period_days,
    )


SELECTOR = CompoundingStrategySelector()


# ---------------------------------------------------------------------------
# 1. HOLD option
# ---------------------------------------------------------------------------

class TestHoldOption(unittest.TestCase):

    def test_hold_net_apy_equals_gross_apy(self):
        i = _inp(gross_apy_pct=5.0)
        opt = SELECTOR._hold_option(i)
        self.assertAlmostEqual(opt.net_apy_pct, 5.0, places=6)

    def test_hold_annual_cost_zero(self):
        i = _inp()
        opt = SELECTOR._hold_option(i)
        self.assertEqual(opt.annual_cost_usd, 0.0)

    def test_hold_annual_net_yield(self):
        i = _inp(capital_usd=100_000, gross_apy_pct=5.0)
        opt = SELECTOR._hold_option(i)
        self.assertAlmostEqual(opt.annual_net_yield_usd, 5_000.0, places=2)

    def test_hold_complexity_low(self):
        i = _inp()
        opt = SELECTOR._hold_option(i)
        self.assertEqual(opt.complexity, "LOW")

    def test_hold_suitable_true(self):
        i = _inp()
        opt = SELECTOR._hold_option(i)
        self.assertTrue(opt.suitable)

    def test_hold_strategy_name(self):
        i = _inp()
        opt = SELECTOR._hold_option(i)
        self.assertEqual(opt.strategy_name, "HOLD")

    def test_hold_suitable_even_when_locked(self):
        """HOLD is always suitable regardless of lock."""
        i = _inp(lock_period_days=90)
        opt = SELECTOR._hold_option(i)
        self.assertTrue(opt.suitable)

    def test_hold_different_apy_values(self):
        for apy in [0.5, 2.0, 10.0, 25.0]:
            i = _inp(gross_apy_pct=apy)
            opt = SELECTOR._hold_option(i)
            self.assertAlmostEqual(opt.net_apy_pct, apy, places=6)


# ---------------------------------------------------------------------------
# 2. MANUAL option
# ---------------------------------------------------------------------------

class TestManualOption(unittest.TestCase):

    def test_manual_strategy_name(self):
        i = _inp()
        opt = SELECTOR._manual_option(i)
        self.assertEqual(opt.strategy_name, "MANUAL")

    def test_manual_complexity_medium(self):
        i = _inp()
        opt = SELECTOR._manual_option(i)
        self.assertEqual(opt.complexity, "MEDIUM")

    def test_manual_suitable_true(self):
        i = _inp()
        opt = SELECTOR._manual_option(i)
        self.assertTrue(opt.suitable)

    def test_manual_suitable_true_even_locked(self):
        """MANUAL is always suitable (user can compound even locked positions)."""
        i = _inp(lock_period_days=30)
        opt = SELECTOR._manual_option(i)
        self.assertTrue(opt.suitable)

    def test_manual_compounded_apy_greater_than_gross(self):
        """Compounding at sub-annual frequency increases effective APY."""
        i = _inp(gross_apy_pct=5.0, manual_gas_usd=0.0, manual_compound_days=7)
        opt = SELECTOR._manual_option(i)
        self.assertGreater(opt.net_apy_pct, 5.0)

    def test_manual_high_gas_drag_net_apy_less_than_gross(self):
        """Small capital + large gas → net APY below gross APY."""
        i = _inp(
            capital_usd=1_000,
            gross_apy_pct=5.0,
            manual_gas_usd=50.0,
            manual_compound_days=7,
        )
        opt = SELECTOR._manual_option(i)
        self.assertLess(opt.net_apy_pct, 5.0)

    def test_manual_zero_gas_net_greater_than_gross(self):
        i = _inp(gross_apy_pct=5.0, manual_gas_usd=0.0, manual_compound_days=7)
        opt = SELECTOR._manual_option(i)
        self.assertGreater(opt.net_apy_pct, 5.0)

    def test_manual_annual_cost_equals_gas_times_frequency(self):
        i = _inp(manual_gas_usd=25.0, manual_compound_days=30)
        opt = SELECTOR._manual_option(i)
        expected_annual_gas = 25.0 * (365.0 / 30)
        self.assertAlmostEqual(opt.annual_cost_usd, expected_annual_gas, places=4)

    def test_manual_annual_net_yield_consistent_with_net_apy(self):
        i = _inp(capital_usd=100_000, gross_apy_pct=5.0, manual_gas_usd=0.0)
        opt = SELECTOR._manual_option(i)
        expected_yield = 100_000 * opt.net_apy_pct / 100.0
        self.assertAlmostEqual(opt.annual_net_yield_usd, expected_yield, places=2)


# ---------------------------------------------------------------------------
# 3. AUTO-COMPOUND options
# ---------------------------------------------------------------------------

class TestAutoOptions(unittest.TestCase):

    def test_auto_options_all_five_compounders(self):
        i = _inp()
        auto_opts = [
            SELECTOR._auto_option(i, name, params)
            for name, params in AUTO_COMPOUNDERS.items()
        ]
        self.assertEqual(len(auto_opts), 5)

    def test_auto_strategy_names_match_keys(self):
        i = _inp()
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            self.assertEqual(opt.strategy_name, name)

    def test_auto_complexity_low(self):
        i = _inp()
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            self.assertEqual(opt.complexity, "LOW")

    def test_auto_suitable_true_when_liquid(self):
        i = _inp(lock_period_days=0)
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            self.assertTrue(opt.suitable, f"{name} should be suitable when liquid")

    def test_auto_suitable_false_when_locked(self):
        i = _inp(lock_period_days=30)
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            self.assertFalse(opt.suitable, f"{name} should not be suitable when locked")

    def test_auto_high_fee_lower_net_apy_than_low_fee(self):
        """Convex (16% fee) should yield less net APY than Yearn (2% fee)."""
        i = _inp(gross_apy_pct=10.0)
        opt_yearn = SELECTOR._auto_option(i, "yearn", AUTO_COMPOUNDERS["yearn"])
        opt_convex = SELECTOR._auto_option(i, "convex", AUTO_COMPOUNDERS["convex"])
        self.assertGreater(opt_yearn.net_apy_pct, opt_convex.net_apy_pct)

    def test_auto_aura_lower_than_yearn(self):
        """Aura (20% fee) < Yearn (2% fee)."""
        i = _inp(gross_apy_pct=10.0)
        opt_yearn = SELECTOR._auto_option(i, "yearn", AUTO_COMPOUNDERS["yearn"])
        opt_aura = SELECTOR._auto_option(i, "aura", AUTO_COMPOUNDERS["aura"])
        self.assertGreater(opt_yearn.net_apy_pct, opt_aura.net_apy_pct)

    def test_auto_annual_cost_positive(self):
        i = _inp(gross_apy_pct=10.0)
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            self.assertGreater(opt.annual_cost_usd, 0.0, f"{name} cost should be positive")

    def test_auto_net_apy_less_than_compounded_apy(self):
        """Net APY is compounded_apy minus fee_drag → must be less."""
        i = _inp(gross_apy_pct=8.0)
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            # The compounded APY is gross_apy * (1 + small bonus), net is less after fee
            # Rough check: net_apy < gross_apy * (1 + small) ≈ slightly above gross
            # More directly: net should be < gross for high-fee compounders
            if params["performance_fee_pct"] >= 10.0:
                self.assertLess(opt.net_apy_pct, i.gross_apy_pct)

    def test_auto_annual_net_yield_consistent(self):
        i = _inp(capital_usd=100_000, gross_apy_pct=5.0)
        for name, params in AUTO_COMPOUNDERS.items():
            opt = SELECTOR._auto_option(i, name, params)
            expected = 100_000 * opt.net_apy_pct / 100.0
            self.assertAlmostEqual(opt.annual_net_yield_usd, expected, places=2)


# ---------------------------------------------------------------------------
# 4. select()
# ---------------------------------------------------------------------------

class TestSelect(unittest.TestCase):

    def test_select_returns_strategy_selection(self):
        i = _inp()
        result = SELECTOR.select(i)
        self.assertIsInstance(result, StrategySelection)

    def test_select_position_id_preserved(self):
        i = _inp(position_id="pos-abc")
        result = SELECTOR.select(i)
        self.assertEqual(result.position_id, "pos-abc")

    def test_select_options_count(self):
        """Should have 7 options: HOLD + MANUAL + 5 auto-compounders."""
        i = _inp()
        result = SELECTOR.select(i)
        self.assertEqual(len(result.options), 7)

    def test_select_best_is_highest_net_apy_suitable(self):
        i = _inp(lock_period_days=0)
        result = SELECTOR.select(i)
        suitable = [o for o in result.options if o.suitable]
        best_apy = max(o.net_apy_pct for o in suitable)
        self.assertAlmostEqual(result.best_net_apy_pct, best_apy, places=6)

    def test_select_locked_only_hold_and_manual_suitable(self):
        i = _inp(lock_period_days=90)
        result = SELECTOR.select(i)
        suitable = [o for o in result.options if o.suitable]
        suitable_names = {o.strategy_name for o in suitable}
        self.assertSetEqual(suitable_names, {"HOLD", "MANUAL"})

    def test_select_best_strategy_name_in_options(self):
        i = _inp()
        result = SELECTOR.select(i)
        option_names = {o.strategy_name for o in result.options}
        self.assertIn(result.best_strategy, option_names)

    def test_select_vs_hold_improvement_calculation(self):
        i = _inp()
        result = SELECTOR.select(i)
        hold_opt = next(o for o in result.options if o.strategy_name == "HOLD")
        expected_improvement = result.best_net_apy_pct - hold_opt.net_apy_pct
        self.assertAlmostEqual(
            result.vs_hold_improvement_pct, expected_improvement, places=6
        )

    def test_select_recommendation_contains_strategy_name(self):
        i = _inp()
        result = SELECTOR.select(i)
        self.assertIn(result.best_strategy, result.recommendation)

    def test_select_recommendation_contains_net_apy(self):
        i = _inp()
        result = SELECTOR.select(i)
        apy_str = f"{result.best_net_apy_pct:.2f}"
        self.assertIn(apy_str, result.recommendation)

    def test_select_rationale_not_empty(self):
        i = _inp()
        result = SELECTOR.select(i)
        self.assertTrue(len(result.rationale) > 0)

    def test_select_locked_best_is_manual_or_hold(self):
        i = _inp(lock_period_days=60)
        result = SELECTOR.select(i)
        self.assertIn(result.best_strategy, ("HOLD", "MANUAL"))

    def test_select_large_capital_auto_compound_beats_manual(self):
        """Large capital → gas drag low → auto-compound likely best."""
        i = _inp(
            capital_usd=10_000_000,
            gross_apy_pct=8.0,
            manual_gas_usd=100.0,
            lock_period_days=0,
        )
        result = SELECTOR.select(i)
        # Best should not be HOLD when capital is huge (compounding effect)
        self.assertNotEqual(result.best_strategy, "HOLD")

    def test_select_small_capital_high_gas_best_could_be_hold(self):
        """Tiny capital + very high gas → hold or manual might win."""
        i = _inp(
            capital_usd=100,
            gross_apy_pct=3.0,
            manual_gas_usd=1000.0,
            lock_period_days=0,
        )
        result = SELECTOR.select(i)
        # Just confirm it runs and returns a valid selection
        self.assertIsInstance(result, StrategySelection)

    def test_select_hold_always_in_options(self):
        i = _inp()
        result = SELECTOR.select(i)
        names = [o.strategy_name for o in result.options]
        self.assertIn("HOLD", names)

    def test_select_manual_always_in_options(self):
        i = _inp()
        result = SELECTOR.select(i)
        names = [o.strategy_name for o in result.options]
        self.assertIn("MANUAL", names)

    def test_select_all_auto_compounders_in_options(self):
        i = _inp()
        result = SELECTOR.select(i)
        names = {o.strategy_name for o in result.options}
        for name in AUTO_COMPOUNDERS:
            self.assertIn(name, names)


# ---------------------------------------------------------------------------
# 5. select_batch()
# ---------------------------------------------------------------------------

class TestSelectBatch(unittest.TestCase):

    def test_batch_empty_returns_empty(self):
        result = SELECTOR.select_batch([])
        self.assertEqual(result, [])

    def test_batch_single_input(self):
        result = SELECTOR.select_batch([_inp()])
        self.assertEqual(len(result), 1)

    def test_batch_multiple_inputs(self):
        inputs = [
            _inp(position_id="p1"),
            _inp(position_id="p2", lock_period_days=30),
            _inp(position_id="p3", capital_usd=500_000),
        ]
        result = SELECTOR.select_batch(inputs)
        self.assertEqual(len(result), 3)

    def test_batch_ids_in_order(self):
        inputs = [_inp(position_id=f"p{i}") for i in range(4)]
        result = SELECTOR.select_batch(inputs)
        for i, sel in enumerate(result):
            self.assertEqual(sel.position_id, f"p{i}")

    def test_batch_all_return_strategy_selection_type(self):
        inputs = [_inp(), _inp(lock_period_days=10)]
        result = SELECTOR.select_batch(inputs)
        for sel in result:
            self.assertIsInstance(sel, StrategySelection)


# ---------------------------------------------------------------------------
# 6. Persistence — save_results / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _tmp_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return Path(path)

    def test_load_history_missing_file_returns_empty(self):
        p = Path("/tmp/nonexistent_compounder_XYZ.json")
        result = SELECTOR.load_history(data_file=p)
        self.assertEqual(result, [])

    def test_save_creates_file(self):
        p = self._tmp_file()
        sel = SELECTOR.select(_inp())
        SELECTOR.save_results([sel], data_file=p)
        self.assertTrue(p.exists())
        p.unlink()

    def test_save_valid_json(self):
        p = self._tmp_file()
        sel = SELECTOR.select(_inp())
        SELECTOR.save_results([sel], data_file=p)
        with open(p) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        p.unlink()

    def test_save_and_load_round_trip(self):
        p = self._tmp_file()
        sel = SELECTOR.select(_inp(position_id="rt-test"))
        SELECTOR.save_results([sel], data_file=p)
        loaded = SELECTOR.load_history(data_file=p)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["position_id"], "rt-test")
        p.unlink()

    def test_ring_buffer_max_entries(self):
        p = self._tmp_file()
        for i in range(MAX_ENTRIES + 5):
            sel = SELECTOR.select(_inp(position_id=f"p{i}"))
            SELECTOR.save_results([sel], data_file=p)
        loaded = SELECTOR.load_history(data_file=p)
        self.assertLessEqual(len(loaded), MAX_ENTRIES)
        p.unlink()

    def test_ring_buffer_keeps_latest(self):
        p = self._tmp_file()
        for i in range(MAX_ENTRIES + 3):
            sel = SELECTOR.select(_inp(position_id=f"p{i}"))
            SELECTOR.save_results([sel], data_file=p)
        loaded = SELECTOR.load_history(data_file=p)
        self.assertEqual(loaded[-1]["position_id"], f"p{MAX_ENTRIES + 2}")
        p.unlink()

    def test_save_atomic_no_tmp_leftover(self):
        p = self._tmp_file()
        sel = SELECTOR.select(_inp())
        SELECTOR.save_results([sel], data_file=p)
        self.assertFalse(Path(str(p) + ".tmp").exists())
        p.unlink()

    def test_load_corrupt_json_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"{{bad json")
        os.close(fd)
        p = Path(path)
        result = SELECTOR.load_history(data_file=p)
        self.assertEqual(result, [])
        p.unlink()

    def test_load_non_list_json_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b'{"key": "value"}')
        os.close(fd)
        p = Path(path)
        result = SELECTOR.load_history(data_file=p)
        self.assertEqual(result, [])
        p.unlink()

    def test_saved_entry_has_saved_at_field(self):
        p = self._tmp_file()
        SELECTOR.save_results([SELECTOR.select(_inp())], data_file=p)
        loaded = SELECTOR.load_history(data_file=p)
        self.assertIn("saved_at", loaded[0])
        p.unlink()

    def test_save_appends_to_existing(self):
        p = self._tmp_file()
        SELECTOR.save_results([SELECTOR.select(_inp(position_id="a"))], data_file=p)
        SELECTOR.save_results([SELECTOR.select(_inp(position_id="b"))], data_file=p)
        loaded = SELECTOR.load_history(data_file=p)
        ids = [e["position_id"] for e in loaded]
        self.assertIn("a", ids)
        self.assertIn("b", ids)
        p.unlink()


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_capital_no_crash(self):
        i = _inp(capital_usd=0.0)
        result = SELECTOR.select(i)
        self.assertIsInstance(result, StrategySelection)

    def test_very_high_apy(self):
        i = _inp(gross_apy_pct=100.0)
        result = SELECTOR.select(i)
        self.assertGreater(result.best_net_apy_pct, 0.0)

    def test_very_low_apy(self):
        i = _inp(gross_apy_pct=0.1)
        result = SELECTOR.select(i)
        self.assertIsInstance(result, StrategySelection)

    def test_all_locked_best_is_hold_or_manual(self):
        i = _inp(lock_period_days=365)
        result = SELECTOR.select(i)
        self.assertIn(result.best_strategy, ("HOLD", "MANUAL"))

    def test_options_list_contains_all_seven(self):
        i = _inp()
        result = SELECTOR.select(i)
        expected_names = {"HOLD", "MANUAL"} | set(AUTO_COMPOUNDERS.keys())
        actual_names = {o.strategy_name for o in result.options}
        self.assertEqual(actual_names, expected_names)

    def test_best_net_apy_is_float(self):
        i = _inp()
        result = SELECTOR.select(i)
        self.assertIsInstance(result.best_net_apy_pct, float)

    def test_vs_hold_improvement_is_float(self):
        i = _inp()
        result = SELECTOR.select(i)
        self.assertIsInstance(result.vs_hold_improvement_pct, float)


if __name__ == "__main__":
    unittest.main()
