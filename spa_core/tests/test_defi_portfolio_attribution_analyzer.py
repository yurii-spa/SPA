"""
Unit tests for MP-853: DeFiPortfolioAttributionAnalyzer
Run: python3 -m unittest spa_core/tests/test_defi_portfolio_attribution_analyzer.py -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure the project root is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_portfolio_attribution_analyzer import (
    analyze,
    init_log,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(
    protocol="TestProto",
    allocation_usd=10_000.0,
    yield_income_usd=500.0,
    price_pnl_usd=0.0,
    il_loss_usd=0.0,
    fees_paid_usd=0.0,
    holding_days=365,
):
    return {
        "protocol": protocol,
        "allocation_usd": allocation_usd,
        "yield_income_usd": yield_income_usd,
        "price_pnl_usd": price_pnl_usd,
        "il_loss_usd": il_loss_usd,
        "fees_paid_usd": fees_paid_usd,
        "holding_days": holding_days,
    }


class TestReturnFormula(unittest.TestCase):
    """Test the total_return_usd formula."""

    def _get_pos(self, **kwargs):
        result = analyze([_pos(**kwargs)])
        return result["positions"][0]

    def test_pure_yield(self):
        p = self._get_pos(yield_income_usd=1000.0, allocation_usd=10_000.0)
        self.assertAlmostEqual(p["total_return_usd"], 1000.0)

    def test_yield_minus_fees(self):
        p = self._get_pos(yield_income_usd=1000.0, fees_paid_usd=100.0)
        self.assertAlmostEqual(p["total_return_usd"], 900.0)

    def test_yield_minus_il(self):
        p = self._get_pos(yield_income_usd=500.0, il_loss_usd=200.0)
        self.assertAlmostEqual(p["total_return_usd"], 300.0)

    def test_price_gain_plus_yield(self):
        p = self._get_pos(yield_income_usd=300.0, price_pnl_usd=700.0)
        self.assertAlmostEqual(p["total_return_usd"], 1000.0)

    def test_price_loss(self):
        p = self._get_pos(yield_income_usd=100.0, price_pnl_usd=-500.0)
        self.assertAlmostEqual(p["total_return_usd"], -400.0)

    def test_all_components(self):
        p = self._get_pos(
            yield_income_usd=1000.0,
            price_pnl_usd=200.0,
            il_loss_usd=150.0,
            fees_paid_usd=50.0,
        )
        # 1000 + 200 - 150 - 50 = 1000
        self.assertAlmostEqual(p["total_return_usd"], 1000.0)

    def test_all_zeros(self):
        p = self._get_pos(
            yield_income_usd=0.0,
            price_pnl_usd=0.0,
            il_loss_usd=0.0,
            fees_paid_usd=0.0,
        )
        self.assertAlmostEqual(p["total_return_usd"], 0.0)


class TestReturnPct(unittest.TestCase):
    """Test total_return_pct = total_return / allocation * 100."""

    def _get_pos(self, **kwargs):
        result = analyze([_pos(**kwargs)])
        return result["positions"][0]

    def test_return_pct_basic(self):
        p = self._get_pos(allocation_usd=10_000.0, yield_income_usd=500.0)
        self.assertAlmostEqual(p["total_return_pct"], 5.0)

    def test_return_pct_zero_allocation(self):
        p = self._get_pos(allocation_usd=0.0, yield_income_usd=500.0)
        self.assertAlmostEqual(p["total_return_pct"], 0.0)

    def test_return_pct_negative(self):
        p = self._get_pos(
            allocation_usd=10_000.0, yield_income_usd=0.0, price_pnl_usd=-1000.0
        )
        self.assertAlmostEqual(p["total_return_pct"], -10.0)

    def test_return_pct_100pct(self):
        p = self._get_pos(allocation_usd=1000.0, yield_income_usd=1000.0)
        self.assertAlmostEqual(p["total_return_pct"], 100.0)


class TestAnnualizedReturn(unittest.TestCase):
    """Test annualized_return_pct = total_return_pct / holding_days * 365."""

    def _get_pos(self, annualize=True, **kwargs):
        result = analyze([_pos(**kwargs)], config={"annualize": annualize})
        return result["positions"][0]

    def test_annualized_365_days(self):
        # 5% over 365 days → 5% annualized
        p = self._get_pos(
            allocation_usd=10_000.0, yield_income_usd=500.0, holding_days=365
        )
        self.assertAlmostEqual(p["annualized_return_pct"], 5.0, places=4)

    def test_annualized_180_days(self):
        # 10% over 180 days → 10/180*365 ≈ 20.278%
        p = self._get_pos(
            allocation_usd=10_000.0, yield_income_usd=1_000.0, holding_days=180
        )
        expected = 10.0 / 180 * 365
        self.assertAlmostEqual(p["annualized_return_pct"], expected, places=4)

    def test_annualized_none_when_days_zero(self):
        p = self._get_pos(
            allocation_usd=10_000.0, yield_income_usd=500.0, holding_days=0
        )
        self.assertIsNone(p["annualized_return_pct"])

    def test_annualized_none_when_disabled(self):
        p = self._get_pos(
            annualize=False,
            allocation_usd=10_000.0,
            yield_income_usd=500.0,
            holding_days=365,
        )
        self.assertIsNone(p["annualized_return_pct"])

    def test_annualized_none_when_zero_allocation(self):
        p = self._get_pos(
            allocation_usd=0.0, yield_income_usd=500.0, holding_days=365
        )
        self.assertIsNone(p["annualized_return_pct"])

    def test_annualized_1_day(self):
        p = self._get_pos(
            allocation_usd=10_000.0, yield_income_usd=100.0, holding_days=1
        )
        # 1% over 1 day → 365%
        self.assertAlmostEqual(p["annualized_return_pct"], 365.0, places=4)


class TestContributionPcts(unittest.TestCase):
    """Test per-component contribution percentages."""

    def _get_pos(self, **kwargs):
        result = analyze([_pos(**kwargs)])
        return result["positions"][0]

    def test_yield_contribution_pct(self):
        p = self._get_pos(allocation_usd=10_000.0, yield_income_usd=650.0)
        self.assertAlmostEqual(p["yield_contribution_pct"], 6.5)

    def test_price_contribution_pct_positive(self):
        p = self._get_pos(allocation_usd=10_000.0, price_pnl_usd=300.0)
        self.assertAlmostEqual(p["price_contribution_pct"], 3.0)

    def test_price_contribution_pct_negative(self):
        p = self._get_pos(allocation_usd=10_000.0, price_pnl_usd=-200.0)
        self.assertAlmostEqual(p["price_contribution_pct"], -2.0)

    def test_il_drag_pct_is_negative(self):
        # il_drag_pct = -il_loss / allocation * 100 → negative
        p = self._get_pos(allocation_usd=10_000.0, il_loss_usd=500.0)
        self.assertAlmostEqual(p["il_drag_pct"], -5.0)

    def test_fee_drag_pct_is_negative(self):
        p = self._get_pos(allocation_usd=10_000.0, fees_paid_usd=100.0)
        self.assertAlmostEqual(p["fee_drag_pct"], -1.0)

    def test_zero_allocation_contributions(self):
        p = self._get_pos(
            allocation_usd=0.0,
            yield_income_usd=500.0,
            price_pnl_usd=100.0,
            il_loss_usd=50.0,
            fees_paid_usd=10.0,
        )
        for key in (
            "yield_contribution_pct",
            "price_contribution_pct",
            "il_drag_pct",
            "fee_drag_pct",
        ):
            self.assertAlmostEqual(p[key], 0.0, msg=f"{key} should be 0 with 0 alloc")


class TestReturnLabel(unittest.TestCase):
    """Test return_label classification."""

    def _label(self, alloc, ret_usd):
        result = analyze([_pos(allocation_usd=alloc, yield_income_usd=ret_usd)])
        return result["positions"][0]["return_label"]

    def test_label_strong(self):
        # 10% exactly → STRONG
        self.assertEqual(self._label(10_000.0, 1_000.0), "STRONG")

    def test_label_strong_above_10(self):
        # 50% → STRONG
        self.assertEqual(self._label(10_000.0, 5_000.0), "STRONG")

    def test_label_positive(self):
        # 5% → POSITIVE
        self.assertEqual(self._label(10_000.0, 500.0), "POSITIVE")

    def test_label_positive_small(self):
        # 0.1% → POSITIVE
        self.assertEqual(self._label(10_000.0, 10.0), "POSITIVE")

    def test_label_breakeven_zero(self):
        # exactly 0 → BREAKEVEN
        self.assertEqual(self._label(10_000.0, 0.0), "BREAKEVEN")

    def test_label_negative(self):
        # -5% → NEGATIVE
        result = analyze(
            [_pos(allocation_usd=10_000.0, price_pnl_usd=-500.0, yield_income_usd=0.0)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "NEGATIVE")

    def test_label_loss(self):
        # -10% → LOSS
        result = analyze(
            [_pos(allocation_usd=10_000.0, price_pnl_usd=-1000.0, yield_income_usd=0.0)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "LOSS")

    def test_label_loss_deep(self):
        # -50% → LOSS
        result = analyze(
            [_pos(allocation_usd=10_000.0, price_pnl_usd=-5000.0, yield_income_usd=0.0)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "LOSS")

    def test_label_breakeven_tiny_positive(self):
        # 0.005% < 0.01 → BREAKEVEN
        result = analyze(
            [_pos(allocation_usd=10_000.0, yield_income_usd=0.5)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "BREAKEVEN")

    def test_label_breakeven_tiny_negative(self):
        result = analyze(
            [_pos(allocation_usd=10_000.0, price_pnl_usd=-0.5, yield_income_usd=0.0)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "BREAKEVEN")


class TestPortfolioSummary(unittest.TestCase):
    """Test portfolio_summary calculations."""

    def setUp(self):
        self.positions = [
            _pos("Aave", allocation_usd=40_000.0, yield_income_usd=1_400.0),
            _pos("Morpho", allocation_usd=35_000.0, yield_income_usd=2_275.0),
            _pos("Curve", allocation_usd=25_000.0, yield_income_usd=500.0, il_loss_usd=250.0),
        ]
        self.result = analyze(self.positions)
        self.summary = self.result["portfolio_summary"]

    def test_total_allocation(self):
        self.assertAlmostEqual(self.summary["total_allocation_usd"], 100_000.0)

    def test_total_yield(self):
        self.assertAlmostEqual(self.summary["total_yield_usd"], 4_175.0)

    def test_total_il_loss(self):
        self.assertAlmostEqual(self.summary["total_il_loss_usd"], 250.0)

    def test_total_return_usd(self):
        # 1400 + 2275 + (500-250) = 3925
        self.assertAlmostEqual(self.summary["total_return_usd"], 3_925.0)

    def test_total_return_pct(self):
        self.assertAlmostEqual(self.summary["total_return_pct"], 3.925, places=4)

    def test_best_contributor(self):
        # Morpho has highest return: 2275
        self.assertEqual(self.summary["best_contributor"], "Morpho")

    def test_worst_contributor(self):
        # Curve: 500-250 = 250
        # Aave: 1400
        # Morpho: 2275
        # Curve is lowest at 250
        self.assertEqual(self.summary["worst_contributor"], "Curve")

    def test_yield_share_pct_positive_return(self):
        # yield_share = 4175 / 3925 * 100 ≈ 106.37%
        self.assertAlmostEqual(
            self.summary["yield_share_pct"], 4175.0 / 3925.0 * 100.0, places=3
        )


class TestPortfolioSummaryEdge(unittest.TestCase):
    """Edge cases for portfolio_summary."""

    def test_empty_positions(self):
        result = analyze([])
        s = result["portfolio_summary"]
        self.assertAlmostEqual(s["total_allocation_usd"], 0.0)
        self.assertAlmostEqual(s["total_return_usd"], 0.0)
        self.assertAlmostEqual(s["total_return_pct"], 0.0)
        self.assertIsNone(s["best_contributor"])
        self.assertIsNone(s["worst_contributor"])
        self.assertAlmostEqual(s["yield_share_pct"], 0.0)

    def test_single_position(self):
        result = analyze([_pos("Solo", allocation_usd=10_000.0, yield_income_usd=500.0)])
        s = result["portfolio_summary"]
        self.assertEqual(s["best_contributor"], "Solo")
        self.assertEqual(s["worst_contributor"], "Solo")

    def test_yield_share_zero_when_total_return_negative(self):
        # When total_return_usd <= 0, yield_share_pct should be 0.0
        pos = _pos(allocation_usd=10_000.0, yield_income_usd=0.0, price_pnl_usd=-1000.0)
        result = analyze([pos])
        self.assertAlmostEqual(result["portfolio_summary"]["yield_share_pct"], 0.0)

    def test_total_fees_accumulated(self):
        positions = [
            _pos("A", fees_paid_usd=100.0),
            _pos("B", fees_paid_usd=200.0),
        ]
        result = analyze(positions)
        self.assertAlmostEqual(result["portfolio_summary"]["total_fees_usd"], 300.0)

    def test_total_price_pnl_accumulated(self):
        positions = [
            _pos("A", price_pnl_usd=500.0),
            _pos("B", price_pnl_usd=-200.0),
        ]
        result = analyze(positions)
        self.assertAlmostEqual(result["portfolio_summary"]["total_price_pnl_usd"], 300.0)


class TestAttributionBreakdown(unittest.TestCase):
    """Test portfolio-level attribution_breakdown."""

    def test_basic_attribution(self):
        positions = [
            _pos(
                "A",
                allocation_usd=10_000.0,
                yield_income_usd=500.0,
                price_pnl_usd=100.0,
                il_loss_usd=50.0,
                fees_paid_usd=20.0,
            )
        ]
        result = analyze(positions)
        ab = result["attribution_breakdown"]
        self.assertAlmostEqual(ab["yield_contribution_pct"], 5.0)
        self.assertAlmostEqual(ab["price_contribution_pct"], 1.0)
        self.assertAlmostEqual(ab["il_drag_pct"], -0.5)
        self.assertAlmostEqual(ab["fee_drag_pct"], -0.2)
        # net = (500+100-50-20)/10000*100 = 530/10000*100 = 5.3
        self.assertAlmostEqual(ab["net_return_pct"], 5.3)

    def test_attribution_zero_allocation(self):
        result = analyze([])
        ab = result["attribution_breakdown"]
        for key in (
            "yield_contribution_pct",
            "price_contribution_pct",
            "il_drag_pct",
            "fee_drag_pct",
            "net_return_pct",
        ):
            self.assertAlmostEqual(ab[key], 0.0, msg=f"{key} should be 0.0")

    def test_attribution_multi_position_aggregate(self):
        positions = [
            _pos("A", allocation_usd=5_000.0, yield_income_usd=250.0),
            _pos("B", allocation_usd=5_000.0, yield_income_usd=250.0),
        ]
        result = analyze(positions)
        ab = result["attribution_breakdown"]
        # total_yield=500 / total_alloc=10000 * 100 = 5%
        self.assertAlmostEqual(ab["yield_contribution_pct"], 5.0)

    def test_attribution_breakdown_keys_present(self):
        result = analyze([_pos()])
        ab = result["attribution_breakdown"]
        for key in (
            "yield_contribution_pct",
            "price_contribution_pct",
            "il_drag_pct",
            "fee_drag_pct",
            "net_return_pct",
        ):
            self.assertIn(key, ab)


class TestResultStructure(unittest.TestCase):
    """Test that the result dict has all required keys."""

    def test_top_level_keys(self):
        result = analyze([_pos()])
        for key in ("positions", "portfolio_summary", "attribution_breakdown", "timestamp"):
            self.assertIn(key, result)

    def test_position_keys(self):
        result = analyze([_pos()])
        pos = result["positions"][0]
        for key in (
            "protocol",
            "allocation_usd",
            "total_return_usd",
            "total_return_pct",
            "annualized_return_pct",
            "yield_contribution_pct",
            "price_contribution_pct",
            "il_drag_pct",
            "fee_drag_pct",
            "return_label",
        ):
            self.assertIn(key, pos)

    def test_portfolio_summary_keys(self):
        result = analyze([_pos()])
        s = result["portfolio_summary"]
        for key in (
            "total_allocation_usd",
            "total_return_usd",
            "total_return_pct",
            "total_yield_usd",
            "total_price_pnl_usd",
            "total_il_loss_usd",
            "total_fees_usd",
            "yield_share_pct",
            "best_contributor",
            "worst_contributor",
        ):
            self.assertIn(key, s)

    def test_timestamp_is_float(self):
        result = analyze([_pos()])
        self.assertIsInstance(result["timestamp"], float)
        self.assertGreater(result["timestamp"], 0)

    def test_positions_list_length(self):
        positions = [_pos("A"), _pos("B"), _pos("C")]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 3)


class TestMultiplePositions(unittest.TestCase):
    """Test with multiple positions to validate aggregation."""

    def test_two_positions_best_worst(self):
        positions = [
            _pos("Winner", allocation_usd=10_000.0, yield_income_usd=2_000.0),
            _pos("Loser", allocation_usd=10_000.0, price_pnl_usd=-500.0, yield_income_usd=0.0),
        ]
        result = analyze(positions)
        s = result["portfolio_summary"]
        self.assertEqual(s["best_contributor"], "Winner")
        self.assertEqual(s["worst_contributor"], "Loser")

    def test_three_positions_total_return(self):
        positions = [
            _pos("A", allocation_usd=10_000.0, yield_income_usd=100.0),
            _pos("B", allocation_usd=10_000.0, yield_income_usd=200.0),
            _pos("C", allocation_usd=10_000.0, yield_income_usd=300.0),
        ]
        result = analyze(positions)
        self.assertAlmostEqual(result["portfolio_summary"]["total_return_usd"], 600.0)

    def test_config_annualize_false_all_none(self):
        positions = [_pos("A", holding_days=100), _pos("B", holding_days=200)]
        result = analyze(positions, config={"annualize": False})
        for p in result["positions"]:
            self.assertIsNone(p["annualized_return_pct"])

    def test_config_defaults_to_annualize_true(self):
        result = analyze([_pos("A", holding_days=100)])
        p = result["positions"][0]
        self.assertIsNotNone(p["annualized_return_pct"])

    def test_protocol_name_preserved(self):
        result = analyze([_pos("UniqueProtoName")])
        self.assertEqual(result["positions"][0]["protocol"], "UniqueProtoName")


class TestLogFunctions(unittest.TestCase):
    """Test ring-buffer log persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_log_creates_empty_file(self):
        init_log(data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "portfolio_attribution_log.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(data, [])

    def test_init_log_no_overwrite(self):
        init_log(data_dir=self.tmpdir)
        # Save one entry
        analyze([_pos()], data_dir=self.tmpdir, save=True)
        # Init again — should not overwrite
        init_log(data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_save_and_load(self):
        analyze([_pos()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)
        self.assertIn("portfolio_summary", history[0])

    def test_ring_buffer_cap(self):
        for _ in range(105):
            analyze([_pos()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertLessEqual(len(history), 100)

    def test_load_history_empty_when_no_file(self):
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history, [])

    def test_save_false_does_not_write(self):
        analyze([_pos()], data_dir=self.tmpdir, save=False)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history, [])

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            analyze([_pos()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_exact_100(self):
        for _ in range(100):
            analyze([_pos()], data_dir=self.tmpdir, save=True)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_101_drops_oldest(self):
        # Save 101 — first should be dropped
        for i in range(101):
            analyze(
                [_pos(f"Proto{i}", yield_income_usd=float(i))],
                data_dir=self.tmpdir,
                save=True,
            )
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)
        # The oldest (i=0) should be gone; youngest (i=100) should be last
        last = history[-1]
        self.assertEqual(last["positions"][0]["protocol"], "Proto100")


class TestEdgeCases(unittest.TestCase):
    """Additional edge cases."""

    def test_zero_allocation_single_pos(self):
        result = analyze([_pos(allocation_usd=0.0)])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_return_pct"], 0.0)
        self.assertAlmostEqual(p["yield_contribution_pct"], 0.0)
        self.assertAlmostEqual(p["il_drag_pct"], 0.0)
        self.assertAlmostEqual(p["fee_drag_pct"], 0.0)

    def test_large_allocation(self):
        result = analyze([_pos(allocation_usd=1_000_000.0, yield_income_usd=50_000.0)])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_return_pct"], 5.0)

    def test_negative_price_pnl_contribution(self):
        result = analyze([_pos(allocation_usd=10_000.0, price_pnl_usd=-300.0)])
        p = result["positions"][0]
        self.assertAlmostEqual(p["price_contribution_pct"], -3.0)

    def test_high_il_loss_causes_loss_label(self):
        result = analyze(
            [_pos(allocation_usd=10_000.0, yield_income_usd=0.0, il_loss_usd=1_500.0)]
        )
        p = result["positions"][0]
        self.assertEqual(p["return_label"], "LOSS")
        self.assertAlmostEqual(p["il_drag_pct"], -15.0)

    def test_result_has_no_extra_position_keys(self):
        result = analyze([_pos()])
        p = result["positions"][0]
        expected_keys = {
            "protocol",
            "allocation_usd",
            "total_return_usd",
            "total_return_pct",
            "annualized_return_pct",
            "yield_contribution_pct",
            "price_contribution_pct",
            "il_drag_pct",
            "fee_drag_pct",
            "return_label",
        }
        self.assertEqual(set(p.keys()), expected_keys)

    def test_fees_and_il_both_drag(self):
        result = analyze(
            [
                _pos(
                    allocation_usd=10_000.0,
                    yield_income_usd=1000.0,
                    il_loss_usd=200.0,
                    fees_paid_usd=100.0,
                )
            ]
        )
        p = result["positions"][0]
        self.assertAlmostEqual(p["il_drag_pct"], -2.0)
        self.assertAlmostEqual(p["fee_drag_pct"], -1.0)

    def test_empty_list_positions_in_result(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])

    def test_empty_list_attribution_breakdown_zeros(self):
        result = analyze([])
        ab = result["attribution_breakdown"]
        for v in ab.values():
            self.assertAlmostEqual(v, 0.0)

    def test_positions_order_preserved(self):
        positions = [_pos("First"), _pos("Second"), _pos("Third")]
        result = analyze(positions)
        protocols = [p["protocol"] for p in result["positions"]]
        self.assertEqual(protocols, ["First", "Second", "Third"])

    def test_config_none_uses_defaults(self):
        result = analyze([_pos(holding_days=100)], config=None)
        p = result["positions"][0]
        # annualize defaults to True so should not be None
        self.assertIsNotNone(p["annualized_return_pct"])

    def test_mixed_il_zero_and_nonzero(self):
        positions = [
            _pos("A", allocation_usd=10_000.0, il_loss_usd=0.0),
            _pos("B", allocation_usd=10_000.0, il_loss_usd=500.0),
        ]
        result = analyze(positions)
        self.assertAlmostEqual(result["positions"][0]["il_drag_pct"], 0.0)
        self.assertAlmostEqual(result["positions"][1]["il_drag_pct"], -5.0)

    def test_breakeven_label_for_exact_zero_pct(self):
        # yield exactly cancels fees → 0 return → BREAKEVEN
        result = analyze(
            [_pos(allocation_usd=10_000.0, yield_income_usd=100.0, fees_paid_usd=100.0)]
        )
        self.assertEqual(result["positions"][0]["return_label"], "BREAKEVEN")


class TestNumericalPrecision(unittest.TestCase):
    """Test floating-point precision scenarios."""

    def test_small_allocation(self):
        result = analyze([_pos(allocation_usd=1.0, yield_income_usd=0.05)])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_return_pct"], 5.0, places=5)

    def test_very_large_values(self):
        result = analyze(
            [_pos(allocation_usd=1e9, yield_income_usd=5e7, holding_days=365)]
        )
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_return_pct"], 5.0, places=5)

    def test_annualized_return_precision(self):
        result = analyze([_pos(allocation_usd=10_000.0, yield_income_usd=274.0, holding_days=365)])
        p = result["positions"][0]
        # 274/10000*100/365*365 = 2.74
        self.assertAlmostEqual(p["annualized_return_pct"], 2.74, places=5)


if __name__ == "__main__":
    unittest.main()
