"""Чтение plist БЕЗ возможности записи — для диагностики флота launchd.

Инцидент 01.11: `plutil -extract <ключ> json <файл>` без `-o -` пишет результат ПОВЕРХ входного файла; так два живых
plist флота превратились в JSON-фрагменты. Диагностика читает plist только отсюда (файл открывается в режиме `rb`,
записи в модуле нет) или `plutil -p`. Только stdlib.
"""
from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any, Optional


class PlistUnreadable(ValueError):
    pass


def read_plist(path) -> dict:
    try:
        with open(Path(path), "rb") as fh:
            doc = plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise PlistUnreadable(f"{path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(doc, dict):
        raise PlistUnreadable(f"{path}: корень plist не словарь")
    return doc


def extract(path, key: str) -> Optional[Any]:
    """Значение ключа верхнего уровня или ``None`` — без записи куда-либо."""
    return read_plist(path).get(key)
