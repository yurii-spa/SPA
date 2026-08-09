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
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from spa_core.utils.atomic import atomic_save

BASE_DIR = Path(__file__).resolve().parents[2]
PREFS_FILE = BASE_DIR / "data" / "telegram" / "user_prefs.json"

#: Куда уходят записи под pytest, когда путь не задан явно (см. :func:`_prefs_path`).
PYTEST_PREFS_FILE = Path(tempfile.gettempdir()) / "spa_telegram_prefs_pytest.json"

#: Аварийный выход: тест, которому нужен ИМЕННО живой путь по умолчанию, ставит эту
#: переменную окружения. По умолчанию — нет: умолчание обязано быть безопасным.
LIVE_ENV_FLAG = "SPA_TELEGRAM_PREFS_LIVE"


def _live_path() -> Path:
    """Живой путь по умолчанию, вычисляемый ИЗ ``BASE_DIR`` (а не из константы).

    Так подмена ``BASE_DIR`` в тесте остаётся «умолчанием этого дерева», а не читается
    как осознанное перенаправление — иначе тест, воспроизводящий аварию, невозможно
    отличить от теста, который сам себе задал путь.
    """
    return BASE_DIR / "data" / "telegram" / "user_prefs.json"


def _prefs_path(override: Path = None) -> Path:
    """Файл настроек. Под pytest — ВСЕГДА временный, если путь не задан явно.

    Урок инцидента «тесты пишут в живое состояние» (тот же, из-за которого
    :func:`spa_core.telegram.alert_actions._state_path` уводит журнал в tempdir):
    в живом ``data/telegram/user_prefs.json`` 26.06 осели chat_id ``424242`` и
    ``999999`` — константы ``OWNER`` и ``STRANGER`` из тест-файлов, причём у одного
    из них проставлен ``mute_until``, то есть прогон тестов ЗАГЛУШИЛ чат в живых
    настройках. Раньше это ловилось только тем, что автор теста вспомнит про
    подмену пути; теперь безопасен сам модуль.

    Порядок разрешения:

    1. явный ``override`` — сильнее всего (аргумент ``path=`` у всех функций);
    2. ``PREFS_FILE``, отличающийся от умолчания дерева, — осознанное
       перенаправление (``monkeypatch.setattr(prefs, "PREFS_FILE", …)``), уважается;
    3. под pytest — ``PYTEST_PREFS_FILE`` (кроме случая, когда выставлен
       :data:`LIVE_ENV_FLAG`);
    4. иначе — живой путь.
    """
    if override is not None:
        return Path(override)
    live = _live_path()
    if Path(PREFS_FILE) != live:
        return Path(PREFS_FILE)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(LIVE_ENV_FLAG):
        return PYTEST_PREFS_FILE
    return live

# Язык по умолчанию — РУССКИЙ. У бота один адресат, и он русскоязычный (директива владельца
# «писать мне в чат простым языком»). Английское умолчание было не нейтральным выбором, а
# дефектом: chat_id владельца в файле настроек отсутствовал, поэтому весь интерфейс приходил
# ему по-английски — при том, что все тексты давно переведены. Замер 2026-08-08.
DEFAULTS: Dict[str, Any] = {
    "lang": "ru",
    "daily": True,
    "weekly": True,
    "warnings": "critical",  # all | critical | off
    "mute_until": 0,
}


def _read_all(path: Path = None) -> Dict[str, Any]:
    """Read the whole prefs map. Returns {} on any error (fail-closed)."""
    path = _prefs_path(path)  # resolve at call time (monkeypatch-friendly)
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
    """Язык чата. Умолчание берётся из ``DEFAULTS``, а НЕ дублируется литералом здесь:
    вторая копия умолчания — это способ сменить его в одном месте и не заметить, что в
    другом оно осталось прежним."""
    default = DEFAULTS["lang"]
    lang = get_prefs(chat_id, path).get("lang", default)
    return lang if lang in ("en", "ru") else default


def set_pref(chat_id: str, key: str, value: Any, path: Path = None) -> Dict[str, Any]:
    """Set one preference key for a chat and persist atomically.

    Returns the updated merged prefs for that chat. Never raises.
    """
    path = _prefs_path(path)  # resolve at call time (monkeypatch-friendly)
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
