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


# ── ПРИЧИНА красной постуры (цикл #198, карточка «CRITICAL — это ЭХО нашей же остановки») ──
#
# Каждый тест ниже — положительный контроль: на модуле БЕЗ починки `posture_reason` в выводе
# нет вовсе, и все они краснеют. Замер аварии, ради которой они написаны (прод 10.08 09:11:55Z):
# `threat_posture.clear=true`, `n_threats=0`, `attack_surface.critical_count=0`,
# `kill_switch_already_active=true` — разведка НЕ наблюдала ничего, а печатала CRITICAL, и
# читателю нечем было отличить врага в периметре от нашей же остановки.

def test_kill_switch_echo_is_named_as_the_only_cause(tmp_path):
    """Снимок прода 10.08: угроз ноль, критических находок ноль — красит ТОЛЬКО наш же выключатель."""
    tp, ap = _seed(tmp_path, clear=True, threats=[], critical=0, kill=True)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "CRITICAL"                       # лестница НЕ ослаблена
    assert out["posture_reason"] == ["kill_switch_already_active"]
    assert out["threat_posture"]["value"]["n_threats"] == 0    # разведка не наблюдала ничего
    assert out["attack_surface"]["value"]["critical_count"] == 0


def test_every_contributing_cause_is_named_not_just_the_first(tmp_path):
    """Причины собираются ДО лестницы — иначе «остановка» затмила бы настоящую находку атаки."""
    tp, ap = _seed(tmp_path, clear=False, threats=["morpho oracle drift"], critical=2, kill=True)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "CRITICAL"
    assert out["posture_reason"] == ["kill_switch_already_active",
                                     "attack_surface_critical", "threats_present"]


def test_calm_posture_names_no_cause(tmp_path):
    """Контроль в обратную сторону: причина не выдумывается там, где красить нечем."""
    tp, ap = _seed(tmp_path, clear=True, threats=[], critical=0, kill=False)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "NO_THREAT_OBSERVED"
    assert out["posture_reason"] == []


def test_threats_without_kill_name_only_threats(tmp_path):
    tp, ap = _seed(tmp_path, clear=False, threats=["aave peg wobble"], critical=0, kill=False)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "THREATS_PRESENT"
    assert out["posture_reason"] == ["threats_present"]


def test_failclosed_paths_name_their_cause_too(tmp_path):
    """Осторожный вердикт тоже обязан сказать ПОЧЕМУ — иначе «UNKNOWN» так же слеп, как «CRITICAL»."""
    tp, ap = _seed(tmp_path, threat=False)                 # входа нет вовсе → fail-closed
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path).analyze()
    assert out["posture"] == "UNKNOWN_CAUTIOUS"
    assert out["posture_reason"] == ["threat_data_missing_or_stale"]

    # вход ЕСТЬ, но он не даёт ни «чисто», ни угроз — вторая, отдельная ветка осторожности
    tp2, ap2 = _seed(tmp_path, clear=False, threats=[], critical=0, kill=False)
    out2 = RedTeamAgent(threat_path=tp2, attack_path=ap2, data_dir=tmp_path).analyze()
    assert out2["posture"] == "UNKNOWN_CAUTIOUS"
    assert out2["posture_reason"] == ["threat_data_inconclusive"]


def test_reason_survives_into_the_written_artifact(tmp_path):
    """Причина обязана дойти до ЧИТАТЕЛЯ (файла), а не остаться внутри analyze()."""
    tp, ap = _seed(tmp_path, clear=True, threats=[], critical=0, kill=True)
    doc = json.loads(RedTeamAgent(threat_path=tp, attack_path=ap,
                                  data_dir=tmp_path).run(now=_dt()).read_text())
    assert doc["posture"] == "CRITICAL"
    assert doc["posture_reason"] == ["kill_switch_already_active"]
