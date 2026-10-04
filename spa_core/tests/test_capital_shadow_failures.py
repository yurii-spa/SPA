"""Failure-model tests for RM-LIVE-01 capital_shadow (ADR-556 WP-A06).

Runs the induced failure matrix (``spa_core.capital_shadow.failure_matrix``) against a disposable
tmp data dir and requires every row to report ``pass: True`` — each row is itself a positive
control that manufactures the exact poломка and checks the frozen safe response.
"""
from __future__ import annotations

import json
from pathlib import Path

from spa_core.capital_shadow import contract, failure_matrix


def test_failure_matrix_has_at_least_24_distinct_rows(tmp_path):
    rows = failure_matrix.run_matrix(tmp_path)
    assert len(rows) >= 24
    names = [r["failure"] for r in rows]
    assert len(names) == len(set(names)), "every failure row must be distinct"


def test_failure_matrix_every_row_passes(tmp_path):
    rows = failure_matrix.run_matrix(tmp_path)
    failing = [r for r in rows if not r["pass"]]
    assert failing == [], f"failing rows: {json.dumps(failing, indent=2, default=str)}"


def test_failure_matrix_every_row_has_required_shape(tmp_path):
    rows = failure_matrix.run_matrix(tmp_path)
    for r in rows:
        assert set(r.keys()) == {"failure", "expected_safe_response", "actual_response", "pass",
                                 "recovery_evidence"}
        assert isinstance(r["failure"], str) and r["failure"]
        assert isinstance(r["expected_safe_response"], str) and r["expected_safe_response"]


def test_failure_matrix_cli_writes_json(tmp_path):
    out = tmp_path / "matrix.json"
    rc = failure_matrix.main(["--out", str(out)])
    assert rc == contract.EXIT_OK
    data = json.loads(out.read_text())
    assert len(data) >= 24
    assert all(r["pass"] for r in data)


def test_policy_violation_catches_excessive_gas():
    from spa_core.capital_shadow import machine
    an_intent = {"constraints": {}, "action_type": contract.ACTION_SUPPLY, "notional": 100.0}
    sim = {"gas_estimate": 10_000_000, "call": {"args_readable": []}}
    assert machine.policy_violation(an_intent, sim) is not None


def test_policy_violation_catches_unlimited_approval():
    from spa_core.capital_shadow import machine
    an_intent = {"constraints": {}, "action_type": contract.ACTION_APPROVE, "notional": 100.0}
    sim = {"gas_estimate": 50_000, "call": {"args_readable": [{"name": "amount", "value":
          machine.UNLIMITED_APPROVAL}]}}
    assert machine.policy_violation(an_intent, sim) is not None


def test_policy_violation_clean_case():
    from spa_core.capital_shadow import machine
    an_intent = {"constraints": {}, "action_type": contract.ACTION_SUPPLY, "notional": 100.0}
    sim = {"gas_estimate": 50_000, "call": {"args_readable": []}}
    assert machine.policy_violation(an_intent, sim) is None
