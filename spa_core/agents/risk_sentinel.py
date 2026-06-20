"""MP-303: Risk Sentinel Agent — детерминированный fast-loop sentinel.

Запускается каждый цикл (every_cycle). Читает risk_alerts.json,
red_flags.json, kill_switch_status.json, классифицирует алерты по четырём
классам и при critical инициирует детерминированную ветку kill-switch.

КОНСТИТУЦИОННЫЙ ИНВАРИАНТ: LLM SDK в этом файле ЗАПРЕЩЁН (risk-домен).
Единственная точка входа для LLM — инжектируемый llm_fn в classify_with_llm,
который деградирует на детерминированный fallback при llm_fn=None.

Stdlib only. Атомарные записи (tmp + os.replace).
"""
from __future__ import annotations

import enum
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.agents.risk_sentinel")

# ─── Константы ────────────────────────────────────────────────────────────────

SENTINEL_STATUS_FILENAME = "sentinel_status.json"

# Источники, которые повышают severity при low (не шум)
_HIGH_SEVERITY_SOURCES = frozenset({"gap_monitor", "kill_switch"})

# Порог просадки для incident (3%) и critical (5%) из rule-set
_INCIDENT_DRAWDOWN_PCT = 3.0
_CRITICAL_DRAWDOWN_PCT = 5.0

# Порог деградированных адаптеров для класса degradation
_DEGRADED_ADAPTER_THRESHOLD = 2


# ─── AlertClass ───────────────────────────────────────────────────────────────


class AlertClass(str, enum.Enum):
    """Четыре класса серьёзности алерта."""

    NOISE = "noise"
    DEGRADATION = "degradation"
    INCIDENT = "incident"
    CRITICAL = "critical"


# ─── Atomic IO helpers ────────────────────────────────────────────────────────



