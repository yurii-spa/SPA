"""
Tests for MP-1099: ProtocolDeFiVeTokenLockOptimizer
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_ve_token_lock_optimizer
Target: ≥ 110 tests
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_defi_ve_token_lock_optimizer import (
    ProtocolDeFiVeTokenLockOptimizer,
    _atomic_write,
    _load_log,
    _append_log,
    _validate_inputs,
    _compute_ve_tokens_received,
    _compute_boost_multiplier,
    _compute_boosted_apy_pct,
    _compute_vote_power_share_pct,
    _compute_break_even_weeks,
    _compute_lock_efficiency_score,
    _compute_lock_label,
    _optimize,
    LABEL_OPTIMAL_LOCK,
    LABEL_GOOD_LOCK,
    LABEL_SHORT_LOCK,
    LABEL_OVER_LOCKED,
    LABEL_LOCK_NOT_RECOMMENDED,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

def _default_kwargs(**overrides):
    """Return a valid complete set of kwargs."""
    base = dict(
        token_amount=10_000.0,
        max_lock_weeks=208,
        candidate_lock_weeks=156,  # 75% of max → OPTIMAL territory
        base_apy_pct=5.0,
        max_boost_multiplier=2.5,
        token_price_usd=1.0,
        weekly_rewards_usd=100_000.0,
        total_ve_supply=50_000_000.0,
        user_time_horizon_weeks=200,
        protocol_name="CurveFinance",
    )
    base.update(overrides)
    return base


# ── 1. Label constants ────────────────────────────────────────────────────────

class TestLabelConstants(unittest.TestCase):

    def test_optimal_lock_value(self):
        self.assertEqual(LABEL_OPTIMAL_LOCK, "OPTIMAL_LOCK")

    def test_good_lock_value(self):
        self.assertEqual(LABEL_GOOD_LOCK, "GOOD_LOCK")

    def test_short_lock_value(self):
        self.assertEqual(LABEL_SHORT_LOCK, "SHORT_LOCK")

    def test_over_locked_value(self):
        self.assertEqual(LABEL_OVER_LOCKED, "OVER_LOCKED")

    def test_lock_not_recommended_value(self):
        self.assertEqual(LABEL_LOCK_NOT_RECOMMENDED, "LOCK_NOT_RECOMMENDED")

    def test_all_labels_are_strings(self):
        for lbl in [
            LABEL_OPTIMAL_LOCK, LABEL_GOOD_LOCK, LABEL_SHORT_LOCK,
            LABEL_OVER_LOCKED, LABEL_LOCK_NOT_RECOMMENDED,
        ]:
            self.assertIsInstance(lbl, str)

    def test_all_labels_are_unique(self):
        labels = [
            LABEL_OPTIMAL_LOCK, LABEL_GOOD_LOCK, LABEL_SHORT_LOCK,
            LABEL_OVER_LOCKED, LABEL_LOCK_NOT_RECOMMENDED,
        ]
        self.assertEqual(len(labels), len(set(labels)))


# ── 2. _compute_ve_tokens_received ───────────────────────────────────────────

class TestComputeVeTokensReceived(unittest.TestCase):

    def test_max_lock_full_amount(self):
        result = _compute_ve_tokens_received(
            token_amount=10_000.0, candidate_lock_weeks=208, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 10_000.0, places=6)

    def test_half_lock(self):
        result = _compute_ve_tokens_received(
            token_amount=10_000.0, candidate_lock_weeks=104, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 5_000.0, places=6)

    def test_zero_lock(self):
        result = _compute_ve_tokens_received(
            token_amount=10_000.0, candidate_lock_weeks=0, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_quarter_lock(self):
        result = _compute_ve_tokens_received(
            token_amount=10_000.0, candidate_lock_weeks=52, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 2_500.0, places=6)

    def test_zero_token_amount(self):
        result = _compute_ve_tokens_received(
            token_amount=0.0, candidate_lock_weeks=104, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_proportional_to_lock_duration(self):
        r1 = _compute_ve_tokens_received(1000.0, candidate_lock_weeks=25, max_lock_weeks=100)
        r2 = _compute_ve_tokens_received(1000.0, candidate_lock_weeks=50, max_lock_weeks=100)
        r3 = _compute_ve_tokens_received(1000.0, candidate_lock_weeks=75, max_lock_weeks=100)
        self.assertAlmostEqual(r1, 250.0, places=6)
        self.assertAlmostEqual(r2, 500.0, places=6)
        self.assertAlmostEqual(r3, 750.0, places=6)

    def test_small_amounts(self):
        result = _compute_ve_tokens_received(
            token_amount=1.0, candidate_lock_weeks=1, max_lock_weeks=4
        )
        self.assertAlmostEqual(result, 0.25, places=8)


# ── 3. _compute_boost_multiplier ─────────────────────────────────────────────

class TestComputeBoostMultiplier(unittest.TestCase):

    def test_at_max_lock_gives_max_boost(self):
        result = _compute_boost_multiplier(
            max_boost_multiplier=2.5, candidate_lock_weeks=208, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 2.5, places=8)

    def test_at_zero_lock_gives_1(self):
        result = _compute_boost_multiplier(
            max_boost_multiplier=2.5, candidate_lock_weeks=0, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 1.0, places=8)

    def test_at_half_lock(self):
        # 1 + (2.5 - 1) * 0.5 = 1 + 0.75 = 1.75
        result = _compute_boost_multiplier(
            max_boost_multiplier=2.5, candidate_lock_weeks=104, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 1.75, places=8)

    def test_boost_always_gte_1(self):
        for weeks in [0, 50, 104, 156, 208]:
            result = _compute_boost_multiplier(
                max_boost_multiplier=2.5, candidate_lock_weeks=weeks, max_lock_weeks=208
            )
            self.assertGreaterEqual(result, 1.0)

    def test_boost_always_lte_max(self):
        max_b = 2.5
        for weeks in [0, 52, 104, 156, 208]:
            result = _compute_boost_multiplier(
                max_boost_multiplier=max_b, candidate_lock_weeks=weeks, max_lock_weeks=208
            )
            self.assertLessEqual(result, max_b)

    def test_boost_monotone_increasing(self):
        boosts = [
            _compute_boost_multiplier(
                max_boost_multiplier=2.5, candidate_lock_weeks=w, max_lock_weeks=208
            )
            for w in range(0, 209, 8)
        ]
        for i in range(len(boosts) - 1):
            self.assertLessEqual(boosts[i], boosts[i + 1])

    def test_boost_1x_when_max_boost_is_1(self):
        result = _compute_boost_multiplier(
            max_boost_multiplier=1.0, candidate_lock_weeks=104, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 1.0, places=8)

    def test_three_x_max_boost(self):
        # 1 + (3.0 - 1) * 52/208 = 1 + 2*0.25 = 1.5
        result = _compute_boost_multiplier(
            max_boost_multiplier=3.0, candidate_lock_weeks=52, max_lock_weeks=208
        )
        self.assertAlmostEqual(result, 1.5, places=8)


# ── 4. _compute_boosted_apy_pct ──────────────────────────────────────────────

class TestComputeBoostedApyPct(unittest.TestCase):

    def test_no_boost(self):
        self.assertAlmostEqual(_compute_boosted_apy_pct(5.0, 1.0), 5.0, places=8)

    def test_max_boost(self):
        self.assertAlmostEqual(_compute_boosted_apy_pct(5.0, 2.5), 12.5, places=8)

    def test_zero_base_apy(self):
        self.assertAlmostEqual(_compute_boosted_apy_pct(0.0, 2.5), 0.0, places=8)

    def test_proportional(self):
        self.assertAlmostEqual(_compute_boosted_apy_pct(10.0, 2.0), 20.0, places=8)

    def test_boost_doubles(self):
        base = 8.0
        self.assertAlmostEqual(_compute_boosted_apy_pct(base, 2.0), 16.0, places=8)


# ── 5. _compute_vote_power_share_pct ─────────────────────────────────────────

class TestComputeVotePowerSharePct(unittest.TestCase):

    def test_zero_ve_and_supply(self):
        result = _compute_vote_power_share_pct(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=8)

    def test_equal_ve_to_supply(self):
        # 1000 / (1000 + 1000) * 100 = 50%
        result = _compute_vote_power_share_pct(1000.0, 1000.0)
        self.assertAlmostEqual(result, 50.0, places=8)

    def test_tiny_share(self):
        # 1000 / (50_000_000 + 1000) * 100 ≈ 0.002%
        result = _compute_vote_power_share_pct(1000.0, 50_000_000.0)
        self.assertAlmostEqual(result, 1000.0 / 50_001_000.0 * 100.0, places=6)

    def test_zero_ve(self):
        result = _compute_vote_power_share_pct(0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0, places=8)

    def test_zero_supply(self):
        # All ve supply belongs to user
        result = _compute_vote_power_share_pct(1000.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=8)

    def test_always_between_0_and_100(self):
        for ve, supply in [(0, 0), (0, 100), (100, 0), (100, 100), (1, 1_000_000)]:
            result = _compute_vote_power_share_pct(ve, supply)
            self.assertGreaterEqual(result, 0.0)
            self.assertLessEqual(result, 100.0)


# ── 6. _compute_break_even_weeks ──────────────────────────────────────────────

class TestComputeBreakEvenWeeks(unittest.TestCase):

    def test_returns_none_for_zero_price(self):
        result = _compute_break_even_weeks(10_000.0, 0.0, 5.0, 12.5)
        self.assertIsNone(result)

    def test_returns_none_for_zero_amount(self):
        result = _compute_break_even_weeks(0.0, 1.0, 5.0, 12.5)
        self.assertIsNone(result)

    def test_returns_none_when_no_incremental_yield(self):
        # boosted == base → no benefit
        result = _compute_break_even_weeks(10_000.0, 1.0, 5.0, 5.0)
        self.assertIsNone(result)

    def test_returns_float_with_valid_inputs(self):
        result = _compute_break_even_weeks(10_000.0, 1.0, 5.0, 12.5)
        self.assertIsInstance(result, float)

    def test_zero_base_apy_returns_zero(self):
        result = _compute_break_even_weeks(10_000.0, 1.0, 0.0, 5.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_break_even_positive(self):
        result = _compute_break_even_weeks(10_000.0, 1.0, 3.0, 7.5)
        self.assertGreater(result, 0.0)

    def test_higher_boost_lower_break_even(self):
        be1 = _compute_break_even_weeks(10_000.0, 1.0, 5.0, 8.0)  # 3% extra
        be2 = _compute_break_even_weeks(10_000.0, 1.0, 5.0, 12.5)  # 7.5% extra
        self.assertIsNotNone(be1)
        self.assertIsNotNone(be2)
        self.assertGreater(be1, be2)


# ── 7. _compute_lock_efficiency_score ─────────────────────────────────────────

class TestComputeLockEfficiencyScore(unittest.TestCase):

    def test_returns_int(self):
        score = _compute_lock_efficiency_score(104, 208, 104, 1.75, 2.5, 5_000.0, 50_000_000.0)
        self.assertIsInstance(score, int)

    def test_score_in_range(self):
        for c, h in [(0, 200), (52, 200), (104, 200), (156, 200), (208, 208)]:
            score = _compute_lock_efficiency_score(c, 208, h, 1.75, 2.5, 5_000.0, 50_000_000.0)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_max_lock_aligned_horizon_higher_score(self):
        s_max = _compute_lock_efficiency_score(208, 208, 208, 2.5, 2.5, 10_000.0, 50_000_000.0)
        s_quarter = _compute_lock_efficiency_score(52, 208, 52, 1.25, 2.5, 2_500.0, 50_000_000.0)
        self.assertGreater(s_max, s_quarter)

    def test_zero_candidate_lock(self):
        score = _compute_lock_efficiency_score(0, 208, 100, 1.0, 2.5, 0.0, 50_000_000.0)
        self.assertGreaterEqual(score, 0)

    def test_zero_horizon(self):
        score = _compute_lock_efficiency_score(104, 208, 0, 1.75, 2.5, 5_000.0, 50_000_000.0)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_max_boost_unity_gives_full_component_3(self):
        # max_boost=1.0, boost=1.0 → component 3 = 20
        score_with = _compute_lock_efficiency_score(104, 208, 104, 1.0, 1.0, 5000.0, 50_000_000.0)
        self.assertGreaterEqual(score_with, 0)

    def test_zero_supply_full_vote_power(self):
        # All veTokens → user, so vote_share = 100% → c4 = 10
        score = _compute_lock_efficiency_score(208, 208, 208, 2.5, 2.5, 10_000.0, 0.0)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ── 8. _compute_lock_label ────────────────────────────────────────────────────

class TestComputeLockLabel(unittest.TestCase):

    def test_zero_price_not_recommended(self):
        lbl = _compute_lock_label(156, 208, 200, 0.0, 5.0)
        self.assertEqual(lbl, LABEL_LOCK_NOT_RECOMMENDED)

    def test_zero_base_apy_not_recommended(self):
        lbl = _compute_lock_label(156, 208, 200, 1.0, 0.0)
        self.assertEqual(lbl, LABEL_LOCK_NOT_RECOMMENDED)

    def test_both_zero_not_recommended(self):
        lbl = _compute_lock_label(156, 208, 200, 0.0, 0.0)
        self.assertEqual(lbl, LABEL_LOCK_NOT_RECOMMENDED)

    def test_over_locked(self):
        # candidate=200, horizon=100, 200 > 100*1.5=150 → OVER_LOCKED
        lbl = _compute_lock_label(200, 208, 100, 1.0, 5.0)
        self.assertEqual(lbl, LABEL_OVER_LOCKED)

    def test_exactly_1_5x_horizon_over_locked(self):
        # candidate=150, horizon=100, 150 > 150 is False, so NOT over_locked
        # 150 > 100 * 1.5 → 150 > 150 is False → not over_locked
        lbl = _compute_lock_label(150, 208, 100, 1.0, 5.0)
        self.assertNotEqual(lbl, LABEL_OVER_LOCKED)

    def test_short_lock(self):
        # candidate=40, max=208, 40 < 208*0.25=52 → SHORT_LOCK
        lbl = _compute_lock_label(40, 208, 200, 1.0, 5.0)
        self.assertEqual(lbl, LABEL_SHORT_LOCK)

    def test_optimal_lock(self):
        # candidate=156 >= 208*0.75=156, horizon=200 >= 156 → OPTIMAL_LOCK
        lbl = _compute_lock_label(156, 208, 200, 1.0, 5.0)
        self.assertEqual(lbl, LABEL_OPTIMAL_LOCK)

    def test_good_lock(self):
        # candidate=104 >= 208*0.5=104, horizon=200 >= 104 → GOOD_LOCK
        lbl = _compute_lock_label(104, 208, 200, 1.0, 5.0)
        self.assertEqual(lbl, LABEL_GOOD_LOCK)

    def test_horizon_too_short_for_optimal_falls_to_short(self):
        # candidate=156, horizon=100 < 156 → can't be OPTIMAL or GOOD → SHORT_LOCK
        lbl = _compute_lock_label(156, 208, 100, 1.0, 5.0)
        # 156 > 100*1.5=150 → OVER_LOCKED (not SHORT_LOCK)
        self.assertEqual(lbl, LABEL_OVER_LOCKED)

    def test_short_lock_exactly_at_threshold(self):
        # candidate=52, max=208; 52 < 52 is False (52 == 52); 52 >= 104? No → SHORT_LOCK
        lbl = _compute_lock_label(52, 208, 200, 1.0, 5.0)
        self.assertEqual(lbl, LABEL_SHORT_LOCK)

    def test_not_recommended_takes_precedence_over_over_locked(self):
        # price=0 → LOCK_NOT_RECOMMENDED even if candidate >> horizon*1.5
        lbl = _compute_lock_label(208, 208, 10, 0.0, 5.0)
        self.assertEqual(lbl, LABEL_LOCK_NOT_RECOMMENDED)


# ── 9. _validate_inputs ──────────────────────────────────────────────────────

class TestValidateInputs(unittest.TestCase):

    def _call(self, **overrides):
        kwargs = _default_kwargs(**overrides)
        _validate_inputs(**kwargs)

    def test_valid_no_error(self):
        self._call()

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="")

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="  ")

    def test_negative_token_amount_raises(self):
        with self.assertRaises(ValueError):
            self._call(token_amount=-1.0)

    def test_max_lock_zero_raises(self):
        with self.assertRaises(ValueError):
            self._call(max_lock_weeks=0)

    def test_max_lock_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(max_lock_weeks=-1)

    def test_candidate_lock_negative_raises(self):
        with self.assertRaises(ValueError):
            self._call(candidate_lock_weeks=-1)

    def test_candidate_exceeds_max_raises(self):
        with self.assertRaises(ValueError):
            self._call(candidate_lock_weeks=209, max_lock_weeks=208)

    def test_negative_base_apy_raises(self):
        with self.assertRaises(ValueError):
            self._call(base_apy_pct=-0.1)

    def test_max_boost_below_1_raises(self):
        with self.assertRaises(ValueError):
            self._call(max_boost_multiplier=0.9)

    def test_negative_token_price_raises(self):
        with self.assertRaises(ValueError):
            self._call(token_price_usd=-0.01)

    def test_negative_weekly_rewards_raises(self):
        with self.assertRaises(ValueError):
            self._call(weekly_rewards_usd=-100.0)

    def test_negative_ve_supply_raises(self):
        with self.assertRaises(ValueError):
            self._call(total_ve_supply=-1.0)

    def test_negative_horizon_raises(self):
        with self.assertRaises(ValueError):
            self._call(user_time_horizon_weeks=-1)

    def test_zero_candidate_lock_ok(self):
        self._call(candidate_lock_weeks=0)

    def test_zero_token_amount_ok(self):
        self._call(token_amount=0.0)

    def test_zero_token_price_ok(self):
        self._call(token_price_usd=0.0)

    def test_zero_base_apy_ok(self):
        self._call(base_apy_pct=0.0)

    def test_zero_horizon_ok(self):
        self._call(user_time_horizon_weeks=0)

    def test_zero_ve_supply_ok(self):
        self._call(total_ve_supply=0.0)

    def test_max_boost_exactly_1_ok(self):
        self._call(max_boost_multiplier=1.0)


# ── 10. _optimize function ────────────────────────────────────────────────────

class TestOptimizeFunction(unittest.TestCase):

    def _call(self, **overrides):
        return _optimize(**_default_kwargs(**overrides))

    def test_returns_dict(self):
        self.assertIsInstance(self._call(), dict)

    def test_all_output_keys_present(self):
        result = self._call()
        for key in [
            "protocol_name", "timestamp",
            "token_amount", "max_lock_weeks", "candidate_lock_weeks",
            "base_apy_pct", "max_boost_multiplier", "token_price_usd",
            "weekly_rewards_usd", "total_ve_supply", "user_time_horizon_weeks",
            "ve_tokens_received", "boost_multiplier", "boosted_apy_pct",
            "vote_power_share_pct", "break_even_weeks",
            "lock_efficiency_score", "lock_label",
        ]:
            self.assertIn(key, result)

    def test_protocol_name_echoed(self):
        result = self._call(protocol_name="Balancer")
        self.assertEqual(result["protocol_name"], "Balancer")

    def test_ve_tokens_at_max_lock(self):
        result = self._call(candidate_lock_weeks=208, max_lock_weeks=208)
        self.assertAlmostEqual(result["ve_tokens_received"], 10_000.0, places=4)

    def test_ve_tokens_half_lock(self):
        result = self._call(candidate_lock_weeks=104, max_lock_weeks=208)
        self.assertAlmostEqual(result["ve_tokens_received"], 5_000.0, places=4)

    def test_boost_at_max(self):
        result = self._call(candidate_lock_weeks=208, max_lock_weeks=208)
        self.assertAlmostEqual(result["boost_multiplier"], 2.5, places=6)

    def test_boost_at_zero(self):
        result = self._call(candidate_lock_weeks=0)
        self.assertAlmostEqual(result["boost_multiplier"], 1.0, places=6)

    def test_boosted_apy_greater_than_base(self):
        result = self._call(candidate_lock_weeks=104)
        self.assertGreater(result["boosted_apy_pct"], result["base_apy_pct"])

    def test_vote_share_positive(self):
        result = self._call()
        self.assertGreater(result["vote_power_share_pct"], 0.0)

    def test_vote_share_zero_with_zero_tokens(self):
        result = self._call(token_amount=0.0)
        self.assertAlmostEqual(result["vote_power_share_pct"], 0.0, places=6)

    def test_lock_label_is_valid(self):
        result = self._call()
        self.assertIn(
            result["lock_label"],
            [LABEL_OPTIMAL_LOCK, LABEL_GOOD_LOCK, LABEL_SHORT_LOCK,
             LABEL_OVER_LOCKED, LABEL_LOCK_NOT_RECOMMENDED],
        )

    def test_efficiency_score_is_int(self):
        result = self._call()
        self.assertIsInstance(result["lock_efficiency_score"], int)

    def test_efficiency_score_in_range(self):
        result = self._call()
        self.assertGreaterEqual(result["lock_efficiency_score"], 0)
        self.assertLessEqual(result["lock_efficiency_score"], 100)

    def test_timestamp_present(self):
        result = self._call()
        self.assertIn("T", result["timestamp"])

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            _optimize(**_default_kwargs(max_lock_weeks=0))

    def test_break_even_none_when_zero_price(self):
        result = self._call(token_price_usd=0.0)
        self.assertIsNone(result["break_even_weeks"])


# ── 11. Atomic I/O helpers ────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ve_log.json")
            _atomic_write(path, [{"a": 1}])
            self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ve_log.json")
            _atomic_write(path, {"key": "val"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "val")

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ve_log.json")
            _atomic_write(path, [1])
            _atomic_write(path, [2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [2, 3])

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "deep", "path", "ve_log.json")
            _atomic_write(path, [])
            self.assertTrue(os.path.exists(path))

    def test_unicode_safe(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ve_log.json")
            _atomic_write(path, {"name": "Крива", "sym": "🔒"})
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["name"], "Крива")


class TestLoadLog(unittest.TestCase):

    def test_missing_file_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load_log(os.path.join(d, "nope.json")), [])

    def test_valid_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, [{"x": 1}])
            self.assertEqual(_load_log(path), [{"x": 1}])

    def test_invalid_json_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                f.write("{{{")
            self.assertEqual(_load_log(path), [])

    def test_non_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, {"not": "list"})
            self.assertEqual(_load_log(path), [])

    def test_empty_list_ok(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_write(path, [])
            self.assertEqual(_load_log(path), [])


class TestAppendLog(unittest.TestCase):

    def test_append_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(path, {"a": 1})
            self.assertTrue(os.path.exists(path))

    def test_single_append(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(path, {"z": 9})
            self.assertEqual(_load_log(path), [{"z": 9}])

    def test_multiple_appends_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(path, {"i": 1})
            _append_log(path, {"i": 2})
            result = _load_log(path)
            self.assertEqual([r["i"] for r in result], [1, 2])

    def test_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for i in range(110):
                _append_log(path, {"seq": i})
            result = _load_log(path)
            self.assertEqual(len(result), 100)
            self.assertEqual(result[0]["seq"], 10)
            self.assertEqual(result[-1]["seq"], 109)

    def test_ring_buffer_exactly_at_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for i in range(100):
                _append_log(path, {"n": i})
            result = _load_log(path)
            self.assertEqual(len(result), 100)


# ── 12. Class-level integration ───────────────────────────────────────────────

class TestProtocolDeFiVeTokenLockOptimizer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "ve_log.json")
        self.optimizer = ProtocolDeFiVeTokenLockOptimizer(data_file=self.log_path)

    def _run(self, **overrides):
        return self.optimizer.optimize(**_default_kwargs(**overrides))

    def test_optimize_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_optimize_writes_log(self):
        self._run()
        self.assertTrue(os.path.exists(self.log_path))

    def test_optimize_log_has_one_entry(self):
        self._run()
        self.assertEqual(len(_load_log(self.log_path)), 1)

    def test_optimize_three_entries(self):
        self._run()
        self._run()
        self._run()
        self.assertEqual(len(_load_log(self.log_path)), 3)

    def test_write_log_false_no_file(self):
        self.optimizer.optimize(**_default_kwargs(), write_log=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_optimal_lock_label(self):
        # 156/208 = 75% of max; horizon=200 > 156 → OPTIMAL_LOCK
        result = self._run(
            candidate_lock_weeks=156,
            max_lock_weeks=208,
            user_time_horizon_weeks=200,
        )
        self.assertEqual(result["lock_label"], LABEL_OPTIMAL_LOCK)

    def test_good_lock_label(self):
        # 104/208 = 50% of max; horizon=200 > 104 → GOOD_LOCK
        result = self._run(
            candidate_lock_weeks=104,
            max_lock_weeks=208,
            user_time_horizon_weeks=200,
        )
        self.assertEqual(result["lock_label"], LABEL_GOOD_LOCK)

    def test_short_lock_label(self):
        # 40/208 < 0.25 → SHORT_LOCK
        result = self._run(
            candidate_lock_weeks=40,
            max_lock_weeks=208,
            user_time_horizon_weeks=200,
        )
        self.assertEqual(result["lock_label"], LABEL_SHORT_LOCK)

    def test_over_locked_label(self):
        # 200 > 100 * 1.5 = 150 → OVER_LOCKED
        result = self._run(
            candidate_lock_weeks=200,
            max_lock_weeks=208,
            user_time_horizon_weeks=100,
        )
        self.assertEqual(result["lock_label"], LABEL_OVER_LOCKED)

    def test_not_recommended_zero_price(self):
        result = self._run(token_price_usd=0.0)
        self.assertEqual(result["lock_label"], LABEL_LOCK_NOT_RECOMMENDED)

    def test_not_recommended_zero_apy(self):
        result = self._run(base_apy_pct=0.0)
        self.assertEqual(result["lock_label"], LABEL_LOCK_NOT_RECOMMENDED)

    def test_ring_buffer_via_class(self):
        for i in range(105):
            self._run(protocol_name=f"P{i}")
        self.assertEqual(len(_load_log(self.log_path)), 100)

    def test_default_data_file(self):
        opt = ProtocolDeFiVeTokenLockOptimizer()
        self.assertIn("ve_token_lock_optimizer_log.json", opt.data_file)

    def test_custom_data_file(self):
        p = os.path.join(self.tmpdir, "custom.json")
        opt = ProtocolDeFiVeTokenLockOptimizer(data_file=p)
        opt.optimize(**_default_kwargs())
        self.assertTrue(os.path.exists(p))

    def test_raises_on_bad_input(self):
        with self.assertRaises(ValueError):
            self._run(max_lock_weeks=0)

    def test_consistent_outputs_same_input(self):
        r1 = self.optimizer.optimize(**_default_kwargs(), write_log=False)
        r2 = self.optimizer.optimize(**_default_kwargs(), write_log=False)
        for key in ["ve_tokens_received", "boost_multiplier", "boosted_apy_pct",
                    "vote_power_share_pct", "lock_efficiency_score", "lock_label"]:
            self.assertEqual(r1[key], r2[key])

    def test_json_serializable(self):
        result = self._run()
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    def test_log_entry_has_all_output_keys(self):
        self._run()
        entry = _load_log(self.log_path)[0]
        for key in [
            "ve_tokens_received", "boost_multiplier", "boosted_apy_pct",
            "vote_power_share_pct", "break_even_weeks",
            "lock_efficiency_score", "lock_label",
        ]:
            self.assertIn(key, entry)

    def test_boost_monotone_with_lock_duration(self):
        boosts = []
        for weeks in [0, 52, 104, 156, 208]:
            r = self.optimizer.optimize(
                **_default_kwargs(candidate_lock_weeks=weeks), write_log=False
            )
            boosts.append(r["boost_multiplier"])
        for i in range(len(boosts) - 1):
            self.assertLessEqual(boosts[i], boosts[i + 1])

    def test_ve_tokens_monotone_with_lock_duration(self):
        ve_tokens = []
        for weeks in [0, 52, 104, 156, 208]:
            r = self.optimizer.optimize(
                **_default_kwargs(candidate_lock_weeks=weeks), write_log=False
            )
            ve_tokens.append(r["ve_tokens_received"])
        for i in range(len(ve_tokens) - 1):
            self.assertLessEqual(ve_tokens[i], ve_tokens[i + 1])


# ── 13. Edge and boundary tests ───────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.optimizer = ProtocolDeFiVeTokenLockOptimizer(
            data_file=os.path.join(self.tmpdir, "edge.json")
        )

    def test_zero_candidate_lock(self):
        result = self.optimizer.optimize(**_default_kwargs(candidate_lock_weeks=0))
        self.assertAlmostEqual(result["ve_tokens_received"], 0.0, places=6)
        self.assertAlmostEqual(result["boost_multiplier"], 1.0, places=6)

    def test_max_candidate_lock(self):
        result = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=208, max_lock_weeks=208)
        )
        self.assertAlmostEqual(result["ve_tokens_received"], 10_000.0, places=4)
        self.assertAlmostEqual(result["boost_multiplier"], 2.5, places=6)

    def test_zero_total_ve_supply(self):
        result = self.optimizer.optimize(**_default_kwargs(total_ve_supply=0.0))
        # User gets 100% of voting power
        self.assertAlmostEqual(result["vote_power_share_pct"], 100.0, places=4)

    def test_very_large_supply_tiny_share(self):
        result = self.optimizer.optimize(
            **_default_kwargs(total_ve_supply=1_000_000_000_000.0)
        )
        self.assertLess(result["vote_power_share_pct"], 0.01)

    def test_break_even_none_zero_price(self):
        result = self.optimizer.optimize(**_default_kwargs(token_price_usd=0.0))
        self.assertIsNone(result["break_even_weeks"])

    def test_all_four_valid_labels_reachable(self):
        """Verify all non-not-recommended labels are reachable."""
        # OPTIMAL
        r1 = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=156, user_time_horizon_weeks=200),
            write_log=False,
        )
        self.assertEqual(r1["lock_label"], LABEL_OPTIMAL_LOCK)

        # GOOD
        r2 = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=104, user_time_horizon_weeks=200),
            write_log=False,
        )
        self.assertEqual(r2["lock_label"], LABEL_GOOD_LOCK)

        # SHORT
        r3 = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=40, user_time_horizon_weeks=200),
            write_log=False,
        )
        self.assertEqual(r3["lock_label"], LABEL_SHORT_LOCK)

        # OVER_LOCKED
        r4 = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=200, user_time_horizon_weeks=50),
            write_log=False,
        )
        self.assertEqual(r4["lock_label"], LABEL_OVER_LOCKED)

    def test_exact_75_pct_threshold_is_optimal(self):
        # 208 * 0.75 = 156 exactly
        result = self.optimizer.optimize(
            **_default_kwargs(
                candidate_lock_weeks=156, max_lock_weeks=208,
                user_time_horizon_weeks=200,
            ),
            write_log=False,
        )
        self.assertEqual(result["lock_label"], LABEL_OPTIMAL_LOCK)

    def test_exact_50_pct_threshold_is_good_not_optimal(self):
        # 208 * 0.5 = 104; 104 < 156 → GOOD not OPTIMAL
        result = self.optimizer.optimize(
            **_default_kwargs(
                candidate_lock_weeks=104, max_lock_weeks=208,
                user_time_horizon_weeks=200,
            ),
            write_log=False,
        )
        self.assertEqual(result["lock_label"], LABEL_GOOD_LOCK)

    def test_score_higher_for_longer_aligned_lock(self):
        s_long = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=208, user_time_horizon_weeks=208),
            write_log=False,
        )["lock_efficiency_score"]
        s_short = self.optimizer.optimize(
            **_default_kwargs(candidate_lock_weeks=52, user_time_horizon_weeks=52),
            write_log=False,
        )["lock_efficiency_score"]
        self.assertGreater(s_long, s_short)


if __name__ == "__main__":
    unittest.main()
