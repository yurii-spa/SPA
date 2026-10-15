"""ADR-760 — the cockpit's ONE write action: a new inbox record (text or voice), and nothing else.

Real sockets (mission_server on measured-free loopback ports), a temporary tracker dir, a stub
transcriber (no whisper run in CI). Each refusal is a positive control: the request that SHOULD be
refused is sent and the tracker dir is checked to be untouched.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
from pathlib import Path

import pytest

from spa_core.studio_os import mission_intake, mission_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Srv:
    def __init__(self, root: Path, tracker: Path, transcriber=None):
        self.port = _free_port()
        servers, _ = mission_server.serve(root, self.port, serve_forever=False, env={},
                                          access_config_path=root / "absent.json",
                                          intake_tracker_dir=tracker, intake_transcriber=transcriber)
        self.httpd = servers["local"]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.port}"

    def req(self, method, path, body=b"", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            hd = {"Host": f"127.0.0.1:{self.port}"}
            hd.update(headers or {})
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hd.items():
                conn.putheader(k, v)
            if method == "POST":
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            if method == "POST" and body:
                conn.send(body)
            r = conn.getresponse()
            data = r.read()
            try:
                return r.status, json.loads(data.decode("utf-8"))
            except ValueError:
                return r.status, data
        finally:
            conn.close()

    def token(self):
        st, doc = self.req("GET", mission_intake.CSRF_PATH)
        assert st == 200
        return doc["token"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def srv(tmp_path):
    root = tmp_path / "serve"
    root.mkdir()
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    s = _Srv(root, tracker, transcriber=lambda p: "Проверить голосовой ввод из пульта")
    s.tracker = tracker
    yield s
    s.close()


def _json_headers(s, token, origin=None):
    return {"Origin": origin or s.origin, mission_intake.TOKEN_HEADER: token, "Content-Type": "application/json"}


def _files(d: Path):
    return sorted(p.name for p in d.rglob("*") if p.is_file())


def test_submit_creates_one_new_inbox_card(srv):
    body = json.dumps({"text": "Добавить сводку по пакетам на главную", "kind": "task"}).encode()
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, _json_headers(srv, srv.token()))
    assert st == 200 and doc["ok"] is True, doc
    files = _files(srv.tracker)
    assert len(files) == 1 and files[0].startswith("inbox-")
    text = (srv.tracker / files[0]).read_text(encoding="utf-8")
    assert "trackerStatus: new" in text or "status: new" in text
    assert "intake_kind: task" in text
    assert "Добавить сводку по пакетам на главную" in text
    assert "audit" not in doc   # the audit line goes to the server log, not to the page


@pytest.mark.parametrize("hdr", [{}, {mission_intake.TOKEN_HEADER: "0" * 64}])
def test_missing_or_wrong_token_is_403_and_writes_nothing(srv, hdr):
    body = json.dumps({"text": "x", "kind": "idea"}).encode()
    headers = {"Origin": srv.origin, "Content-Type": "application/json", **hdr}
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, headers)
    assert st == 403 and doc["code"] == "CSRF"
    assert _files(srv.tracker) == []


@pytest.mark.parametrize("origin", ["https://evil.example", None])
def test_cross_origin_or_missing_origin_is_403(srv, origin):
    body = json.dumps({"text": "x", "kind": "idea"}).encode()
    headers = {mission_intake.TOKEN_HEADER: srv.token(), "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, headers)
    assert st == 403 and doc["code"] == "ORIGIN"
    assert _files(srv.tracker) == []


def test_oversize_json_is_413(srv):
    body = json.dumps({"text": "я" * 40000, "kind": "note"}).encode()
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, _json_headers(srv, srv.token()))
    assert st == 413
    assert _files(srv.tracker) == []


def test_bad_kind_and_empty_text_are_refused(srv):
    tok = srv.token()
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, json.dumps({"text": "x", "kind": "execute"}).encode(),
                      _json_headers(srv, tok))
    assert st == 400 and doc["code"] == "NO_KIND"
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, json.dumps({"text": "  ", "kind": "idea"}).encode(),
                      _json_headers(srv, tok))
    assert st == 400 and doc["code"] == "NO_TEXT"
    assert _files(srv.tracker) == []


def test_rate_limit_on_submit(srv):
    tok = srv.token()
    codes = []
    for i in range(11):
        body = json.dumps({"text": f"запись номер {i} про разное", "kind": "idea"}).encode()
        codes.append(srv.req("POST", mission_intake.SUBMIT_PATH, body, _json_headers(srv, tok))[0])
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_transcribe_returns_text_only_and_writes_nothing(srv):
    st, doc = srv.req("POST", mission_intake.TRANSCRIBE_PATH, b"\x00\x01fake-audio",
                      {"Origin": srv.origin, mission_intake.TOKEN_HEADER: srv.token(), "Content-Type": "audio/mp4"})
    assert st == 200 and doc["text"] == "Проверить голосовой ввод из пульта"
    assert _files(srv.tracker) == []


def test_transcribe_with_whisper_absent_is_a_named_refusal(tmp_path, monkeypatch):
    root = tmp_path / "serve"
    root.mkdir()
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    s = _Srv(root, tracker, transcriber=None)
    monkeypatch.setattr(mission_intake, "whisper_status", lambda: {"whisper_present": False})
    try:
        st, doc = s.req("POST", mission_intake.TRANSCRIBE_PATH, b"abc",
                        {"Origin": s.origin, mission_intake.TOKEN_HEADER: s.token(), "Content-Type": "audio/mp4"})
        assert st == 503 and doc["code"] == "WHISPER_UNAVAILABLE"
        assert "whisper" in doc["message"]
    finally:
        s.close()


def test_wrong_audio_type_is_415(srv):
    st, doc = srv.req("POST", mission_intake.TRANSCRIBE_PATH, b"abc",
                      {"Origin": srv.origin, mission_intake.TOKEN_HEADER: srv.token(), "Content-Type": "text/plain"})
    assert st == 415


def test_post_to_any_other_path_is_405(srv):
    for path in ("/", "/mission.json", "/api/intake/other", "/api/intake/submit/x"):
        st, _doc = srv.req("POST", path, b"", {"Origin": srv.origin, "Content-Type": "application/json"})
        assert st == 405, path
        # with a body the pre-existing smuggling guard answers first (400) — still a refusal
        st, _doc = srv.req("POST", path, b"{}", {"Origin": srv.origin, "Content-Type": "application/json"})
        assert st in (400, 405), path
    assert _files(srv.tracker) == []
    for method in ("PUT", "DELETE", "PATCH"):
        st, _doc = srv.req(method, mission_intake.SUBMIT_PATH)
        assert st == 405, method


def test_proxy_header_on_the_local_listener_is_refused(srv):
    body = json.dumps({"text": "x", "kind": "idea"}).encode()
    headers = _json_headers(srv, srv.token())
    headers["Cf-Connecting-Ip"] = "1.2.3.4"
    st, _doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, headers)
    assert st == 403
    assert _files(srv.tracker) == []


def test_submit_never_writes_outside_the_tracker_dir(srv, tmp_path):
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    body = json.dumps({"text": "Голосовая заметка", "kind": "note", "transcript": "Голосовая заметка"}).encode()
    st, doc = srv.req("POST", mission_intake.SUBMIT_PATH, body, _json_headers(srv, srv.token()))
    assert st == 200
    new = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    assert len(new) == 1 and next(iter(new)).parent == srv.tracker
    assert "Расшифровка голосового (whisper)" in next(iter(new)).read_text(encoding="utf-8")
