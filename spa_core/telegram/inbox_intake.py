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


#: ADR-612 (review P1-1, second line): a card whose text names money (asset + verb/amount) is
#: stamped so its reader treats it as a TOPIC, never as an order to execute. The bot has no
#: execution path and real capital is $0 — the stamp keeps it that way for any future reader.
MONEY_INTENT_FIELD = "money_intent"
MONEY_INTENT_NOTE = ("> ⚠️ `money_intent: suspected` — текст упоминает деньги/актив. Это НЕ приказ: "
                     "исполнения нет, реальный капитал $0; предмет №1 (ADR-285) — только решение владельца.")


def _money_fields(*texts: str | None) -> tuple[dict | None, list[str]]:
    from spa_core.telegram import money_intent
    if any(t and money_intent.is_suspected(t) for t in texts):
        return {MONEY_INTENT_FIELD: "suspected"}, [MONEY_INTENT_NOTE, ""]
    return None, []


#: ADR-760: the owner cockpit's voice/text intake uses THIS function too (one intake path, one card
#: format). ``kind`` is the owner's own label (idea/task/note) — a hint for the orchestrator's
#: classification, never an instruction to execute.
INTAKE_KIND_RU = {"idea": "идея", "task": "задача", "note": "замечание"}


def inbox_tracker_dir() -> Path:
    """Каталог, куда ``save_inbox_task`` пишет по умолчанию (читается в момент вызова: тесты и
    прод подменяют ``queue.TRACKER_DIR``). Пульту он нужен для замка и поиска ``submission_id``."""
    from spa_core.owner_queue import queue as _q
    return Path(_q.TRACKER_DIR)


def save_inbox_task(text: str, source: str = "telegram", transcript: str | None = None, *,
                    kind: str | None = None, origin_label: str = "Telegram",
                    tracker_dir=None, extra_fields: dict | None = None,
                    preamble: list[str] | None = None) -> tuple[Path, str]:
    """Create an Inbox card from free text. Returns (path, title).

    ``extra_fields`` / ``preamble`` — дополнительные поля frontmatter и строки в начале тела
    (пульт ADR-760: ``submission_id``, ``actor``, строка о границе полномочий). Telegram их
    не передаёт — его карточки не меняются.
    """
    title = _title_from_text(text)
    extra, note = _money_fields(text, transcript)
    if kind in INTAKE_KIND_RU:
        extra = dict(extra or {})
        extra["intake_kind"] = kind
    if extra_fields:
        extra = dict(extra or {})
        extra.update(extra_fields)
    body_parts = note + list(preamble or []) + [f"## Задание (из {origin_label})", ""]
    if kind in INTAKE_KIND_RU:
        body_parts += [f"_Владелец пометил как: {INTAKE_KIND_RU[kind]}._", ""]
    body_parts += [text.strip(), ""]
    if transcript is not None:
        body_parts += ["## Расшифровка голосового (whisper)", "", transcript.strip(), ""]
    body_parts += [
        "---",
        "_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку "
        "со ссылкой на порождённую работу (§6.4)._",
    ]
    path = create_card(
        "inbox", title, "\n".join(body_parts),
        status="new", source=source, extra_fields=extra, tracker_dir=tracker_dir,
    )
    return path, title


#: Заголовок тела карточки-«неприменённый ответ». Отдельная константа, потому что по
#: ней карточку узнаёт разбор очереди: «2» в заголовке неотличимо от задания, а эта
#: строка — отличима, и её ищут, а не угадывают.
UNAPPLIED_ANSWER_HEADING = "## Неприменённый ответ владельца — это НЕ задание"


def save_unapplied_owner_answer(text: str, *, num: str = "", candidates=(),
                                asked_with_buttons: bool = False,
                                source: str = "telegram") -> tuple[Path, str]:
    """Ответ владельца, который НЕ К ЧЕМУ применить, — карточкой, названной честно.

    Слова владельца сохраняются ровно как раньше (:func:`save_inbox_task` их не терял),
    меняется ИМЯ вещи. Голое «2» уезжало в очередь карточкой с заголовком «2» и телом
    «## Задание (из Telegram)» — то есть ответ владельца лежал среди РАБОТЫ, а вопрос
    продолжал висеть `needs-owner`. Замер 22–23.08: четыре таких карточки за двое суток
    (`inbox-1-2`, `inbox-2`, `inbox-1-3`, `inbox-2-2`), и каждый раз разбирать их
    приходилось человеку, вручную восстанавливая, что это вообще было.

    Догадки о СМЫСЛЕ числа здесь нет: в тело кладётся только измеренное — что прислал
    владелец, какие вопросы были открыты и предлагал ли каждый из них этот номер.
    """
    shown = str(num or "").strip() or _title_from_text(text, maxlen=40)
    title = f"Неприменённый ответ владельца «{shown}» — адресат не назван"
    lines = [
        UNAPPLIED_ANSWER_HEADING,
        "",
        f"Владелец прислал в чат: «{text.strip()}». Это ОТВЕТ на вопрос, а не поручение — "
        "применить его было не к чему: открытых вопросов несколько, и угадывать адресата "
        "запрещено (ADR-075).",
        "",
    ]
    if asked_with_buttons:
        lines += ["**Что сделал бот:** переспросил ОДНИМ сообщением с кнопками — какому "
                  "вопросу предназначен ответ. Нажатие запишет решение обычным "
                  "owner-путём.", ""]
    else:
        lines += ["**Что сделал бот:** назвал причину текстом. Кнопок не было: ни один из "
                  "открытых вопросов такого варианта не предлагает.", ""]
    lines += ["### Открытые вопросы на момент ответа", ""]
    if candidates:
        for c in candidates:
            mark = "предлагает этот вариант" if c.get("offers") else "этого варианта НЕ предлагает"
            lines.append(f"- `{c.get('card_id') or '?'}` — {c.get('title') or ''} ({mark})")
    else:
        lines.append("- (список не измерен)")
    lines += [
        "",
        "### Что делать оркестратору",
        "",
        "Задачей это НЕ исполнять. Владелец нажал кнопку ⇒ решение уже записано в свою "
        "карточку, здесь останется только закрыть этот след (`done`) со ссылкой. Не нажал "
        "⇒ переспросить по протоколу (`notify` / `resend`), не угадывая, к чему относился "
        "номер.",
        "",
        "---",
        "_Карточку создал бот (`inbox_intake.save_unapplied_owner_answer`) — см. класс "
        "`inbox-golyi-otvet-vladeltsa-1-2-pri-voprose-be`._",
    ]
    path = create_card("inbox", title, "\n".join(lines), status="new", source=source)
    return path, title


