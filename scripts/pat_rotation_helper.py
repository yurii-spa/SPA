#!/usr/bin/env python3
"""
PAT Rotation Helper — SPA Project
Напоминает о ротации PAT и генерирует пошаговый checklist.
PAT НИКОГДА не читается и не хранится в коде — только Keychain.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# ── константы ────────────────────────────────────────────────────────────────
ROTATION_INTERVAL_DAYS = 90
WARNING_THRESHOLD_DAYS = 14
KEYCHAIN_SERVICE = "spa-claude-pat"

# Путь к state-файлу относительно корня проекта (2 уровня вверх от scripts/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
STATE_FILE = _PROJECT_ROOT / "data" / "pat_rotation_state.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    """Атомарная запись: tmpfile → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".pat_rotation_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_state() -> dict:
    """Читает state-файл; если нет — создаёт с today."""
    if not STATE_FILE.exists():
        today = date.today().isoformat()
        next_rotation = (date.today() + timedelta(days=ROTATION_INTERVAL_DAYS)).isoformat()
        state = {
            "last_rotation": today,
            "next_rotation": next_rotation,
            "keychain_service": KEYCHAIN_SERVICE,
        }
        _atomic_write(STATE_FILE, state)
        return state

    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _compute_status(state: dict) -> dict:
    """Вычисляет сколько дней до следующей ротации и признак срочности."""
    next_rotation_str = state.get("next_rotation")
    if not next_rotation_str:
        # Fallback: считаем от last_rotation
        last = date.fromisoformat(state["last_rotation"])
        next_rotation = last + timedelta(days=ROTATION_INTERVAL_DAYS)
    else:
        next_rotation = date.fromisoformat(next_rotation_str)

    today = date.today()
    days_until = (next_rotation - today).days
    is_overdue = days_until < 0
    needs_rotation = days_until < WARNING_THRESHOLD_DAYS

    return {
        "today": today.isoformat(),
        "last_rotation": state.get("last_rotation"),
        "next_rotation": next_rotation.isoformat(),
        "days_until_rotation": days_until,
        "is_overdue": is_overdue,
        "needs_rotation_soon": needs_rotation,
        "keychain_service": state.get("keychain_service", KEYCHAIN_SERVICE),
    }


def _print_warning(status: dict) -> None:
    """Печатает WARNING с полным checklist."""
    days = status["days_until_rotation"]
    deadline = status["next_rotation"]
    service = status["keychain_service"]

    if status["is_overdue"]:
        header = f"🚨  PAT ROTATION OVERDUE BY {abs(days)} DAYS (was due: {deadline})"
    else:
        header = f"⚠️   PAT ROTATION DUE IN {days} DAYS (deadline: {deadline})"

    print(header)
    print()
    print("Checklist:")
    print("  1. GitHub → Settings → Developer settings → PATs → Fine-grained tokens")
    print("  2. Создай новый PAT с правами: Contents (read/write), Workflows (read/write)")
    print(f"  3. security-update-keychain '<new_token>' {service}   ← НЕ ЗАПУСКАЙ через код")
    print("  4. Протестируй: python3 push_to_github.py --dry-run")
    print("  5. Обнови pat_rotation_state.json: python3 scripts/pat_rotation_helper.py --mark-rotated")
    print("  6. Удали старый PAT на GitHub")
    print()
    print(f"  Last rotation: {status['last_rotation']}")
    print(f"  State file:    {STATE_FILE}")


# ── команды ───────────────────────────────────────────────────────────────────

def cmd_default(status: dict) -> int:
    """Основной режим: показывает статус, при необходимости — WARNING."""
    days = status["days_until_rotation"]

    if status["needs_rotation_soon"] or status["is_overdue"]:
        _print_warning(status)
        return 1
    else:
        print(f"✅  PAT rotation OK — {days} days until next rotation (due {status['next_rotation']})")
        print(f"    Last rotation: {status['last_rotation']}")
        return 0


def cmd_check(status: dict) -> int:
    """--check: тихий режим, только exit code (0=ok, 1=нужна ротация скоро)."""
    return 1 if status["needs_rotation_soon"] or status["is_overdue"] else 0


def cmd_status(status: dict) -> int:
    """--status: JSON вывод статуса."""
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0


def cmd_mark_rotated() -> int:
    """--mark-rotated: обновляет дату последней ротации."""
    today = date.today()
    next_rotation = today + timedelta(days=ROTATION_INTERVAL_DAYS)

    # Загружаем существующее состояние чтобы сохранить keychain_service
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            existing = json.load(f)
        keychain_service = existing.get("keychain_service", KEYCHAIN_SERVICE)
    else:
        keychain_service = KEYCHAIN_SERVICE

    state = {
        "last_rotation": today.isoformat(),
        "next_rotation": next_rotation.isoformat(),
        "keychain_service": keychain_service,
    }
    _atomic_write(STATE_FILE, state)

    print(f"✅  PAT rotation marked. Next rotation due: {next_rotation.isoformat()}")
    print(f"    State file updated: {STATE_FILE}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="PAT Rotation Helper — SPA Project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/pat_rotation_helper.py              # показать статус / warning
  python3 scripts/pat_rotation_helper.py --check      # exit 0=ok, 1=rotation needed
  python3 scripts/pat_rotation_helper.py --status     # JSON вывод
  python3 scripts/pat_rotation_helper.py --mark-rotated  # записать дату ротации
""",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Тихий режим: только exit code (0=ok, 1=нужна ротация)",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Вывести JSON-статус",
    )
    group.add_argument(
        "--mark-rotated",
        action="store_true",
        dest="mark_rotated",
        help="Обновить дату ротации на сегодня",
    )
    args = parser.parse_args(argv)

    if args.mark_rotated:
        return cmd_mark_rotated()

    state = _load_state()
    status = _compute_status(state)

    if args.check:
        return cmd_check(status)
    elif args.status:
        return cmd_status(status)
    else:
        return cmd_default(status)


if __name__ == "__main__":
    sys.exit(main())
