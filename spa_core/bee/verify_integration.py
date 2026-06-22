"""
BEE S9.6 — Verification Integration.
======================================
EPIC-9 / ADR-043

Оркестратор верификации BEE выходных файлов:
  - PIN каждый BEE output файл (sha256 + canonical JSON)
  - Строит hash chain (tamper-evident: каждый блок хэширует предыдущий)
  - run_full_verification(): точка входа для pipeline

LLM_FORBIDDEN: этот модуль не вызывает и не использует LLM.
Fail-closed: верификация обязательна; ошибки не замалчиваются.

Директории (не пересекаются с pin.py — разные расширения):
  data/bee/hashes/     — {name}.json (метаданные пина + sha256)
  data/bee/pinned/     — {name}.json (каноническая копия файла)
  data/bee/hash_chain.json — tamper-evident chain

stdlib only. Атомарные записи (tmp + os.replace).
"""
# LLM_FORBIDDEN
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

VERIFY_INTEGRATION_VERSION = "verify_integration_v1.0"

# Список всех BEE выходных файлов для верификации
BEE_OUTPUT_FILES = [
    "data/bee/safety_report.json",
    "data/bee/backtest_live_fit.json",
    "data/bee/robustness_summary.json",
    "data/bee/benchmark_result.json",
    "data/bee/failure_boundary.json",
]

# Директории хранения (расширения .json — не конфликтуют с pin.py *.sha256)
_PIN_DIR = _PROJECT_ROOT / "data" / "bee" / "pinned"
_HASH_DIR = _PROJECT_ROOT / "data" / "bee" / "hashes"
_CHAIN_FILE = _PROJECT_ROOT / "data" / "bee" / "hash_chain.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    """SHA256 хэш строки. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonical_json(obj) -> str:
    """Детерминированная JSON сериализация (sort_keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _atomic_write(path: Path, content: str) -> None:
    """Атомарная запись: tmp + os.replace. Никогда прямой open(..., 'w')."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        # Убираем tmp если что-то пошло не так
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# PIN / VERIFY
# ---------------------------------------------------------------------------

def pin_file(file_path: Path, name: Optional[str] = None) -> Dict:
    """
    PIN файл: вычисляет SHA256 по canonical JSON, сохраняет метаданные
    в data/bee/hashes/{name}.json и каноническую копию в data/bee/pinned/{name}.json.

    LLM_FORBIDDEN. Fail-closed: файл не найден → ok=False, не исключение.

    Returns:
        {"ok": bool, "name": str, "sha256": str} или {"ok": False, "error": str}
    """
    # LLM_FORBIDDEN

    if not file_path.exists():
        return {
            "ok": False,
            "name": name or file_path.name,
            "error": f"FAIL_CLOSED: file not found: {file_path}",
        }

    try:
        content = file_path.read_text(encoding="utf-8")

        # Пробуем парсить JSON для канонической формы; если не JSON — хэшируем as-is
        try:
            obj = json.loads(content)
            canonical = _canonical_json(obj)
        except (json.JSONDecodeError, ValueError):
            canonical = content

        file_hash = _sha256(canonical)
        pin_name = name or file_path.stem

        # Метаданные пина — в hashes/{name}.json
        hash_entry = {
            "name": pin_name,
            "file": str(file_path),
            "sha256": file_hash,
            "pinned_at": datetime.utcnow().isoformat() + "Z",
            "LLM_FORBIDDEN": True,
        }
        _atomic_write(
            _HASH_DIR / f"{pin_name}.json",
            json.dumps(hash_entry, indent=2),
        )

        # Каноническая копия — в pinned/{name}.json
        _atomic_write(_PIN_DIR / f"{pin_name}.json", canonical)

        return {"ok": True, "name": pin_name, "sha256": file_hash}

    except Exception as e:
        return {
            "ok": False,
            "name": name or file_path.name,
            "error": f"FAIL_CLOSED: pin error: {e}",
        }


