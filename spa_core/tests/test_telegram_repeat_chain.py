"""Сквозная цепочка повторяющегося сообщения: источник → код причины → событие → ОДНА задача → устранение.

ARB 27.10 §6: повтор той же причины не плодит задач; дрейф числа/времени в тексте не ломает
дедупликацию; новая критическая причина не теряется; после восстановления — одно «восстановлено».
Отправитель поддельный (`push_policy._send`), Юрию ничего не уходит; хранилища — во временном каталоге.
"""
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import problem_store as ps
from spa_core.telegram import push_policy

T0 = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — update_store(now=T0+…), push_critical(now=T0+…)


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(push_policy, "_send", lambda text: box.append(text) or True)
    return box


def _report(issue):
    return {"overall": "CRITICAL", "agents": [{"label": "com.spa.telegram_bot", "status": "CRITICAL",
                                               "issue": issue}], "system_issues": []}


def _tick(store, issue, hour, data_dir):
    now = T0 + timedelta(hours=hour)
    cond = [] if issue is None else [{"agent": "com.spa.telegram_bot",
                                      "cause_code": ps.cause_from_agent_issue(issue) or "unknown",
                                      "severity": "CRITICAL", "detail": issue, "source": "agent_health"}]
    store, events = ps.update_store(store, cond, {"agent_health": {"status": "measured"}}, now=now)
    for ev in events:                       # как run_once: открывшаяся проблема получает ОДНУ карточку
        ev.entry["card_path"] = f"tracker/agent-task-{ev.problem_id}.md"
    if issue is None:
        push_policy.push_critical("agent_health_critical", "INFO", "ok", resolved=True,
                                  data_dir=data_dir, now=now)
    else:
        push_policy.push_critical("agent_health_critical", "CRITICAL", "сбой", issue, data_dir=data_dir,
                                  now=now, dedup_key=ahm.alert_fingerprint(_report(issue)))
    return store, events


def test_repeat_with_drifting_numbers_is_one_problem_and_one_message(tmp_path, sent):
    store = {"problems": {}}
    opened = []
    for h, issue in enumerate(["маячку 971с (норма ≤ 300) — процесс есть, но цикл не крутится",
                               "маячку 1062с (норма ≤ 300) — процесс есть, но цикл не крутится",
                               "маячку 1430с (норма ≤ 300) — процесс есть, но цикл не крутится"]):
        store, ev = _tick(store, issue, h, tmp_path)
        opened += ev
    assert len(store["problems"]) == 1, "дрейф числа завёл вторую задачу"
    assert len(opened) == 1, "повтор той же причины открыл задачу заново"
    assert len(sent) == 1, f"одна причина — одно сообщение, а не {len(sent)}"


def test_new_critical_cause_is_not_lost_and_recovery_is_announced_once(tmp_path, sent):
    store = {"problems": {}}
    store, _ = _tick(store, "маячку 971с (норма ≤ 300) — процесс есть, но цикл не крутится", 0, tmp_path)
    store, _ = _tick(store, "PID=0 (server down)", 1, tmp_path)          # ДРУГАЯ причина
    assert len(sent) == 2, "новая критическая причина потерялась за дедупликацией"
    store, _ = _tick(store, None, 2, tmp_path)
    store, _ = _tick(store, None, 3, tmp_path)
    assert len(sent) == 3 and "RESOLVED" in sent[-1].upper() or "✅" in sent[-1]


def test_two_cyrillic_causes_of_one_agent_get_distinct_ids():
    a = ps.problem_id("com.spa.x", ps.cause_from_agent_issue("маячку 971с (норма ≤ 300) — процесс есть, но цикл не крутится"))
    b = ps.problem_id("com.spa.x", ps.cause_from_agent_issue("процесс завис без маячка"))
    assert a != b and not a.endswith(".")
    assert ps.problem_id("com.spa.x", "stale_log") == "com.spa.x.stale_log", "латинские id не меняются"
