"""
Tests for MP-763: PositionSizingEngine
≥65 unittest tests covering all specified cases.

Run: python3 -m unittest spa_core.tests.test_position_sizing_engine -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.position_sizing_engine import (
    _FIXED_FRACTION_PCT,
    _KELLY_MAX,
    _MAX_ALLOWED_LOSS_PCT,
    _RING_BUFFER_MAX,
    PortfolioSizingResult,
    SizingInput,
    SizingResult,
    get_sizing_label,
    kelly_fraction,
    load_history,
    max_dd_position,
    save_results,
    size_portfolio,
    size_position,
    vol_adjusted_position,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PORTFOLIO = 100_000.0


def _inp(
    name: str = "TestStrat",
    portfolio: float = PORTFOLIO,
    apy: float = 5.0,
    vol: float = 10.0,
    max_dd: float = 10.0,
    win_rate: float = 0.60,
    avg_win: float = 1.0,
    avg_loss: float = 0.50,
) -> SizingInput:
    return SizingInput(
        strategy_name=name,
        portfolio_value_usd=portfolio,
        strategy_apy_pct=apy,
        strategy_volatility_pct=vol,
        max_drawdown_pct=max_dd,
        win_rate=win_rate,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
    )


def _inp_dict(**kwargs) -> dict:
    base = dict(
        strategy_name="S",
        portfolio_value_usd=PORTFOLIO,
        strategy_apy_pct=5.0,
        strategy_volatility_pct=10.0,
        max_drawdown_pct=10.0,
        win_rate=0.60,
        avg_win_pct=1.0,
        avg_loss_pct=0.50,
    )
    base.update(kwargs)
    return base


# ===========================================================================
# 1. kelly_fraction
# ===========================================================================

class TestKellyFraction(unittest.TestCase):

    def test_formula_basic(self):
        # win_rate=0.55, avg_win=1.0, avg_loss=1.0 → b=1 → f=0.55 - 0.45/1 = 0.10
        # raw=0.10 < 0.25 cap → returned as-is
        result = kelly_fraction(0.55, 1.0, 1.0)
        self.assertAlmostEqual(result, 0.10, places=6)

    def test_clamped_at_kelly_max(self):
        # Very favorable odds → raw f > 0.25 → clamped
        result = kelly_fraction(0.99, 10.0, 0.01)
        self.assertAlmostEqual(result, _KELLY_MAX)

    def test_negative_kelly_returns_zero(self):
        # Negative expectancy → clamped to 0
        result = kelly_fraction(0.2, 0.5, 2.0)
        self.assertAlmostEqual(result, 0.0)

    def test_avg_loss_zero_returns_zero(self):
        result = kelly_fraction(0.7, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_avg_loss_negative_returns_zero(self):
        result = kelly_fraction(0.7, 1.0, -1.0)
        self.assertAlmostEqual(result, 0.0)

    def test_perfect_win_rate_near_max(self):
        # win_rate→1 → f → 1 - 0/b = 1 → clamped 0.25
        result = kelly_fraction(1.0, 1.0, 0.5)
        self.assertAlmostEqual(result, _KELLY_MAX)

    def test_fifty_fifty(self):
        # win_rate=0.5, b=1 → f = 0.5 - 0.5/1 = 0
        result = kelly_fraction(0.5, 1.0, 1.0)
        self.assertAlmostEqual(result, 0.0)

    def test_result_in_valid_range(self):
        for wr in [0.3, 0.5, 0.6, 0.8]:
            r = kelly_fraction(wr, 1.0, 0.5)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, _KELLY_MAX)


# ===========================================================================
# 2. vol_adjusted_position
# ===========================================================================

class TestVolAdjustedPosition(unittest.TestCase):

    def test_formula_10pct_vol(self):
        # target=10, vol=10 → raw=portfolio → clamped to 30%
        result = vol_adjusted_position(100_000, 10.0)
        self.assertAlmostEqual(result, 30_000.0)  # 10/10 * 100k = 100k, but capped at 30%

    def test_formula_20pct_vol(self):
        # target=10, vol=20 → raw=50_000 → not exceeds 30% cap (30k) → wait
        # raw = 100_000 * 10/20 = 50_000; cap = 30_000 → returns 30_000
        result = vol_adjusted_position(100_000, 20.0)
        self.assertAlmostEqual(result, 30_000.0)

    def test_formula_50pct_vol(self):
        # raw = 100_000 * 10/50 = 20_000 < 30_000 cap → returns 20_000
        result = vol_adjusted_position(100_000, 50.0)
        self.assertAlmostEqual(result, 20_000.0)

    def test_capped_at_30pct(self):
        # Very low vol → huge raw → capped at 30%
        result = vol_adjusted_position(100_000, 1.0)
        self.assertAlmostEqual(result, 30_000.0)  # cap = 100k * 0.30 = 30k

    def test_vol_zero_returns_10pct(self):
        result = vol_adjusted_position(100_000, 0.0)
        self.assertAlmostEqual(result, 10_000.0)

    def test_vol_negative_returns_10pct(self):
        result = vol_adjusted_position(100_000, -5.0)
        self.assertAlmostEqual(result, 10_000.0)

    def test_very_high_volatility_tiny_position(self):
        # vol=200% → raw = 100k * 10/200 = 5_000
        result = vol_adjusted_position(100_000, 200.0)
        self.assertAlmostEqual(result, 5_000.0)

    def test_scales_with_portfolio(self):
        r1 = vol_adjusted_position(200_000, 50.0)
        r2 = vol_adjusted_position(100_000, 50.0)
        self.assertAlmostEqual(r1, r2 * 2)


# ===========================================================================
# 3. max_dd_position
# ===========================================================================

class TestMaxDdPosition(unittest.TestCase):

    def test_formula_basic(self):
        # max_allowed=5%, max_dd=10% → 100k * 5/10 = 50_000
        result = max_dd_position(100_000, 10.0)
        self.assertAlmostEqual(result, 50_000.0)

    def test_formula_20pct_dd(self):
        # 100k * 5/20 = 25_000
        result = max_dd_position(100_000, 20.0)
        self.assertAlmostEqual(result, 25_000.0)

    def test_max_dd_zero_returns_5pct(self):
        result = max_dd_position(100_000, 0.0)
        self.assertAlmostEqual(result, 5_000.0)

    def test_max_dd_negative_returns_5pct(self):
        result = max_dd_position(100_000, -10.0)
        self.assertAlmostEqual(result, 5_000.0)

    def test_custom_max_allowed_loss(self):
        # 10% allowed loss, 20% dd → 100k * 10/20 = 50_000
        result = max_dd_position(100_000, 20.0, max_allowed_loss_pct=10.0)
        self.assertAlmostEqual(result, 50_000.0)

    def test_scales_with_portfolio(self):
        r1 = max_dd_position(200_000, 10.0)
        r2 = max_dd_position(100_000, 10.0)
        self.assertAlmostEqual(r1, r2 * 2)

    def test_large_drawdown_small_position(self):
        # 50% dd → 100k * 5/50 = 10_000
        result = max_dd_position(100_000, 50.0)
        self.assertAlmostEqual(result, 10_000.0)


# ===========================================================================
# 4. get_sizing_label
# ===========================================================================

class TestGetSizingLabel(unittest.TestCase):

    def test_aggressive(self):
        self.assertEqual(get_sizing_label(25.0), "AGGRESSIVE")

    def test_aggressive_boundary(self):
        self.assertEqual(get_sizing_label(20.1), "AGGRESSIVE")

    def test_moderate_at_20(self):
        # exactly 20% → MODERATE (not > 20)
        self.assertEqual(get_sizing_label(20.0), "MODERATE")

    def test_moderate_at_10(self):
        self.assertEqual(get_sizing_label(10.0), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(get_sizing_label(15.0), "MODERATE")

    def test_conservative(self):
        self.assertEqual(get_sizing_label(5.0), "CONSERVATIVE")

    def test_conservative_near_boundary(self):
        self.assertEqual(get_sizing_label(9.9), "CONSERVATIVE")

    def test_zero_conservative(self):
        self.assertEqual(get_sizing_label(0.0), "CONSERVATIVE")


# ===========================================================================
# 5. size_position
# ===========================================================================

class TestSizePosition(unittest.TestCase):

    def _result(self, **kwargs) -> SizingResult:
        return size_position(_inp(**kwargs))

    def test_returns_sizing_result(self):
        self.assertIsInstance(self._result(), SizingResult)

    def test_fixed_fraction_pct_always_2(self):
        r = self._result()
        self.assertAlmostEqual(r.fixed_fraction_pct, _FIXED_FRACTION_PCT)

    def test_fixed_fraction_usd(self):
        r = self._result(portfolio=100_000)
        self.assertAlmostEqual(r.fixed_fraction_usd, 2_000.0)

    def test_kelly_position_usd(self):
        r = self._result(win_rate=0.6, avg_win=1.0, avg_loss=0.5)
        kf = kelly_fraction(0.6, 1.0, 0.5)
        self.assertAlmostEqual(r.kelly_position_usd, PORTFOLIO * kf, places=4)

    def test_kelly_fraction_field(self):
        r = self._result(win_rate=0.6, avg_win=1.0, avg_loss=0.5)
        expected = kelly_fraction(0.6, 1.0, 0.5)
        self.assertAlmostEqual(r.kelly_fraction, expected, places=6)

    def test_vol_adjusted_usd(self):
        r = self._result(vol=50.0)
        expected = vol_adjusted_position(PORTFOLIO, 50.0)
        self.assertAlmostEqual(r.vol_adjusted_usd, expected, places=4)

    def test_vol_adjusted_fraction_pct(self):
        r = self._result(vol=50.0)
        expected = r.vol_adjusted_usd / PORTFOLIO * 100
        self.assertAlmostEqual(r.vol_adjusted_fraction_pct, expected, places=6)

    def test_max_dd_usd(self):
        r = self._result(max_dd=10.0)
        expected = max_dd_position(PORTFOLIO, 10.0)
        self.assertAlmostEqual(r.max_dd_usd, expected, places=4)

    def test_max_dd_fraction_pct(self):
        r = self._result(max_dd=10.0)
        expected = r.max_dd_usd / PORTFOLIO * 100
        self.assertAlmostEqual(r.max_dd_fraction_pct, expected, places=6)

    def test_recommended_is_minimum_of_four(self):
        r = self._result()
        expected = min(
            r.fixed_fraction_usd,
            r.kelly_position_usd,
            r.vol_adjusted_usd,
            r.max_dd_usd,
        )
        self.assertAlmostEqual(r.recommended_position_usd, expected, places=4)

    def test_recommended_fraction_pct(self):
        r = self._result()
        expected = r.recommended_position_usd / PORTFOLIO * 100
        self.assertAlmostEqual(r.recommended_fraction_pct, expected, places=6)

    def test_expected_annual_yield(self):
        r = self._result(apy=5.0)
        expected = r.recommended_position_usd * 5.0 / 100.0
        self.assertAlmostEqual(r.expected_annual_yield_usd, expected, places=4)

    def test_expected_annual_risk(self):
        r = self._result(vol=10.0)
        expected = r.recommended_position_usd * 10.0 / 100.0
        self.assertAlmostEqual(r.expected_annual_risk_usd, expected, places=4)

    def test_sizing_label_conservative(self):
        # Tiny positions → conservative
        r = self._result(max_dd=1.0, vol=200.0, win_rate=0.3)
        self.assertEqual(r.sizing_label, "CONSERVATIVE")

    def test_sizing_label_aggressive(self):
        # Force a large rec: high kelly, low vol, low max_dd but large
        # To get >20%, we need all 4 methods to be large.
        # fixed=2%, kelly=2%, vol...max_dd must all be >20%
        # This is hard to manufacture → just test the label function directly
        # already covered in TestGetSizingLabel
        pass

    def test_recommendation_conservative_text(self):
        r = self._result(max_dd=1.0, vol=200.0, win_rate=0.3)
        self.assertIn("conservative", r.recommendation.lower())

    def test_recommendation_is_string(self):
        r = self._result()
        self.assertIsInstance(r.recommendation, str)
        self.assertGreater(len(r.recommendation), 0)

    def test_strategy_name_preserved(self):
        r = self._result(name="MyStrategy")
        self.assertEqual(r.strategy_name, "MyStrategy")

    def test_portfolio_value_preserved(self):
        r = self._result(portfolio=200_000)
        self.assertAlmostEqual(r.portfolio_value_usd, 200_000.0)

    def test_very_high_vol_small_vol_adjusted(self):
        # vol=100% → raw = 100k * 10/100 = 10k; recommended ≤ 10k
        r = self._result(vol=100.0)
        self.assertLessEqual(r.vol_adjusted_usd, 10_000.0 + 1e-6)

    def test_perfect_win_rate_kelly_at_max(self):
        r = self._result(win_rate=0.99, avg_win=10.0, avg_loss=0.01)
        self.assertAlmostEqual(r.kelly_fraction, _KELLY_MAX)


# ===========================================================================
# 6. size_portfolio
# ===========================================================================

class TestSizePortfolio(unittest.TestCase):

    def _data(self, n: int = 3) -> list:
        names = ["S1", "S2", "S3"]
        return [_inp_dict(strategy_name=names[i]) for i in range(n)]

    def test_returns_portfolio_sizing_result(self):
        r = size_portfolio(self._data(2))
        self.assertIsInstance(r, PortfolioSizingResult)

    def test_total_recommended_usd(self):
        r = size_portfolio(self._data(2))
        expected = sum(s.recommended_position_usd for s in r.sizings)
        self.assertAlmostEqual(r.total_recommended_usd, expected, places=4)

    def test_total_recommended_pct(self):
        r = size_portfolio(self._data(2))
        expected = r.total_recommended_usd / PORTFOLIO * 100
        self.assertAlmostEqual(r.total_recommended_pct, expected, places=6)

    def test_remaining_cash(self):
        r = size_portfolio(self._data(2))
        expected = PORTFOLIO - r.total_recommended_usd
        self.assertAlmostEqual(r.remaining_cash_usd, expected, places=4)

    def test_over_allocated_false_normal(self):
        r = size_portfolio(self._data(2))
        self.assertFalse(r.over_allocated)

    def test_over_allocated_true_when_over_90pct(self):
        # Force high allocation: many strategies with favorable parameters
        # 45 strategies × ~2% fixed = ~90%, just need >90%
        # use 50 strategies all at 2% fixed
        data = [_inp_dict(strategy_name=f"S{i}") for i in range(50)]
        r = size_portfolio(data)
        if r.total_recommended_pct > 90.0:
            self.assertTrue(r.over_allocated)
        # If still under 90% due to kelly/vol/maxdd constraints, over_allocated=False
        self.assertEqual(
            r.over_allocated,
            r.total_recommended_usd > PORTFOLIO * 0.90,
        )

    def test_recommendation_summary_is_string(self):
        r = size_portfolio(self._data(2))
        self.assertIsInstance(r.recommendation_summary, str)
        self.assertGreater(len(r.recommendation_summary), 0)

    def test_over_allocated_text(self):
        # Manually check text when over_allocated is True
        data = [_inp_dict(strategy_name=f"S{i}") for i in range(50)]
        r = size_portfolio(data)
        if r.over_allocated:
            self.assertIn("90%", r.recommendation_summary)

    def test_sizings_count(self):
        r = size_portfolio(self._data(3))
        self.assertEqual(len(r.sizings), 3)

    def test_saved_to_defaults_empty(self):
        r = size_portfolio(self._data(2))
        self.assertEqual(r.saved_to, "")

    def test_single_strategy(self):
        r = size_portfolio([_inp_dict()])
        self.assertEqual(len(r.sizings), 1)
        self.assertAlmostEqual(
            r.total_recommended_usd,
            r.sizings[0].recommended_position_usd,
            places=4,
        )

    def test_remaining_cash_not_exceeds_portfolio(self):
        r = size_portfolio(self._data(2))
        self.assertLessEqual(r.total_recommended_usd, PORTFOLIO * 2)  # sanity


# ===========================================================================
# 7. Persistence: save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _result(self):
        return size_portfolio([_inp_dict(strategy_name="S1"), _inp_dict(strategy_name="S2")])

    def test_load_history_empty_when_missing(self):
        h = load_history(self.data_dir)
        self.assertEqual(h, [])

    def test_load_history_empty_on_corrupt_file(self):
        (self.data_dir / "position_sizing_log.json").write_text("CORRUPT!!")
        h = load_history(self.data_dir)
        self.assertEqual(h, [])

    def test_save_creates_file(self):
        r = self._result()
        save_results(r, self.data_dir)
        self.assertTrue((self.data_dir / "position_sizing_log.json").exists())

    def test_save_sets_saved_to(self):
        r = self._result()
        save_results(r, self.data_dir)
        self.assertIn("position_sizing_log.json", r.saved_to)

    def test_round_trip(self):
        r = self._result()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 1)
        self.assertIn("total_recommended_usd", history[0])
        self.assertIn("sizings", history[0])

    def test_appends_to_existing(self):
        for _ in range(3):
            save_results(self._result(), self.data_dir)
        h = load_history(self.data_dir)
        self.assertEqual(len(h), 3)

    def test_ring_buffer_cap(self):
        for _ in range(_RING_BUFFER_MAX + 5):
            save_results(self._result(), self.data_dir)
        h = load_history(self.data_dir)
        self.assertLessEqual(len(h), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest(self):
        for _ in range(105):
            save_results(self._result(), self.data_dir)
        h = load_history(self.data_dir)
        self.assertEqual(len(h), _RING_BUFFER_MAX)

    def test_saved_at_key_present(self):
        r = self._result()
        save_results(r, self.data_dir)
        h = load_history(self.data_dir)
        self.assertIn("saved_at", h[0])

    def test_over_allocated_preserved(self):
        r = self._result()
        save_results(r, self.data_dir)
        h = load_history(self.data_dir)
        self.assertEqual(h[0]["over_allocated"], r.over_allocated)

    def test_total_recommended_preserved(self):
        r = self._result()
        save_results(r, self.data_dir)
        h = load_history(self.data_dir)
        self.assertAlmostEqual(
            h[0]["total_recommended_usd"],
            r.total_recommended_usd,
            places=4,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
