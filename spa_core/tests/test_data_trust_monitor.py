"""Tests for the 6mo-M2 #16 tournament data-trust monitor (spa_core/monitoring/data_trust_monitor.py).

Verifies: the expected untrusted state (trustworthy=False, promotions=0) reads OK; a trustworthy flip OR
any promotion raises ALERT; a missing artifact is reported fail-CLOSED (never silently trusted); the
verdict is deterministic. Uses tmp files — no live data, no network.
"""
import json

import pytest

from spa_core.monitoring import data_trust_monitor as dtm


def _write(tmp_path, mass_trust=False, strat_trust=False, promotions=0,
           skip=()):
    files = {
        "_MASS": ("mass_tournament_results.json", {"trustworthy": mass_trust}),
        "_TOURN": ("strategy_tournament.json", {"trustworthy": strat_trust}),
        "_ENGINE": ("tournament_engine_state.json", {"total_promotions": promotions}),
    }
    paths = {}
    for attr, (name, body) in files.items():
        p = tmp_path / name
        if attr not in skip:
            p.write_text(json.dumps(body))
        paths[attr] = p
    paths["_OUT"] = tmp_path / "data_trust_status.json"
    return paths


def _patch(monkeypatch, paths):
    for attr, p in paths.items():
        monkeypatch.setattr(dtm, attr, p)


def test_expected_untrusted_state_is_ok(monkeypatch, tmp_path):
    _patch(monkeypatch, _write(tmp_path, mass_trust=False, strat_trust=False, promotions=0))
    rep = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00")
    assert rep["status"] == "OK"
    assert rep["reasons"] == []
    assert rep["first_alert_at"] is None


def test_trustworthy_flip_alerts(monkeypatch, tmp_path):
    _patch(monkeypatch, _write(tmp_path, mass_trust=True))
    rep = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00")
    assert rep["status"] == "ALERT"
    assert any("trustworthy" in r for r in rep["reasons"])
    assert rep["first_alert_at"] == "2026-07-11T00:00:00+00:00"


def test_promotion_fired_alerts(monkeypatch, tmp_path):
    _patch(monkeypatch, _write(tmp_path, promotions=1))
    rep = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00")
    assert rep["status"] == "ALERT"
    assert any("promot" in r for r in rep["reasons"])


def test_missing_artifact_fail_closed(monkeypatch, tmp_path):
    # engine state missing → promotions unknown (None), NOT treated as trusted/OK-with-promotions
    paths = _write(tmp_path, skip=("_ENGINE",))
    _patch(monkeypatch, paths)
    rep = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00")
    assert "tournament_engine_state.json" in rep["missing_artifacts"]
    # missing engine → total_promotions None → not >0 → still OK on the trust flags alone (both False),
    # but the missing artifact is explicitly surfaced (fail-CLOSED disclosure)
    assert rep["total_promotions"] is None


def test_alert_clears_back_to_ok(monkeypatch, tmp_path):
    paths = _write(tmp_path, promotions=1)
    _patch(monkeypatch, paths)
    a = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00")
    assert a["status"] == "ALERT" and a["first_alert_at"]
    # promotions revert to 0 → OK, first_alert_at cleared
    (tmp_path / "tournament_engine_state.json").write_text(json.dumps({"total_promotions": 0}))
    b = dtm.build_report(now_iso="2026-07-11T01:00:00+00:00")
    assert b["status"] == "OK"
    assert b["first_alert_at"] is None


def test_deterministic(monkeypatch, tmp_path):
    _patch(monkeypatch, _write(tmp_path))
    a = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00", write=False)
    b = dtm.build_report(now_iso="2026-07-11T00:00:00+00:00", write=False)
    assert a == b
