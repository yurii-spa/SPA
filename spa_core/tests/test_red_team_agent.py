"""spa_core/tests/test_red_team_agent.py — Red Team analyst (AAA Phase 2, step 9).

Proves it CONSUMES the threat-reactor + attack-sim output into an advisory posture, can only RAISE
concern (never approves), and fails CLOSED to UNKNOWN_CAUTIOUS on missing/stale threat data (never a
default all-clear). PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.red_team import RedTeamAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, threats=None, clear=True, kill=False, critical=0, threat=True, attack=True):
    tp = tmp_path / "threat.json"
    ap = tmp_path / "attack.json"
    if threat:
        tp.write_text(json.dumps({"ts": "2026-07-17T01:00:00Z", "threats": threats or [],
                                  "clear": clear, "kill_switch_already_active": kill}))
    if attack:
        ap.write_text(json.dumps([{"timestamp": 1783112660.0, "critical_count": critical,
                                   "average_security_score": 72.0, "most_vulnerable": "X"}]))
    return tp, ap


def test_no_threat_observed_is_not_approval(tmp_path):
    tp, ap = _seed(tmp_path, clear=True, threats=[])
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["posture"] == "NO_THREAT_OBSERVED"
    # never emits an approval / safe-to-allocate field
    assert "approved" not in out and "safe_to_allocate" not in out


def test_threats_present_escalates(tmp_path):
    tp, ap = _seed(tmp_path, threats=["aave peg wobble"], clear=False)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "THREATS_PRESENT"
    assert out["threat_posture"]["value"]["n_threats"] == 1


def test_critical_attack_or_kill_is_critical(tmp_path):
    tp, ap = _seed(tmp_path, clear=True, critical=2)
    assert RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()["posture"] == "CRITICAL"
    tp2, ap2 = _seed(tmp_path, kill=True)
    assert RedTeamAgent(threat_path=tp2, attack_path=ap2, data_dir=tmp_path).analyze()["posture"] == "CRITICAL"


def test_missing_threat_is_cautious_unknown_never_all_clear(tmp_path):
    tp, ap = _seed(tmp_path, threat=False)  # no threat-reactor file
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN
    assert out["posture"] == "UNKNOWN_CAUTIOUS"   # NEVER defaults to clear when data is missing


def test_stale_threat_is_cautious_unknown(tmp_path):
    import os
    tp, ap = _seed(tmp_path)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(tp, (old, old))
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "UNKNOWN_CAUTIOUS"


def test_run_emits_advisory_artifact(tmp_path):
    tp, ap = _seed(tmp_path)
    path = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "red_team"
    assert doc["posture"] in ("NO_THREAT_OBSERVED", "THREATS_PRESENT", "CRITICAL", "UNKNOWN_CAUTIOUS")
    assert (tmp_path / "red_team_proof.jsonl").exists()
