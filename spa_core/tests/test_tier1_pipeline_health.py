"""
Hermetic tests for spa_core/backtesting/tier1/pipeline_health.py.

Each test redirects the module's data path to a tmp dir, so nothing reads/writes the real
data/ tree. Covers: fresh→OK, old→STALE, missing→MISSING, core-missing→CRITICAL overall,
status set membership, determinism, and build_report structure + atomicity.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import pytest

from spa_core.backtesting.tier1 import pipeline_health as ph


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the module at a throwaway data dir and (bee/) subdir, return helpers."""
    data = tmp_path / "data"
    (data / "bee").mkdir(parents=True)
    monkeypatch.setattr(ph, "_DATA", data)
    monkeypatch.setattr(ph, "_OUT", data / "tier1_pipeline_health.json")
    now = datetime.datetime(2026, 6, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def write_artifact(name: str, generated_at: datetime.datetime | None):
        p = data / name
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {"x": 1}
        if generated_at is not None:
            body["generated_at"] = _iso(generated_at)
        p.write_text(json.dumps(body))
        return p

    def write_all_fresh():
        for spec in ph.ARTIFACTS:
            write_artifact(spec["name"], now - datetime.timedelta(hours=1))

    return type("SB", (), {"data": data, "now": now,
                           "write_artifact": staticmethod(write_artifact),
                           "write_all_fresh": staticmethod(write_all_fresh)})


def test_fresh_artifact_is_ok(sandbox):
    sandbox.write_all_fresh()
    r = ph.check(now=sandbox.now)
    assert r["overall"] == "OK"
    assert r["stale_count"] == 0
    assert r["missing_count"] == 0
    assert all(a["status"] == "OK" for a in r["artifacts"])
    assert all(a["exists"] for a in r["artifacts"])


def test_old_artifact_is_stale(sandbox):
    sandbox.write_all_fresh()
    # Push one NON-core artifact past its SLO → STALE, overall DEGRADED.
    target = next(s["name"] for s in ph.ARTIFACTS if not s["core"])
    slo = next(s["slo_hours"] for s in ph.ARTIFACTS if s["name"] == target)
    sandbox.write_artifact(target, sandbox.now - datetime.timedelta(hours=slo + 5))
    r = ph.check(now=sandbox.now)
    stale = [a for a in r["artifacts"] if a["status"] == "STALE"]
    assert [a["name"] for a in stale] == [target]
    assert r["stale_count"] == 1
    assert r["overall"] == "DEGRADED"
    assert stale[0]["age_hours"] > stale[0]["slo_hours"]


def test_missing_artifact(sandbox):
    sandbox.write_all_fresh()
    # Remove one NON-core artifact → MISSING, overall DEGRADED (not CRITICAL).
    target = next(s["name"] for s in ph.ARTIFACTS if not s["core"])
    os.unlink(sandbox.data / target)
    r = ph.check(now=sandbox.now)
    missing = [a for a in r["artifacts"] if a["status"] == "MISSING"]
    assert [a["name"] for a in missing] == [target]
    assert missing[0]["exists"] is False
    assert missing[0]["age_hours"] is None
    assert r["missing_count"] == 1
    assert r["overall"] == "DEGRADED"


def test_core_missing_is_critical(sandbox):
    sandbox.write_all_fresh()
    core_name = next(s["name"] for s in ph.ARTIFACTS if s["core"])
    os.unlink(sandbox.data / core_name)
    r = ph.check(now=sandbox.now)
    assert r["overall"] == "CRITICAL"
    assert any(a["name"] == core_name and a["status"] == "MISSING" for a in r["artifacts"])


def test_core_stale_is_critical(sandbox):
    sandbox.write_all_fresh()
    core = next(s for s in ph.ARTIFACTS if s["core"])
    sandbox.write_artifact(core["name"],
                           sandbox.now - datetime.timedelta(hours=core["slo_hours"] + 10))
    r = ph.check(now=sandbox.now)
    assert r["overall"] == "CRITICAL"


def test_status_set_membership(sandbox):
    # Mixed: fresh, stale, missing across artifacts.
    sandbox.write_all_fresh()
    non_core = [s["name"] for s in ph.ARTIFACTS if not s["core"]]
    sandbox.write_artifact(non_core[0], sandbox.now - datetime.timedelta(hours=100))
    os.unlink(sandbox.data / non_core[1])
    r = ph.check(now=sandbox.now)
    for a in r["artifacts"]:
        assert a["status"] in ph.STATUSES
    assert r["overall"] in ph.OVERALL


def test_mtime_fallback_when_no_timestamp_field(sandbox):
    # Artifact without a generated_at field → age derived from mtime; fresh file → OK.
    sandbox.write_all_fresh()
    name = next(s["name"] for s in ph.ARTIFACTS if not s["core"])
    p = sandbox.data / name
    p.write_text(json.dumps({"no_ts": True}))
    fresh = (sandbox.now - datetime.timedelta(hours=2)).timestamp()
    os.utime(p, (fresh, fresh))
    r = ph.check(now=sandbox.now)
    art = next(a for a in r["artifacts"] if a["name"] == name)
    assert art["status"] == "OK"
    assert art["age_hours"] is not None and art["age_hours"] > 0


def test_determinism(sandbox):
    sandbox.write_all_fresh()
    a = ph.check(now=sandbox.now)
    b = ph.check(now=sandbox.now)
    assert a == b


def test_build_report_structure_and_atomic(sandbox):
    sandbox.write_all_fresh()
    rep = ph.build_report(write=True, now=sandbox.now)
    # Structure
    assert rep["model"] == "tier1_pipeline_health"
    assert rep["llm_forbidden"] is True
    assert "generated_at" in rep
    assert rep["overall"] in ph.OVERALL
    assert isinstance(rep["artifacts"], list)
    assert {"name", "exists", "age_hours", "slo_hours", "core", "status"} <= set(rep["artifacts"][0])
    # Persisted file matches and no temp leftovers
    out = sandbox.data / "tier1_pipeline_health.json"
    assert out.is_file()
    on_disk = json.loads(out.read_text())
    assert on_disk == rep
    leftovers = [p for p in sandbox.data.iterdir() if p.name.startswith(".tier1health_")]
    assert leftovers == []


def test_build_report_no_write(sandbox):
    sandbox.write_all_fresh()
    ph.build_report(write=False, now=sandbox.now)
    assert not (sandbox.data / "tier1_pipeline_health.json").exists()
