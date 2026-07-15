"""Telegram → Inbox intake (ENV_SETUP_BRIEF_v3 · Этап 6).

Turns two Telegram inputs into files-first Inbox cards (nimbalyst-local/tracker/):
  - ``/task <text>``  → an Inbox card, source=telegram
  - a voice message   → transcribed OFFLINE via the local ``whisper`` CLI
                        (large-v3-turbo, ru/uk auto-detect), source=voice, with
                        the transcript attached in the card body.

stdlib-only (subprocess/urllib/tempfile). The orchestrator later classifies each
card (task/idea/unclear) per docs/ORCHESTRATOR_PROTOCOL.md. Fail-safe: any error
returns a friendly result and never raises into the bot poll loop.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from spa_core.owner_queue.queue import create_card

log = logging.getLogger(__name__)

# Local offline transcription. large-v3-turbo is already cached in ~/.cache/whisper.
_WHISPER_BIN = os.environ.get("SPA_WHISPER_BIN") or shutil.which("whisper") or "/opt/homebrew/bin/whisper"
_WHISPER_MODEL = os.environ.get("SPA_WHISPER_MODEL", "turbo")


def _title_from_text(text: str, maxlen: int = 80) -> str:
    """First non-empty line, trimmed — the card title."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= maxlen else line[: maxlen - 1].rstrip() + "…"
    return "Задание из Telegram"


def save_inbox_task(text: str, source: str = "telegram", transcript: str | None = None) -> tuple[Path, str]:
    """Create an Inbox card from free text. Returns (path, title)."""
    title = _title_from_text(text)
    body_parts = ["## Задание (из Telegram)", "", text.strip(), ""]
    if transcript is not None:
        body_parts += ["## Расшифровка голосового (whisper)", "", transcript.strip(), ""]
    body_parts += [
        "---",
        "_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку "
        "со ссылкой на порождённую работу (§6.4)._",
    ]
    path = create_card(
        "inbox", title, "\n".join(body_parts),
        status="new", source=source,
    )
    return path, title


def transcribe_voice(audio_path: str | Path, language: str | None = None, timeout: int = 300) -> str | None:
    """Transcribe an audio file with the local whisper CLI. Returns text or None.

    ``language=None`` → auto-detect (handles both ru and uk). Offline, no network.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="spa_whisper_") as out_dir:
        cmd = [
            _WHISPER_BIN, str(audio_path),
            "--model", _WHISPER_MODEL,
            "--task", "transcribe",
            "--output_format", "txt",
            "--output_dir", out_dir,
            "--fp16", "False",
        ]
        if language:
            cmd += ["--language", language]
        # whisper shells out to ffmpeg; under launchd PATH lacks /opt/homebrew/bin,
        # so ensure Homebrew's bin (ffmpeg + whisper) is resolvable in the child env.
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log.warning("transcribe_voice: whisper failed to run: %s", exc)
            return None
        if proc.returncode != 0:
            log.warning("transcribe_voice: whisper exit %s: %s", proc.returncode, proc.stderr[-300:])
            return None
        # whisper writes <stem>.txt in out_dir
        txts = list(Path(out_dir).glob("*.txt"))
        if not txts:
            return None
        text = txts[0].read_text(encoding="utf-8", errors="replace").strip()
        return text or None


def download_telegram_file(token: str, file_id: str, dest_dir: str | Path, timeout: int = 30) -> Path | None:
    """Resolve a Telegram file_id via getFile and download it. Returns local path or None."""
    try:
        api = f"https://api.telegram.org/bot{token}"
        with urllib.request.urlopen(f"{api}/getFile?file_id={file_id}", timeout=timeout) as resp:
            import json

            meta = json.loads(resp.read().decode("utf-8"))
        if not meta.get("ok"):
            log.warning("download_telegram_file: getFile not ok: %s", meta)
            return None
        file_path = meta["result"]["file_path"]
        suffix = os.path.splitext(file_path)[1] or ".oga"
        dest = Path(dest_dir) / f"voice_{file_id[:16]}{suffix}"
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        with urllib.request.urlopen(url, timeout=timeout) as r, open(dest, "wb") as fh:
            shutil.copyfileobj(r, fh)
        return dest
    except Exception as exc:  # noqa: BLE001 — fail-safe, never crash the bot
        log.warning("download_telegram_file failed: %s", exc)
        return None


def transcribe_voice_message(token: str, file_id: str) -> str | None:
    """Download a Telegram voice file and transcribe it (NO card). Returns text or None.

    Used by the Q&A router: a voice message may be a QUESTION, not a task — so we
    transcribe first, then classify, instead of always saving an Inbox card.
    """
    with tempfile.TemporaryDirectory(prefix="spa_voice_") as tmp:
        audio = download_telegram_file(token, file_id, tmp)
        if audio is None:
            return None
        return transcribe_voice(audio)


def handle_voice_message(token: str, file_id: str) -> tuple[Path, str] | None:
    """Full voice path: download → transcribe → Inbox card. Returns (path, transcript) or None."""
    with tempfile.TemporaryDirectory(prefix="spa_voice_") as tmp:
        audio = download_telegram_file(token, file_id, tmp)
        if audio is None:
            return None
        transcript = transcribe_voice(audio)
        if not transcript:
            return None
        path, _title = save_inbox_task(transcript, source="voice", transcript=transcript)
        return path, transcript
