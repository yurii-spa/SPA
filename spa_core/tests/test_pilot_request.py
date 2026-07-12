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


@pytest.fixture(autouse=True)
def _tmp_sink(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_REQ_LOG", tmp_path / "pilot_requests.jsonl")
    # default: notify succeeds (stubbed) — individual tests override as needed
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: True)


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


def test_email_edge_cases():
    for bad in ("", "a@b", "no-at.com", "x@y.", "@no-local.com"):
        assert I.pilot_request(I.PilotRequest(email=bad))["ok"] is False
    for good in ("a@b.co", "fund.manager@family-office.io"):
        assert I.pilot_request(I.PilotRequest(email=good))["ok"] is True
