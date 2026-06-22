"""
DataTrust Circuit Breaker.
N consecutive alarms → OPEN circuit → блокирует торговлю.
LLM_FORBIDDEN. fail-closed: OPEN → не пропускает.

Стейт-машина:
  CLOSED      → нормальная работа, торговля разрешена
  OPEN        → торговля ЗАБЛОКИРОВАНА (fail-closed)
  HALF_OPEN   → пробный период, торговля ограничена (strict=False)

Стратегия записи: атомарная (tmp + os.replace).
"""
# LLM_FORBIDDEN
from enum import Enum
from pathlib import Path
from datetime import datetime
import json
import os
import tempfile

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CB_STATE_FILE = _PROJECT_ROOT / "data" / "circuit_breaker_state.json"

CB_VERSION = "circuit_breaker_v1.0"

# Конфигурация (изменяй только через ADR)
CONSECUTIVE_ALARMS_TO_OPEN: int = 3    # N alarm подряд → OPEN
RECOVERY_HOURS: int = 1                 # Через N часов без alarm → HALF_OPEN
AUTO_CLOSE_HOURS: int = 4              # Через N часов в HALF_OPEN → CLOSED


class CBState(str, Enum):
    CLOSED    = "CLOSED"       # Нормально — торговля разрешена
    OPEN      = "OPEN"         # Блокирует — торговля запрещена (fail-closed)
    HALF_OPEN = "HALF_OPEN"    # Пробный период


