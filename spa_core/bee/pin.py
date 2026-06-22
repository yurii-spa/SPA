"""
BEE pin.py — Пиннинг входных данных + сиды + хэш результата
=============================================================
EPIC-9 / ADR-043

LLM_FORBIDDEN: этот модуль не вызывает и не использует никаких LLM-вызовов
Обеспечивает воспроизводимость BEE результатов:
  - pin_data(): сохраняет входные данные + сид + SHA256 хэш
  - verify_pin(): проверяет, что pinned данные не изменились
  - hash_result(): хэш результата BEE для якорения/подписи

Директории:
  data/bee/pinned/   — пинированные данные (*.json, *.manifest.json)
  data/bee/hashes/   — хэши (*.sha256, result_*.sha256)

stdlib only. Атомарные записи.
"""
# LLM_FORBIDDEN
import json
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_BEE = _PROJECT_ROOT / "data" / "bee"
_PINNED_DIR = _DATA_BEE / "pinned"
_HASHES_DIR = _DATA_BEE / "hashes"


def pin_data(name: str, data: Dict, seed: int = 42) -> Dict:
    """
    Пиннинг входных данных для воспроизводимого бэктеста.
    Записывает данные + сид + SHA256 хэш в data/bee/pinned/.

    Args:
        name: имя пина (идентификатор)
        data: входные данные для пиннинга
        seed: детерминированный сид (по умолчанию 42)

    Returns:
        pin manifest с content_hash
    """
    _PINNED_DIR.mkdir(parents=True, exist_ok=True)
    _HASHES_DIR.mkdir(parents=True, exist_ok=True)

    pinned_at = datetime.utcnow().isoformat() + "Z"

    payload = {
        "name": name,
        "seed": seed,
        "pinned_at": pinned_at,
        "data": data,
    }

    # Канонический JSON для детерминизма
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()

    manifest = {
        "name": name,
        "seed": seed,
        "content_hash": content_hash,
        "pinned_at": pinned_at,
        "canonical_bytes": len(canonical.encode()),
    }

    # Атомарная запись: данные
    pin_path = _PINNED_DIR / f"{name}.json"
    _atomic_write(pin_path, json.dumps(payload, indent=2))

    # Атомарная запись: хэш
    hash_path = _HASHES_DIR / f"{name}.sha256"
    _atomic_write(hash_path, content_hash + "\n")

    # Атомарная запись: манифест
    manifest_path = _PINNED_DIR / f"{name}.manifest.json"
    _atomic_write(manifest_path, json.dumps(manifest, indent=2))

    return manifest


def verify_pin(name: str) -> Dict:
    """
    Проверяет, что pinned данные не изменились.

    Returns:
        {"ok": bool, "name": str, "stored_hash": str, "actual_hash": str}
    """
    pin_path = _PINNED_DIR / f"{name}.json"
    hash_path = _HASHES_DIR / f"{name}.sha256"

    if not pin_path.exists():
        return {"ok": False, "name": name, "error": f"Pin not found: {name}"}

    # Перечитываем и пересчитываем хэш
    payload_bytes = pin_path.read_bytes()
    try:
        parsed = json.loads(payload_bytes)
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        actual_hash = hashlib.sha256(canonical.encode()).hexdigest()
    except Exception as e:
        return {"ok": False, "name": name, "error": f"Parse error: {e}"}

    stored_hash = hash_path.read_text().strip() if hash_path.exists() else None

    ok = actual_hash == stored_hash
    return {
        "ok": ok,
        "name": name,
        "stored_hash": stored_hash,
        "actual_hash": actual_hash,
        "verified_at": datetime.utcnow().isoformat() + "Z",
    }


def hash_result(result: Dict, name: str) -> str:
    """
    Вычисляет SHA256 хэш результата BEE и сохраняет в data/bee/hashes/.

    Args:
        result: результат BEE (dict)
        name: имя для файла хэша

    Returns:
        hex-строка SHA256
    """
    _HASHES_DIR.mkdir(parents=True, exist_ok=True)

    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(canonical.encode()).hexdigest()

    hash_path = _HASHES_DIR / f"result_{name}.sha256"
    _atomic_write(hash_path, h + "\n")

    return h


def _atomic_write(path: Path, content: str) -> None:
    """Атомарная запись: tmp + os.replace."""
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, str(path))
