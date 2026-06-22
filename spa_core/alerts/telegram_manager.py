"""spa_core/alerts/telegram_manager.py — Centralized Telegram notification manager.

ARCHITECTURE RULE: ALL Telegram sends (except legacy TelegramSender used by
cycle_runner's pre-existing code) must go through TelegramManager.send().
Never call urllib.request / requests directly in monitoring or analytics code.

Design:
  • Cooldown state persisted to data/telegram_cooldowns.json (atomic write).
    This survives process restarts — fixes the in-memory-only dedup bug.
  • Category-based cooldowns:
      "daily"     → 23 h  (daily reports; once per day)
      "milestone" → 4 h   (GoLive pass-count changes, track milestones)
      "p0"        → 0 s   (kill-switch, gap > 26 h, API down > 2 h — bypass all cooldowns)
      "alert"     → 1 h   (risk threshold breach, peg deviation, red flag)
      "debug"     → suppressed in production (only logs locally)
  • P0 category ALWAYS sends — no cooldown check.
  • Dedup key: sha256(category + ":" + title)[:16]  — same title in same
    category is suppressed until cooldown expires.
  • SECRETS POLICY: tokens read from macOS Keychain at send time; never stored.
  • STDLIB ONLY: json, os, hashlib, subprocess, urllib.request, datetime, pathlib.
  • LLM FORBIDDEN per CLAUDE.md (monitoring domain).
  • All disk writes are atomic (tmp + os.replace).

Usage:
    from spa_core.alerts.telegram_manager import TelegramManager
    mgr = TelegramManager()
    mgr.send("🚨 Kill-switch triggered", title="kill_switch", category="p0")
    mgr.send("Daily digest", title="daily_summary", category="daily")

CLI (dry-run / status):
    python3 -m spa_core.alerts.telegram_manager --status
    python3 -m spa_core.alerts.telegram_manager --dry-run --category p0 --title test --message "hi"
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.alerts.telegram_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_COOLDOWN_FILE = _DEFAULT_DATA_DIR / "telegram_cooldowns.json"

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Default cooldown per category (seconds).  P0 → 0 means no cooldown.
CATEGORY_COOLDOWNS: Dict[str, int] = {
    "daily":     23 * 3600,   # 23 h — daily reports
    "milestone":  4 * 3600,   # 4 h  — go-live / track milestones
    "alert":      1 * 3600,   # 1 h  — risk/peg/red-flag alerts
    "p0":         0,           # bypass — kill-switch, gap, critical infra
    "debug":     -1,           # -1   — suppressed in production
}


# ---------------------------------------------------------------------------
# Keychain helpers
# ---------------------------------------------------------------------------

_KEYCHAIN_TOKEN_KEY = "TELEGRAM_BOT_TOKEN_SPA"
_KEYCHAIN_CHAT_KEY  = "TELEGRAM_CHAT_ID_SPA"


def _keychain_get(key: str) -> Optional[str]:
    """Read a secret from macOS Keychain. Returns None on any error."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", key, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            return value if value else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Cooldown state helpers (disk-persisted, atomic)
# ---------------------------------------------------------------------------

def _utc_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _load_cooldown_state(path: Path) -> Dict[str, float]:
    """Load cooldown state {dedup_key: last_sent_ts}. Returns {} on any error."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: float(v) for k, v in data.items()
                        if isinstance(v, (int, float))}
    except Exception as exc:
        log.warning("telegram_cooldowns.json unreadable (%s) — starting fresh", exc)
    return {}


def _save_cooldown_state(path: Path, state: Dict[str, float]) -> None:
    """Atomically write cooldown state. Silent on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(state, str(path))
    except Exception as exc:
        log.warning("telegram_cooldowns.json write failed (%s) — dedup not persisted", exc)


def _dedup_key(category: str, title: str) -> str:
    """Short deterministic key for (category, title) pair."""
    raw = f"{category}:{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# TelegramManager
# ---------------------------------------------------------------------------

