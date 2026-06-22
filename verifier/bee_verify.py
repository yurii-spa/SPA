#!/usr/bin/env python3
"""
BEE Independent Verifier — standalone, без импортов spa_core.
==============================================================
EPIC-9 / ADR-043

S9.3: verify_result_hash / verify_event_catalog / verify_safety_report
S9.6: verify_one (новый PIN-формат) / verify_chain (hash chain) / verify_all

Запускается НЕЗАВИСИМО от основного кода (не импортирует spa_core).
LLM_FORBIDDEN: нет вызовов AI.

Использование:
  python3 verifier/bee_verify.py --all
  python3 verifier/bee_verify.py --name safety_report
  python3 verifier/bee_verify.py --chain
  python3 verifier/bee_verify.py --catalog
  python3 verifier/bee_verify.py --report
  python3 verifier/bee_verify.py --name safety_report --repo /path/to/repo
"""
# LLM_FORBIDDEN
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Пути (S9.6 — standalone константы, не зависят от spa_core)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
_HASH_DIR = _ROOT / "data" / "bee" / "hashes"
_PIN_DIR = _ROOT / "data" / "bee" / "pinned"
_CHAIN_FILE = _ROOT / "data" / "bee" / "hash_chain.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    """LLM_FORBIDDEN: deterministic SHA256."""
    # LLM_FORBIDDEN
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    """Детерминированная JSON сериализация."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# S9.3 functions (backward compat — не изменяются)
# ---------------------------------------------------------------------------

def verify_result_hash(name: str, repo_root: Path) -> Dict:
    """
    S9.3: Верифицирует SHA256 хэш сохранённого результата BEE.

    Читает result_<name>.sha256 из data/bee/hashes/ и
    проверяет против pinned данных в data/bee/pinned/<name>.json.

    Returns:
        {"ok": bool | None, ...}
    """
    hashes_dir = repo_root / "data" / "bee" / "hashes"
    pinned_dir = repo_root / "data" / "bee" / "pinned"

    result_hash_file = hashes_dir / f"result_{name}.sha256"
    if not result_hash_file.exists():
        return {
            "name": name,
            "ok": None,
            "note": "No result hash stored yet (run BEE first)",
        }

    stored_hash = result_hash_file.read_text().strip()

    pin_file_path = pinned_dir / f"{name}.json"
    if not pin_file_path.exists():
        return {
            "name": name,
            "ok": False,
            "error": f"Pin file not found: {pin_file_path}",
            "stored_hash": stored_hash,
        }

    try:
        payload = json.loads(pin_file_path.read_bytes())
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        actual_hash = hashlib.sha256(canonical.encode()).hexdigest()
    except Exception as e:
        return {
            "name": name,
            "ok": False,
            "error": f"Parse/hash error: {e}",
            "stored_hash": stored_hash,
        }

    ok = actual_hash == stored_hash
    return {
        "name": name,
        "ok": ok,
        "stored_hash": stored_hash,
        "actual_hash": actual_hash,
    }