def _atomic_write(path: Path, data: str) -> None:
    """Атомарная запись: tmp-файл + os.replace. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state() -> dict:
    """
    Загружает состояние circuit breaker.
    LLM_FORBIDDEN. fail-closed: ошибка чтения → возвращает OPEN.
    """
    # LLM_FORBIDDEN
    if not _CB_STATE_FILE.exists():
        return {
            "state": CBState.CLOSED,
            "consecutive_alarms": 0,
            "last_alarm_at": None,
            "last_alarm_metric": None,
            "opened_at": None,
            "half_open_at": None,
            "version": CB_VERSION,
        }
    try:
        return json.loads(_CB_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        # FAIL-CLOSED: ошибка чтения → OPEN (безопасное состояние)
        now = datetime.utcnow().isoformat() + "Z"
        return {
            "state": CBState.OPEN,
            "consecutive_alarms": CONSECUTIVE_ALARMS_TO_OPEN,
            "last_alarm_at": now,
            "last_alarm_metric": "state_file_corrupt",
            "opened_at": now,
            "half_open_at": None,
            "version": CB_VERSION,
            "note": "FAIL_CLOSED: state file corrupt → OPEN",
        }


def save_state(state_dict: dict) -> None:
    """Сохраняет состояние circuit breaker атомарно. LLM_FORBIDDEN."""
    # LLM_FORBIDDEN
    state_dict["updated_at"] = datetime.utcnow().isoformat() + "Z"
    state_dict.setdefault("version", CB_VERSION)
    _atomic_write(_CB_STATE_FILE, json.dumps(state_dict, indent=2))


def record_alarm(metric: str) -> dict:
    """
    Записывает новый alarm. Если consecutive_alarms >= N → OPEN.
    LLM_FORBIDDEN. fail-closed.

    Returns: текущий state dict после обновления.
    """
    # LLM_FORBIDDEN
    state = load_state()
    now = datetime.utcnow().isoformat() + "Z"

    state["consecutive_alarms"] = state.get("consecutive_alarms", 0) + 1
    state["last_alarm_at"] = now
    state["last_alarm_metric"] = metric

    current = state.get("state", CBState.CLOSED)

    if state["consecutive_alarms"] >= CONSECUTIVE_ALARMS_TO_OPEN:
        if current != CBState.OPEN:
            state["state"] = CBState.OPEN
            state["opened_at"] = now
            state["half_open_at"] = None
    # Если уже HALF_OPEN и снова alarm → откат в OPEN
    elif current == CBState.HALF_OPEN:
        state["state"] = CBState.OPEN
        state["opened_at"] = now
        state["half_open_at"] = None

    save_state(state)
    return state


def record_success() -> dict:
    """
    Записывает успешную валидацию (нет alarm).
    CLOSED  → сбрасываем счётчик.
    OPEN    → если прошло RECOVERY_HOURS без alarm → переходим в HALF_OPEN.
    HALF_OPEN → если прошло AUTO_CLOSE_HOURS → переходим в CLOSED.
    LLM_FORBIDDEN.

    Returns: текущий state dict после обновления.
    """
    # LLM_FORBIDDEN
    state = load_state()
    now = datetime.utcnow()
    current = state.get("state", CBState.CLOSED)

    if current == CBState.CLOSED:
        state["consecutive_alarms"] = 0
        save_state(state)
        return state

    if current == CBState.OPEN:
        last_alarm_str = state.get("last_alarm_at")
        if last_alarm_str:
            try:
                last_alarm = datetime.fromisoformat(last_alarm_str.rstrip("Z"))
                if (now - last_alarm).total_seconds() >= RECOVERY_HOURS * 3600:
                    # OPEN → HALF_OPEN: прошло достаточно времени без alarm
                    state["state"] = CBState.HALF_OPEN
                    state["half_open_at"] = now.isoformat() + "Z"
            except (ValueError, TypeError):
                pass
        save_state(state)
        return state

    if current == CBState.HALF_OPEN:
        half_open_str = state.get("half_open_at")
        if half_open_str:
            try:
                half_open_at = datetime.fromisoformat(half_open_str.rstrip("Z"))
                if (now - half_open_at).total_seconds() >= AUTO_CLOSE_HOURS * 3600:
                    # HALF_OPEN → CLOSED: восстановление завершено
                    state["state"] = CBState.CLOSED
                    state["consecutive_alarms"] = 0
                    state["opened_at"] = None
                    state["half_open_at"] = None
            except (ValueError, TypeError):
                pass
        save_state(state)
        return state

    # Неизвестное состояние → не трогаем
    save_state(state)
    return state


def is_trading_allowed(strict: bool = True) -> dict:
    """
    Основной метод: разрешена ли торговля?

    fail-closed:
      CLOSED    → allowed=True
      OPEN      → allowed=False (всегда)
      HALF_OPEN → allowed=False если strict=True, True если strict=False
      UNKNOWN   → allowed=False

    LLM_FORBIDDEN.

    Returns:
        {
            "allowed": bool,
            "state": str,
            "reason": str,
            "LLM_FORBIDDEN": True,
            ...
        }
    """
    # LLM_FORBIDDEN
    state = load_state()
    # default → OPEN если состояние неизвестно (fail-closed)
    current = state.get("state", CBState.OPEN)

    if current == CBState.CLOSED:
        return {
            "allowed": True,
            "state": current,
            "reason": "Circuit closed — normal operation",
            "consecutive_alarms": state.get("consecutive_alarms", 0),
            "LLM_FORBIDDEN": True,
        }

    if current == CBState.OPEN:
        return {
            "allowed": False,
            "state": current,
            "reason": (
                f"FAIL_CLOSED: Circuit OPEN after {state.get('consecutive_alarms', 0)} "
                f"consecutive alarms. Last metric: {state.get('last_alarm_metric', '?')}"
            ),
            "opened_at": state.get("opened_at"),
            "consecutive_alarms": state.get("consecutive_alarms", 0),
            "LLM_FORBIDDEN": True,
        }

    if current == CBState.HALF_OPEN:
        return {
            "allowed": not strict,
            "state": current,
            "reason": (
                "Circuit HALF_OPEN — recovery in progress"
                + (" (strict=False: trading allowed)" if not strict else " (strict=True: trading blocked)")
            ),
            "half_open_at": state.get("half_open_at"),
            "LLM_FORBIDDEN": True,
        }

    # Неизвестное состояние → fail-closed
    return {
        "allowed": False,
        "state": "UNKNOWN",
        "reason": f"FAIL_CLOSED: unknown circuit state '{current}'",
        "LLM_FORBIDDEN": True,
    }


def get_status() -> dict:
    """
    Полный статус circuit breaker (для дашборда / GoLiveChecker).
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    state = load_state()
    trading = is_trading_allowed()
    return {
        "version": CB_VERSION,
        "state": state.get("state", "UNKNOWN"),
        "allowed": trading["allowed"],
        "consecutive_alarms": state.get("consecutive_alarms", 0),
        "last_alarm_at": state.get("last_alarm_at"),
        "last_alarm_metric": state.get("last_alarm_metric"),
        "opened_at": state.get("opened_at"),
        "half_open_at": state.get("half_open_at"),
        "config": {
            "consecutive_alarms_to_open": CONSECUTIVE_ALARMS_TO_OPEN,
            "recovery_hours": RECOVERY_HOURS,
            "auto_close_hours": AUTO_CLOSE_HOURS,
        },
        "LLM_FORBIDDEN": True,
    }


def reset_circuit() -> dict:
    """
    Принудительный сброс circuit breaker в CLOSED.
    Только для ops/тестов — в нормальном режиме не вызывать.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    state = {
        "state": CBState.CLOSED,
        "consecutive_alarms": 0,
        "last_alarm_at": None,
        "last_alarm_metric": None,
        "opened_at": None,
        "half_open_at": None,
        "version": CB_VERSION,
        "reset_at": datetime.utcnow().isoformat() + "Z",
        "note": "Manual reset via reset_circuit()",
    }
    save_state(state)
    return state
