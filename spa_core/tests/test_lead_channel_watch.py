"""spa_core/tests/test_lead_channel_watch.py — сторож канала «заявка с сайта → владелец».

Решение владельца 2026-08-22 (карточка `owner-decision-prover-odno-pole-dohodyat-li-do-tebya-za`,
вариант 1): поставить сторожа, который закричит, если канал ОТВАЛИТСЯ потом.

**Каждый тест здесь — воспроизведение настоящей аварии, а не украшение** (правило
`.claude/rules/deployment.md`, «проверка сторожа сторожей»). Классы аварий, по одному на тест:

* связка ключей пуста / ключ переименован ⇒ заявка ложится в файл, владелец не узнаёт;
* `pilot_request` выпал из Tier-1 ⇒ мгновенный пинг молча демотится в дайджест;
* `pilot_request` выпал из one-shot ⇒ ВТОРАЯ заявка глохнет edge-триггером;
* обработчик перестал звать уведомитель (проводка) ⇒ все части исправны и зелены, канала нет;
* среда не умеет мерить (нет `security`) ⇒ обязано быть «не измерено», а НЕ «всё хорошо».

Плюс два обратных контроля: на НАСТОЯЩЕМ исходнике `interest.py` и на НАСТОЯЩЕМ `push_policy`
сторож обязан быть зелёным — иначе он ложная тревога, а ложный отказ здесь опаснее пропуска.

PURE / без сети / без обращения к настоящей связке ключей: все пробы инъектируются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import lead_channel_watch as LCW

FIXED_NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)  # время — ВХОД, тест бессмертен

def _creds(ok=True, missing=(), error=None):
    return lambda: {"ok": ok, "missing": list(missing), "error": error}


_GOOD = dict(
    creds_status=_creds(),
    keychain_available=lambda: True,
    whitelist=frozenset({"pilot_request"}),
    oneshot=frozenset({"pilot_request"}),
    source="@router.post('/api/pilot/request')\ndef h(r):\n    return _notify_owner_telegram(r)\n",
)


def _check(**over):
    kwargs = dict(_GOOD)
    kwargs.update(over)
    return LCW.check(now=FIXED_NOW, **kwargs)


def _probe(verdict, name):
    return next(p for p in verdict.probes if p.name == name)


# ── обратные контроли: на исправном канале сторож ЗЕЛЁН ─────────────────────
def test_healthy_channel_is_ok():
    v = _check()
    assert v.status == LCW.OK
    assert v.severity is None
    assert all(p.status == LCW.OK for p in v.probes)


def test_real_endpoint_source_is_wired():
    """Проводка меряется на НАСТОЯЩЕМ модуле, не на копии.

    Если кто-то переименует уведомитель или уберёт вызов из обработчика — краснеет здесь,
    а не у владельца через месяц молчания. Сверять надо с ИСТОЧНИКОМ: сторож, сравнивающий
    копию с копией, зелен ровно в ту аварию, ради которой написан.
    """
    from spa_core.api.routers import interest

    probe = LCW.probe_wiring(source_path=Path(interest.__file__))
    assert probe.status == LCW.OK, probe.detail


def test_real_push_policy_still_carries_the_lead_key():
    probes = {p.name: p for p in LCW.probe_route_keys()}
    assert probes["tier1_key"].status == LCW.OK, probes["tier1_key"].detail
    assert probes["oneshot_key"].status == LCW.OK, probes["oneshot_key"].detail


# ── авария 1: связка ключей ────────────────────────────────────────────────
def test_missing_keychain_entry_is_broken_and_critical():
    v = _check(creds_status=_creds(ok=False, missing=["TELEGRAM_BOT_TOKEN_SPA"]))
    assert v.status == LCW.BROKEN
    assert v.severity == "CRITICAL"          # внешняя тихая авария — зовём владельца
    assert "TELEGRAM_BOT_TOKEN_SPA" in _probe(v, "credentials").detail


def test_empty_credential_value_is_broken():
    """Запись есть, значение пустое — авторитет считает это отсутствием ключа."""
    v = _check(creds_status=_creds(ok=False, missing=["TELEGRAM_CHAT_ID_SPA"]))
    assert v.status == LCW.BROKEN
    assert "TELEGRAM_CHAT_ID_SPA" in _probe(v, "credentials").detail


def test_unknown_credential_failure_is_unchecked_not_broken():
    """Незнакомая поломка пробы ≠ «ключа нет». Сомнение → «не измерено», не приговор."""
    v = _check(creds_status=_creds(ok=None, error="RuntimeError('keychain daemon busy')"))
    assert v.status == LCW.UNCHECKED
    assert _probe(v, "credentials").status == LCW.UNCHECKED


# ── авария 2/3: ключ маршрута ──────────────────────────────────────────────
def test_key_dropped_from_tier1_is_broken_but_only_warning():
    v = _check(whitelist=frozenset({"kill_switch"}))
    assert v.status == LCW.BROKEN
    assert v.severity == "WARNING"           # наша собственная доставка — владельца не зовём
    assert _probe(v, "tier1_key").status == LCW.BROKEN


def test_key_dropped_from_oneshot_is_broken():
    """Ровно тот дефект, из-за которого `golive_ready` пришлось переводить в one-shot:
    без него ВТОРАЯ заявка молчит как «всё ещё плохо»."""
    v = _check(oneshot=frozenset())
    assert v.status == LCW.BROKEN
    assert _probe(v, "oneshot_key").status == LCW.BROKEN
    assert "ВТОРАЯ" in _probe(v, "oneshot_key").detail


# ── авария 4: проводка ─────────────────────────────────────────────────────
def test_notifier_call_removed_from_handler_is_broken():
    src = "@router.post('/api/pilot/request')\ndef h(r):\n    return {'ok': True}\n"
    v = _check(source=src)
    assert v.status == LCW.BROKEN
    assert _probe(v, "wiring").status == LCW.BROKEN


def test_notifier_named_only_in_a_comment_is_not_wiring():
    """Разбор по AST, а не по подстроке: комментарий, объясняющий вызов, вызовом не является.
    На этом уже обжигались — сканер неподключённых скриптов снимал скрипт с учёта по
    упоминанию его имени в комментарии."""
    src = ("@router.post('/api/pilot/request')\n"
           "def h(r):\n"
           '    """раньше здесь звали _notify_owner_telegram(r)"""\n'
           "    # _notify_owner_telegram(r)\n"
           "    return {'ok': True}\n")
    v = _check(source=src)
    assert _probe(v, "wiring").status == LCW.BROKEN


def test_handler_gone_entirely_is_broken():
    v = _check(source="def unrelated():\n    return _notify_owner_telegram(1)\n")
    assert _probe(v, "wiring").status == LCW.BROKEN
    assert "нет обработчика" in _probe(v, "wiring").detail


def test_unparsable_source_is_unchecked_not_ok():
    v = _check(source="def broken(:\n")
    assert v.status == LCW.UNCHECKED
    assert _probe(v, "wiring").status == LCW.UNCHECKED


def test_missing_source_file_is_unchecked():
    probe = LCW.probe_wiring(source_path=Path("/nonexistent/interest.py"))
    assert probe.status == LCW.UNCHECKED


# ── «не измерено» никогда не равно «всё хорошо» ────────────────────────────
def test_no_security_binary_is_unchecked_not_ok():
    v = _check(keychain_available=lambda: False)
    assert v.status == LCW.UNCHECKED
    assert v.status != LCW.OK and v.status != LCW.BROKEN
    assert _probe(v, "credentials").status == LCW.UNCHECKED


def test_broken_wins_over_unchecked_fail_closed():
    """Агрегация fail-CLOSED: одно сломанное перекрывает любое количество неизмеренного."""
    v = _check(keychain_available=lambda: False, whitelist=frozenset())
    assert v.status == LCW.BROKEN


# ── секреты наружу не уезжают (инвариант #7) ───────────────────────────────
def test_verdict_never_carries_the_secret_value():
    """Авторитет не отдаёт значение секрета — а сторож не имеет права его показать даже
    если бы отдал: проверяем ОБЕ стороны (инв. #7)."""
    secret = "1234567:AA-super-secret-bot-token"
    v = _check(creds_status=lambda: {"ok": True, "missing": [], "error": None, "value": secret})
    blob = repr(v.to_dict())
    assert secret not in blob
    assert "AA-super-secret" not in blob


# ── коды возврата CLI (fail-CLOSED) ────────────────────────────────────────
def test_cli_exit_codes(monkeypatch, tmp_path):
    for status, code in ((LCW.OK, 0), (LCW.UNCHECKED, 1), (LCW.BROKEN, 2)):
        monkeypatch.setattr(
            LCW, "check",
            lambda status=status, **k: LCW.Verdict(status=status, probes=[], checked_at="t"),
        )
        assert LCW.main(["--no-write", "--json"]) == code


def test_status_file_is_written_atomically(tmp_path):
    v = _check()
    path = LCW.write_status(v, data_dir=tmp_path)
    assert path is not None and path.exists()
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["status"] == LCW.OK
    assert {p["name"] for p in doc["probes"]} == {"credentials", "tier1_key", "oneshot_key", "wiring"}


# ── проводка САМОГО сторожа в отчёт здоровья ───────────────────────────────
# «Правь проводку, а не детали»: один удалённый вызов оставил бы 1364 теста зелёными.
def test_system_health_d7_includes_the_lead_channel_check(monkeypatch):
    from spa_core.monitoring import system_health_monitor as SHM

    monkeypatch.setattr(LCW, "check", lambda **k: LCW.Verdict(LCW.OK, [], "t"))
    mon = SHM.SystemHealthMonitor()
    ids = {c.id for c in mon.check_d7_hygiene()}
    assert "d7.lead_channel" in ids


@pytest.mark.parametrize(
    "verdict,expected",
    [
        (LCW.Verdict(LCW.BROKEN, [LCW.Probe("credentials", LCW.BROKEN, "ключей нет")], "t"), "CRITICAL"),
        (LCW.Verdict(LCW.BROKEN, [LCW.Probe("wiring", LCW.BROKEN, "вызова нет")], "t"), "WARNING"),
        (LCW.Verdict(LCW.UNCHECKED, [LCW.Probe("credentials", LCW.UNCHECKED, "нечем")], "t"), "SKIPPED"),
        (LCW.Verdict(LCW.OK, [LCW.Probe("credentials", LCW.OK, "ок")], "t"), "OK"),
    ],
)
def test_system_health_severity_comes_from_the_probe(monkeypatch, verdict, expected):
    """Тяжесть назначает ПРОБА, а не место вызова: пустая связка ключей — внешняя авария
    (зовём владельца), сломанная нами проводка — наша доставка (ADR-084, не зовём)."""
    from spa_core.monitoring import system_health_monitor as SHM

    monkeypatch.setattr(LCW, "check", lambda **k: verdict)
    mon = SHM.SystemHealthMonitor()
    res = mon._check_lead_channel("d7_hygiene")
    assert res.status == expected


def test_system_health_check_never_raises(monkeypatch):
    from spa_core.monitoring import system_health_monitor as SHM

    def boom(**k):
        raise RuntimeError("проба сорвалась")

    monkeypatch.setattr(LCW, "check", boom)
    res = SHM.SystemHealthMonitor()._check_lead_channel("d7_hygiene")
    assert res.status == "SKIPPED" and res.skipped_reason


# ── авторитет отвечает своим же кодом, а не копией ─────────────────────────
def test_authority_reports_missing_credentials(monkeypatch):
    """`push_policy.credentials_status` — единственный, кому позволено трогать транспорт
    (`test_no_rogue_telegram_senders` запрещает импорт транспорта всем вне списка, и
    запрещает НАМЕРЕННО шире своего предмета). Здесь проверяется, что он различает три
    исхода: ключей нет · всё на месте · измерить не удалось."""
    from spa_core.telegram import push_policy
    import spa_core.alerts.telegram_client as TC

    def no_token(*a, **k):
        raise EnvironmentError("Telegram credentials not found in Keychain")

    monkeypatch.setattr(TC, "get_bot_token", no_token)
    monkeypatch.setattr(TC, "get_chat_id", lambda: "chat")
    st = push_policy.credentials_status()
    assert st["ok"] is False and st["missing"] == [TC.TOKEN_SERVICE]

    monkeypatch.setattr(TC, "get_bot_token", lambda: "token")
    assert push_policy.credentials_status()["ok"] is True

    monkeypatch.setattr(TC, "get_chat_id", lambda: "   ")   # запись есть, значение пустое
    assert push_policy.credentials_status()["ok"] is False

    def boom():
        raise RuntimeError("keychain daemon busy")

    monkeypatch.setattr(TC, "get_chat_id", boom)
    st = push_policy.credentials_status()
    assert st["ok"] is None and "keychain daemon busy" in (st["error"] or "")


def test_authority_never_returns_the_secret(monkeypatch):
    import spa_core.alerts.telegram_client as TC
    from spa_core.telegram import push_policy

    secret = "1234567:AA-super-secret-bot-token"
    monkeypatch.setattr(TC, "get_bot_token", lambda: secret)
    monkeypatch.setattr(TC, "get_chat_id", lambda: "chat")
    assert secret not in repr(push_policy.credentials_status())


def test_watch_does_not_import_the_transport():
    """Положительный контроль к самому инварианту: сторож НЕ тянется за транспортом.

    Если кто-то «оптимизирует» пробу обратно на прямой импорт `telegram_client`, красным
    станет и общий страж одной двери, и этот тест — рядом с кодом, а не в чужом файле.
    """
    from pathlib import Path as _P

    src = _P(LCW.__file__).read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#") or "`" in line:
            continue                      # проза докстринга — не проводка
        assert "telegram_client" not in line, f"{LCW.__file__}:{i}: {line.strip()}"
