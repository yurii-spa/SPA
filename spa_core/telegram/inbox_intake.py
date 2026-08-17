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
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.owner_queue.queue import create_card

log = logging.getLogger(__name__)

# Local offline transcription. large-v3-turbo is already cached in ~/.cache/whisper.
_WHISPER_BIN = os.environ.get("SPA_WHISPER_BIN") or shutil.which("whisper") or "/opt/homebrew/bin/whisper"
_WHISPER_MODEL = os.environ.get("SPA_WHISPER_MODEL", "turbo")

# ── Склейка ОДНОГО длинного сообщения владельца (замер #215, 13.08) ─────────────
#
# Telegram НЕ УМЕЕТ доставить сообщение длиннее ~4096 символов: клиент сам рубит
# вставленный документ на куски и отправляет их подряд, за секунды. Для бота это
# N НЕЗАВИСИМЫХ сообщений, и интейк заводил по карточке на каждое. 13.08 в 13:10
# спецификация владельца «TASK — Portfolio CIO» приехала СЕМЬЮ карточками за 21
# секунду; шесть из них — обрывки на полуслове («если тот же target можно
# приблизить простым:»), то есть задания, которых владелец не давал. Разрез
# происходил не «по абзацам» в нашем коде — его делал транспорт, а наш код молча
# принимал результат за семь заданий.
#
# Правило — детерминированное, без LLM, на двух проверяемых признаках:
#   1) предыдущая часть ДЛИННАЯ (≈ упёрлась в лимит транспорта) ⇒ она оборвана,
#      а не закончена;
#   2) следующее сообщение пришло в течение окна и в него же (тот же source).
# Тогда это ПРОДОЛЖЕНИЕ — оно дописывается в ту же карточку. Явный маркер новой
# задачи в начале текста разрывает склейку: владелец сказал «это новое».
#
#: Длина части, после которой сообщение считается ОБОРВАННЫМ транспортом.
#: Замер на живых семи кусках: 4088, 3346, 4085, 4062, 4086, 4080, 4087 символов
#: при лимите Telegram 4096 — порог 3000 покрывает все семь с запасом, а обычное
#: человеческое поручение («проверь дашборд») до него не дотягивает и близко.
_SPLIT_HINT_CHARS = 3000
#: Окно на продолжение. Клиент шлёт куски за секунды (7 частей ≈ 21 с); 5 минут —
#: запас на ручную досылку хвоста, но не настолько, чтобы склеить два разговора.
_CONTINUATION_WINDOW_SEC = 300
#: Предохранитель: карточка не растёт бесконечно, даже если склейка ошиблась.
_MAX_PARTS = 60

_FIELD_LAST_PART_AT = "intake_last_part_at"
_FIELD_PART_CHARS = "intake_last_part_chars"
_FIELD_PARTS = "intake_parts"

#: Явное «это НОВАЯ задача» в начале сообщения — склейку не делаем.
_NEW_TASK_MARKER = re.compile(
    r"^\s*(?:/task\b|новая\s+задача\b|задача\s*[:\-—]|задание\s*[:\-—])",
    re.IGNORECASE,
)

_FOOTER = ("_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку "
           "со ссылкой на порождённую работу (§6.4)._")


