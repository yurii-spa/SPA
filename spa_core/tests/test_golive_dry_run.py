"""
Tests for the end-to-end GO-LIVE DRY-RUN HARNESS (spa_core/execution/golive_dry_run.py).

Proves the harness:
  * reaches ALL gates, in the correct ORDER;
  * an injected 6% drawdown → kill-switch fires (would-refuse);
  * a malformed / NaN input → RiskPolicy refuses (fail-CLOSED, P5-1);
  * an over-concentration → blocked;
  * a CLEAN compliant input → all upstream gates PASS BUT would_proceed=False
    (the live trading gate is the master inert block);
  * the harness NEVER writes/moves anything outside data/golive_dry_run.json;
  * the harness leaves NO dirty global kill-switch state.

stdlib + pytest only. No network, no chain, no capital.
"""
from __future__ import annotations

import math

import pytest

from spa_core.execution import golive_dry_run as gdr
from spa_core.execution.golive_dry_run import dry_run, build_report, EXPECTED_GATE_ORDER
from spa_core.execution.safety_checks import PreExecutionSafety


CLEAN_ALLOC = {"aave_v3": 5000.0}


def _verdict(report, gate_name):
    g = next(g for g in report["gates"] if g["name"] == gate_name)
    return g["verdict"]


# ── Gate walk: all gates reached, in order ──────────────────────────────────

def test_all_gates_reached_in_order():
    report = dry_run(CLEAN_ALLOC)
    reached = [g["name"] for g in report["gates"]]
    assert reached == list(EXPECTED_GATE_ORDER)
    assert report["all_gates_reached"] is True
    assert report["ordering_ok"] is True
    assert len(report["gates"]) == 5


def test_dry_run_flags_are_inert():
    report = dry_run(CLEAN_ALLOC)
    assert report["dry_run"] is True
    assert report["is_dry_run"] is True
    assert report["moves_capital"] is False
    assert gdr.IS_DRY_RUN is True


# ── Clean compliant input: all upstream pass BUT would_proceed=False ────────

def test_clean_input_all_pass_but_inert():
    report = dry_run(CLEAN_ALLOC)
    assert _verdict(report, "kill_switch") == "PASS"
    assert _verdict(report, "pre_execution_safety") == "PASS"
    assert _verdict(report, "nav_reconciliation") == "PASS"
    assert _verdict(report, "position_monitor") == "PASS"
    # Every upstream gate clear...
    assert report["every_upstream_gate_clear"] is True
    # ...but the live gate is LOCKED → inert.
    assert _verdict(report, "live_trading_gate") == "BLOCKED"
    assert report["live_trading_gate_active"] is False
    # The harness NEVER proceeds.
    assert report["would_proceed"] is False


def test_would_proceed_always_false_even_when_everything_clears():
    # Multiple clean allocations — would_proceed must be pinned False regardless.
    for alloc in ({"aave_v3": 5000.0}, {"compound_v3": 3000.0}, {"yearn_v3": 2000.0}):
        report = dry_run(alloc)
        assert report["would_proceed"] is False


# ── Fault injection: 6% drawdown → kill-switch fires ────────────────────────

def test_injected_drawdown_fires_kill_switch():
    report = dry_run(CLEAN_ALLOC, inject={"drawdown_pct": 0.06})
    assert _verdict(report, "kill_switch") == "BLOCKED"
    # The pre-exec safety pipeline ALSO catches the 6% drawdown at its own
    # 5% kill-switch stage.
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True
    assert report["would_proceed"] is False


def test_drawdown_below_stop_does_not_fire():
    # 4% < 5% execution kill-switch stop → kill-switch must NOT fire.
    report = dry_run(CLEAN_ALLOC, inject={"drawdown_pct": 0.04})
    assert _verdict(report, "kill_switch") == "PASS"


# ── Fault injection: NaN input → RiskPolicy refuses (fail-closed) ───────────

def test_nan_apy_riskpolicy_refuses():
    report = dry_run(CLEAN_ALLOC, inject={"apy": float("nan")})
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True
    # The RiskPolicy stage specifically is the one that refuses.
    safety = next(g for g in report["gates"] if g["name"] == "pre_execution_safety")
    rp = next(s for s in safety["stages"] if s["stage"] == "RiskPolicy")
    assert rp["verdict"] == "BLOCKED"
    assert "non-finite" in rp["detail"].lower()
    assert report["would_proceed"] is False


