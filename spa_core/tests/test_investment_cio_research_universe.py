"""Tests for spa_core.investment_cio.research_universe (ADR-560 WP-S07 / binding #14).

Package A (``research_factory.read``) landed on this tree while this module was being written, but
this suite still treats the dependency as something that can be ABSENT, STALE or BROKEN — both
because the read interface is defined by Appendix I (frozen) rather than by today's implementation,
and because research_universe.build() must degrade gracefully regardless of which package A/B
happen to be deployed at any given moment. Every non-trivial scenario is reached by monkeypatching
``spa_core.research_factory.read``'s functions (or, for the "package absent" case, the module cache
itself) — never a real network call, never a real research_factory ledger on disk.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into build_sleeves/policy.recommend/
# research_universe.build; nothing here reads the wall clock.
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.investment_cio import contract, ledger, policy, read as cio_read, research_universe, sleeves
from spa_core.tests.test_investment_cio_sleeves import _full_scene

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
RF_PKG = "spa_core.research_factory"
RF_READ_MODULE = "spa_core.research_factory.read"


def _simulate_package_absent(monkeypatch):
    """Makes ``from spa_core.research_factory import read`` raise ImportError regardless of
    whether the real package is installed on this tree: swap the cached package module for a bare
    one with no ``__path__`` (so it is not a package as far as the import system is concerned) and
    drop the submodule's own cache entry."""
    fake_pkg = types.ModuleType(RF_PKG)
    monkeypatch.setitem(sys.modules, RF_PKG, fake_pkg)
    monkeypatch.delitem(sys.modules, RF_READ_MODULE, raising=False)


def _install_fake_rf_read(monkeypatch, *, cio_view=None, latest=None):
    """Installs a fake ``read`` module as BOTH the sys.modules entry and the already-imported
    parent package's ``read`` attribute — ``from pkg import read`` resolves via ``getattr(pkg,
    'read')`` first when the real submodule was already imported earlier in the test session, so
    patching sys.modules alone is not enough once package A exists on disk."""
    import spa_core.research_factory as rf_pkg
    fake = types.ModuleType(RF_READ_MODULE)
    if cio_view is not None:
        fake.cio_view = cio_view
    if latest is not None:
        fake.latest = latest
    monkeypatch.setitem(sys.modules, RF_READ_MODULE, fake)
    monkeypatch.setattr(rf_pkg, "read", fake, raising=False)
    return fake


# ── research_universe.build() — fail-closed states ──────────────────────────────────────────────

def test_build_is_not_measured_when_research_factory_package_is_absent(tmp_path, monkeypatch):
    _simulate_package_absent(monkeypatch)
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] == research_universe.STATE_NOT_MEASURED
    assert view["observe_only"] == [] and view["paper_active"] == [] and view["cio_eligible"] == []
    assert view["reason"]


def test_build_is_broken_when_cio_view_raises(tmp_path, monkeypatch):
    def _boom(data_dir, now):
        raise RuntimeError("ledger chain is not intact")
    _install_fake_rf_read(monkeypatch, cio_view=_boom)
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] == research_universe.STATE_BROKEN
    assert "RuntimeError" in view["reason"]


def test_build_is_broken_on_an_unexpected_shape(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, cio_view=lambda d, n: {"nonsense": True})
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] == research_universe.STATE_BROKEN


def test_build_projects_a_healthy_view(tmp_path, monkeypatch):
    def _view(data_dir, now):
        return {"state": "OK", "reason": None, "observe_only": ["o1"], "paper_active": ["p1"],
                "cio_eligible": [{"candidate_id": "c1", "exposure_key_version": 1}],
                "correlation_groups": {"SKY_SSR": ["c1"]}, "ledger_head_hash": "deadbeef"}
    _install_fake_rf_read(monkeypatch, cio_view=_view)
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] == research_universe.STATE_OK
    assert view["observe_only"] == ["o1"] and view["paper_active"] == ["p1"]
    assert view["cio_eligible"] == [{"candidate_id": "c1", "exposure_key_version": 1}]
    assert view["correlation_groups"] == {"SKY_SSR": ["c1"]}
    assert view["ledger_head_hash"] == "deadbeef"


