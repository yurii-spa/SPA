"""
test_api_riskwire.py — the /api/riskwire/proof surface (WS1.4): serves the chain verbatim + a LIVE
verification verdict, fail-CLOSED on missing/tampered artifacts.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from spa_core.api import server
from spa_core.riskwire import (RISKWIRE_CLASS_LABELS, RiskWireClass, RiskWireMeasurement,
                               RiskWireRefusal, SubjectKind)
from spa_core.riskwire import proof


def _mk(sid, cls, seed_hash):
    return RiskWireMeasurement(
        subject_id=sid, kind=SubjectKind.POOL, display_name=sid.split("::")[-1], risk_class=cls,
        risk_class_label=RISKWIRE_CLASS_LABELS[cls], native_verdict=cls.value,
        refusal=RiskWireRefusal("SAFE", "clean", False), exit_liquidity_by_size=[],
        liquidation_nav=None, structural_haircut=None, total_haircut=None, seed="dfb",
        seed_proof_hash=seed_hash, as_of="2026-06-30", flagged=False, flag_reason=None,
        provenance="dfb:seed", prev_hash="")


def _write_day30(tmp_path):
    rw = tmp_path / "riskwire"
    rw.mkdir(parents=True, exist_ok=True)
    review = {
        "schema": "day30-review-v1", "generated_at": "2026-06-30T09:05:00+00:00",
        "state": "TRACK_MATURING", "ready_for_review": False,
        "day30_artifact": {"schema": "day30-v1", "generated_at": "2026-06-30T09:05:01+00:00",
                           "proof_hash": "e" * 64},
    }
    review["review_hash"] = proof.compute_review_hash(review)
    (rw / "day30_review.json").write_text(json.dumps(review, indent=1))


@pytest.fixture
def client(tmp_path, monkeypatch):
    proof.write_measurements([_mk("pool::a", RiskWireClass.A, "a" * 64),
                              _mk("pool::b", RiskWireClass.D, "b" * 64)],
                             generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30",
                             data_dir=tmp_path)
    _write_day30(tmp_path)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def test_proof_index_all_verified(client):
    c, _ = client
    r = c.get("/api/riskwire/proof")
    assert r.status_code == 200
    body = r.json()
    assert body["all_verified"] is True
    assert body["artifacts"]["measurements"]["verified"] is True
    assert body["artifacts"]["day30_review"]["verified"] is True
    assert body["artifacts"]["measurements"]["head_hash"]
    assert "verify_riskwire.py" in body["reproduce"]["verify_with"]


def test_artifact_served_verbatim(client):
    c, tmp_path = client
    r = c.get("/api/riskwire/proof/measurements")
    assert r.status_code == 200
    served = r.json()
    on_disk = json.loads((tmp_path / "riskwire" / "measurements.json").read_text())
    # verbatim: the row chain + hashes are byte-equal to disk (so an outsider's recompute matches)
    assert served["head_hash"] == on_disk["head_hash"]
    assert served["artifact_hash"] == on_disk["artifact_hash"]
    assert served["measurements"] == on_disk["measurements"]


def test_unknown_artifact_404(client):
    c, _ = client
    assert c.get("/api/riskwire/proof/nonsense").status_code == 404


def test_missing_artifact_fail_closed(tmp_path, monkeypatch):
    # empty data dir → present:false / verified:false, never a fabricated pass
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/riskwire/proof").json()
        assert body["all_verified"] is False
        assert body["artifacts"]["measurements"]["present"] is False
        assert c.get("/api/riskwire/proof/measurements").status_code == 404


def test_tampered_artifact_reports_unverified(client):
    c, tmp_path = client
    p = tmp_path / "riskwire" / "measurements.json"
    doc = json.loads(p.read_text())
    doc["measurements"][1]["risk_class"] = "A"     # forge toxic → safe, no re-hash
    p.write_text(json.dumps(doc, indent=1))
    body = c.get("/api/riskwire/proof").json()
    assert body["all_verified"] is False
    assert body["artifacts"]["measurements"]["verified"] is False
    assert body["artifacts"]["measurements"]["broken_at"] == 1
