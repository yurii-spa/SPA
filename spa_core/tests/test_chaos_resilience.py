"""
spa_core/tests/test_chaos_resilience.py — CHAOS / failure-injection resilience suite.

# LLM_FORBIDDEN

Institutional resilience testing: prove the system's self-healing / detection logic
ACTUALLY WORKS when faults are injected. We do NOT break the live system — every fault is
injected hermetically via monkeypatch / tmp_path against the REAL modules' real functions,
then we assert the module DETECTS / RECOVERS / handles the failure gracefully. dry_run is
used wherever the module supports it (never actually kickstart / activate / write live state).

Hermetic guarantees:
  * Nothing under the repo's real data/ is read or written — module path globals
    (_DATA / _CACHE / _OUT) and loader functions are monkeypatched to tmp_path.
  * No launchctl is invoked — self_heal / threat_reactor are exercised with dry_run=True
    and with their loaders/labels stubbed.
  * Deterministic: timestamps are pinned where the verdict depends on them.

Scenarios covered:
  1. threat_reactor — CRITICAL depeg detected; held-protocol CRITICAL red flag detected;
     same flag with fallback_used=True is IGNORED; emergency HALT detected; clear → no
     threat; kill-switch-already-active tuple handling.
  2. self_heal — a missing expected agent is reported as "would bootstrap"; all-present →
     healthy; a missed cycle is reported as "would recover".
  3. nav_proof — components sum != reported equity → reconciliation_ok False (drift caught);
     equal (+accrued yield) → True; verify_proof round-trips.
  4. data_integrity — future date / out-of-band APY / out-of-order dates each flagged;
     clean series → CLEAN.
  5. pipeline_health — missing core artifact → CRITICAL; stale core → CRITICAL; stale
     non-core → DEGRADED; all fresh → OK.
  6. gate — gate file absent → is_eligible fail-OPEN True (does not block ops).
  7. kill_switch — is_kill_switch_active() returns (bool, reason); callers must unpack the
     tuple (regression guard for the known "treated tuple as bool" bug).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.backtesting.tier1 import data_integrity as di
from spa_core.backtesting.tier1 import gate as gate_mod
from spa_core.backtesting.tier1 import nav_proof
from spa_core.backtesting.tier1 import pipeline_health as ph
from spa_core.governance.kill_switch import KillSwitchChecker
from spa_core.monitoring import self_heal
from spa_core.monitoring import threat_reactor


# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _point_threat_reactor_at(tmp_path, monkeypatch, **files):
    """Redirect threat_reactor._DATA at a hermetic tmp dir and seed its JSON inputs.

    threat_reactor._load reads `_DATA / name` at call time, so patching the module
    global is sufficient. We also force _kill_switch_active() to a known value so the
    test controls the 'already active' branch without touching real kill-switch state.
    """
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(threat_reactor, "_DATA", data)
    for name, obj in files.items():
        _write_json(data / f"{name}.json", obj)
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# 1) THREAT REACTOR
# ═══════════════════════════════════════════════════════════════════════════════


def test_threat_reactor_detects_critical_depeg(tmp_path, monkeypatch):
    """Inject a CRITICAL depeg into peg_report → _detect_threats reports it and a dry-run
    run_reactor surfaces it WITHOUT activating anything."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        peg_report={"critical": 1, "worst_adapter": "usde", "worst_deviation_pct": -4.2},
    )
    monkeypatch.setattr(threat_reactor, "_kill_switch_active", lambda: False)

    threats = threat_reactor._detect_threats()
    assert any("depeg CRITICAL" in t for t in threats), threats

    report = threat_reactor.run_reactor(dry_run=True)
    assert report["clear"] is False
    assert report["threats"]
    # dry-run must NEVER act / activate.
    assert report["acted"] is False
    assert report["activation_failed"] is False


def test_threat_reactor_detects_wide_band_depeg(tmp_path, monkeypatch):
    """Even without critical>0, a worst deviation beyond DEPEG_BAND_PCT is a threat."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        peg_report={"critical": 0, "worst_adapter": "sdai", "worst_deviation_pct": -2.0},
    )
    threats = threat_reactor._detect_threats()
    assert any("depeg" in t for t in threats), threats


def test_threat_reactor_held_protocol_critical_redflag_detected(tmp_path, monkeypatch):
    """A LIVE (fallback_used=False) CRITICAL red flag on a HELD protocol → threat."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        current_positions={"positions": {"aave_v3": 50000.0}},
        red_flags={
            "fallback_used": False,
            "red_flags": [
                {"severity": "CRITICAL", "protocol": "aave_v3", "category": "tvl_collapse"}
            ],
        },
    )
    threats = threat_reactor._detect_threats()
    assert any("red flag CRITICAL on HELD" in t for t in threats), threats


