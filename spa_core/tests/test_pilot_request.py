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
    # default: notify succeeds (stubbed) — individual tests override as needed.
    # The notifier now returns (state, reason), not a bool: "no exception" was never delivery.
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("sent", ""))
    # channel probe is deterministic in tests (no Keychain/subprocess, no network)
    monkeypatch.setattr(I, "_telegram_configured", lambda: True)


def test_invalid_email_refused():
    r = I.pilot_request(I.PilotRequest(email="not-an-email"))
    assert r["ok"] is False
    assert not I._REQ_LOG.exists()  # nothing persisted on a bad email


def test_valid_request_persisted_and_notified():
    r = I.pilot_request(I.PilotRequest(email="fund@example.com", message="pilot?",
                                       tier="conservative", utm_source="site", utm_campaign="pilot"))
    # `stored` was ADDED to the contract (waitlist fail-OPEN card): `ok` alone could not tell a
    # persisted lead from a swallowed write, so the happy path now also states the write happened.
    assert r == {"ok": True, "stored": "ok", "notified": "sent"}
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
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("error", "stubbed transport failure"))
    r = I.pilot_request(I.PilotRequest(email="ok@ok.com"))
    assert r["ok"] is True and r["notified"] == "error"
    assert I._REQ_LOG.exists()  # still persisted even if the ping failed


def test_early_access_returns_real_position(monkeypatch):
    # M7: source=early_access returns a REAL, incrementing position; normal requests get no position.
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("sent", ""))
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
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("error", "stubbed transport failure"))
    r = I.pilot_request(I.PilotRequest(email="lost@example.com"))
    assert r["ok"] is False
    assert r["stored"] == "error" and r["notified"] == "error"
    assert r["error"]


def test_failed_write_is_named_even_when_the_owner_was_pinged(monkeypatch, tmp_path):
    # Ping delivered ⇒ the lead is not lost (ok stays true), but the failed WRITE is still stated:
    # `ok` must stop meaning "everything is fine" by default.
    _break_sink(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("sent", ""))
    r = I.pilot_request(I.PilotRequest(email="ok@example.com"))
    assert r["ok"] is True
    assert r["stored"] == "error"


def test_no_position_is_handed_out_for_an_unwritten_row(monkeypatch, tmp_path):
    # M7 position = count+1 read from the sink. If the row was not appended, the SAME number goes
    # to the next signup — a fabricated queue place. It must be withheld, not guessed.
    _break_sink(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("sent", ""))
    r = I.pilot_request(I.PilotRequest(email="early@example.com", source="early_access"))
    assert "position" not in r
    assert r["stored"] == "error"


def test_working_sink_still_reports_stored_ok(monkeypatch):
    # Control in the other direction — the honest signal is not hardwired to "error".
    monkeypatch.setattr(I, "_notify_owner_telegram", lambda *a, **k: ("error", "stubbed transport failure"))
    r = I.pilot_request(I.PilotRequest(email="fine@example.com"))
    assert r["ok"] is True and r["stored"] == "ok" and r["notified"] == "error"
    assert I._REQ_LOG.exists()


def test_email_edge_cases():
    for bad in ("", "a@b", "no-at.com", "x@y.", "@no-local.com"):
        assert I.pilot_request(I.PilotRequest(email=bad))["ok"] is False
    for good in ("a@b.co", "fund.manager@family-office.io"):
        assert I.pilot_request(I.PilotRequest(email=good))["ok"] is True


# ── POSITIVE CONTROL №2: the owner-NOTIFICATION leg of the same fail-OPEN class ────────────────
# Card `agent-checkup-waitlist-fail-open-ok-true`, measured here 2026-08-19: `_notify_owner_telegram`
# returned True whenever no exception escaped, but NOTHING it calls raises — `push_critical` returns
# False when the policy gate demotes the event or the transport fails, and the digest enqueue
# swallowed its own write failure and returned None. So an undelivered lead was reported as
# `notified: true` → `ok: true`, i.e. the DeFi Checkup waitlist defect, one leg over.
# Every test below is RED on the pre-fix notifier (which could only answer True/False).
#
# Three outcomes must stay DISTINGUISHABLE: delivered (sent/queued) · not delivered, with a reason
# (skipped/error) · not measured (unknown, which never counts as delivery — fail-CLOSED).
import types as _types  # noqa: E402

#: The REAL notifier, captured at import time — the autouse fixture stubs the module attribute,
#: and these tests exercise the notifier itself.
_REAL_NOTIFY = I._notify_owner_telegram


def _use_real_notifier(monkeypatch):
    monkeypatch.setattr(I, "_notify_owner_telegram", _REAL_NOTIFY)


def _stub_push_policy(monkeypatch, *, push=False, queue=False):
    """Install a fake push_policy so no Telegram/network/Keychain is ever touched."""
    fake = _types.SimpleNamespace(
        push_critical=lambda *a, **k: push,
        enqueue_digest=lambda *a, **k: queue,
    )
    import sys
    import spa_core.telegram as _tg
    monkeypatch.setitem(sys.modules, "spa_core.telegram.push_policy", fake)
    # `from spa_core.telegram import push_policy` binds the PACKAGE ATTRIBUTE, so patching
    # sys.modules alone would leave the real (network/Keychain-touching) module in play.
    monkeypatch.setattr(_tg, "push_policy", fake)
    _use_real_notifier(monkeypatch)
    monkeypatch.setattr(I, "_telegram_configured", lambda: True)
    return fake


