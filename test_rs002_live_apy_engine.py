"""
tests/test_rs002_live_apy_engine.py

Tests for spa_core/analytics/rs002_live_apy_engine.py

35 tests covering:
  - blended_gross_apy() near target 29.24%
  - blended_net_apy() < blended_gross_apy() at zero move (IL always present from vol)
  - IL drag on BTC crash scenarios
  - clean_fraction_net_apy() < 1.0%
  - net_apy_scenarios() returns 7 scenarios
  - slot_apys() structure validation
  - weight sum validation
  - save() atomic write
  - apy_breakdown_report() structure

MP-1320 / Sprint v9.36
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ─── path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.rs002_live_apy_engine import (
    RS002LiveAPYEngine,
    _SLOTS_DEF,
    _BTC_MOVE_SCENARIOS,
    TARGET_GROSS_APY,
    RESEARCH_ONLY,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. blended_gross_apy()
# ══════════════════════════════════════════════════════════════════════════════

class TestBlendedGrossAPY(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()

    def test_gross_apy_near_target(self):
        """Blended gross APY should be within ±0.5% of 29.24%."""
        gross = self.engine.blended_gross_apy()
        self.assertGreaterEqual(gross, 29.0)
        self.assertLessEqual(gross, 30.0)

    def test_gross_apy_matches_target_constant(self):
        gross = self.engine.blended_gross_apy()
        self.assertAlmostEqual(gross, TARGET_GROSS_APY, places=1)

    def test_gross_apy_is_float(self):
        self.assertIsInstance(self.engine.blended_gross_apy(), float)

    def test_gross_apy_positive(self):
        self.assertGreater(self.engine.blended_gross_apy(), 0.0)

    def test_gross_apy_does_not_depend_on_btc_vol(self):
        """Gross APY should not change with different vol assumptions."""
        e1 = RS002LiveAPYEngine(btc_vol_annualized=0.40)
        e2 = RS002LiveAPYEngine(btc_vol_annualized=0.80)
        self.assertAlmostEqual(
            e1.blended_gross_apy(), e2.blended_gross_apy(), places=4
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. blended_net_apy()
# ══════════════════════════════════════════════════════════════════════════════

class TestBlendedNetAPY(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()

    def test_net_less_than_gross_at_zero_move(self):
        """IL drag due to vol means net < gross even at zero BTC move."""
        net = self.engine.blended_net_apy(0.0)
        gross = self.engine.blended_gross_apy()
        self.assertLess(net, gross)

    def test_net_apy_crash_much_lower_than_zero_move(self):
        """BTC -50% should destroy net APY vs zero move."""
        net_zero = self.engine.blended_net_apy(0.0)
        net_crash = self.engine.blended_net_apy(-50.0)
        # Must be significantly less
        self.assertLess(net_crash, net_zero - 5.0)

    def test_net_apy_zero_move_is_float(self):
        self.assertIsInstance(self.engine.blended_net_apy(0.0), float)

    def test_net_apy_symmetric_around_zero(self):
        """IL is symmetric: BTC +50% and -50% produce same net APY."""
        net_pos = self.engine.blended_net_apy(50.0)
        net_neg = self.engine.blended_net_apy(-50.0)
        self.assertAlmostEqual(net_pos, net_neg, places=4)

    def test_net_apy_monotone_decreasing_with_larger_move(self):
        """Larger BTC moves → lower net APY (more IL)."""
        n0 = self.engine.blended_net_apy(0.0)
        n10 = self.engine.blended_net_apy(-10.0)
        n30 = self.engine.blended_net_apy(-30.0)
        n50 = self.engine.blended_net_apy(-50.0)
        self.assertGreater(n0, n10)
        self.assertGreater(n10, n30)
        self.assertGreater(n30, n50)

    def test_net_apy_zero_move_within_research_range(self):
        """At default vol (60%), net APY at zero move should be 10-25%."""
        net = self.engine.blended_net_apy(0.0)
        self.assertGreater(net, 10.0)
        self.assertLess(net, 25.0)

    def test_net_apy_high_vol_lower_than_low_vol(self):
        """Higher BTC vol → more IL drag → lower net APY."""
        low_vol = RS002LiveAPYEngine(btc_vol_annualized=0.30)
        high_vol = RS002LiveAPYEngine(btc_vol_annualized=0.90)
        self.assertGreater(
            low_vol.blended_net_apy(0.0),
            high_vol.blended_net_apy(0.0),
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. clean_fraction_net_apy()
# ══════════════════════════════════════════════════════════════════════════════

class TestCleanFractionNetAPY(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()

    def test_clean_fraction_less_than_one_percent(self):
        """Only 16% × 4% = 0.64% is CLEAN. Must be < 1%."""
        clean = self.engine.clean_fraction_net_apy()
        self.assertLess(clean, 1.0)

    def test_clean_fraction_positive(self):
        clean = self.engine.clean_fraction_net_apy()
        self.assertGreater(clean, 0.0)

    def test_clean_fraction_approx_0_64(self):
        """stablecoin_deposit: 0.16 × 4.0 = 0.64%"""
        clean = self.engine.clean_fraction_net_apy()
        self.assertAlmostEqual(clean, 0.64, places=2)

    def test_clean_fraction_is_float(self):
        self.assertIsInstance(self.engine.clean_fraction_net_apy(), float)


# ══════════════════════════════════════════════════════════════════════════════
# 4. net_apy_scenarios()
# ══════════════════════════════════════════════════════════════════════════════

class TestNetAPYScenarios(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()
        self.scenarios = self.engine.net_apy_scenarios()

    def test_returns_seven_scenarios(self):
        self.assertEqual(len(self.scenarios), 7)

    def test_scenarios_is_list(self):
        self.assertIsInstance(self.scenarios, list)

    def test_each_scenario_is_dict(self):
        for s in self.scenarios:
            self.assertIsInstance(s, dict)

    def test_each_scenario_has_btc_move_pct(self):
        for s in self.scenarios:
            self.assertIn("btc_move_pct", s)

    def test_each_scenario_has_blended_net_apy(self):
        for s in self.scenarios:
            self.assertIn("blended_net_apy", s)

    def test_each_scenario_has_blended_gross_apy(self):
        for s in self.scenarios:
            self.assertIn("blended_gross_apy", s)

    def test_each_scenario_has_il_drag(self):
        for s in self.scenarios:
            self.assertIn("il_drag_btc_slot", s)

    def test_scenarios_cover_negative_and_positive_moves(self):
        moves = [s["btc_move_pct"] for s in self.scenarios]
        self.assertIn(-50.0, moves)
        self.assertIn(50.0, moves)
        self.assertIn(0.0, moves)

    def test_zero_move_scenario_net_apy_is_highest(self):
        """Zero move should produce the highest net APY (min IL)."""
        zero_net = next(s["blended_net_apy"] for s in self.scenarios if s["btc_move_pct"] == 0.0)
        for s in self.scenarios:
            self.assertGreaterEqual(zero_net, s["blended_net_apy"])


# ══════════════════════════════════════════════════════════════════════════════
# 5. slot_apys()
# ══════════════════════════════════════════════════════════════════════════════

class TestSlotAPYs(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()
        self.slots = self.engine.slot_apys()

    def test_returns_four_slots(self):
        self.assertEqual(len(self.slots), 4)

    def test_slot_has_required_keys(self):
        for slot in self.slots:
            for key in ("slot_id", "weight", "gross_apy", "il_drag", "net_apy", "source_quality"):
                self.assertIn(key, slot)

    def test_weight_sum_approx_one(self):
        total = sum(s["weight"] for s in self.slots)
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_btc_lp_slot_has_positive_il_drag(self):
        btc_slot = next(s for s in self.slots if s["slot_id"] == "btc_usd_conc_liq")
        self.assertGreater(btc_slot["il_drag"], 0.0)

    def test_stablecoin_slot_has_zero_il_drag(self):
        stbl = next(s for s in self.slots if s["slot_id"] == "stablecoin_deposit")
        self.assertEqual(stbl["il_drag"], 0.0)

    def test_non_lp_vault_has_zero_il_drag(self):
        vault = next(s for s in self.slots if s["slot_id"] == "trader_losses_vault")
        self.assertEqual(vault["il_drag"], 0.0)

    def test_stablecoin_source_quality_is_clean(self):
        stbl = next(s for s in self.slots if s["slot_id"] == "stablecoin_deposit")
        self.assertEqual(stbl["source_quality"], "clean")

    def test_btc_slot_source_quality_is_source_needed(self):
        btc_slot = next(s for s in self.slots if s["slot_id"] == "btc_usd_conc_liq")
        self.assertEqual(btc_slot["source_quality"], "source_needed")


# ══════════════════════════════════════════════════════════════════════════════
# 6. apy_breakdown_report()
# ══════════════════════════════════════════════════════════════════════════════

class TestAPYBreakdownReport(unittest.TestCase):

    def setUp(self):
        self.engine = RS002LiveAPYEngine()
        self.report = self.engine.apy_breakdown_report()

    def test_report_has_research_only_true(self):
        self.assertTrue(self.report["research_only"])

    def test_report_has_slots(self):
        self.assertIn("slots", self.report)
        self.assertEqual(len(self.report["slots"]), 4)

    def test_report_blended_gross_matches_engine(self):
        self.assertAlmostEqual(
            self.report["blended_gross_apy"],
            self.engine.blended_gross_apy(),
            places=4,
        )

    def test_report_weight_sum_approx_one(self):
        self.assertAlmostEqual(self.report["weight_sum"], 1.0, places=4)

    def test_report_has_strategy_id(self):
        self.assertEqual(self.report["strategy_id"], "S21")


# ══════════════════════════════════════════════════════════════════════════════
# 7. save() — atomic write
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveAtomic(unittest.TestCase):

    def test_save_creates_valid_json(self):
        engine = RS002LiveAPYEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "rs002_test.json")
            engine.save(path=out_path)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                data = json.load(f)
            self.assertIn("slots", data)

    def test_save_no_tmp_files_remain(self):
        engine = RS002LiveAPYEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "rs002_test.json")
            engine.save(path=out_path)
            tmp_files = [
                f for f in os.listdir(tmpdir)
                if f.startswith(".rs002_apy_breakdown_tmp_")
            ]
            self.assertEqual(len(tmp_files), 0)

    def test_save_content_has_research_only(self):
        engine = RS002LiveAPYEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "rs002_test.json")
            engine.save(path=out_path)
            with open(out_path) as f:
                data = json.load(f)
            self.assertTrue(data["research_only"])


# ══════════════════════════════════════════════════════════════════════════════
# 8. RESEARCH_ONLY flag and constructor guards
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleGuards(unittest.TestCase):

    def test_research_only_flag_is_true(self):
        self.assertTrue(RESEARCH_ONLY)

    def test_negative_vol_raises(self):
        with self.assertRaises(ValueError):
            RS002LiveAPYEngine(btc_vol_annualized=-0.1)

    def test_zero_vol_no_vol_path_drag(self):
        """At zero vol, IL drag for zero BTC move should be zero."""
        engine = RS002LiveAPYEngine(btc_vol_annualized=0.0)
        slots = engine.slot_apys(btc_price_move_pct=0.0)
        btc_slot = next(s for s in slots if s["slot_id"] == "btc_usd_conc_liq")
        self.assertEqual(btc_slot["il_drag"], 0.0)


if __name__ == "__main__":
    unittest.main()
