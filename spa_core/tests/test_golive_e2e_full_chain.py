"""WS-3.5 — END-TO-END INERT FULL-CHAIN DRY-RUN tests.

Proves that ``golive_dry_run.e2e_full_chain`` walks a REAL allocation through
EVERY pre-broadcast defense (gate_chain → reconciliation → signer-nonce →
multisig-signable → mev-guard) and that:

  * the chain is TOTAL + ORDERED (a reorder/skip would be caught);
  * the INERT invariant holds — is_live False, would_cutover False, NO real
    sign, NO real broadcast (zero on-chain side effects);
  * red-team — a malicious/over-cap allocation is REJECTED at the gate chain
    BEFORE it could ever reach the signer (reached_signer=False);
  * red-team — a gas-spike / stale-oracle makes the MEV guard ABORT (no submit);
  * red-team — an unsignable multisig is BLOCKED; a nonce gap is BLOCKED;
  * the harness writes ONLY data/golive_e2e_dry_run.json and is deterministic.

stdlib + pytest only. No network, no chain, no capital.
"""
from __future__ import annotations

import json

import pytest

from spa_core.execution import golive_dry_run as gdr
from spa_core.execution.golive_dry_run import (
    EXPECTED_E2E_CHAIN_ORDER,
    build_e2e_report,
    e2e_full_chain,
)

REAL_ALLOC = {"aave_v3": 30_000.0, "compound_v3": 20_000.0, "morpho_blue": 15_000.0}


def _verdict(report, name):
    return next(d for d in report["chain"] if d["name"] == name)["verdict"]


# ── Chain is total + ordered ────────────────────────────────────────────────

def test_full_chain_total_and_ordered():
    rep = e2e_full_chain(REAL_ALLOC)
    reached = [d["name"] for d in rep["chain"]]
    assert reached == list(EXPECTED_E2E_CHAIN_ORDER)
    assert rep["all_defenses_reached"] is True
    assert rep["ordering_ok"] is True
    assert len(rep["chain"]) == 5


def test_clean_walk_every_defense_passes():
    rep = e2e_full_chain(REAL_ALLOC)
    for name in EXPECTED_E2E_CHAIN_ORDER:
        assert _verdict(rep, name) == "PASS", name
    assert rep["every_defense_ok"] is True
    assert rep["reached_signer"] is True


# ── INERT invariant: zero side effects, is_live/would_cutover False ─────────

def test_inert_invariant_holds():
    rep = e2e_full_chain(REAL_ALLOC)
    assert rep["is_live"] is False
    assert rep["would_cutover"] is False
    assert rep["moves_capital"] is False
    assert rep["no_real_sign"] is True
    assert rep["no_real_broadcast"] is True
    assert rep["inert_invariant_held"] is True
    assert gdr._IS_LIVE is False


def test_would_cutover_pinned_false_across_allocations():
    for alloc in (REAL_ALLOC, {"aave_v3": 5_000.0}, {"yearn_v3": 2_000.0}, {}):
        rep = e2e_full_chain(alloc)
        assert rep["would_cutover"] is False
        assert rep["is_live"] is False


# ── RED-TEAM: malicious / over-cap allocation rejected PRE-SIGN ─────────────

@pytest.mark.parametrize("inj", [{"malicious_over_cap": True}, {"over_concentration": True}])
def test_malicious_allocation_rejected_before_signer(inj):
    rep = e2e_full_chain(REAL_ALLOC, inject=inj)
    # The gate chain correctly rejected the over-cap allocation...
    assert _verdict(rep, "gate_chain") == "PASS"  # PASS == "correctly rejected it"
    assert rep["alloc_rejected_pre_sign"] is True
    # ...so the signer / multisig / broadcast defenses are NEVER reached.
    assert rep["reached_signer"] is False
    assert _verdict(rep, "signer_nonce") == "NOT_REACHED"
    assert _verdict(rep, "multisig_signable") == "NOT_REACHED"
    assert _verdict(rep, "mev_guard") == "NOT_REACHED"
    # Inert invariant still holds — nothing signed, nothing broadcast.
    assert rep["no_real_broadcast"] is True
    assert rep["inert_invariant_held"] is True
    assert rep["would_cutover"] is False
    # Still total + ordered.
    assert rep["ordering_ok"] is True


# ── RED-TEAM: gas-spike / stale-oracle → MEV guard ABORT (no broadcast) ─────

@pytest.mark.parametrize("inj", [{"gas_spike_mult": 4.0}, {"stale_oracle": True}])
def test_mev_guard_aborts_no_broadcast(inj):
    rep = e2e_full_chain(REAL_ALLOC, inject=inj)
    # The MEV guard ABORTed → the defense did the right thing (verdict PASS).
    assert _verdict(rep, "mev_guard") == "PASS"
    assert rep["no_real_broadcast"] is True
    assert rep["inert_invariant_held"] is True
    # Earlier defenses still pass (the alloc itself is clean).
    assert rep["reached_signer"] is True
    assert rep["would_cutover"] is False


# ── RED-TEAM: unsignable multisig BLOCKED ───────────────────────────────────

def test_unsignable_multisig_blocked():
    rep = e2e_full_chain(REAL_ALLOC, inject={"unsignable_multisig": True})
    # The multisig guard refused the unsignable 2-of-1 config (verdict PASS).
    assert _verdict(rep, "multisig_signable") == "PASS"
    assert rep["inert_invariant_held"] is True


# ── RED-TEAM: nonce gap BLOCKED pre-sign ────────────────────────────────────

def test_nonce_gap_blocked_pre_sign():
    rep = e2e_full_chain(REAL_ALLOC, inject={"nonce_gap": True})
    # The nonce guard refused the gap (verdict PASS == correctly blocked).
    assert _verdict(rep, "signer_nonce") == "PASS"
    # No real sign EVER happened — assert_nonce_ok is a pure validator.
    assert rep["no_real_sign"] is True


# ── Determinism ─────────────────────────────────────────────────────────────

def test_deterministic_chain_verdicts():
    a = e2e_full_chain(REAL_ALLOC)
    b = e2e_full_chain(REAL_ALLOC)
    assert [d["verdict"] for d in a["chain"]] == [d["verdict"] for d in b["chain"]]
    assert a["ordering_ok"] == b["ordering_ok"] is True
    assert a["would_cutover"] == b["would_cutover"] is False


# ── I/O scope: only data/golive_e2e_dry_run.json is written ─────────────────

def test_writes_only_e2e_report(tmp_path, monkeypatch):
    out = tmp_path / "golive_e2e_dry_run.json"
    monkeypatch.setattr(gdr, "_E2E_OUT", out)
    before = set(p.name for p in tmp_path.iterdir())
    build_e2e_report(write=True, cycle_output=REAL_ALLOC)
    after = set(p.name for p in tmp_path.iterdir())
    assert (after - before) == {"golive_e2e_dry_run.json"}
    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["would_cutover"] is False
    assert persisted["is_live"] is False
    assert persisted["ordering_ok"] is True


def test_build_e2e_report_no_write(tmp_path, monkeypatch):
    out = tmp_path / "golive_e2e_dry_run.json"
    monkeypatch.setattr(gdr, "_E2E_OUT", out)
    build_e2e_report(write=False, cycle_output=REAL_ALLOC)
    assert not out.exists()


# ── Empty allocation still walks the full chain, stays inert ────────────────

def test_empty_allocation_still_total_and_inert():
    rep = e2e_full_chain({})
    assert rep["ordering_ok"] is True
    assert rep["would_cutover"] is False
    assert rep["no_real_broadcast"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:randomly"]))
