"""
DataTrust Gate v1.0 — единая точка интеграции DataTrust с cycle_runner.

Назначение:
  - Вызывается ПЕРЕД каждым дневным циклом.
  - Проверяет Circuit Breaker (fail-closed: OPEN → block).
  - Проверяет свежесть критических data-файлов.
  - Возвращает GateResult(allowed, reason, ...).
  - Логирует результат в data/datatrust_gate_log.json (ring-buffer 200).

Контракт fail-closed:
  - Любая необработанная ошибка → allowed=False.
  - Нет circuit_breaker модуля → allowed=False.
  - CB OPEN → allowed=False (не зависит от данных).
  - CB HALF_OPEN (strict=True по умолчанию) → allowed=False.
  - 3+ stale критических файла → allowed=False.
  - Stale файл, которого ещё нет на диске → не stale (новый проект).

LLM_FORBIDDEN: нет вызовов AI в этом модуле.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATATRUST_GATE_VERSION = "datatrust_gate_v1.0"

# ---------------------------------------------------------------------------
# Критические data-файлы и максимальный возраст (секунды).
# Отсутствующий файл → не stale (может ещё не создан).
# ---------------------------------------------------------------------------
CRITICAL_DATA_FRESHNESS: dict = {
    "data/paper_trading_status.json": 7200,   # 2 часа
    "data/adapter_status.json":        14400,  # 4 часа
    "data/portfolio_health.json":      86400,  # 1 день (если есть)
}

# Порог: сколько stale-файлов уже блокируют цикл
_STALE_BLOCK_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Результирующий датакласс
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Результат DataTrust gate check. LLM_FORBIDDEN."""
    allowed: bool
    reason: str
    circuit_state: str          # "CLOSED" / "OPEN" / "HALF_OPEN" / "UNKNOWN"
    stale_files: List[str]
    checked_at: str             # ISO UTC
    LLM_FORBIDDEN: bool = field(default=True, init=False)


# ---------------------------------------------------------------------------
# Circuit Breaker check
# ---------------------------------------------------------------------------

def check_circuit_breaker() -> Tuple[bool, str]:
    """
    Проверяет Circuit Breaker.

    fail-closed:
      - Ошибка импорта / чтения → (False, "circuit_breaker_error=...")
      - CB OPEN             → (False, "circuit_breaker=OPEN")
      - CB HALF_OPEN (strict=True) → (False, "circuit_breaker=HALF_OPEN (strict)")
      - CB CLOSED           → (True,  "circuit_breaker=CLOSED")

    LLM_FORBIDDEN.

    Returns:
        (allowed: bool, reason: str)
    """
    # LLM_FORBIDDEN
    try:
        from spa_core.data_trust.circuit_breaker import (  # noqa: PLC0415
            is_trading_allowed,
            get_status,
        )

        # get_status возвращает dict с полем "state" (CBState — str-enum).
        # CBState наследует str, но str(CBState.CLOSED) в Python 3.11+
        # даёт "CBState.CLOSED", поэтому берём .value (если есть) или str().
        status = get_status()
        raw_state = status.get("state", "OPEN")
        # CBState → .value = "CLOSED"/"OPEN"/"HALF_OPEN"
        state_val: str = (
            raw_state.value if hasattr(raw_state, "value") else str(raw_state)
        )

        # OPEN → немедленно блокируем
        if state_val == "OPEN":
            return False, "circuit_breaker=OPEN"

        # HALF_OPEN: вызываем с strict=True → dict["allowed"] False
        if state_val == "HALF_OPEN":
            result = is_trading_allowed(strict=True)
            if not result.get("allowed", False):
                return False, "circuit_breaker=HALF_OPEN (strict)"
            # strict=False → пропускаем (нестандартный путь, не должен случаться)
            return True, "circuit_breaker=HALF_OPEN (allowed)"

        # CLOSED → разрешено
        if state_val == "CLOSED":
            return True, "circuit_breaker=CLOSED"

        # Неизвестное состояние → fail-closed
        return False, f"circuit_breaker=UNKNOWN({state_val})"

    except Exception as exc:  # noqa: BLE001
        # fail-closed: ошибка импорта / I/O → блок
        short = str(exc)[:60].replace("\n", " ")
        return False, f"circuit_breaker_error={short}"


# ---------------------------------------------------------------------------
# Data Freshness check
# ---------------------------------------------------------------------------

def check_data_freshness() -> Tuple[bool, List[str]]:
    """
    Проверяет свежесть критических data-файлов по mtime.

    - Файл отсутствует → пропускаем (не stale).
    - mtime > max_age_sec → добавляем в stale list.

    LLM_FORBIDDEN. fail-closed: ошибка stat → пропускаем файл.

    Returns:
        (all_fresh: bool, stale_descriptions: List[str])
    """
    # LLM_FORBIDDEN
    now_ts = datetime.now(timezone.utc).timestamp()
    stale: List[str] = []

    for rel_path, max_age_sec in CRITICAL_DATA_FRESHNESS.items():
        full_path = _PROJECT_ROOT / rel_path
        if not full_path.exists():
            # Файл ещё не создан — не считаем stale
            continue
        try:
            age_sec = now_ts - full_path.stat().st_mtime
            if age_sec > max_age_sec:
                stale.append(
                    f"{rel_path} (age={age_sec / 3600:.1f}h"
                    f" > max={max_age_sec // 3600}h)"
                )
        except OSError:
            # Ошибка stat → не stale, пропускаем
            pass

    return len(stale) == 0, stale


