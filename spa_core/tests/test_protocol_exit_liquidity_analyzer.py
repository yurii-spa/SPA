"""
Tests for MP-872 ProtocolExitLiquidityAnalyzer
≥65 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_exit_liquidity_analyzer import (
    analyze,
    _compute_estimated_exit_days,
    _market_depth_coverage,
    _exit_liquidity_score,
    _exit_label,
    _bottleneck,
    _recommendation,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol: str = "AaveV3",
    position_usd: float = 50_000.0,
    withdrawal_queue_usd: float = 0.0,
    daily_withdrawal_limit_usd: float = 0.0,
    exit_fee_pct: float = 0.0,
    lock_up_days_remaining: int = 0,
    market_depth_at_1pct_usd: float = 100_000.0,
    token_type: str = "LIQUID",
) -> dict:
    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "withdrawal_queue_usd": withdrawal_queue_usd,
        "daily_withdrawal_limit_usd": daily_withdrawal_limit_usd,
        "exit_fee_pct": exit_fee_pct,
        "lock_up_days_remaining": lock_up_days_remaining,
        "market_depth_at_1pct_usd": market_depth_at_1pct_usd,
        "token_type": token_type,
    }


_INSTANT = _pos("Aave", 50_000, 0, 0, 0.0, 0, 200_000)
_LOCKED_90 = _pos("Maple", 30_000, 0, 0, 0.0, 90, 10_000)
_QUEUE_SLOW = _pos("Queue", 30_000, 50_000, 10_000, 0.5, 0, 5_000)


# ===========================================================================
# 1. _compute_estimated_exit_days
# ===========================================================================

class TestComputeEstimatedExitDays(unittest.TestCase):
    def test_immediate_no_constraints(self):
        days = _compute_estimated_exit_days(0, 0.0, 0.0, 50_000.0)
        self.assertEqual(days, 0.0)

    def test_lock_up_overrides_all(self):
        days = _compute_estimated_exit_days(30, 10_000.0, 5_000.0, 50_000.0)
        self.assertEqual(days, 30.0)

    def test_lock_up_zero_uses_queue_logic(self):
        # lock_up=0, daily=10k, position=30k, queue=50k
        days = _compute_estimated_exit_days(0, 10_000.0, 50_000.0, 30_000.0)
        # queue_days = 50k/10k=5, position_days=30k/10k=3 → 8
        self.assertAlmostEqual(days, 8.0)

    def test_position_within_daily_limit_no_queue(self):
        # position <= daily_limit → no limit constraint
        days = _compute_estimated_exit_days(0, 100_000.0, 0.0, 50_000.0)
        self.assertEqual(days, 0.0)

    def test_queue_no_daily_limit(self):
        # withdrawal_queue > 0 but no daily limit → 1 day estimate
        days = _compute_estimated_exit_days(0, 0.0, 20_000.0, 50_000.0)
        self.assertEqual(days, 1.0)

    def test_queue_and_daily_limit(self):
        # daily_limit=5k, position=10k, queue=15k
        days = _compute_estimated_exit_days(0, 5_000.0, 15_000.0, 10_000.0)
        # queue_days=15k/5k=3, position_days=10k/5k=2 → 5
        self.assertAlmostEqual(days, 5.0)

    def test_lock_up_one_day(self):
        days = _compute_estimated_exit_days(1, 0.0, 0.0, 50_000.0)
        self.assertEqual(days, 1.0)

    def test_position_exactly_equal_to_daily_limit(self):
        # position == daily_limit → NOT > limit → immediate
        days = _compute_estimated_exit_days(0, 50_000.0, 0.0, 50_000.0)
        self.assertEqual(days, 0.0)

    def test_no_queue_unlimited_limit(self):
        days = _compute_estimated_exit_days(0, 0.0, 0.0, 100_000.0)
        self.assertEqual(days, 0.0)

    def test_large_lock_up(self):
        days = _compute_estimated_exit_days(365, 0.0, 0.0, 50_000.0)
        self.assertEqual(days, 365.0)


# ===========================================================================
# 2. _market_depth_coverage
# ===========================================================================

class TestMarketDepthCoverage(unittest.TestCase):
    def test_zero_position(self):
        cov = _market_depth_coverage(100_000.0, 0.0)
        self.assertEqual(cov, 0.0)

    def test_full_coverage(self):
        # depth == position → 100%
        cov = _market_depth_coverage(50_000.0, 50_000.0)
        self.assertAlmostEqual(cov, 100.0)

    def test_double_coverage(self):
        cov = _market_depth_coverage(100_000.0, 50_000.0)
        self.assertAlmostEqual(cov, 200.0)

    def test_partial_coverage(self):
        cov = _market_depth_coverage(25_000.0, 50_000.0)
        self.assertAlmostEqual(cov, 50.0)

    def test_zero_depth(self):
        cov = _market_depth_coverage(0.0, 50_000.0)
        self.assertAlmostEqual(cov, 0.0)


# ===========================================================================
# 3. _exit_liquidity_score
# ===========================================================================

class TestExitLiquidityScore(unittest.TestCase):
    def test_immediate_full_depth(self):
        score = _exit_liquidity_score(0, 0.0, 7, 200.0)
        self.assertEqual(score, 100)  # 80 + 20

    def test_immediate_no_depth(self):
        score = _exit_liquidity_score(0, 0.0, 7, 0.0)
        self.assertEqual(score, 80)

    def test_fast_exit(self):
        # estimated_exit_days=0.5 (>0 but ≤1) → base=70
        score = _exit_liquidity_score(0, 0.5, 7, 100.0)
        self.assertEqual(score, 85)  # 70+15

    def test_moderate_exit(self):
        # estimated > 1 but ≤ target → base=55
        score = _exit_liquidity_score(0, 3.0, 7, 50.0)
        self.assertEqual(score, 65)  # 55+10

    def test_slow_exit(self):
        # estimated > target_exit_days → base=30
        score = _exit_liquidity_score(0, 10.0, 7, 20.0)
        self.assertEqual(score, 35)  # 30+5

    def test_locked_30d(self):
        # lock_up ≤30 → base=20
        score = _exit_liquidity_score(15, 15.0, 7, 0.0)
        self.assertEqual(score, 20)

    def test_locked_90d(self):
        # lock_up >30 → base=12 (>30 branch)
        score = _exit_liquidity_score(60, 60.0, 7, 0.0)
        self.assertEqual(score, 12)

    def test_locked_180d(self):
        # lock_up >90 → base=8
        score = _exit_liquidity_score(100, 100.0, 7, 0.0)
        self.assertEqual(score, 8)

    def test_locked_over_180d(self):
        # lock_up >180 → base=5
        score = _exit_liquidity_score(181, 181.0, 7, 0.0)
        self.assertEqual(score, 5)

    def test_capped_at_100(self):
        score = _exit_liquidity_score(0, 0.0, 7, 500.0)
        self.assertLessEqual(score, 100)

    def test_depth_bonus_100pct(self):
        # immediate + depth=100% → +15
        score = _exit_liquidity_score(0, 0.0, 7, 100.0)
        self.assertEqual(score, 95)

    def test_depth_bonus_20pct(self):
        # immediate + depth=20% → +5
        score = _exit_liquidity_score(0, 0.0, 7, 20.0)
        self.assertEqual(score, 85)

    def test_depth_below_20_no_bonus(self):
        score = _exit_liquidity_score(0, 0.0, 7, 10.0)
        self.assertEqual(score, 80)


# ===========================================================================
# 4. _exit_label
# ===========================================================================

class TestExitLabel(unittest.TestCase):
    def test_locked(self):
        self.assertEqual(_exit_label(1, 30.0, 7), "LOCKED")

    def test_slow(self):
        self.assertEqual(_exit_label(0, 10.0, 7), "SLOW")

    def test_moderate(self):
        self.assertEqual(_exit_label(0, 2.0, 7), "MODERATE")

    def test_fast(self):
        self.assertEqual(_exit_label(0, 0.5, 7), "FAST")

    def test_instant(self):
        self.assertEqual(_exit_label(0, 0.0, 7), "INSTANT")

    def test_boundary_exactly_target(self):
        # estimated_exit_days == target → NOT > target → MODERATE if >1, else FAST/INSTANT
        # estimated=7.0, target=7 → NOT > 7 → check >1 → MODERATE
        self.assertEqual(_exit_label(0, 7.0, 7), "MODERATE")

    def test_boundary_exactly_one(self):
        # estimated=1.0 → NOT >1 → check >0 → FAST
        self.assertEqual(_exit_label(0, 1.0, 7), "FAST")

    def test_lock_up_zero_instant(self):
        self.assertEqual(_exit_label(0, 0.0, 7), "INSTANT")


# ===========================================================================
# 5. _bottleneck
# ===========================================================================

class TestBottleneck(unittest.TestCase):
    def test_lock_up(self):
        self.assertEqual(_bottleneck(5, 0.0, 50_000.0, 0.0, 100.0), "LOCK_UP")

    def test_daily_limit(self):
        self.assertEqual(_bottleneck(0, 10_000.0, 50_000.0, 0.0, 100.0), "DAILY_LIMIT")

    def test_queue(self):
        self.assertEqual(_bottleneck(0, 0.0, 5_000.0, 20_000.0, 100.0), "QUEUE")

    def test_market_depth(self):
        self.assertEqual(_bottleneck(0, 0.0, 5_000.0, 0.0, 10.0), "MARKET_DEPTH")

    def test_none(self):
        self.assertIsNone(_bottleneck(0, 0.0, 5_000.0, 0.0, 100.0))

    def test_lock_up_beats_daily_limit(self):
        # lock_up > 0 → LOCK_UP even if daily limit also present
        self.assertEqual(_bottleneck(5, 10_000.0, 50_000.0, 0.0, 0.0), "LOCK_UP")

    def test_daily_limit_beats_queue(self):
        # daily_limit > 0 AND position > limit → DAILY_LIMIT beats QUEUE
        self.assertEqual(_bottleneck(0, 10_000.0, 50_000.0, 20_000.0, 100.0), "DAILY_LIMIT")


# ===========================================================================
# 6. _recommendation
# ===========================================================================

class TestRecommendation(unittest.TestCase):
    def test_locked_message(self):
        rec = _recommendation("LOCKED", 30, 30.0, 7, 0.0, 100.0)
        self.assertIn("30d", rec)
        self.assertIn("lock", rec.lower())

    def test_slow_message(self):
        rec = _recommendation("SLOW", 0, 14.0, 7, 0.0, 100.0)
        self.assertIn("14d", rec)
        self.assertIn("target", rec.lower())

    def test_moderate_message(self):
        rec = _recommendation("MODERATE", 0, 3.0, 7, 5000.0, 100.0)
        self.assertIn("7d", rec)
        self.assertIn("5000", rec)

    def test_fast_message(self):
        rec = _recommendation("FAST", 0, 0.5, 7, 0.0, 100.0)
        self.assertIn("quickly", rec.lower())

    def test_instant_message(self):
        rec = _recommendation("INSTANT", 0, 0.0, 7, 0.0, 150.0)
        self.assertIn("150%", rec)
        self.assertIn("Immediate", rec)

    def test_instant_zero_depth(self):
        rec = _recommendation("INSTANT", 0, 0.0, 7, 0.0, 0.0)
        self.assertIn("0%", rec)


# ===========================================================================
# 7. analyze() — empty input
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.r = analyze([])

    def test_positions_empty(self):
        self.assertEqual(self.r["positions"], [])

    def test_instantly_exitable_zero(self):
        self.assertEqual(self.r["instantly_exitable_usd"], 0.0)

    def test_total_position_zero(self):
        self.assertEqual(self.r["total_position_usd"], 0.0)

    def test_liquidity_ratio_zero(self):
        self.assertEqual(self.r["liquidity_ratio_pct"], 0.0)

    def test_most_locked_none(self):
        self.assertIsNone(self.r["most_locked"])

    def test_avg_score_zero(self):
        self.assertEqual(self.r["average_exit_liquidity_score"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.r)
        self.assertIsInstance(self.r["timestamp"], float)


# ===========================================================================
# 8. analyze() — single instant position
# ===========================================================================

class TestAnalyzeSingleInstant(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_INSTANT])
        self.pos = self.r["positions"][0]

    def test_exit_fee_usd(self):
        self.assertAlmostEqual(self.pos["exit_fee_usd"], 0.0)

    def test_net_exit_value(self):
        self.assertAlmostEqual(self.pos["net_exit_value_usd"], 50_000.0)

    def test_estimated_exit_days(self):
        self.assertEqual(self.pos["estimated_exit_days"], 0.0)

    def test_can_exit_in_target(self):
        self.assertTrue(self.pos["can_exit_in_target"])

    def test_exit_label_instant(self):
        self.assertEqual(self.pos["exit_label"], "INSTANT")

    def test_bottleneck_none(self):
        self.assertIsNone(self.pos["bottleneck"])

    def test_instantly_exitable(self):
        self.assertAlmostEqual(self.r["instantly_exitable_usd"], 50_000.0)

    def test_liquidity_ratio_100(self):
        self.assertAlmostEqual(self.r["liquidity_ratio_pct"], 100.0)

    def test_most_locked_none(self):
        self.assertIsNone(self.r["most_locked"])


# ===========================================================================
# 9. analyze() — single locked position
# ===========================================================================

class TestAnalyzeSingleLocked(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_LOCKED_90])
        self.pos = self.r["positions"][0]

    def test_exit_label_locked(self):
        self.assertEqual(self.pos["exit_label"], "LOCKED")

    def test_estimated_exit_days(self):
        self.assertAlmostEqual(self.pos["estimated_exit_days"], 90.0)

    def test_can_exit_in_target_false(self):
        self.assertFalse(self.pos["can_exit_in_target"])

    def test_bottleneck_lock_up(self):
        self.assertEqual(self.pos["bottleneck"], "LOCK_UP")

    def test_instantly_exitable_zero(self):
        self.assertAlmostEqual(self.r["instantly_exitable_usd"], 0.0)

    def test_most_locked(self):
        self.assertEqual(self.r["most_locked"], "Maple")

    def test_liquidity_ratio_zero(self):
        self.assertAlmostEqual(self.r["liquidity_ratio_pct"], 0.0)


# ===========================================================================
# 10. analyze() — exit fee calculations
# ===========================================================================

class TestExitFees(unittest.TestCase):
    def test_fee_deducted(self):
        pos = _pos(position_usd=100_000.0, exit_fee_pct=0.5)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertAlmostEqual(p["exit_fee_usd"], 500.0)
        self.assertAlmostEqual(p["net_exit_value_usd"], 99_500.0)

    def test_zero_fee(self):
        pos = _pos(position_usd=50_000.0, exit_fee_pct=0.0)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertAlmostEqual(p["exit_fee_usd"], 0.0)
        self.assertAlmostEqual(p["net_exit_value_usd"], 50_000.0)

    def test_high_fee(self):
        pos = _pos(position_usd=10_000.0, exit_fee_pct=2.0)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertAlmostEqual(p["exit_fee_usd"], 200.0)
        self.assertAlmostEqual(p["net_exit_value_usd"], 9_800.0)

    def test_fee_doesnt_affect_exit_timing(self):
        pos = _pos(position_usd=50_000.0, exit_fee_pct=5.0)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertEqual(p["estimated_exit_days"], 0.0)
        self.assertEqual(p["exit_label"], "INSTANT")


# ===========================================================================
# 11. analyze() — queue and daily limit
# ===========================================================================

class TestQueueAndDailyLimit(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_QUEUE_SLOW])
        self.pos = self.r["positions"][0]

    def test_exit_label_slow(self):
        # queue=50k, daily=10k → queue_days=5, pos_days=3 → 8 days > target(7)
        self.assertEqual(self.pos["exit_label"], "SLOW")

    def test_estimated_exit_days(self):
        # 50_000/10_000 + 30_000/10_000 = 5+3=8
        self.assertAlmostEqual(self.pos["estimated_exit_days"], 8.0)

    def test_can_exit_in_target_false(self):
        self.assertFalse(self.pos["can_exit_in_target"])

    def test_bottleneck_daily_limit(self):
        self.assertEqual(self.pos["bottleneck"], "DAILY_LIMIT")

    def test_queue_exit_1day(self):
        pos = _pos("X", 50_000, withdrawal_queue_usd=5_000, daily_withdrawal_limit_usd=0)
        r = analyze([pos])
        p = r["positions"][0]
        # queue > 0, no daily limit → 1 day
        self.assertAlmostEqual(p["estimated_exit_days"], 1.0)
        self.assertEqual(p["exit_label"], "FAST")


# ===========================================================================
# 12. analyze() — multi-position portfolio
# ===========================================================================

class TestMultiPosition(unittest.TestCase):
    def setUp(self):
        self.positions = [_INSTANT, _LOCKED_90, _QUEUE_SLOW]
        self.r = analyze(self.positions)

    def test_three_positions_returned(self):
        self.assertEqual(len(self.r["positions"]), 3)

    def test_instantly_exitable_only_instant(self):
        # only _INSTANT is "INSTANT" with position_usd=50_000
        self.assertAlmostEqual(self.r["instantly_exitable_usd"], 50_000.0)

    def test_total_position_usd(self):
        # 50k + 30k + 30k = 110k
        self.assertAlmostEqual(self.r["total_position_usd"], 110_000.0)

    def test_liquidity_ratio(self):
        # 50k/110k
        expected = 50_000 / 110_000 * 100
        self.assertAlmostEqual(self.r["liquidity_ratio_pct"], expected, places=3)

    def test_most_locked_is_locked_90(self):
        # Maple locked 90 days
        self.assertEqual(self.r["most_locked"], "Maple")

    def test_avg_score_is_float(self):
        self.assertIsInstance(self.r["average_exit_liquidity_score"], float)

    def test_avg_score_reasonable(self):
        score = self.r["average_exit_liquidity_score"]
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)


# ===========================================================================
# 13. analyze() — market depth coverage
# ===========================================================================

class TestMarketDepthInAnalyze(unittest.TestCase):
    def test_depth_coverage_computed(self):
        pos = _pos(position_usd=50_000, market_depth_at_1pct_usd=100_000)
        r = analyze([pos])
        self.assertAlmostEqual(r["positions"][0]["market_depth_coverage_pct"], 200.0)

    def test_zero_position_depth(self):
        pos = _pos(position_usd=0.0, market_depth_at_1pct_usd=100_000)
        r = analyze([pos])
        self.assertAlmostEqual(r["positions"][0]["market_depth_coverage_pct"], 0.0)

    def test_low_depth_is_bottleneck(self):
        pos = _pos(position_usd=100_000, market_depth_at_1pct_usd=10_000)
        r = analyze([pos])
        p = r["positions"][0]
        # 10k/100k=10% < 50% → MARKET_DEPTH
        self.assertEqual(p["bottleneck"], "MARKET_DEPTH")

    def test_sufficient_depth_no_bottleneck(self):
        pos = _pos(position_usd=50_000, market_depth_at_1pct_usd=50_000)
        r = analyze([pos])
        p = r["positions"][0]
        # 50k/50k = 100% ≥ 50% → no market depth bottleneck
        self.assertIsNone(p["bottleneck"])


# ===========================================================================
# 14. analyze() — config override
# ===========================================================================

class TestConfigOverride(unittest.TestCase):
    def test_custom_target_exit_days(self):
        # Position exits in 5 days — is it within target?
        pos = _pos("X", 50_000, withdrawal_queue_usd=50_000,
                   daily_withdrawal_limit_usd=10_000)
        # queue_days=5, position_days=5 → 10 days
        r3 = analyze([pos], config={"target_exit_days": 3})
        r15 = analyze([pos], config={"target_exit_days": 15})
        self.assertFalse(r3["positions"][0]["can_exit_in_target"])
        self.assertTrue(r15["positions"][0]["can_exit_in_target"])

    def test_default_target_is_7(self):
        pos = _pos("X", 50_000, withdrawal_queue_usd=50_000,
                   daily_withdrawal_limit_usd=10_000)
        r = analyze([pos])
        # 10 days > 7 → SLOW
        self.assertEqual(r["positions"][0]["exit_label"], "SLOW")

    def test_none_config_uses_default(self):
        pos = _pos()
        r = analyze([pos], config=None)
        self.assertEqual(r["positions"][0]["exit_label"], "INSTANT")


# ===========================================================================
# 15. Return structure
# ===========================================================================

class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_INSTANT])

    def test_top_level_keys(self):
        expected = {
            "positions",
            "instantly_exitable_usd",
            "total_position_usd",
            "liquidity_ratio_pct",
            "most_locked",
            "average_exit_liquidity_score",
            "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_position_keys(self):
        expected = {
            "protocol",
            "position_usd",
            "exit_fee_usd",
            "net_exit_value_usd",
            "estimated_exit_days",
            "can_exit_in_target",
            "exit_liquidity_score",
            "exit_label",
            "market_depth_coverage_pct",
            "bottleneck",
            "recommendation",
        }
        self.assertEqual(set(self.r["positions"][0].keys()), expected)

    def test_exit_label_valid(self):
        valid = {"INSTANT", "FAST", "MODERATE", "SLOW", "LOCKED"}
        self.assertIn(self.r["positions"][0]["exit_label"], valid)

    def test_score_int(self):
        score = self.r["positions"][0]["exit_liquidity_score"]
        self.assertIsInstance(score, int)

    def test_can_exit_bool(self):
        self.assertIsInstance(self.r["positions"][0]["can_exit_in_target"], bool)

    def test_timestamp_float(self):
        self.assertIsInstance(self.r["timestamp"], float)


# ===========================================================================
# 16. Atomic log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def _make_log_path(self, tmp_dir: str) -> str:
        return os.path.join(tmp_dir, "test_exit_log.json")

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"a": 1})
            _atomic_log(path, {"b": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(110):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_oldest_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["i"], 5)

    def test_corrupted_file_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            with open(path, "w") as f:
                f.write("INVALID JSON <<<")
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


# ===========================================================================
# 17. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_zero_position_usd(self):
        pos = _pos(position_usd=0.0, exit_fee_pct=1.0)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertAlmostEqual(p["exit_fee_usd"], 0.0)
        self.assertAlmostEqual(p["net_exit_value_usd"], 0.0)
        self.assertEqual(p["exit_label"], "INSTANT")

    def test_missing_fields_defaults(self):
        """Position with missing optional fields should not crash."""
        r = analyze([{"protocol": "X", "position_usd": 10_000}])
        self.assertEqual(len(r["positions"]), 1)

    def test_multiple_instant_positions(self):
        positions = [
            _pos("A", 30_000),
            _pos("B", 70_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["instantly_exitable_usd"], 100_000.0)
        self.assertAlmostEqual(r["liquidity_ratio_pct"], 100.0)

    def test_all_locked_no_instantly_exitable(self):
        positions = [
            _pos("A", 50_000, lock_up_days_remaining=30),
            _pos("B", 50_000, lock_up_days_remaining=60),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["instantly_exitable_usd"], 0.0)
        self.assertAlmostEqual(r["liquidity_ratio_pct"], 0.0)

    def test_most_locked_picks_highest_days(self):
        positions = [
            _pos("Short", 10_000, lock_up_days_remaining=10),
            _pos("Long", 10_000, lock_up_days_remaining=180),
        ]
        r = analyze(positions)
        self.assertEqual(r["most_locked"], "Long")

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze([_pos()])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_single_queue_no_limit_is_fast(self):
        """Queue present but no daily limit → 1 day → FAST (≤target=7)."""
        pos = _pos("X", 50_000, withdrawal_queue_usd=5_000, daily_withdrawal_limit_usd=0)
        r = analyze([pos])
        p = r["positions"][0]
        self.assertEqual(p["exit_label"], "FAST")
        self.assertAlmostEqual(p["estimated_exit_days"], 1.0)

    def test_recommendation_string(self):
        r = analyze([_pos()])
        rec = r["positions"][0]["recommendation"]
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_score_within_bounds(self):
        positions = [
            _pos("A", 50_000, lock_up_days_remaining=365),
            _pos("B", 50_000),
        ]
        r = analyze(positions)
        for p in r["positions"]:
            self.assertGreaterEqual(p["exit_liquidity_score"], 0)
            self.assertLessEqual(p["exit_liquidity_score"], 100)


if __name__ == "__main__":
    unittest.main()
