"""The 24-scenario ACTUALLY INDUCED failure matrix for the Research Factory (ADR-560), run
through the real code (``spa_core.research_factory.failure_matrix``) and asserted green here —
plus a few explicit mutation checks proving specific scenarios are guard-sensitive, not
vacuously true.

No literal date lives in this file (it only calls into failure_matrix.py's own NOW anchor by
reference, via ``fm.NOW``) — the frozen-date ratchet does not apply here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spa_core.research_factory import contract, failure_matrix as fm


def test_at_least_22_scenarios_declared():
    assert len(fm.CASES) >= 22
    assert len({c.id for c in fm.CASES}) == len(fm.CASES)  # unique ids


def test_every_scenario_is_actually_induced_and_passes():
    rows = fm.run_all()
    failed = [r for r in rows if not r["pass"]]
    assert not failed, "\n".join(f"{r['id']} {r['scenario']}: expected {r['expected']!r}, "
                                 f"observed {r['observed']!r}" for r in failed)
    for r in rows:
        assert r["induced"], f"{r['id']} names no induced condition"
        assert r["expected"] is not None
        assert "observed" in r


def test_cli_writes_json_and_returns_nonzero_on_failure(tmp_path, monkeypatch):
    out = tmp_path / "fm.json"
    rc = fm.main(["--out", str(out)])
    assert rc == 0
    assert out.exists()
    import json
    rows = json.loads(out.read_text())
    assert len(rows) == len(fm.CASES)


def test_cli_returns_nonzero_when_a_scenario_is_broken(tmp_path, monkeypatch):
    broken_case = fm.Case("FM-BROKEN", "a scenario forced to fail", lambda tmp: ("x", "y", "z", False))
    monkeypatch.setattr(fm, "CASES", fm.CASES + [broken_case])
    out = tmp_path / "fm2.json"
    rc = fm.main(["--out", str(out)])
    assert rc == 1


# ── targeted mutation checks: prove specific scenarios are guard-sensitive ─────────────────

def test_mutation_check_stale_scenario_is_sensitive_to_the_freshness_window(monkeypatch, tmp_path):
    """FM-01 (stale APY) must flip to NOT-stale if the freshness window were widened enough to
    cover the induced age — proving the scenario actually depends on the live freshness window,
    not on a hard-coded expectation.

    Round 5 (ADR-564 binding #1) re-verification, 2026-10-04: FM-01 now runs through the real
    v2 pipeline (``run._sherlock_review_candidate``, since v1's own admission.evaluate() is
    display-only and no longer drives the lifecycle). v2's freshness check
    (``grades.freshness_verdict``) reads ``evidence_contract.FRESHNESS``, a DIFFERENT table from
    v1's ``contract.FRESHNESS_MAX_AGE_H`` (which v2 never consults) — patching the v1 table here
    left this check silently vacuous (observed stayed STALE either way) until corrected."""
    from spa_core.research_factory import evidence_contract as ec
    wide = {k: dict(v) for k, v in ec.FRESHNESS.items()}
    wide["rate"]["max_age_h"] = 24.0 * 365  # a window wide enough to swallow the induced 10-day staleness
    monkeypatch.setattr(ec, "FRESHNESS", wide)
    row = fm._c01_stale_apy(tmp_path)
    induced, expected, observed, ok = row
    assert observed != contract.STALE_STATE, (
        "widening evidence_contract.FRESHNESS did not change the observed outcome — FM-01 is not "
        "actually exercising the freshness window, it is a hard-coded assertion")


def test_mutation_check_duplicate_scenario_is_sensitive_to_dedup_being_disabled(monkeypatch, tmp_path):
    """FM-06 (duplicate from two scanners) collapses to ONE candidate via registry keying, not
    via admission's no_duplicate_exposure gate — this proves THAT mechanism specifically: if
    registry.upsert's fingerprint-keyed idempotency is bypassed (simulated by forcing a
    DIFFERENT candidate_id on the second write, as real corruption would), two rows appear."""
    from spa_core.research_factory import registry
    from spa_core.research_factory._common import ledger_for
    c1 = fm.base_candidate(venue_or_protocol="scanner_a")
    c2 = fm.base_candidate(venue_or_protocol="scanner_b")
    c2["candidate_id"] = "corrupted-different-id"  # simulates the registry-keying guard failing
    registry.upsert(tmp_path, c1, fm.NOW)
    registry.upsert(tmp_path, c2, fm.NOW)
    ids = registry.all_candidate_ids(ledger_for(tmp_path))
    assert len(ids) == 2, (
        "forcing a different candidate_id still produced ONE row — the dedup test below would "
        "be vacuous if registry keying could not be defeated at all")


def test_mutation_check_no_conflicted_inputs_gate_catches_a_conflicted_cell():
    """Direct, minimal mutation check on admission._no_conflicted_inputs: a CONFLICTED cell on
    ANY cell field must FAIL the gate; removing the check (simulated by calling the gate on an
    object that never has a CONFLICTED cell) must PASS — showing the assertion is sensitive."""
    from spa_core.research_factory import admission
    c = fm.base_candidate()
    clean = admission._no_conflicted_inputs(c)
    assert clean["verdict"] == contract.GATE_PASS
    c["liquidity"] = contract.cell(contract.CONFLICTED, reason="independent roots disagree")
    conflicted = admission._no_conflicted_inputs(c)
    assert conflicted["verdict"] == contract.GATE_FAIL


def test_mutation_check_restart_idempotency_is_sensitive_to_a_real_second_write(tmp_path, monkeypatch):
    """FM-22 (restart idempotency) must be sensitive to an ACTUAL new write happening: if we
    force a genuinely different candidate in between the two run_once calls, the row count
    SHOULD grow — proving the matching row-count assertion in FM-22 is not just always-equal."""
    import spa_core.research_factory.run as run_mod
    from spa_core.research_factory import registry
    from spa_core.research_factory._common import ledger_for
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    c = fm.base_candidate()
    registry.upsert(tmp_path, c, fm.NOW)
    run_mod.run_once(tmp_path, fm.NOW)
    n1 = len(ledger_for(tmp_path).read_all())
    # a genuinely NEW candidate between the two runs
    c2 = fm.base_candidate(venue_or_protocol="a_truly_new_scanner", instrument_id="ethereum:0x" + "77" * 20)
    registry.upsert(tmp_path, c2, fm.NOW)
    run_mod.run_once(tmp_path, fm.NOW)
    n2 = len(ledger_for(tmp_path).read_all())
    assert n2 > n1, "a genuinely new candidate between two runs produced no new rows at all"
