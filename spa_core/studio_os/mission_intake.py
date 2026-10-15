"""spa_core/studio_os/mission_intake.py — the ONE write action of the owner cockpit (ADR-760).

Owner 15.10: «голосовой ввод с телефона — огромный плюс». The cockpit stays read-only for
everything else; this module is the only place a cockpit request may write, and it may write
exactly one thing: a NEW inbox card through the SAME intake path the Telegram ``/task`` and voice
messages use (``spa_core.telegram.inbox_intake.save_inbox_task`` → ``owner_queue.create_card``,
status ``new``). It never executes, approves, answers, moves money or touches any other file.

Two operations, each guarded by :class:`IntakeGate` (the server calls ``gate.check`` first):

* ``transcribe(audio_bytes, content_type)`` — the SAME local offline whisper the Telegram bot uses
  (``inbox_intake.transcribe_voice``); audio ≤ ``MAX_AUDIO_BYTES`` and ≤ ``MAX_AUDIO_SECONDS``
  (measured by ``ffprobe`` when present; absent ⇒ the duration is «не измерена» and only the size
  limit applies — said in the answer, never silently). Whisper absent ⇒ a NAMED refusal
  ``WHISPER_UNAVAILABLE``, never an empty transcript.
* ``submit(text, kind, transcript, actor)`` — one inbox card; ``kind`` ∈ idea/task/note.
  ``submission_id`` (made by the page when the composer opens, kept across retries) makes the
  write IDEMPOTENT: a card already carrying that id (any status) is returned with
  ``duplicate: true`` instead of a second card. The check-and-write runs under one lock
  (an in-process lock + ``flock`` on the tracker directory itself — no marker file is written).
  Every cockpit card records the Access ``actor`` and the fixed authority-boundary line
  :data:`AUTHORITY_NOTE` (ADR-285): a note is never a permission.

Whisper outcomes are NOT collapsed (inv. #17): timeout ⇒ 504 ``WHISPER_TIMEOUT``, the process failed
⇒ 503 ``WHISPER_FAILED``, nothing heard ⇒ 422 ``EMPTY_TRANSCRIPT``, a transcription already running
⇒ 429 ``WHISPER_BUSY`` (one whisper at a time — ``_WHISPER_SLOT``).

Guards (fail-CLOSED; any doubt ⇒ refusal, nothing written):
  * a per-process CSRF token (``csrf_token()``; the page fetches it with a same-origin GET — a
    cross-site page cannot read it) must be echoed in ``X-Intake-Token``;
  * ``Origin`` must equal the listener's own origin (loopback for the local listener, the
    Access-protected public host for the public one); missing ⇒ refused;
  * the body type must match the operation; size limits; a small rate limit per operation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

TRANSCRIBE_PATH = "/api/intake/transcribe"
SUBMIT_PATH = "/api/intake/submit"
CSRF_PATH = "/api/intake/csrf"
POST_PATHS = (TRANSCRIBE_PATH, SUBMIT_PATH)

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
MAX_TEXT_CHARS = 4000
MAX_JSON_BYTES = 64 * 1024
AUDIO_TYPES = ("audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac", "audio/webm", "audio/ogg",
               "audio/wav", "audio/x-wav", "audio/mpeg")
AUDIO_SUFFIX = {"audio/mp4": ".m4a", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
                "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
                "audio/mpeg": ".mp3"}
KINDS = {"idea": "Идея", "task": "Задача", "note": "Замечание"}
RATE_LIMITS = {TRANSCRIBE_PATH: (6, 60.0), SUBMIT_PATH: (10, 60.0)}   # (count, per seconds)
TOKEN_HEADER = "X-Intake-Token"

#: Идентификатор отправки (страница создаёт его при открытии окна записи и держит при повторах).
SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
SUBMISSION_FIELD = "submission_id"
#: Источники карточек пульта (ADR-760) — по ним «Мои записи» и приём узнают запись из пульта.
COCKPIT_SOURCES = ("cockpit", "cockpit-voice")
#: Граница полномочий (ADR-285): заметка из пульта — не разрешение. Строка фиксированная,
#: её ищут дословно (тест), поэтому она живёт в одном месте.
AUTHORITY_NOTE = ("> Это заметка владельца из пульта, а не разрешение на действия с деньгами, публичными "
                  "числами или необратимые действия (ADR-285); такие действия — только через owner-gate / "
                  "карточку владельца.")

#: Один whisper за раз: turbo на Mac занимает все ядра, шесть параллельных расшифровок
#: (лимит частоты — 6 в минуту) уводили каждую за таймаут. Занято ⇒ честный 429, не очередь.
_WHISPER_SLOT = threading.Semaphore(1)
#: Сериализация «проверить submission_id → записать карточку» внутри процесса; между процессами —
#: ``flock`` на каталоге трекера (см. :func:`_tracker_lock`).
_SUBMIT_LOCK = threading.Lock()


class IntakeRefused(Exception):
    """A refusal with an HTTP status and a stable code; ``message_ru`` is shown to the owner."""

    def __init__(self, status: int, code: str, message_ru: str):
        super().__init__(f"{status} {code}: {message_ru}")
        self.status, self.code, self.message_ru = status, code, message_ru

    def as_json(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.message_ru}


class IntakeGate:
    """Per-listener guard: CSRF token, origin, content type, size and rate limit."""

    def __init__(self, allowed_origins: tuple, secret: Optional[bytes] = None, clock=time.monotonic):
        self.allowed_origins = tuple(o.rstrip("/") for o in allowed_origins if o)
        self._secret = secret or secrets.token_bytes(32)
        self._clock = clock
        self._hits = {p: deque() for p in POST_PATHS}
        self._lock = threading.Lock()

    def csrf_token(self) -> str:
        return hmac.new(self._secret, b"mission-intake/1", hashlib.sha256).hexdigest()

    def check(self, path: str, headers, content_type: str, length: Optional[int]) -> None:
        if path not in POST_PATHS:
            raise IntakeRefused(405, "METHOD_NOT_ALLOWED", "Этот адрес только для чтения")
        origin = (headers.get("Origin") or "").rstrip("/")
        if not origin or origin not in self.allowed_origins:
            raise IntakeRefused(403, "ORIGIN", "Запрос пришёл не со страницы пульта")
        token = headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(token, self.csrf_token()):
            raise IntakeRefused(403, "CSRF", "Проверочный ключ страницы не совпал — обновите страницу")
        ct = (content_type or "").split(";", 1)[0].strip().lower()
        if path == TRANSCRIBE_PATH:
            if ct not in AUDIO_TYPES:
                raise IntakeRefused(415, "AUDIO_TYPE", "Неподдерживаемый формат записи")
            limit = MAX_AUDIO_BYTES
        else:
            if ct != "application/json":
                raise IntakeRefused(415, "JSON_TYPE", "Ожидался текст записи")
            limit = MAX_JSON_BYTES
        if length is None or length <= 0:
            raise IntakeRefused(411, "LENGTH", "Пустой запрос")
        if length > limit:
            raise IntakeRefused(413, "TOO_LARGE", "Слишком большая запись" if path == TRANSCRIBE_PATH
                                else "Слишком длинный текст")
        with self._lock:
            n, per = RATE_LIMITS[path]
            q = self._hits[path]
            now = self._clock()
            while q and now - q[0] > per:
                q.popleft()
            if len(q) >= n:
                raise IntakeRefused(429, "RATE", "Слишком часто — подождите минуту")
            q.append(now)


# ── transcription: the same local whisper the Telegram bot uses ─────────────────────────────────────
def whisper_status() -> dict:
    """Read-only availability of the local pipeline (recorded for the report; never installs)."""
    from spa_core.telegram import inbox_intake as ii   # the bot's own constants — one pipeline
    binp = ii._WHISPER_BIN
    ok = bool(binp) and (Path(binp).exists() or shutil.which(binp) is not None)
    return {"whisper_bin": binp, "whisper_present": ok, "model": ii._WHISPER_MODEL,
            "ffprobe": _ffprobe()}


def _ffprobe() -> Optional[str]:
    for c in (shutil.which("ffprobe"), "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if c and Path(c).exists():
            return c
    return None


def _duration_seconds(path: Path) -> Optional[float]:
    fp = _ffprobe()
    if not fp:
        return None
    try:
        out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=noprint_wrappers=1:nokey=1", str(path)],
                             capture_output=True, text=True, timeout=20)
        return float(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _run_transcriber(p: Path, transcriber, timeout: int) -> tuple:
    """(outcome, text) — the injected transcriber may return text/None or raise; the default is the
    bot's own whisper call with its distinguishing outcomes."""
    from spa_core.telegram import inbox_intake as ii
    if transcriber is None:
        return ii.transcribe_voice_detailed(p, timeout=timeout)
    try:
        text = transcriber(p)
    except subprocess.TimeoutExpired:
        return ii.TRANSCRIBE_TIMEOUT, None
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return ii.TRANSCRIBE_FAILED, None
    text = (text or "").strip() if isinstance(text, str) else ""
    return (ii.TRANSCRIBE_OK, text) if text else (ii.TRANSCRIBE_EMPTY, None)


