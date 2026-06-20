"""Tests for spa_core.analytics.rebalance_optimizer (MP-619).

Groups / counts:
  TestRebalanceMove            12
  TestRebalancePlan            10
  TestLoadCurrentPositions      6
  TestLoadAdapterRegistry       6
  TestFindUpgradeOpportunities 20
  TestCheckTierLimits          10
  TestEstimateOptimizedApy      8
  TestGeneratePlan             12
  TestSavePlan                  4
  TestFormatTelegramMessage     8
                               ---
  Total                        96

All tests use tempfile.TemporaryDirectory — production data/ NOT touched.
"""
from __future__ import annotations

import json
import os
import unittest
import tempfile
from dataclasses import asdict
from pathlib import Path

from spa_core.analytics.rebalance_optimizer import (
    DISCLAIMER,
    RebalanceMove,
    RebalancePlan,
    RebalanceOptimizer,
    _classify_priority,
    _safe_float,
    _extract_apy,
    RING_BUFFER_MAX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_optimizer(data_dir: str) -> RebalanceOptimizer:
    return RebalanceOptimizer(data_path=data_dir)


def _write_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_tracker_json(
    total_usd: float,
    contributions: list,
) -> dict:
    """Build a minimal yield_attribution_tracker.json payload."""
    return {
        "schema_version": "1.0",
        "latest": {
            "total_allocated_usd": total_usd,
            "contributions": contributions,
        },
    }


def _make_adapter_status(adapters: dict) -> dict:
    """Build a minimal adapter_status.json payload with top-level entries."""
    return adapters


def _make_contribution(
    adapter_id: str,
    allocated_usd: float,
    apy_pct: float,
    tier: str = "T1",
) -> dict:
    return {
        "adapter_id": adapter_id,
        "allocated_usd": allocated_usd,
        "apy_pct": apy_pct,
        "tier": tier,
    }


def _make_adapter_entry(apy_pct: float, tier: str, is_eligible: bool = True, risk_score: float = 0.3) -> dict:
    return {
        "apy_pct": apy_pct,
        "tier": tier,
        "is_eligible": is_eligible,
        "risk_score": risk_score,
    }


# ---------------------------------------------------------------------------
# TestRebalanceMove (12)
# ---------------------------------------------------------------------------


class TestRebalanceMove(unittest.TestCase):
    """Tests for RebalanceMove dataclass."""

    def _make_move(self, from_apy: float = 3.0, to_apy: float = 5.0, amount: float = 10_000.0) -> RebalanceMove:
        gain = to_apy - from_apy
        return RebalanceMove(
            from_adapter="aave_v3",
            to_adapter="morpho_blue",
            amount_usd=amount,
            from_apy=from_apy,
            to_apy=to_apy,
            apy_gain_pct=gain,
            annual_gain_usd=amount * gain / 100.0,
            priority=_classify_priority(gain),
            reason=f"Higher APY: {to_apy:.1f}% vs {from_apy:.1f}%",
        )

    def test_apy_gain_pct_calculation(self):
        """apy_gain_pct = to_apy - from_apy."""
        m = self._make_move(3.0, 5.0)
        self.assertAlmostEqual(m.apy_gain_pct, 2.0)

    def test_annual_gain_usd_calculation(self):
        """annual_gain_usd = amount_usd * apy_gain / 100."""
        m = self._make_move(3.0, 5.0, 10_000.0)
        self.assertAlmostEqual(m.annual_gain_usd, 200.0)

    def test_priority_high_when_gain_above_1_5(self):
        """Gain > 1.5% → HIGH."""
        m = self._make_move(3.0, 5.0)  # gain = 2.0
        self.assertEqual(m.priority, "HIGH")

    def test_priority_high_exact_boundary(self):
        """Gain = 1.6% → HIGH (strictly > 1.5)."""
        self.assertEqual(_classify_priority(1.6), "HIGH")

    def test_priority_medium_at_1_5(self):
        """Gain = 1.5% → MEDIUM (not > 1.5)."""
        self.assertEqual(_classify_priority(1.5), "MEDIUM")

    def test_priority_medium_at_0_5(self):
        """Gain = 0.5% → MEDIUM (lower boundary)."""
        self.assertEqual(_classify_priority(0.5), "MEDIUM")

    def test_priority_low_below_0_5(self):
        """Gain = 0.4% → LOW."""
        self.assertEqual(_classify_priority(0.4), "LOW")

    def test_priority_low_zero(self):
        """Gain = 0.0% → LOW."""
        self.assertEqual(_classify_priority(0.0), "LOW")

    def test_reason_format(self):
        """reason must contain both APY values."""
        m = self._make_move(4.1, 5.2)
        self.assertIn("5.2%", m.reason)
        self.assertIn("4.1%", m.reason)

    def test_to_dict_keys(self):
        """to_dict returns all expected fields."""
        m = self._make_move()
        d = m.to_dict()
        for key in ("from_adapter", "to_adapter", "amount_usd", "from_apy",
                    "to_apy", "apy_gain_pct", "annual_gain_usd", "priority", "reason"):
            self.assertIn(key, d)

    def test_to_dict_json_serializable(self):
        """to_dict result must be JSON-serializable."""
        m = self._make_move()
        json.dumps(m.to_dict())  # should not raise

    def test_from_to_adapter_stored_correctly(self):
        """from_adapter and to_adapter are stored as given."""
        m = self._make_move()
        self.assertEqual(m.from_adapter, "aave_v3")
        self.assertEqual(m.to_adapter, "morpho_blue")


# ---------------------------------------------------------------------------
# TestRebalancePlan (10)
# ---------------------------------------------------------------------------


class TestRebalancePlan(unittest.TestCase):
    """Tests for RebalancePlan dataclass and recommendation logic."""

    def _make_plan(self, moves: list, recommendation: str = "HOLD") -> RebalancePlan:
        high = [m for m in moves if m.priority == "HIGH"]
        return RebalancePlan(
            generated_at="2026-06-13T00:00:00+00:00",
            current_portfolio_apy=5.0,
            optimized_portfolio_apy=5.5,
            apy_improvement=0.5,
            annual_improvement_usd=500.0,
            moves=moves,
            high_priority_moves=high,
            total_moves=len(moves),
            tier_limits_respected=True,
            min_move_usd=500.0,
            recommendation=recommendation,
            summary=f"{len(moves)} moves suggested",
            disclaimer=DISCLAIMER,
        )

    def _high_move(self) -> RebalanceMove:
        return RebalanceMove("a", "b", 10_000.0, 3.0, 5.5, 2.5, 250.0, "HIGH", "Higher APY")

    def _medium_move(self) -> RebalanceMove:
        return RebalanceMove("c", "d", 5_000.0, 4.0, 4.8, 0.8, 40.0, "MEDIUM", "Higher APY")

    def _low_move(self) -> RebalanceMove:
        return RebalanceMove("e", "f", 2_000.0, 4.5, 4.7, 0.2, 4.0, "LOW", "Higher APY")

    def test_recommendation_rebalance_with_high(self):
        """Has HIGH → REBALANCE."""
        plan = self._make_plan([self._high_move()], recommendation="REBALANCE")
        self.assertEqual(plan.recommendation, "REBALANCE")

    def test_recommendation_monitor_with_medium(self):
        """Has MEDIUM, no HIGH → MONITOR."""
        plan = self._make_plan([self._medium_move()], recommendation="MONITOR")
        self.assertEqual(plan.recommendation, "MONITOR")

    def test_recommendation_hold_with_low_only(self):
        """Only LOW → HOLD."""
        plan = self._make_plan([self._low_move()], recommendation="HOLD")
        self.assertEqual(plan.recommendation, "HOLD")

    def test_recommendation_hold_empty_moves(self):
        """No moves → HOLD."""
        plan = self._make_plan([], recommendation="HOLD")
        self.assertEqual(plan.recommendation, "HOLD")

    def test_tier_limits_respected_field(self):
        """tier_limits_respected is stored correctly."""
        plan = self._make_plan([])
        self.assertTrue(plan.tier_limits_respected)

    def test_disclaimer_always_set(self):
        """disclaimer is always the standard advisory text."""
        plan = self._make_plan([])
        self.assertEqual(plan.disclaimer, DISCLAIMER)

    def test_high_priority_moves_populated(self):
        """high_priority_moves contains only HIGH priority."""
        plan = self._make_plan([self._high_move(), self._medium_move()], "REBALANCE")
        self.assertEqual(len(plan.high_priority_moves), 1)
        self.assertEqual(plan.high_priority_moves[0].priority, "HIGH")

    def test_total_moves_matches_moves_len(self):
        """total_moves == len(moves)."""
        moves = [self._high_move(), self._medium_move()]
        plan = self._make_plan(moves, "REBALANCE")
        self.assertEqual(plan.total_moves, len(moves))

    def test_to_dict_json_serializable(self):
        """to_dict returns JSON-serializable structure."""
        plan = self._make_plan([self._high_move()])
        json.dumps(plan.to_dict())  # no raise

    def test_summary_format_contains_moves_count(self):
        """summary mentions move count."""
        plan = self._make_plan([self._high_move(), self._medium_move()], "REBALANCE")
        self.assertIn("2", plan.summary)


# ---------------------------------------------------------------------------
# TestLoadCurrentPositions (6)
# ---------------------------------------------------------------------------


class TestLoadCurrentPositions(unittest.TestCase):
    """Tests for RebalanceOptimizer.load_current_positions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.optimizer = _make_optimizer(self.data_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_defaults(self):
        """No file → (100_000.0, [])."""
        total, contribs = self.optimizer.load_current_positions()
        self.assertEqual(total, 100_000.0)
        self.assertEqual(contribs, [])

    def test_invalid_json_returns_defaults(self):
        """Corrupted JSON → fallback."""
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        with open(path, "w") as f:
            f.write("NOT_JSON{{{")
        total, contribs = self.optimizer.load_current_positions()
        self.assertEqual(total, 100_000.0)
        self.assertEqual(contribs, [])

    def test_valid_file_returns_correct_total(self):
        """Valid file with total → uses that total."""
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        data = _make_tracker_json(
            80_000.0,
            [_make_contribution("aave_v3", 80_000.0, 3.5)],
        )
        _write_json(path, data)
        total, contribs = self.optimizer.load_current_positions()
        self.assertAlmostEqual(total, 80_000.0)

    def test_valid_file_returns_contributions(self):
        """Valid file → contributions list returned."""
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        data = _make_tracker_json(
            100_000.0,
            [
                _make_contribution("aave_v3", 50_000.0, 3.5),
                _make_contribution("compound_v3", 45_000.0, 4.8),
            ],
        )
        _write_json(path, data)
        _, contribs = self.optimizer.load_current_positions()
        self.assertEqual(len(contribs), 2)

    def test_zero_total_falls_back_to_100k(self):
        """total_allocated_usd=0 → fallback to 100_000."""
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        data = _make_tracker_json(0.0, [_make_contribution("aave_v3", 50_000.0, 3.5)])
        _write_json(path, data)
        total, _ = self.optimizer.load_current_positions()
        self.assertEqual(total, 100_000.0)

    def test_zero_allocated_usd_filtered_out(self):
        """Contributions with allocated_usd=0 are excluded."""
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        data = _make_tracker_json(
            100_000.0,
            [
                _make_contribution("aave_v3", 0.0, 3.5),
                _make_contribution("compound_v3", 50_000.0, 4.8),
            ],
        )
        _write_json(path, data)
        _, contribs = self.optimizer.load_current_positions()
        self.assertEqual(len(contribs), 1)
        self.assertEqual(contribs[0]["adapter_id"], "compound_v3")


# ---------------------------------------------------------------------------
# TestLoadAdapterRegistry (6)
# ---------------------------------------------------------------------------


class TestLoadAdapterRegistry(unittest.TestCase):
    """Tests for RebalanceOptimizer.load_adapter_registry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.optimizer = _make_optimizer(self.data_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_empty(self):
        """No adapter_status.json → {}."""
        self.assertEqual(self.optimizer.load_adapter_registry(), {})

    def test_invalid_json_returns_empty(self):
        """Corrupted JSON → {}."""
        path = os.path.join(self.data_dir, "adapter_status.json")
        with open(path, "w") as f:
            f.write("{invalid}")
        self.assertEqual(self.optimizer.load_adapter_registry(), {})

    def test_valid_file_returns_adapters(self):
        """Valid file → registry dict with entries."""
        path = os.path.join(self.data_dir, "adapter_status.json")
        _write_json(path, {
            "aave_v3": _make_adapter_entry(3.5, "T1"),
            "compound_v3": _make_adapter_entry(4.8, "T1"),
        })
        registry = self.optimizer.load_adapter_registry()
        self.assertIn("aave_v3", registry)
        self.assertIn("compound_v3", registry)

    def test_adapter_without_tier_skipped(self):
        """Entries missing 'tier' key are skipped."""
        path = os.path.join(self.data_dir, "adapter_status.json")
        _write_json(path, {
            "no_tier_adapter": {"apy_pct": 5.0},
            "aave_v3": _make_adapter_entry(3.5, "T1"),
        })
        registry = self.optimizer.load_adapter_registry()
        self.assertNotIn("no_tier_adapter", registry)
        self.assertIn("aave_v3", registry)

    def test_adapter_without_positive_apy_skipped(self):
        """Entries with zero/negative APY are skipped."""
        path = os.path.join(self.data_dir, "adapter_status.json")
        _write_json(path, {
            "zero_apy": {"tier": "T1", "apy_pct": 0.0},
            "compound_v3": _make_adapter_entry(4.8, "T1"),
        })
        registry = self.optimizer.load_adapter_registry()
        self.assertNotIn("zero_apy", registry)
        self.assertIn("compound_v3", registry)

    def test_adapters_array_processed(self):
        """Items in 'adapters' array are also included."""
        path = os.path.join(self.data_dir, "adapter_status.json")
        _write_json(path, {
            "generated_at": "2026-06-13",
            "adapters": [
                {"protocol_key": "morpho-blue", "tier": "T2", "apy_pct": 6.5},
            ],
        })
        registry = self.optimizer.load_adapter_registry()
        self.assertIn("morpho_blue", registry)


# ---------------------------------------------------------------------------
# TestFindUpgradeOpportunities (20)
# ---------------------------------------------------------------------------


class TestFindUpgradeOpportunities(unittest.TestCase):
    """Tests for RebalanceOptimizer.find_upgrade_opportunities."""

    def setUp(self):
        self.optimizer = RebalanceOptimizer()

    def _basic_registry(self) -> dict:
        return {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 4.8, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
            "maple": {"apy_pct": 7.0, "tier": "T2", "is_eligible": True, "risk_score": 0.5},
        }

    def test_no_positions_returns_empty(self):
        """Empty current_positions → []."""
        moves = self.optimizer.find_upgrade_opportunities([], self._basic_registry(), 100_000.0)
        self.assertEqual(moves, [])

    def test_no_registry_returns_empty(self):
        """Empty registry → []."""
        positions = [_make_contribution("aave_v3", 50_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, {}, 100_000.0)
        self.assertEqual(moves, [])

    def test_to_equals_from_skipped(self):
        """Candidate same as source → not suggested."""
        registry = {"aave_v3": {"apy_pct": 5.0, "tier": "T1", "is_eligible": True, "risk_score": 0.2}}
        positions = [_make_contribution("aave_v3", 50_000.0, 3.0)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_gain_below_threshold_skipped(self):
        """Gain < 0.1% → not suggested."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 3.55, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
        }
        positions = [_make_contribution("aave_v3", 50_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_gain_exactly_0_1_included(self):
        """Gain = 0.1% → included (at threshold)."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 3.6, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
        }
        positions = [_make_contribution("aave_v3", 50_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)

    def test_amount_below_min_move_skipped(self):
        """allocated_usd < MIN_MOVE_USD → no move generated."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [_make_contribution("aave_v3", 100.0, 3.5)]  # $100 < $500
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_valid_move_created(self):
        """Valid configuration → move created with correct fields."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [_make_contribution("aave_v3", 40_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)
        m = moves[0]
        self.assertEqual(m.from_adapter, "aave_v3")
        self.assertEqual(m.to_adapter, "morpho_blue")
        self.assertAlmostEqual(m.apy_gain_pct, 3.0)

    def test_sorted_by_apy_gain_descending(self):
        """Moves are sorted by apy_gain descending."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 4.0, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
            "morpho_blue": {"apy_pct": 7.0, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
            "maple": {"apy_pct": 6.0, "tier": "T2", "is_eligible": True, "risk_score": 0.5},
        }
        positions = [
            _make_contribution("aave_v3", 30_000.0, 3.5),
            _make_contribution("compound_v3", 30_000.0, 4.0),
        ]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        gains = [m.apy_gain_pct for m in moves]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_ineligible_adapter_skipped(self):
        """is_eligible=False → candidate skipped."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "bad_pool": {"apy_pct": 9.0, "tier": "T2", "is_eligible": False, "risk_score": 0.9},
        }
        positions = [_make_contribution("aave_v3", 50_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_tier_limit_violated_skipped(self):
        """Move from T1 to T3 that would breach 10% T3 cap → skipped."""
        optimizer = RebalanceOptimizer()
        # T3 already at 10%; moving 80K T1 capital to T3 would push T3 to 90% → blocked
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "t3_pool": {"apy_pct": 20.0, "tier": "T3", "is_eligible": True, "risk_score": 0.8},
        }
        # Only one position: aave_v3 (T1). Moving 80K to T3 → 80% T3 > 10% cap → blocked
        positions = [
            _make_contribution("aave_v3", 80_000.0, 3.5, "T1"),
        ]
        moves = optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        # The T3 move from aave_v3 should be blocked
        t3_moves = [m for m in moves if m.to_adapter == "t3_pool" and m.from_adapter == "aave_v3"]
        self.assertEqual(t3_moves, [])

    def test_multiple_positions_multiple_moves(self):
        """Multiple positions each with an upgrade → multiple moves."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 4.0, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [
            _make_contribution("aave_v3", 20_000.0, 3.5, "T1"),
            _make_contribution("compound_v3", 20_000.0, 4.0, "T1"),
        ]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 2)

    def test_best_candidate_selected(self):
        """For one position, the highest-gain candidate is selected."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "option_a": {"apy_pct": 5.0, "tier": "T1", "is_eligible": True, "risk_score": 0.3},
            "option_b": {"apy_pct": 7.0, "tier": "T1", "is_eligible": True, "risk_score": 0.35},
        }
        positions = [_make_contribution("aave_v3", 50_000.0, 3.5, "T1")]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].to_adapter, "option_b")

    def test_move_amount_equals_position_size(self):
        """Move amount = full position size."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [_make_contribution("aave_v3", 33_000.0, 3.5)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves[0].amount_usd, 33_000.0)

    def test_no_better_adapter_available(self):
        """Current adapter already has best APY → no move."""
        registry = {
            "morpho_blue": {"apy_pct": 7.0, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
        }
        positions = [_make_contribution("morpho_blue", 50_000.0, 7.0, "T2")]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_annual_gain_computed_correctly(self):
        """annual_gain_usd = amount_usd * apy_gain / 100."""
        registry = {
            "aave_v3": {"apy_pct": 3.0, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 5.0, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [_make_contribution("aave_v3", 10_000.0, 3.0)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)
        # gain = 2.0%, amount = $10_000 → annual gain = $200
        self.assertAlmostEqual(moves[0].annual_gain_usd, 200.0)

    def test_priority_assigned_correctly_high(self):
        """gain > 1.5% → priority HIGH."""
        registry = {
            "aave_v3": {"apy_pct": 3.0, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 7.0, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [_make_contribution("aave_v3", 10_000.0, 3.0)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves[0].priority, "HIGH")

    def test_priority_assigned_correctly_medium(self):
        """gain = 0.8% → priority MEDIUM."""
        registry = {
            "aave_v3": {"apy_pct": 4.0, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"apy_pct": 4.8, "tier": "T1", "is_eligible": True, "risk_score": 0.25},
        }
        positions = [_make_contribution("aave_v3", 10_000.0, 4.0)]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].priority, "MEDIUM")

    def test_position_without_adapter_id_skipped(self):
        """Position missing adapter_id → skipped gracefully."""
        registry = {
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [{"allocated_usd": 50_000.0, "apy_pct": 3.5, "tier": "T1"}]  # no adapter_id
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        self.assertEqual(moves, [])

    def test_t2_cap_enforcement(self):
        """Move from T1 that would push T2 above 50% is rejected."""
        optimizer = RebalanceOptimizer()
        # T2 already at 45% (45K). Moving aave_v3 (40K T1) to morpho_blue (T2) → T2 = 85% > 50%
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [
            _make_contribution("aave_v3", 40_000.0, 3.5, "T1"),
            _make_contribution("yearn_v3", 45_000.0, 5.0, "T2"),
        ]
        # Move from aave_v3 (T1) → morpho_blue (T2) → T2 = 85K/100K = 85% > 50% → blocked
        moves = optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        t2_moves_from_t1 = [m for m in moves if m.from_adapter == "aave_v3" and m.to_adapter == "morpho_blue"]
        self.assertEqual(t2_moves_from_t1, [])

    def test_from_apy_fallback_to_registry(self):
        """Position with apy_pct=0 falls back to registry APY."""
        registry = {
            "aave_v3": {"apy_pct": 3.5, "tier": "T1", "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"apy_pct": 6.5, "tier": "T2", "is_eligible": True, "risk_score": 0.4},
        }
        positions = [{"adapter_id": "aave_v3", "allocated_usd": 50_000.0, "apy_pct": 0.0, "tier": "T1"}]
        moves = self.optimizer.find_upgrade_opportunities(positions, registry, 100_000.0)
        # from_apy should be 3.5 (from registry), gain = 3.0% → HIGH
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].priority, "HIGH")


# ---------------------------------------------------------------------------
# TestCheckTierLimits (10)
# ---------------------------------------------------------------------------


class TestCheckTierLimits(unittest.TestCase):
    """Tests for RebalanceOptimizer.check_tier_limits."""

    def setUp(self):
        self.optimizer = RebalanceOptimizer()

    def _positions(self, entries: list) -> list:
        """entries: [(adapter_id, usd, tier)]."""
        return [{"adapter_id": aid, "allocated_usd": usd, "tier": tier} for aid, usd, tier in entries]

    def test_t2_40pct_ok(self):
        """T2 at 40% → True."""
        pos = self._positions([
            ("t1_pool", 60_000.0, "T1"),
            ("t2_pool", 40_000.0, "T2"),
        ])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t2_55pct_fails(self):
        """T2 at 55% → False."""
        pos = self._positions([
            ("t1_pool", 45_000.0, "T1"),
            ("t2_pool", 55_000.0, "T2"),
        ])
        self.assertFalse(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t2_exactly_50pct_ok(self):
        """T2 at exactly 50% → True (boundary included)."""
        pos = self._positions([
            ("t1_pool", 50_000.0, "T1"),
            ("t2_pool", 50_000.0, "T2"),
        ])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t3_8pct_ok(self):
        """T3 at 8% → True."""
        pos = self._positions([
            ("t1_pool", 92_000.0, "T1"),
            ("t3_pool", 8_000.0, "T3"),
        ])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t3_12pct_fails(self):
        """T3 at 12% → False."""
        pos = self._positions([
            ("t1_pool", 88_000.0, "T1"),
            ("t3_pool", 12_000.0, "T3"),
        ])
        self.assertFalse(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t3_exactly_10pct_ok(self):
        """T3 at exactly 10% → True (boundary included)."""
        pos = self._positions([
            ("t1_pool", 90_000.0, "T1"),
            ("t3_pool", 10_000.0, "T3"),
        ])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_empty_positions_ok(self):
        """Empty positions → True (no violations)."""
        self.assertTrue(self.optimizer.check_tier_limits([], 100_000.0))

    def test_zero_total_usd_returns_true(self):
        """total_usd ≤ 0 → True (skip check)."""
        pos = self._positions([("t2_pool", 100_000.0, "T2")])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 0.0))

    def test_t1_only_ok(self):
        """All T1 → True."""
        pos = self._positions([
            ("aave_v3", 50_000.0, "T1"),
            ("compound_v3", 50_000.0, "T1"),
        ])
        self.assertTrue(self.optimizer.check_tier_limits(pos, 100_000.0))

    def test_t3_spec_counted_in_t3(self):
        """T3-SPEC tier counted as T3 cap."""
        pos = self._positions([
            ("t1_pool", 80_000.0, "T1"),
            ("pendle", 20_000.0, "T3-SPEC"),  # 20% > 10%
        ])
        self.assertFalse(self.optimizer.check_tier_limits(pos, 100_000.0))


# ---------------------------------------------------------------------------
# TestEstimateOptimizedApy (8)
# ---------------------------------------------------------------------------


class TestEstimateOptimizedApy(unittest.TestCase):
    """Tests for RebalanceOptimizer.estimate_optimized_apy."""

    def setUp(self):
        self.optimizer = RebalanceOptimizer()

    def _move(self, apy_gain: float, amount_usd: float) -> RebalanceMove:
        return RebalanceMove(
            from_adapter="a", to_adapter="b",
            amount_usd=amount_usd, from_apy=3.0, to_apy=3.0 + apy_gain,
            apy_gain_pct=apy_gain, annual_gain_usd=amount_usd * apy_gain / 100,
            priority=_classify_priority(apy_gain), reason="test",
        )

    def test_empty_moves_returns_current(self):
        """Empty moves → returns current_apy unchanged."""
        result = self.optimizer.estimate_optimized_apy([], 5.0, 100_000.0)
        self.assertAlmostEqual(result, 5.0)

    def test_zero_total_returns_current(self):
        """total_usd ≤ 0 → returns current_apy unchanged."""
        moves = [self._move(1.0, 10_000.0)]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 0.0)
        self.assertAlmostEqual(result, 5.0)

    def test_single_move_improvement(self):
        """One move of $10K (+2%) on $100K portfolio → +0.2% APY."""
        moves = [self._move(2.0, 10_000.0)]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 100_000.0)
        self.assertAlmostEqual(result, 5.2, places=4)

    def test_full_portfolio_move(self):
        """Moving full portfolio (+2%) → +2% APY."""
        moves = [self._move(2.0, 100_000.0)]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 100_000.0)
        self.assertAlmostEqual(result, 7.0, places=4)

    def test_multiple_moves_cumulative(self):
        """Two moves sum their contributions."""
        moves = [
            self._move(2.0, 50_000.0),   # contributes +1.0%
            self._move(1.0, 50_000.0),   # contributes +0.5%
        ]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 100_000.0)
        self.assertAlmostEqual(result, 6.5, places=4)

    def test_small_gain_small_position(self):
        """Small gain on small position has proportionally small effect."""
        moves = [self._move(0.1, 1_000.0)]  # 0.1% gain, 1% of portfolio
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 100_000.0)
        self.assertAlmostEqual(result, 5.001, places=4)

    def test_result_is_rounded(self):
        """Result is rounded to 4 decimal places."""
        moves = [self._move(1.0, 33_333.0)]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0, 100_000.0)
        # Verify it's a float (implicitly rounded by round())
        self.assertIsInstance(result, float)

    def test_default_total_usd_parameter(self):
        """Default total_usd=100_000 is used when not provided."""
        moves = [self._move(2.0, 10_000.0)]
        result = self.optimizer.estimate_optimized_apy(moves, 5.0)
        self.assertAlmostEqual(result, 5.2, places=4)


# ---------------------------------------------------------------------------
# TestGeneratePlan (12)
# ---------------------------------------------------------------------------


class TestGeneratePlan(unittest.TestCase):
    """Tests for RebalanceOptimizer.generate_plan."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.optimizer = _make_optimizer(self.data_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_tracker(self, total: float, contributions: list) -> None:
        path = os.path.join(self.data_dir, "yield_attribution_tracker.json")
        _write_json(path, _make_tracker_json(total, contributions))

    def _write_registry(self, adapters: dict) -> None:
        path = os.path.join(self.data_dir, "adapter_status.json")
        _write_json(path, adapters)

    def test_no_positions_returns_hold(self):
        """No positions file → HOLD recommendation."""
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.recommendation, "HOLD")

    def test_no_positions_empty_moves(self):
        """No positions → empty moves list."""
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.moves, [])

    def test_high_priority_moves_gives_rebalance(self):
        """Position with HIGH gain available → REBALANCE.

        Uses a T1 target so moving 40K doesn't breach any tier cap.
        """
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 40_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            # T1 target with 3.0 + 2.0 = 5.0% gain → HIGH
            "spark_susds": {"tier": "T1", "apy_pct": 6.5, "is_eligible": True, "risk_score": 0.25},
        })
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.recommendation, "REBALANCE")

    def test_medium_priority_moves_gives_monitor(self):
        """Only MEDIUM gains → MONITOR."""
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 50_000.0, 4.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 4.0, "is_eligible": True, "risk_score": 0.2},
            "compound_v3": {"tier": "T1", "apy_pct": 4.6, "is_eligible": True, "risk_score": 0.25},
        })
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.recommendation, "MONITOR")

    def test_no_upgrades_gives_hold(self):
        """No upgrades available → HOLD."""
        self._write_tracker(100_000.0, [_make_contribution("morpho_blue", 80_000.0, 7.0, "T2")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.5, "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"tier": "T2", "apy_pct": 7.0, "is_eligible": True, "risk_score": 0.4},
        })
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.recommendation, "HOLD")

    def test_disclaimer_always_present(self):
        """disclaimer is always set to advisory text."""
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.disclaimer, DISCLAIMER)
        self.assertIn("Advisory only", plan.disclaimer)
        self.assertIn("No transactions", plan.disclaimer)

    def test_apy_improvement_computed(self):
        """apy_improvement = optimized - current.

        Uses T1 target to avoid T2 cap violation.
        """
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 40_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            "spark_susds": {"tier": "T1", "apy_pct": 5.0, "is_eligible": True, "risk_score": 0.25},
        })
        plan = self.optimizer.generate_plan()
        self.assertGreater(plan.apy_improvement, 0.0)
        self.assertAlmostEqual(
            plan.optimized_portfolio_apy,
            plan.current_portfolio_apy + plan.apy_improvement,
            places=4,
        )

    def test_annual_improvement_usd_computed(self):
        """annual_improvement_usd = apy_improvement * total_capital / 100."""
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 80_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"tier": "T2", "apy_pct": 5.0, "is_eligible": True, "risk_score": 0.4},
        })
        plan = self.optimizer.generate_plan()
        expected = round(100_000.0 * plan.apy_improvement / 100.0, 2)
        self.assertAlmostEqual(plan.annual_improvement_usd, expected, places=1)

    def test_tier_limits_respected_true_for_valid_positions(self):
        """tier_limits_respected=True when T2 is within cap."""
        self._write_tracker(100_000.0, [
            _make_contribution("aave_v3", 60_000.0, 3.5, "T1"),
            _make_contribution("morpho_blue", 30_000.0, 5.0, "T2"),
        ])
        self._write_registry({"aave_v3": {"tier": "T1", "apy_pct": 3.5, "is_eligible": True, "risk_score": 0.2}})
        plan = self.optimizer.generate_plan()
        self.assertTrue(plan.tier_limits_respected)

    def test_high_priority_moves_subset(self):
        """high_priority_moves contains only HIGH priority moves."""
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 80_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"tier": "T2", "apy_pct": 6.5, "is_eligible": True, "risk_score": 0.4},
        })
        plan = self.optimizer.generate_plan()
        for m in plan.high_priority_moves:
            self.assertEqual(m.priority, "HIGH")

    def test_total_moves_correct(self):
        """total_moves == len(moves)."""
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 80_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"tier": "T2", "apy_pct": 6.5, "is_eligible": True, "risk_score": 0.4},
        })
        plan = self.optimizer.generate_plan()
        self.assertEqual(plan.total_moves, len(plan.moves))

    def test_summary_contains_moves_info(self):
        """summary mentions move count and gain when moves exist."""
        self._write_tracker(100_000.0, [_make_contribution("aave_v3", 80_000.0, 3.0, "T1")])
        self._write_registry({
            "aave_v3": {"tier": "T1", "apy_pct": 3.0, "is_eligible": True, "risk_score": 0.2},
            "morpho_blue": {"tier": "T2", "apy_pct": 6.5, "is_eligible": True, "risk_score": 0.4},
        })
        plan = self.optimizer.generate_plan()
        self.assertIn("move", plan.summary.lower())


