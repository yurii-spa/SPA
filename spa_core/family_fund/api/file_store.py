"""Thread-safe, async-friendly чтение SPA data/*.json.

FastAPI async-эндпоинты не делают блокирующий open() напрямую — это заблокирует
event loop. Чтение идёт через asyncio.to_thread() + TTL-кэш. Запись делает
cycle_runner атомарно (tmp + os.replace), поэтому читатель всегда видит целый файл.

Защита от path traversal: читать можно только внутри data/.
"""
from __future__ import annotations

import asyncio
import glob as _glob
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("family_fund.file_store")

_CACHE_TTL = 5.0  # секунд

_cache: dict[str, tuple[Any, float]] = {}
_cache_lock = threading.Lock()

# Корень репозитория: spa_core/family_fund/api/file_store.py → ../../../..
_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _data_dir() -> Path:
    return (_BASE_DIR / "data").resolve()


def _allowed_path(name: str) -> Path:
    """Резолвит имя файла внутри data/ и блокирует path traversal."""
    # принимаем как 'foo.json', так и 'data/foo.json'
    rel = name[5:] if name.startswith("data/") else name
    resolved = (_data_dir() / rel).resolve()
    allowed = _data_dir()
    if not (resolved == allowed or str(resolved).startswith(str(allowed) + "/")):
        raise ValueError(f"Path traversal attempt: {name!r}")
    return resolved


def _read_json_sync(name: str) -> Any:
    """Синхронное чтение с TTL-кэшем (запускается в thread pool)."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(name)
        if cached is not None and now < cached[1]:
            return cached[0]

    file_path = _allowed_path(name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("Data file not found: %s", name)
        data = {}
    except json.JSONDecodeError as e:
        # файл может быть в процессе записи — отдаём пусто вместо 500
        logger.error("JSON decode error in %s: %s", name, e)
        data = {}

    with _cache_lock:
        _cache[name] = (data, now + _CACHE_TTL)
    return data


async def read_json_file(name: str) -> Any:
    """Async-friendly чтение JSON. Не блокирует event loop."""
    return await asyncio.to_thread(_read_json_sync, name)


def read_json_sync(name: str) -> Any:
    """Синхронный вариант (для тестов / не-async кода)."""
    return _read_json_sync(name)


def list_data_files(pattern: str) -> list[str]:
    """Возвращает отсортированные basename'ы файлов data/, подходящих под glob.

    pattern — только basename-glob, напр. 'daily_report_*.json'.
    """
    if "/" in pattern or ".." in pattern:
        raise ValueError(f"Invalid pattern: {pattern!r}")
    matches = _glob.glob(str(_data_dir() / pattern))
    return sorted(Path(m).name for m in matches)


def invalidate_cache(name: str | None = None) -> None:
    """Сбрасывает TTL-кэш (тесты / форс-обновление)."""
    with _cache_lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)


def set_base_dir(path: Path) -> None:
    """Переопределяет корень репозитория (используется в тестах)."""
    global _BASE_DIR
    _BASE_DIR = Path(path).resolve()
    invalidate_cache()
