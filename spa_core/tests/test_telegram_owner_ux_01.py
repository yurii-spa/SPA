# LLM_FORBIDDEN
# FROZEN-DATE-OK: dates are the subject — PDF incident fixtures rendered verbatim; no freshness is judged against the clock
"""TELEGRAM-OWNER-UX-01 (ADR-OWN-2026-10-28, задание docs/tasks/telegram-owner-alerts-2026-10-28.md).

Девять случаев из разбора владельца (PDF 14–28.10, SHA256 a9cc7dba…) — на ВРЕМЕННЫХ фикстурах
и с ФИКТИВНЫМ отправителем: ни один тест не зовёт рабочий транспорт, не трогает живую очередь
сводки и не пишет в рабочие данные (всё — в ``tmp_path``). Тексты фикстур — обезличенные
системные сообщения из PDF; личной переписки здесь нет.

Каждый тест проверяет СМЫСЛ, а не наличие функции: что владелец прочтёт, что не прочтёт, и
что числа/время/неизвестное не потерялись. Случаи 1 и 2 (COMMIT/REVEAL и постоянный INCIDENT)
живут во втором репозитории (earn-defi) и покрыты его тестами — доказательства раздельные.
"""
from __future__ import annotations

import json

import pytest

from spa_core.monitoring import dashboard_watcher as dw
from spa_core.monitoring import resource_guard as rg
from spa_core.telegram import humanize, push_policy
from spa_core.telegram import owner_decisions as od
from spa_core.telegram.reports import daily


@pytest.fixture
def fake_sender(monkeypatch):
    """Фиктивный транспорт push_policy: копит тексты, сеть не трогает."""
    sent: list[str] = []
    outcome = {"ok": True}

    def _fake(text: str) -> bool:
        sent.append(text)
        return outcome["ok"]

    monkeypatch.setattr(push_policy, "_send", _fake)
    sent_outcome = outcome
    return sent, sent_outcome


def _queue(tmp_path):
    return push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)


# ── Случай 3: «Agent DOWN: com.spa.resource_guard ×12» при нуле CRITICAL ──────────────────

RG_WARN = {"label": "com.spa.resource_guard", "status": "WARNING", "pid": 0, "last_exit": 1,
           "loaded": True, "category": "high_freq", "log_age_min": 1.6,
           "issue": "ресурсы Мака: измерено WARN (память/своп) — код 1 по договору resource_guard, "
                    "не сбой агента"}


def _route_findings(monkeypatch, tmp_path, snapshots):
    """Прогнать находки dashboard_watcher в ВРЕМЕННУЮ очередь (дедуп /tmp отключён)."""
    monkeypatch.setattr(push_policy, "_tg_dir", lambda data_dir=None: tmp_path / "telegram")
    monkeypatch.setattr(dw, "_is_seen", lambda key: False)
    monkeypatch.setattr(dw, "_mark_seen", lambda key: None)
    monkeypatch.setattr(dw, "_is_in_cooldown", lambda kind: False)
    for snap in snapshots:
        for f in dw.check_agent_health(snap):
            dw.maybe_send(f, {})


def test_case3_measured_warning_is_not_down_and_twelve_observations_are_one_problem(monkeypatch, tmp_path):
    snap = {"overall_status": "WARNING", "agents": [RG_WARN]}
    _route_findings(monkeypatch, tmp_path, [snap] * 12)
    items = _queue(tmp_path)
    assert len(items) == 12                                   # наблюдения не потеряны
    assert {i["incident"] for i in items} == {"agent:measured:com.spa.resource_guard"}
    section = daily._format_digest_section(items)
    assert "DOWN" not in section and "×12" not in section
    assert "событий с прошлого отчёта: 12, из них с CRITICAL: 0" in section
    assert "разных проблем: 1, из них критичных: 0" in section
    assert "Контроль ресурсов Mac сообщает о нехватке ресурсов" in section
    assert "агент отработал штатно" in section and "наблюдений: 12" in section


def test_case3_a_really_stopped_agent_stays_visible_and_critical(monkeypatch, tmp_path):
    stopped = {"label": "com.spa.autopush", "status": "CRITICAL", "pid": 0, "loaded": False,
               "category": "always_on", "issue": "not loaded in launchctl"}
    _route_findings(monkeypatch, tmp_path, [{"overall_status": "CRITICAL", "agents": [RG_WARN, stopped]}])
    items = _queue(tmp_path)
    kinds = {i["incident"] for i in items}
    assert "agent:stopped:com.spa.autopush" in kinds
    section = daily._format_digest_section(items)
    assert "Ключевой агент com.spa.autopush: не работает" in section
    # критичное стоит первым и посчитано как критичная проблема
    assert section.index("com.spa.autopush") < section.index("Контроль ресурсов")
    # критичных два: остановленный ключевой агент и общий CRITICAL флота из этого снимка;
    # измеренное предупреждение resource_guard критичным не считается
    assert "из них критичных: 2" in section


