"""spa_core/tests/test_pilot_request.py — OWNER-approved pilot CONTACT capture (2026-07-12).

Covers the /api/pilot/request + /api/pilot/requests/count endpoints in interest.py:
a warm visitor opts in with their email to request a conversation; the full request goes to the
owner (Telegram + data/pilot_requests.jsonl) but /admin only ever sees a COUNT (no PII on the
unauthenticated admin surface).

PURE / no network / deterministic. Telegram notify is monkeypatched off; the JSONL sink is a tmp file.
Proves: email validated fail-closed; a valid request is persisted + owner-notified; count endpoint
NEVER returns email/message; a Telegram failure never breaks the request.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.api.routers import interest as I

#: НАСТОЯЩИЕ функции, снятые ДО того, как autouse-фикстура подменит их заглушками.
#: Тесты ниже проверяют именно их, а не заглушку — иначе проверка была бы украшением.
_REAL_NOTIFY = I._notify_owner_telegram
_REAL_NOTIFY_CHANNEL = I._notify_channel_status


@pytest.fixture(autouse=True)
def _tmp_sink(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_REQ_LOG", tmp_path / "pilot_requests.jsonl")
    # default: notify succeeds (stubbed) — individual tests override as needed
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: True)
    # Поле `notify_channel` счётчика спрашивает НАСТОЯЩУЮ связку ключей через
    # `lead_channel_watch`. Здесь оно заглушено, чтобы прежние тесты не зависели от среды
    # (на Linux-раннере связки нет вовсе). Проверка не ослаблена: у самого поля есть свои
    # тесты ниже (`test_notify_channel_*`) и целый набор `test_lead_channel_watch.py`.
    monkeypatch.setattr(I, "_notify_channel_status",
                        lambda: {"configured": True, "status": "OK", "detail": "stub", "probes": {}})


def test_invalid_email_refused():
    r = I.pilot_request(I.PilotRequest(email="not-an-email"))
    assert r["ok"] is False
    assert not I._REQ_LOG.exists()  # nothing persisted on a bad email


def test_valid_request_persisted_and_notified():
    r = I.pilot_request(I.PilotRequest(email="fund@example.com", message="pilot?",
                                       tier="conservative", utm_source="site", utm_campaign="pilot"))
    assert r == {"ok": True, "notified": True}
    rows = [json.loads(l) for l in I._REQ_LOG.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["email"] == "fund@example.com"
    assert rows[0]["message"] == "pilot?"
    assert rows[0]["utm"] == "site:pilot"


def test_count_endpoint_never_leaks_pii():
    I.pilot_request(I.PilotRequest(email="a@b.com", message="secret note"))
    out = I.pilot_requests_count()
    assert out["total_requests"] == 1 and out["requests_today"] == 1
    blob = json.dumps(out)
    assert "@" not in blob and "secret note" not in blob  # no email / message ever surfaced


def test_telegram_failure_does_not_break_request(monkeypatch):
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: False)
    r = I.pilot_request(I.PilotRequest(email="ok@ok.com"))
    assert r["ok"] is True and r["notified"] is False
    assert I._REQ_LOG.exists()  # still persisted even if the ping failed


def test_early_access_returns_real_position(monkeypatch):
    # M7: source=early_access returns a REAL, incrementing position; normal requests get no position.
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: True)
    r1 = I.pilot_request(I.PilotRequest(email="a@b.co", source="early_access", tier="aggressive"))
    r2 = I.pilot_request(I.PilotRequest(email="c@d.co", source="early_access"))
    r3 = I.pilot_request(I.PilotRequest(email="e@f.co"))  # normal, no source
    assert r1["position"] == 1 and r2["position"] == 2
    assert "position" not in r3  # non-early-access requests never get a fabricated number
    rows = [json.loads(l) for l in I._REQ_LOG.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for r in rows if r.get("source") == "early_access") == 2


def test_email_edge_cases():
    for bad in ("", "a@b", "no-at.com", "x@y.", "@no-local.com"):
        assert I.pilot_request(I.PilotRequest(email=bad))["ok"] is False
    for good in ("a@b.co", "fund.manager@family-office.io"):
        assert I.pilot_request(I.PilotRequest(email=good))["ok"] is True


# ---------------------------------------------------------------------------
# Решение владельца 2026-08-22 (карточка `owner-decision-prover-odno-pole-...`, вариант 1):
# «доходят ли до тебя заявки». Два дефекта, найденные при исполнении этого решения:
#   1. `_notify_owner_telegram` возвращал True БЕЗУСЛОВНО — API рапортовал сайту
#      «уведомил» даже когда `push_policy.push_critical` вернул False (пустая связка
#      ключей, сеть, дневной потолок). Зелёный ответ на СВОЙ вопрос («я позвал
#      отправителя») читался как ответ на нужный («владелец узнал»).
#   2. Поля `notify_channel`, которое карточка велела прочитать владельцу, в коде
#      не существовало НИ РАЗУ — ответ «configured: true» доказательством не был.
# Тесты ниже — положительные контроли обоих: на неисправленном коде краснеют.
# ---------------------------------------------------------------------------
class _FakePush:
    """Подмена единственного отправителя Tier-1. Настоящий `push_critical` в тестах звать
    нельзя: он ходит в сеть, и страж `telegram_guard` уронит тест НАЗЫВАЯ его."""

    def __init__(self, sent: bool):
        self.sent = sent
        self.pushed: list = []
        self.digested: list = []

    def push_critical(self, key, severity, title, body="", **kw):
        self.pushed.append((key, title))
        return self.sent

    def enqueue_digest(self, key, title, body="", **kw):
        self.digested.append((key, title))


def _material_lead():
    # B2B-домен ⇒ материальная заявка ⇒ мгновенный пинг (см. `_is_material_lead`)
    return "manager@family-office.io"


def test_notified_is_false_when_the_push_did_not_go(monkeypatch):
    fake = _FakePush(sent=False)
    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", fake.push_critical)
    monkeypatch.setattr(I, "_notify_owner_telegram", _REAL_NOTIFY)   # снимаем заглушку фикстуры
    r = I.pilot_request(I.PilotRequest(email=_material_lead(), message="pilot?"))
    assert r["ok"] is True
    assert r["notified"] is False          # ← на неисправленном коде было True
    assert fake.pushed and fake.pushed[0][0] == "pilot_request"
    assert I._REQ_LOG.exists()             # заявка всё равно сохранена: её терять нельзя


def test_notified_is_true_when_the_push_went(monkeypatch):
    fake = _FakePush(sent=True)
    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", fake.push_critical)
    monkeypatch.setattr(I, "_notify_owner_telegram", _REAL_NOTIFY)
    r = I.pilot_request(I.PilotRequest(email=_material_lead()))
    assert r["notified"] is True and fake.pushed


def test_retail_lead_goes_to_the_digest_and_never_pushes(monkeypatch):
    fake = _FakePush(sent=True)
    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", fake.push_critical)
    monkeypatch.setattr("spa_core.telegram.push_policy.enqueue_digest", fake.enqueue_digest)
    monkeypatch.setattr(I, "_notify_owner_telegram", _REAL_NOTIFY)
    r = I.pilot_request(I.PilotRequest(email="someone@gmail.com"))
    assert r["notified"] is True
    assert not fake.pushed and fake.digested   # розничная заявка владельца не будит


def test_notify_channel_field_exists_and_mirrors_the_watch(monkeypatch):
    """Поле, которое велели прочитать владельцу, обязано существовать И меряться."""
    from spa_core.monitoring import lead_channel_watch as LCW

    monkeypatch.setattr(I, "_notify_channel_status", _REAL_NOTIFY_CHANNEL)
    monkeypatch.setattr(LCW, "check",
                        lambda **k: LCW.Verdict(LCW.OK, [LCW.Probe("credentials", LCW.OK, "ок")], "t"))
    out = I.pilot_requests_count()
    assert out["notify_channel"]["configured"] is True
    assert out["notify_channel"]["status"] == "OK"

    monkeypatch.setattr(LCW, "check",
                        lambda **k: LCW.Verdict(LCW.BROKEN,
                                                [LCW.Probe("credentials", LCW.BROKEN, "ключей нет")], "t"))
    out = I.pilot_requests_count()
    assert out["notify_channel"]["configured"] is False
    assert out["notify_channel"]["probes"]["credentials"] == "BROKEN"


def test_notify_channel_never_leaks_the_token(monkeypatch):
    from spa_core.monitoring import lead_channel_watch as LCW

    secret = "1234567:AA-super-secret-bot-token"
    monkeypatch.setattr(I, "_notify_channel_status", _REAL_NOTIFY_CHANNEL)
    monkeypatch.setattr(LCW, "check", lambda **k: LCW.check(
        read_token=lambda: secret, read_chat_id=lambda: "chat", keychain_available=lambda: True,
        whitelist=frozenset({"pilot_request"}), oneshot=frozenset({"pilot_request"}),
        source="@router.post('/api/pilot/request')\ndef h(r):\n    return _notify_owner_telegram(r)\n"))
    blob = json.dumps(I.pilot_requests_count(), ensure_ascii=False)
    assert secret not in blob and "AA-super-secret" not in blob


def test_notify_channel_survives_a_broken_probe(monkeypatch):
    """Админ-счётчик не имеет права падать из-за пробы канала — но и врать «настроено» тоже."""
    from spa_core.monitoring import lead_channel_watch as LCW

    def boom(**k):
        raise RuntimeError("проба сорвалась")

    monkeypatch.setattr(I, "_notify_channel_status", _REAL_NOTIFY_CHANNEL)
    monkeypatch.setattr(LCW, "check", boom)
    out = I.pilot_requests_count()
    assert out["notify_channel"]["configured"] is False
    assert out["notify_channel"]["status"] == "UNCHECKED"
