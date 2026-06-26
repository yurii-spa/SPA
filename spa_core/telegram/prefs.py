#!/usr/bin/env python3
"""Per-chat user preferences for the interactive SPA Telegram bot.

Persisted atomically to ``data/telegram/user_prefs.json`` (per the UX doc's
Settings screen: language EN|RU, daily/weekly digest toggles, warning level,
mute). Stdlib only, fail-closed (defaults on any read error), deterministic.

Shape::

    {
      "<chat_id>": {
        "lang": "en"|"ru",
        "daily": true|false,
        "weekly": true|false,
        "warnings": "all"|"critical"|"off",
        "mute_until": <epoch_seconds or 0>
      }
    }
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from spa_core.utils.atomic import atomic_save

BASE_DIR = Path(__file__).resolve().parents[2]
PREFS_FILE = BASE_DIR / "data" / "telegram" / "user_prefs.json"

DEFAULTS: Dict[str, Any] = {
    "lang": "en",
    "daily": True,
    "weekly": True,
    "warnings": "critical",  # all | critical | off
    "mute_until": 0,
}


def _read_all(path: Path = None) -> Dict[str, Any]:
    """Read the whole prefs map. Returns {} on any error (fail-closed)."""
    path = path or PREFS_FILE  # resolve at call time (monkeypatch-friendly)
    try:
        if not path.exists():
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (ValueError, OSError):
        return {}


def get_prefs(chat_id: str, path: Path = None) -> Dict[str, Any]:
    """Return the merged-with-defaults prefs for one chat. Never raises."""
    out = dict(DEFAULTS)
    row = _read_all(path).get(str(chat_id))
    if isinstance(row, dict):
        for k in DEFAULTS:
            if k in row:
                out[k] = row[k]
    return out


def get_lang(chat_id: str, path: Path = None) -> str:
    lang = get_prefs(chat_id, path).get("lang", "en")
    return lang if lang in ("en", "ru") else "en"


def set_pref(chat_id: str, key: str, value: Any, path: Path = None) -> Dict[str, Any]:
    """Set one preference key for a chat and persist atomically.

    Returns the updated merged prefs for that chat. Never raises.
    """
    path = path or PREFS_FILE  # resolve at call time (monkeypatch-friendly)
    if key not in DEFAULTS:
        return get_prefs(chat_id, path)
    allp = _read_all(path)
    row = allp.get(str(chat_id))
    if not isinstance(row, dict):
        row = {}
    row[key] = value
    allp[str(chat_id)] = row
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(allp, str(path))
    except Exception:
        pass  # fail-closed: a write error must not crash the bot
    return get_prefs(chat_id, path)


def toggle_lang(chat_id: str, path: Path = None) -> str:
    """Flip EN ⇄ RU, persist, return the new language."""
    cur = get_lang(chat_id, path)
    new = "ru" if cur == "en" else "en"
    set_pref(chat_id, "lang", new, path)
    return new


def is_muted(chat_id: str, now: float = None, path: Path = None) -> bool:
    now = time.time() if now is None else now
    mu = get_prefs(chat_id, path).get("mute_until", 0)
    try:
        return float(mu) > now
    except (TypeError, ValueError):
        return False