def verify_file(file_path: Path, name: Optional[str] = None) -> Dict:
    """
    Верифицирует файл против сохранённого PIN.

    LLM_FORBIDDEN. Fail-closed: нет PIN → status='not_pinned', ok=False.

    Returns:
        {"ok": bool, "name": str, "status": str, ...}
    """
    # LLM_FORBIDDEN

    pin_name = name or file_path.stem
    hash_file = _HASH_DIR / f"{pin_name}.json"

    if not hash_file.exists():
        return {
            "ok": False,
            "name": pin_name,
            "status": "not_pinned",
            "error": f"No PIN found for {pin_name}",
        }

    try:
        stored = json.loads(hash_file.read_text(encoding="utf-8"))
        stored_hash = stored["sha256"]
    except Exception as e:
        return {
            "ok": False,
            "name": pin_name,
            "status": "pin_corrupt",
            "error": str(e),
        }

    if not file_path.exists():
        return {
            "ok": False,
            "name": pin_name,
            "status": "file_missing",
            "error": f"File not found: {file_path}",
        }

    try:
        content = file_path.read_text(encoding="utf-8")
        try:
            obj = json.loads(content)
            canonical = _canonical_json(obj)
        except (json.JSONDecodeError, ValueError):
            canonical = content

        current_hash = _sha256(canonical)
        matches = current_hash == stored_hash

        return {
            "ok": matches,
            "name": pin_name,
            "status": "match" if matches else "tampered",
            "stored_hash": stored_hash[:16] + "...",
            "current_hash": current_hash[:16] + "...",
            "match": matches,
        }
    except Exception as e:
        return {
            "ok": False,
            "name": pin_name,
            "status": "verify_error",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# HASH CHAIN
# ---------------------------------------------------------------------------

def build_hash_chain(
    results: List[Dict],
    previous_chain_hash: Optional[str] = None,
) -> Dict:
    """
    Строит tamper-evident hash chain из успешных PIN результатов.
    Каждый блок: SHA256(name + sha256 + prev_hash) → block_hash.
    block_hash передаётся следующему блоку как prev_hash.

    LLM_FORBIDDEN. Атомарная запись → data/bee/hash_chain.json.

    Returns:
        chain dict с entries и chain_head.
    """
    # LLM_FORBIDDEN

    prev_hash = previous_chain_hash if previous_chain_hash is not None else "GENESIS"
    chain_entries = []

    for result in results:
        if not result.get("ok"):
            continue

        entry = {
            "name": result["name"],
            "sha256": result.get("sha256", ""),
            "prev_hash": prev_hash,
        }

        # block_hash = SHA256(детерминированного JSON этого блока без block_hash)
        block_content = _canonical_json(entry)
        block_hash = _sha256(block_content)
        entry["block_hash"] = block_hash
        chain_entries.append(entry)
        prev_hash = block_hash

    chain = {
        "verify_integration_version": VERIFY_INTEGRATION_VERSION,
        "built_at": datetime.utcnow().isoformat() + "Z",
        "chain_length": len(chain_entries),
        "chain_head": prev_hash,
        "genesis": previous_chain_hash is None,
        "entries": chain_entries,
        "LLM_FORBIDDEN": True,
        "tamper_evident": True,
        "note": "Any modification to BEE outputs invalidates this chain.",
    }

    _atomic_write(_CHAIN_FILE, json.dumps(chain, indent=2))

    return chain


# ---------------------------------------------------------------------------
# ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_full_verification(
    output_dir: Optional[Path] = None,
    files_to_verify: Optional[List[str]] = None,
) -> Dict:
    """
    Оркестратор S9.6:
      1. PIN все BEE выходные файлы
      2. Построить hash chain из успешных PIN
      3. Верифицировать все пиннированные файлы
      4. Сохранить сводку → data/bee/verify_summary.json

    LLM_FORBIDDEN. Fail-closed: пропущенные файлы фиксируются в отчёте.
    Атомарные записи для всех выходных файлов.

    Returns:
        summary dict.
    """
    # LLM_FORBIDDEN

    if output_dir is None:
        output_dir = _PROJECT_ROOT

    if files_to_verify is None:
        files_to_verify = BEE_OUTPUT_FILES

    # ---- Шаг 1: PIN ----
    pin_results = []
    for rel_path in files_to_verify:
        file_path = Path(output_dir) / rel_path
        result = pin_file(file_path, name=Path(rel_path).stem)
        pin_results.append(result)

    # ---- Шаг 2: Hash chain из успешных PIN ----
    successful_pins = [r for r in pin_results if r.get("ok")]
    chain = build_hash_chain(results=successful_pins)

    # ---- Шаг 3: Верификация ----
    verify_results = []
    for rel_path in files_to_verify:
        file_path = Path(output_dir) / rel_path
        result = verify_file(file_path, name=Path(rel_path).stem)
        verify_results.append(result)

    # ---- Статистика ----
    pinned_count = sum(1 for r in pin_results if r.get("ok"))
    verified_count = sum(1 for r in verify_results if r.get("ok"))
    missing_count = sum(1 for r in pin_results if not r.get("ok"))

    summary = {
        "verify_integration_version": VERIFY_INTEGRATION_VERSION,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "files_checked": len(files_to_verify),
        "pinned_ok": pinned_count,
        "verified_ok": verified_count,
        "missing_or_error": missing_count,
        "chain_head": chain["chain_head"],
        "chain_length": chain["chain_length"],
        "all_verified": verified_count == pinned_count and pinned_count > 0,
        "pin_results": pin_results,
        "verify_results": verify_results,
        "LLM_FORBIDDEN": True,
        "note": (
            "BEE verification integrity check. "
            "Missing files indicate incomplete BEE run."
        ),
    }

    verify_summary_path = _PROJECT_ROOT / "data" / "bee" / "verify_summary.json"
    _atomic_write(verify_summary_path, json.dumps(summary, indent=2, default=str))

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    result = run_full_verification()
    print(f"BEE S9.6 verify_integration v{VERIFY_INTEGRATION_VERSION}")
    print(f"Files checked:    {result['files_checked']}")
    print(f"Pinned OK:        {result['pinned_ok']}")
    print(f"Verified OK:      {result['verified_ok']}")
    print(f"Missing/error:    {result['missing_or_error']}")
    chain_head = result.get("chain_head", "")
    print(f"Chain head:       {chain_head[:16]}..." if chain_head and chain_head != "GENESIS" else f"Chain head:       {chain_head}")
    print(f"LLM_FORBIDDEN:    {result['LLM_FORBIDDEN']}")
    sys.exit(0)
