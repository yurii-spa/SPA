"""Tests for the Q3-5 kill-switch drill EVIDENCE artifact (scripts/kill_switch_drill.py write_status).

Verifies the drill persists a dated, auditable latency/verdict artifact (atomic) with the expected
fields, and that a passing drill records latency under its budget. Deterministic; no network.
"""
import importlib
import json

import pytest

ksd = importlib.import_module("scripts.kill_switch_drill")


def test_run_drill_passes_and_is_fast():
    res = ksd.run_drill()
    assert res["passed"] is True
    assert res["verdict"].startswith("PASS")
    assert 0.0 < res["total_time_ms"] < 1000.0     # within the 1s budget
    assert res["steps"] and all(s.get("ok") for s in res["steps"])


def test_write_status_persists_dated_evidence(tmp_path):
    res = ksd.run_drill()
    path = ksd.write_status(res, data_dir=str(tmp_path))
    assert path.exists()
    doc = json.loads(path.read_text())
    assert doc["model"] == "kill_switch_drill_status"
    assert doc["is_advisory"] is True
    assert doc["last_drill_at"] == res["drill_timestamp"]      # dated to the drill
    assert doc["latency_ms"] == res["total_time_ms"]
    assert doc["latency_limit_ms"] == 1000.0
    assert doc["passed"] is True
    assert doc["all_steps_ok"] is True
    assert doc["n_steps"] == len(res["steps"])


def test_write_status_atomic_roundtrip(tmp_path):
    res = ksd.run_drill()
    p1 = ksd.write_status(res, data_dir=str(tmp_path))
    p2 = ksd.write_status(res, data_dir=str(tmp_path))          # overwrite is clean
    assert p1 == p2
    assert json.loads(p2.read_text())["verdict"] == res["verdict"]
