"""
RegimeGate Engine B — ENTER/EXIT логика с гистерезисом.

Гистерезис предотвращает «флипинг» (частое переключение) при граничных значениях:
  - ENTER требует более строгих условий, чем EXIT
  - Между ENTER и EXIT порогами — сохраняется текущее состояние

LLM_FORBIDDEN: этот модуль не вызывает и не использует LLM.
fail-closed: нет данных → UNKNOWN → трактуется как EXIT.

Запись в data/hy_regime_log.json — атомарная (tmp + os.replace).
"""
# LLM_FORBIDDEN
from enum import Enum
from typing import Optional
import json
from pathlib import Path

from spa_core.risk.policy_hy import HY_LIMITS, HYRiskLimits, evaluate_exit
from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REGIME_LOG = _PROJECT_ROOT / "data" / "hy_regime_log.json"


class RegimeState(str, Enum):
    """
    Состояние режима Engine B.
    str-Enum: сравнивается со строками ("ENTER" == RegimeState.ENTER → True).
    """
    ENTER = "ENTER"      # Разрешён вход в позиции
    EXIT = "EXIT"        # Требуется выход из позиций / запрет входа
    UNKNOWN = "UNKNOWN"  # Нет данных — fail-closed → трактуется как EXIT


def evaluate_regime(
    *,
    funding_rate: Optional[float],
    depeg_pct: Optional[float],
    current_drawdown_pct: float = 0.0,
    current_state: Optional[str] = None,
    limits: HYRiskLimits = HY_LIMITS,
) -> dict:
    """
    Оценивает текущий режим рынка для Engine B (Carry/HY).

    Гистерезис (ENTER порог строже EXIT):
      - ENTER если: funding_rate > enter_thr AND depeg < enter_thr AND drawdown ok
      - EXIT если:  funding_rate <= exit_thr OR depeg >= exit_thr OR drawdown kill
      - Между порогами: сохраняется current_state (если передан)
      - По умолчанию при отсутствии current_state: fail-closed → EXIT

    Args:
        funding_rate: Аннуализированная ставка фандинга (None → UNKNOWN)
        depeg_pct: Процент депега (None → UNKNOWN)
        current_drawdown_pct: Текущая просадка слоя B (0.0 = нет просадки)
        current_state: Текущее состояние ("ENTER" / "EXIT" / None)
        limits: Лимиты RiskPolicy-HY

    Returns:
        {
            "state": RegimeState,
            "reason": str,
            "signals": dict,
            "timestamp": str (ISO 8601 UTC),
        }

    LLM_FORBIDDEN: детерминированные правила, без AI.
    fail-closed: None данные → UNKNOWN.
    """
    # LLM_FORBIDDEN
    ts = clock.utcnow().isoformat() + "Z"

    # --- FAIL-CLOSED: отсутствие данных → UNKNOWN ---
    if funding_rate is None or depeg_pct is None:
        return {
            "state": RegimeState.UNKNOWN,
            "reason": "FAIL_CLOSED: missing data -> treat as EXIT",
            "signals": {
                "funding_rate": funding_rate,
                "depeg_pct": depeg_pct,
            },
            "timestamp": ts,
        }

    # --- Проверяем EXIT условия (через evaluate_exit с гистерезисом) ---
    exit_result = evaluate_exit(
        depeg_pct=depeg_pct,
        funding_rate=funding_rate,
        current_drawdown_pct=current_drawdown_pct,
        limits=limits,
    )

    if exit_result["should_exit"]:
        return {
            "state": RegimeState.EXIT,
            "reason": "; ".join(exit_result["exit_signals"]),
            "signals": {
                "funding_rate": funding_rate,
                "depeg_pct": depeg_pct,
                "drawdown_pct": current_drawdown_pct,
            },
            "timestamp": ts,
        }

    # --- Проверяем ENTER условия (строже EXIT — гистерезис) ---
    if (
        funding_rate > limits.funding_rate_enter          # >5%
        and depeg_pct < limits.depeg_enter_pct            # <0.3%
        and current_drawdown_pct > -limits.drawdown_kill_pct  # не hit kill
    ):
        return {
            "state": RegimeState.ENTER,
            "reason": (
                f"funding_rate {funding_rate * 100:.2f}% > "
                f"{limits.funding_rate_enter * 100:.1f}%, "
                f"depeg {depeg_pct * 100:.3f}% < "
                f"{limits.depeg_enter_pct * 100:.1f}%"
            ),
            "signals": {
                "funding_rate": funding_rate,
                "depeg_pct": depeg_pct,
                "drawdown_pct": current_drawdown_pct,
            },
            "timestamp": ts,
        }

    # --- Гистерезисная зона (между ENTER и EXIT порогами) ---
    # Сохраняем текущее состояние если оно ENTER
    if current_state == RegimeState.ENTER:
        return {
            "state": RegimeState.ENTER,
            "reason": (
                "Hysteresis: staying in ENTER "
                "(not crossed EXIT threshold yet)"
            ),
            "signals": {
                "funding_rate": funding_rate,
                "depeg_pct": depeg_pct,
                "drawdown_pct": current_drawdown_pct,
            },
            "timestamp": ts,
        }

    # По умолчанию — EXIT (fail-closed, нет явного ENTER)
    return {
        "state": RegimeState.EXIT,
        "reason": "fail-closed: conditions not sufficient for ENTER",
        "signals": {
            "funding_rate": funding_rate,
            "depeg_pct": depeg_pct,
            "drawdown_pct": current_drawdown_pct,
        },
        "timestamp": ts,
    }


def log_regime_change(
    regime_result: dict,
    previous_state: Optional[str] = None,
) -> None:
    """
    Атомарно записывает изменение/подтверждение режима в hy_regime_log.json.

    Использует tmp + os.replace для атомарности (идиома проекта).
    Если файл повреждён — пересоздаёт с нуля (fail-safe).
    """
    log_path = _PROJECT_ROOT / "data" / "hy_regime_log.json"

    # Читаем существующий лог (или начинаем с нуля)
    try:
        existing = json.loads(log_path.read_text()) if log_path.exists() else {}
        entries = existing.get("entries", [])
        if not isinstance(entries, list):
            entries = []
    except Exception:
        entries = {}

    # Normalise the state to its plain value. RegimeState is a (str, Enum); under
    # Python 3.11+ str(RegimeState.ENTER) is "RegimeState.ENTER" (the repr), not
    # "ENTER" — which would break readers that compare against "ENTER"/"EXIT".
    _state = regime_result.get("state", "UNKNOWN")
    _state_str = getattr(_state, "value", None) or str(_state)

    entry = {
        "state": _state_str,
        "reason": regime_result.get("reason", ""),
        "signals": regime_result.get("signals", {}),
        "timestamp": regime_result.get(
            "timestamp", clock.utcnow().isoformat() + "Z"
        ),
        "previous_state": previous_state,
    }
    entries.append(entry)

    # Кольцевой буфер: последние 500 записей
    if len(entries) > 500:
        entries = entries[-500:]

    updated = {
        "version": "1.0",
        "description": "Engine B (Carry/HY) regime change log",
        "current_state": _state_str,
        "last_updated": clock.utcnow().isoformat() + "Z",
        "entries": entries,
    }

    # Атомарная запись через канонический atomic_save (P3-9).
    # Байт-идентично для сериализуемого payload (indent=2).
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(updated, str(log_path))