def _read_json(path: Path, default: Any = None) -> Any:
    """Читает JSON защищённо; при ошибке возвращает default."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── Классификация алертов ────────────────────────────────────────────────────


def classify_alert(alert: dict) -> AlertClass:
    """Детерминированная классификация одного алерта.

    Правила (применяются в порядке убывания серьёзности):
    - critical : severity="critical"  OR  kill_switch_active=True
                 OR  drawdown_pct > 5%
    - incident : severity="high"      OR  drawdown_pct > 3%
    - degradation: severity="medium"
    - noise    : severity="low"  AND  source НЕ в ["gap_monitor","kill_switch"]

    Если severity="low" и source в high-severity-sources → degradation.
    Неизвестный severity → degradation (conservative default).
    """
    if not isinstance(alert, dict):
        return AlertClass.NOISE

    severity = str(alert.get("severity") or "").lower().strip()
    source = str(alert.get("source") or "").lower().strip()
    drawdown = 0.0
    raw_dd = alert.get("drawdown_pct") or alert.get("drawdown") or 0.0
    try:
        drawdown = float(raw_dd)
    except (TypeError, ValueError):
        drawdown = 0.0

    # Проверяем kill_switch_active флаг в самом алерте
    kill_switch_active = bool(alert.get("kill_switch_active") or
                              alert.get("kill_switch_triggered") or False)

    # Critical ─ наивысший приоритет
    if (severity == "critical"
            or kill_switch_active
            or drawdown > _CRITICAL_DRAWDOWN_PCT):
        return AlertClass.CRITICAL

    # Incident
    if severity == "high" or drawdown > _INCIDENT_DRAWDOWN_PCT:
        return AlertClass.INCIDENT

    # Degradation
    if severity == "medium":
        return AlertClass.DEGRADATION

    # Noise или special-source low
    if severity == "low":
        if source in _HIGH_SEVERITY_SOURCES:
            return AlertClass.DEGRADATION
        return AlertClass.NOISE

    # Неизвестный severity → conservative fallback
    return AlertClass.DEGRADATION


def classify_with_llm(
    alert: dict,
    llm_fn: Optional[Callable[[str], str]] = None,
) -> AlertClass:
    """LLM-enhanced классификация с детерминированным fallback.

    Parameters
    ----------
    alert   : алерт (dict)
    llm_fn  : callable(prompt: str) -> str  или  None.
              При None → возвращает classify_alert(alert) без вызова LLM.
              Ожидаемый ответ LLM: одна из строк "noise" / "degradation" /
              "incident" / "critical".  Невалидный ответ → fallback.

    Returns
    -------
    AlertClass
    """
    if llm_fn is None:
        return classify_alert(alert)

    # Строим промпт для LLM
    prompt = (
        "Classify the following SPA risk alert into exactly one category: "
        "noise, degradation, incident, or critical.\n"
        "Respond with only the category name.\n\n"
        f"Alert: {json.dumps(alert, ensure_ascii=False)}"
    )
    try:
        response = llm_fn(prompt)
        response_clean = str(response).strip().lower()
        # Парсим ответ
        for cls in AlertClass:
            if cls.value in response_clean:
                return cls
        # Невалидный ответ LLM → детерминированный fallback
        log.warning(
            "classify_with_llm: invalid LLM response %r — falling back to "
            "deterministic classify_alert",
            response,
        )
        return classify_alert(alert)
    except Exception as exc:
        log.warning(
            "classify_with_llm: LLM call failed (%s) — falling back to "
            "deterministic classify_alert",
            exc,
        )
        return classify_alert(alert)


# ─── Sentinel Cycle ───────────────────────────────────────────────────────────


def _count_degraded_adapters(data_dir: Path) -> int:
    """Считает адаптеры со статусом != 'ok' из adapter_orchestrator_status.json.

    Fail-safe: при отсутствии файла возвращает 0.
    """
    orch = _read_json(data_dir / "adapter_orchestrator_status.json", {})
    if not isinstance(orch, dict):
        return 0
    adapters = orch.get("adapters") or []
    if not isinstance(adapters, list):
        return 0
    count = 0
    for entry in adapters:
        if isinstance(entry, dict):
            status = str(entry.get("status") or "").lower()
            if status and status != "ok":
                count += 1
    return count


def _collect_alerts(data_dir: Path) -> list[dict]:
    """Собирает алерты из всех источников.

    Источники: risk_alerts.json, red_flags.json, kill_switch_status.json.
    Fail-safe: недоступный файл → пустой список.
    """
    alerts: list[dict] = []

    # 1. risk_alerts.json
    risk_doc = _read_json(data_dir / "risk_alerts.json", {})
    if isinstance(risk_doc, dict):
        for a in (risk_doc.get("alerts") or []):
            if isinstance(a, dict):
                alerts.append(a)
    elif isinstance(risk_doc, list):
        for a in risk_doc:
            if isinstance(a, dict):
                alerts.append(a)

    # 2. red_flags.json → каждый флаг как алерт со severity="high"
    flags_doc = _read_json(data_dir / "red_flags.json", {})
    if isinstance(flags_doc, dict):
        for flag in (flags_doc.get("red_flags") or []):
            if isinstance(flag, dict):
                synthetic = {
                    "source": "red_flags",
                    "severity": flag.get("severity") or "high",
                    "message": flag.get("message") or str(flag),
                    "type": flag.get("type") or "red_flag",
                }
                alerts.append(synthetic)
            elif isinstance(flag, str):
                alerts.append({
                    "source": "red_flags",
                    "severity": "high",
                    "message": flag,
                    "type": "red_flag",
                })

    # 3. kill_switch_status.json → если triggered, добавляем synthetic critical
    ks_doc = _read_json(data_dir / "kill_switch_status.json", {})
    if isinstance(ks_doc, dict) and ks_doc.get("triggered"):
        alerts.append({
            "source": "kill_switch",
            "severity": "critical",
            "message": ks_doc.get("reason") or "kill switch triggered",
            "type": "kill_switch",
            "kill_switch_active": True,
        })

    return alerts


def run_sentinel_cycle(data_dir: str = "data") -> dict:
    """Основной цикл Risk Sentinel Agent.

    1. Собирает алерты из risk_alerts.json, red_flags.json,
       kill_switch_status.json.
    2. Классифицирует каждый алерт детерминированно.
    3. Учитывает деградацию адаптеров (>= 2 ненормальных → degradation bump).
    4. При наличии critical-алертов вызывает run_kill_switch_check (fail-safe).
    5. Пишет data/sentinel_status.json атомарно.

    Returns
    -------
    dict с ключами:
        checked_at, total_alerts, by_class, kill_switch_triggered, status
    """
    data_path = Path(data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()

    # Счётчики классов
    by_class: dict[str, int] = {
        AlertClass.NOISE.value: 0,
        AlertClass.DEGRADATION.value: 0,
        AlertClass.INCIDENT.value: 0,
        AlertClass.CRITICAL.value: 0,
    }

    # Сбор и классификация алертов
    alerts = _collect_alerts(data_path)
    classified: list[dict] = []
    for alert in alerts:
        cls = classify_alert(alert)
        by_class[cls.value] += 1
        classified.append({"alert": alert, "class": cls.value})

    # Проверяем деградацию адаптеров
    degraded_count = _count_degraded_adapters(data_path)
    if degraded_count >= _DEGRADED_ADAPTER_THRESHOLD:
        # Добавляем synthetic degradation-алерт
        synth = {
            "source": "adapter_orchestrator",
            "severity": "medium",
            "message": (
                f"{degraded_count} adapters degraded "
                f"(threshold={_DEGRADED_ADAPTER_THRESHOLD})"
            ),
            "type": "adapter_degradation",
            "degraded_count": degraded_count,
        }
        cls = classify_alert(synth)
        by_class[cls.value] += 1
        classified.append({"alert": synth, "class": cls.value})

    total = len(classified)

    # Определяем итоговый статус
    kill_switch_triggered = False
    if by_class[AlertClass.CRITICAL.value] > 0:
        # Детерминированная ветка kill-switch
        kill_switch_triggered = _run_kill_switch_safe(data_path)
        status = "critical"
    elif by_class[AlertClass.INCIDENT.value] > 0:
        status = "incident"
    elif by_class[AlertClass.DEGRADATION.value] > 0:
        status = "degraded"
    else:
        status = "ok"

    result: dict = {
        "checked_at": now_ts,
        "total_alerts": total,
        "by_class": dict(by_class),
        "kill_switch_triggered": kill_switch_triggered,
        "status": status,
    }

    # Атомарная запись sentinel_status.json
    try:
        atomic_save(result, str(data_path / SENTINEL_STATUS_FILENAME))
    except Exception as exc:
        log.error("run_sentinel_cycle: failed to write sentinel_status.json: %s", exc)

    return result


def _run_kill_switch_safe(data_path: Path) -> bool:
    """Вызывает run_kill_switch_check fail-safe (исключение не валит цикл).

    Returns
    -------
    bool — True если kill-switch сработал (triggered=True).
    """
    try:
        from spa_core.governance.kill_switch import run_kill_switch_check
        result = run_kill_switch_check(data_dir=str(data_path))
        return bool(result.get("triggered", False))
    except Exception as exc:
        log.error(
            "_run_kill_switch_safe: kill_switch check failed (%s) — "
            "continuing sentinel cycle",
            exc,
        )
        return False