class TelegramManager:
    """Centralized Telegram notification manager with disk-persisted cooldowns.

    Parameters
    ----------
    data_dir:
        Directory for telegram_cooldowns.json (defaults to data/).
    production:
        When False, "debug" category messages are sent (useful in tests).
        When True (default), "debug" messages are suppressed.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        *,
        production: bool = True,
    ) -> None:
        self._cooldown_file = (
            Path(data_dir) / "telegram_cooldowns.json"
            if data_dir is not None
            else _COOLDOWN_FILE
        )
        self._production = production

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        message: str,
        *,
        title: str,
        category: str = "alert",
        cooldown_override_hours: Optional[float] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a Telegram message, respecting cooldown rules.

        Parameters
        ----------
        message:
            Text of the Telegram message.
        title:
            Logical name of this alert type used for dedup (e.g. "peg_critical").
            Two calls with the same title+category within the cooldown window
            are suppressed.
        category:
            One of: "daily", "milestone", "alert", "p0", "debug".
        cooldown_override_hours:
            If given, overrides the default cooldown for this category.
        parse_mode:
            Telegram parse mode ("HTML" or "Markdown").

        Returns
        -------
        bool
            True if a message was actually sent to Telegram.
            False if suppressed by cooldown, debug suppression, or send error.
        """
        # 1. Resolve cooldown seconds
        if cooldown_override_hours is not None:
            cooldown_sec = int(cooldown_override_hours * 3600)
        else:
            cooldown_sec = CATEGORY_COOLDOWNS.get(category, 3600)

        # 2. "debug" category is suppressed in production
        if category == "debug" and self._production:
            log.debug("TelegramManager: [debug] suppressed in production — title=%s", title)
            return False

        # 3. "p0" always sends (no cooldown check)
        if category != "p0" and cooldown_sec > 0:
            state = _load_cooldown_state(self._cooldown_file)
            key = _dedup_key(category, title)
            last_sent = state.get(key)
            now = _utc_now()
            if last_sent is not None and (now - last_sent) < cooldown_sec:
                remaining_min = int((cooldown_sec - (now - last_sent)) / 60)
                log.debug(
                    "TelegramManager: cooldown active for [%s/%s] — "
                    "%d min remaining, suppressing",
                    category, title, remaining_min,
                )
                return False

        # 4. Load credentials from Keychain
        token   = _keychain_get(_KEYCHAIN_TOKEN_KEY)
        chat_id = _keychain_get(_KEYCHAIN_CHAT_KEY)
        if not token or not chat_id:
            log.warning(
                "TelegramManager: Keychain credentials missing "
                "(keys: %s, %s) — message not sent",
                _KEYCHAIN_TOKEN_KEY, _KEYCHAIN_CHAT_KEY,
            )
            return False

        # 5. Send
        sent = self._send_raw(token, chat_id, message, parse_mode)

        # 6. Record timestamp on success
        if sent:
            state = _load_cooldown_state(self._cooldown_file)
            key = _dedup_key(category, title)
            state[key] = _utc_now()
            _save_cooldown_state(self._cooldown_file, state)
            log.info(
                "TelegramManager: sent [%s/%s] (cooldown=%ds)",
                category, title, cooldown_sec,
            )
        else:
            log.warning(
                "TelegramManager: send failed for [%s/%s]", category, title
            )

        return sent

    def is_in_cooldown(self, *, title: str, category: str) -> bool:
        """Return True if this title/category is currently within its cooldown window."""
        cooldown_sec = CATEGORY_COOLDOWNS.get(category, 3600)
        if category == "p0" or cooldown_sec <= 0:
            return False
        state = _load_cooldown_state(self._cooldown_file)
        key = _dedup_key(category, title)
        last_sent = state.get(key)
        if last_sent is None:
            return False
        return (_utc_now() - last_sent) < cooldown_sec

    def cooldown_remaining_minutes(self, *, title: str, category: str) -> int:
        """Return minutes remaining in cooldown (0 if not in cooldown)."""
        cooldown_sec = CATEGORY_COOLDOWNS.get(category, 3600)
        if category == "p0" or cooldown_sec <= 0:
            return 0
        state = _load_cooldown_state(self._cooldown_file)
        key = _dedup_key(category, title)
        last_sent = state.get(key)
        if last_sent is None:
            return 0
        elapsed = _utc_now() - last_sent
        remaining = cooldown_sec - elapsed
        return max(0, int(remaining / 60))

    def status(self) -> dict:
        """Return current cooldown state (for --status CLI and health checks)."""
        state = _load_cooldown_state(self._cooldown_file)
        now = _utc_now()
        result: dict = {}
        for raw_key, last_ts in state.items():
            elapsed_min = int((now - last_ts) / 60)
            result[raw_key] = {
                "last_sent_at": datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat(),
                "elapsed_minutes": elapsed_min,
            }
        return result

    # ------------------------------------------------------------------
    # Internal send
    # ------------------------------------------------------------------

    @staticmethod
    def _send_raw(token: str, chat_id: str, text: str, parse_mode: str) -> bool:
        """POST to Telegram Bot API. Returns True on success. Never raises."""
        url = _TELEGRAM_API.format(token=token)
        payload = json.dumps({
            "chat_id":                  chat_id,
            "text":                     text,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": True,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            log.error("TelegramManager HTTP error %d: %s", exc.code, body[:200])
            return False
        except Exception as exc:
            log.error("TelegramManager send error: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Module-level convenience instance (lazy, singleton-like)
# ---------------------------------------------------------------------------

_default_manager: Optional[TelegramManager] = None


def get_manager(data_dir: Optional[Path] = None) -> TelegramManager:
    """Return the default TelegramManager instance (created once)."""
    global _default_manager
    if _default_manager is None:
        _default_manager = TelegramManager(data_dir=data_dir)
    return _default_manager


def send(
    message: str,
    *,
    title: str,
    category: str = "alert",
    cooldown_override_hours: Optional[float] = None,
    parse_mode: str = "HTML",
) -> bool:
    """Module-level shortcut: TelegramManager().send(...)"""
    return get_manager().send(
        message,
        title=title,
        category=category,
        cooldown_override_hours=cooldown_override_hours,
        parse_mode=parse_mode,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="TelegramManager CLI — check cooldown state or send a test message.",
    )
    sub = parser.add_subparsers(dest="cmd")

    # --status
    sub.add_parser("--status", help="Print current cooldown state")
    parser.add_argument("--status", action="store_true", help="Print cooldown state")

    # --dry-run send
    parser.add_argument("--dry-run",  action="store_true", help="Check cooldown without sending")
    parser.add_argument("--category", default="alert", help="Category (daily/milestone/alert/p0/debug)")
    parser.add_argument("--title",    default="test_message", help="Alert title for dedup")
    parser.add_argument("--message",  default="SPA TelegramManager test", help="Message text")

    args = parser.parse_args(argv)

    mgr = TelegramManager()

    if args.status:
        state = mgr.status()
        if not state:
            print("No cooldown state recorded yet.")
        else:
            print("Current cooldown state:")
            for key, info in state.items():
                print(f"  {key}: last={info['last_sent_at']}  elapsed={info['elapsed_minutes']}m")
        return 0

    in_cd = mgr.is_in_cooldown(title=args.title, category=args.category)
    remaining = mgr.cooldown_remaining_minutes(title=args.title, category=args.category)

    if in_cd:
        print(
            f"[{args.category}/{args.title}] In cooldown — {remaining} min remaining. "
            "Would NOT send."
        )
        if args.dry_run:
            return 0
    else:
        print(f"[{args.category}/{args.title}] Cooldown clear. Would send.")

    if args.dry_run:
        print(f"[dry-run] Message:\n{args.message}")
        return 0

    ok = mgr.send(args.message, title=args.title, category=args.category)
    if ok:
        print(f"✅ Sent [{args.category}/{args.title}]")
        return 0
    else:
        print(f"❌ Send failed or suppressed [{args.category}/{args.title}]")
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(_main())
