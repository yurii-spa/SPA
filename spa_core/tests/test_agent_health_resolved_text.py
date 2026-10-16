"""Снятие тревоги агентов владельцу (ARB 16.10).

Первое снятие на исправленном коде (16.10 01:22Z) ушло старым текстом «Агенты: всё восстановилось ·
All agents healthy again.» — по-английски и при пяти оставшихся предупреждениях. Снятие обязано
называть ровно то, что снято, время проверки, что осталось по видам и нужно ли решение.
"""
# FROZEN-DATE-OK: the literal timestamp IS the subject — it is printed verbatim in Madrid time; no freshness window is judged
from __future__ import annotations

import json

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.telegram import humanize

TS = "2026-10-16T01:22:21+00:00"


def _report(agents, system_issues=()):
    return {"timestamp": TS, "overall_status": ahm.WARNING if any(a["status"] != ahm.OK for a in agents) else ahm.OK,
            "agents": list(agents), "system_issues": list(system_issues)}


def _agent(label, status=ahm.OK, issue="", evidence=None):
    return {"label": label, "status": status, "issue": issue, "evidence": evidence}


def test_resolved_names_what_remains_not_all_healthy():
    rep = _report([
        _agent("com.spa.site_freshness", ahm.WARNING, "last_exit=1"),
        _agent("com.spa.weekly_backup", ahm.WARNING, "retired_but_loaded — label is in RETIRED_LABELS"),
        _agent("com.spa.sky_monitor", ahm.OK, "", ahm.EVIDENCE_AWAITING_FIRST_RUN),
        _agent("com.spa.hy_cycle", ahm.OK, "", ahm.EVIDENCE_RECEIPT),
    ], ["fleet parity DRIFT"])
    msg = ahm.format_resolved(rep)
    assert "критичных сбоев агентов больше нет" in msg
    assert "2026-10-16 03:22 Мадрид (CEST)" in msg
    assert "предупреждений: 2" in msg
    assert "расхождение настройки" in msg and "системные пункты: 1" in msg
    assert "ждут первого планового запуска после перезагрузки: 1 — это не сбой" in msg
    assert "Нужно ли твоё решение:</b> нет" in msg
    assert "healthy" not in msg.lower() and "всё восстановилось" not in msg


def test_resolved_with_nothing_left_says_so():
    msg = ahm.format_resolved(_report([_agent("com.spa.a")]))
    assert "замечаний нет" in msg


def test_resolve_push_uses_the_precise_title_and_the_new_body(tmp_path, monkeypatch):
    sent = {}
    from spa_core.telegram import push_policy

    def fake_resolve(event, title, body, **kw):
        sent.update(event=event, title=title, body=body)
        return True
    monkeypatch.setattr(push_policy, "resolve", fake_resolve)
    rep = _report([_agent("com.spa.site_freshness", ahm.WARNING, "last_exit=1")])
    assert ahm._push_via_policy(rep, data_dir=tmp_path) is True
    assert sent["event"] == "agent_health_critical"
    assert humanize.humanize_title(sent["title"]) == "Агенты: критичных сбоев больше нет"
    assert "All agents healthy again" not in sent["body"] and "предупреждений: 1" in sent["body"]
    json.dumps(sent)