# ---------------------------------------------------------------------------
# Главная функция gate
# ---------------------------------------------------------------------------

def run_datatrust_gate(strict_half_open: bool = True) -> GateResult:
    """
    Основная функция DataTrust gate.

    Вызывается перед каждым дневным циклом cycle_runner.
    Логирует результат в data/datatrust_gate_log.json.

    Порядок проверок:
        1. Circuit Breaker (fail-closed: OPEN → немедленный block).
        2. Data freshness (>= _STALE_BLOCK_THRESHOLD stale → block).
        3. All OK → allowed=True.

    LLM_FORBIDDEN. fail-closed: необработанное исключение → allowed=False.

    Args:
        strict_half_open: если True (дефолт), HALF_OPEN блокирует цикл.

    Returns:
        GateResult
    """
    # LLM_FORBIDDEN
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # ------------------------------------------------------------------
        # 1. Circuit Breaker
        # ------------------------------------------------------------------
        cb_allowed, cb_reason = check_circuit_breaker()

        # Извлекаем состояние из reason-строки для GateResult
        # Формат reason: "circuit_breaker=CLOSED" / "circuit_breaker_error=..."
        circuit_state = "UNKNOWN"
        if "=" in cb_reason:
            raw_state = cb_reason.split("=", 1)[1].split(" ")[0]
            circuit_state = raw_state if raw_state in ("CLOSED", "OPEN", "HALF_OPEN") else "UNKNOWN"

        if not cb_allowed:
            result = GateResult(
                allowed=False,
                reason=cb_reason,
                circuit_state=circuit_state,
                stale_files=[],
                checked_at=now_iso,
            )
            log_gate_result(result)
            return result

        # ------------------------------------------------------------------
        # 2. Data freshness
        # ------------------------------------------------------------------
        _fresh_ok, stale_files = check_data_freshness()

        if len(stale_files) >= _STALE_BLOCK_THRESHOLD:
            result = GateResult(
                allowed=False,
                reason=f"too_many_stale_files={len(stale_files)}",
                circuit_state=circuit_state,
                stale_files=stale_files,
                checked_at=now_iso,
            )
            log_gate_result(result)
            return result

        # ------------------------------------------------------------------
        # 3. All OK
        # ------------------------------------------------------------------
        stale_count = len(stale_files)
        reason = f"{cb_reason} | stale={stale_count}"
        result = GateResult(
            allowed=True,
            reason=reason,
            circuit_state=circuit_state,
            stale_files=stale_files,
            checked_at=now_iso,
        )
        log_gate_result(result)
        return result

    except Exception as exc:  # noqa: BLE001
        # fail-closed: любая необработанная ошибка → block
        short = str(exc)[:60].replace("\n", " ")
        result = GateResult(
            allowed=False,
            reason=f"datatrust_gate_exception={short}",
            circuit_state="OPEN",
            stale_files=[],
            checked_at=now_iso,
        )
        log_gate_result(result)
        return result


# ---------------------------------------------------------------------------
# Логирование результата (ring-buffer 200)
# ---------------------------------------------------------------------------

def log_gate_result(result: GateResult) -> None:
    """
    Атомарно записывает результат gate в data/datatrust_gate_log.json.

    Ring-buffer 200 записей. Ошибка логирования не блокирует основную логику.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    log_path = _PROJECT_ROOT / "data" / "datatrust_gate_log.json"

    try:
        # Читаем существующий лог
        if log_path.exists():
            try:
                existing = json.loads(log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {"entries": []}
        else:
            existing = {"entries": []}

        entries: list = existing.get("entries", [])

        entries.append({
            "allowed": result.allowed,
            "reason": result.reason,
            "circuit_state": result.circuit_state,
            "stale_files_count": len(result.stale_files),
            "stale_files": result.stale_files,
            "checked_at": result.checked_at,
        })

        # Ring-buffer: держим последние 200
        if len(entries) > 200:
            entries = entries[-200:]

        existing["entries"] = entries
        existing["last_result"] = {
            "allowed": result.allowed,
            "reason": result.reason,
            "circuit_state": result.circuit_state,
            "stale_files_count": len(result.stale_files),
            "checked_at": result.checked_at,
        }
        existing["version"] = DATATRUST_GATE_VERSION

        # Атомарная запись
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=log_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(existing, indent=2))
            os.replace(tmp_name, log_path)
        except Exception:  # noqa: BLE001
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    except Exception:  # noqa: BLE001
        # Логирование не должно ломать основной поток
        pass
