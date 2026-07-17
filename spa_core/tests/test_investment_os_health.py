"""spa_core/tests/test_investment_os_health.py — product-layer health monitor (AAA Phase 2).

Proves the meta-monitor classifies each analyst artifact (present/fresh/status) and rolls up to
HEALTHY / STALE / DEGRADED honestly. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from spa_core.investment_os import health as H


def _dt(day=17):
    return datetime(2026, 7, day, 12, 0, tzinfo=timezone.utc)


def _write(d, agent, status="ok", *, age_days=0.0):
    p = d / f"{agent}.json"
    p.write_text(json.dumps({"agent": agent, "status": status}))
    if age_days:
        t = _dt().timestamp() - age_days * 86400
        os.utime(p, (t, t))


def test_all_fresh_ok_is_healthy(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "HEALTHY"
    assert s["counts"]["healthy"] == len(H.ANALYSTS)


def test_missing_artifact_is_degraded(tmp_path):
    for a in H.ANALYSTS[1:]:
        _write(tmp_path, a, "ok")   # first analyst missing
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "DEGRADED"
    assert s["counts"]["missing"] == 1


def test_unknown_status_is_degraded(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, H.ANALYSTS[0], "UNKNOWN")
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "DEGRADED"
    assert s["counts"]["unknown_or_corrupt"] == 1


def test_stale_artifact_is_stale(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, H.ANALYSTS[0], "ok", age_days=5)   # older than the 2-day budget
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "STALE"
    assert s["counts"]["stale"] == 1


def test_corrupt_artifact_flagged(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    (tmp_path / f"{H.ANALYSTS[0]}.json").write_text("{ not json")
    s = H.scan(tmp_path, now=_dt())
    assert s["counts"]["unknown_or_corrupt"] == 1


def test_run_writes_health_artifact(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    H.run(now=_dt(), data_dir=tmp_path)
    doc = json.loads((tmp_path / "_health.json").read_text())
    assert doc["overall"] == "HEALTHY" and doc["is_advisory"] is True
    assert (tmp_path / "_health_proof.jsonl").exists()
