"""Tests for the ADR-560 binding #8 repair in spa_core.capital_shadow.readiness:
`_NEVER_CANDIDATE["market_neutral_basis"]` stays an UNCONDITIONAL NOT_READY gate — only its REASON
TEXT is derived from the research factory's measured ``basis_track``. Package A
(``research_factory.read``) landed on this tree while this module was written, but the derivation
is still exercised through monkeypatching, never a real network call or a real ledger on disk, and
the module-absent path is still exercised explicitly (Appendix I is the contract, not today's
deployment state).
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into readiness.evaluate(); nothing here
# reads the wall clock.
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.capital_shadow import contract, readiness
from spa_core.tests.test_capital_shadow_lifecycle import _seed_common

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
RF_PKG = "spa_core.research_factory"
RF_READ_MODULE = "spa_core.research_factory.read"


def _simulate_package_absent(monkeypatch):
    fake_pkg = types.ModuleType(RF_PKG)
    monkeypatch.setitem(sys.modules, RF_PKG, fake_pkg)
    monkeypatch.delitem(sys.modules, RF_READ_MODULE, raising=False)


def _install_fake_rf_read(monkeypatch, *, latest=None):
    import spa_core.research_factory as rf_pkg
    fake = types.ModuleType(RF_READ_MODULE)
    if latest is not None:
        fake.latest = latest
    monkeypatch.setitem(sys.modules, RF_READ_MODULE, fake)
    monkeypatch.setattr(rf_pkg, "read", fake, raising=False)
    return fake


# ── the gate itself: NEVER a pilot candidate, regardless of the derived reason ─────────────────

def test_market_neutral_basis_is_not_ready_when_the_track_is_missing(tmp_path, monkeypatch):
    _simulate_package_absent(monkeypatch)
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    rep = reports["market_neutral_basis"]
    assert rep["readiness_state"] == contract.R_NOT_READY
    assert "ADR-560" in rep["blocking_conditions"][0]["reason"]
    assert "NOT_MEASURED" in rep["blocking_conditions"][0]["reason"]


def test_market_neutral_basis_is_not_ready_even_with_a_fresh_measured_basis_track(tmp_path, monkeypatch):
    """ADR-560 binding #8's own acceptance test: a FRESH, MEASURED basis track still yields
    NOT_READY — the readiness repair must never open a pilot path."""
    _install_fake_rf_read(monkeypatch, latest=lambda d: {
        "integrity": "OK",
        "basis_track": {"state": "MEASURED", "funding_as_of": "2026-10-04T11:00:00Z", "reason": "live funding cell"},
    })
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    rep = reports["market_neutral_basis"]
    assert rep["readiness_state"] == contract.R_NOT_READY
    reason = rep["blocking_conditions"][0]["reason"]
    assert "ADR-560" in reason and "MEASURED" in reason


def test_market_neutral_basis_reason_names_a_stale_basis_track(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, latest=lambda d: {
        "integrity": "OK", "basis_track": {"state": "STALE", "reason": "funding cell stale or unjudgeable"}})
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    reason = reports["market_neutral_basis"]["blocking_conditions"][0]["reason"]
    assert "STALE" in reason and "ADR-560" in reason


def test_market_neutral_basis_reason_falls_back_on_a_broken_factory_ledger(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, latest=lambda d: {"integrity": "BROKEN", "reason": "hash break"})
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    reason = reports["market_neutral_basis"]["blocking_conditions"][0]["reason"]
    assert "NOT_MEASURED" in reason and "ADR-560" in reason


def test_market_neutral_basis_reason_falls_back_when_latest_raises(tmp_path, monkeypatch):
    def _boom(d):
        raise RuntimeError("torn ledger line")
    _install_fake_rf_read(monkeypatch, latest=_boom)
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    reason = reports["market_neutral_basis"]["blocking_conditions"][0]["reason"]
    assert "NOT_MEASURED" in reason and "ADR-560" in reason


def test_market_neutral_basis_reason_falls_back_when_basis_track_key_is_missing(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, latest=lambda d: {"integrity": "OK"})
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    reason = reports["market_neutral_basis"]["blocking_conditions"][0]["reason"]
    assert "NOT_MEASURED" in reason and "ADR-560" in reason


def test_other_never_candidates_are_unaffected(tmp_path, monkeypatch):
    """cash / trading_research keep their own static reasons — only market_neutral_basis's text is
    derived."""
    _install_fake_rf_read(monkeypatch, latest=lambda d: {
        "integrity": "OK", "basis_track": {"state": "MEASURED", "reason": "live funding cell"}})
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    assert reports["cash"]["readiness_state"] == contract.R_NOT_READY
    assert "ADR-560" not in reports["cash"]["blocking_conditions"][0]["reason"]
    assert reports["trading_research"]["readiness_state"] == contract.R_NOT_READY
    assert "ADR-560" not in reports["trading_research"]["blocking_conditions"][0]["reason"]


def test_against_the_real_package_a_with_no_ledger_yet(tmp_path):
    """Integration smoke test against the REAL spa_core.research_factory.read (now on this tree):
    a data_dir with no research_factory ledger at all must still yield NOT_READY with a sensible
    fallback reason, never raise."""
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    rep = reports["market_neutral_basis"]
    assert rep["readiness_state"] == contract.R_NOT_READY
    assert "ADR-560" in rep["blocking_conditions"][0]["reason"]