def test_build_propagates_stale(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, cio_view=lambda d, n: {
        "state": "STALE", "reason": "read model older than 26h", "observe_only": [], "paper_active": [],
        "cio_eligible": [], "correlation_groups": {}, "ledger_head_hash": "x"})
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] == research_universe.STATE_STALE
    assert "26h" in view["reason"]


def test_build_against_the_real_package_a_with_no_ledger_yet(tmp_path):
    """Integration smoke test against the REAL spa_core.research_factory.read (now on this tree):
    an empty data_dir with no research_factory ledger must still answer cleanly, never raise."""
    view = research_universe.build(tmp_path, NOW)
    assert view["state"] in research_universe.VIEW_STATES


# ── research_sleeve_allocatable — fail-closed ───────────────────────────────────────────────────

_OK_VIEW = {"state": "OK", "cio_eligible": [{"candidate_id": "c1", "exposure_key_version": 1}]}


def test_allocatable_false_when_contract_flag_is_false():
    assert research_universe.research_sleeve_allocatable(False, "c1", 1, _OK_VIEW) is False


def test_allocatable_false_when_view_state_is_not_ok():
    for bad_state in ("STALE", "BROKEN", "NOT_MEASURED", None):
        v = dict(_OK_VIEW, state=bad_state)
        assert research_universe.research_sleeve_allocatable(True, "c1", 1, v) is False


def test_allocatable_false_when_candidate_absent():
    assert research_universe.research_sleeve_allocatable(True, "unknown", 1, _OK_VIEW) is False


def test_allocatable_false_on_version_mismatch():
    """A candidate_id match with a DIFFERENT exposure_key_version is a different candidate
    wearing the old name (ADR-560 binding #14) — never allocatable."""
    assert research_universe.research_sleeve_allocatable(True, "c1", 2, _OK_VIEW) is False


def test_allocatable_true_only_when_flag_and_state_and_membership_all_hold():
    assert research_universe.research_sleeve_allocatable(True, "c1", 1, _OK_VIEW) is True


def test_allocatable_matches_by_id_when_view_entry_has_no_version():
    """The real package A's cio_view() publishes cio_eligible as bare candidate_id strings today
    (no per-entry exposure_key_version) — matched by id alone, per the helper's documented
    best-effort rule for that shape."""
    v = {"state": "OK", "cio_eligible": ["c1"]}
    assert research_universe.research_sleeve_allocatable(True, "c1", 1, v) is True


def test_allocatable_false_on_malformed_view():
    assert research_universe.research_sleeve_allocatable(True, "c1", 1, None) is False
    assert research_universe.research_sleeve_allocatable(True, "c1", 1, {}) is False


# ── read.latest() carries research_universe as its own top-level key ───────────────────────────

def test_read_latest_carries_research_universe_even_with_no_cio_recommendation_yet(tmp_path, monkeypatch):
    _simulate_package_absent(monkeypatch)
    doc = cio_read.latest(tmp_path, now=NOW)
    assert doc["state"] == contract.NOT_MEASURED
    assert "research_universe" in doc
    assert doc["research_universe"]["state"] == research_universe.STATE_NOT_MEASURED


def test_read_latest_carries_research_universe_alongside_a_real_recommendation(tmp_path, monkeypatch):
    _install_fake_rf_read(monkeypatch, cio_view=lambda d, n: {
        "state": "OK", "reason": None, "observe_only": ["o1"], "paper_active": [], "cio_eligible": [],
        "correlation_groups": {}, "ledger_head_hash": "abc"})
    rec = {"schema": contract.SCHEMA_REC, "recommendation_id": "r1", "generated_at": "2026-10-04T09:30:00Z",
           "date": "2026-10-04", "recommended_weights": {"defi_conservative": 1.0},
           "seed_split_weights": {"defi_conservative": 1.0}, "stance": contract.STANCE_RECOMMEND, "lineage": {}}
    ledger.append(tmp_path, rec, snapshot_digest_="deadbeef")
    doc = cio_read.latest(tmp_path, now=NOW)
    assert doc["state"] == contract.MEASURED
    assert doc["research_universe"]["state"] == "OK"
    assert doc["research_universe"]["observe_only"] == ["o1"]
    # the ledger record itself (what `recommendation` is) carries none of this — it is a read-time
    # addition only, never written through the ledger (contract.REC_FIELDS is frozen).
    assert "research_universe" not in doc["recommendation"]
    assert set(doc["recommendation"]) <= set(contract.REC_FIELDS) | {"lineage"}


