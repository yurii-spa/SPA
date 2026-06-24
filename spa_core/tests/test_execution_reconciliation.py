"""
Tests for spa_core/execution/reconciliation.py — dry-run round-trip + reconciliation.

Hermetic: no network, no chain, no real data-file dependence (round_trip is driven
with explicit current/target and write=False / monkeypatched paths). Deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.execution import reconciliation as rc


# --------------------------------------------------------------------------- #
# plan_trades
# --------------------------------------------------------------------------- #
def test_plan_detects_all_four_actions():
    current = {"aave_v3": 1000.0, "compound_v3": 500.0, "euler_v2": 300.0}
    target = {"aave_v3": 1000.0, "compound_v3": 800.0, "euler_v2": 0.0, "maple": 400.0}
    # aave: unchanged (skip), compound: INCREASE, euler: EXIT, maple: ENTER
    trades = rc.plan_trades(current, target)
    by_proto = {t["protocol"]: t for t in trades}

    assert "aave_v3" not in by_proto  # unchanged → skipped
    assert by_proto["compound_v3"]["action"] == "INCREASE"
    assert by_proto["compound_v3"]["amount_usd"] == pytest.approx(300.0)
    assert by_proto["euler_v2"]["action"] == "EXIT"
    assert by_proto["euler_v2"]["amount_usd"] == pytest.approx(300.0)
    assert by_proto["maple"]["action"] == "ENTER"
    assert by_proto["maple"]["amount_usd"] == pytest.approx(400.0)


def test_plan_detects_decrease():
    trades = rc.plan_trades({"aave_v3": 1000.0}, {"aave_v3": 600.0})
    assert len(trades) == 1
    assert trades[0]["action"] == "DECREASE"
    assert trades[0]["amount_usd"] == pytest.approx(400.0)


def test_plan_skips_dust():
    # 5 USD change with default 10 USD floor → skipped.
    trades = rc.plan_trades({"aave_v3": 1000.0}, {"aave_v3": 1005.0})
    assert trades == []
    # custom floor allows it through.
    trades2 = rc.plan_trades({"aave_v3": 1000.0}, {"aave_v3": 1005.0}, min_trade_usd=1.0)
    assert len(trades2) == 1 and trades2[0]["action"] == "INCREASE"


def test_plan_ordering_exits_before_entries():
    current = {"aave_v3": 1000.0, "zeta": 500.0}
    target = {"zeta": 0.0, "aardvark": 1000.0, "aave_v3": 1000.0}
    # zeta EXIT (exit-side), aardvark ENTER (entry-side)
    trades = rc.plan_trades(current, target)
    actions = [t["action"] for t in trades]
    # exit-side group comes first
    assert actions[0] in ("EXIT", "DECREASE")
    assert actions[-1] in ("ENTER", "INCREASE")
    assert trades[0]["protocol"] == "zeta"  # only exit
    assert trades[1]["protocol"] == "aardvark"  # only entry


# --------------------------------------------------------------------------- #
# dry_run_execute
# --------------------------------------------------------------------------- #
def test_dry_run_reaches_target():
    current = {"aave_v3": 1000.0, "euler_v2": 300.0}
    target = {"aave_v3": 1200.0, "maple": 500.0}
    trades = rc.plan_trades(current, target)
    out = rc.dry_run_execute(current, trades)
    assert out["resulting_positions"] == {"aave_v3": 1200.0, "maple": 500.0}
    # euler fully exited → dropped from result
    assert "euler_v2" not in out["resulting_positions"]


def test_dry_run_gross_traded():
    current = {"a": 1000.0}
    target = {"a": 1200.0, "b": 500.0}  # +200 increase, +500 enter
    trades = rc.plan_trades(current, target)
    out = rc.dry_run_execute(current, trades)
    assert out["gross_traded_usd"] == pytest.approx(700.0)


# --------------------------------------------------------------------------- #
# reconcile
# --------------------------------------------------------------------------- #
def test_reconcile_matches_when_equal():
    target = {"aave_v3": 1000.0, "maple": 500.0}
    resulting = {"aave_v3": 1000.0, "maple": 500.0}
    r = rc.reconcile(target, resulting, nav_before=1500.0, costs_usd=0.0)
    assert r["matches_target"] is True
    assert r["max_position_delta_usd"] == pytest.approx(0.0)
    assert r["nav_conserved"] is True


def test_reconcile_within_tolerance():
    # off by 0.50 < 1.0 tolerance → still matches
    target = {"aave_v3": 1000.0}
    resulting = {"aave_v3": 1000.50}
    r = rc.reconcile(target, resulting, nav_before=1000.0, costs_usd=0.0)
    assert r["matches_target"] is True


def test_reconcile_fails_when_off_beyond_tolerance():
    target = {"aave_v3": 1000.0}
    resulting = {"aave_v3": 1010.0}  # off by 10 > 1.0 tolerance
    r = rc.reconcile(target, resulting, nav_before=1000.0, costs_usd=0.0)
    assert r["matches_target"] is False
    assert r["max_position_delta_usd"] == pytest.approx(10.0)
    assert r["deltas_usd"]["aave_v3"] == pytest.approx(10.0)


def test_reconcile_nav_conserved_with_costs():
    target = {"a": 990.0}
    resulting = {"a": 990.0}
    # nav_after=990, expected = 1000 - 10 = 990 → conserved
    r = rc.reconcile(target, resulting, nav_before=1000.0, costs_usd=10.0)
    assert r["nav_conserved"] is True
    assert r["nav_after"] == pytest.approx(990.0)
    assert r["expected_nav_after"] == pytest.approx(990.0)


def test_reconcile_nav_not_conserved():
    target = {"a": 1000.0}
    resulting = {"a": 1000.0}
    # nav_after=1000, expected = 1000 - 50 = 950 → leaked 50 > tolerance
    r = rc.reconcile(target, resulting, nav_before=1000.0, costs_usd=50.0)
    assert r["nav_conserved"] is False


# --------------------------------------------------------------------------- #
# estimate_costs
# --------------------------------------------------------------------------- #
def test_estimate_costs_deterministic():
    trades = [
        {"protocol": "a", "action": "ENTER", "amount_usd": 10000.0},
        {"protocol": "b", "action": "EXIT", "amount_usd": 10000.0},
    ]
    # 2 trades * 2.0 gas + 5bps * 20000 = 4.0 + 10.0 = 14.0
    assert rc.estimate_costs(trades) == pytest.approx(14.0)
    assert rc.estimate_costs([]) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# round_trip
# --------------------------------------------------------------------------- #
def test_round_trip_noop_reconciles_perfectly():
    current = {"aave_v3": 1000.0, "maple": 500.0}
    # target defaults to current → no-op
    r = rc.round_trip(current=current, target=None, write=False, ts="2026-06-24T00:00:00+00:00")
    assert r["n_trades"] == 0
    assert r["matches_target"] is True
    assert r["nav_conserved"] is True
    assert r["go_live_ready"] is True
    assert r["resulting_positions"] == {"aave_v3": 1000.0, "maple": 500.0}


def test_round_trip_real_rebalance_reconciles():
    current = {"aave_v3": 1000.0, "euler_v2": 300.0}
    target = {"aave_v3": 1200.0, "maple": 100.0}
    r = rc.round_trip(current=current, target=target, write=False, ts="2026-06-24T00:00:00+00:00")
    assert r["n_trades"] >= 1
    assert r["matches_target"] is True
    assert r["nav_conserved"] is True


def test_round_trip_deterministic():
    current = {"aave_v3": 1000.0, "euler_v2": 300.0}
    target = {"aave_v3": 1200.0, "maple": 100.0}
    a = rc.round_trip(current=current, target=target, write=False, ts="2026-06-24T00:00:00+00:00")
    b = rc.round_trip(current=current, target=target, write=False, ts="2026-06-24T00:00:00+00:00")
    a.pop("audit_recorded", None)
    b.pop("audit_recorded", None)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_round_trip_loads_from_disk(tmp_path, monkeypatch):
    pos_file = tmp_path / "current_positions.json"
    pos_file.write_text(json.dumps({"positions": {"aave_v3": 1000.0, "maple": 500.0}}))
    out_file = tmp_path / "execution_reconciliation.json"
    monkeypatch.setattr(rc, "_positions_path", lambda: pos_file)
    monkeypatch.setattr(rc, "_out_path", lambda: out_file)
    # Disable audit side effect for hermeticity.
    monkeypatch.setattr(
        "spa_core.audit.hash_chain.append",
        lambda *a, **k: {},
    )

    r = rc.round_trip(write=True, ts="2026-06-24T00:00:00+00:00")
    # no-op baseline on loaded data
    assert r["nav_before_usd"] == pytest.approx(1500.0)
    assert r["n_trades"] == 0
    assert r["matches_target"] is True
    # atomic write landed
    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["matches_target"] is True
    assert written["live_execution"] is False


def test_round_trip_write_is_atomic_no_tmp_left(tmp_path, monkeypatch):
    out_file = tmp_path / "execution_reconciliation.json"
    monkeypatch.setattr(rc, "_out_path", lambda: out_file)
    monkeypatch.setattr("spa_core.audit.hash_chain.append", lambda *a, **k: {})
    rc.round_trip(current={"a": 100.0}, write=True, ts="2026-06-24T00:00:00+00:00")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".execrecon_")]
    assert leftovers == []
