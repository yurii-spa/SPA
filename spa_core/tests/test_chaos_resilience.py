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
    """A RESIDENT-required agent (KeepAlive / StartInterval) absent from launchctl
    list → dry-run reports it WOULD revive it, and is unhealthy."""
    expected = ["com.spa.autopush", "com.spa.rules_watchdog", "com.spa.apiserver"]
    loaded = {"com.spa.autopush": 1234, "com.spa.rules_watchdog": 4321}  # apiserver MISSING
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: list(expected))
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: dict(loaded))
    # All three are residency-required (the down apiserver must be revived).
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda lbl: True)
    # Neutralise side-effect probes so the test is hermetic & deterministic.
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)

    report = self_heal.run_self_heal(dry_run=True)
    assert report["healthy"] is False
    assert any("would bootstrap com.spa.apiserver" in a for a in report["actions"]), report
    assert report["missing_resident"] == ["com.spa.apiserver"]
    assert report["failures"] == []


def test_self_heal_does_not_bootstrap_idle_calendar_agent(monkeypatch):
    """A calendar/one-time agent (RunAtLoad:False) that has correctly EXITED
    between scheduled runs is NOT resident — self_heal must NOT churn-bootstrap it
    and the fleet stays healthy (this is the chronic false-CRITICAL loop fix)."""
    expected = ["com.spa.autopush", "com.spa.telegram_daily"]
    loaded = {"com.spa.autopush": 1234}  # telegram_daily not resident (idle, correct)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: list(expected))
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: dict(loaded))
    # autopush is a resident guardian; telegram_daily is an idle calendar agent.
    monkeypatch.setattr(
        self_heal, "_must_be_resident",
        lambda lbl: lbl != "com.spa.telegram_daily",
    )
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)

    report = self_heal.run_self_heal(dry_run=True)
    # No bootstrap of the idle calendar agent; nothing missing among residents.
    assert not any("telegram_daily" in a for a in report["actions"]), report
    assert report["missing_resident"] == []
    assert report["idle_calendar_skipped"] == 1
    assert report["healthy"] is True


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


# ═══════════════════════════════════════════════════════════════════════════════
# 8) DAILY-CYCLE FAULT INJECTION — SAFE DEGRADATION (track-corruption hazard)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Sprint Task 5. The sections above prove the DETECTION modules work in
# isolation. This section drives the REAL ``cycle_runner.run_cycle`` end-to-end
# against realistic faults and asserts the daily cycle degrades SAFELY: each
# fault → the cycle either completes cleanly OR aborts WITHOUT mutating live
# state into a corrupt/torn/duplicated/discontinuous equity curve, and the NEXT
# cycle recovers. This is the regression guard for the 2026-06-25 track
# corruption (ad-hoc runs mutated the live track).
#
# Hermetic: every run targets an explicit ``tmp_path`` data dir (an explicit
# NON-canonical dir is honoured verbatim by the write-interlock, so the real
# repo ``data/`` is NEVER read or written). Orchestrator / allocator / risk
# scorer / track persister are in-process fakes (network-free). Timestamps are
# pinned so the per-UTC-day idempotency verdict is deterministic.

import logging as _logging  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
from types import SimpleNamespace as _NS  # noqa: E402

from spa_core.paper_trading import cycle_runner as _cr  # noqa: E402
from spa_core.paper_trading._cycle_io import EQUITY_FILENAME as _EQF  # noqa: E402
from spa_core.paper_trading._cycle_io import STATUS_FILENAME as _STF  # noqa: E402
from spa_core.utils import atomic as _atomic  # noqa: E402


# A policy-compliant target: T1 aave ≤40%, one T2 ≤20%, T2 total ≤50%, cash >5%
# → the cycle is APPROVED so it actually accrues yield (lets us assert a
# continuous, monotonically-advancing real curve across days).
_CLEAN_TARGET = {"aave_v3": 35_000.0, "compound_v3": 20_000.0}


