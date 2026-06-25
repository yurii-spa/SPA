"""
spa_core/monitoring/telegram_watcher.py
==========================================
SPA Telegram Alert Watcher — autonomous error detection & auto-fix trigger.

Reads Telegram messages via getUpdates, detects CRITICAL/ERROR/❌/⚠️ patterns,
deduplicates via SHA-1, enforces cooldowns, then invokes auto_fixer.

Run via launchd every 5 min:
    python3 -m spa_core.monitoring.telegram_watcher

Design constraints:
  - STDLIB ONLY (urllib, hashlib, json, subprocess)
  - FAIL-SAFE — every network/IO call wrapped in try/except
  - READ/WRITE: data/telegram_last_update_id.json
  - Dedup files: /tmp/spa_tw_seen_{hash}  (TTL 24 h)
  - Cooldown: /tmp/spa_tw_cooldown_{hash}  (TTL 30 min)
  - LLM calls delegated to auto_fixer.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Module-level import of run_auto_fix so tests can monkeypatch
# spa_core.monitoring.telegram_watcher.run_auto_fix directly.
try:
    from spa_core.devtools.auto_fixer import run_auto_fix  # noqa: F401
except ImportError:
    def run_auto_fix(alert_text: str, **kwargs) -> bool:  # type: ignore[misc]
        """Fallback stub — auto_fixer not available."""
        return False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("spa.monitoring.telegram_watcher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root (spa_core/monitoring/→spa_core/→root)
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"
KEYCHAIN_ACCOUNT = "spa"

OFFSET_FILE = DATA_DIR / "telegram_last_update_id.json"
DEDUP_TTL_SEC = 86_400        # 24 hours
COOLDOWN_TTL_SEC = 1_800      # 30 minutes
MAX_MESSAGE_AGE_SEC = 7_200   # 2 hours
TMP_PREFIX_SEEN = "/tmp/spa_tw_seen_"
TMP_PREFIX_COOLDOWN = "/tmp/spa_tw_cooldown_"

# Alert detection patterns (case-insensitive substring checks + exact)
ALERT_PATTERNS = [
    "CRITICAL",
    "ERROR",
    "❌",
    "⚠️",
    "FAILED",
    "Exception",
    "Traceback",
]

# Daily summary / APY report keywords — these should NOT trigger auto-fix
SKIP_PATTERNS = [
    "Daily Summary",
    "APY Report",
    "Morning Report",
    "Weekly Report",
    "Portfolio Summary",
    "daily report",
    "📊 Daily",
    "📈 APY",
    "📅 Week",
]

HTTP_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Keychain helpers (same pattern as spa_core/telegram/bot.py)
# ---------------------------------------------------------------------------

def _read_keychain(service: str) -> Optional[str]:
    """Read one generic-password from macOS Keychain. None on any failure."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                return val
    except Exception:
        pass
    return None


def get_bot_token() -> Optional[str]:
    token = _read_keychain(TOKEN_SERVICE)
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get("TELEGRAM_BOT_TOKEN")
    return token