def save_inbox_document(text: str, provenance: str, source: str = "telegram") -> tuple[Path, str]:
    """Создать ОДНУ карточку из документа, собранного обратно из кусков Телеграма.

    Отличие от :func:`save_inbox_task` — тело несёт ПРОИСХОЖДЕНИЕ: из скольких сообщений
    документ собран и почему сборка закрыта. Без этой строки восстановить связь частей
    можно было бы только памятью человека (ровно на этом и погорели семь карточек 13.08).

    Классификатор ВОПРОС/ЗАДАЧА здесь сознательно не зовётся: многочастный документ — это
    задание с телом, а не вопрос. Заодно в разборщик не уезжает текст в десятки килобайт.
    """
    title = _title_from_text(text)
    body = "\n".join([
        "## Задание (из Telegram)",
        "",
        text.strip(),
        "",
        "## Как это приехало",
        "",
        provenance,
        "",
        "_Классификатор не вызывался: документ из нескольких частей — задание, а не вопрос._",
        "",
        "---",
        "_Оркестратор: при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._",
    ])
    extra, note = _money_fields(text)
    if note:
        body = "\n".join(note) + "\n" + body
    path = create_card("inbox", title, body, status="new", source=source, extra_fields=extra)
    return path, title


#: Исходы расшифровки (ADR-760, инв. #17): «whisper не успел», «whisper упал» и «речь пустая» —
#: три РАЗНЫХ наблюдения, а не одно ``None``. Пульт показывает владельцу каждое своими словами.
TRANSCRIBE_OK = "ok"
TRANSCRIBE_EMPTY = "empty"
TRANSCRIBE_TIMEOUT = "timeout"
TRANSCRIBE_FAILED = "failed"


def transcribe_voice_detailed(audio_path: str | Path, language: str | None = None,
                              timeout: int = 300) -> tuple[str, str | None]:
    """Transcribe with the local whisper CLI. Returns ``(outcome, text)``.

    ``outcome`` ∈ ``TRANSCRIBE_OK`` (text is non-empty) · ``TRANSCRIBE_EMPTY`` (whisper ran and
    heard nothing) · ``TRANSCRIBE_TIMEOUT`` (killed after ``timeout`` s) · ``TRANSCRIBE_FAILED``
    (no input file, could not start, non-zero exit). ``language=None`` → auto-detect (ru and uk).
    Offline, no network.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return TRANSCRIBE_FAILED, None
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
        except subprocess.TimeoutExpired as exc:
            log.warning("transcribe_voice: whisper timed out after %ss: %s", timeout, exc)
            return TRANSCRIBE_TIMEOUT, None
        except (FileNotFoundError, OSError) as exc:
            log.warning("transcribe_voice: whisper failed to run: %s", exc)
            return TRANSCRIBE_FAILED, None
        if proc.returncode != 0:
            log.warning("transcribe_voice: whisper exit %s: %s", proc.returncode, (proc.stderr or "")[-300:])
            return TRANSCRIBE_FAILED, None
        # whisper writes <stem>.txt in out_dir
        txts = list(Path(out_dir).glob("*.txt"))
        if not txts:
            return TRANSCRIBE_EMPTY, None
        text = txts[0].read_text(encoding="utf-8", errors="replace").strip()
        return (TRANSCRIBE_OK, text) if text else (TRANSCRIBE_EMPTY, None)


def transcribe_voice(audio_path: str | Path, language: str | None = None, timeout: int = 300) -> str | None:
    """Transcribe an audio file with the local whisper CLI. Returns text or None.

    The Telegram contract (text or ``None``) is unchanged; the distinguishing outcomes live in
    :func:`transcribe_voice_detailed`.
    """
    _outcome, text = transcribe_voice_detailed(audio_path, language=language, timeout=timeout)
    return text


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