# ── the differential test (task's own requirement): CIO run is byte-identical either way ──────

def _sleeves_and_rec(data_dir: Path) -> tuple[dict, dict]:
    sleeves_doc = sleeves.build_sleeves(data_dir, NOW)
    rec = policy.recommend(sleeves_doc, None, NOW)
    return sleeves_doc, rec


def test_cio_run_is_byte_identical_with_and_without_a_research_factory_status_present(tmp_path):
    """research_factory/status.json existing (even malformed) must not change build_sleeves'
    output, policy.recommend's weights, or the ledger record it would write — sleeves.py and
    policy.py never read anything under research_factory/ (ADR-560 WP-S07: the research universe
    is a READ-TIME-only projection added in investment_cio/read.py, never an input to the CIO
    itself)."""
    without_dir = _full_scene(tmp_path / "without", now=NOW)
    with_dir = _full_scene(tmp_path / "with", now=NOW)
    (with_dir / "research_factory").mkdir(parents=True, exist_ok=True)
    (with_dir / "research_factory" / "status.json").write_text(
        '{"schema": "research-factory-status/1", "generated_at": "2026-10-04T09:05:00Z", '
        '"integrity": "OK", "by_domain": {"CASH_TREASURY": 5}}')

    sleeves_without, rec_without = _sleeves_and_rec(without_dir)
    sleeves_with, rec_with = _sleeves_and_rec(with_dir)

    # generated_at / inputs timestamps are identical because NOW is fixed and neither scene reads
    # anything that differs except the extra research_factory file.
    assert sleeves_without == sleeves_with
    assert rec_without["recommended_weights"] == rec_with["recommended_weights"]
    assert rec_without["recommendation_id"] == rec_with["recommendation_id"]
    hash_basis_without = {k: v for k, v in rec_without.items() if k not in ("recommendation_id", "generated_at")}
    hash_basis_with = {k: v for k, v in rec_with.items() if k not in ("recommendation_id", "generated_at")}
    assert hash_basis_without == hash_basis_with

    snap_without = ledger.save_snapshot(without_dir, sleeves_without)
    snap_with = ledger.save_snapshot(with_dir, sleeves_with)
    line_without = ledger.append(without_dir, rec_without, snapshot_digest_=snap_without,
                                 code_identity_=ledger.code_identity())
    line_with = ledger.append(with_dir, rec_with, snapshot_digest_=snap_with,
                              code_identity_=ledger.code_identity())
    rec_field_without = {k: v for k, v in line_without["recommendation"].items() if k != "generated_at"}
    rec_field_with = {k: v for k, v in line_with["recommendation"].items() if k != "generated_at"}
    assert rec_field_without == rec_field_with
    assert "research_universe" not in line_without["recommendation"]
    assert "research_universe" not in line_with["recommendation"]


def test_cio_run_unaffected_even_when_research_factory_status_is_broken_json(tmp_path):
    """A malformed research_factory/status.json (e.g. mid-write torn JSON) must not raise out of
    build_sleeves/policy.recommend either — the CIO run is simply blind to it."""
    data_dir = _full_scene(tmp_path, now=NOW)
    (data_dir / "research_factory").mkdir(parents=True, exist_ok=True)
    (data_dir / "research_factory" / "status.json").write_text("{not json")
    sleeves_doc = sleeves.build_sleeves(data_dir, NOW)
    rec = policy.recommend(sleeves_doc, None, NOW)
    assert rec["stance"] in contract.STANCES