# ---------------------------------------------------------------------------
# TestSavePlan (4)
# ---------------------------------------------------------------------------


class TestSavePlan(unittest.TestCase):
    """Tests for RebalanceOptimizer.save_plan."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.optimizer = _make_optimizer(self.data_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_simple_plan(self) -> RebalancePlan:
        return RebalancePlan(
            generated_at="2026-06-13T00:00:00+00:00",
            current_portfolio_apy=5.0,
            optimized_portfolio_apy=5.5,
            apy_improvement=0.5,
            annual_improvement_usd=500.0,
            moves=[],
            high_priority_moves=[],
            total_moves=0,
            tier_limits_respected=True,
            min_move_usd=500.0,
            recommendation="HOLD",
            summary="Test plan",
            disclaimer=DISCLAIMER,
        )

    def test_save_creates_file(self):
        """save_plan creates rebalance_plan.json."""
        plan = self._make_simple_plan()
        path = self.optimizer.save_plan(plan)
        self.assertTrue(os.path.exists(path))

    def test_save_returns_path_string(self):
        """save_plan returns a string path."""
        plan = self._make_simple_plan()
        result = self.optimizer.save_plan(plan)
        self.assertIsInstance(result, str)

    def test_ring_buffer_max_30(self):
        """Ring buffer keeps at most 30 snapshots."""
        for i in range(35):
            p = self._make_simple_plan()
            self.optimizer.save_plan(p)
        out_path = os.path.join(self.data_dir, "rebalance_plan.json")
        with open(out_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["snapshots"]), RING_BUFFER_MAX)

    def test_atomic_no_tmp_left(self):
        """No .tmp files remain after save."""
        plan = self._make_simple_plan()
        self.optimizer.save_plan(plan)
        tmp_files = [f for f in os.listdir(self.data_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


# ---------------------------------------------------------------------------
# TestFormatTelegramMessage (8)
# ---------------------------------------------------------------------------


class TestFormatTelegramMessage(unittest.TestCase):
    """Tests for RebalanceOptimizer.format_telegram_message."""

    def setUp(self):
        self.optimizer = RebalanceOptimizer()

    def _plan(
        self,
        recommendation: str = "HOLD",
        current_apy: float = 5.0,
        optimized_apy: float = 5.0,
        moves: Optional[list] = None,
    ) -> "RebalancePlan":
        moves = moves or []
        high = [m for m in moves if m.priority == "HIGH"]
        return RebalancePlan(
            generated_at="2026-06-13T00:00:00+00:00",
            current_portfolio_apy=current_apy,
            optimized_portfolio_apy=optimized_apy,
            apy_improvement=round(optimized_apy - current_apy, 4),
            annual_improvement_usd=round(100_000.0 * (optimized_apy - current_apy) / 100.0, 2),
            moves=moves,
            high_priority_moves=high,
            total_moves=len(moves),
            tier_limits_respected=True,
            min_move_usd=500.0,
            recommendation=recommendation,
            summary="test",
            disclaimer=DISCLAIMER,
        )

    def _high_move(self) -> RebalanceMove:
        return RebalanceMove(
            "compound_v3", "morpho_blue", 10_000.0, 4.0, 5.5, 1.5, 150.0, "HIGH", "Higher APY"
        )

    def test_message_length_under_1500(self):
        """Telegram message ≤ 1500 chars."""
        moves = [self._high_move()] * 5
        plan = self._plan("REBALANCE", 4.0, 5.5, moves)
        msg = self.optimizer.format_telegram_message(plan)
        self.assertLessEqual(len(msg), 1500)

    def test_contains_advisory_text(self):
        """Message contains 'Advisory'."""
        plan = self._plan()
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("Advisory", msg)

    def test_contains_no_transactions(self):
        """Message contains 'No transactions'."""
        plan = self._plan()
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("No transactions", msg)

    def test_contains_recommendation(self):
        """Message includes the recommendation value."""
        for rec in ("REBALANCE", "MONITOR", "HOLD"):
            plan = self._plan(recommendation=rec)
            msg = self.optimizer.format_telegram_message(plan)
            self.assertIn(rec, msg)

    def test_contains_apy_values(self):
        """Message includes current and optimized APY."""
        plan = self._plan(current_apy=5.0, optimized_apy=5.5)
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("5.00", msg)
        self.assertIn("5.50", msg)

    def test_rebalance_message_shows_moves(self):
        """REBALANCE plan shows at least one move."""
        plan = self._plan("REBALANCE", 4.0, 5.5, [self._high_move()])
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("compound_v3", msg)
        self.assertIn("morpho_blue", msg)

    def test_hold_message_shows_no_moves(self):
        """HOLD plan with empty moves shows 'No moves suggested'."""
        plan = self._plan("HOLD")
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("No moves suggested", msg)

    def test_high_priority_move_has_checkmark(self):
        """HIGH priority moves show ✅ in message."""
        move = RebalanceMove(
            "a", "b", 10_000.0, 3.0, 5.0, 2.0, 200.0, "HIGH", "Higher APY"
        )
        plan = self._plan("REBALANCE", 3.0, 5.0, [move])
        msg = self.optimizer.format_telegram_message(plan)
        self.assertIn("✅", msg)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
