"""
tests/test_s21_cashflow_research.py — MP-1303 тесты RS-002 Cashflow Research

Тест-группы:
  TestModuleConstants           — модульные константы (7 тестов)
  TestCashflowInit              — инициализация (3 теста)
  TestGrossBlendedApy           — gross_blended_apy() (4 теста)
  TestNetApyEstimate            — net_apy_estimate() (6 тестов)
  TestIlDragEstimate            — il_drag_estimate() (6 тестов)
  TestStrictEligibleFraction    — strict_eligible_fraction() (3 теста)
  TestRiskClassification        — risk_classification() (2 теста)
  TestAllocate                  — allocate() (8 тестов)
  TestTrackerBasic              — RS002ShadowTracker базовые (6 тестов)
  TestTrackerRingBuffer         — ring-buffer cap=100 (4 теста)
  TestTrackerAtomicWrite        — атомарные записи (3 теста)

Итого: 52 теста (≥35 требуемых)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.strategies.s21_cashflow_research import (
    RESEARCH_ONLY,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_GROSS,
    NET_APY_ESTIMATE_RANGE,
    ALLOCATION,
    GROSS_APY_ASSUMPTIONS,
    STRICT_ELIGIBLE,
    CashflowResearchStrategy,
)
from spa_core.analytics.strategy_rs002_tracker import (
    RS002ShadowTracker,
    RING_BUFFER_CAP,
)


# ══════════════════════════════════════════════════════════════════════════════
# TestModuleConstants
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleConstants(unittest.TestCase):
    """Модульные константы."""

    def test_research_only_is_true(self) -> None:
        self.assertTrue(RESEARCH_ONLY)

    def test_strategy_id(self) -> None:
        self.assertEqual(STRATEGY_ID, "S21")

    def test_strategy_name_contains_research(self) -> None:
        self.assertIn("Research", STRATEGY_NAME)

    def test_target_apy_gross(self) -> None:
        self.assertAlmostEqual(TARGET_APY_GROSS, 29.24, places=2)

    def test_net_apy_range_lower(self) -> None:
        self.assertEqual(NET_APY_ESTIMATE_RANGE[0], 12.0)

    def test_net_apy_range_upper(self) -> None:
        self.assertEqual(NET_APY_ESTIMATE_RANGE[1], 18.0)

    def test_allocation_weights_sum_to_one(self) -> None:
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# TestCashflowInit
# ══════════════════════════════════════════════════════════════════════════════

class TestCashflowInit(unittest.TestCase):
    """Инициализация CashflowResearchStrategy."""

    def test_default_capital(self) -> None:
        s = CashflowResearchStrategy()
        self.assertEqual(s._capital, 50_000.0)

    def test_custom_capital(self) -> None:
        s = CashflowResearchStrategy(capital=100_000.0)
        self.assertEqual(s._capital, 100_000.0)

    def test_invalid_capital_raises(self) -> None:
        with self.assertRaises(ValueError):
            CashflowResearchStrategy(capital=0.0)


# ══════════════════════════════════════════════════════════════════════════════
# TestGrossBlendedApy
# ══════════════════════════════════════════════════════════════════════════════

class TestGrossBlendedApy(unittest.TestCase):
    """gross_blended_apy() расчёты."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()

    def test_gross_apy_approx_target(self) -> None:
        """Gross blended APY должен быть ≈ 29.24%."""
        self.assertAlmostEqual(self.s.gross_blended_apy(), 29.24, places=2)

    def test_gross_apy_returns_float(self) -> None:
        result = self.s.gross_blended_apy()
        self.assertIsInstance(result, float)

    def test_gross_apy_positive(self) -> None:
        self.assertGreater(self.s.gross_blended_apy(), 0.0)

    def test_gross_apy_matches_manual_calc(self) -> None:
        """0.60*40 + 0.10*18 + 0.14*20 + 0.16*4 = 29.24."""
        expected = 0.60 * 40.0 + 0.10 * 18.0 + 0.14 * 20.0 + 0.16 * 4.0
        self.assertAlmostEqual(self.s.gross_blended_apy(), expected, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# TestNetApyEstimate
# ══════════════════════════════════════════════════════════════════════════════

class TestNetApyEstimate(unittest.TestCase):
    """net_apy_estimate() по режимам."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()

    def test_sideways_in_range(self) -> None:
        """Sideways net APY должен быть в диапазоне 12-18%."""
        val = self.s.net_apy_estimate("sideways")
        self.assertGreaterEqual(val, 12.0)
        self.assertLessEqual(val, 18.0)

    def test_trending_less_than_sideways(self) -> None:
        self.assertLess(
            self.s.net_apy_estimate("trending"),
            self.s.net_apy_estimate("sideways"),
        )

    def test_crash_negative_or_zero(self) -> None:
        self.assertLessEqual(self.s.net_apy_estimate("crash"), 0.0)

    def test_crash_less_than_trending(self) -> None:
        self.assertLess(
            self.s.net_apy_estimate("crash"),
            self.s.net_apy_estimate("trending"),
        )

    def test_default_regime_sideways(self) -> None:
        self.assertEqual(
            self.s.net_apy_estimate(),
            self.s.net_apy_estimate("sideways"),
        )

    def test_unknown_regime_fallback(self) -> None:
        """Неизвестный режим не должен бросать исключение."""
        val = self.s.net_apy_estimate("unknown_xyz")
        self.assertIsInstance(val, float)


# ══════════════════════════════════════════════════════════════════════════════
# TestIlDragEstimate
# ══════════════════════════════════════════════════════════════════════════════

class TestIlDragEstimate(unittest.TestCase):
    """il_drag_estimate() модель IL."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()

    def test_no_move_zero_il(self) -> None:
        """При btc_move_pct=0 IL = 0."""
        self.assertEqual(self.s.il_drag_estimate(0.0), 0.0)

    def test_zero_int_zero_il(self) -> None:
        """Целочисленный 0 тоже даёт 0."""
        self.assertEqual(self.s.il_drag_estimate(0), 0.0)

    def test_positive_move_positive_il(self) -> None:
        """При движении +20% IL > 0."""
        self.assertGreater(self.s.il_drag_estimate(20.0), 0.0)

    def test_negative_move_same_as_positive(self) -> None:
        """IL симметричен: +20% = -20%."""
        self.assertAlmostEqual(
            self.s.il_drag_estimate(20.0),
            self.s.il_drag_estimate(-20.0),
            places=6,
        )

    def test_larger_move_larger_il(self) -> None:
        """Больше движение → больше IL."""
        self.assertGreater(
            self.s.il_drag_estimate(50.0),
            self.s.il_drag_estimate(20.0),
        )

    def test_il_drag_10pct_move(self) -> None:
        """10% BTC move: IL drag = 0.60 * 0.5 * 0.01 * 2.0 * 100 = 0.6%."""
        expected = 0.60 * 0.5 * (0.10 ** 2) * 2.0 * 100.0
        self.assertAlmostEqual(self.s.il_drag_estimate(10.0), expected, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# TestStrictEligibleFraction
# ══════════════════════════════════════════════════════════════════════════════

class TestStrictEligibleFraction(unittest.TestCase):
    """strict_eligible_fraction() — только stablecoin_deposit."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()

    def test_fraction_is_016(self) -> None:
        self.assertAlmostEqual(self.s.strict_eligible_fraction(), 0.16, places=6)

    def test_fraction_type_float(self) -> None:
        self.assertIsInstance(self.s.strict_eligible_fraction(), float)

    def test_stablecoin_is_only_eligible(self) -> None:
        """Только stablecoin_deposit = True в STRICT_ELIGIBLE."""
        eligible = [leg for leg, v in STRICT_ELIGIBLE.items() if v]
        self.assertEqual(eligible, ["stablecoin_deposit"])


# ══════════════════════════════════════════════════════════════════════════════
# TestRiskClassification
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskClassification(unittest.TestCase):
    """risk_classification() = AGGRESSIVE."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()

    def test_returns_aggressive(self) -> None:
        self.assertEqual(self.s.risk_classification(), "AGGRESSIVE")

    def test_returns_string(self) -> None:
        self.assertIsInstance(self.s.risk_classification(), str)


# ══════════════════════════════════════════════════════════════════════════════
# TestAllocate
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocate(unittest.TestCase):
    """allocate() — аллокация капитала."""

    def setUp(self) -> None:
        self.s = CashflowResearchStrategy()
        self.capital = 50_000.0

    def test_weights_sum_to_one(self) -> None:
        result = self.s.allocate(self.capital)
        total_weight = sum(leg["weight"] for leg in result["legs"].values())
        self.assertAlmostEqual(total_weight, 1.0, places=9)

    def test_usd_sum_equals_capital(self) -> None:
        result = self.s.allocate(self.capital)
        total_usd = sum(leg["usd"] for leg in result["legs"].values())
        self.assertAlmostEqual(total_usd, self.capital, places=2)

    def test_research_only_flag_in_result(self) -> None:
        result = self.s.allocate(self.capital)
        self.assertTrue(result["research_only"])

    def test_strategy_id_in_result(self) -> None:
        result = self.s.allocate(self.capital)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_all_legs_present(self) -> None:
        result = self.s.allocate(self.capital)
        for leg in ALLOCATION:
            self.assertIn(leg, result["legs"])

    def test_live_apy_used_for_eligible_leg(self) -> None:
        """live_apy для stablecoin_deposit должен применяться."""
        live = {"stablecoin_deposit": 5.5}
        result = self.s.allocate(self.capital, live_apy=live)
        leg = result["legs"]["stablecoin_deposit"]
        self.assertEqual(leg["apy_pct"], 5.5)
        self.assertEqual(leg["apy_source"], "live")

    def test_placeholder_for_non_eligible_leg(self) -> None:
        """btc_usd_conc_liq всегда placeholder."""
        live = {"btc_usd_conc_liq": 999.0}
        result = self.s.allocate(self.capital, live_apy=live)
        leg = result["legs"]["btc_usd_conc_liq"]
        self.assertEqual(leg["apy_source"], "placeholder")
        self.assertEqual(leg["apy_pct"], GROSS_APY_ASSUMPTIONS["btc_usd_conc_liq"])

    def test_invalid_capital_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.allocate(-1000.0)


# ══════════════════════════════════════════════════════════════════════════════
# TestTrackerBasic
# ══════════════════════════════════════════════════════════════════════════════

class TestTrackerBasic(unittest.TestCase):
    """RS002ShadowTracker базовые операции."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.tracker = RS002ShadowTracker(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initial_entry_count_zero(self) -> None:
        self.assertEqual(self.tracker.entry_count(), 0)

    def test_record_increments_count(self) -> None:
        self.tracker.record("2026-06-01", capital=50_000.0)
        self.assertEqual(self.tracker.entry_count(), 1)

    def test_record_returns_dict(self) -> None:
        entry = self.tracker.record("2026-06-01", capital=50_000.0)
        self.assertIsInstance(entry, dict)

    def test_latest_after_record(self) -> None:
        self.tracker.record("2026-06-01", capital=50_000.0)
        latest = self.tracker.latest()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["date"], "2026-06-01")

    def test_latest_is_none_when_empty(self) -> None:
        self.assertIsNone(self.tracker.latest())

    def test_clear_empties_entries(self) -> None:
        self.tracker.record("2026-06-01", capital=50_000.0)
        self.tracker.clear()
        self.assertEqual(self.tracker.entry_count(), 0)


# ══════════════════════════════════════════════════════════════════════════════
# TestTrackerRingBuffer
# ══════════════════════════════════════════════════════════════════════════════

class TestTrackerRingBuffer(unittest.TestCase):
    """Ring-buffer cap=100."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.tracker = RS002ShadowTracker(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_ring_buffer_cap_constant(self) -> None:
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_cap_not_exceeded(self) -> None:
        """После 110 записей count должен быть ≤ 100."""
        for i in range(110):
            self.tracker.record(f"2026-01-{(i % 28) + 1:02d}", capital=50_000.0)
        self.assertLessEqual(self.tracker.entry_count(), RING_BUFFER_CAP)

    def test_latest_is_last_inserted(self) -> None:
        """Последняя запись — самая свежая (tail)."""
        for i in range(1, 106):
            self.tracker.record(f"2026-06-{(i % 28) + 1:02d}", capital=float(i * 100))
        latest = self.tracker.latest()
        self.assertEqual(latest["capital"], float(105 * 100))

    def test_entries_returns_list(self) -> None:
        self.tracker.record("2026-06-01", capital=50_000.0)
        result = self.tracker.entries()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)


# ══════════════════════════════════════════════════════════════════════════════
# TestTrackerAtomicWrite
# ══════════════════════════════════════════════════════════════════════════════

class TestTrackerAtomicWrite(unittest.TestCase):
    """Атомарность записей (файл на диске после record)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.tracker = RS002ShadowTracker(data_dir=self._tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_file_created_after_record(self) -> None:
        path = Path(self._tmpdir) / "rs002_shadow.json"
        self.assertFalse(path.exists())
        self.tracker.record("2026-06-01", capital=50_000.0)
        self.assertTrue(path.exists())

    def test_file_is_valid_json(self) -> None:
        self.tracker.record("2026-06-01", capital=50_000.0)
        path = Path(self._tmpdir) / "rs002_shadow.json"
        with open(path, "r") as fh:
            data = json.load(fh)
        self.assertIn("entries", data)
        self.assertEqual(len(data["entries"]), 1)

    def test_reload_preserves_data(self) -> None:
        """Перезагрузка трекера читает данные с диска."""
        self.tracker.record("2026-06-01", capital=50_000.0)
        tracker2 = RS002ShadowTracker(data_dir=self._tmpdir)
        self.assertEqual(tracker2.entry_count(), 1)


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
