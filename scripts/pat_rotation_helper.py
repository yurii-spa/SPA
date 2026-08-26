#!/usr/bin/env python3
"""
PAT Rotation Helper — SPA Project
Напоминает о ротации PAT и генерирует пошаговый checklist.
PAT НИКОГДА не читается и не хранится в коде — только Keychain.

**Почему модуль переписан (карточка `inbox-strazh-rotatsii-pat-sam-sochinyaet-datu`,
замер цикла #379, починка #383).** `_load_state()` при ОТСУТСТВУЮЩЕМ файле состояния
создавал его с `last_rotation = сегодня`. То есть первый же `--status` или `--check`
СОЧИНЯЛ факт, о котором отчитывался: «ротация была сегодня, до следующей 90 дней», и
`--check` возвращал 0 ровно потому, что его спросили впервые. Замер вживую 25.08: в
прод-дереве `data/pat_rotation_state.json` не существовало, один вызов `--status` создал
его с датой, в которую никакой ротации не было.

Это класс «fail-OPEN monitor»: страж, который не может покраснеть, потому что молчание
он сам превращает в благополучие. Инвариант проекта — refusal-first: нет наблюдения ⇒
ОТКАЗ, а не выдуманное значение.

**Что теперь:**

- `_load_state()` НИЧЕГО не пишет. Нет файла (или он нечитаем) ⇒ `None`, и это состояние
  называется своим именем: «дата последней ротации НЕ ИЗВЕСТНА».
- Дату ротации выставляет ТОЛЬКО `--mark-rotated` — человек, который её реально сделал.
- Время — ВХОД (`now=`), а не `date.today()` внутри (`.claude/rules/deployment.md`,
  раздел про фиксированные даты): обе стороны сравнения закрепляются тестом.
- В состоянии «не известно» словарь статуса НЕ СОДЕРЖИТ ключей-суждений
  (`days_until_rotation`, `is_overdue`, `needs_rotation_soon`, `last_rotation`,
  `next_rotation`) — намеренно. Ключ, который присутствует и ложен, — ровно то, чем этот
  дефект и держался: наивный `if status["needs_rotation_soon"]` прочитал бы `None` как
  «всё хорошо». `KeyError` громкий, `None` — нет.

Коды возврата: **0** — ротация не нужна · **1** — нужна ротация ИЛИ дата НЕ ИЗВЕСТНА
(`--check`, требование карточки) · **2** — `--status` при неизмеренном состоянии
(конвенция репозитория «2 = не измерено»: репортёр, отвечающий 0 на «я не знаю», — тот
же fail-OPEN, только тише).
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
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


def _load_state(state_file: Path = None):
    """Читает state-файл. НИЧЕГО не пишет. Нет файла / нечитаем ⇒ ``None``.

    Раньше здесь стояла авто-запись `last_rotation = сегодня`, и она и была дефектом:
    отсутствие наблюдения превращалось в наблюдение «ротация была только что». Читатель
    обязан отличать «дата известна» от «даты нет», поэтому «нет» возвращается отдельным
    значением, а не подставляется.
    """
    path = state_file or STATE_FILE
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _unknown_status(reason: str, now: date, state=None) -> dict:
    """Статус «дата ротации НЕ ИЗВЕСТНА» — без единого ключа-суждения.

    Ключи `days_until_rotation` / `is_overdue` / `needs_rotation_soon` здесь ОТСУТСТВУЮТ
    намеренно (см. модульный докстринг): присутствующий и ложный ключ — это и есть тот
    способ, которым «не измерено» бесшумно читается как «в порядке».
    """
    keychain = KEYCHAIN_SERVICE
    if isinstance(state, dict):
        keychain = state.get("keychain_service", KEYCHAIN_SERVICE)
    return {
        "today": now.isoformat(),
        "rotation_date_known": False,
        "unknown_reason": reason,
        "keychain_service": keychain,
    }


def _compute_status(state, now: date = None, state_file: Path = None) -> dict:
    """Сколько дней до следующей ротации и признак срочности — либо честное «не знаю».

    `now` — ВХОД (по умолчанию реальные часы): тест закрепляет обе стороны сравнения и
    не начинает падать от того, что сдвинулся календарь.
    """
    now = now or date.today()
    path = state_file or STATE_FILE

    if not state:
        if not path.exists():
            reason = (f"файла состояния нет ({path}) — дата последней ротации PAT НЕ ИЗВЕСТНА. "
                      f"Её выставляет только `--mark-rotated`, и только после настоящей ротации")
        else:
            reason = (f"файл состояния {path} не читается (нет JSON-объекта) — "
                      f"дата последней ротации PAT НЕ ИЗМЕРЕНА")
        return _unknown_status(reason, now)

    next_rotation_str = state.get("next_rotation")
    try:
        if next_rotation_str:
            next_rotation = date.fromisoformat(next_rotation_str)
        else:
            # Fallback: считаем от last_rotation
            next_rotation = (date.fromisoformat(state["last_rotation"])
                             + timedelta(days=ROTATION_INTERVAL_DAYS))
    except (KeyError, TypeError, ValueError):
        # Ни одной пригодной даты. Раньше здесь летел KeyError/ValueError наружу;
        # теперь это тот же вид, что и «файла нет»: наблюдения нет.
        return _unknown_status(
            f"в {path} нет пригодной даты ротации (next_rotation={state.get('next_rotation')!r}, "
            f"last_rotation={state.get('last_rotation')!r}) — НЕ ИЗМЕРЕНО", now, state)

    days_until = (next_rotation - now).days
    is_overdue = days_until < 0
    needs_rotation = days_until < WARNING_THRESHOLD_DAYS

    return {
        "today": now.isoformat(),
        "rotation_date_known": True,
        "last_rotation": state.get("last_rotation"),
        "next_rotation": next_rotation.isoformat(),
        "days_until_rotation": days_until,
        "is_overdue": is_overdue,
        "needs_rotation_soon": needs_rotation,
        "keychain_service": state.get("keychain_service", KEYCHAIN_SERVICE),
    }


def _print_unknown(status: dict) -> None:
    """Печатает ОТКАЗ: даты нет, значит и ответа «всё хорошо» нет."""
    print("❓  ДАТА РОТАЦИИ PAT НЕ ИЗВЕСТНА — это отказ, а не «всё в порядке»")
    print()
    print(f"  Причина: {status['unknown_reason']}")
    print()
    print("  Что делать:")
    print("  1. Если ротацию делали — вспомнить когда её делали НА САМОМ ДЕЛЕ;")
    print("     файл состояния восстанавливается только настоящей датой.")
    print("  2. Если не делали (или дата потеряна) — сделать ротацию сейчас "
          "и отметить её:")
    print("     python3 scripts/pat_rotation_helper.py --mark-rotated")
    print()
    print(f"  Ожидаемый файл состояния: {STATE_FILE}")


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
    """Основной режим: показывает статус, при необходимости — WARNING или ОТКАЗ."""
    if not status.get("rotation_date_known"):
        _print_unknown(status)
        return 1

    days = status["days_until_rotation"]
    if status["needs_rotation_soon"] or status["is_overdue"]:
        _print_warning(status)
        return 1
    else:
        print(f"✅  PAT rotation OK — {days} days until next rotation (due {status['next_rotation']})")
        print(f"    Last rotation: {status['last_rotation']}")
        return 0


def cmd_check(status: dict) -> int:
    """--check: тихий режим, только exit code (0=ok, 1=нужна ротация ЛИБО дата не известна).

    Проверка «известна ли дата» стоит ПЕРВОЙ и намеренно: пока её не было, отсутствие
    наблюдения давало 0 — тот самый зелёный ответ, которого никто не измерял.
    """
    if not status.get("rotation_date_known"):
        return 1
    return 1 if status["needs_rotation_soon"] or status["is_overdue"] else 0


def cmd_status(status: dict) -> int:
    """--status: JSON вывод статуса. Код 2, если дата НЕ ИЗМЕРЕНА (конвенция репозитория)."""
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status.get("rotation_date_known") else 2


def cmd_mark_rotated(now: date = None, state_file: Path = None) -> int:
    """--mark-rotated: ЕДИНСТВЕННЫЙ путь, которым дата ротации попадает в состояние."""
    now = now or date.today()
    path = state_file or STATE_FILE
    next_rotation = now + timedelta(days=ROTATION_INTERVAL_DAYS)

    # Загружаем существующее состояние чтобы сохранить keychain_service
    existing = _load_state(path)
    keychain_service = (existing or {}).get("keychain_service", KEYCHAIN_SERVICE)

    state = {
        "last_rotation": now.isoformat(),
        "next_rotation": next_rotation.isoformat(),
        "keychain_service": keychain_service,
    }
    _atomic_write(path, state)

    print(f"✅  PAT rotation marked. Next rotation due: {next_rotation.isoformat()}")
    print(f"    State file updated: {path}")
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
