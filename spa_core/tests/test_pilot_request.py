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
    # `stored` was ADDED to the contract (waitlist fail-OPEN card): `ok` alone could not tell a
    # persisted lead from a swallowed write, so the happy path now also states the write happened.
    assert r == {"ok": True, "stored": "ok", "notified": True}
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


# ── POSITIVE CONTROL: the waitlist fail-OPEN itself ────────────────────────────────────────────
# Card `agent-checkup-waitlist-fail-open-ok-true`: the handler answered {"ok": true, "position": N}
# whether or not the join was recorded, so a broken sink looked identical to a working one for three
# weeks. Every test below RED on the unfixed handler (it returned ok:True unconditionally).
#
# The sink is broken WITHOUT chmod on purpose: this suite also runs as root, where permission bits
# are ignored, and a chmod-based test would pass for the wrong reason. Pointing the sink at a
# DIRECTORY makes the append fail for everyone (IsADirectoryError).
def _break_sink(monkeypatch, tmp_path):
    broken = tmp_path / "sink_is_a_directory"
    broken.mkdir()
    monkeypatch.setattr(I, "_REQ_LOG", broken)
    return broken


def test_lost_lead_is_not_reported_ok(monkeypatch, tmp_path):
    # Sink unwritable AND the owner ping fails ⇒ the lead is GONE. Saying ok:true here is the defect.
    _break_sink(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: False)
    r = I.pilot_request(I.PilotRequest(email="lost@example.com"))
    assert r["ok"] is False
    assert r["stored"] == "error" and r["notified"] is False
    assert r["error"]


def test_failed_write_is_named_even_when_the_owner_was_pinged(monkeypatch, tmp_path):
    # Ping delivered ⇒ the lead is not lost (ok stays true), but the failed WRITE is still stated:
    # `ok` must stop meaning "everything is fine" by default.
    _break_sink(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: True)
    r = I.pilot_request(I.PilotRequest(email="ok@example.com"))
    assert r["ok"] is True
    assert r["stored"] == "error"


def test_no_position_is_handed_out_for_an_unwritten_row(monkeypatch, tmp_path):
    # M7 position = count+1 read from the sink. If the row was not appended, the SAME number goes
    # to the next signup — a fabricated queue place. It must be withheld, not guessed.
    _break_sink(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: True)
    r = I.pilot_request(I.PilotRequest(email="early@example.com", source="early_access"))
    assert "position" not in r
    assert r["stored"] == "error"


def test_working_sink_still_reports_stored_ok(monkeypatch):
    # Control in the other direction — the honest signal is not hardwired to "error".
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: False)
    r = I.pilot_request(I.PilotRequest(email="fine@example.com"))
    assert r["ok"] is True and r["stored"] == "ok" and r["notified"] is False
    assert I._REQ_LOG.exists()


def test_email_edge_cases():
    for bad in ("", "a@b", "no-at.com", "x@y.", "@no-local.com"):
        assert I.pilot_request(I.PilotRequest(email=bad))["ok"] is False
    for good in ("a@b.co", "fund.manager@family-office.io"):
        assert I.pilot_request(I.PilotRequest(email=good))["ok"] is True