def _title_from_text(text: str, maxlen: int = 80) -> str:
    """First non-empty line, trimmed — the card title."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= maxlen else line[: maxlen - 1].rstrip() + "…"
    return "Задание из Telegram"


def _parse_ts(value: str) -> datetime | None:
    """ISO-8601 (с ``Z`` или смещением) → aware UTC datetime; мусор → None."""
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_continuation_target(source: str, now: datetime, tracker_dir=None):
    """Открытая карточка, ЧАСТЬЮ которой является пришедший сейчас текст, или None.

    Ищем последнюю inbox-карточку того же источника, чья последняя часть (а) упёрлась
    в лимит транспорта и (б) принята не позже ``_CONTINUATION_WINDOW_SEC`` назад.
    """
    from spa_core.owner_queue.queue import _OPEN_STATUSES, list_cards

    best = None
    best_ts = None
    for card in list_cards(tracker_type="inbox", tracker_dir=tracker_dir):
        if (card.status or "") not in _OPEN_STATUSES:
            continue
        if str(card.fields.get("source", "")) != source:
            continue
        ts = _parse_ts(card.fields.get(_FIELD_LAST_PART_AT, ""))
        if ts is None:
            continue
        try:
            prev_chars = int(str(card.fields.get(_FIELD_PART_CHARS, "0")).strip() or 0)
            parts = int(str(card.fields.get(_FIELD_PARTS, "1")).strip() or 1)
        except ValueError:
            continue
        if prev_chars < _SPLIT_HINT_CHARS or parts >= _MAX_PARTS:
            continue
        if not (timedelta(0) <= now - ts <= timedelta(seconds=_CONTINUATION_WINDOW_SEC)):
            continue
        if best_ts is None or ts > best_ts:
            best, best_ts = card, ts
    return best


def continue_open_task(
    text: str,
    source: str = "telegram",
    now: datetime | None = None,
    tracker_dir=None,
) -> tuple[Path, str, int] | None:
    """Дописать ``text`` как ЧАСТЬ уже принятого длинного сообщения.

    Возвращает ``(path, title, part_no)``, если это продолжение, иначе ``None`` —
    тогда вызывающий заводит новую карточку обычным путём.
    """
    from spa_core.owner_queue.queue import load_card, set_fields
    from spa_core.utils.atomic import atomic_save_text

    body = (text or "").strip()
    if not body or _NEW_TASK_MARKER.match(body):
        return None
    dt = now or datetime.now(timezone.utc)
    card = find_continuation_target(source, dt, tracker_dir=tracker_dir)
    if card is None:
        return None
    try:
        parts = int(str(card.fields.get(_FIELD_PARTS, "1")).strip() or 1) + 1
        raw = card.path.read_text(encoding="utf-8")
        chunk = f"\n## Продолжение — часть {parts} (то же сообщение владельца, {_fmt_ts(dt)})\n\n{body}\n"
        # Вставляем ПЕРЕД служебным хвостом, чтобы тело читалось как один документ.
        idx = raw.rfind(_FOOTER)
        if idx == -1:
            new_text = raw.rstrip("\n") + "\n" + chunk
        else:
            head = raw[:idx].rstrip("\n")
            new_text = f"{head}\n{chunk}\n{raw[idx:].lstrip()}"
        atomic_save_text(new_text, str(card.path))
        set_fields(card.path, {
            _FIELD_LAST_PART_AT: _fmt_ts(dt),
            _FIELD_PART_CHARS: len(body),
            _FIELD_PARTS: parts,
        })
    except Exception as exc:  # noqa: BLE001 — не склеили ⇒ пусть будет отдельная карточка,
        log.warning("continue_open_task failed: %s — падаю на обычную карточку", exc)
        return None
    return card.path, load_card(card.path).title, parts


def save_inbox_task(
    text: str,
    source: str = "telegram",
    transcript: str | None = None,
    *,
    now: datetime | None = None,
    tracker_dir=None,
    allow_continuation: bool = True,
) -> tuple[Path, str]:
    """Create an Inbox card from free text. Returns (path, title).

    Длинное сообщение, разрубленное транспортом на куски, остаётся ОДНОЙ карточкой:
    продолжение дописывается в неё (см. ``continue_open_task``). ``allow_continuation=False``
    — для явного ``/task``: владелец сам объявил новое задание.
    """
    dt = now or datetime.now(timezone.utc)
    if allow_continuation and transcript is None:
        cont = continue_open_task(text, source=source, now=dt, tracker_dir=tracker_dir)
        if cont is not None:
            path, title, _parts = cont
            return path, title

    title = _title_from_text(text)
    body_parts = ["## Задание (из Telegram)", "", text.strip(), ""]
    if transcript is not None:
        body_parts += ["## Расшифровка голосового (whisper)", "", transcript.strip(), ""]
    body_parts += ["---", _FOOTER]
    kwargs = {
        "status": "new",
        "source": source,
        # Отметки склейки — в самой карточке (files-first, отдельного state-файла нет).
        "extra_fields": {
            _FIELD_LAST_PART_AT: _fmt_ts(dt),
            _FIELD_PART_CHARS: len(text.strip()),
            _FIELD_PARTS: 1,
        },
    }
    if tracker_dir is not None:
        kwargs["tracker_dir"] = tracker_dir
    path = create_card("inbox", title, "\n".join(body_parts), **kwargs)
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
