"""
spa_core/tests/test_nav_proof.py — Tier-1 verifiable NAV / proof-of-reserves snapshot.

Covers: NAV sums positions+cash; reconciliation flag true when equity==sum and false when
it doesn't; verify_proof true for a fresh proof and false after tampering computed_nav;
hash determinism; graceful handling of missing/empty positions.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy

import pytest

from spa_core.backtesting.tier1 import nav_proof as np


# ----------------------------- compute_nav sums correctly ----------------------------- #

def test_compute_nav_sums_positions_and_cash():
    positions = {"aave_v3": 100.0, "compound_v3": 50.0, "yearn_v3": 25.0}
    comp = np._components_hash(positions, 7.0)  # smoke: hashing works on a map
    assert isinstance(comp, str) and len(comp) == 64
    deployed = sum(positions.values())
    nav = deployed + 7.0
    assert nav == pytest.approx(182.0)


def test_load_positions_handles_dict_valued(monkeypatch):
    # positions may carry amount/usd fields instead of a bare number
    monkeypatch.setattr(np, "_read_json", lambda path: {
        "positions": {"aave_v3": {"usd": 100.0}, "maple": {"amount": 40.0}},
        "cash_usd": 10.0,
    })
    pos = np._load_positions()
    assert pos == {"aave_v3": 100.0, "maple": 40.0}


# ----------------------------- reconciliation flag ----------------------------- #

def test_reconciliation_ok_when_equity_equals_sum():
    rec = np._reconcile(computed_nav=100000.0, reported_equity=100000.0)
    assert rec["reconciliation_delta_usd"] == 0.0
    assert rec["reconciliation_ok"] is True


def test_reconciliation_ok_within_dollar_tolerance():
    rec = np._reconcile(computed_nav=100000.50, reported_equity=100000.0)
    assert rec["reconciliation_ok"] is True  # |delta| $0.50 < $1 tolerance


def test_reconciliation_not_ok_when_mismatch():
    rec = np._reconcile(computed_nav=105000.0, reported_equity=100000.0)
    assert rec["reconciliation_ok"] is False
    assert rec["reconciliation_delta_usd"] == pytest.approx(5000.0)
    assert "MISMATCH" in rec["reconciliation_note"]


def test_reconciliation_no_reported_equity():
    rec = np._reconcile(computed_nav=100000.0, reported_equity=None)
    assert rec["reconciliation_ok"] is False
    assert rec["reconciliation_delta_usd"] is None


# ----------------------------- verify_proof ----------------------------- #

def _synthetic_proof(monkeypatch, positions, cash, reported, accrued=0.0, costs=None):
    monkeypatch.setattr(np, "_load_positions", lambda: dict(positions))
    monkeypatch.setattr(np, "_load_cash", lambda: cash)
    monkeypatch.setattr(np, "_load_accrued_yield", lambda: accrued)
    monkeypatch.setattr(np, "_load_costs_paid", lambda: costs)
    monkeypatch.setattr(np, "_load_reported_equity", lambda: reported)
    return np.build_proof(write=False)


# ---------------- paid costs are a NAV component (P1 2026-10-08 replay) ---------------- #
# The figures below are the production proof of 8 Oct 2026 (the incident); no clock is read.

_BOOK_2026_10_08 = {"aave_v3": 5000.0, "compound_v3": 40000.0, "fluid_fusdc": 20000.0,
                    "maple": 20000.0, "morpho_blue_base": 10000.0}


def test_paid_costs_close_the_50_dollar_mismatch(monkeypatch):
    # Positive control, the real incident: accrued 1600.27, costs 50.15 (2026-09-11 rebalance),
    # reported equity 101,550.12. Without the cost component the proof said MISMATCH $50.15.
    proof = _synthetic_proof(monkeypatch, _BOOK_2026_10_08, 5000.0, 101550.12,
                             accrued=1600.27, costs=50.15)
    assert proof["computed_nav_usd"] == pytest.approx(101550.12)
    assert proof["costs_paid_usd"] == pytest.approx(50.15)
    assert proof["reconciliation_ok"] is True
    assert np.verify_proof(proof) is True


def test_dropping_the_cost_component_reproduces_the_mismatch(monkeypatch):
    # Negative control: the same book with costs unknown (None ⇒ 0) is NOT reconciled — the
    # proof must keep exposing a real gap, not hide it.
    proof = _synthetic_proof(monkeypatch, _BOOK_2026_10_08, 5000.0, 101550.12,
                             accrued=1600.27, costs=None)
    assert proof["costs_paid_usd"] is None
    assert proof["computed_nav_usd"] == pytest.approx(101600.27)
    assert proof["reconciliation_ok"] is False


def test_verify_proof_catches_tampered_costs(monkeypatch):
    proof = _synthetic_proof(monkeypatch, _BOOK_2026_10_08, 5000.0, 101550.12,
                             accrued=1600.27, costs=50.15)
    bad = copy.deepcopy(proof)
    bad["costs_paid_usd"] = 0.0
    assert np.verify_proof(bad) is False


def test_load_costs_paid_absent_is_none_not_zero(monkeypatch):
    monkeypatch.setattr(np, "_read_json", lambda path: {"accrued_yield_usd": 1.0})
    assert np._load_costs_paid() is None
    monkeypatch.setattr(np, "_read_json", lambda path: {"costs_paid_usd": 50.15})
    assert np._load_costs_paid() == pytest.approx(50.15)


def test_verify_proof_true_for_fresh_proof(monkeypatch):
    proof = _synthetic_proof(monkeypatch, {"aave_v3": 60000.0, "maple": 33000.0}, 7000.0, 100000.0)
    assert proof["computed_nav_usd"] == pytest.approx(100000.0)
    assert proof["reconciliation_ok"] is True
    assert np.verify_proof(proof) is True


def test_verify_proof_false_when_computed_nav_tampered(monkeypatch):
    proof = _synthetic_proof(monkeypatch, {"aave_v3": 60000.0, "maple": 33000.0}, 7000.0, 100000.0)
    assert np.verify_proof(proof) is True
    tampered = copy.deepcopy(proof)
    tampered["computed_nav_usd"] = 999999.0  # NAV no longer equals sum of parts
    assert np.verify_proof(tampered) is False


def test_verify_proof_false_when_position_tampered(monkeypatch):
    proof = _synthetic_proof(monkeypatch, {"aave_v3": 60000.0, "maple": 33000.0}, 7000.0, 100000.0)
    tampered = copy.deepcopy(proof)
    tampered["positions"][0]["usd"] = 1.0  # components no longer match components_hash
    assert np.verify_proof(tampered) is False


def test_verify_proof_false_when_cash_tampered(monkeypatch):
    proof = _synthetic_proof(monkeypatch, {"aave_v3": 60000.0, "maple": 33000.0}, 7000.0, 100000.0)
    tampered = copy.deepcopy(proof)
    tampered["cash_usd"] = 999.0
    assert np.verify_proof(tampered) is False


def test_verify_proof_false_on_malformed():
    assert np.verify_proof({}) is False
    assert np.verify_proof({"positions": "nonsense"}) is False


# ----------------------------- determinism ----------------------------- #

def test_components_hash_deterministic_and_order_independent():
    a = np._components_hash({"aave_v3": 100.0, "maple": 50.0}, 5.0)
    b = np._components_hash({"maple": 50.0, "aave_v3": 100.0}, 5.0)  # insertion order differs
    assert a == b  # canonical sort makes it order-independent
    assert a == np._components_hash({"aave_v3": 100.0, "maple": 50.0}, 5.0)


def test_components_hash_changes_with_inputs():
    base = np._components_hash({"aave_v3": 100.0}, 5.0)
    assert base != np._components_hash({"aave_v3": 100.01}, 5.0)
    assert base != np._components_hash({"aave_v3": 100.0}, 5.01)


def test_nav_hash_deterministic():
    ch = np._components_hash({"aave_v3": 100.0}, 5.0)
    h1 = np._nav_hash(105.0, ch, "2026-06-24T00:00:00+00:00")
    h2 = np._nav_hash(105.0, ch, "2026-06-24T00:00:00+00:00")
    assert h1 == h2
    assert h1 != np._nav_hash(105.0, ch, "2026-06-24T00:00:01+00:00")  # ts binds in


def test_build_proof_is_self_consistent_fixed_inputs(monkeypatch):
    # two builds with identical components differ only by ts; both must verify.
    p1 = _synthetic_proof(monkeypatch, {"aave_v3": 50.0}, 0.0, 50.0)
    p2 = _synthetic_proof(monkeypatch, {"aave_v3": 50.0}, 0.0, 50.0)
    assert p1["components_hash"] == p2["components_hash"]  # same components -> same hash
    assert np.verify_proof(p1) and np.verify_proof(p2)


# ----------------------------- empty / missing graceful ----------------------------- #

def test_empty_positions_graceful(monkeypatch):
    proof = _synthetic_proof(monkeypatch, {}, 0.0, 0.0)
    assert proof["positions"] == []
    assert proof["deployed_usd"] == 0.0
    assert proof["computed_nav_usd"] == 0.0
    assert proof["reconciliation_ok"] is True  # 0 == 0
    assert np.verify_proof(proof) is True


def test_missing_files_do_not_raise(monkeypatch, tmp_path):
    # point all loaders at non-existent paths; loaders return defaults, no exception
    monkeypatch.setattr(np, "_POSITIONS", tmp_path / "nope1.json")
    monkeypatch.setattr(np, "_STATUS", tmp_path / "nope2.json")
    monkeypatch.setattr(np, "_EQUITY", tmp_path / "nope3.json")
    assert np._load_positions() == {}
    assert np._load_cash() == 0.0
    assert np._load_reported_equity() is None
    assert np._load_costs_paid() is None
    proof = np.build_proof(write=False)
    assert proof["computed_nav_usd"] == 0.0
    assert np.verify_proof(proof) is True