def transcribe(audio: bytes, content_type: str, *, transcriber=None, timeout: int = 90) -> dict:
    from spa_core.telegram import inbox_intake as ii
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    st = whisper_status() if transcriber is None else {"whisper_present": True}
    if not st.get("whisper_present"):
        raise IntakeRefused(503, "WHISPER_UNAVAILABLE",
                            "Расшифровка недоступна: на Mac не найден whisper — введите текст вручную")
    if not _WHISPER_SLOT.acquire(blocking=False):
        raise IntakeRefused(429, "WHISPER_BUSY", "Расшифровка уже идёт, подождите")
    try:
        with tempfile.TemporaryDirectory(prefix="mission_intake_") as d:
            p = Path(d) / ("voice" + AUDIO_SUFFIX.get(ct, ".bin"))
            p.write_bytes(audio)
            dur = _duration_seconds(p)
            if dur is not None and dur > MAX_AUDIO_SECONDS + 1:
                raise IntakeRefused(413, "TOO_LONG", "Запись длиннее 2 минут — сократите")
            outcome, text = _run_transcriber(p, transcriber, timeout)
    finally:
        _WHISPER_SLOT.release()
    if outcome == ii.TRANSCRIBE_TIMEOUT:
        raise IntakeRefused(504, "WHISPER_TIMEOUT",
                            "Расшифровка не успела за отведённое время — запись сохранена на странице, "
                            "нажмите «Повторить расшифровку» или введите текст")
    if outcome == ii.TRANSCRIBE_FAILED:
        raise IntakeRefused(503, "WHISPER_FAILED",
                            "Программа расшифровки на Mac завершилась с ошибкой — нажмите «Повторить "
                            "расшифровку» или введите текст")
    if outcome != ii.TRANSCRIBE_OK or not text:
        raise IntakeRefused(422, "EMPTY_TRANSCRIPT", "Не удалось разобрать речь — попробуйте ещё раз или введите текст")
    return {"ok": True, "text": text.strip()[:MAX_TEXT_CHARS],
            "duration_s": round(dur, 1) if dur is not None else None,
            "duration_note": None if dur is not None else "длительность не измерена (нет ffprobe)"}