def _clean_orch(data_dir):
    adapters = [
        {
            "protocol": p,
            "apy_pct": 4.0,
            "tvl_usd": 1e7,
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
        }
        for p in _CLEAN_TARGET
    ]
    return _NS(adapters=adapters, status="ok", data_freshness="live")


def _stale_orch(data_dir):
    """Stale/empty adapter feed: no usable live APY (the P5-1 / N3 fault)."""
    return _NS(adapters=[], status="no_live_data", data_freshness="stale")


class _CleanAllocator:
    def allocate(self):
        return _NS(
            target_usd=dict(_CLEAN_TARGET),
            target_weights={p: v / 100_000 for p, v in _CLEAN_TARGET.items()},
            expected_apy_pct=4.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run_chaos_cycle(ddir, now, *, orch=_clean_orch):
    """Drive the REAL run_cycle against an explicit (non-canonical) tmp data dir.

    The orchestrator/allocator/scorer/persister are network-free fakes. The dir
    is explicit + non-canonical, so the write-interlock honours it verbatim and
    the real repo data/ is never touched.
    """
    return _cr.run_cycle(
        data_dir=str(ddir),
        now=now,
        orchestrator_fn=orch,
        allocator=_CleanAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


def _assert_curve_valid_and_continuous(ddir):
    """Assert equity_curve_daily.json is parseable, has unique ascending dates,
    no torn/partial content, and is monotonically forward in time. Returns the
    list of (date, close_equity) for further per-test assertions."""
    path = ddir / _EQF
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)  # raises if torn/partial → proves no torn canonical
    daily = doc.get("daily") or []
    dates = [b["date"] for b in daily]
    # No duplicate same-day bars (idempotency invariant).
    assert len(dates) == len(set(dates)), f"duplicate equity bars: {dates}"
    # Strictly ascending dates (continuity / no out-of-order corruption).
    assert dates == sorted(dates), f"equity dates not ascending: {dates}"
    # Every bar has a finite, positive close_equity (no NaN/garbage accrual).
    for b in daily:
        ce = b.get("close_equity")
        assert isinstance(ce, (int, float)) and ce == ce and ce > 0, b
    return [(b["date"], float(b["close_equity"])) for b in daily]


@pytest.fixture(autouse=False)
def _quiet_cycle_logs():
    """Silence the cycle's verbose WARNING/INFO chatter during fault injection."""
    prev = _logging.getLogger().manager.disable
    _logging.disable(_logging.CRITICAL)
    try:
        yield
    finally:
        _logging.disable(prev)


# ── FAULT 1: stale / empty adapter feed → no fabricated APY, no garbage bar ───


def test_fault_stale_feed_skips_without_garbage_bar(tmp_path, _quiet_cycle_logs):
    """A stale/empty adapter feed (no usable live APY) → the cycle takes the
    fail-closed no-live-data path: status='skipped_no_live_data', zero yield, and
    it does NOT append a fabricated equity bar for that day. The prior real curve
    is left intact, and the NEXT cycle (feed restored) recovers and advances it."""
    # Day 1: healthy → one real bar.
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 11, 8, tzinfo=_tz.utc))
    before = _assert_curve_valid_and_continuous(tmp_path)
    assert [d for d, _ in before] == ["2026-06-11"]

    # Day 2: stale feed.
    r = _run_chaos_cycle(
        tmp_path, _dt(2026, 6, 12, 8, tzinfo=_tz.utc), orch=_stale_orch
    )
    assert r.status == "skipped_no_live_data"
    assert r.live_data is False
    assert r.daily_yield_usd == 0.0
    # No fabricated bar for the stale day — curve unchanged (still 1 bar).
    after = _assert_curve_valid_and_continuous(tmp_path)
    assert [d for d, _ in after] == ["2026-06-11"], "stale feed fabricated a bar!"

    # Day 3: feed restored → recovers, advances the curve, stays continuous.
    r3 = _run_chaos_cycle(tmp_path, _dt(2026, 6, 13, 8, tzinfo=_tz.utc))
    assert r3.status == "ok"
    recov = _assert_curve_valid_and_continuous(tmp_path)
    assert [d for d, _ in recov] == ["2026-06-11", "2026-06-13"]


