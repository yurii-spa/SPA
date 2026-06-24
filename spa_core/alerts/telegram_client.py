"""MP-015: Telegram client with credentials from macOS Keychain.

Secrets policy (incident 2026-06-10): the bot token and chat id are NEVER
stored in files or env defaults — they are read at runtime from the macOS
Keychain entries ``TELEGRAM_BOT_TOKEN_SPA`` / ``TELEGRAM_CHAT_ID_SPA``
(account ``spa``). Rotation = ``security add-generic-password ... -U``.

Stdlib only: ``subprocess`` for Keychain, ``urllib.request`` for HTTP.

* ``get_bot_token()`` / ``get_chat_id()`` raise ``EnvironmentError`` when the
  Keychain entry is unavailable.
* ``send_message()`` is fail-safe: 10 s timeout, one retry on network error,
  any failure (including missing credentials) → WARNING + ``False``,
  never raises.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("spa.alerts.telegram_client")

KEYCHAIN_ACCOUNT = "spa"
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

HTTP_TIMEOUT_S = 10
RETRIES = 1  # one retry on network error → two attempts total

# ── Flood guard ──────────────────────────────────────────────────────────────
# A SHARED, cross-process rate limit. Every SPA agent is a separate process, so the
# counter lives in a state file: the cap bounds TOTAL Telegram volume no matter how many
# agents (or one runaway loop) try to send. Excess is dropped + logged so a flooder is
# visible in the log without spamming the chat. Fail-open (a guard error never blocks sends).
_RATE_STATE = Path(__file__).resolve().parents[2] / "data" / ".telegram_rate.json"
MAX_MSGS_PER_MIN = 12


def _rate_limit_ok(text: str = "") -> bool:
    try:
        now = time.time()
        try:
            hist = json.loads(_RATE_STATE.read_text())
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []
        hist = [t for t in hist if isinstance(t, (int, float)) and (now - t) < 60.0]
        if len(hist) >= MAX_MSGS_PER_MIN:
            log.warning("Telegram FLOOD GUARD: dropped message (>%d/min). preview=%r",
                        MAX_MSGS_PER_MIN, (text or "")[:100])
            return False
        hist.append(now)
        _RATE_STATE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_RATE_STATE.parent), prefix=".tgrate_")
        with os.fdopen(fd, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, _RATE_STATE)
        return True
    except Exception:
        return True  # fail-open: never block a legitimate send on a guard error


def _read_keychain(service: str) -> str:
    """Read one generic password from the macOS Keychain. Raises EnvironmentError."""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", service,
                "-a", KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=HTTP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError(
            "Telegram credentials not found in Keychain"
        ) from exc
    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        raise EnvironmentError("Telegram credentials not found in Keychain")
    return value


def get_bot_token() -> str:
    """Bot token from Keychain service ``TELEGRAM_BOT_TOKEN_SPA``."""
    return _read_keychain(TOKEN_SERVICE)


def get_chat_id() -> str:
    """Chat id from Keychain service ``TELEGRAM_CHAT_ID_SPA``."""
    return _read_keychain(CHAT_ID_SERVICE)


def _post_message(payload_dict: dict) -> bool:
    """Internal: POST a sendMessage payload. Shared by send_message and
    send_message_with_keyboard. Fail-safe: any failure → WARNING + False."""
    # FLOOD GUARD: a shared cross-process rate limit so NO sender (any agent) can flood
    # Telegram. Excess messages are DROPPED + logged with a preview (identifies the flooder).
    if not _rate_limit_ok(payload_dict.get("text", "")):
        return False
    try:
        token = get_bot_token()
        chat_id = get_chat_id()
    except EnvironmentError as exc:
        log.warning("Telegram send skipped: %s", exc)
        return False

    payload_dict["chat_id"] = chat_id
    payload_dict.setdefault("parse_mode", "Markdown")
    payload_dict.setdefault("disable_web_page_preview", True)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(payload_dict).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(1 + RETRIES):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status == 200:
                    return True
                last_err = RuntimeError(f"HTTP status {resp.status}")
        except urllib.error.HTTPError as exc:
            # 400 = parse error (Markdown/HTML choke on '_' in protocol names or '<').
            # Retry ONCE as plain text so the message always delivers (no formatting
            # beats a silently-dropped alert). Fixes the recurring 400 glitch class.
            if exc.code == 400 and "parse_mode" in payload_dict:
                log.warning("Telegram 400 (parse) — retrying as plain text")
                payload_dict.pop("parse_mode", None)
                payload = json.dumps(payload_dict).encode("utf-8")
                continue
            log.warning("Telegram API error %s: %s", exc.code, exc.reason)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
        except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
            last_err = exc

    log.warning("Telegram send failed after %d attempt(s): %s", 1 + RETRIES, last_err)
    return False


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """POST the message to the Telegram Bot API.

    ``parse_mode`` defaults to ``"Markdown"`` (back-compat). Pass ``"HTML"`` for
    messages that contain HTML tags such as ``<b>`` — Telegram's legacy Markdown
    parser 400s on the ``_`` in protocol names (e.g. ``aave_v3``) and on ``<>``.

    Fail-safe: missing credentials, HTTP or network errors → WARNING + False.
    One retry on network error. Never raises.
    """
    return _post_message({"text": text, "parse_mode": parse_mode})


def send_message_with_keyboard(text: str, keyboard: dict) -> bool:
    """POST the message with an inline keyboard to the Telegram Bot API.

    ``keyboard`` must be a dict ready to be JSON-serialised, e.g.::

        {"inline_keyboard": [[{"text": "X", "callback_data": "cmd_x"}]]}

    Fail-safe: any failure → WARNING + False. Never raises.
    """
    return _post_message({"text": text, "reply_markup": json.dumps(keyboard)})
