"""tests/test_rebalancer.py — Portfolio Rebalancer test suite.

Covers RebalanceAction, Rebalancer.compute_actions, compute_dollar_moves,
estimate_rebalance_cost, record_rebalance, needs_rebalance.

Run:
    python3 -m pytest tests/test_rebalancer.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make spa_core importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.rebalancer import (
    ACTION_DECREASE,
    ACTION_ENTER,
    ACTION_EXIT,
    ACTION_HOLD,
    ACTION_INCREASE,
    HISTORY_MAX,
    RebalanceAction,
    Rebalancer,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_rb(**kwargs) -> Rebalancer:
    """Construct Rebalancer with optional overrides."""
    return Rebalancer(**kwargs)


def _tmp_data_dir():
    """Return a fresh temporary directory (caller must clean up)."""
    return tempfile.mkdtemp()


# ─── RebalanceAction ─────────────────────────────────────────────────────────

class TestRebalanceAction:
    def test_fields_accessible(self):
        a = RebalanceAction(
            adapter_id="aave_v3",
            current_weight=0.40,
            target_weight=0.35,
            delta_weight=-0.05,
            action=ACTION_DECREASE,
            priority=4,
        )
        assert a.adapter_id == "aave_v3"
        assert a.current_weight == 0.40
        assert a.target_weight == 0.35
        assert a.delta_weight == -0.05
        assert a.action == ACTION_DECREASE
        assert a.priority == 4
        assert a.dollar_amount is None  # default

    def test_dollar_amount_settable(self):
        a = RebalanceAction("x", 0.1, 0.2, 0.1, ACTION_INCREASE, 3)
        a.dollar_amount = 5000.0
        assert a.dollar_amount == 5000.0

    def test_to_dict_excludes_none_dollar_amount(self):
        a = RebalanceAction("x", 0.1, 0.2, 0.1, ACTION_INCREASE, 3)
        d = a.to_dict()
        assert "dollar_amount" not in d

    def test_to_dict_includes_dollar_amount_when_set(self):
        a = RebalanceAction("x", 0.1, 0.2, 0.1, ACTION_INCREASE, 3)
        a.dollar_amount = 1234.56
        d = a.to_dict()
        assert d["dollar_amount"] == 1234.56

    def test_to_dict_has_all_required_keys(self):
        a = RebalanceAction("aave_v3", 0.30, 0.40, 0.10, ACTION_INCREASE, 3)
        a.dollar_amount = 10000.0
        d = a.to_dict()
        for key in ("adapter_id", "current_weight", "target_weight",
                    "delta_weight", "action", "priority", "dollar_amount"):
            assert key in d


# ─── Rebalancer.needs_rebalance ───────────────────────────────────────────────

class TestNeedsRebalance:
    def test_needs_rebalance_false_when_identical(self):
        rb = _make_rb()
        w = {"aave_v3": 0.40, "compound_v3": 0.35, "cash": 0.25}
        assert rb.needs_rebalance(w, w) is False

    def test_needs_rebalance_false_within_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40}
        tgt = {"aave_v3": 0.419}  # 1.9% drift — below 2%
        assert rb.needs_rebalance(cur, tgt) is False

    def test_needs_rebalance_true_above_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40}
        tgt = {"aave_v3": 0.43}   # 3% drift — above 2%
        assert rb.needs_rebalance(cur, tgt) is True

    def test_needs_rebalance_true_on_new_adapter(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40}
        tgt = {"aave_v3": 0.40, "morpho": 0.05}  # morpho goes 0→5% = 5% drift
        assert rb.needs_rebalance(cur, tgt) is True

    def test_needs_rebalance_true_on_exiting_adapter(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40, "morpho": 0.10}
        tgt = {"aave_v3": 0.40}   # morpho exits (0.10 drift)
        assert rb.needs_rebalance(cur, tgt) is True

    def test_needs_rebalance_exact_threshold_is_true(self):
        """Drift exactly equal to threshold should trigger rebalance."""
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"a": 0.40}
        tgt = {"a": 0.42}  # exactly 2%
        assert rb.needs_rebalance(cur, tgt) is True

    def test_needs_rebalance_empty_weights(self):
        rb = _make_rb()
        assert rb.needs_rebalance({}, {}) is False

    def test_needs_rebalance_custom_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=5.0)
        cur = {"a": 0.40}
        tgt = {"a": 0.44}   # 4% drift — below 5% custom threshold
        assert rb.needs_rebalance(cur, tgt) is False


# ─── Rebalancer.compute_actions ──────────────────────────────────────────────

class TestComputeActions:
    def test_no_rebalance_within_threshold(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40, "compound_v3": 0.35, "cash": 0.25}
        tgt = {"aave_v3": 0.41, "compound_v3": 0.35, "cash": 0.24}  # 1% drift
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert actions == []

    def test_increase_action_generated(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.30}
        tgt = {"aave_v3": 0.40}  # +10%
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].action == ACTION_INCREASE
        assert actions[0].adapter_id == "aave_v3"
        assert actions[0].delta_weight == pytest.approx(0.10, abs=1e-8)

    def test_decrease_action_generated(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40}
        tgt = {"aave_v3": 0.30}  # -10%
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].action == ACTION_DECREASE
        assert actions[0].delta_weight == pytest.approx(-0.10, abs=1e-8)

    def test_exit_action_when_target_zero(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40}
        tgt = {"aave_v3": 0.0}   # EXIT — full withdrawal
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].action == ACTION_EXIT

    def test_enter_action_when_current_zero(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {}
        tgt = {"morpho": 0.10}   # ENTER — new position
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].action == ACTION_ENTER
        assert actions[0].adapter_id == "morpho"

    def test_exit_takes_priority_over_enter_in_sort(self):
        """When exit and enter have same |delta|, EXIT sorts before ENTER."""
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"a": 0.10, "b": 0.0}
        tgt = {"a": 0.0,  "b": 0.10}
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert actions[0].action == ACTION_EXIT
        assert actions[1].action == ACTION_ENTER

    def test_actions_sorted_by_abs_delta_desc(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"a": 0.40, "b": 0.30, "c": 0.20}
        tgt = {"a": 0.30, "b": 0.10, "c": 0.40}  # b moves 20%, c/a move 10–20%
        actions = rb.compute_actions(cur, tgt, 100_000)
        deltas = [abs(a.delta_weight) for a in actions]
        assert deltas == sorted(deltas, reverse=True)

    def test_hold_not_in_returned_list(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"aave_v3": 0.40, "compound_v3": 0.35}
        tgt = {"aave_v3": 0.41, "compound_v3": 0.34}  # all < 2%
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert all(a.action != ACTION_HOLD for a in actions)

    def test_adapter_missing_in_current_treated_as_zero(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {}
        tgt = {"new_proto": 0.15}
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].current_weight == 0.0
        assert actions[0].action == ACTION_ENTER

    def test_adapter_missing_in_target_treated_as_zero(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"old_proto": 0.15}
        tgt = {}
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert len(actions) == 1
        assert actions[0].target_weight == 0.0
        assert actions[0].action == ACTION_EXIT

    def test_multiple_actions_correct_count(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"a": 0.40, "b": 0.35, "c": 0.15, "cash": 0.10}
        tgt = {"a": 0.30, "b": 0.40, "c": 0.20, "cash": 0.10}
        actions = rb.compute_actions(cur, tgt, 100_000)
        # a: -10%, b: +5%, c: +5% — all above 2%; cash: 0 — HOLD
        assert len(actions) == 3

    def test_priority_field_set_correctly(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"a": 0.30, "b": 0.0,  "c": 0.30}
        tgt = {"a": 0.0,  "b": 0.10, "c": 0.50}
        actions = rb.compute_actions(cur, tgt, 100_000)
        action_map = {a.action: a.priority for a in actions}
        assert action_map[ACTION_EXIT]    == 1
        assert action_map[ACTION_ENTER]   == 2
        assert action_map[ACTION_INCREASE] == 3

    def test_delta_weight_is_target_minus_current(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        cur = {"x": 0.25}
        tgt = {"x": 0.40}
        actions = rb.compute_actions(cur, tgt, 100_000)
        assert actions[0].delta_weight == pytest.approx(0.15, abs=1e-8)

    def test_empty_both_dicts_returns_empty(self):
        rb = _make_rb()
        assert rb.compute_actions({}, {}, 100_000) == []

    def test_all_within_threshold_returns_empty(self):
        rb = _make_rb(rebalance_threshold_pct=5.0)
        cur = {"a": 0.50, "b": 0.50}
        tgt = {"a": 0.54, "b": 0.46}  # 4% drift each — below 5%
        assert rb.compute_actions(cur, tgt, 100_000) == []


# ─── Rebalancer.compute_dollar_moves ─────────────────────────────────────────

class TestComputeDollarMoves:
    def _actions(self, deltas: dict) -> list:
        """Build minimal action list from {adapter_id: delta_weight}."""
        result = []
        for aid, dw in deltas.items():
            act = ACTION_INCREASE if dw > 0 else ACTION_DECREASE
            result.append(
                RebalanceAction(
                    adapter_id=aid,
                    current_weight=0.30,
                    target_weight=0.30 + dw,
                    delta_weight=dw,
                    action=act,
                    priority=3,
                )
            )
        return result

    def test_dollar_moves_calculated_correctly(self):
        rb = _make_rb()
        actions = self._actions({"a": 0.10})  # 10% of 100k = $10k
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount == pytest.approx(10_000.0, rel=1e-6)

    def test_dollar_move_capped_at_max(self):
        """Move of 15% should be capped at MAX_SINGLE_MOVE_PCT=10%."""
        rb = _make_rb(max_single_move_pct=10.0)
        actions = self._actions({"a": 0.15})  # 15% → capped at 10%
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount == pytest.approx(10_000.0, rel=1e-6)

    def test_dollar_move_not_capped_below_max(self):
        rb = _make_rb(max_single_move_pct=10.0)
        actions = self._actions({"a": 0.05})  # 5% — below cap
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount == pytest.approx(5_000.0, rel=1e-6)

    def test_dollar_moves_for_multiple_actions(self):
        rb = _make_rb(max_single_move_pct=10.0)
        actions = self._actions({"a": 0.05, "b": -0.08})
        rb.compute_dollar_moves(actions, 100_000)
        amounts = {a.adapter_id: a.dollar_amount for a in actions}
        assert amounts["a"] == pytest.approx(5_000.0, rel=1e-6)
        assert amounts["b"] == pytest.approx(8_000.0, rel=1e-6)

    def test_dollar_amount_uses_absolute_delta(self):
        """Negative delta should still produce positive dollar_amount."""
        rb = _make_rb()
        actions = self._actions({"a": -0.07})
        rb.compute_dollar_moves(actions, 100_000)
        assert actions[0].dollar_amount > 0

    def test_compute_dollar_moves_returns_same_list(self):
        rb = _make_rb()
        actions = self._actions({"a": 0.05})
        returned = rb.compute_dollar_moves(actions, 100_000)
        assert returned is actions  # same list object

    def test_dollar_moves_with_custom_equity(self):
        rb = _make_rb(max_single_move_pct=10.0)
        actions = self._actions({"a": 0.05})
        rb.compute_dollar_moves(actions, 200_000)
        assert actions[0].dollar_amount == pytest.approx(10_000.0, rel=1e-6)

    def test_cap_applied_per_action_not_total(self):
        """Each action is capped individually."""
        rb = _make_rb(max_single_move_pct=10.0)
        actions = self._actions({"a": 0.15, "b": 0.15})
        rb.compute_dollar_moves(actions, 100_000)
        # Both should be capped at 10k each (not shared cap)
        for a in actions:
            assert a.dollar_amount == pytest.approx(10_000.0, rel=1e-6)


# ─── Rebalancer.estimate_rebalance_cost ──────────────────────────────────────

class TestEstimateRebalanceCost:
    def _actions_with_dollars(self, amounts: list) -> list:
        """Build actions that already have dollar_amount set."""
        result = []
        for i, amt in enumerate(amounts):
            a = RebalanceAction(
                adapter_id=f"proto_{i}",
                current_weight=0.20,
                target_weight=0.30,
                delta_weight=0.10,
                action=ACTION_INCREASE,
                priority=3,
            )
            a.dollar_amount = amt
            result.append(a)
        return result

    def test_cost_estimate_basic(self):
        rb = _make_rb()
        actions = self._actions_with_dollars([10_000.0, 5_000.0])
        cost = rb.estimate_rebalance_cost(actions, slippage_bps=10.0)
        assert cost["total_moves_usd"] == pytest.approx(15_000.0, rel=1e-6)
        assert cost["total_cost_usd"]  == pytest.approx(15.0, rel=1e-6)  # 10bps
        assert cost["action_count"]    == 2

    def test_cost_bps_matches_slippage(self):
        rb = _make_rb()
        actions = self._actions_with_dollars([50_000.0])
        cost = rb.estimate_rebalance_cost(actions, slippage_bps=10.0)
        assert cost["cost_bps"] == pytest.approx(10.0, rel=1e-4)

    def test_cost_estimate_empty_actions(self):
        rb = _make_rb()
        cost = rb.estimate_rebalance_cost([])
        assert cost["total_moves_usd"] == 0.0
        assert cost["total_cost_usd"]  == 0.0
        assert cost["cost_bps"]        == 0.0
        assert cost["action_count"]    == 0

    def test_cost_estimate_custom_slippage(self):
        rb = _make_rb()
        actions = self._actions_with_dollars([10_000.0])
        cost_5bps  = rb.estimate_rebalance_cost(actions, slippage_bps=5.0)
        cost_20bps = rb.estimate_rebalance_cost(actions, slippage_bps=20.0)
        assert cost_20bps["total_cost_usd"] == pytest.approx(
            4 * cost_5bps["total_cost_usd"], rel=1e-6
        )

    def test_cost_estimate_has_required_keys(self):
        rb = _make_rb()
        cost = rb.estimate_rebalance_cost([])
        for key in ("total_moves_usd", "total_cost_usd", "cost_bps", "action_count"):
            assert key in cost

    def test_cost_action_count_matches_list_length(self):
        rb = _make_rb()
        actions = self._actions_with_dollars([1000, 2000, 3000])
        cost = rb.estimate_rebalance_cost(actions)
        assert cost["action_count"] == 3

    def test_cost_graceful_when_dollar_amount_none(self):
        """Actions without dollar_amount set contribute 0 to cost."""
        rb = _make_rb()
        a = RebalanceAction("x", 0.10, 0.20, 0.10, ACTION_INCREASE, 3)
        # dollar_amount intentionally left as None
        cost = rb.estimate_rebalance_cost([a])
        assert cost["total_cost_usd"] == 0.0


# ─── Rebalancer.record_rebalance ─────────────────────────────────────────────

class TestRecordRebalance:
    def _simple_actions(self) -> list:
        a = RebalanceAction("aave_v3", 0.40, 0.35, -0.05, ACTION_DECREASE, 4)
        a.dollar_amount = 5_000.0
        return [a]

    def test_record_creates_file_if_not_exists(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=data_dir)
        hist_file = Path(data_dir) / "rebalance_history.json"
        assert hist_file.exists()

    def test_record_appends_history(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=data_dir)
        rb.record_rebalance(self._simple_actions(), 100_500.0, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        assert len(hist) == 2

    def test_record_entry_schema(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_017.45, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        entry = hist[0]
        for key in ("date", "equity", "actions_count", "total_moves_usd",
                    "cost_usd", "actions"):
            assert key in entry, f"missing key: {key}"

    def test_record_actions_list_in_entry(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        actions_rec = hist[0]["actions"]
        assert len(actions_rec) == 1
        assert actions_rec[0]["adapter_id"] == "aave_v3"
        assert actions_rec[0]["action"] == ACTION_DECREASE

    def test_record_atomic_write_no_tmp_files_left(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=data_dir)
        tmp_files = list(Path(data_dir).glob(".rebalance_history_*.tmp"))
        assert tmp_files == []

    def test_record_ring_buffer_eviction(self):
        """History is capped at HISTORY_MAX entries."""
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        # Seed HISTORY_MAX + 5 extra entries to trigger eviction
        for i in range(HISTORY_MAX + 5):
            rb.record_rebalance(self._simple_actions(), 100_000.0 + i, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        assert len(hist) == HISTORY_MAX

    def test_record_equity_stored_correctly(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 99_999.99, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        assert hist[0]["equity"] == pytest.approx(99_999.99, rel=1e-6)

    def test_record_actions_count_matches(self):
        data_dir = _tmp_data_dir()
        rb = _make_rb()
        actions = self._simple_actions()
        rb.record_rebalance(actions, 100_000.0, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        assert hist[0]["actions_count"] == len(actions)

    def test_record_existing_corrupt_file_recovers(self):
        """Corrupt history file → overwrite with fresh single entry."""
        data_dir = _tmp_data_dir()
        hist_path = Path(data_dir) / "rebalance_history.json"
        hist_path.write_text("NOT VALID JSON <<<", encoding="utf-8")
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=data_dir)
        hist = json.loads(hist_path.read_text())
        assert len(hist) == 1

    def test_record_creates_data_dir_if_missing(self):
        base = _tmp_data_dir()
        nested = os.path.join(base, "subdir", "data")
        rb = _make_rb()
        rb.record_rebalance(self._simple_actions(), 100_000.0, data_dir=nested)
        assert (Path(nested) / "rebalance_history.json").exists()


# ─── Integration / end-to-end flows ──────────────────────────────────────────

class TestIntegrationFlows:
    def test_full_rebalance_flow(self):
        """compute_actions → compute_dollar_moves → estimate_cost → record."""
        rb = _make_rb(rebalance_threshold_pct=2.0, max_single_move_pct=10.0)
        current = {"aave_v3": 0.40, "compound_v3": 0.35, "morpho": 0.20, "cash": 0.05}
        target  = {"aave_v3": 0.35, "compound_v3": 0.35, "morpho": 0.25, "cash": 0.05}
        equity  = 100_000.0

        assert rb.needs_rebalance(current, target) is True

        actions = rb.compute_actions(current, target, equity)
        assert len(actions) >= 1

        rb.compute_dollar_moves(actions, equity)
        for a in actions:
            assert a.dollar_amount is not None

        cost = rb.estimate_rebalance_cost(actions)
        assert cost["action_count"] == len(actions)

        data_dir = _tmp_data_dir()
        rb.record_rebalance(actions, equity, data_dir=data_dir)
        hist = json.loads((Path(data_dir) / "rebalance_history.json").read_text())
        assert len(hist) == 1

    def test_no_rebalance_produces_empty_actions(self):
        rb = _make_rb(rebalance_threshold_pct=2.0)
        current = {"aave_v3": 0.40, "compound_v3": 0.35, "cash": 0.25}
        target  = {"aave_v3": 0.40, "compound_v3": 0.35, "cash": 0.25}
        assert not rb.needs_rebalance(current, target)
        assert rb.compute_actions(current, target, 100_000) == []

    def test_exit_then_enter_scenario(self):
        """Rotate out of one adapter and into another in one rebalance."""
        rb = _make_rb(rebalance_threshold_pct=2.0)
        current = {"old_adapter": 0.20, "aave_v3": 0.40, "cash": 0.40}
        target  = {"new_adapter": 0.20, "aave_v3": 0.40, "cash": 0.40}
        actions = rb.compute_actions(current, target, 100_000)
        action_types = {a.action for a in actions}
        assert ACTION_EXIT  in action_types
        assert ACTION_ENTER in action_types

    def test_cost_zero_for_empty_rebalance(self):
        rb = _make_rb()
        cost = rb.estimate_rebalance_cost([])
        assert cost["total_cost_usd"] == 0.0

    def test_custom_threshold_suppresses_small_drifts(self):
        rb = _make_rb(rebalance_threshold_pct=10.0)
        current = {"a": 0.40, "b": 0.35, "c": 0.25}
        target  = {"a": 0.46, "b": 0.35, "c": 0.19}  # 6% drift — below 10%
        assert rb.needs_rebalance(current, target) is False
        assert rb.compute_actions(current, target, 100_000) == []

    def test_large_portfolio_dollar_cap(self):
        """10% cap on a $1M portfolio → max $100k per move."""
        rb = _make_rb(max_single_move_pct=10.0, rebalance_threshold_pct=2.0)
        current = {"a": 0.20}
        target  = {"a": 0.50}   # +30% drift → raw = $300k → capped at $100k
        actions = rb.compute_actions(current, target, 1_000_000)
        rb.compute_dollar_moves(actions, 1_000_000)
        assert actions[0].dollar_amount == pytest.approx(100_000.0, rel=1e-6)
