"""
Data Integrity Layer — периодические проверки консистентности данных.
LLM_FORBIDDEN. fail-closed: нарушение → alarm.
"""
# LLM_FORBIDDEN
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json
import hashlib
import os
import tempfile

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

INTEGRITY_VERSION = "integrity_v1.0"


def _file_sha256(path: Path) -> Optional[str]:
    """SHA256 файла. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _atomic_write(path: Path, data: str) -> None:
    """Атомарная запись: tmp-файл + os.replace. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def check_json_valid(path: Path) -> Dict:
    """
    Проверяет что JSON файл валиден и не пустой.
    LLM_FORBIDDEN. fail-closed: ошибка → {"ok": False}.
    """
    # LLM_FORBIDDEN
    if not path.exists():
        return {"ok": False, "status": "missing", "path": str(path)}
    try:
        content = path.read_text()
        if not content.strip():
            return {"ok": False, "status": "empty", "path": str(path)}
        obj = json.loads(content)
        return {
            "ok": True,
            "status": "valid",
            "path": str(path),
            "size_bytes": len(content),
            "type": type(obj).__name__,
        }
    except json.JSONDecodeError as e:
        return {"ok": False, "status": "invalid_json", "path": str(path), "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": "read_error", "path": str(path), "error": str(e)}


def check_required_fields(path: Path, required_fields: List[str]) -> Dict:
    """
    Проверяет наличие обязательных полей в JSON.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    valid = check_json_valid(path)
    if not valid["ok"]:
        return valid

    try:
        obj = json.loads(path.read_text())
        missing = [f for f in required_fields if f not in obj]
        return {
            "ok": len(missing) == 0,
            "status": "fields_ok" if not missing else "missing_fields",
            "missing": missing,
            "path": str(path),
        }
    except Exception as e:
        return {"ok": False, "status": "check_error", "error": str(e)}


def check_data_age(path: Path, field: str, max_age_hours: int = 24) -> Dict:
    """
    Проверяет что временная метка в данных не старше max_age_hours.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    valid = check_json_valid(path)
    if not valid["ok"]:
        return valid

    try:
        obj = json.loads(path.read_text())
        ts_str = obj.get(field)
        if not ts_str:
            return {"ok": False, "status": "missing_timestamp", "field": field}

        ts = datetime.fromisoformat(str(ts_str).rstrip("Z"))
        age_hours = (datetime.utcnow() - ts).total_seconds() / 3600

        return {
            "ok": age_hours <= max_age_hours,
            "status": "fresh" if age_hours <= max_age_hours else "stale",
            "age_hours": age_hours,
            "max_age_hours": max_age_hours,
            "timestamp": ts_str,
        }
    except Exception as e:
        return {"ok": False, "status": "age_check_error", "error": str(e)}


# Конфигурация критических файлов данных
CRITICAL_DATA_FILES: Dict[str, Dict] = {
    "paper_trading_status": {
        "path": "data/paper_trading_status.json",
        "required_fields": ["equity", "daily_history"],
        "age_field": "updated_at",
        "max_age_hours": 4,
    },
    "gap_monitor": {
        "path": "data/gap_monitor.json",
        "required_fields": ["has_gaps", "start_date"],
        "age_field": "updated_at",
        "max_age_hours": 24,
    },
    "adapter_status": {
        "path": "data/adapter_status.json",
        "required_fields": [],
        "age_field": None,
        "max_age_hours": None,
    },
}


def run_integrity_check(
    files: Optional[Dict] = None,
    project_root: Optional[Path] = None,
) -> Dict:
    """
    Запускает полную проверку целостности данных.
    LLM_FORBIDDEN. fail-closed: любая критическая ошибка → status="fail".

    Returns:
        dict с "overall_ok", "results", "critical_failures"
    """
    # LLM_FORBIDDEN
    if files is None:
        files = CRITICAL_DATA_FILES
    if project_root is None:
        project_root = _PROJECT_ROOT

    results: Dict = {}
    critical_failures: List[str] = []

    for name, cfg in files.items():
        path = project_root / cfg["path"]

        # 1. JSON валидность
        json_check = check_json_valid(path)
        if not json_check["ok"]:
            results[name] = {"ok": False, "reason": json_check["status"]}
            critical_failures.append(name)
            continue

        # 2. Required fields
        if cfg.get("required_fields"):
            field_check = check_required_fields(path, cfg["required_fields"])
            if not field_check["ok"]:
                results[name] = {
                    "ok": False,
                    "reason": f"missing_fields: {field_check.get('missing')}",
                }
                critical_failures.append(name)
                continue

        # 3. Age check (опционально)
        if cfg.get("age_field") and cfg.get("max_age_hours"):
            age_check = check_data_age(path, cfg["age_field"], cfg["max_age_hours"])
            if not age_check["ok"] and age_check.get("status") not in ["missing_timestamp"]:
                results[name] = {
                    "ok": False,
                    "reason": f"stale: {age_check.get('age_hours', '?'):.1f}h > {cfg['max_age_hours']}h",
                    "warning": True,
                }
                # Стейл данные — предупреждение, не критический сбой
                continue

        results[name] = {
            "ok": True,
            "sha256": _file_sha256(path),
            "path": str(path),
        }

    overall_ok = len(critical_failures) == 0

    summary = {
        "integrity_version": INTEGRITY_VERSION,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "overall_ok": overall_ok,
        "files_checked": len(files),
        "critical_failures": critical_failures,
        "results": results,
        "LLM_FORBIDDEN": True,
    }

    # Атомарная запись отчёта
    report_path = project_root / "data" / "integrity_report.json"
    _atomic_write(report_path, json.dumps(summary, indent=2))

    return summary