def verify_event_catalog(repo_root: Path) -> Dict:
    """
    S9.3: Проверяет целостность event_catalog.json.

    Returns:
        {"ok": bool, "events_count": int, ...}
    """
    catalog_path = repo_root / "data" / "bee" / "event_catalog.json"
    if not catalog_path.exists():
        return {"ok": False, "error": "event_catalog.json not found"}

    try:
        data = json.loads(catalog_path.read_text())
        events = data.get("events", [])
        required_fields = {
            "event_id", "name", "window_start", "window_end",
            "affected_assets", "stress_type", "expected_gate_reaction", "severity",
        }
        issues = []
        for event in events:
            missing = required_fields - set(event.keys())
            if missing:
                issues.append(f"Event {event.get('event_id', '?')}: missing {missing}")

        return {
            "ok": len(issues) == 0,
            "events_count": len(events),
            "issues": issues,
            "catalog_version": data.get("version", "unknown"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def verify_safety_report(repo_root: Path) -> Dict:
    """
    S9.3: Проверяет safety_report.json: наличие caveat, честность framing.

    Returns:
        {"ok": bool, "issues": list}
    """
    report_path = repo_root / "data" / "bee" / "safety_report.json"
    if not report_path.exists():
        return {"ok": None, "note": "safety_report.json not found (run BEE first)"}

    try:
        data = json.loads(report_path.read_text())
        issues = []

        # Проверяем caveat
        caveat = data.get("caveat", "")
        if len(caveat) < 20:
            issues.append("caveat слишком короткий или отсутствует")
        if "guarantee" in caveat.lower() and "no guarantee" not in caveat.lower():
            issues.append("caveat содержит 'guarantee' без отрицания")

        # Проверяем data_source
        if data.get("data_source") not in ("modeled", "real-data"):
            issues.append(f"data_source невалидный: {data.get('data_source')}")

        # Проверяем события
        events = data.get("events", [])
        if len(events) < 4:
            issues.append(f"Мало событий в отчёте: {len(events)} < 4")

        return {
            "ok": len(issues) == 0,
            "events_analyzed": data.get("total_events_analyzed", 0),
            "false_positives": data.get("false_positives", 0),
            "data_source": data.get("data_source", "unknown"),
            "issues": issues,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# S9.6 functions — verify_one / verify_chain / verify_all
# ---------------------------------------------------------------------------

def verify_one(name: str, repo_root: Optional[Path] = None) -> Dict:
    """
    S9.6: Верифицирует один PIN по новому формату (hashes/{name}.json).

    Независим от spa_core. Использует _HASH_DIR и _PIN_DIR или repo_root.
    LLM_FORBIDDEN. Fail-closed: нет PIN → status='no_pin', ok=False.

    Returns:
        {"ok": bool, "name": str, "status": str, ...}
    """
    # LLM_FORBIDDEN

    hash_dir = (repo_root / "data" / "bee" / "hashes") if repo_root else _HASH_DIR
    pin_dir = (repo_root / "data" / "bee" / "pinned") if repo_root else _PIN_DIR

    hash_file = hash_dir / f"{name}.json"

    if not hash_file.exists():
        return {
            "ok": False,
            "name": name,
            "status": "no_pin",
            "msg": f"No hash file for {name}",
        }

    try:
        stored = json.loads(hash_file.read_text(encoding="utf-8"))
        stored_hash = stored["sha256"]
    except Exception as e:
        return {
            "ok": False,
            "name": name,
            "status": "hash_corrupt",
            "msg": str(e),
        }

    # Ищем файл: сначала pinned копия, потом оригинал
    pin_copy = pin_dir / f"{name}.json"
    if pin_copy.exists():
        content = pin_copy.read_text(encoding="utf-8")
    else:
        orig_path = stored.get("file", "")
        orig = Path(orig_path) if orig_path else None
        if orig and orig.exists():
            content = orig.read_text(encoding="utf-8")
        else:
            return {
                "ok": False,
                "name": name,
                "status": "file_missing",
                "msg": (
                    f"Neither pinned copy ({pin_copy}) "
                    f"nor original found for {name}"
                ),
            }

    try:
        try:
            obj = json.loads(content)
            canonical = _canonical(obj)
        except (json.JSONDecodeError, ValueError):
            canonical = content

        current_hash = _sha256(canonical)
        match = current_hash == stored_hash

        return {
            "ok": match,
            "name": name,
            "status": "match" if match else "TAMPERED",
            "stored_hash": stored_hash[:16] + "...",
            "current_hash": current_hash[:16] + "...",
        }
    except Exception as e:
        return {"ok": False, "name": name, "status": "error", "msg": str(e)}


def verify_chain(repo_root: Optional[Path] = None) -> Dict:
    """
    S9.6: Верифицирует целостность hash chain (data/bee/hash_chain.json).

    Пересчитывает block_hash для каждого блока и проверяет:
      - prev_hash каждого блока соответствует block_hash предыдущего
      - block_hash соответствует SHA256(каноническому JSON блока без block_hash)

    LLM_FORBIDDEN. Fail-closed: нет файла → status='no_chain'.

    Returns:
        {"ok": bool, "status": str, "chain_length": int, ...}
    """
    # LLM_FORBIDDEN

    chain_file = (repo_root / "data" / "bee" / "hash_chain.json") if repo_root else _CHAIN_FILE

    if not chain_file.exists():
        return {
            "ok": False,
            "status": "no_chain",
            "msg": "No hash_chain.json found",
        }

    try:
        chain = json.loads(chain_file.read_text(encoding="utf-8"))
        entries = chain.get("entries", [])

        if not entries:
            return {
                "ok": True,
                "status": "empty_chain",
                "chain_length": 0,
            }

        prev_hash = "GENESIS"
        for i, entry in enumerate(entries):
            # Воссоздаём блок без block_hash для пересчёта
            block_for_hash = {
                "name": entry["name"],
                "sha256": entry["sha256"],
                "prev_hash": entry["prev_hash"],
            }
            expected_block_hash = _sha256(_canonical(block_for_hash))

            if entry.get("block_hash") != expected_block_hash:
                return {
                    "ok": False,
                    "status": "chain_broken",
                    "broken_at_index": i,
                    "broken_name": entry.get("name"),
                    "msg": (
                        f"Block hash mismatch at index {i} "
                        f"({entry.get('name')})"
                    ),
                }

            if entry.get("prev_hash") != prev_hash:
                return {
                    "ok": False,
                    "status": "chain_broken",
                    "broken_at_index": i,
                    "msg": f"prev_hash mismatch at index {i}",
                }

            prev_hash = entry["block_hash"]

        return {
            "ok": True,
            "status": "chain_intact",
            "chain_length": len(entries),
            "chain_head": chain.get("chain_head"),
        }
    except Exception as e:
        return {"ok": False, "status": "error", "msg": str(e)}


def verify_all(repo_root: Optional[Path] = None) -> List[Dict]:
    """
    S9.6: Верифицирует все PIN из data/bee/hashes/*.json (новый формат S9.6).

    Не затрагивает старые result_*.sha256 файлы (S9.3 формат).
    LLM_FORBIDDEN.

    Returns:
        list[dict] — может быть пустым если нет пинов S9.6 формата.
    """
    # LLM_FORBIDDEN

    hash_dir = (repo_root / "data" / "bee" / "hashes") if repo_root else _HASH_DIR

    if not hash_dir.exists():
        return []

    results = []
    for hash_file in sorted(hash_dir.glob("*.json")):
        name = hash_file.stem
        result = verify_one(name, repo_root=repo_root)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """Точка входа верификатора."""
    # LLM_FORBIDDEN

    default_repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description=(
            "BEE Independent Verifier — S9.3 + S9.6 (hash chain)\n"
            "LLM_FORBIDDEN"
        )
    )
    parser.add_argument("--name", help="(S9.6) Верифицировать один PIN по имени")
    parser.add_argument(
        "--all", action="store_true",
        help="(S9.6) Верифицировать все PIN из hashes/*.json + chain",
    )
    parser.add_argument(
        "--chain", action="store_true",
        help="(S9.6) Верифицировать целостность hash chain",
    )
    parser.add_argument(
        "--catalog", action="store_true",
        help="(S9.3) Проверить event_catalog.json",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="(S9.3) Проверить safety_report.json",
    )
    parser.add_argument(
        "--repo", default=str(default_repo_root),
        help="Путь к репо (по умолчанию: родитель директории verifier/)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo)
    hashes_dir = repo_root / "data" / "bee" / "hashes"

    all_ok = True
    checked = 0

    # ---- S9.6: --name ----
    if args.name:
        result = verify_one(args.name, repo_root=repo_root)
        checked += 1
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    # ---- S9.6: --chain ----
    if args.chain:
        result = verify_chain(repo_root=repo_root)
        checked += 1
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    # ---- S9.6: --all ----
    if args.all:
        results = verify_all(repo_root=repo_root)
        chain_result = verify_chain(repo_root=repo_root)
        checked += len(results) + 1

        ok_count = sum(1 for r in results if r.get("ok"))
        fail_count = len(results) - ok_count

        print(f"\n=== BEE Verification Report (S9.6) ===")
        print(f"Files verified: {len(results)}")
        print(f"  OK:      {ok_count}")
        print(f"  FAILED:  {fail_count}")
        print(f"\nHash chain: {chain_result.get('status', 'unknown')}")

        for r in results:
            icon = "✓" if r["ok"] else "✗"
            print(f"  {icon} {r['name']}: {r['status']}")

        overall_ok = fail_count == 0 and chain_result.get("ok", False)
        print(json.dumps({
            "files": results,
            "chain": chain_result,
            "overall_ok": overall_ok,
        }, indent=2))

        return 0 if overall_ok else 1

    # ---- S9.3: --catalog / --report (backward compat) ----
    s93_names_to_check: list = []
    if hashes_dir.exists():
        s93_names_to_check = [
            f.stem.replace("result_", "")
            for f in hashes_dir.glob("result_*.sha256")
        ]

    for name in s93_names_to_check:
        r = verify_result_hash(name, repo_root)
        checked += 1
        ok = r.get("ok")
        if ok is True:
            print(f"✅ OK    {name}")
        elif ok is None:
            print(f"⚠️  N/A   {name}: {r.get('note', '')}")
        else:
            print(f"❌ FAIL  {name}")
            if r.get("error"):
                print(f"         error: {r['error']}")
            else:
                print(f"         stored: {r.get('stored_hash', '?')}")
                print(f"         actual: {r.get('actual_hash', '?')}")
            all_ok = False

    if args.catalog or (not s93_names_to_check and not args.report):
        r = verify_event_catalog(repo_root)
        checked += 1
        if r.get("ok") is True:
            print(f"✅ OK    event_catalog.json ({r.get('events_count', 0)} events)")
        elif r.get("ok") is False:
            print(f"❌ FAIL  event_catalog.json")
            for issue in r.get("issues", []):
                print(f"         - {issue}")
            if r.get("error"):
                print(f"         error: {r['error']}")
            all_ok = False

    if args.report or (not s93_names_to_check and not args.catalog):
        r = verify_safety_report(repo_root)
        checked += 1
        ok = r.get("ok")
        if ok is True:
            print(
                f"✅ OK    safety_report.json "
                f"({r.get('events_analyzed', 0)} events, "
                f"fp={r.get('false_positives', 0)}, "
                f"src={r.get('data_source', '?')})"
            )
        elif ok is None:
            print(f"⚠️  N/A   safety_report.json: {r.get('note', '')}")
        else:
            print(f"❌ FAIL  safety_report.json")
            for issue in r.get("issues", []):
                print(f"         - {issue}")
            all_ok = False

    if checked == 0:
        parser.print_help()
        return 1

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