def test_threat_reactor_fallback_redflag_is_ignored(tmp_path, monkeypatch):
    """The SAME held-protocol CRITICAL flag with fallback_used=True must be IGNORED
    (bootstrap/fallback data is not actionable). Resilience = no false trip."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        current_positions={"positions": {"aave_v3": 50000.0}},
        red_flags={
            "fallback_used": True,
            "red_flags": [
                {"severity": "CRITICAL", "protocol": "aave_v3", "category": "tvl_collapse"}
            ],
        },
    )
    threats = threat_reactor._detect_threats()
    assert not any("red flag" in t for t in threats), threats


def test_threat_reactor_critical_redflag_on_unheld_protocol_ignored(tmp_path, monkeypatch):
    """A CRITICAL flag on a protocol we do NOT hold is not actionable for the reactor."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        current_positions={"positions": {"aave_v3": 50000.0}},
        red_flags={
            "fallback_used": False,
            "red_flags": [
                {"severity": "CRITICAL", "protocol": "some_obscure_proto", "category": "x"}
            ],
        },
    )
    threats = threat_reactor._detect_threats()
    assert not any("red flag" in t for t in threats), threats


def test_threat_reactor_detects_emergency_halt(tmp_path, monkeypatch):
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        emergency_status={"status": "HALT"},
    )
    threats = threat_reactor._detect_threats()
    assert any("emergency breaker" in t for t in threats), threats


def test_threat_reactor_clear_when_no_faults(tmp_path, monkeypatch):
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        peg_report={"critical": 0, "worst_deviation_pct": 0.1},
        red_flags={"fallback_used": False, "red_flags": []},
        emergency_status={"status": "OK"},
    )
    monkeypatch.setattr(threat_reactor, "_kill_switch_active", lambda: False)
    report = threat_reactor.run_reactor(dry_run=True)
    assert report["clear"] is True
    assert report["threats"] == []
    assert report["acted"] is False


def test_threat_reactor_idempotent_when_kill_switch_already_active(tmp_path, monkeypatch):
    """If the kill-switch is already active, the reactor must NOT re-fire (acted stays
    False) even with live threats. Guards against re-activation storms."""
    _point_threat_reactor_at(
        tmp_path, monkeypatch,
        peg_report={"critical": 1, "worst_adapter": "usde", "worst_deviation_pct": -5.0},
    )
    monkeypatch.setattr(threat_reactor, "_kill_switch_active", lambda: True)
    report = threat_reactor.run_reactor(dry_run=False)
    assert report["threats"], "threat should still be detected"
    assert report["kill_switch_already_active"] is True
    assert report["acted"] is False
    assert report["activation_failed"] is False


def test_threat_reactor_kill_switch_tuple_handling(tmp_path, monkeypatch):
    """_kill_switch_active() must correctly UNPACK the (bool, reason) tuple the real
    KillSwitchChecker API returns. Point its _DATA at a tmp data dir containing a manual
    kill-switch file and assert it reads True (not 'truthy tuple')."""
    data = _point_threat_reactor_at(tmp_path, monkeypatch)
    _write_json(data / "kill_switch_active.json", {"active": True, "reason": "manual chaos"})
    assert threat_reactor._kill_switch_active() is True

    # And inactive (active=False overwrite, file present) → must read False.
    _write_json(data / "kill_switch_active.json", {"active": False, "reason": "resumed"})
    assert threat_reactor._kill_switch_active() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2) SELF HEAL
# ═══════════════════════════════════════════════════════════════════════════════


