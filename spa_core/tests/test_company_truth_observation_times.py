"""spa_core/tests/test_company_truth_observation_times.py — ARB-CONTINUITY-01 wave D.

The continuity read model (ADR-610) demotes a RUNTIME section marked MEASURED without ``as_of``
to PARTIAL. Four Company Truth cells — the money chip, Sherlock, the studio fleet and memory —
carried NO observation time, so the context could never read FRESH. Each cell now takes the
OBSERVATION time of its own artifact (never render time) and keeps ``None`` when the artifact
has none (inv. #17). Every test here has both directions: stamp present ⇒ ``as_of`` equals it;
stamp absent ⇒ ``as_of`` is ``None`` — never a substituted "now".
"""
# FROZEN-DATE-OK: the literal date IS the subject — an observation stamp copied through verbatim; no freshness window is judged here
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from spa_core.studio_os import company_truth as ct

STAMP = "2026-10-05T11:22:33Z"


def _fleet(agent_health_doc):
    manifest = {"agents": [{"label": "com.spa.a", "intent": "active", "schedule": "daemon"}]}
    return ct.typed_fleet(manifest, {"com.spa.a": {}}, agent_health_doc, {"roles": []},
                          announced=0, unannounced=0)


def test_fleet_takes_the_health_monitors_own_timestamp():
    f = _fleet({"timestamp": "2026-10-05T11:22:33.123+00:00", "agents": [{"label": "com.spa.a", "status": "OK"}]})
    assert f["headline"]["state"] == ct.MEASURED and f["headline"]["as_of"] == STAMP
    assert ct.fleet_cell(f)["as_of"] == STAMP          # the UI/continuity cell inherits it


def test_fleet_without_a_timestamp_has_no_as_of():
    f = _fleet({"agents": [{"label": "com.spa.a", "status": "OK"}]})
    assert f["headline"]["state"] == ct.MEASURED and f["headline"]["as_of"] is None


def test_money_chip_carries_the_observation_time_it_is_given():
    c = ct.money_chip({"state": "LIVE_NOT_APPROVED", "usd": 0, "observed_at": STAMP})
    assert c["state"] == ct.MEASURED and c["as_of"] == STAMP and c["usd"] == 0
    assert ct.money_chip({"state": "LIVE_NOT_APPROVED", "usd": 0})["as_of"] is None
    assert ct.money_chip({"state": "UNKNOWN", "usd": None, "observed_at": STAMP})["as_of"] is None


def test_sherlock_takes_the_factory_sections_observation_time():
    ru = {"_meta": {"observed_at": STAMP}, "sherlock": {"evidence_ready": 1}}
    assert ct.capital_sherlock(ru)["as_of"] == STAMP
    assert ct.capital_sherlock({"sherlock": {"evidence_ready": 1}})["as_of"] is None


def _memory_repo(tmp_path, built_at):
    repo = tmp_path / "repo"
    (repo / "data" / "memory").mkdir(parents=True)
    (repo / "architecture").mkdir(parents=True)
    con = sqlite3.connect(repo / "data" / "memory" / "index.db")
    con.execute("CREATE TABLE chunks (path TEXT, body TEXT)")
    con.execute("INSERT INTO chunks VALUES (?, ?)", ("docs/decisions/ADR-500-x.md", "text"))
    con.execute("CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT)")
    if built_at is not None:
        con.execute("INSERT INTO manifest VALUES ('built_at', ?)", (json.dumps(built_at),))
    con.commit()
    con.close()
    mirror = tmp_path / "mirror"
    (mirror / "docs" / "decisions").mkdir(parents=True)
    (mirror / "docs" / "decisions" / "ADR-500-x.md").write_text("x", encoding="utf-8")
    return repo, mirror


def test_memory_takes_the_index_build_time(tmp_path):
    repo, mirror = _memory_repo(tmp_path, 1791199353)       # 2026-10-05T11:22:33Z
    out = ct.studio_memory(repo, mirror)
    assert out["state"] in (ct.MEASURED, ct.MEASURED_ZERO) and out["as_of"] == STAMP


def test_memory_without_a_build_stamp_has_no_as_of(tmp_path):
    repo, mirror = _memory_repo(tmp_path, None)
    out = ct.studio_memory(repo, mirror)
    assert out["state"] in (ct.MEASURED, ct.MEASURED_ZERO) and out["as_of"] is None
    repo2, mirror2 = _memory_repo(tmp_path / "b", True)     # a bool is not a time
    assert ct.studio_memory(repo2, mirror2)["as_of"] is None
