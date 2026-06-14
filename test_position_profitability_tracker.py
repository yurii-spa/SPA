"""
Tests for PositionProfitabilityTracker (MP-718).
Run: python3 -m pytest spa_core/tests/test_position_profitability_tracker.py -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.position_profitability_tracker import (
    ProfitabilitySnapshot,
    ProfitabilityReport,
    add_snapshot,
    analyze,
    compare_positions,
    find_best_performing,
    save_results,
    load_history,
)


def _make_snaps(pos=10_500.0, yld=200.0, gas=20.0, ts="2026-06-10"):
    return [ProfitabilitySnapshot(
        timestamp_iso=ts,
        position_value_usd=pos,
        yield_collected_usd=yld,
        gas_spent_usd=gas,
    )]


def _base_report(**kwargs):
    defaults = dict(
        protocol="Aave V3",
        pool="USDC",
        entry_value_usd=10_000.0,
        entry_timestamp_iso="2026-05-01",
        current_timestamp_iso="2026-06-10",
        snapshots=_make_snaps(),
        impermanent_loss_usd=0.0,
    )
    defaults.update(kwargs)
    return analyze(**defaults)


class TestUnrealizedPnl(unittest.TestCase):

    def test_positive_unrealized_pnl(self):
        r = _base_report(entry_value_usd=10_000.0, snapshots=_make_snaps(pos=10_500.0))
        self.assertAlmostEqual(r.unrealized_pnl_usd, 500.0, places=2)

    def test_negative_unrealized_pnl(self):
        r = _base_report(entry_value_usd=10_000.0, snapshots=_make_snaps(pos=9_500.0))
        self.assertAlmostEqual(r.unrealized_pnl_usd, -500.0, places=2)

    def test_zero_unrealized_pnl(self):
        r = _base_report(entry_value_usd=10_000.0, snapshots=_make_snaps(pos=10_000.0))
        self.assertAlmostEqual(r.unrealized_pnl_usd, 0.0, places=2)

    def test_current_position_value_matches_last_snapshot(self):
        r = _base_report(snapshots=_make_snaps(pos=12_345.67))
        self.assertAlmostEqual(r.current_position_value_usd, 12_345.67, places=2)


class TestRealizedYield(unittest.TestCase):

    def test_realized_yield_positive(self):
        r = _base_report(snapshots=_make_snaps(yld=300.0, gas=50.0))
        self.assertAlmostEqual(r.realized_yield_usd, 250.0, places=2)

    def test_realized_yield_zero(self):
        r = _base_report(snapshots=_make_snaps(yld=100.0, gas=100.0))
        self.assertAlmostEqual(r.realized_yield_usd, 0.0, places=2)

    def test_realized_yield_negative_gas_exceeds(self):
        r = _base_report(snapshots=_make_snaps(yld=50.0, gas=200.0))
        self.assertAlmostEqual(r.realized_yield_usd, -150.0, places=2)

    def test_yield_collected_stored(self):
        r = _base_report(snapshots=_make_snaps(yld=999.0, gas=1.0))
        self.assertAlmostEqual(r.total_yield_collected_usd, 999.0, places=2)

    def test_gas_spent_stored(self):
        r = _base_report(snapshots=_make_snaps(yld=100.0, gas=77.0))
        self.assertAlmostEqual(r.total_gas_spent_usd, 77.0, places=2)


class TestTotalPnl(unittest.TestCase):

    def test_total_pnl_formula(self):
        # unrealized=500, realized=180, il=50  → 630
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=10_500.0, yld=200.0, gas=20.0),
            impermanent_loss_usd=50.0,
        )
        expected = 500.0 + (200.0 - 20.0) - 50.0
        self.assertAlmostEqual(r.total_pnl_usd, expected, places=2)

    def test_total_pnl_no_il(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=10_200.0, yld=100.0, gas=30.0),
            impermanent_loss_usd=0.0,
        )
        expected = 200.0 + 70.0
        self.assertAlmostEqual(r.total_pnl_usd, expected, places=2)

    def test_total_pnl_negative(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=9_000.0, yld=50.0, gas=100.0),
            impermanent_loss_usd=200.0,
        )
        expected = -1_000.0 + (-50.0) - 200.0
        self.assertAlmostEqual(r.total_pnl_usd, expected, places=2)


class TestTotalPnlPct(unittest.TestCase):

    def test_pnl_pct_formula(self):
        # total_pnl=500, entry=10000 → 5%
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=10_500.0, yld=0.0, gas=0.0),
        )
        self.assertAlmostEqual(r.total_pnl_pct, 5.0, places=4)

    def test_pnl_pct_negative(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=9_000.0, yld=0.0, gas=0.0),
        )
        self.assertAlmostEqual(r.total_pnl_pct, -10.0, places=4)

    def test_pnl_pct_zero_entry_guard(self):
        # entry_value=0 → uses 0.01 guard, no ZeroDivisionError
        r = _base_report(
            entry_value_usd=0.0,
            snapshots=_make_snaps(pos=0.0, yld=0.0, gas=0.0),
        )
        self.assertIsInstance(r.total_pnl_pct, float)


class TestAnnualizedReturn(unittest.TestCase):

    def test_annualized_10pct_over_30_days(self):
        # 10% total over 30 days → 10/30*365 ≈ 121.67%
        r = _base_report(
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-05-31",
            snapshots=_make_snaps(pos=11_000.0, yld=0.0, gas=0.0),
        )
        expected = 10.0 / 30.0 * 365.0
        self.assertAlmostEqual(r.annualized_return_pct, expected, places=4)

    def test_annualized_0_days(self):
        r = _base_report(
            entry_timestamp_iso="2026-06-10",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(),
        )
        self.assertEqual(r.annualized_return_pct, 0.0)

    def test_annualized_1_day(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-06-09",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(pos=10_100.0, yld=0.0, gas=0.0),
        )
        # 1% over 1 day → 365%
        self.assertAlmostEqual(r.annualized_return_pct, 365.0, places=3)

    def test_days_held_calculation(self):
        r = _base_report(
            entry_timestamp_iso="2026-01-01",
            current_timestamp_iso="2026-04-11",  # 100 days
            snapshots=_make_snaps(),
        )
        self.assertEqual(r.days_held, 100)


class TestDailyReturn(unittest.TestCase):

    def test_daily_return_formula(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(pos=10_500.0, yld=100.0, gas=20.0),
        )
        expected = r.total_pnl_usd / r.days_held
        self.assertAlmostEqual(r.daily_return_usd, expected, places=4)

    def test_daily_return_0_days(self):
        r = _base_report(
            entry_timestamp_iso="2026-06-10",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(pos=10_000.0, yld=0.0, gas=0.0),
        )
        # days_held=0 → divides by max(0,1)=1
        self.assertAlmostEqual(r.daily_return_usd, r.total_pnl_usd, places=4)


class TestYieldToGasRatio(unittest.TestCase):

    def test_normal_ratio(self):
        r = _base_report(snapshots=_make_snaps(yld=500.0, gas=50.0))
        self.assertAlmostEqual(r.yield_to_gas_ratio, 10.0, places=4)

    def test_gas_zero_uses_guard(self):
        # gas=0 → ratio = yield / 0.01
        r = _base_report(snapshots=_make_snaps(yld=100.0, gas=0.0))
        self.assertAlmostEqual(r.yield_to_gas_ratio, 100.0 / 0.01, places=2)

    def test_ratio_below_threshold(self):
        r = _base_report(snapshots=_make_snaps(yld=10.0, gas=100.0))
        expected = 10.0 / 100.0
        self.assertAlmostEqual(r.yield_to_gas_ratio, expected, places=4)


class TestILDragPct(unittest.TestCase):

    def test_il_drag_formula(self):
        r = _base_report(entry_value_usd=10_000.0, impermanent_loss_usd=500.0,
                         snapshots=_make_snaps())
        self.assertAlmostEqual(r.il_drag_pct, 5.0, places=4)

    def test_il_drag_zero(self):
        r = _base_report(impermanent_loss_usd=0.0, snapshots=_make_snaps())
        self.assertAlmostEqual(r.il_drag_pct, 0.0, places=4)

    def test_il_drag_large(self):
        r = _base_report(entry_value_usd=10_000.0, impermanent_loss_usd=1_000.0,
                         snapshots=_make_snaps())
        self.assertAlmostEqual(r.il_drag_pct, 10.0, places=4)


class TestProfitabilityLabel(unittest.TestCase):

    def _label_for_ann(self, ann_pct: float) -> str:
        # Create report where annualized ≈ target using 365-day window
        # total_pnl_pct = ann_pct (1 day → ann = pct * 365 → use 365 days)
        entry = 10_000.0
        # total_pnl_pct * 365 / 365 = ann, so pnl_pct = ann_pct/365*365 = ann_pct
        # over 365 days: ann = pnl_pct
        target_pct = ann_pct
        pos_delta = entry * target_pct / 100.0
        r = analyze(
            protocol="X", pool="Y",
            entry_value_usd=entry,
            entry_timestamp_iso="2025-06-13",
            current_timestamp_iso="2026-06-13",
            snapshots=_make_snaps(pos=entry + pos_delta, yld=0.0, gas=0.0),
        )
        return r.profitability_label

    def test_excellent_30pct(self):
        self.assertEqual(self._label_for_ann(30.0), "EXCELLENT")

    def test_good_15pct(self):
        self.assertEqual(self._label_for_ann(15.0), "GOOD")

    def test_breakeven_5pct(self):
        self.assertEqual(self._label_for_ann(5.0), "BREAKEVEN")

    def test_loss_negative(self):
        self.assertEqual(self._label_for_ann(-1.0), "LOSS")

    def test_boundary_exactly_20(self):
        self.assertEqual(self._label_for_ann(20.0), "EXCELLENT")

    def test_boundary_exactly_10(self):
        self.assertEqual(self._label_for_ann(10.0), "GOOD")

    def test_boundary_exactly_0(self):
        self.assertEqual(self._label_for_ann(0.0), "BREAKEVEN")


class TestGasEfficiency(unittest.TestCase):

    def test_efficient_ratio_15(self):
        r = _base_report(snapshots=_make_snaps(yld=150.0, gas=10.0))  # ratio=15
        self.assertEqual(r.gas_efficiency, "EFFICIENT")

    def test_moderate_ratio_5(self):
        r = _base_report(snapshots=_make_snaps(yld=50.0, gas=10.0))   # ratio=5
        self.assertEqual(r.gas_efficiency, "MODERATE")

    def test_expensive_ratio_1(self):
        r = _base_report(snapshots=_make_snaps(yld=10.0, gas=10.0))   # ratio=1
        self.assertEqual(r.gas_efficiency, "EXPENSIVE")

    def test_boundary_exactly_10(self):
        # ratio = 10.0: NOT > 10, so MODERATE
        r = _base_report(snapshots=_make_snaps(yld=100.0, gas=10.0))
        self.assertEqual(r.gas_efficiency, "MODERATE")

    def test_boundary_exactly_3(self):
        # ratio = 3.0: NOT > 3, so EXPENSIVE
        r = _base_report(snapshots=_make_snaps(yld=30.0, gas=10.0))
        self.assertEqual(r.gas_efficiency, "EXPENSIVE")


class TestWarnings(unittest.TestCase):

    def test_warning_significant_il_drag(self):
        # il_drag > 5%: il=600 on entry=10000 → 6%
        r = _base_report(
            entry_value_usd=10_000.0,
            impermanent_loss_usd=600.0,
            snapshots=_make_snaps(pos=10_000.0, yld=100.0, gas=5.0),
        )
        self.assertIn("significant IL drag", r.warnings)

    def test_no_il_drag_warning_below_5pct(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            impermanent_loss_usd=400.0,
            snapshots=_make_snaps(),
        )
        self.assertNotIn("significant IL drag", r.warnings)

    def test_warning_expensive_gas(self):
        # ratio = 1 (10 yield / 10 gas) → EXPENSIVE
        r = _base_report(snapshots=_make_snaps(yld=10.0, gas=10.0))
        self.assertIn("high gas costs eating yield", r.warnings)

    def test_no_gas_warning_when_efficient(self):
        r = _base_report(snapshots=_make_snaps(yld=200.0, gas=10.0))  # ratio=20
        self.assertNotIn("high gas costs eating yield", r.warnings)

    def test_warning_position_in_loss(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=9_000.0, yld=0.0, gas=0.0),
        )
        self.assertIn("position in loss", r.warnings)

    def test_no_loss_warning_when_profitable(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            snapshots=_make_snaps(pos=10_500.0, yld=100.0, gas=10.0),
        )
        self.assertNotIn("position in loss", r.warnings)

    def test_multiple_warnings(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            impermanent_loss_usd=2_000.0,
            snapshots=_make_snaps(pos=7_000.0, yld=10.0, gas=10.0),
        )
        self.assertIn("significant IL drag", r.warnings)
        self.assertIn("high gas costs eating yield", r.warnings)
        self.assertIn("position in loss", r.warnings)

    def test_no_warnings_healthy_position(self):
        r = _base_report(
            entry_value_usd=10_000.0,
            impermanent_loss_usd=0.0,
            snapshots=_make_snaps(pos=11_000.0, yld=500.0, gas=10.0),
        )
        self.assertEqual(r.warnings, [])


class TestComparePositions(unittest.TestCase):

    def _make_report(self, ann_pct: float, label: str) -> ProfitabilityReport:
        entry = 10_000.0
        pos_delta = entry * ann_pct / 100.0
        return analyze(
            protocol="X", pool=label,
            entry_value_usd=entry,
            entry_timestamp_iso="2025-06-13",
            current_timestamp_iso="2026-06-13",
            snapshots=_make_snaps(pos=entry + pos_delta, yld=0.0, gas=0.0),
        )

    def test_compare_sorted_descending(self):
        r1 = self._make_report(5.0, "low")
        r2 = self._make_report(25.0, "high")
        r3 = self._make_report(12.0, "mid")
        result = compare_positions([r1, r2, r3])
        self.assertEqual(result[0].pool, "high")
        self.assertEqual(result[1].pool, "mid")
        self.assertEqual(result[2].pool, "low")

    def test_compare_single(self):
        r = self._make_report(10.0, "only")
        result = compare_positions([r])
        self.assertEqual(len(result), 1)

    def test_compare_empty(self):
        self.assertEqual(compare_positions([]), [])


class TestFindBestPerforming(unittest.TestCase):

    def _make_report(self, pos: float) -> ProfitabilityReport:
        return analyze(
            protocol="X", pool="Y",
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(pos=pos, yld=0.0, gas=0.0),
        )

    def test_finds_highest_pnl_pct(self):
        r1 = self._make_report(10_500.0)
        r2 = self._make_report(11_000.0)
        r3 = self._make_report(9_800.0)
        best = find_best_performing([r1, r2, r3])
        self.assertAlmostEqual(best.current_position_value_usd, 11_000.0, places=1)

    def test_returns_none_on_empty(self):
        self.assertIsNone(find_best_performing([]))

    def test_single_element(self):
        r = self._make_report(12_000.0)
        best = find_best_performing([r])
        self.assertAlmostEqual(best.current_position_value_usd, 12_000.0, places=1)


class TestAddSnapshot(unittest.TestCase):

    def test_appends_to_empty_list(self):
        snaps = add_snapshot([], 10_000.0, 100.0, 10.0, "2026-06-01")
        self.assertEqual(len(snaps), 1)
        self.assertAlmostEqual(snaps[0].position_value_usd, 10_000.0)
        self.assertAlmostEqual(snaps[0].yield_collected_usd, 100.0)
        self.assertAlmostEqual(snaps[0].gas_spent_usd, 10.0)
        self.assertEqual(snaps[0].timestamp_iso, "2026-06-01")

    def test_appends_multiple(self):
        snaps = []
        snaps = add_snapshot(snaps, 10_000.0, 0.0, 0.0, "2026-06-01")
        snaps = add_snapshot(snaps, 10_100.0, 50.0, 5.0, "2026-06-05")
        snaps = add_snapshot(snaps, 10_200.0, 100.0, 10.0, "2026-06-10")
        self.assertEqual(len(snaps), 3)
        self.assertAlmostEqual(snaps[-1].position_value_usd, 10_200.0)

    def test_does_not_mutate_original(self):
        original = []
        snaps = add_snapshot(original, 10_000.0, 100.0, 10.0, "2026-06-01")
        self.assertEqual(len(original), 0)
        self.assertEqual(len(snaps), 1)

    def test_last_snapshot_used_in_analyze(self):
        snaps = add_snapshot([], 9_000.0, 50.0, 10.0, "2026-06-05")
        snaps = add_snapshot(snaps, 11_000.0, 200.0, 20.0, "2026-06-10")
        r = analyze("X", "Y", 10_000.0, "2026-06-01", "2026-06-10", snaps)
        self.assertAlmostEqual(r.current_position_value_usd, 11_000.0)
        self.assertAlmostEqual(r.total_yield_collected_usd, 200.0)
        self.assertAlmostEqual(r.total_gas_spent_usd, 20.0)


class TestSaveLoadRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_report(self, pos=10_500.0) -> ProfitabilityReport:
        return analyze(
            protocol="Aave", pool="USDC",
            entry_value_usd=10_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-06-10",
            snapshots=_make_snaps(pos=pos),
        )

    def test_save_creates_file(self):
        r = self._make_report()
        save_results(r, self.data_dir)
        log_path = self.data_dir / "profitability_log.json"
        self.assertTrue(log_path.exists())

    def test_load_empty_when_no_file(self):
        history = load_history(self.data_dir)
        self.assertEqual(history, [])

    def test_save_load_round_trip(self):
        r = self._make_report(pos=10_800.0)
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["current_position_value_usd"], 10_800.0)

    def test_multiple_saves_accumulate(self):
        for pos in [10_100.0, 10_200.0, 10_300.0]:
            r = self._make_report(pos=pos)
            save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_at_100(self):
        for i in range(110):
            r = self._make_report(pos=10_000.0 + i)
            save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_report(pos=float(i))
            save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        # Last 100 entries: indices 5..104
        self.assertAlmostEqual(history[0]["current_position_value_usd"], 5.0, places=1)
        self.assertAlmostEqual(history[-1]["current_position_value_usd"], 104.0, places=1)

    def test_saved_to_field_set(self):
        r = self._make_report()
        path = save_results(r, self.data_dir)
        self.assertEqual(r.saved_to, path)

    def test_atomic_write_valid_json(self):
        r = self._make_report()
        save_results(r, self.data_dir)
        log_path = self.data_dir / "profitability_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestEdgeCases(unittest.TestCase):

    def test_no_snapshots_uses_entry_value(self):
        r = analyze(
            protocol="X", pool="Y",
            entry_value_usd=5_000.0,
            entry_timestamp_iso="2026-05-01",
            current_timestamp_iso="2026-06-01",
            snapshots=[],
        )
        self.assertAlmostEqual(r.current_position_value_usd, 5_000.0)
        self.assertAlmostEqual(r.total_yield_collected_usd, 0.0)
        self.assertAlmostEqual(r.total_gas_spent_usd, 0.0)
        self.assertAlmostEqual(r.unrealized_pnl_usd, 0.0)

    def test_single_snapshot(self):
        snaps = [ProfitabilitySnapshot("2026-06-01", 10_100.0, 50.0, 5.0)]
        r = analyze("X", "Y", 10_000.0, "2026-05-01", "2026-06-01", snaps)
        self.assertAlmostEqual(r.current_position_value_usd, 10_100.0)

    def test_entry_value_zero_guard_no_crash(self):
        r = analyze("X", "Y", 0.0, "2026-05-01", "2026-06-10", _make_snaps(pos=0.0))
        self.assertIsInstance(r.total_pnl_pct, float)
        self.assertIsInstance(r.annualized_return_pct, float)

    def test_days_held_zero_ann_is_zero(self):
        r = analyze(
            "X", "Y", 10_000.0,
            "2026-06-10", "2026-06-10",
            _make_snaps(pos=10_500.0),
        )
        self.assertEqual(r.days_held, 0)
        self.assertEqual(r.annualized_return_pct, 0.0)

    def test_large_il_causes_loss_label(self):
        # Large IL → total_pnl negative → profitability_label = LOSS
        r = analyze(
            "X", "Y", 10_000.0,
            "2025-06-13", "2026-06-13",
            _make_snaps(pos=10_500.0, yld=100.0, gas=10.0),
            impermanent_loss_usd=5_000.0,
        )
        self.assertEqual(r.profitability_label, "LOSS")

    def test_snapshots_field_stored(self):
        snaps = _make_snaps()
        r = analyze("X", "Y", 10_000.0, "2026-05-01", "2026-06-10", snaps)
        self.assertEqual(len(r.snapshots), 1)

    def test_protocol_and_pool_stored(self):
        r = analyze("Morpho", "USDC-pool", 10_000.0, "2026-05-01", "2026-06-10", _make_snaps())
        self.assertEqual(r.protocol, "Morpho")
        self.assertEqual(r.pool, "USDC-pool")


if __name__ == "__main__":
    unittest.main()