def test_self_heal_reports_missing_agent(monkeypatch):
    """An expected agent absent from launchctl list → dry-run reports it WOULD revive it."""
    expected = ["com.spa.autopush", "com.spa.daily_cycle", "com.spa.rules_watchdog"]
    loaded = {"com.spa.autopush": 1234, "com.spa.rules_watchdog": 4321}  # daily_cycle MISSING
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: list(expected))
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: dict(loaded))
    # Neutralise side-effect probes so the test is hermetic & deterministic.
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)

    report = self_heal.run_self_heal(dry_run=True)
    assert report["healthy"] is False
    assert any("would bootstrap com.spa.daily_cycle" in a for a in report["actions"]), report
    assert report["failures"] == []


def test_self_heal_healthy_when_all_present(monkeypatch):
    labels = ["com.spa.autopush", "com.spa.daily_cycle"]
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: list(labels))
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {x: 999 for x in labels})
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)

    report = self_heal.run_self_heal(dry_run=True)
    assert report["healthy"] is True
    assert report["actions"] == []
    assert report["failures"] == []


def test_self_heal_recovers_stale_cycle(monkeypatch):
    """A daily cycle older than CYCLE_GAP_HOURS → dry-run reports it would recover it."""
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.daily_cycle"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.daily_cycle": 1})
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    monkeypatch.setattr(
        self_heal, "_last_cycle_age_hours", lambda: self_heal.CYCLE_GAP_HOURS + 10.0
    )
    report = self_heal.run_self_heal(dry_run=True)
    assert any("would recover cycle" in a for a in report["actions"]), report


# ═══════════════════════════════════════════════════════════════════════════════
# 3) NAV RECONCILIATION (proof-of-reserves drift detection)
# ═══════════════════════════════════════════════════════════════════════════════


def test_nav_reconciliation_flags_drift(monkeypatch):
    """Components sum != reported equity → reconciliation_ok False (hidden value caught)."""
    monkeypatch.setattr(nav_proof, "_load_positions", lambda: {"aave_v3": 60000.0, "compound_v3": 30000.0})
    monkeypatch.setattr(nav_proof, "_load_cash", lambda: 5000.0)
    monkeypatch.setattr(nav_proof, "_load_accrued_yield", lambda: 0.0)
    # Reported headline equity is $100k but parts only sum to $95k → $5k drift.
    monkeypatch.setattr(nav_proof, "_load_reported_equity", lambda: 100000.0)

    nav = nav_proof.compute_nav()
    assert nav["computed_nav_usd"] == 95000.0
    assert nav["reconciliation_ok"] is False
    assert abs(nav["reconciliation_delta_usd"]) >= 5000.0


def test_nav_reconciliation_ok_with_accrued_yield(monkeypatch):
    """Parts + accrued yield == reported equity (within tolerance) → reconciliation_ok True,
    and verify_proof round-trips the published proof."""
    monkeypatch.setattr(nav_proof, "_load_positions", lambda: {"aave_v3": 60000.0, "compound_v3": 30000.0})
    monkeypatch.setattr(nav_proof, "_load_cash", lambda: 9850.0)
    monkeypatch.setattr(nav_proof, "_load_accrued_yield", lambda: 150.0)
    monkeypatch.setattr(nav_proof, "_load_reported_equity", lambda: 100000.0)

    nav = nav_proof.compute_nav()
    assert nav["computed_nav_usd"] == 100000.0
    assert nav["reconciliation_ok"] is True

    proof = nav_proof.build_proof(write=False)  # write=False → never touches real data/
    assert proof["reconciliation_ok"] is True
    assert nav_proof.verify_proof(proof) is True

    # Tamper with a published component → verify_proof must reject it.
    tampered = dict(proof)
    tampered["cash_usd"] = proof["cash_usd"] + 1000.0
    assert nav_proof.verify_proof(tampered) is False


def test_nav_reconciliation_no_reported_equity(monkeypatch):
    """No reported equity to reconcile against → reconciliation_ok False, handled gracefully."""
    monkeypatch.setattr(nav_proof, "_load_positions", lambda: {"aave_v3": 1000.0})
    monkeypatch.setattr(nav_proof, "_load_cash", lambda: 0.0)
    monkeypatch.setattr(nav_proof, "_load_accrued_yield", lambda: 0.0)
    monkeypatch.setattr(nav_proof, "_load_reported_equity", lambda: None)
    nav = nav_proof.compute_nav()
    assert nav["reconciliation_ok"] is False
    assert nav["reconciliation_delta_usd"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4) DATA INTEGRITY (no-lookahead / clean-series audit)
