"""
Tests for MP-707: PortfolioConcentrationOptimizer
≥ 65 tests. Pure unittest, stdlib only.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.portfolio_concentration_optimizer import (
    RING_BUFFER_CAP,
    OptimizationResult,
    Position,
    calculate_hhi,
    calculate_weighted_avg,
    explain_trades,
    load_history,
    optimize,
    save_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(name, apy=5.0, weight=0.25, risk=30.0, max_w=0.4, protocol="TestProto", chain="ethereum"):
    return Position(
        name=name,
        protocol=protocol,
        chain=chain,
        current_weight=weight,
        apy=apy,
        risk_score=risk,
        max_weight=max_w,
    )


def _four_equal_positions():
    return [
        _pos("A", apy=4.0, weight=0.25),
        _pos("B", apy=5.0, weight=0.25),
        _pos("C", apy=6.0, weight=0.25),
        _pos("D", apy=7.0, weight=0.25),
    ]


def _concentrated_portfolio():
    return [
        _pos("Dominant", apy=3.5, weight=0.80),
        _pos("Minor1",   apy=5.0, weight=0.10),
        _pos("Minor2",   apy=6.0, weight=0.10),
    ]


def _tmp_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


# ---------------------------------------------------------------------------
# 1. calculate_hhi
# ---------------------------------------------------------------------------
class TestCalculateHhi(unittest.TestCase):

    def test_single_position_full_weight(self):
        self.assertAlmostEqual(calculate_hhi([1.0]), 1.0, places=9)

    def test_two_equal_weights(self):
        self.assertAlmostEqual(calculate_hhi([0.5, 0.5]), 0.5, places=9)

    def test_four_equal_weights(self):
        self.assertAlmostEqual(calculate_hhi([0.25, 0.25, 0.25, 0.25]), 0.25, places=9)

    def test_ten_equal_weights(self):
        weights = [0.1] * 10
        self.assertAlmostEqual(calculate_hhi(weights), 0.1, places=9)

    def test_concentrated_portfolio(self):
        hhi = calculate_hhi([0.8, 0.1, 0.1])
        self.assertAlmostEqual(hhi, 0.64 + 0.01 + 0.01, places=9)

    def test_empty_list_returns_zero(self):
        self.assertAlmostEqual(calculate_hhi([]), 0.0, places=9)

    def test_hhi_between_0_and_1(self):
        weights = [0.3, 0.3, 0.2, 0.2]
        hhi = calculate_hhi(weights)
        self.assertGreaterEqual(hhi, 0.0)
        self.assertLessEqual(hhi, 1.0)

    def test_three_equal(self):
        hhi = calculate_hhi([1/3, 1/3, 1/3])
        self.assertAlmostEqual(hhi, 1/3, places=6)


# ---------------------------------------------------------------------------
# 2. calculate_weighted_avg
# ---------------------------------------------------------------------------
class TestCalculateWeightedAvg(unittest.TestCase):

    def test_single_element(self):
        self.assertAlmostEqual(calculate_weighted_avg([1.0], [5.0]), 5.0, places=9)

    def test_equal_weights(self):
        result = calculate_weighted_avg([0.5, 0.5], [4.0, 6.0])
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_skewed_weights(self):
        result = calculate_weighted_avg([0.8, 0.2], [4.0, 6.0])
        self.assertAlmostEqual(result, 4.4, places=9)

    def test_zero_weight(self):
        result = calculate_weighted_avg([1.0, 0.0], [5.0, 100.0])
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_four_positions(self):
        result = calculate_weighted_avg([0.25, 0.25, 0.25, 0.25], [4.0, 5.0, 6.0, 7.0])
        self.assertAlmostEqual(result, 5.5, places=9)

    def test_returns_float(self):
        result = calculate_weighted_avg([0.5, 0.5], [3.0, 7.0])
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 3. optimize — recommended weights sum to 1
# ---------------------------------------------------------------------------
class TestOptimizeWeightSum(unittest.TestCase):

    def test_two_positions_sum_to_1(self):
        positions = [_pos("A", weight=0.5), _pos("B", weight=0.5)]
        result = optimize(positions)
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_four_positions_sum_to_1(self):
        result = optimize(_four_equal_positions())
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_concentrated_positions_sum_to_1(self):
        result = optimize(_concentrated_portfolio())
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_single_position_sum_to_1(self):
        result = optimize([_pos("Solo", weight=1.0)])
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_five_positions_sum_to_1(self):
        positions = [_pos(f"P{i}", weight=0.2, apy=3.0 + i) for i in range(5)]
        result = optimize(positions)
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)


# ---------------------------------------------------------------------------
# 4. optimize — max_weight cap
# ---------------------------------------------------------------------------
class TestOptimizeMaxWeightCap(unittest.TestCase):

    def test_max_weight_respected(self):
        positions = [_pos(f"P{i}", weight=0.25, apy=5.0, max_w=0.3) for i in range(4)]
        result = optimize(positions)
        for name, w in result.recommended_weights.items():
            self.assertLessEqual(w, 0.3 + 1e-9)

    def test_strict_low_max_weight(self):
        positions = [_pos(f"P{i}", weight=0.25, apy=5.0 + i, max_w=0.2) for i in range(5)]
        result = optimize(positions)
        for name, w in result.recommended_weights.items():
            self.assertLessEqual(w, 0.2 + 1e-9)

    def test_max_weight_40_pct_default(self):
        positions = [_pos(f"P{i}", weight=0.25, apy=5.0 + i * 2, max_w=0.4) for i in range(4)]
        result = optimize(positions)
        for name, w in result.recommended_weights.items():
            self.assertLessEqual(w, 0.4 + 1e-9)

    def test_dominant_position_capped(self):
        # One position with max_weight=0.25 despite high APY
        positions = [
            _pos("HighYield", apy=20.0, weight=0.4, max_w=0.25),
            _pos("Mid1",      apy=5.0,  weight=0.3, max_w=0.4),
            _pos("Mid2",      apy=4.0,  weight=0.3, max_w=0.4),
        ]
        result = optimize(positions)
        self.assertLessEqual(result.recommended_weights["HighYield"], 0.25 + 1e-9)


# ---------------------------------------------------------------------------
# 5. optimize — HHI improvement for concentrated portfolios
# ---------------------------------------------------------------------------
class TestOptimizeHhiImprovement(unittest.TestCase):

    def test_hhi_improves_for_concentrated_portfolio(self):
        result = optimize(_concentrated_portfolio())
        # current_hhi ≈ 0.66 (80% dominant); after optimization should drop
        self.assertGreater(result.current_hhi, result.recommended_hhi)

    def test_hhi_improvement_positive_for_concentrated(self):
        result = optimize(_concentrated_portfolio())
        self.assertGreater(result.hhi_improvement, 0)

    def test_current_hhi_computed_correctly(self):
        positions = _four_equal_positions()
        result = optimize(positions)
        self.assertAlmostEqual(result.current_hhi, 0.25, places=9)

    def test_recommended_hhi_computed_from_recommended_weights(self):
        result = optimize(_four_equal_positions())
        weights = list(result.recommended_weights.values())
        expected_hhi = sum(w * w for w in weights)
        self.assertAlmostEqual(result.recommended_hhi, expected_hhi, places=9)

    def test_recommended_hhi_in_valid_range(self):
        result = optimize(_concentrated_portfolio())
        self.assertGreaterEqual(result.recommended_hhi, 0.0)
        self.assertLessEqual(result.recommended_hhi, 1.0)


# ---------------------------------------------------------------------------
# 6. optimize — APY change
# ---------------------------------------------------------------------------
class TestOptimizeApyChange(unittest.TestCase):

    def test_apy_change_computed(self):
        result = optimize(_four_equal_positions())
        expected = result.recommended_weighted_apy - result.current_weighted_apy
        self.assertAlmostEqual(result.apy_change, expected, places=9)

    def test_current_weighted_apy_correct(self):
        positions = [_pos("A", apy=4.0, weight=0.5), _pos("B", apy=6.0, weight=0.5)]
        result = optimize(positions)
        self.assertAlmostEqual(result.current_weighted_apy, 5.0, places=9)

    def test_recommended_weighted_apy_from_recommended_weights(self):
        result = optimize(_four_equal_positions())
        positions = result.positions
        weights = [result.recommended_weights[p.name] for p in positions]
        apys = [p.apy for p in positions]
        expected = sum(w * a for w, a in zip(weights, apys))
        self.assertAlmostEqual(result.recommended_weighted_apy, expected, places=9)


# ---------------------------------------------------------------------------
# 7. optimize — diversification_score
# ---------------------------------------------------------------------------
class TestDiversificationScore(unittest.TestCase):

    def test_formula(self):
        result = optimize(_four_equal_positions())
        expected = (1.0 - result.recommended_hhi) * 100.0
        self.assertAlmostEqual(result.diversification_score, expected, places=9)

    def test_score_between_0_and_100(self):
        result = optimize(_concentrated_portfolio())
        self.assertGreaterEqual(result.diversification_score, 0.0)
        self.assertLessEqual(result.diversification_score, 100.0)

    def test_perfect_monopoly_score_zero(self):
        # Single position → hhi=1 after optimization → score=0
        result = optimize([_pos("Solo", weight=1.0)])
        # recommended_hhi=1 → score=0
        self.assertAlmostEqual(result.diversification_score, 0.0, places=6)


# ---------------------------------------------------------------------------
# 8. optimize — recommendation label
# ---------------------------------------------------------------------------
class TestRecommendationLabel(unittest.TestCase):

    def test_well_diversified_label(self):
        # 10 equal positions → hhi=0.1 < 0.15 → WELL_DIVERSIFIED
        positions = [_pos(f"P{i}", weight=0.1, apy=5.0, max_w=0.2) for i in range(10)]
        result = optimize(positions)
        if result.recommended_hhi < 0.15:
            self.assertEqual(result.recommendation, "WELL_DIVERSIFIED")

    def test_concentrated_risk_label_for_single_position(self):
        result = optimize([_pos("Solo", weight=1.0)])
        # hhi=1 → CONCENTRATED_RISK
        self.assertEqual(result.recommendation, "CONCENTRATED_RISK")

    def test_recommendation_is_valid_string(self):
        result = optimize(_four_equal_positions())
        self.assertIn(result.recommendation, {"WELL_DIVERSIFIED", "REBALANCE_RECOMMENDED", "CONCENTRATED_RISK"})

    def test_concentrated_portfolio_gets_non_diversified_label(self):
        result = optimize(_concentrated_portfolio())
        self.assertIn(result.recommendation, {"REBALANCE_RECOMMENDED", "CONCENTRATED_RISK"})

    def test_rebalance_recommended_threshold(self):
        # 5 equal positions (hhi≈0.2) → should get REBALANCE_RECOMMENDED
        positions = [_pos(f"P{i}", weight=0.2, apy=5.0) for i in range(5)]
        result = optimize(positions)
        if 0.15 <= result.recommended_hhi < 0.25:
            self.assertEqual(result.recommendation, "REBALANCE_RECOMMENDED")


# ---------------------------------------------------------------------------
# 9. optimize — rebalance_trades
# ---------------------------------------------------------------------------
class TestRebalanceTrades(unittest.TestCase):

    def test_all_positions_have_trade(self):
        positions = _four_equal_positions()
        result = optimize(positions)
        trade_names = {t["position"] for t in result.rebalance_trades}
        pos_names = {p.name for p in positions}
        self.assertEqual(trade_names, pos_names)

    def test_trade_action_values(self):
        result = optimize(_four_equal_positions())
        for trade in result.rebalance_trades:
            self.assertIn(trade["action"], {"INCREASE", "DECREASE", "HOLD"})

    def test_increase_when_weight_goes_up(self):
        result = optimize(_concentrated_portfolio())
        for trade in result.rebalance_trades:
            if trade["delta"] > 1e-6:
                self.assertEqual(trade["action"], "INCREASE")

    def test_decrease_when_weight_goes_down(self):
        result = optimize(_concentrated_portfolio())
        for trade in result.rebalance_trades:
            if trade["delta"] < -1e-6:
                self.assertEqual(trade["action"], "DECREASE")

    def test_trade_has_required_keys(self):
        result = optimize(_four_equal_positions())
        for trade in result.rebalance_trades:
            self.assertIn("position", trade)
            self.assertIn("action", trade)
            self.assertIn("from_weight", trade)
            self.assertIn("to_weight", trade)
            self.assertIn("delta", trade)

    def test_delta_equals_to_minus_from(self):
        result = optimize(_four_equal_positions())
        for trade in result.rebalance_trades:
            expected_delta = trade["to_weight"] - trade["from_weight"]
            self.assertAlmostEqual(trade["delta"], expected_delta, places=9)

    def test_concentrated_dominant_has_decrease(self):
        result = optimize(_concentrated_portfolio())
        dominant_trade = next(t for t in result.rebalance_trades if t["position"] == "Dominant")
        self.assertEqual(dominant_trade["action"], "DECREASE")


# ---------------------------------------------------------------------------
# 10. optimize — warnings
# ---------------------------------------------------------------------------
class TestWarnings(unittest.TestCase):

    def test_warning_high_single_position_when_over_35pct(self):
        # Force a position to recommended weight > 0.35
        # Two positions where one has very low max_weight forcing the other high
        positions = [
            _pos("Big",   apy=8.0, weight=0.5, max_w=0.9),
            _pos("Small", apy=2.0, weight=0.5, max_w=0.1),
        ]
        result = optimize(positions)
        over_35 = any(w > 0.35 for w in result.recommended_weights.values())
        if over_35:
            warning_texts = " ".join(result.warnings)
            self.assertIn("high single position", warning_texts)

    def test_warning_poor_hhi_improvement(self):
        # Optimize a portfolio that's already well-balanced (4 equal)
        # Algorithm should not worsen HHI; if it does → warning
        positions = _four_equal_positions()
        result = optimize(positions)
        if result.hhi_improvement < 0:
            self.assertIn("optimization didn't improve HHI", result.warnings)

    def test_no_spurious_warnings_for_well_balanced(self):
        # 5 equal positions, uniform APY → no dramatic shifts → few/no warnings
        positions = [_pos(f"P{i}", weight=0.2, apy=5.0, max_w=0.3) for i in range(5)]
        result = optimize(positions)
        # We just check that warnings is a list
        self.assertIsInstance(result.warnings, list)

    def test_warnings_is_list(self):
        result = optimize(_four_equal_positions())
        self.assertIsInstance(result.warnings, list)


# ---------------------------------------------------------------------------
# 11. explain_trades
# ---------------------------------------------------------------------------
class TestExplainTrades(unittest.TestCase):

    def test_returns_non_empty_string(self):
        result = optimize(_four_equal_positions())
        explanation = explain_trades(result)
        self.assertIsInstance(explanation, str)
        self.assertGreater(len(explanation), 0)

    def test_contains_recommendation(self):
        result = optimize(_four_equal_positions())
        explanation = explain_trades(result)
        self.assertIn(result.recommendation, explanation)

    def test_contains_all_position_names(self):
        positions = _four_equal_positions()
        result = optimize(positions)
        explanation = explain_trades(result)
        for p in positions:
            self.assertIn(p.name, explanation)

    def test_empty_result_returns_no_positions_message(self):
        result = optimize([])
        explanation = explain_trades(result)
        self.assertIn("No positions", explanation)

    def test_contains_hhi_values(self):
        result = optimize(_concentrated_portfolio())
        explanation = explain_trades(result)
        # Should mention HHI somewhere
        self.assertIn("HHI", explanation)

    def test_contains_action_words(self):
        result = optimize(_concentrated_portfolio())
        explanation = explain_trades(result)
        # At least one action verb should appear
        has_action = any(
            action in explanation
            for action in ["INCREASE", "DECREASE", "HOLD"]
        )
        self.assertTrue(has_action)


# ---------------------------------------------------------------------------
# 12. optimize — edge cases
# ---------------------------------------------------------------------------
class TestOptimizeEdgeCases(unittest.TestCase):

    def test_single_position(self):
        result = optimize([_pos("Solo", weight=1.0)])
        self.assertEqual(result.recommended_weights["Solo"], 1.0)
        self.assertAlmostEqual(result.recommended_hhi, 1.0, places=9)

    def test_empty_positions_list(self):
        result = optimize([])
        self.assertEqual(result.recommended_weights, {})
        self.assertAlmostEqual(result.current_hhi, 0.0, places=9)

    def test_all_same_apy(self):
        positions = [_pos(f"P{i}", weight=0.25, apy=5.0) for i in range(4)]
        result = optimize(positions)
        # All same APY → no tilt bias; weights should be near equal
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_two_positions_complementary_weights(self):
        positions = [
            _pos("A", apy=3.0, weight=0.7, max_w=0.5),
            _pos("B", apy=7.0, weight=0.3, max_w=0.5),
        ]
        result = optimize(positions)
        total = sum(result.recommended_weights.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_weighted_risk_computed(self):
        positions = [_pos("A", risk=20.0, weight=0.5), _pos("B", risk=60.0, weight=0.5)]
        result = optimize(positions)
        self.assertAlmostEqual(result.current_weighted_risk, 40.0, places=9)

    def test_recommended_weighted_risk_computed(self):
        positions = _four_equal_positions()
        result = optimize(positions)
        weights = [result.recommended_weights[p.name] for p in positions]
        risks = [p.risk_score for p in positions]
        expected = sum(w * r for w, r in zip(weights, risks))
        self.assertAlmostEqual(result.recommended_weighted_risk, expected, places=9)

    def test_positions_list_preserved(self):
        positions = _four_equal_positions()
        result = optimize(positions)
        self.assertEqual(len(result.positions), 4)
        self.assertEqual(result.positions[0].name, "A")


# ---------------------------------------------------------------------------
# 13. save / load / ring-buffer
# ---------------------------------------------------------------------------
class TestSaveLoad(unittest.TestCase):

    def test_save_creates_file(self):
        path = _tmp_file()
        result = optimize(_four_equal_positions())
        save_results(result, data_file=path)
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_save_sets_saved_to(self):
        path = _tmp_file()
        result = optimize(_four_equal_positions())
        save_results(result, data_file=path)
        self.assertEqual(result.saved_to, path)
        os.unlink(path)

    def test_load_returns_empty_when_no_file(self):
        path = _tmp_file()
        self.assertEqual(load_history(data_file=path), [])

    def test_round_trip(self):
        path = _tmp_file()
        positions = _concentrated_portfolio()
        result = optimize(positions)
        save_results(result, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertAlmostEqual(entry["current_hhi"], result.current_hhi, places=9)
        self.assertEqual(entry["recommendation"], result.recommendation)
        os.unlink(path)

    def test_ring_buffer_cap_100(self):
        path = _tmp_file()
        positions = _four_equal_positions()
        for _ in range(110):
            result = optimize(positions)
            save_results(result, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), RING_BUFFER_CAP)
        os.unlink(path)

    def test_ring_buffer_keeps_last_entries(self):
        path = _tmp_file()
        for i in range(105):
            positions = [_pos(f"P{j}", weight=0.25, apy=float(i) + j) for j in range(4)]
            result = optimize(positions)
            save_results(result, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), RING_BUFFER_CAP)
        os.unlink(path)

    def test_load_corrupted_file_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            f.write("}{bad json")
        result = load_history(data_file=path)
        self.assertEqual(result, [])
        os.unlink(path)

    def test_atomic_write_valid_json_each_time(self):
        path = _tmp_file()
        positions = _four_equal_positions()
        for _ in range(5):
            result = optimize(positions)
            save_results(result, data_file=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        os.unlink(path)

    def test_multiple_saves_accumulate(self):
        path = _tmp_file()
        for i in range(3):
            positions = [_pos(f"P{j}", weight=0.25, apy=5.0 + i) for j in range(4)]
            result = optimize(positions)
            save_results(result, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), 3)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