def get_chat_id() -> Optional[str]:
    cid = _read_keychain(CHAT_ID_SERVICE)
    if not cid:
        cid = os.environ.get("TELEGRAM_CHAT_ID_SPA") or os.environ.get("TELEGRAM_CHAT_ID")
    return cid


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def _tg_request(token: str, method: str, payload: Optional[Dict] = None,
                timeout: int = HTTP_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Generic Telegram Bot API call. Returns parsed JSON or None."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("Telegram API %s failed: %s", method, exc)
        return None


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a message to Telegram. Returns True on success."""
    result = _tg_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }, timeout=15)
    ok = bool(result and result.get("ok"))
    if not ok:
        log.warning("send_telegram failed: %s", result)
    return ok


def get_updates(token: str, offset: Optional[int] = None,
                limit: int = 100) -> Optional[List[Dict]]:
    """Call getUpdates (no long-poll — just drain pending)."""
    params: Dict[str, Any] = {"limit": limit, "timeout": 0}
    if offset is not None:
        params["offset"] = offset
    result = _tg_request(token, "getUpdates", params, timeout=15)
    if result and result.get("ok"):
        return result.get("result", [])
    return None


# ---------------------------------------------------------------------------
# Offset persistence
# ---------------------------------------------------------------------------

def _load_offset() -> Optional[int]:
    try:
        if OFFSET_FILE.exists():
            data = json.loads(OFFSET_FILE.read_text())
            return int(data.get("offset", 0)) or None
    except Exception:
        pass
    return None


def _save_offset(offset: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OFFSET_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"offset": offset, "updated_at": datetime.now(timezone.utc).isoformat()}))
        tmp.replace(OFFSET_FILE)
    except Exception as exc:
        log.warning("Failed to save offset: %s", exc)


# ---------------------------------------------------------------------------
# Dedup & cooldown (file-based, /tmp)
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _is_seen(content_hash: str) -> bool:
    path = TMP_PREFIX_SEEN + content_hash
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    if age > DEDUP_TTL_SEC:
        try:
            os.unlink(path)
        except OSError:
            pass
        return False
    return True


def _mark_seen(content_hash: str) -> None:
    try:
        path = TMP_PREFIX_SEEN + content_hash
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _is_in_cooldown(content_hash: str) -> bool:
    path = TMP_PREFIX_COOLDOWN + content_hash
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    if age > COOLDOWN_TTL_SEC:
        try:
            os.unlink(path)
        except OSError:
            pass
        return False
    return True


def _start_cooldown(content_hash: str) -> None:
    try:
        path = TMP_PREFIX_COOLDOWN + content_hash
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Alert detection
# ---------------------------------------------------------------------------

def is_alert_message(text: str) -> bool:
    """Return True if the message contains an alert pattern."""
    for pattern in ALERT_PATTERNS:
        if pattern.lower() in text.lower() or pattern in text:
            return True
    return False


def is_daily_summary(text: str) -> bool:
    """Return True if the message looks like a routine daily summary/report.

    A traceback or exception in the text always takes precedence — even if a
    summary keyword is present, the message is treated as an alert.
    """
    # If there's a Python traceback or explicit exception → NOT a summary
    has_traceback = "Traceback" in text or "traceback" in text
    has_exception = "Exception" in text or "exception" in text
    if has_traceback or has_exception:
        return False

    # Known skip patterns: daily/weekly summary headers with no error context
    for pattern in SKIP_PATTERNS:
        if pattern.lower() in text.lower() or pattern in text:
            return True

    # Heuristic: no traceback/exception AND no error words → summary
    error_words = ["error", "failed", "critical", "❌"]
    has_error_word = any(w.lower() in text.lower() for w in error_words)
    if not has_error_word:
        return True

    return False


def parse_alert_type(text: str) -> str:
    """Identify the dominant error type from alert text."""
    if "ImportError" in text or "ModuleNotFoundError" in text:
        return "ImportError"
    if "FileNotFoundError" in text or "No such file or directory" in text:
        return "FileNotFoundError"
    if "AttributeError" in text:
        return "AttributeError"
    if "TypeError" in text:
        return "TypeError"
    if "ValueError" in text:
        return "ValueError"
    if "KeyError" in text:
        return "KeyError"
    if "NameError" in text:
        return "NameError"
    if "IndexError" in text:
        return "IndexError"
    if "RuntimeError" in text:
        return "RuntimeError"
    if "ConnectionError" in text or "TimeoutError" in text:
        return "NetworkError"
    if "CRITICAL" in text:
        return "CRITICAL"
    if "Traceback" in text or "Exception" in text:
        return "GenericException"
    return "ERROR"


def is_message_too_old(msg: Dict) -> bool:
    """Return True if the message is older than MAX_MESSAGE_AGE_SEC."""
    try:
        ts = msg.get("message", {}).get("date", 0)
        if not ts:
            return False  # can't determine age → process it
        age = time.time() - ts
        return age > MAX_MESSAGE_AGE_SEC
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core watcher logic
# ---------------------------------------------------------------------------

def process_updates(updates: List[Dict], token: str, chat_id: str) -> int:
    """Process a batch of Telegram updates. Returns count of fixes triggered."""
    fixes_triggered = 0
    for update in updates:
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            continue

        text = msg.get("text") or msg.get("caption") or ""
        if not text:
            continue

        # Skip messages older than 2 hours
        if is_message_too_old(update):
            log.debug("Skipping old message (age > %d s)", MAX_MESSAGE_AGE_SEC)
            continue

        # Must be an alert
        if not is_alert_message(text):
            continue

        # Skip daily summaries / APY reports
        if is_daily_summary(text):
            log.debug("Skipping daily summary message")
            continue

        # Dedup: skip if we've already seen this exact content recently
        content_hash = _content_hash(text)
        if _is_seen(content_hash):
            log.info("Duplicate alert skipped (hash=%s)", content_hash)
            continue

        # Cooldown: skip if we triggered a fix for similar content recently
        if _is_in_cooldown(content_hash):
            log.info("Cooldown active for hash=%s — skipping auto-fix", content_hash)
            continue

        # Mark seen immediately to prevent parallel runs from double-triggering
        _mark_seen(content_hash)

        alert_type = parse_alert_type(text)
        log.info("Alert detected: type=%s hash=%s", alert_type, content_hash)

        # Trigger auto-fix via module-level run_auto_fix (patchable in tests)
        try:
            fixed = run_auto_fix(text, token=token, chat_id=chat_id)
        except Exception as _fix_exc:
            log.error("auto_fixer error: %s", _fix_exc, exc_info=True)
            fixed = False
        except Exception as exc:
            log.error("auto_fixer error: %s", exc, exc_info=True)
            fixed = False

        if fixed:
            _start_cooldown(content_hash)
            fixes_triggered += 1

    return fixes_triggered


def run_once() -> None:
    """Single pass: drain getUpdates, process alerts, save offset."""
    token = get_bot_token()
    chat_id = get_chat_id()

    if not token:
        log.error(
            "ANTHROPIC_API_KEY / TELEGRAM_BOT_TOKEN not found in Keychain.\n"
            "Add via: security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w YOUR_TOKEN"
        )
        # Still try to run detection; just can't send confirmations
        return

    if not chat_id:
        log.warning("TELEGRAM_CHAT_ID_SPA not found — will detect but not confirm")

    offset = _load_offset()
    log.info("Polling getUpdates (offset=%s)", offset)

    updates = get_updates(token, offset=offset)
    if updates is None:
        log.error("getUpdates returned None — possible network/token issue")
        return

    if not updates:
        log.info("No new updates")
        return

    log.info("Got %d update(s)", len(updates))

    # Advance offset past all fetched updates regardless of processing result
    max_update_id = max(u["update_id"] for u in updates)
    _save_offset(max_update_id + 1)

    fixes = process_updates(updates, token=token or "", chat_id=chat_id or "")
    log.info("Done. Fixes triggered: %d", fixes)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.info("=== SPA Telegram Watcher starting ===")
    try:
        run_once()
    except Exception as exc:
        log.critical("Unhandled error in run_once: %s", exc, exc_info=True)
        sys.exit(1)
    log.info("=== SPA Telegram Watcher done ===")


if __name__ == "__main__":
    main()
