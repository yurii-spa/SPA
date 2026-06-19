"""tests/test_rebalancer_production.py — CRIT-002 Production tests for
spa_core/paper_trading/rebalancer.py and position_tracker.py

MP-1386 Sprint v10.2

Coverage:
  rebalancer.py — Rebalancer
  ───────────────────────────
  - Default thresholds / construction
  - compute_actions: EXIT / ENTER / INCREASE / DECREASE / HOLD (skipped)
  - compute_actions: priority ordering (EXIT > ENTER > INCREASE > DECREASE)
  - compute_actions: union of keys, missing sides treated as 0
  - compute_dollar_moves: raw amount, per-move cap, capped correctly
  - estimate_rebalance_cost: total_moves, cost_bps, empty actions
  - record_rebalance: atomic write, ring-buffer cap, schema fields
  - needs_rebalance: True above threshold, False below, boundary exactly
  - RebalanceAction.to_dict: dollar_amount absent when None

  position_tracker.py — PositionTracker
  ───────────────────────────────────────
  - record_position: creates file, correct fields
  - record_position: idempotent per date
  - record_position: apy_weighted computed when apy_map supplied
  - record_position: apy_weighted absent without apy_map
  - record_position: NaN / negative allocation weights filtered
  - get_history: returns [] for missing file, list after write
  - get_current_weights: {} when empty, latest allocation
  - compute_drift: no drift when weights match, overweight/underweight
  - compute_drift: returns {} when no history
  - compute_drift: handles asymmetric key sets
  - get_concentration_metric: empty weights, single adapter, multi HHI
  - ring-buffer: enforces HISTORY_MAX cap (365)
  - _atomic_write: no leftover tmp files
  - date_str override
  - equity edge cases: zero, large value
  - top_adapter field set correctly

Run:
    python3 -m pytest tests/test_rebalancer_production.py -v
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.rebalancer import (
    ACTION_DECREASE,
    ACTION_ENTER,
    ACTION_EXIT,
    ACTION_HOLD,
    ACTION_INCREASE,
    HISTORY_FILENAME,
    HISTORY_MAX,
    RebalanceAction,
    Rebalancer,
)
from spa_core.paper_trading.position_tracker import (
    HISTORY_FILENAME as PT_HISTORY_FILENAME,
    HISTORY_MAX as PT_HISTORY_MAX,
    PositionTracker,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _tmp() -> str:
    """Return path to a fresh temp directory (auto-cleaned by OS after test)."""
    return tempfile.mkdtemp()


def _make_rb(**kwargs) -> Rebalancer:
    return Rebalancer(**kwargs)


def _action(adapter_id: str, cur: float, tgt: float,
            act: str, priority: int,
            dollar_amount: float | None = None) -> RebalanceAction:
    return RebalanceAction(
        adapter_id=adapter_id,
        current_weight=cur,
        target_weight=tgt,
        delta_weight=round(tgt - cur, 8),
        action=act,
        priority=priority,
        dollar_amount=dollar_amount,
    )


def _make_pt() -> PositionTracker:
    return PositionTracker()


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — RebalanceAction dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestRebalanceAction:
    def test_fields_accessible(self):
        a = _action("aave_v3", 0.40, 0.35, ACTION_DECREASE, 4)
        assert a.adapter_id == "aave_v3"
        assert a.current_weight == 0.40
        assert a.target_weight == 0.35
        assert a.delta_weight == pytest.approx(-0.05)
        assert a.action == ACTION_DECREASE
        assert a.priority == 4

    def test_dollar_amount_default_none(self):
        a = _action("aave_v3", 0.40, 0.35, ACTION_DECREASE, 4)
        assert a.dollar_amount is None

    def test_to_dict_omits_dollar_amount_when_none(self):
        a = _action("aave_v3", 0.40, 0.35, ACTION_DECREASE, 4)
        d = a.to_dict()
        assert "dollar_amount" not in d

    def test_to_dict_includes_dollar_amount_when_set(self):
        a = _action("aave_v3", 0.40, 0.35, ACTION_DECREASE, 4,
                    dollar_amount=5_000.0)
        d = a.to_dict()
        assert d["dollar_amount"] == 5_000.0

    def test_to_dict_contains_required_keys(self):
        a = _action("x", 0.2, 0.3, ACTION_INCREASE, 3)
        d = a.to_dict()
        for key in ("adapter_id", "current_weight", "target_weight",
                    "delta_weight", "action", "priority"):
            assert key in d


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Rebalancer defaults
# ═══════════════════════════════════════════════════════════════════════════════

class TestRebalancerDefaults:
    def test_default_threshold_is_2_pct(self):
        rb = _make_rb()
        assert rb.rebalance_threshold_pct == 2.0

    def test_default_max_single_move_is_10_pct(self):
        rb = _make_rb()
        assert rb.max_single_move_pct == 10.0

    def test_custom_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=5.0)
        assert rb.rebalance_threshold_pct == 5.0

    def test_custom_max_move(self):
        rb = _make_rb(max_single_move_pct=20.0)
        assert rb.max_single_move_pct == 20.0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — compute_actions: action classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeActions:
    def test_exit_when_target_zero(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"aave_v3": 0.40},
            {"aave_v3": 0.0},
            equity=100_000,
        )
        assert len(actions) == 1
        assert actions[0].action == ACTION_EXIT

    def test_enter_when_current_zero(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {},
            {"aave_v3": 0.40},
            equity=100_000,
        )
        assert len(actions) == 1
        assert actions[0].action == ACTION_ENTER

    def test_increase_when_target_above_threshold(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"aave_v3": 0.30},
            {"aave_v3": 0.35},   # +5pp > 2pp threshold
            equity=100_000,
        )
        assert len(actions) == 1
        assert actions[0].action == ACTION_INCREASE

    def test_decrease_when_target_below_threshold(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"aave_v3": 0.40},
            {"aave_v3": 0.34},   # -6pp > 2pp threshold
            equity=100_000,
        )
        assert len(actions) == 1
        assert actions[0].action == ACTION_DECREASE

    def test_hold_excluded_from_results(self):
        """Drift below threshold must not appear in results."""
        rb = _make_rb()
        actions = rb.compute_actions(
            {"aave_v3": 0.40},
            {"aave_v3": 0.41},   # +1pp < 2pp → HOLD
            equity=100_000,
        )
        assert len(actions) == 0

    def test_missing_current_key_treated_as_zero_enter(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {},
            {"new_proto": 0.30},
            equity=100_000,
        )
        assert actions[0].action == ACTION_ENTER

    def test_missing_target_key_treated_as_zero_exit(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"old_proto": 0.30},
            {},
            equity=100_000,
        )
        assert actions[0].action == ACTION_EXIT

    def test_sorted_largest_delta_first(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30, "b": 0.30},
            {"a": 0.60, "b": 0.10},  # a +30pp, b -20pp
            equity=100_000,
        )
        # Both above threshold; largest |delta| first
        assert abs(actions[0].delta_weight) >= abs(actions[1].delta_weight)

    def test_delta_weight_set_correctly(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.50},
            equity=100_000,
        )
        assert actions[0].delta_weight == pytest.approx(0.20)

    def test_priority_exit_before_enter(self):
        """EXIT has priority 1, ENTER has priority 2 — EXIT sorts first on equal |delta|."""
        rb = _make_rb()
        actions = rb.compute_actions(
            {"exit_me": 0.30, "enter_me": 0.0},
            {"exit_me": 0.0,  "enter_me": 0.30},
            equity=100_000,
        )
        action_types = [a.action for a in actions]
        assert action_types.index(ACTION_EXIT) < action_types.index(ACTION_ENTER)

    def test_multi_adapter_all_types(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.50, "b": 0.30, "c": 0.0},
            {"a": 0.0,  "b": 0.55, "c": 0.40},
            equity=100_000,
        )
        types = {a.action for a in actions}
        assert ACTION_EXIT in types
        assert ACTION_INCREASE in types
        assert ACTION_ENTER in types


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — compute_dollar_moves
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeDollarMoves:
    def test_dollar_amount_set_on_actions(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.60},
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount is not None

    def test_dollar_amount_equals_delta_times_equity(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.60},  # delta = 0.30
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        # raw = 0.30 * 100_000 = 30_000 but capped at 10% = 10_000
        assert actions[0].dollar_amount == pytest.approx(10_000.0)

    def test_per_move_cap_applied(self):
        rb = _make_rb(max_single_move_pct=5.0)  # 5% cap
        actions = rb.compute_actions(
            {"a": 0.0},
            {"a": 0.80},  # wants 80% = $80K move
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount == pytest.approx(5_000.0)  # capped at 5%

    def test_small_move_not_capped(self):
        rb = _make_rb(max_single_move_pct=10.0)
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.35},  # 5pp = $5K on $100K
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount == pytest.approx(5_000.0)

    def test_returns_same_list_for_chaining(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.55},
            equity=100_000,
        )
        returned = rb.compute_dollar_moves(actions, 100_000)
        assert returned is actions

    def test_empty_actions_no_crash(self):
        rb = _make_rb()
        result = rb.compute_dollar_moves([], 100_000)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — estimate_rebalance_cost
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateRebalanceCost:
    def test_empty_actions_returns_zero(self):
        rb = _make_rb()
        cost = rb.estimate_rebalance_cost([])
        assert cost["total_moves_usd"] == 0.0
        assert cost["total_cost_usd"] == 0.0
        assert cost["action_count"] == 0

    def test_cost_bps_matches_slippage(self):
        """10 bps slippage × $10K move = $10 cost."""
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.35},
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        cost = rb.estimate_rebalance_cost(actions, slippage_bps=10.0)
        assert cost["total_cost_usd"] == pytest.approx(
            cost["total_moves_usd"] * 10 / 10_000, rel=1e-3
        )

    def test_action_count_correct(self):
        rb = _make_rb()
        actions = rb.compute_actions(
            {"a": 0.0, "b": 0.0},
            {"a": 0.30, "b": 0.40},
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        cost = rb.estimate_rebalance_cost(actions)
        assert cost["action_count"] == 2

    def test_cost_bps_field_present(self):
        rb = _make_rb()
        cost = rb.estimate_rebalance_cost([])
        assert "cost_bps" in cost


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — needs_rebalance
# ═══════════════════════════════════════════════════════════════════════════════

class TestNeedsRebalance:
    def test_true_when_drift_exceeds_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        assert rb.needs_rebalance(
            {"aave_v3": 0.40},
            {"aave_v3": 0.35},  # -5pp > 2pp
        ) is True

    def test_false_when_drift_below_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        assert rb.needs_rebalance(
            {"aave_v3": 0.40},
            {"aave_v3": 0.41},  # +1pp < 2pp
        ) is False

    def test_false_when_identical_weights(self):
        rb = _make_rb()
        assert rb.needs_rebalance(
            {"a": 0.30, "b": 0.70},
            {"a": 0.30, "b": 0.70},
        ) is False

    def test_true_for_new_adapter_in_target(self):
        rb = _make_rb()
        assert rb.needs_rebalance(
            {"a": 0.30},
            {"a": 0.30, "b": 0.40},   # b missing from current → drift = 40pp
        ) is True

    def test_true_for_adapter_exiting(self):
        rb = _make_rb()
        assert rb.needs_rebalance(
            {"a": 0.30, "b": 0.40},
            {"a": 0.30},             # b removed → drift = -40pp
        ) is True

    def test_empty_both_returns_false(self):
        rb = _make_rb()
        assert rb.needs_rebalance({}, {}) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7 — record_rebalance (atomic write + ring-buffer)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordRebalance:
    def test_creates_history_file(self):
        rb = _make_rb()
        d = _tmp()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.55},
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        rb.record_rebalance(actions, equity=100_000, data_dir=d)
        assert (Path(d) / HISTORY_FILENAME).exists()

    def test_history_entry_has_required_fields(self):
        rb = _make_rb()
        d = _tmp()
        actions = rb.compute_actions(
            {"a": 0.30},
            {"a": 0.55},
            equity=100_000,
        )
        rb.compute_dollar_moves(actions, 100_000)
        rb.record_rebalance(actions, equity=100_000, data_dir=d)
        history = json.loads((Path(d) / HISTORY_FILENAME).read_text())
        assert len(history) == 1
        entry = history[0]
        for key in ("date", "equity", "actions_count", "total_moves_usd",
                    "cost_usd", "actions"):
            assert key in entry, f"Missing key: {key}"

    def test_history_equity_recorded(self):
        rb = _make_rb()
        d = _tmp()
        actions = rb.compute_actions({"a": 0.0}, {"a": 0.30}, equity=99_000)
        rb.compute_dollar_moves(actions, 99_000)
        rb.record_rebalance(actions, equity=99_000, data_dir=d)
        history = json.loads((Path(d) / HISTORY_FILENAME).read_text())
        assert history[0]["equity"] == pytest.approx(99_000.0)

    def test_multiple_entries_accumulate(self):
        rb = _make_rb()
        d = _tmp()
        for equity in (100_000, 101_000, 102_000):
            actions = rb.compute_actions({"a": 0.0}, {"a": 0.30}, equity=equity)
            rb.compute_dollar_moves(actions, equity)
            rb.record_rebalance(actions, equity=equity, data_dir=d)
        history = json.loads((Path(d) / HISTORY_FILENAME).read_text())
        assert len(history) == 3

    def test_ring_buffer_respects_history_max(self):
        rb = _make_rb()
        d = _tmp()
        # Write HISTORY_MAX + 5 entries
        for i in range(HISTORY_MAX + 5):
            actions = rb.compute_actions(
                {"a": 0.0}, {"a": 0.30}, equity=100_000 + i
            )
            rb.compute_dollar_moves(actions, 100_000 + i)
            rb.record_rebalance(actions, equity=100_000 + i, data_dir=d)
        history = json.loads((Path(d) / HISTORY_FILENAME).read_text())
        assert len(history) == HISTORY_MAX

    def test_no_leftover_tmp_files(self):
        rb = _make_rb()
        d = _tmp()
        actions = rb.compute_actions({"a": 0.0}, {"a": 0.30}, equity=100_000)
        rb.compute_dollar_moves(actions, 100_000)
        rb.record_rebalance(actions, equity=100_000, data_dir=d)
        tmp_files = list(Path(d).glob(".rebalance_history_*.tmp"))
        assert len(tmp_files) == 0

    def test_actions_recorded_in_entry(self):
        rb = _make_rb()
        d = _tmp()
        actions = rb.compute_actions({"a": 0.0}, {"a": 0.30}, equity=100_000)
        rb.compute_dollar_moves(actions, 100_000)
        rb.record_rebalance(actions, equity=100_000, data_dir=d)
        history = json.loads((Path(d) / HISTORY_FILENAME).read_text())
        assert history[0]["actions_count"] == 1
        assert history[0]["actions"][0]["adapter_id"] == "a"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 8 — PositionTracker.record_position
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordPosition:
    def test_creates_history_file(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 0.60, "compound_v3": 0.40}, 100_000, data_dir=d)
        assert (Path(d) / PT_HISTORY_FILENAME).exists()

    def test_snapshot_has_required_fields(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"aave_v3": 0.60, "compound_v3": 0.40}, 100_000, data_dir=d
        )
        for key in ("date", "equity", "allocation", "timestamp",
                    "top_adapter", "adapter_count"):
            assert key in snap

    def test_equity_stored_correctly(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position({"aave_v3": 1.0}, 99_750.50, data_dir=d)
        assert snap["equity"] == pytest.approx(99_750.50, rel=1e-4)

    def test_adapter_count_correct(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"a": 0.30, "b": 0.40, "c": 0.30}, 100_000, data_dir=d
        )
        assert snap["adapter_count"] == 3

    def test_top_adapter_is_largest_weight(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"small": 0.10, "big": 0.70, "medium": 0.20}, 100_000, data_dir=d
        )
        assert snap["top_adapter"] == "big"

    def test_apy_weighted_present_when_apy_map_supplied(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"aave_v3": 0.60, "compound_v3": 0.40},
            100_000,
            apy_map={"aave_v3": 4.0, "compound_v3": 5.0},
            data_dir=d,
        )
        assert "apy_weighted" in snap
        # 0.6 * 4.0 + 0.4 * 5.0 = 4.4
        assert snap["apy_weighted"] == pytest.approx(4.4, rel=1e-4)

    def test_apy_weighted_absent_without_apy_map(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position({"aave_v3": 1.0}, 100_000, data_dir=d)
        assert "apy_weighted" not in snap

    def test_idempotent_same_date(self):
        """Calling record_position twice for same date returns existing snapshot."""
        pt = _make_pt()
        d = _tmp()
        snap1 = pt.record_position(
            {"aave_v3": 0.60}, 100_000, date_str="2026-06-19", data_dir=d
        )
        snap2 = pt.record_position(
            {"aave_v3": 0.80},  # different allocation — should be ignored
            110_000,
            date_str="2026-06-19",
            data_dir=d,
        )
        history = pt.get_history(d)
        assert len(history) == 1
        assert snap2["equity"] == pytest.approx(100_000.0)  # first write wins

    def test_different_dates_both_recorded(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 1.0}, 100_000, date_str="2026-06-18", data_dir=d)
        pt.record_position({"a": 1.0}, 101_000, date_str="2026-06-19", data_dir=d)
        history = pt.get_history(d)
        assert len(history) == 2

    def test_nan_weight_filtered(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"good": 0.80, "bad": float("nan")}, 100_000, data_dir=d
        )
        assert "bad" not in snap["allocation"]
        assert "good" in snap["allocation"]

    def test_negative_weight_filtered(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position(
            {"valid": 0.70, "neg": -0.10}, 100_000, data_dir=d
        )
        assert "neg" not in snap["allocation"]

    def test_non_dict_allocation_raises(self):
        pt = _make_pt()
        d = _tmp()
        with pytest.raises(ValueError, match="allocation must be a dict"):
            pt.record_position([0.30, 0.70], 100_000, data_dir=d)

    def test_nan_equity_raises(self):
        pt = _make_pt()
        d = _tmp()
        with pytest.raises(ValueError, match="equity must be a real number"):
            pt.record_position({"a": 1.0}, float("nan"), data_dir=d)

    def test_zero_equity_allowed(self):
        """Zero equity is a valid (if unusual) state — should not raise."""
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position({"a": 1.0}, 0.0, data_dir=d)
        assert snap["equity"] == 0.0

    def test_date_str_override(self):
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position({"a": 1.0}, 100_000,
                                   date_str="2025-01-15", data_dir=d)
        assert snap["date"] == "2025-01-15"

    def test_timestamp_is_iso8601(self):
        import datetime
        pt = _make_pt()
        d = _tmp()
        snap = pt.record_position({"a": 1.0}, 100_000, data_dir=d)
        ts = snap["timestamp"]
        # Should parse without raising
        datetime.datetime.fromisoformat(ts)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 9 — get_history / get_current_weights
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetHistoryAndCurrentWeights:
    def test_get_history_empty_when_no_file(self):
        pt = _make_pt()
        d = _tmp()
        assert pt.get_history(d) == []

    def test_get_history_returns_list(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 1.0}, 100_000, data_dir=d)
        history = pt.get_history(d)
        assert isinstance(history, list)

    def test_get_history_single_entry(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 0.40, "b": 0.60}, 100_000, data_dir=d)
        assert len(pt.get_history(d)) == 1

    def test_get_history_multiple_entries(self):
        pt = _make_pt()
        d = _tmp()
        for i in range(5):
            pt.record_position({"a": 1.0}, 100_000 + i,
                                date_str=f"2026-06-{10+i:02d}", data_dir=d)
        assert len(pt.get_history(d)) == 5

    def test_get_history_corrupt_json_returns_empty(self):
        d = _tmp()
        (Path(d) / PT_HISTORY_FILENAME).write_text("NOT JSON{{{")
        pt = _make_pt()
        assert pt.get_history(d) == []

    def test_get_current_weights_empty_when_no_history(self):
        pt = _make_pt()
        d = _tmp()
        assert pt.get_current_weights(d) == {}

    def test_get_current_weights_returns_latest(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"old": 1.0}, 100_000, date_str="2026-06-18", data_dir=d)
        pt.record_position({"new": 1.0}, 101_000, date_str="2026-06-19", data_dir=d)
        weights = pt.get_current_weights(d)
        assert "new" in weights
        assert "old" not in weights

    def test_ring_buffer_enforces_max(self):
        pt = _make_pt()
        d = _tmp()
        for i in range(PT_HISTORY_MAX + 10):
            # Use unique dates to bypass idempotency
            year = 2024 + i // 365
            day_of_year = (i % 365) + 1
            import datetime
            fake_date = (datetime.date(year, 1, 1) +
                         datetime.timedelta(days=day_of_year - 1)).isoformat()
            pt.record_position({"a": 1.0}, 100_000 + i,
                                date_str=fake_date, data_dir=d)
        assert len(pt.get_history(d)) == PT_HISTORY_MAX


# ═══════════════════════════════════════════════════════════════════════════════
# Section 10 — compute_drift
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeDrift:
    def test_returns_empty_when_no_history(self):
        pt = _make_pt()
        d = _tmp()
        assert pt.compute_drift({"aave_v3": 0.50}, data_dir=d) == {}

    def test_zero_drift_when_weights_match(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 0.60, "compound_v3": 0.40},
                            100_000, data_dir=d)
        drift = pt.compute_drift({"aave_v3": 0.60, "compound_v3": 0.40}, data_dir=d)
        for v in drift.values():
            assert abs(v) < 1e-4

    def test_overweight_positive_drift(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 0.70}, 100_000, data_dir=d)
        drift = pt.compute_drift({"aave_v3": 0.50}, data_dir=d)
        # current 70% vs target 50% → drift = +20pp
        assert drift["aave_v3"] == pytest.approx(20.0, rel=1e-3)

    def test_underweight_negative_drift(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 0.30}, 100_000, data_dir=d)
        drift = pt.compute_drift({"aave_v3": 0.50}, data_dir=d)
        # current 30% vs target 50% → drift = -20pp
        assert drift["aave_v3"] == pytest.approx(-20.0, rel=1e-3)

    def test_asymmetric_keys_included(self):
        """Adapters in current but not in target, and vice versa, both appear."""
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"only_current": 0.50}, 100_000, data_dir=d)
        drift = pt.compute_drift({"only_target": 0.50}, data_dir=d)
        assert "only_current" in drift
        assert "only_target" in drift


# ═══════════════════════════════════════════════════════════════════════════════
# Section 11 — get_concentration_metric
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetConcentrationMetric:
    def test_returns_zero_dict_when_no_history(self):
        pt = _make_pt()
        d = _tmp()
        m = pt.get_concentration_metric(d)
        assert m["max_single_pct"] == 0.0
        assert m["hhi"] == 0.0
        assert m["adapter_count"] == 0

    def test_single_adapter_max_single_100(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 1.0}, 100_000, data_dir=d)
        m = pt.get_concentration_metric(d)
        assert m["max_single_pct"] == pytest.approx(100.0)

    def test_single_adapter_hhi_is_one(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"aave_v3": 1.0}, 100_000, data_dir=d)
        m = pt.get_concentration_metric(d)
        assert m["hhi"] == pytest.approx(1.0, rel=1e-4)

    def test_two_equal_adapters_hhi(self):
        """Two equal weights → HHI = 0.5^2 + 0.5^2 = 0.5."""
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 0.50, "b": 0.50}, 100_000, data_dir=d)
        m = pt.get_concentration_metric(d)
        assert m["hhi"] == pytest.approx(0.5, rel=1e-4)

    def test_adapter_count_correct(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 0.30, "b": 0.40, "c": 0.30}, 100_000, data_dir=d)
        m = pt.get_concentration_metric(d)
        assert m["adapter_count"] == 3

    def test_top3_pct_with_four_adapters(self):
        """top3_pct should sum only the top-3 largest weights."""
        pt = _make_pt()
        d = _tmp()
        pt.record_position(
            {"a": 0.40, "b": 0.30, "c": 0.20, "d": 0.10}, 100_000, data_dir=d
        )
        m = pt.get_concentration_metric(d)
        # Top 3 = 40 + 30 + 20 = 90%
        assert m["top3_pct"] == pytest.approx(90.0, rel=1e-3)

    def test_all_fields_present(self):
        pt = _make_pt()
        d = _tmp()
        pt.record_position({"a": 1.0}, 100_000, data_dir=d)
        m = pt.get_concentration_metric(d)
        for key in ("max_single_pct", "top3_pct", "hhi", "adapter_count"):
            assert key in m
