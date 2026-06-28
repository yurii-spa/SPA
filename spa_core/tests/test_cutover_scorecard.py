"""WS-3.6 — CUTOVER READINESS SCORECARD tests.

Proves ``cutover_scorecard.build_scorecard`` produces an HONEST readiness report:

  * a CODE-readiness % derived from the proven WS-3.x inert defenses;
  * ready_for_live / is_live / would_cutover ALWAYS False (owner-gated flip);
  * owner-only blockers explicitly NAMED (custody / capital / audit / track / flip);
  * the schema is a SUPERSET of readiness_audit (posture/checks/live_blockers kept);
  * INERT + read-only — writes ONLY data/execution_readiness.json, deterministic.

stdlib + pytest only. No network, no chain, no capital.
"""
from __future__ import annotations

import json

import pytest

from spa_core.execution import cutover_scorecard as cs


@pytest.fixture()
def clean_env(monkeypatch):
    from spa_core.execution import readiness_audit as ra
    for name in (ra.EXECUTION_MODE_ENV, *ra.SIGNER_KEY_ENVS):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


# ── Shape + honesty ─────────────────────────────────────────────────────────

def test_scorecard_shape(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    for key in ("audited_at", "version", "posture", "ready_for_live", "live_blockers",
                "checks", "code_defenses", "code_readiness_pct", "code_defenses_total",
                "code_defenses_proven", "owner_only_blockers", "is_live", "would_cutover"):
        assert key in rep, key
    assert isinstance(rep["code_readiness_pct"], float)
    assert 0.0 <= rep["code_readiness_pct"] <= 100.0


def test_inert_and_owner_gated(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    # The flip is owner-gated — these are ALWAYS False regardless of code readiness.
    assert rep["is_live"] is False
    assert rep["would_cutover"] is False
    assert rep["ready_for_live"] is False
    assert rep["moves_capital"] is False


def test_owner_only_blockers_named(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    blob = " ".join(rep["owner_only_blockers"]).lower()
    for needle in ("custody", "capital", "audit", "track", "is_live"):
        assert needle in blob, needle


def test_code_defenses_cover_ws3_chain(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    names = {d["defense"] for d in rep["code_defenses"]}
    # Every WS-3.x defense must be scored.
    for expected in (
        "gate_chain_ordered_total_fail_closed",
        "reconciliation_fail_closed",
        "signer_nonce_guard",
        "multisig_signable_guard",
        "mev_guard_abort",
        "e2e_full_chain_inert",
        "pre_cutover_money_path_defenses",
    ):
        assert expected in names, expected


def test_proven_count_matches_pct(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    proven = sum(1 for d in rep["code_defenses"] if d["proven"])
    assert rep["code_defenses_proven"] == proven
    expected_pct = round(100.0 * proven / rep["code_defenses_total"], 1)
    assert rep["code_readiness_pct"] == expected_pct


def test_core_ws3_defenses_proven(clean_env, data_dir):
    """The WS-3.1..3.5 hardened defenses should each score PROVEN in this repo."""
    rep = cs.build_scorecard(data_dir=data_dir)
    by_name = {d["defense"]: d for d in rep["code_defenses"]}
    for name in (
        "gate_chain_ordered_total_fail_closed",
        "reconciliation_fail_closed",
        "signer_nonce_guard",
        "multisig_signable_guard",
        "mev_guard_abort",
        "e2e_full_chain_inert",
    ):
        assert by_name[name]["proven"] is True, name


# ── ready_for_live stays False even with a fully-satisfied posture audit ────

def test_ready_for_live_false_even_when_posture_audit_ready(monkeypatch, tmp_path):
    """Even if the posture self-audit says ready, the live-gate-locked check pins
    ready_for_live False (the human flip never armed the gate)."""
    from spa_core.execution import readiness_audit as ra
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv(ra.EXECUTION_MODE_ENV, "live")
    monkeypatch.setenv("SPA_PRIVATE_KEY", "0x" + "cd" * 32)
    (d / "paper_trading_status.json").write_text(json.dumps({"days_running": 45}))
    (d / "golive_status.json").write_text(json.dumps({"ready": True, "passed": 29, "total": 29}))
    (d / "external_audit_attestation.json").write_text(json.dumps({"passed": True}))
    rep = cs.build_scorecard(data_dir=d)
    # The LiveTradingGate is LOCKED → ready_for_live must stay False (owner flip).
    assert rep["live_trading_gate_locked"] is True
    assert rep["ready_for_live"] is False
    assert rep["would_cutover"] is False


# ── Superset schema: readiness_audit keys preserved ─────────────────────────

def test_superset_of_readiness_audit(clean_env, data_dir):
    rep = cs.build_scorecard(data_dir=data_dir)
    assert rep["posture"] in ("PAPER_SAFE", "POSTURE_AT_RISK")
    assert isinstance(rep["checks"], dict)
    assert isinstance(rep["live_blockers"], list)


# ── Atomic write + read-only ────────────────────────────────────────────────

def test_build_report_writes_only_the_report(clean_env, data_dir):
    before = set(p.name for p in data_dir.iterdir())
    cs.build_report(write=True, data_dir=data_dir)
    after = set(p.name for p in data_dir.iterdir())
    assert (after - before) == {cs._REPORT_FILENAME}
    on_disk = json.loads((data_dir / cs._REPORT_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["would_cutover"] is False
    assert on_disk["is_live"] is False
    assert "code_readiness_pct" in on_disk


def test_build_report_no_write(clean_env, data_dir):
    cs.build_report(write=False, data_dir=data_dir)
    assert not (data_dir / cs._REPORT_FILENAME).exists()


def test_determinism(clean_env, data_dir):
    a = cs.build_scorecard(data_dir=data_dir)
    b = cs.build_scorecard(data_dir=data_dir)
    a.pop("audited_at")
    b.pop("audited_at")
    assert a == b


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:randomly"]))