# ═══════════════════════════════════════════════════════════════════════════════


def _series_cache(points):
    return {"pool_results": {"aave_v3": {"apy_series": points}}}


def test_data_integrity_flags_future_date(tmp_path, monkeypatch):
    cache = tmp_path / "defillama_apy_history.json"
    future = (datetime.datetime.now(datetime.timezone.utc).date()
              + datetime.timedelta(days=30)).isoformat()
    _write_json(cache, _series_cache([
        {"date": "2026-01-01", "apy": 0.04},
        {"date": future, "apy": 0.04},
    ]))
    monkeypatch.setattr(di, "_CACHE", cache)
    out = di.audit(write=False)
    assert out["status"] == "ISSUES"
    assert out["total_issues"] >= 1
    assert any("future_date" in i for i in out["protocols"]["aave_v3"]["issues"])


def test_data_integrity_flags_out_of_band_apy(tmp_path, monkeypatch):
    cache = tmp_path / "defillama_apy_history.json"
    _write_json(cache, _series_cache([
        {"date": "2026-01-01", "apy": 0.04},
        {"date": "2026-01-02", "apy": 5.0},  # 500% → out of decimal band
    ]))
    monkeypatch.setattr(di, "_CACHE", cache)
    out = di.audit(write=False)
    assert out["status"] == "ISSUES"
    assert any("apy_out_of_band" in i for i in out["protocols"]["aave_v3"]["issues"])


def test_data_integrity_flags_out_of_order_dates(tmp_path, monkeypatch):
    cache = tmp_path / "defillama_apy_history.json"
    _write_json(cache, _series_cache([
        {"date": "2026-01-05", "apy": 0.04},
        {"date": "2026-01-02", "apy": 0.04},  # goes backwards
    ]))
    monkeypatch.setattr(di, "_CACHE", cache)
    out = di.audit(write=False)
    assert out["status"] == "ISSUES"
    assert any("out_of_order" in i for i in out["protocols"]["aave_v3"]["issues"])


def test_data_integrity_clean_series(tmp_path, monkeypatch):
    cache = tmp_path / "defillama_apy_history.json"
    _write_json(cache, _series_cache([
        {"date": "2026-01-01", "apy": 0.040},
        {"date": "2026-01-02", "apy": 0.041},
        {"date": "2026-01-03", "apy": 0.039},
    ]))
    monkeypatch.setattr(di, "_CACHE", cache)
    out = di.audit(write=False)
    assert out["status"] == "CLEAN"
    assert out["total_issues"] == 0
    assert out["protocols"]["aave_v3"]["clean"] is True


def test_data_integrity_missing_cache_no_data(tmp_path, monkeypatch):
    """Cache file absent → audit returns NO_DATA gracefully (never raises)."""
    monkeypatch.setattr(di, "_CACHE", tmp_path / "does_not_exist.json")
    out = di.audit(write=False)
    assert out["status"] == "NO_DATA"
    assert out["checked"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5) PIPELINE HEALTH (artifact freshness SLO)
# ═══════════════════════════════════════════════════════════════════════════════


