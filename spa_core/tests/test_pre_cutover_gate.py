"""Tests for spa_core/paper_trading/pre_cutover_gate.py — the PRE-CUTOVER GATE.

Asserts:
  1.  run_gate exits 0-equivalent (all_defenses_fired) against a clean sandbox.
  2.  main() returns 0 when all defenses fire.
  3.  A forced-broken defense (kill-switch stubbed to NOT fire) → all_defenses_fired
      False, exit 1, and the failing gate is NAMED in failing_gates.
  4.  NAV-reconcile under the NEW states (clean residual 0, corruption caught).
  5.  position_monitor correct in post-HARD-kill all-cash + post-SOFT held-only,
      and a deliberately corrupted position set is caught.
  6.  The gate NEVER imports execution/ (transitively).
  7.  The gate REFUSES to run against the live data/ directory.
  8.  would_cutover is ALWAYS False (inert), is_inert True, moves_capital False.
  9.  Each individual money-path drill passes against a sandbox.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE.parent) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE.parent))

from spa_core.paper_trading import pre_cutover_gate as pcg


# ── 1. clean sandbox → all defenses fire ──────────────────────────────────────
def test_all_defenses_fire_in_sandbox(tmp_path: Path):
    report = pcg.run_gate(data_dir=str(tmp_path), write=True)
    assert report["all_defenses_fired"] is True, report["failing_gates"]
    assert report["failing_gates"] == []
    assert report["defenses_passed"] == report["defenses_total"] == len(pcg._DRILLS)
    # report persisted into the SANDBOX, not live data/
    assert (tmp_path / "pre_cutover_gate.json").exists()


# ── 2. main() exit 0 ──────────────────────────────────────────────────────────
def test_main_exit_zero(tmp_path: Path):
    rc = pcg.main(["--data-dir", str(tmp_path), "--no-save"])
    assert rc == 0


# ── 3. forced-broken defense → exit 1 + names the gate ────────────────────────
def test_broken_killswitch_fails_and_names_gate(tmp_path: Path, monkeypatch):
    """Stub KillSwitchChecker.check_drawdown_trigger to NOT fire → HARD_KILL
    drawdown defense must FAIL, exit non-zero, and name the gate."""
    monkeypatch.setattr(
        pcg.KillSwitchChecker, "check_drawdown_trigger",
        lambda self, curve: (False, "STUBBED: kill switch disabled"),
        raising=True,
    )
    report = pcg.run_gate(data_dir=str(tmp_path), write=False)
    assert report["all_defenses_fired"] is False
    assert "HARD_KILL_DRAWDOWN" in report["failing_gates"]
    # And the CLI surfaces exit 1.
    rc = pcg.main(["--data-dir", str(tmp_path), "--no-save"])
    # main re-runs the gate; the monkeypatch is still active in this test scope.
    assert rc == 1


def test_broken_riskpolicy_fails_and_names_gate(tmp_path: Path, monkeypatch):
    """Stub the RiskPolicy gate to APPROVE an over-concentration target → the
    RISKPOLICY_BLOCK defense must FAIL and be named."""
    monkeypatch.setattr(
        pcg, "_apply_risk_policy_gate",
        lambda *a, **k: {"approved": True, "violations": [], "warnings": [],
                         "trimmed": False, "target_usd": {}, "error": None},
        raising=True,
    )
    report = pcg.run_gate(data_dir=str(tmp_path), write=False)
    assert report["all_defenses_fired"] is False
    assert "RISKPOLICY_BLOCK" in report["failing_gates"]


# ── 4. NAV reconcile under the new states ─────────────────────────────────────
def test_nav_reconcile_clean_residual_zero():
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
    rec = pcg.nav_reconcile(target, dict(target))
    assert rec["matches_target"] is True
    assert rec["nav_conserved"] is True
    assert rec["residual_usd"] == 0.0


def test_nav_reconcile_catches_corruption():
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
    corrupt = {"aave_v3": 35_000.0, "morpho_blue": 20_000.0}  # lost $5k
    rec = pcg.nav_reconcile(target, corrupt)
    assert rec["matches_target"] is False


def test_nav_reconcile_catches_non_finite():
    target = {"aave_v3": 40_000.0}
    rec = pcg.nav_reconcile(target, {"aave_v3": float("nan")})
    assert rec["matches_target"] is False


# ── 5. position monitor under the new states ──────────────────────────────────
def test_position_monitor_post_hard_kill_all_cash():
    """Post-HARD-kill ALL-CASH state: NORMAL, no anomaly, all_cash True."""
    s = pcg.position_monitor_scan({"aave_v3": 0.0, "morpho_blue": 0.0})
    assert s["anomaly"] is False
    assert s["all_cash"] is True
    assert s["held_count"] == 0


def test_position_monitor_post_soft_held_only():
    """Post-SOFT held-only state: NORMAL, no anomaly, held tracked."""
    s = pcg.position_monitor_scan({"aave_v3": 30_000.0, "morpho_blue": 20_000.0})
    assert s["anomaly"] is False
    assert s["held_count"] == 2
    assert s["all_cash"] is False


def test_position_monitor_catches_corruption():
    assert pcg.position_monitor_scan({"aave_v3": -10_000.0})["anomaly"] is True
    assert pcg.position_monitor_scan({"aave_v3": float("inf")})["anomaly"] is True
    assert pcg.position_monitor_scan({"aave_v3": 200_000.0})["anomaly"] is True  # > capital


# ── 6. never imports execution/ ───────────────────────────────────────────────
def test_no_execution_import(tmp_path: Path):
    pcg.run_gate(data_dir=str(tmp_path), write=False)
    leaked = [m for m in sys.modules if m.startswith("spa_core.execution")]
    assert leaked == [], f"execution/ imported transitively: {leaked}"


# ── 7. refuses live data/ ─────────────────────────────────────────────────────
def test_refuses_live_data_dir():
    live = pcg._ROOT / "data"
    with pytest.raises(RuntimeError, match="live data"):
        pcg.run_gate(data_dir=str(live), write=False)


# ── 8. inert invariants ───────────────────────────────────────────────────────
def test_inert_invariants(tmp_path: Path):
    report = pcg.run_gate(data_dir=str(tmp_path), write=False)
    assert report["would_cutover"] is False
    assert report["is_inert"] is True
    assert report["moves_capital"] is False
    assert report["llm_forbidden"] is True
    assert report["live_data_untouched"] is True


# ── 9. each individual drill passes ───────────────────────────────────────────
@pytest.mark.parametrize("name,drill", list(pcg._DRILLS))
def test_each_drill_passes(name, drill, tmp_path: Path):
    pcg._seed_sandbox(tmp_path)
    res = drill(tmp_path)
    assert res["gate"] == name
    assert res["pass"] is True, f"{name}: expected={res['expected']} actual={res['actual']}"


# ── 10. report contains owner-only blockers + ladder thresholds ───────────────
def test_report_documents_owner_blockers_and_ladder(tmp_path: Path):
    report = pcg.run_gate(data_dir=str(tmp_path), write=False)
    blockers = " ".join(report["owner_only_blockers"]).lower()
    assert "custody" in blockers and "audit" in blockers and "track" in blockers
    th = report["thresholds"]
    assert th["dl01_daily_loss_pct"] == 2.0
    assert th["dl02_peak_drawdown_pct"] == 10.0
    assert th["soft_derisk_pct"] == 5.0
    assert th["hard_kill_pct"] == 10.0  # ADR-048: lowered 15→10 (owns DL-02 rung)
