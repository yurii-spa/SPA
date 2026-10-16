"""ARB 16.10 — provenance of cockpit records: channel · ESTABLISHED author · authority, three separate facts.

Defect replayed: on 16.10 an AGENT submitted a demo record through the loopback listener (``actor: local``)
and the card still opened with «Это заметка владельца из пульта…». Client-supplied fields and the mere fact
of arrival do not establish authorship; only a server-verified Cloudflare Access identity names the owner.

Positive controls (each fails on origin 3584de55f): the owner line appears ONLY for a verified Access
identity; a body ``actor``/``author`` of «owner» changes nothing; the agent channel is labelled as agent;
«Мои записи» shows channel/author/authority and never repeats the legacy owner claim it cannot back.
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import access_jwt, mission_control as mc, mission_intake as mi, mission_server
from spa_core.studio_os import owner_view as ov
from spa_core.tests.test_mission_server import AUD, CERTS, OWNER_EMAIL, TEAM, base_claims, make_jwt

NOW = datetime(2026, 10, 16, 7, 30, tzinfo=timezone.utc)   # FROZEN-DATE-OK: injected-clock — passed as now=
PUBLIC_HOST = "mc.example.test"
OWNER_LINE = "заметка владельца"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _body(text, kind="task", **extra) -> bytes:
    return json.dumps({"text": text, "kind": kind, **extra}).encode()


def _cards(d: Path):
    return sorted(d.glob("inbox-*.md"))


def _fm(text: str, key: str):
    m = re.search(rf"^{key}: \"?([^\"\n]*)\"?$", text.split("\n---", 1)[0], re.M)
    return m.group(1) if m else None


class _Pair:
    """Real local + public listeners (public behind a verified-JWT gate, certs stubbed — no network)."""

    def __init__(self, tmp: Path, monkeypatch):
        self.root = tmp / "serve"
        self.root.mkdir()
        self.tracker = tmp / "tracker"
        self.tracker.mkdir()
        monkeypatch.setattr(access_jwt, "fetch_certs", lambda *a, **k: CERTS)
        self.local_port, self.public_port = _free_port(), _free_port()
        env = {"MC_PUBLIC_HOST": PUBLIC_HOST, "MC_PUBLIC_PORT": str(self.public_port), "MC_ACCESS_AUD": AUD,
               "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        servers, _ = mission_server.serve(self.root, self.local_port, serve_forever=False, env=env,
                                          access_config_path=self.root / "absent.json", allow_env_config=True,
                                          intake_tracker_dir=self.tracker, intake_transcriber=lambda p: "x")
        self.servers = [servers["local"], servers["public"]]
        for h in self.servers:
            threading.Thread(target=h.serve_forever, daemon=True).start()

    def req(self, public: bool, method, path, body=b"", headers=None):
        port = self.public_port if public else self.local_port
        host = PUBLIC_HOST if public else f"127.0.0.1:{port}"
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            hd = {"Host": host}
            hd.update(headers or {})
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hd.items():
                conn.putheader(k, v)
            if method == "POST":
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            if body:
                conn.send(body)
            r = conn.getresponse()
            data = r.read()
            try:
                return r.status, json.loads(data.decode("utf-8"))
            except ValueError:
                return r.status, data
        finally:
            conn.close()

    def submit(self, public: bool, body: bytes, extra_headers=None, jwt=None):
        auth = {"Cf-Access-Jwt-Assertion": jwt} if public else {}
        st, doc = self.req(public, "GET", mi.CSRF_PATH, headers=auth)
        assert st == 200, (st, doc)
        origin = f"https://{PUBLIC_HOST}" if public else f"http://127.0.0.1:{self.local_port}"
        hd = {"Origin": origin, mi.TOKEN_HEADER: doc["token"], "Content-Type": "application/json", **auth}
        hd.update(extra_headers or {})
        return self.req(public, "POST", mi.SUBMIT_PATH, body, hd)

    def close(self):
        for h in self.servers:
            h.shutdown()
            h.server_close()


@pytest.fixture()
def pair(tmp_path, monkeypatch):
    p = _Pair(tmp_path, monkeypatch)
    yield p
    p.close()


# ── (1) public listener with a VERIFIED Access identity ⇒ author = owner ─────────────────────────────
def test_public_listener_with_verified_identity_names_the_owner(pair):
    st, doc = pair.submit(True, _body("Запись владельца с телефона"), jwt=make_jwt(base_claims(time.time())))
    assert st == 200, doc
    text = (pair.tracker / doc["card"]).read_text(encoding="utf-8")
    assert _fm(text, "channel") == mi.CHANNEL_PUBLIC
    assert _fm(text, "author") == mi.AUTHOR_OWNER
    assert _fm(text, "author_basis") == "access-jwt-verified"
    assert "автор: владелец" in text.lower() or "Автор: владелец" in text
    assert mi.AUTHORITY_NOTE in text and OWNER_LINE not in text
    assert "_Владелец пометил как: задача._" in text


# ── (2) public without a verifiable identity ⇒ author not established (and the server refuses) ───────
def test_public_without_verifiable_identity_never_names_the_owner(pair):
    # over the socket: no JWT / a token for another e-mail never reaches submit — nothing is written
    st, _ = pair.req(True, "POST", mi.SUBMIT_PATH, _body("x"), {"Origin": f"https://{PUBLIC_HOST}",
                                                                "Content-Type": "application/json"})
    assert st == 403
    assert _cards(pair.tracker) == []
    # the provenance rule itself: unverified / not-an-owner e-mail ⇒ «канал защищён Access, личность не проверена»
    for email in (None, "", "stranger@example.com"):
        p = mi.provenance_for("public", verified_email=email, owner_emails={OWNER_EMAIL.lower()})
        assert (p.channel, p.author, p.basis) == (mi.CHANNEL_PUBLIC, mi.AUTHOR_NOT_ESTABLISHED, "access-unverified")
        assert "личность не проверена подписью" in p.author_ru and "владел" not in p.author_ru


# ── (3) loopback ⇒ author not established, whatever the body claims ───────────────────────────────────
def test_loopback_body_actor_owner_does_not_establish_the_owner(pair):
    st, doc = pair.submit(False, _body("Запись через петлю", actor="owner", author="owner",
                                       channel="cockpit-public"))
    assert st == 200, doc
    text = (pair.tracker / doc["card"]).read_text(encoding="utf-8")
    assert _fm(text, "channel") == mi.CHANNEL_LOCAL
    assert _fm(text, "author") == mi.AUTHOR_NOT_ESTABLISHED
    assert "автор не установлен (локальный доступ к Mac)" in text
    assert OWNER_LINE not in text and "Владелец пометил" not in text
    assert _fm(text, "actor") is None
    assert mi.AUTHORITY_NOTE in text


# ── (4) explicit agent channel ⇒ author = agent; the marker is refused on the public listener ────────
def test_agent_marker_on_loopback_labels_the_record_as_agent(pair):
    st, doc = pair.submit(False, _body("Демо сквозного пути"), extra_headers={mi.AGENT_HEADER: "arb-demo-1"})
    assert st == 200, doc
    text = (pair.tracker / doc["card"]).read_text(encoding="utf-8")
    assert (_fm(text, "channel"), _fm(text, "author"), _fm(text, "author_identity")) == \
        (mi.CHANNEL_AGENT, mi.AUTHOR_AGENT, "arb-demo-1")
    assert "агент «arb-demo-1»" in text and OWNER_LINE not in text and "Владелец пометил" not in text


def test_agent_marker_on_public_listener_is_refused_and_writes_nothing(pair):
    st, doc = pair.submit(True, _body("x"), extra_headers={mi.AGENT_HEADER: "arb-demo-1"},
                          jwt=make_jwt(base_claims(time.time())))
    assert st == 400 and doc["code"] == "AGENT_MARKER_PUBLIC"
    assert _cards(pair.tracker) == []


def test_bad_agent_marker_is_refused(pair):
    st, doc = pair.submit(False, _body("x"), extra_headers={mi.AGENT_HEADER: "../owner"})
    assert st == 400 and doc["code"] == "BAD_AGENT_MARKER"
    assert _cards(pair.tracker) == []


def test_submit_without_provenance_is_fail_closed(tmp_path):
    res = mi.submit(_body("Без происхождения"), actor="owner@example.com", tracker_dir=tmp_path, now=NOW)
    text = (tmp_path / res["card"]).read_text(encoding="utf-8")
    assert (_fm(text, "channel"), _fm(text, "author")) == (mi.CHANNEL_UNKNOWN, mi.AUTHOR_NOT_ESTABLISHED)
    assert "owner@example.com" not in text and OWNER_LINE not in text


# ── (5) no card claims «заметка владельца» unless established ────────────────────────────────────────
def test_no_card_text_claims_owner_authorship_unless_established(tmp_path):
    for i, prov in enumerate((mi.provenance_for("local"), mi.provenance_for("local", agent_marker="bot-1"),
                              mi.provenance_for("public", verified_email=None, owner_emails={"o@x.y"}),
                              mi.provenance_for(None))):
        mi.submit(_body(f"Запись {i}", sid=f"ffff0000-{i:04d}"), provenance=prov, tracker_dir=tmp_path, now=NOW)
    for p in _cards(tmp_path):
        text = p.read_text(encoding="utf-8")
        assert OWNER_LINE not in text, p.name
        assert "Владелец пометил" not in text and "Автор: владелец" not in text, p.name
        assert not re.search(r"^author: owner$", text, re.M), p.name


# ── (6) «Мои записи»: channel / author / authority per row ────────────────────────────────────────────
def _write(d: Path, name: str, fm: dict, body: str):
    head = "\n".join(f"{k}: {v}" for k, v in {"title": name, "status": "new", "source": "cockpit", **fm}.items())
    (d / name).write_text(f"---\n{head}\n---\n\n{body}\n", encoding="utf-8")


def test_my_records_shows_channel_author_and_authority(tmp_path):
    owner = mi.provenance_for("public", verified_email="o@x.y", owner_emails={"o@x.y"})
    mi.submit(_body("Владельца", sid="aaaa0000-0001"), provenance=owner, tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Петля", sid="aaaa0000-0002"), provenance=mi.provenance_for("local"), tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Агент", sid="aaaa0000-0003"), provenance=mi.provenance_for("local", agent_marker="bot-1"),
              tracker_dir=tmp_path, now=NOW)
    # legacy card (before 16.10): `actor: local` + the old owner line in its body
    _write(tmp_path, "inbox-legacy.md", {"actor": "local", "submitted_at": "2026-10-15T10:00:00Z"},
           mi.LEGACY_AUTHORITY_NOTE + "\n\n## Задание (из пульта)\n\nСтарая запись")
    # the 16.10 demo card after the append-only clarification
    _write(tmp_path, "inbox-demo.md", {"actor": "local", "submitted_at": "2026-10-16T15:39:32Z"},
           mi.LEGACY_AUTHORITY_NOTE + "\n\n## Уточнение 16.10\n\n"
           "provenance_correction: channel=cockpit-local author=agent identity=arb-demo")
    rec = mc.cockpit_records(mc._cards(tmp_path), NOW, source="test")
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    rows = {r["title"]: r for r in view["rows"]}
    assert "ваши" not in view["sub"]
    for r in rows.values():
        assert r["authority_ru"] == ov.RECORD_AUTHORITY_RU and "ADR-285" in r["authority_ru"]
        assert r["author_ru"].startswith("автор: владелец") == (r is rows["Владельца"]), r["title"]
        assert r["by_owner"] == (r is rows["Владельца"])
    assert "Cloudflare Access" in rows["Владельца"]["channel_ru"]
    assert rows["Петля"]["author_ru"] == "автор не установлен (локальный доступ к Mac)"
    assert "агент «bot-1»" in rows["Агент"]["author_ru"] and rows["Агент"]["author_established"]
    legacy = rows["inbox-legacy.md"]
    assert legacy["channel_ru"] == ov.RECORD_CHANNEL_RU["cockpit-local"]
    assert "не записан" in legacy["author_ru"] and legacy["provenance_note"]
    demo = rows["inbox-demo.md"]
    assert "агент «arb-demo»" in demo["author_ru"] and "Уточнено" in demo["provenance"]
    assert demo["provenance_note"]   # the legacy owner line in its body is named as unconfirmed


def test_mission_control_vocabulary_matches_the_writer():
    assert set(mc.COCKPIT_CHANNELS) == set(mi.CHANNEL_RU)
    assert set(mc.COCKPIT_AUTHORS) == {mi.AUTHOR_OWNER, mi.AUTHOR_AGENT, mi.AUTHOR_NOT_ESTABLISHED}
    assert set(ov.RECORD_CHANNEL_RU) == set(mi.CHANNEL_RU)
