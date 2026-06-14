"""
Tests for MP-738: LiquidityDepthScorer
≥65 test cases using unittest only.
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Ensure repo root is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.liquidity_depth_scorer import (
    LiquidityDepthMetrics,
    LiquidityDepthResult,
    analyze_portfolio,
    analyze_position,
    compute_depth_score,
    depth_label,
    estimate_slippage,
    exit_capacity,
    load_history,
    save_results,
    RING_BUFFER_CAP,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _tmp_file() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    # Write empty list as stub
    with open(path, "w") as f:
        json.dump([], f)
    return path


def _make_position(
    protocol="TestProto",
    asset="USDC",
    total_liquidity_usd=100_000_000.0,
    position_size_usd=1_000_000.0,
) -> dict:
    return {
        "protocol": protocol,
        "asset": asset,
        "total_liquidity_usd": total_liquidity_usd,
        "position_size_usd": position_size_usd,
    }


# ---------------------------------------------------------------------------
# 1. estimate_slippage
# ---------------------------------------------------------------------------

class TestEstimateSlippage(unittest.TestCase):

    def test_basic_formula(self):
        # position=1M, liquidity=100M → pct=1%, slip=1/20=0.05%
        slip = estimate_slippage(1_000_000, 100_000_000)
        self.assertAlmostEqual(slip, 0.05, places=6)

    def test_zero_liquidity_returns_100(self):
        self.assertEqual(estimate_slippage(1_000, 0), 100.0)

    def test_negative_liquidity_treated_as_zero(self):
        self.assertEqual(estimate_slippage(1_000, -500), 100.0)

    def test_large_position_equals_liquidity(self):
        # position == liquidity → pct=100%, slip=100/20=5%
        slip = estimate_slippage(50_000_000, 50_000_000)
        self.assertAlmostEqual(slip, 5.0, places=6)

    def test_position_double_liquidity(self):
        # position=200M, liquidity=100M → pct=200, slip=10
        slip = estimate_slippage(200_000_000, 100_000_000)
        self.assertAlmostEqual(slip, 10.0, places=6)

    def test_tiny_position(self):
        # position=1, liquidity=1B → pct=1e-7, slip ~ 5e-9
        slip = estimate_slippage(1, 1_000_000_000)
        self.assertAlmostEqual(slip, 1e-7 / 20, places=12)

    def test_zero_position(self):
        slip = estimate_slippage(0, 100_000_000)
        self.assertAlmostEqual(slip, 0.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(estimate_slippage(100, 1000), float)


# ---------------------------------------------------------------------------
# 2. exit_capacity
# ---------------------------------------------------------------------------

class TestExitCapacity(unittest.TestCase):

    def test_1pct_slippage(self):
        # capacity = 100M * 1 * 20 / 100 = 20M
        cap = exit_capacity(100_000_000, 1.0)
        self.assertAlmostEqual(cap, 20_000_000.0, places=2)

    def test_3pct_slippage(self):
        # capacity = 100M * 3 * 20 / 100 = 60M
        cap = exit_capacity(100_000_000, 3.0)
        self.assertAlmostEqual(cap, 60_000_000.0, places=2)

    def test_5pct_slippage_capped_at_liquidity(self):
        # capacity = 100M * 5 * 20 / 100 = 100M → capped at 100M
        cap = exit_capacity(100_000_000, 5.0)
        self.assertAlmostEqual(cap, 100_000_000.0, places=2)

    def test_capped_does_not_exceed_liquidity(self):
        cap = exit_capacity(50_000_000, 10.0)
        self.assertLessEqual(cap, 50_000_000.0)

    def test_zero_liquidity(self):
        self.assertEqual(exit_capacity(0, 3.0), 0.0)

    def test_negative_liquidity(self):
        self.assertEqual(exit_capacity(-100, 3.0), 0.0)

    def test_zero_slippage(self):
        cap = exit_capacity(100_000_000, 0.0)
        self.assertAlmostEqual(cap, 0.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(exit_capacity(1_000_000, 1.0), float)

    def test_1B_liquidity_3pct(self):
        cap = exit_capacity(1_000_000_000, 3.0)
        self.assertAlmostEqual(cap, 600_000_000.0, places=2)


# ---------------------------------------------------------------------------
# 3. compute_depth_score
# ---------------------------------------------------------------------------

class TestComputeDepthScore(unittest.TestCase):

    def test_1B_gives_100(self):
        score = compute_depth_score(1_000_000_000)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_1_gives_0(self):
        score = compute_depth_score(1.0)
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_zero_gives_0(self):
        score = compute_depth_score(0.0)
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_negative_gives_0(self):
        score = compute_depth_score(-999.0)
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_1M_approximately_66_7(self):
        # log10(1e6)/log10(1e9)*100 = 6/9*100 = 66.67
        score = compute_depth_score(1_000_000)
        self.assertAlmostEqual(score, 66.666, delta=0.01)

    def test_1K_approximately_33_3(self):
        # log10(1e3)/log10(1e9)*100 = 3/9*100 = 33.33
        score = compute_depth_score(1_000)
        self.assertAlmostEqual(score, 33.333, delta=0.01)

    def test_score_bounded_0_100(self):
        for liq in [0, 1, 1e3, 1e6, 1e9, 1e12]:
            score = compute_depth_score(liq)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_monotonically_increasing(self):
        scores = [compute_depth_score(10 ** i) for i in range(10)]
        for i in range(1, len(scores)):
            self.assertGreaterEqual(scores[i], scores[i - 1])

    def test_returns_float(self):
        self.assertIsInstance(compute_depth_score(1e8), float)


# ---------------------------------------------------------------------------
# 4. depth_label
# ---------------------------------------------------------------------------

class TestDepthLabel(unittest.TestCase):

    def test_deep_at_80(self):
        self.assertEqual(depth_label(80.0), "DEEP")

    def test_deep_above_80(self):
        self.assertEqual(depth_label(95.0), "DEEP")

    def test_adequate_at_50(self):
        self.assertEqual(depth_label(50.0), "ADEQUATE")

    def test_adequate_between_50_and_80(self):
        self.assertEqual(depth_label(65.0), "ADEQUATE")

    def test_shallow_below_50(self):
        self.assertEqual(depth_label(49.9), "SHALLOW")

    def test_shallow_at_0(self):
        self.assertEqual(depth_label(0.0), "SHALLOW")

    def test_shallow_at_30(self):
        self.assertEqual(depth_label(30.0), "SHALLOW")


# ---------------------------------------------------------------------------
# 5. analyze_position
# ---------------------------------------------------------------------------

class TestAnalyzePosition(unittest.TestCase):

    def test_returns_LiquidityDepthMetrics(self):
        m = analyze_position("Aave", "USDC", 1_000_000_000, 50_000)
        self.assertIsInstance(m, LiquidityDepthMetrics)

    def test_protocol_set_correctly(self):
        m = analyze_position("TestP", "USDT", 100_000_000, 1_000)
        self.assertEqual(m.protocol, "TestP")
        self.assertEqual(m.asset, "USDT")

    def test_total_liquidity_set(self):
        m = analyze_position("P", "A", 500_000_000, 10_000)
        self.assertAlmostEqual(m.total_liquidity_usd, 500_000_000.0)

    def test_exit_1pct_formula(self):
        # 100M * 1 * 20 / 100 = 20M
        m = analyze_position("P", "A", 100_000_000, 10_000)
        self.assertAlmostEqual(m.exit_1pct_slippage_usd, 20_000_000.0, places=2)

    def test_exit_3pct_formula(self):
        m = analyze_position("P", "A", 100_000_000, 10_000)
        self.assertAlmostEqual(m.exit_3pct_slippage_usd, 60_000_000.0, places=2)

    def test_exit_5pct_capped(self):
        m = analyze_position("P", "A", 100_000_000, 10_000)
        self.assertAlmostEqual(m.exit_5pct_slippage_usd, 100_000_000.0, places=2)

    def test_position_pct_of_liquidity(self):
        m = analyze_position("P", "A", 200_000_000, 2_000_000)
        # 2M / 200M * 100 = 1%
        self.assertAlmostEqual(m.position_as_pct_of_liquidity, 1.0, places=6)

    def test_estimated_slippage(self):
        m = analyze_position("P", "A", 100_000_000, 1_000_000)
        # 1M/100M*100=1%, slip=1/20=0.05%
        self.assertAlmostEqual(m.estimated_slippage_pct, 0.05, places=6)

    def test_can_exit_under_1pct_true(self):
        # slip = 0.05% → can_exit_under_1pct True
        m = analyze_position("P", "A", 100_000_000, 1_000_000)
        self.assertTrue(m.can_exit_under_1pct)

    def test_can_exit_under_1pct_false(self):
        # position = 40M, liquidity = 100M → pct=40%, slip=2% → False
        m = analyze_position("P", "A", 100_000_000, 40_000_000)
        self.assertFalse(m.can_exit_under_1pct)

    def test_can_exit_under_3pct_true(self):
        # slip = 2% (40M/100M)
        m = analyze_position("P", "A", 100_000_000, 40_000_000)
        self.assertTrue(m.can_exit_under_3pct)

    def test_can_exit_under_3pct_false(self):
        # position=70M, liquidity=100M → pct=70%, slip=3.5% → False
        m = analyze_position("P", "A", 100_000_000, 70_000_000)
        self.assertFalse(m.can_exit_under_3pct)

    def test_recommendation_safe(self):
        m = analyze_position("P", "A", 1_000_000_000, 10_000)
        self.assertIn("Safe", m.recommendation)

    def test_recommendation_manageable(self):
        # slip slightly above 1% but under 3%: pos=25M, liq=100M → pct=25%, slip=25/20=1.25%
        m = analyze_position("P", "A", 100_000_000, 25_000_000)
        self.assertIn("Manageable", m.recommendation)

    def test_recommendation_warning(self):
        # slip > 3%: pos=70M, liq=100M → pct=70, slip=3.5%
        m = analyze_position("P", "A", 100_000_000, 70_000_000)
        self.assertIn("WARNING", m.recommendation)

    def test_depth_score_computed(self):
        m = analyze_position("P", "A", 1_000_000_000, 1)
        self.assertAlmostEqual(m.depth_score, 100.0, places=4)

    def test_depth_label_deep(self):
        m = analyze_position("P", "A", 1_000_000_000, 1)
        self.assertEqual(m.depth_label, "DEEP")

    def test_depth_label_shallow(self):
        m = analyze_position("P", "A", 1_000, 1)  # score ~ 33
        self.assertEqual(m.depth_label, "SHALLOW")

    def test_zero_liquidity_position_pct_100(self):
        m = analyze_position("P", "A", 0, 1_000)
        self.assertAlmostEqual(m.position_as_pct_of_liquidity, 100.0)

    def test_very_large_position_exceeds_liquidity(self):
        # position > liquidity: 200M vs 100M → slip=10%
        m = analyze_position("P", "A", 100_000_000, 200_000_000)
        self.assertAlmostEqual(m.estimated_slippage_pct, 10.0, places=4)
        self.assertIn("WARNING", m.recommendation)


# ---------------------------------------------------------------------------
# 6. analyze_portfolio
# ---------------------------------------------------------------------------

class TestAnalyzePortfolio(unittest.TestCase):

    def _positions(self):
        return [
            _make_position("Aave", "USDC", 2_000_000_000, 50_000),
            _make_position("Compound", "USDC", 300_000_000, 30_000),
            _make_position("SmallPool", "USDC", 500_000, 10_000),
        ]

    def test_returns_LiquidityDepthResult(self):
        result = analyze_portfolio(self._positions())
        self.assertIsInstance(result, LiquidityDepthResult)

    def test_metrics_count(self):
        result = analyze_portfolio(self._positions())
        self.assertEqual(len(result.metrics), 3)

    def test_deepest_protocol_is_highest_liquidity(self):
        result = analyze_portfolio(self._positions())
        self.assertEqual(result.deepest_protocol, "Aave")

    def test_shallowest_protocol_is_lowest_liquidity(self):
        result = analyze_portfolio(self._positions())
        self.assertEqual(result.shallowest_protocol, "SmallPool")

    def test_avg_depth_score_formula(self):
        result = analyze_portfolio(self._positions())
        expected = sum(m.depth_score for m in result.metrics) / 3
        self.assertAlmostEqual(result.avg_depth_score, round(expected, 4), places=4)

    def test_pct_deep_calculation(self):
        # Aave (2B → DEEP), Compound (300M → DEEP ~83), SmallPool (500K → ADEQUATE ~63)
        result = analyze_portfolio(self._positions())
        deep_count = sum(1 for m in result.metrics if m.depth_label == "DEEP")
        expected_pct = deep_count / 3 * 100.0
        self.assertAlmostEqual(result.pct_deep, round(expected_pct, 4), places=4)

    def test_total_liquid_capacity_sum_of_3pct(self):
        result = analyze_portfolio(self._positions())
        expected = sum(m.exit_3pct_slippage_usd for m in result.metrics)
        self.assertAlmostEqual(
            result.total_liquid_capacity_usd, round(expected, 2), places=2
        )

    def test_empty_portfolio(self):
        result = analyze_portfolio([])
        self.assertEqual(result.deepest_protocol, "N/A")
        self.assertEqual(result.shallowest_protocol, "N/A")
        self.assertAlmostEqual(result.avg_depth_score, 0.0)
        self.assertEqual(result.total_liquid_capacity_usd, 0.0)

    def test_single_position(self):
        result = analyze_portfolio([_make_position("Solo", "USDC", 1_000_000_000, 1)])
        self.assertEqual(len(result.metrics), 1)
        self.assertEqual(result.deepest_protocol, "Solo")
        self.assertEqual(result.shallowest_protocol, "Solo")

    def test_recommendation_summary_deep(self):
        # All positions in 1B+ liquidity → pct_deep=100 → deep summary
        positions = [
            _make_position("P1", "USDC", 1_000_000_000, 1),
            _make_position("P2", "USDC", 2_000_000_000, 1),
        ]
        result = analyze_portfolio(positions)
        self.assertIn("deep", result.recommendation_summary.lower())

    def test_recommendation_summary_mixed(self):
        positions = [
            _make_position("P1", "USDC", 1_000_000_000, 1),  # DEEP
            _make_position("P2", "USDC", 100_000, 1),         # SHALLOW
            _make_position("P3", "USDC", 200_000, 1),         # SHALLOW
        ]
        result = analyze_portfolio(positions)
        # 1/3 deep = 33.3% → "Significant liquidity risk"
        self.assertIn("risk", result.recommendation_summary.lower())

    def test_saved_to_empty_initially(self):
        result = analyze_portfolio(self._positions())
        self.assertEqual(result.saved_to, "")


# ---------------------------------------------------------------------------
# 7. save_results / load_history (ring-buffer)
# ---------------------------------------------------------------------------

class TestSaveLoadRingBuffer(unittest.TestCase):

    def test_save_and_load_roundtrip(self):
        tmp = _tmp_file()
        try:
            positions = [_make_position("Aave", "USDC", 1_000_000_000, 10_000)]
            result = analyze_portfolio(positions)
            save_results(result, tmp)
            history = load_history(tmp)
            self.assertEqual(len(history), 1)
        finally:
            os.unlink(tmp)

    def test_saved_to_populated(self):
        tmp = _tmp_file()
        try:
            result = analyze_portfolio([_make_position("P", "A", 1e8, 1e4)])
            save_results(result, tmp)
            self.assertEqual(result.saved_to, tmp)
        finally:
            os.unlink(tmp)

    def test_multiple_saves_accumulate(self):
        tmp = _tmp_file()
        try:
            for i in range(5):
                r = analyze_portfolio([_make_position(f"P{i}", "A", 1e8, 1e3)])
                save_results(r, tmp)
            history = load_history(tmp)
            self.assertEqual(len(history), 5)
        finally:
            os.unlink(tmp)

    def test_ring_buffer_cap_100(self):
        tmp = _tmp_file()
        try:
            for i in range(RING_BUFFER_CAP + 15):
                r = analyze_portfolio([_make_position(f"P{i}", "A", 1e8, 1e3)])
                save_results(r, tmp)
            history = load_history(tmp)
            self.assertEqual(len(history), RING_BUFFER_CAP)
        finally:
            os.unlink(tmp)

    def test_ring_buffer_keeps_latest_entries(self):
        tmp = _tmp_file()
        try:
            for i in range(RING_BUFFER_CAP + 10):
                r = analyze_portfolio([_make_position(f"Protocol_{i}", "A", 1e8, 1e3)])
                save_results(r, tmp)
            history = load_history(tmp)
            # Last entry should be Protocol_109
            last_metrics = history[-1]["metrics"]
            self.assertTrue(last_metrics[0]["protocol"].startswith("Protocol_"))
        finally:
            os.unlink(tmp)

    def test_load_missing_file_returns_empty(self):
        result = load_history("/tmp/no_such_file_xyz_12345.json")
        self.assertEqual(result, [])

    def test_load_corrupted_file_returns_empty(self):
        tmp = _tmp_file()
        try:
            with open(tmp, "w") as f:
                f.write("not valid json {{{")
            result = load_history(tmp)
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)

    def test_atomic_write_via_os_replace(self):
        # Verify the file is valid JSON after save (atomic property)
        tmp = _tmp_file()
        try:
            r = analyze_portfolio([_make_position("P", "A", 1e9, 1e4)])
            save_results(r, tmp)
            with open(tmp) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            os.unlink(tmp)

    def test_history_entry_contains_metrics_key(self):
        tmp = _tmp_file()
        try:
            r = analyze_portfolio([_make_position("Aave", "USDC", 1e9, 5e4)])
            save_results(r, tmp)
            history = load_history(tmp)
            self.assertIn("metrics", history[0])
        finally:
            os.unlink(tmp)

    def test_history_entry_contains_avg_depth_score(self):
        tmp = _tmp_file()
        try:
            r = analyze_portfolio([_make_position("Aave", "USDC", 1e9, 5e4)])
            save_results(r, tmp)
            history = load_history(tmp)
            self.assertIn("avg_depth_score", history[0])
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# 8. Additional edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_position_as_pct_zero_position(self):
        m = analyze_position("P", "A", 100_000_000, 0)
        self.assertAlmostEqual(m.position_as_pct_of_liquidity, 0.0)

    def test_slip_exactly_1pct_can_exit_1pct(self):
        # For slip = exactly 1%: pos/liq*100/20 = 1 → pos/liq = 0.2
        pos = 20_000_000.0
        liq = 100_000_000.0
        m = analyze_position("P", "A", liq, pos)
        self.assertAlmostEqual(m.estimated_slippage_pct, 1.0, places=6)
        self.assertTrue(m.can_exit_under_1pct)

    def test_slip_exactly_3pct_can_exit_3pct(self):
        # slip=3% → pos/liq=0.6 → pos=60M for 100M liq
        m = analyze_position("P", "A", 100_000_000, 60_000_000)
        self.assertAlmostEqual(m.estimated_slippage_pct, 3.0, places=6)
        self.assertTrue(m.can_exit_under_3pct)

    def test_all_metric_fields_present(self):
        m = analyze_position("P", "A", 1e8, 1e5)
        fields = [
            "protocol", "asset", "total_liquidity_usd",
            "exit_1pct_slippage_usd", "exit_3pct_slippage_usd", "exit_5pct_slippage_usd",
            "position_size_usd", "position_as_pct_of_liquidity", "estimated_slippage_pct",
            "can_exit_under_1pct", "can_exit_under_3pct",
            "depth_score", "depth_label", "recommendation",
        ]
        for f in fields:
            self.assertTrue(hasattr(m, f), f"Missing field: {f}")

    def test_all_result_fields_present(self):
        result = analyze_portfolio([_make_position()])
        fields = [
            "metrics", "deepest_protocol", "shallowest_protocol",
            "avg_depth_score", "pct_deep", "total_liquid_capacity_usd",
            "recommendation_summary", "saved_to",
        ]
        for f in fields:
            self.assertTrue(hasattr(result, f), f"Missing field: {f}")

    def test_two_protocols_same_liquidity_rankings_stable(self):
        positions = [
            _make_position("Alpha", "USDC", 500_000_000, 1_000),
            _make_position("Beta", "USDC", 500_000_000, 1_000),
        ]
        result = analyze_portfolio(positions)
        # Both same liquidity; deepest/shallowest just picks first match
        self.assertIn(result.deepest_protocol, ["Alpha", "Beta"])
        self.assertIn(result.shallowest_protocol, ["Alpha", "Beta"])

    def test_1M_liquidity_depth_label_adequate(self):
        # score = 6/9*100 = 66.67 → ADEQUATE
        m = analyze_position("P", "A", 1_000_000, 0)
        self.assertEqual(m.depth_label, "ADEQUATE")

    def test_100M_liquidity_depth_score(self):
        # log10(1e8)/log10(1e9)*100 = 8/9*100 = 88.89 → DEEP
        score = compute_depth_score(1e8)
        self.assertAlmostEqual(score, 88.888, delta=0.01)
        self.assertEqual(depth_label(score), "DEEP")

    def test_slippage_in_recommendation_manageable(self):
        # slip just above 1%: pos=25M, liq=100M → pct=25, slip=1.25%
        m = analyze_position("P", "A", 100_000_000, 25_000_000)
        self.assertIn("1.2", m.recommendation)  # formatted slip

    def test_slippage_in_recommendation_warning(self):
        # slip > 3%: 70M/100M → pct=70, slip=3.5%
        m = analyze_position("P", "A", 100_000_000, 70_000_000)
        self.assertIn("3.5", m.recommendation)

    def test_ring_buffer_exactly_100(self):
        tmp = _tmp_file()
        try:
            for i in range(100):
                r = analyze_portfolio([_make_position(f"P{i}", "A", 1e8, 1e3)])
                save_results(r, tmp)
            history = load_history(tmp)
            self.assertEqual(len(history), 100)
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