# ── submit: a NEW inbox card through the existing intake path ────────────────────────────────────────
class _tracker_lock:
    """In-process lock + ``flock`` on the tracker DIRECTORY (no lock file is created: the tracker is
    git-tracked, and a sidecar would be a stray file there). No ``fcntl`` ⇒ the in-process lock alone
    (the mission server is the only writer of cockpit cards)."""

    def __init__(self, d: Path):
        self.d, self.fd = d, None

    def __enter__(self):
        _SUBMIT_LOCK.acquire()
        try:
            import fcntl
            self.d.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(str(self.d), os.O_RDONLY)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except ImportError:
            self.fd = None
        except Exception:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            _SUBMIT_LOCK.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
        finally:
            self.fd = None
            _SUBMIT_LOCK.release()
        return False


def find_submission(tracker_dir: Path, submission_id: str) -> Optional[Path]:
    """The inbox card already carrying ``submission_id`` (any status), or None."""
    needle = f"{SUBMISSION_FIELD}: {submission_id}"
    if not tracker_dir.is_dir():
        return None
    for p in sorted(tracker_dir.glob("inbox-*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle not in text:
            continue
        head = text.split("\n---", 2)[0] if text.startswith("---") else ""
        if any(ln.strip() == needle for ln in head.splitlines()):
            return p
    return None


def _card_field(path: Path, key: str) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    for ln in text.split("\n---", 2)[0].splitlines()[1:]:
        if ln.startswith(key + ":"):
            return ln.split(":", 1)[1].strip().strip('"')
    return None


def submit(body: bytes, *, actor: str, tracker_dir=None, now=None) -> dict:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise IntakeRefused(400, "BAD_JSON", "Не удалось прочитать запрос")
    if not isinstance(doc, dict):
        raise IntakeRefused(400, "BAD_JSON", "Не удалось прочитать запрос")
    text = doc.get("text")
    kind = doc.get("kind")
    transcript = doc.get("transcript")
    sid = doc.get(SUBMISSION_FIELD)
    if not isinstance(text, str) or not text.strip():
        raise IntakeRefused(400, "NO_TEXT", "Введите или продиктуйте текст")
    if len(text) > MAX_TEXT_CHARS:
        raise IntakeRefused(413, "TOO_LONG_TEXT", "Слишком длинный текст")
    if kind not in KINDS:
        raise IntakeRefused(400, "NO_KIND", "Выберите: идея, задача или замечание")
    if transcript is not None and (not isinstance(transcript, str) or len(transcript) > MAX_TEXT_CHARS):
        raise IntakeRefused(400, "BAD_TRANSCRIPT", "Расшифровка повреждена")
    # Старая страница (открытая до обновления пульта) id не присылает — тогда защита от повтора
    # только прежняя (открытый близнец в create_card). Присланный, но кривой id — отказ.
    if sid is not None and (not isinstance(sid, str) or not SUBMISSION_ID_RE.match(sid)):
        raise IntakeRefused(400, "BAD_SUBMISSION_ID", "Повреждён идентификатор отправки — обновите страницу")
    from datetime import datetime, timezone

    from spa_core.telegram import inbox_intake as ii
    save_inbox_task = ii.save_inbox_task
    tdir = Path(tracker_dir) if tracker_dir is not None else ii.inbox_tracker_dir()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = {"submitted_at": stamp, "actor": actor}
    if sid:
        extra[SUBMISSION_FIELD] = sid
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    with _tracker_lock(tdir):
        existing = find_submission(tdir, sid) if sid else None
        if existing is not None:
            ekind = _card_field(existing, "intake_kind")
            ekind = ekind if ekind in KINDS else kind
            return {"ok": True, "duplicate": True, "card": existing.name,
                    "title": _card_field(existing, "title") or existing.stem, "kind": ekind,
                    "kind_ru": KINDS[ekind],
                    "audit": f"intake actor={actor} kind={ekind} card={existing.name} sha={digest} duplicate=1"}
        path, title = save_inbox_task(text, source="cockpit-voice" if transcript else "cockpit",
                                      transcript=transcript, kind=kind, origin_label="пульта",
                                      tracker_dir=tdir, extra_fields=extra, preamble=[AUTHORITY_NOTE, ""])
    return {"ok": True, "duplicate": False, "card": Path(path).name, "title": title, "kind": kind,
            "kind_ru": KINDS[kind],
            "audit": f"intake actor={actor} kind={kind} card={Path(path).name} sha={digest}"}