def test_unconfigured_channel_is_named_skipped_not_notified(monkeypatch):
    # The local twin of the missing RESEND_API_KEY: nothing was ATTEMPTED, and the answer says so.
    _stub_push_policy(monkeypatch, push=False, queue=False)   # nothing may reach a transport
    monkeypatch.setattr(I, "_telegram_configured", lambda: False)
    r = I.pilot_request(I.PilotRequest(email="lead@corp.example"))
    assert r["notified"] == "skipped"
    assert r["notify_reason"]                 # the reason is stated, not left to guesswork
    assert r["ok"] is True and r["stored"] == "ok"   # the lead itself is safe on the sink


def test_unconfigured_channel_plus_broken_sink_is_not_ok(monkeypatch, tmp_path):
    # Nothing stored, nobody notified ⇒ the lead is GONE. Pre-fix this answered ok:true.
    _break_sink(monkeypatch, tmp_path)
    _stub_push_policy(monkeypatch, push=False, queue=False)
    monkeypatch.setattr(I, "_telegram_configured", lambda: False)
    r = I.pilot_request(I.PilotRequest(email="lost@corp.example"))
    assert r["ok"] is False and r["stored"] == "error" and r["notified"] == "skipped"
    assert r["error"]


def test_refused_push_that_reaches_the_digest_is_queued_not_sent(monkeypatch):
    # Gate demoted / transport failed, but the digest write is CONFIRMED ⇒ delivered-by-digest.
    _stub_push_policy(monkeypatch, push=False, queue=True)
    r = I.pilot_request(I.PilotRequest(email="lead@corp.example", tier="aggressive"))
    assert r["notified"] == "queued" and r["notify_reason"]


def test_refused_push_and_failed_queue_is_error_not_notified(monkeypatch):
    # Both notification paths failed. Pre-fix: notified=True (no exception was raised).
    _stub_push_policy(monkeypatch, push=False, queue=False)
    r = I.pilot_request(I.PilotRequest(email="lead@corp.example", tier="aggressive"))
    assert r["notified"] == "error" and r["notify_reason"]
    assert r["ok"] is True and r["stored"] == "ok"   # still stored — best-effort notify never kills the lead


def test_failed_digest_write_for_a_retail_lead_is_error(monkeypatch):
    # Non-material lead → digest only. A failed queue write must not read as a notified owner.
    _stub_push_policy(monkeypatch, push=True, queue=False)
    r = I.pilot_request(I.PilotRequest(email="someone@gmail.com"))   # free mail ⇒ non-material
    assert r["notified"] == "error"


def test_delivered_push_is_sent(monkeypatch):
    # Control in the other direction: a real delivery is still reported as a delivery.
    _stub_push_policy(monkeypatch, push=True, queue=False)
    r = I.pilot_request(I.PilotRequest(email="lead@corp.example", tier="aggressive"))
    assert r["notified"] == "sent" and "notify_reason" not in r and r["ok"] is True


def test_unmeasurable_channel_never_counts_as_delivery(monkeypatch, tmp_path):
    # "Could not measure" is its own outcome and is NOT delivery (fail-CLOSED): with the sink
    # broken as well, the honest answer is ok:false.
    _break_sink(monkeypatch, tmp_path)
    _stub_push_policy(monkeypatch, push=False, queue=False)
    monkeypatch.setattr(I, "_telegram_configured", lambda: None)
    r = I.pilot_request(I.PilotRequest(email="lead@corp.example"))
    assert r["notified"] == "unknown" and r["ok"] is False


def test_channel_state_is_published_on_the_console(monkeypatch):
    # An unconfigured notification channel must be visible BEFORE a lead is lost.
    monkeypatch.setattr(I, "_telegram_configured", lambda: False)
    ch = I.pilot_requests_count()["notify_channel"]
    assert ch["configured"] is False and ch["measured"] is True and ch["flag_reason"]
    monkeypatch.setattr(I, "_telegram_configured", lambda: None)
    ch = I.pilot_requests_count()["notify_channel"]
    assert ch["configured"] is None and ch["measured"] is False and ch["flag_reason"]
    monkeypatch.setattr(I, "_telegram_configured", lambda: True)
    ch = I.pilot_requests_count()["notify_channel"]
    assert ch["configured"] is True and ch["measured"] is True and "flag_reason" not in ch


def test_digest_enqueue_reports_whether_the_item_reached_the_queue(tmp_path):
    # push_policy._enqueue_digest used to swallow its failure AND return None, which is what let
    # the caller above report a notified owner. It now answers the question it was asked.
    from spa_core.telegram import push_policy as PP
    assert PP._enqueue_digest(tmp_path, {"ts": "x", "event_key": "pilot_request"}) is True
    broken = tmp_path / "nope"
    broken.write_text("i am a file, not a directory", encoding="utf-8")
    assert PP._enqueue_digest(broken, {"ts": "x", "event_key": "pilot_request"}) is False