@pytest.mark.parametrize("agent,subtype,words", [
    ({"label": "com.spa.x", "status": "WARNING", "pid": 0, "last_exit": 1, "issue": "log stale"},
     "warning", "предупреждение (это не остановка агента)"),
    ({"label": "com.spa.x", "status": "STALE"}, "stale", "сведения о нём устарели"),
    ({"label": "com.spa.x", "status": "UNCHECKED"}, "unchecked", "состояние не измерено"),
    ({"label": "com.spa.x", "status": "MYSTERY"}, "unchecked", "состояние не измерено"),
    ({"label": "com.spa.srv", "status": "CRITICAL", "pid": 0, "issue": "PID=0 (server down)"},
     "stopped", "не работает"),
    ({"label": "com.spa.x", "status": "CRITICAL", "pid": 5, "issue": "log stale 42 min"},
     "critical", "критическое состояние"),
    # resource_guard, код 2: ARB 27.10 оставил его прежней веткой — не «штатный замер»
    ({"label": "com.spa.resource_guard", "status": "WARNING", "pid": 0, "last_exit": 2,
      "issue": "last_exit=2"}, "warning", "предупреждение"),
])
def test_point1_each_state_has_its_own_meaning(agent, subtype, words):
    out = dw.check_agent_health({"overall_status": "WARNING", "agents": [agent]})
    assert [f["subtype"] for f in out] == [subtype]
    assert words in dw.agent_summary(out[0])
    if agent["status"] == "MYSTERY":                         # неизвестный статус назван дословно
        assert "статус источника: MYSTERY" in out[0]["issues"]


def test_point1_owner_disabled_agent_is_not_a_finding():
    # agent_health пишет отключённого владельцем агента как OK с пометкой — это не сбой.
    snap = {"overall_status": "OK", "agents": [
        {"label": "com.spa.x", "status": "OK", "pid": 0, "loaded": False,
         "note": "intentionally disabled (launchctl disable)"}]}
    assert dw.check_agent_health(snap) == []


# ── Дневная сводка: 0 / 1 / 2 / 3 события, неизвестный код, одинаковое начало, HTML ─────

def test_digest_zero_one_two_three_events_are_readable_russian():
    zero = daily._format_digest_section([])
    assert "отложенных событий с прошлого отчёта нет" in zero
    one = daily._format_digest_section([{"event_key": "system_health_summary", "body": ""}])
    assert "сводка проверки здоровья системы" in one and "system_health_summary" not in one
    two = daily._format_digest_section([
        {"event_key": "system_health_summary", "body": ""},
        {"event_key": "apy_spike", "body": "compound_v3 9.20% > 8.00%"}])
    assert "разных проблем: 2" in two and "compound_v3 9.20% &gt; 8.00%" in two
    three = daily._format_digest_section([
        {"event_key": "a", "body": "⚠️ первая проблема"},
        {"event_key": "b", "body": "⚠️ вторая проблема"},
        {"event_key": "c", "body": "⚠️ третья проблема"}])
    assert all(x in three for x in ("первая", "вторая", "третья"))


def test_digest_unknown_code_gets_an_honest_general_explanation_and_keeps_the_code():
    ev = humanize.describe_queued_event({"event_key": "zz_new_probe", "body": ""})
    assert ev["known"] is False
    assert "событие без описания" in ev["text"] and "zz_new_probe" in ev["text"]


def test_digest_distinct_problems_with_the_same_first_120_chars_do_not_merge():
    head = "⚠️ " + "очень длинное общее начало строки " * 5
    items = [{"event_key": "x", "body": head + "— причина A"},
             {"event_key": "x", "body": head + "— причина B"}]
    assert len(head) > 120
    section = daily._format_digest_section(items)
    assert "разных проблем: 2" in section


def test_digest_a_changing_age_or_time_is_the_same_incident_but_worse_severity_is_new():
    a = humanize.describe_queued_event({"event_key": "k", "body": "⚠️ лог устарел 12.5 мин назад (10:15)"})
    b = humanize.describe_queued_event({"event_key": "k", "body": "⚠️ лог устарел 48.0 мин назад (11:02)"})
    c = humanize.describe_queued_event({"event_key": "k", "body": "🔴 лог устарел 48.0 мин назад (11:02)"})
    assert a["incident"] == b["incident"]
    assert c["incident"] != b["incident"]