# ── FAULT 2: torn / partial JSON write (crash mid-write) ──────────────────────


def test_fault_atomic_write_crash_leaves_old_complete_file(tmp_path):
    """A crash DURING the equity write must leave the canonical file as the OLD
    COMPLETE version (os.replace is atomic — it never ran), NEVER a torn file, and
    must leave no .tmp turd behind. This is the core atomic-write guarantee the
    whole cycle relies on (tmp + os.replace)."""
    target = tmp_path / _EQF
    old = {"source": "cycle_runner", "daily": [
        {"date": "2026-06-11", "close_equity": 100_000.0}]}
    _atomic.atomic_save(old, str(target))
    old_bytes = target.read_bytes()

    real_dump = json.dump

    def _boom(obj, fh, *a, **k):  # write partial bytes then crash mid-write
        fh.write('{"source":"cycle_runner","daily":[{"date":"2026-06-12","clo')
        raise RuntimeError("simulated crash mid-write")

    json.dump = _boom
    try:
        with pytest.raises(RuntimeError):
            _atomic.atomic_save({"new": "doc"}, str(target))
    finally:
        json.dump = real_dump

    # Canonical is byte-identical to the old COMPLETE file → never torn.
    assert target.read_bytes() == old_bytes
    # And it still parses cleanly (no partial read as canonical).
    assert json.loads(target.read_text())["daily"][0]["date"] == "2026-06-11"
    # No leftover tmp file in the dir.
    assert list(tmp_path.glob("*.tmp")) == []


def test_fault_preexisting_torn_equity_file_recovers(tmp_path, _quiet_cycle_logs):
    """If a torn/partial equity file somehow exists on disk (worst case), the
    cycle's defensive read must not crash on it — it recovers and the next write
    produces a VALID, parseable curve (never propagates the torn content)."""
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 11, 8, tzinfo=_tz.utc))
    # Corrupt the canonical equity file out-of-band (truncated mid-object).
    (tmp_path / _EQF).write_text(
        '{"source":"cycle_runner","daily":[{"date":"2026-06-11","clo'
    )
    # Next cycle must not raise, and must leave a valid curve behind.
    r = _run_chaos_cycle(tmp_path, _dt(2026, 6, 12, 8, tzinfo=_tz.utc))
    assert r.status in ("ok", "blocked_by_policy", "skipped_no_live_data")
    _assert_curve_valid_and_continuous(tmp_path)  # parses → no torn canonical


# ── FAULT 3: missing data file (current_positions.json absent) ────────────────


def test_fault_missing_positions_file_no_crash(tmp_path, _quiet_cycle_logs):
    """A missing current_positions.json (lost/deleted) must fail-closed to an
    empty position set — the cycle does NOT crash and the equity curve stays
    valid and continuous."""
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 11, 8, tzinfo=_tz.utc))
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 12, 8, tzinfo=_tz.utc))
    # Lose the positions file.
    (tmp_path / "current_positions.json").unlink()
    r = _run_chaos_cycle(tmp_path, _dt(2026, 6, 13, 8, tzinfo=_tz.utc))
    assert r.status in ("ok", "blocked_by_policy")
    curve = _assert_curve_valid_and_continuous(tmp_path)
    assert [d for d, _ in curve] == ["2026-06-11", "2026-06-12", "2026-06-13"]


# ── FAULT 4: clock skew / duplicate same-day run → idempotent ─────────────────


def test_fault_duplicate_same_day_run_is_idempotent(tmp_path, _quiet_cycle_logs):
    """Two cycles on the SAME UTC day (e.g. a clock-skew double-fire or a manual
    re-run) must NOT append a second bar for that day, must NOT double-accrue
    yield, and must recompute the bar off the PRIOR day's close (idempotent)."""
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 11, 8, tzinfo=_tz.utc))
    r2a = _run_chaos_cycle(tmp_path, _dt(2026, 6, 12, 8, tzinfo=_tz.utc))
    # Re-run the SAME day at a different wall-clock time.
    r2b = _run_chaos_cycle(tmp_path, _dt(2026, 6, 12, 23, 59, tzinfo=_tz.utc))

    curve = _assert_curve_valid_and_continuous(tmp_path)
    dates = [d for d, _ in curve]
    assert dates == ["2026-06-11", "2026-06-12"], f"same-day duplicate: {dates}"
    # The re-run must reproduce the SAME close (no double-accrual / compounding).
    assert r2b.current_equity == pytest.approx(r2a.current_equity, abs=0.01)


