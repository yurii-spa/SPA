"""S4 K5 / TELEGRAM-OWNER-UX-01 (первый установленный дефект): WARNING агента — не «Agent DOWN».

Разбор ARB 28.10: `resource_guard` с кодом 1 по договору (измеренное предупреждение) владелец видел как
«Agent DOWN ×5». Ключ находки при этом НЕ меняется — push_policy узнаёт по нему уже открытый инцидент,
и смена ключа сделала бы старый инцидент новым (E7.3)."""
from spa_core.monitoring import dashboard_watcher as dw


def _data(status):
    return {"overall_status": "WARNING", "agents": [
        {"label": "com.spa.resource_guard", "status": status, "issue": "last_exit=1", "log_age_min": 3.0}]}


def test_warning_is_worded_as_a_warning_not_a_stop():
    (f,) = dw.check_agent_health(_data("WARNING"))
    assert f["subtype"] == "warning" and f["key"] == "agent:down:com.spa.resource_guard"
    text = dw.format_agent_alert(f, {})
    assert "DOWN" not in text and "WARNING" in text and "not stopped" in text


def test_critical_still_says_down():
    (f,) = dw.check_agent_health(_data("CRITICAL"))
    assert f["subtype"] == "down" and "Agent DOWN" in dw.format_agent_alert(f, {})


def test_incident_identity_is_unchanged_between_warning_and_down():
    (w,) = dw.check_agent_health(_data("WARNING"))
    (c,) = dw.check_agent_health(_data("CRITICAL"))
    assert w["key"] == c["key"]


def test_down_after_a_warning_is_not_swallowed_by_the_warning_dedup(monkeypatch):
    """Ревью S4: остановка через минуты после предупреждения не должна глушиться 2-часовым дедупом."""
    seen = set()
    monkeypatch.setattr(dw, "_is_seen", lambda k: k in seen)
    monkeypatch.setattr(dw, "_mark_seen", lambda k: seen.add(k))
    monkeypatch.setattr(dw, "_is_in_cooldown", lambda kind: False)
    sent = []
    monkeypatch.setattr(dw, "send_telegram", lambda text: sent.append(text) or True)
    (w,) = dw.check_agent_health(_data("WARNING"))
    (c,) = dw.check_agent_health(_data("CRITICAL"))
    dw.maybe_send(w, {})
    dw.maybe_send(c, {})
    assert any("DOWN" in t for t in sent) and any("WARNING" in t for t in sent)
