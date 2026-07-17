"""spa_core/tests/test_protocol_risk_agent.py — Protocol & Peg Risk analyst (AAA Phase 2).

Proves it CONSUMES the protocol-risk map + peg report into an advisory risk view, surfaces a cautious
concern flag (PEG_CRITICAL on a critical peg), can only RAISE concern, and fails CLOSED to UNKNOWN when
both sources are gone (never a default all-safe). PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.protocol_risk import ProtocolRiskAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, rmap=True, peg=True, peg_critical=0, peg_status="STABLE"):
    rp = tmp_path / "protocol_risk_map.json"
    pp = tmp_path / "peg_report.json"
    if rmap:
        rp.write_text(json.dumps({"generated_at": "2026-07-17T00:00:00Z", "count": 33,
                                  "count_by_tier": {"T1": 10, "T2": 15, "T3": 8}, "map_version": "v3"}))
    if peg:
        pp.write_text(json.dumps({"generated_at": "2026-07-17T00:00:00Z", "total_monitored": 12,
                                  "stable": 12 - peg_critical, "caution": 0, "warning": 0,
                                  "critical": peg_critical, "overall_status": peg_status,
                                  "worst_adapter": "x", "worst_deviation_pct": 0.1}))
    return rp, pp


def test_consumes_both_and_flags_none(tmp_path):
    rp, pp = _seed(tmp_path)
    out = ProtocolRiskAgent(risk_map_path=rp, peg_path=pp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["protocol_risk"]["value"]["count"] == 33
    assert out["peg_health"]["value"]["total_monitored"] == 12
    assert out["concern"] == "NONE_SURFACED"
    assert out["protocol_risk"]["evidence_level"] == "L4"


def test_critical_peg_surfaces_concern(tmp_path):
    rp, pp = _seed(tmp_path, peg_critical=1, peg_status="CRITICAL")
    out = ProtocolRiskAgent(risk_map_path=rp, peg_path=pp, data_dir=tmp_path).analyze()
    assert out["concern"] == "PEG_CRITICAL"


def test_one_source_missing_still_ok(tmp_path):
    rp, pp = _seed(tmp_path, peg=False)
    out = ProtocolRiskAgent(risk_map_path=rp, peg_path=pp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["protocol_risk"]["value"]["count"] == 33
    assert out["peg_health"]["value"] == UNKNOWN


def test_both_missing_is_unknown(tmp_path):
    out = ProtocolRiskAgent(risk_map_path=tmp_path / "a.json", peg_path=tmp_path / "b.json",
                            data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    rp, pp = _seed(tmp_path)
    path = ProtocolRiskAgent(risk_map_path=rp, peg_path=pp, data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "protocol_risk"
    assert (tmp_path / "protocol_risk_proof.jsonl").exists()