# ── FAULT 5: killed mid-cycle (equity written, status not) → next cycle recovers


def test_fault_killed_after_equity_before_status_recovers(tmp_path, _quiet_cycle_logs):
    """Process dies AFTER the equity bar is written but BEFORE the status file is
    refreshed (torn cross-file state). The next cycle must reconcile: it advances
    to the new day, updates the stale status, and does NOT duplicate the
    already-written bar. No torn/duplicated equity state survives."""
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 11, 8, tzinfo=_tz.utc))
    _run_chaos_cycle(tmp_path, _dt(2026, 6, 12, 8, tzinfo=_tz.utc))

    # Simulate the crash: append a day-13 equity bar but DON'T update the status
    # (status still reflects day-12 → the cross-file state is torn).
    eq = json.loads((tmp_path / _EQF).read_text())
    last = eq["daily"][-1]
    bar13 = dict(last)
    bar13.update({
        "date": "2026-06-13",
        "open_equity": last["close_equity"],
        "close_equity": round(last["close_equity"] + 6.0, 2),
        "equity": round(last["close_equity"] + 6.0, 2),
    })
    eq["daily"].append(bar13)
    _atomic.atomic_save(eq, str(tmp_path / _EQF))
    status_before = json.loads((tmp_path / _STF).read_text())
    assert str(status_before.get("last_cycle_ts", ""))[:10] == "2026-06-12"

    # Next cycle = day 14. It must recover without duplicating day-13.
    r = _run_chaos_cycle(tmp_path, _dt(2026, 6, 14, 8, tzinfo=_tz.utc))
    curve = _assert_curve_valid_and_continuous(tmp_path)
    dates = [d for d, _ in curve]
    assert dates == ["2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14"]
    assert dates.count("2026-06-13") == 1, "recovery duplicated the day-13 bar"
    # Status reconciled forward to the recovery day.
    status_after = json.loads((tmp_path / _STF).read_text())
    assert str(status_after.get("last_cycle_ts", ""))[:10] == "2026-06-14"
    assert r.status in ("ok", "blocked_by_policy")


# ── Cross-cutting: a fault run must NEVER touch the canonical live track ───────


def test_fault_runs_never_touch_canonical_track(tmp_path, monkeypatch):
    """Defense-in-depth: even a DEFAULT (no data_dir, no opt-in) cycle under the
    interlock must redirect to a sandbox, never the canonical repo data/. Pin the
    'canonical' dir to a temp dir so this assertion can never touch real data/."""
    from spa_core.paper_trading import _cycle_io as _cio

    canon = tmp_path / "data"
    canon.mkdir()
    monkeypatch.setattr(_cio, "_DEFAULT_DATA_DIR", canon, raising=True)
    monkeypatch.setattr(_cr, "_DEFAULT_DATA_DIR", canon, raising=True)
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path / "sbx"))
    monkeypatch.delenv("SPA_ALLOW_LIVE_WRITE", raising=False)

    _logging.disable(_logging.CRITICAL)
    try:
        _cr.run_cycle(
            data_dir=None,
            now=_dt(2026, 6, 11, 8, tzinfo=_tz.utc),
            orchestrator_fn=_clean_orch,
            allocator=_CleanAllocator(),
            risk_scorer_fn=lambda d: None,
            track_persister_fn=lambda d: None,
            write=True,
            allow_live_write=False,
        )
    finally:
        _logging.disable(_logging.NOTSET)

    # The canonical equity curve was never created; the sandbox got the write.
    assert not (canon / _EQF).exists(), "fault run mutated the canonical track!"
    assert (tmp_path / "sbx" / _EQF).exists()
