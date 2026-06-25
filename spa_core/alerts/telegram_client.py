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
from datetime import datetime, timezone
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

# ── Alert history (append-only audit trail) ──────────────────────────────────
# Every send outcome is recorded here for observability: {ts, type, ok, message_id|error}.
# Ring-buffer capped at HISTORY_MAX so the file never grows unbounded. Atomic write via
# os.replace. Fail-open: a history error NEVER blocks or fails a send. Disabled under
# pytest unless SPA_ALERT_HISTORY_TEST is set (so tests don't pollute the live file).
_HISTORY_STATE = Path(__file__).resolve().parents[2] / "data" / "alert_history.json"
HISTORY_MAX = 500


def _classify(text: str) -> str:
    """Best-effort alert type from the message text (cheap, prefix-based)."""
    t = (text or "")
    head = t.lstrip()[:64]
    if "Go-Live" in head or "Go-Live" in t[:120]:
        return "golive"
    if "Gap" in head:
        return "gap"
    if "Важные события" in head or "red flag" in t.lower()[:120]:
        return "red_flag"
    if "Tournament" in head or "Турнир" in head:
        return "tournament"
    if "подключён" in t[:120] or "startup" in t.lower()[:64]:
        return "startup"
    if "SPA —" in head or "SPA " in head:
        return "daily_summary"
    return "other"


def _record_history(text: str, ok: bool, message_id=None, error: str | None = None) -> None:
    """Append one send outcome to the ring-buffered alert_history.json. Never raises."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_ALERT_HISTORY_TEST"
    ):
        return
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": _classify(text),
            "ok": bool(ok),
            "preview": (text or "")[:80],
        }
        if message_id is not None:
            entry["message_id"] = message_id
        if error:
            entry["error"] = str(error)[:200]

        try:
            doc = json.loads(_HISTORY_STATE.read_text())
            if not isinstance(doc, dict):
                doc = {}
        except Exception:
            doc = {}
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
        entries.append(entry)
        entries = entries[-HISTORY_MAX:]

        doc = {
            "schema_version": 1,
            "source": "telegram_client",
            "updated_at": entry["ts"],
            "count": len(entries),
            "max_entries": HISTORY_MAX,
            "entries": entries,
        }
        _HISTORY_STATE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_HISTORY_STATE.parent), prefix=".alerthist_")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _HISTORY_STATE)
    except Exception:  # noqa: BLE001 — observability must never break a send
        log.debug("alert_history record failed", exc_info=True)


def _rate_limit_ok(text: str = "") -> bool:
    # Under pytest the guard is disabled: tests must be isolated and are never a real flood
    # source (the shared state file would otherwise leak counts across tests).
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
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


def flood_guard_ok(text: str = "") -> bool:
    """Public flood-guard check for callers that do their OWN HTTP send.

    Modules that POST to Telegram directly (with their own per-instance or env
    credentials) must still honour the shared cross-process rate limit. They
    call this BEFORE sending: ``False`` → drop the message (already logged).
    Disabled under pytest (see ``_rate_limit_ok``). Fail-open on guard error.
    """
    return _rate_limit_ok(text)


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
    text = payload_dict.get("text", "")
    # FLOOD GUARD: a shared cross-process rate limit so NO sender (any agent) can flood
    # Telegram. Excess messages are DROPPED + logged with a preview (identifies the flooder).
    if not _rate_limit_ok(text):
        _record_history(text, ok=False, error="flood_guard_dropped")
        return False
    try:
        token = get_bot_token()
        chat_id = get_chat_id()
    except EnvironmentError as exc:
        log.warning("Telegram send skipped: %s", exc)
        _record_history(text, ok=False, error=str(exc))
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
                    msg_id = None
                    try:
                        body = json.loads(resp.read().decode("utf-8"))
                        msg_id = (body.get("result") or {}).get("message_id")
                    except Exception:  # noqa: BLE001 — body parse is best-effort
                        pass
                    _record_history(text, ok=True, message_id=msg_id)
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
            _record_history(text, ok=False, error=f"HTTP {exc.code}: {exc.reason}")
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
        except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
            last_err = exc

    log.warning("Telegram send failed after %d attempt(s): %s", 1 + RETRIES, last_err)
    _record_history(text, ok=False, error=str(last_err))
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
