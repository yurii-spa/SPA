"""spa_core/tests/test_onchain_agent.py — On-chain / Developer Activity analyst (AAA Phase 2).

Proves it CONSUMES the developer-activity log into an advisory activity view, surfaces INACTIVE_TEAMS
concern when protocols are abandoned, and fails CLOSED to UNKNOWN. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.onchain import OnchainActivityAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, inactive=None):
    p = tmp_path / "developer_activity_log.json"
    p.write_text(json.dumps([
        {"protocols": [], "average_activity_score": 0},  # older
        {"protocols": [
            {"name": "aave", "activity_level": "VERY_ACTIVE", "activity_score": 82},
            {"name": "morpho", "activity_level": "ACTIVE", "activity_score": 60}],
         "most_active": "aave", "least_active": "morpho", "average_activity_score": 71.0,
         "inactive_protocols": inactive or []},
    ]))
    return p


def test_consumes_latest(tmp_path):
    out = OnchainActivityAgent(dev_log_path=_seed(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    v = out["developer_activity"]["value"]
    assert v["average_activity_score"] == 71.0
    assert v["most_active"] == "aave"
    assert v["by_activity_level"] == {"VERY_ACTIVE": 1, "ACTIVE": 1}
    assert out["concern"] == "NONE_SURFACED"


def test_inactive_teams_flags_concern(tmp_path):
    out = OnchainActivityAgent(dev_log_path=_seed(tmp_path, inactive=["deadproto"]), data_dir=tmp_path).analyze()
    assert out["concern"] == "INACTIVE_TEAMS"
    assert out["developer_activity"]["value"]["inactive_protocols"] == ["deadproto"]


def test_missing_is_unknown(tmp_path):
    out = OnchainActivityAgent(dev_log_path=tmp_path / "no.json", data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    path = OnchainActivityAgent(dev_log_path=_seed(tmp_path), data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "onchain"
    assert (tmp_path / "onchain_proof.jsonl").exists()