def _seed_all_artifacts(data_dir, generated_at):
    """Write every expected Tier-1 artifact with a given generated_at timestamp."""
    for spec in ph.ARTIFACTS:
        path = data_dir / spec["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"generated_at": generated_at}))


def test_pipeline_health_critical_on_missing_core(tmp_path, monkeypatch):
    """A missing CORE artifact (tier1_verdict.json) → overall CRITICAL."""
    data = tmp_path / "data"
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(ph, "_DATA", data)
    _seed_all_artifacts(data, now.isoformat())
    (data / "tier1_verdict.json").unlink()  # remove a core artifact

    report = ph.check(now=now)
    assert report["overall"] == "CRITICAL"
    assert report["missing_count"] >= 1


def test_pipeline_health_critical_on_stale_core(tmp_path, monkeypatch):
    """A CORE artifact older than its SLO → overall CRITICAL."""
    data = tmp_path / "data"
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(ph, "_DATA", data)
    _seed_all_artifacts(data, now.isoformat())
    stale = (now - datetime.timedelta(hours=ph._DAILY_SLO_H + 5)).isoformat()
    (data / "tier1_gate.json").write_text(json.dumps({"generated_at": stale}))  # core, stale

    report = ph.check(now=now)
    assert report["overall"] == "CRITICAL"
    assert report["stale_count"] >= 1


def test_pipeline_health_degraded_on_stale_noncore(tmp_path, monkeypatch):
    """A NON-core artifact stale (cores fresh) → DEGRADED, not CRITICAL."""
    data = tmp_path / "data"
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(ph, "_DATA", data)
    _seed_all_artifacts(data, now.isoformat())
    stale = (now - datetime.timedelta(hours=ph._DAILY_SLO_H + 5)).isoformat()
    (data / "tier1_var.json").write_text(json.dumps({"generated_at": stale}))  # non-core

    report = ph.check(now=now)
    assert report["overall"] == "DEGRADED"
    assert report["stale_count"] >= 1


def test_pipeline_health_ok_when_all_fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(ph, "_DATA", data)
    _seed_all_artifacts(data, now.isoformat())
    report = ph.check(now=now)
    assert report["overall"] == "OK"
    assert report["stale_count"] == 0
    assert report["missing_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6) GATE FAIL-OPEN
# ═══════════════════════════════════════════════════════════════════════════════


def test_gate_fail_open_when_file_absent(tmp_path, monkeypatch):
    """Gate file missing → is_eligible returns True (fail-OPEN, never blocks ops on a
    missing Tier-1 run)."""
    monkeypatch.setattr(gate_mod, "_OUT", tmp_path / "tier1_gate.json")  # nonexistent
    assert gate_mod.is_eligible("any_strategy") is True


def test_gate_blocks_when_file_present_and_strategy_not_listed(tmp_path, monkeypatch):
    """When the gate IS present, only listed strategies are eligible (fail-open does not
    mask a real gate verdict)."""
    gate_file = tmp_path / "tier1_gate.json"
    _write_json(gate_file, {"eligible_for_paper": ["S1", "S2"]})
    monkeypatch.setattr(gate_mod, "_OUT", gate_file)
    assert gate_mod.is_eligible("S1") is True
    assert gate_mod.is_eligible("S99") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7) KILL-SWITCH TUPLE CONTRACT (regression guard)
# ═══════════════════════════════════════════════════════════════════════════════


def test_kill_switch_returns_bool_reason_tuple(tmp_path):
    """is_kill_switch_active() MUST return a (bool, reason) tuple. Callers that treat it as a
    bare bool would silently be 'always truthy' — this is the regression guard for that bug."""
    checker = KillSwitchChecker(data_dir=str(tmp_path))  # empty dir → all clear
    res = checker.is_kill_switch_active(equity_curve=[])
    assert isinstance(res, tuple) and len(res) == 2
    active, reason = res  # the correct unpacking contract
    assert active is False
    assert isinstance(reason, str) and reason


def test_kill_switch_manual_trigger_via_tuple(tmp_path):
    """A manual kill-switch file → tuple unpacks to (True, reason); inactive overwrite →
    (False, reason). Proves callers must inspect [0], not file existence / truthiness."""
    checker = KillSwitchChecker(data_dir=str(tmp_path))
    _write_json(tmp_path / "kill_switch_active.json", {"active": True, "reason": "chaos test"})
    active, reason = checker.is_kill_switch_active(equity_curve=[])
    assert active is True
    assert "manual" in reason.lower() or "chaos" in reason.lower()

    # active=False overwrite (sandbox can't unlink) must NOT trip the switch.
    _write_json(tmp_path / "kill_switch_active.json", {"active": False, "reason": "resumed"})
    active2, _ = checker.is_kill_switch_active(equity_curve=[])
    assert active2 is False


def test_kill_switch_drawdown_trigger_via_tuple(tmp_path):
    """A >15% drawdown equity curve → (True, reason) with the drawdown reason."""
    checker = KillSwitchChecker(data_dir=str(tmp_path))
    # Bars must be dated post-anchor + evidenced so the drawdown trigger (which
    # now operates strictly over the REAL evidenced series) sees them.
    curve = [
        {"date": "2026-06-12", "close_equity": 100000.0,
         "source": "cycle", "evidenced": True},
        {"date": "2026-06-13", "close_equity": 80000.0,
         "source": "cycle", "evidenced": True},  # -20%
    ]
    active, reason = checker.is_kill_switch_active(equity_curve=curve)
    assert active is True
    assert "drawdown" in reason.lower()