def test_digest_is_html_safe_and_hashes_are_not_events():
    items = [{"event_key": "x", "body": "⚠️ <script>alert(1)</script> & co"},
             {"event_key": "book_commit", "title": "Book commitment",
              "body": "sha256 f22a960c59ce4eebb8deac43b45961c75cec0fdb1327ca5f58567d6800d4ae17"}]
    section = daily._format_digest_section(items)
    assert "<script>" not in section and "&amp;" in section
    assert "f22a960c" not in section


def test_digest_counts_observations_problems_and_says_queue_is_not_a_send():
    items = [{"event_key": "k", "severity": "CRITICAL", "body": "🔴 X"}] * 3 + [{"event_key": "j", "body": "⚠️ Y"}]
    section = daily._format_digest_section(items)
    assert "событий с прошлого отчёта: 4, из них с CRITICAL: 3" in section
    assert "разных проблем: 2, из них критичных: 1" in section
    assert "отдельными сообщениями эти события не отправлялись" in section


# ── Случай 4: «Ресурсы Мака на исходе» при нормальной RAM ─────────────────────────────

def _rg_report():
    return {
        "overall": rg.CRITICAL, "generated_at": "2026-10-26T21:21:26Z",
        "disk": {"state": rg.WARN, "free_gb": 22.8, "total_gb": 460.4},
        "memory": {"state": rg.CRITICAL, "pressure_level": 1, "ram_total_gb": 24.0,
                   "swap": {"used_mb": 9.7 * 1024, "total_mb": 10.0 * 1024, "used_pct": 97.3},
                   "triggers": [{"signal": "swap", "state": rg.CRITICAL}]},
        "processes": {"top": [{"cmd": "/Applications/Google Chrome.app/x", "rss_mb": 0.8 * 1024,
                               "label": "application.com.google.Chrome.795720550.903014360"}]},
        "disposable_backlog": {"count": 452},
    }


def test_case4_resources_message_names_what_fired_and_keeps_every_number(tmp_path, fake_sender):
    sent, _ = fake_sender
    assert rg.notify(_rg_report(), data_dir=tmp_path) is True
    text = sent[-1]
    assert "Ресурсы Mac: своп заполнен, мало места на диске" in text
    assert "на исходе" not in text
    assert "заполнен файл подкачки (своп) — критично" in text
    assert "на диске мало места — предупреждение" in text
    assert "давление на оперативную память в норме" in text
    for number in ("97,3", "22,8", "460,4", "24,0"):
        assert number in text, number
    assert "Влияние на работу системы: не установлено" in text and "не назначен" in text
    assert "Chrome (приложение)" in text and "795720550" not in text
    assert "--cleanup --apply" not in text and "expired disposable" not in text
    assert "452" in text and "сколько места они занимают, этот замер не установил" in text


def test_case4_same_incident_is_silent_and_worsening_pushes_again(tmp_path, fake_sender):
    sent, _ = fake_sender
    rg.notify(_rg_report(), data_dir=tmp_path)
    assert rg.notify(_rg_report(), data_dir=tmp_path) is False     # тот же инцидент — молчит
    worse = _rg_report()
    worse["disk"]["state"] = rg.CRITICAL                            # ухудшение — новый инцидент
    assert rg.notify(worse, data_dir=tmp_path) is True
    assert len(sent) == 2


# ── Доставка: сбой отправки не считается доставкой; след инцидента ─────────────────────

def test_send_failure_is_not_delivery_and_is_retried(tmp_path, fake_sender):
    sent, outcome = fake_sender
    outcome["ok"] = False
    assert push_policy.push_critical("core_agent_down", "CRITICAL", "T", "B",
                                     data_dir=tmp_path, dedup_key="a") is False
    rec = push_policy.current_record("core_agent_down", data_dir=tmp_path)
    assert rec["entry_pushed"] is False
    outcome["ok"] = True
    assert push_policy.push_critical("core_agent_down", "CRITICAL", "T", "B",
                                     data_dir=tmp_path, dedup_key="a") is True
    rec = push_policy.current_record("core_agent_down", data_dir=tmp_path)
    assert rec["entry_pushed"] is True
    from spa_core.alerts.telegram_client import text_fingerprint
    assert rec["entry_text_sha256"] == text_fingerprint(sent[-1])


def test_history_keeps_a_bounded_trace_of_the_full_text(tmp_path, monkeypatch):
    from spa_core.alerts import telegram_client as tc
    path = tmp_path / "alert_history.json"
    monkeypatch.setattr(tc, "_HISTORY_STATE", str(path))
    monkeypatch.setenv("SPA_ALERT_HISTORY_TEST", "1")
    text = "🚨 <b>Агенты: критическая проблема</b>\n" + "длинное тело " * 40
    tc._record_history(text, ok=True, message_id=777)
    entry = json.loads(path.read_text(encoding="utf-8"))["entries"][-1]
    assert entry["text_sha256"] == tc.text_fingerprint(text)
    assert entry["chars"] == len(text) and len(entry["preview"]) <= 80
    assert text not in json.dumps(entry, ensure_ascii=False)        # полный текст не хранится