def test_nan_tvl_riskpolicy_refuses():
    report = dry_run(CLEAN_ALLOC, inject={"tvl": float("nan")})
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True


def test_inf_apy_riskpolicy_refuses():
    report = dry_run(CLEAN_ALLOC, inject={"apy": float("inf")})
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True


# ── Fault injection: over-concentration → blocked ───────────────────────────

def test_over_concentration_blocked():
    report = dry_run(CLEAN_ALLOC, inject={"over_concentration": True})
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True
    # Concentration breach must appear in the RiskPolicy reasoning.
    safety = next(g for g in report["gates"] if g["name"] == "pre_execution_safety")
    rp = next(s for s in safety["stages"] if s["stage"] == "RiskPolicy")
    assert rp["verdict"] == "BLOCKED"
    assert "concentration" in rp["detail"].lower()
    assert report["would_proceed"] is False


# ── Manual kill injection ───────────────────────────────────────────────────

def test_manual_kill_fires_and_leaves_no_dirty_state():
    assert PreExecutionSafety.is_kill_switch_active() is False
    report = dry_run(CLEAN_ALLOC, inject={"manual_kill": True})
    assert _verdict(report, "kill_switch") == "BLOCKED"
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["would_proceed"] is False
    # Critical: the harness must NOT leave the module-level kill switch armed.
    assert PreExecutionSafety.is_kill_switch_active() is False


# ── NAV reconciliation gate ─────────────────────────────────────────────────

def test_nav_reconciliation_conserves_for_clean_alloc():
    report = dry_run(CLEAN_ALLOC)
    nav = next(g for g in report["gates"] if g["name"] == "nav_reconciliation")
    assert nav["verdict"] == "PASS"


# ── Cycle-output shape acceptance (positions doc) ───────────────────────────

def test_accepts_current_positions_doc_shape():
    doc = {"positions": {"aave_v3": 5000.0, "compound_v3": 3000.0}, "capital_usd": 100000.0}
    report = dry_run(doc)
    assert report["all_gates_reached"] is True
    assert report["representative_trade"]["protocol"] in ("aave_v3", "compound_v3")


def test_representative_trade_is_largest_position():
    report = dry_run({"aave_v3": 1000.0, "compound_v3": 8000.0, "yearn_v3": 2000.0})
    assert report["representative_trade"]["protocol"] == "compound_v3"
    assert math.isclose(report["representative_trade"]["amount_usd"], 8000.0)


# ── Determinism ─────────────────────────────────────────────────────────────

def test_deterministic_gate_verdicts():
    a = dry_run(CLEAN_ALLOC)
    b = dry_run(CLEAN_ALLOC)
    assert [g["verdict"] for g in a["gates"]] == [g["verdict"] for g in b["gates"]]
    assert a["all_gates_reached"] == b["all_gates_reached"]
    assert a["would_proceed"] == b["would_proceed"] is False


# ── I/O scope: only data/golive_dry_run.json is written ─────────────────────

def test_writes_only_golive_dry_run_json(tmp_path, monkeypatch):
    """build_report(write=True) must touch ONLY data/golive_dry_run.json."""
    out = tmp_path / "golive_dry_run.json"
    monkeypatch.setattr(gdr, "_OUT", out)

    before = set(p.name for p in tmp_path.iterdir())
    report = build_report(write=True, cycle_output=CLEAN_ALLOC)
    after = set(p.name for p in tmp_path.iterdir())

    new_files = after - before
    assert new_files == {"golive_dry_run.json"}
    assert out.exists()
    # The written report round-trips and is inert.
    import json
    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["would_proceed"] is False
    assert persisted["dry_run"] is True
    assert persisted["all_gates_reached"] is True


def test_build_report_no_write_does_not_create_file(tmp_path, monkeypatch):
    out = tmp_path / "golive_dry_run.json"
    monkeypatch.setattr(gdr, "_OUT", out)
    report = build_report(write=False, cycle_output=CLEAN_ALLOC)
    assert not out.exists()
    assert report["would_proceed"] is False


# ── Empty / degenerate input fails closed ───────────────────────────────────

def test_empty_allocation_fails_closed():
    report = dry_run({})
    # No representative trade → safety gate cannot pass → fail-closed, inert.
    assert _verdict(report, "pre_execution_safety") == "BLOCKED"
    assert report["fail_closed_on_bad_input"] is True
    assert report["would_proceed"] is False
    # Still reaches every gate in order.
    assert report["all_gates_reached"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:randomly"]))
