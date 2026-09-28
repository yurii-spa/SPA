#!/usr/bin/env python3
"""Owner Remote loopback server — static shell + local STT + canonical write seams.

LOOPBACK ONLY (127.0.0.1, deployment rule #8). stdlib only. No secrets. No money/execution path:
the only writes it performs are (a) a canonical INBOX task via the existing orchestrator_queue
(status `new`, never taking work / never dispatching) and (b) an owner IDEA note under docs/ideas/
(a home where agents do not act until #promote). Decision writing has no accepted canonical
interface → reported NOT_AVAILABLE. Every write requires an explicit `confirmed: true` in the body
(the Owner-confirm gate); RED commands never reach this server (the UI blocks them client-side and
this server exposes no capital/sign/live/risk route at all).

STT: shells out to the LOCAL `whisper` CLI (openai-whisper, cached model) — fully offline, no paid
API. If the faster local `~/.openclaw` whisper HTTP server is up on 127.0.0.1:8080 it is used first.

Run:  python3 studio_shell/voice_server.py [--port 8899]
Then: http://127.0.0.1:8899/graph.html
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Per-run CSRF/DNS-rebinding defences (this server performs canonical writes, so a browser on any
# origin the Owner happens to visit must NOT be able to drive it):
#   1. Host allow-list — a DNS-rebinding request arrives with the attacker's hostname in Host, never
#      a loopback literal → rejected.
#   2. Origin check — a cross-origin fetch carries the attacker Origin → rejected.
#   3. Content-Type application/json on write routes — blocks simple <form> CSRF.
#   4. Per-run token, injected into graph.html and required on write routes — a cross-origin page
#      cannot read the (opaque) HTML, so it cannot learn the token.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
RUN_TOKEN = secrets.token_urlsafe(24)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable or "python3"
WHISPER = "/opt/homebrew/bin/whisper"
WHISPER_MODEL = os.getenv("OWNER_REMOTE_WHISPER_MODEL", "large-v3-turbo")
OPENCLAW_STT = "http://127.0.0.1:8080/v1/audio/transcriptions"
MAX_AUDIO = 25 * 1024 * 1024
RED_RE = re.compile(  # defence in depth: this server refuses anything that smells like an action
    r"(перевед|переведи|перевес|перевод|перечисл|прода|купи|покуп|вывед|сними|снять|подпиш"
    r"|включи\s*(live|исполн|реальн|торг)"
    r"|(измени|поменяй|подними|снизь|поставь)\s*(риск|ставк|порог|лимит|политик|risk|rate|limit|policy)"
    r"|kill.?switch|стоп-?кран|transfer|\bsell\b|\bbuy\b|withdraw|deposit|\bsign\b"
    r"|enable\s*(live|execution|real|trading)|go\s*live|change\s*(the\s*)?(rate|risk|policy|limit)"
    r"|disable\s*(stop|kill)|custody|private\s*key)", re.I)

# Prefer the ONE shared classifier so web-server-side RED and Telegram RED are the same authority;
# fall back to the local regex only if the package can't be imported.
try:
    sys.path.insert(0, str(REPO))
    from spa_core.owner_remote.intent import is_red as _shared_is_red
except Exception:
    _shared_is_red = None


def _is_red(text: str) -> bool:
    return _shared_is_red(text) if _shared_is_red else bool(RED_RE.search(text or ""))


def _stt_engine():
    if Path(WHISPER).exists():
        return "LOCAL_WHISPER"
    return "NONE"


def _transcribe(audio: bytes, lang: str) -> dict:
    # 1) try the already-running local faster-whisper server (fast path)
    try:
        req = urllib.request.Request(OPENCLAW_STT, data=audio, method="POST",
                                     headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=3) as r:
            txt = json.loads(r.read().decode()).get("text", "")
            if txt:
                return {"text": txt.strip(), "engine": "LOCAL_WHISPER", "via": "openclaw:8080"}
    except Exception:
        pass
    # 2) shell out to the local whisper CLI (self-contained, offline)
    if not Path(WHISPER).exists():
        return {"error": "LOCAL_WHISPER unavailable", "engine": "NONE"}
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.audio"
        src.write_bytes(audio)
        cmd = [WHISPER, str(src), "--model", WHISPER_MODEL, "--task", "transcribe",
               "--output_format", "txt", "--output_dir", td, "--fp16", "False"]
        if lang in ("ru", "en"):
            cmd += ["--language", lang]
        try:
            subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=120, check=True)
        except subprocess.CalledProcessError as e:
            return {"error": "whisper failed: " + (e.stderr or "")[-300:], "engine": "LOCAL_WHISPER"}
        except subprocess.TimeoutExpired:
            return {"error": "whisper timeout", "engine": "LOCAL_WHISPER"}
        out = Path(td) / "in.txt"
        text = out.read_text(encoding="utf-8").strip() if out.exists() else ""
        return {"text": text, "engine": "LOCAL_WHISPER", "via": f"cli:{WHISPER_MODEL}"}


def _create_task(title: str, body: str) -> dict:
    tracker = REPO / "nimbalyst-local" / "tracker"
    cmd = [PY, str(REPO / "scripts" / "orchestrator_queue.py"), "create",
           "--type", "inbox", "--title", title, "--body", body,
           "--status", "new", "--source", "voice"]
    if tracker.exists():
        cmd += ["--tracker-dir", str(tracker)]
    try:
        r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "intake timeout"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "intake failed").strip()[-400:]}
    path = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
    return {"ok": bool(path), "id": path, "canonical": "orchestrator_queue.create/inbox"}


_SLUG_RE = re.compile(r"[^a-z0-9а-яё]+", re.I)


def _write_idea(text: str, ts: str) -> dict:
    ideas = REPO / "docs" / "ideas"
    if not ideas.exists():
        return {"ok": False, "error": "docs/ideas not present"}
    date = ts[:10]
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")[:48] or "voice-idea"
    path = ideas / f"{date}-{slug}.md"
    n = 2
    while path.exists():
        path = ideas / f"{date}-{slug}-{n}.md"; n += 1
    body = (f"# {text.strip()[:80]}\n\n"
            f"> Захвачено голосом через Owner Remote {ts}. Идея ≠ инструкция — агенты не действуют "
            f"до `#promote` (см. docs/ideas/README.md).\n\n{text.strip()}\n")
    path.write_text(body, encoding="utf-8")
    return {"ok": True, "id": str(path.relative_to(REPO)), "canonical": "docs/ideas"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def log_message(self, format, *args):  # noqa: A002 — match base signature
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, limit):
        n = int(self.headers.get("Content-Length", 0))
        if n > limit:
            return None
        return self.rfile.read(n)

    def _origin_guard(self):
        """Reject anything that isn't a same-loopback request (DNS-rebinding + CSRF defence)."""
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]")
        if host not in LOOPBACK_HOSTS:
            self._json(403, {"error": "bad host (loopback only)"}); return False
        origin = self.headers.get("Origin")
        if origin:
            oh = (urlparse(origin).hostname or "")
            if oh not in LOOPBACK_HOSTS:
                self._json(403, {"error": "bad origin (loopback only)"}); return False
        return True

    def _write_guard(self):
        """Extra gate for state-changing routes: JSON content-type + per-run token."""
        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            self._json(415, {"ok": False, "error": "Content-Type must be application/json"}); return False
        if not secrets.compare_digest(self.headers.get("X-Owner-Token", ""), RUN_TOKEN):
            self._json(403, {"ok": False, "error": "missing/invalid owner token"}); return False
        return True

    def do_GET(self):
        if not self._origin_guard():
            return
        # inject the per-run token into the shell so ONLY a same-origin page can obtain it
        if self.path.split("?")[0] in ("/", "/graph.html"):
            f = HERE / "graph.html"
            if f.exists():
                html = f.read_text(encoding="utf-8").replace(
                    "</head>", f'<script>window.__OWNER_REMOTE_TOKEN={json.dumps(RUN_TOKEN)}</script></head>', 1)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        if self.path.split("?")[0] == "/voice/health":
            return self._json(200, {
                "stt_engine": _stt_engine(),
                "capabilities": {
                    "transcribe": _stt_engine() == "LOCAL_WHISPER",
                    "canonical_task": (REPO / "scripts" / "orchestrator_queue.py").exists(),
                    "canonical_idea": (REPO / "docs" / "ideas").exists(),
                    "canonical_decision": False,   # no accepted owner-decision write interface
                },
                "decision_write": "NOT_AVAILABLE",
                "loopback_only": True,
            })
        return super().do_GET()

    def do_POST(self):
        if not self._origin_guard():
            return
        route = self.path.split("?")[0]
        qs = self.path.split("?")[1] if "?" in self.path else ""
        lang = "ru"
        m = re.search(r"lang=(\w+)", qs)
        if m:
            lang = m.group(1)

        if route == "/voice/transcribe":
            audio = self._read_body(MAX_AUDIO)
            if audio is None:
                return self._json(413, {"error": "audio too large"})
            return self._json(200, _transcribe(audio, lang))

        # JSON write routes — require confirmed:true and refuse RED text (defence in depth)
        raw = self._read_body(256 * 1024)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return self._json(400, {"error": "bad json"})
        transcript = (data.get("transcript") or data.get("text") or "").strip()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if route == "/voice/decision":
            # explicit: no accepted canonical decision write; never fabricate an ADR from a phrase
            return self._json(200, {"available": False, "status": "NOT_AVAILABLE",
                                    "reason": "no accepted canonical owner-decision write interface",
                                    "draft": transcript})

        if route in ("/voice/task", "/voice/idea"):
            if not self._write_guard():      # json content-type + per-run owner token
                return
            if not data.get("confirmed"):
                return self._json(403, {"ok": False, "error": "owner confirmation required"})
            if _is_red(transcript):
                return self._json(403, {"ok": False, "error": "REFUSED: command resembles an action (RED); this server only creates tasks/ideas"})
            if not transcript:
                return self._json(400, {"ok": False, "error": "empty transcript"})
            if route == "/voice/task":
                title = (data.get("normalized") or transcript)[:120]
                body = (f"Создано голосом (Owner Remote) {ts}.\n\n"
                        f"Транскрипт: {transcript}\n")
                return self._json(200, _create_task(title, body))
            return self._json(200, _write_idea(transcript, ts))

        return self._json(404, {"error": "unknown route"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)   # loopback only — never all interfaces
    print(f"Owner Remote server on http://127.0.0.1:{a.port}  (STT={_stt_engine()})", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