# ── Случай 5: длинный CRITICAL агентов — английские хвосты и коды ──────────────────────

def test_case5_agent_critical_lines_are_russian_and_keep_numbers_and_problem_ref():
    body = ("❌ com.spa.digest_weekly — no run since reboot 9.4d (>2.5d) — missed first scheduled run "
            "due by 2026-10-18T08:15:00Z [Problem com.spa.digest_weekly.no_run_since_reboot]\n"
            "⚠️ fleet parity DRIFT (5 retired-still-installed, 8 orphan-plist)")
    out = humanize.humanize_body(body)
    assert "no run since reboot" not in out and "retired-still-installed" not in out
    assert "9.4 дн" in out and "2.5 дн" in out and "2026-10-18T08:15:00Z" in out
    assert "[Problem com.spa.digest_weekly.no_run_since_reboot]" in out
    assert "списаны, но ещё установлены — 5" in out and "— 8" in out


def test_case5_same_incident_does_not_repeat_but_a_new_cause_does(tmp_path, fake_sender):
    sent, _ = fake_sender
    for fp in ("a|b", "a|b", "a|b|c"):
        push_policy.push_critical("agent_health_critical", "CRITICAL", "SPA Agent Health — CRITICAL",
                                  "body", data_dir=tmp_path, dedup_key=fp)
    assert len(sent) == 2


# ── Случай 7: цепочка сторожа — по-русски, без обещания результата ─────────────────────

def test_case7_watchdog_lines_are_russian_and_do_not_claim_recovery():
    out = humanize.humanize_body("🛡️ <b>SPA Watchdog</b> (guardian-of-guardians)\n"
                                 "⚠️ guardian com.spa.self_heal heartbeat stale (119.6min old)\n"
                                 "✅ kickstarted com.spa.self_heal (stale: 119.6min old)")
    assert "guardian" not in out and "heartbeat" not in out and "kickstart" not in out
    assert "119.6 мин" in out
    assert "что агент ожил, это сообщение не подтверждает" in out


# ── Случай 8: поручение не выдаётся за решение владельца ──────────────────────────────

def test_case8_assignment_card_is_not_titled_as_an_owner_decision():
    text = od.build_message("Агент-наблюдатель просыпается раз в 7,6 часа вместо 6",
                            "## Что случилось\nНастройка расписания.\n", [], has_buttons=True,
                            ack_buttons=True)
    assert "Нужно твоё решение" not in text
    assert text.startswith("📋 <b>Поручение системе — нужно только подтверждение</b>")
    assert "Выбора в карточке нет" in text and "НЕ взята в работу" in text
    assert "Молчание ответом не считается" in text


def test_case8_a_real_decision_keeps_its_title():
    opts = [od.ParsedOption(num="1", label="вариант", recommended=False)]
    text = od.build_message("Вопрос", "## Что случилось\nx\n", opts, has_buttons=True)
    assert text.startswith("🧑‍⚖️ <b>Нужно твоё решение</b>")


# ── Случай 9: ежедневная простыня про красный CI ──────────────────────────────────────

def test_case9_red_ci_is_one_line_per_series_and_says_what_it_does_not_measure():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "mwd_ux01", Path(__file__).resolve().parents[2] / "scripts" / "morning_work_digest.py")
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    block = m._ci_block("АВТОПРОВЕРКА КОДА: КРАСНАЯ. «SPA Tests» красное 61.4 суток (последний "
                        "зелёный 2026-08-26T22:25:03Z); «SPA CI» красное 61.4 суток (последний "
                        "зелёный 2026-08-26T22:25:03Z).")
    assert block.count("Автопроверка кода КРАСНАЯ") == 1
    assert "61.4 суток" in block and "«SPA Tests», «SPA CI»" in block
    assert "Новые ли это падения, эта строка не измеряет" in block
    assert "зелён" in block and "NO_REGRESSION" not in block


# ── «аварий нет» по одной подсистеме ─────────────────────────────────────────────────

def test_one_subsystem_clear_is_not_a_whole_system_claim(tmp_path):
    (tmp_path / "emergency_status.json").write_text(json.dumps({
        "status": "CLEAR", "checked_at": "2026-10-28T07:00:20+00:00",
        "checks": {"eb01": {"status": "PASS"}, "eb03": {"status": "SKIP"}}}), encoding="utf-8")
    line = daily._fleet_line(tmp_path, {})
    assert "аварий нет" not in line
    assert "аварийные правила SPA не сработали" in line and "не измерено 1" in line
