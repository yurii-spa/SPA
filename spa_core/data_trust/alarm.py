"""
DataTrust Alarm System — отслеживает стейл/дивергентные данные.
LLM_FORBIDDEN. fail-closed: alarm → log + (optional) Telegram.

Интеграция с валидатором:
  alarm = process_validation_result(metric, status.value, result.details)

Стратегия записи: ring-buffer 100 алармов, атомарные записи (tmp + os.replace).
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Optional, Dict, List
from pathlib import Path
import json
import os
import tempfile
from spa_core.utils import clock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALARM_LOG = _PROJECT_ROOT / "data" / "datatrust_alarm_log.json"

ALARM_VERSION = "alarm_v1.0"
_RING_BUFFER_SIZE = 100  # максимум алармов в логе


class AlarmLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class DataAlarm:
    """Тревога о проблеме с данными."""
    alarm_id: str
    level: AlarmLevel
    metric: str
    source: str
    message: str
    signal: str   # "stale" | "divergent" | "missing" | "out_of_range" | "fail_closed"
    created_at: str
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "alarm_id": self.alarm_id,
            "level": self.level.value,  # .value → "warn"/"critical"/"info" (str(Enum) даёт "AlarmLevel.WARN" в Py3.10)
            "metric": self.metric,
            "source": self.source,
            "message": self.message,
            "signal": self.signal,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


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


def create_alarm(
    metric: str,
    signal: str,
    message: str,
    source: str = "datatrust",
    level: AlarmLevel = AlarmLevel.WARN,
) -> "DataAlarm":
    """
    Создаёт новый DataAlarm и записывает в ring-buffer лог.
    LLM_FORBIDDEN. fail-closed.
    """
    # LLM_FORBIDDEN
    now = clock.utcnow().isoformat() + "Z"
    alarm_id = f"DT-{metric[:10]}-{int(clock.utcnow().timestamp())}"

    alarm = DataAlarm(
        alarm_id=alarm_id,
        level=level,
        metric=metric,
        source=source,
        message=message,
        signal=signal,
        created_at=now,
    )

    # Лог (ring-buffer 100)
    try:
        log = json.loads(_ALARM_LOG.read_text(encoding="utf-8")) if _ALARM_LOG.exists() else {"alarms": []}
    except Exception:
        log = {"alarms": []}

    alarms = log.get("alarms", [])
    alarms.append(alarm.to_dict())
    # ring-buffer: обрезаем старые
    if len(alarms) > _RING_BUFFER_SIZE:
        alarms = alarms[-_RING_BUFFER_SIZE:]

    log["alarms"] = alarms
    log["last_updated"] = now
    log["version"] = ALARM_VERSION
    log["total_count"] = log.get("total_count", 0) + 1

    _atomic_write(_ALARM_LOG, json.dumps(log, indent=2))

    return alarm


def send_alarm_telegram(alarm: "DataAlarm") -> bool:
    """
    Отправляет alarm в Telegram через spa_core.alerts.telegram_client.
    LLM_FORBIDDEN. Non-blocking: ошибка → False (не падает).
    Secrets — только через macOS Keychain (не в файлах, SECRETS POLICY).
    """
    # LLM_FORBIDDEN
    # Phase-1 Telegram rebuild: a CRITICAL data-trust alarm (data corruption /
    # fail-closed) is a genuine Tier-1 interrupt → push_policy ``system_critical``
    # (edge-triggered). WARN/INFO alarms are advisory → digest queue, never
    # pushed. Never raises.
    try:
        from spa_core.telegram import push_policy
        body = (
            f"Metric: {alarm.metric}\n"
            f"Signal: {alarm.signal}\n"
            f"Level: {alarm.level}\n"
            f"Message: {alarm.message}\n"
            f"Time: {alarm.created_at}"
        )
        if alarm.level == AlarmLevel.CRITICAL:
            return bool(
                push_policy.push_critical(
                    "system_critical", "CRITICAL", "DataTrust Alarm", body,
                )
            )
        push_policy.enqueue_digest(
            "data_trust", "DataTrust alarm", body,
            severity=str(alarm.level), reason="data_trust_alarm_advisory",
        )
        return False
    except Exception:  # noqa: BLE001 — alarm must never crash callers
        return False


def process_validation_result(
    metric: str,
    signal: str,
    details: str,
    send_telegram: bool = True,
) -> Optional["DataAlarm"]:
    """
    Обрабатывает результат валидации: если signal != "ok" → создаёт alarm.

    signal может быть:
      "ok"           → None (нет аларма)
      "stale"        → WARN
      "divergent"    → WARN
      "alarm"        → WARN  (сигнал от validator при divergence)
      "missing"      → CRITICAL
      "out_of_range" → CRITICAL
      "fail_closed"  → CRITICAL
      "exit"         → CRITICAL  (обобщённый сигнал validator)

    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if signal == "ok":
        return None

    _critical_signals = {"missing", "out_of_range", "fail_closed", "exit"}
    level = AlarmLevel.CRITICAL if signal in _critical_signals else AlarmLevel.WARN

    alarm = create_alarm(
        metric=metric,
        signal=signal,
        message=details[:200],  # обрезаем длинные сообщения
        level=level,
    )

    # Telegram только для CRITICAL — WARN пишется тихо
    if send_telegram and level == AlarmLevel.CRITICAL:
        send_alarm_telegram(alarm)

    return alarm


def get_active_alarms(lookback_hours: int = 24) -> List["DataAlarm"]:
    """
    Возвращает неразрешённые alarms за последние N часов.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if not _ALARM_LOG.exists():
        return []

    try:
        log = json.loads(_ALARM_LOG.read_text(encoding="utf-8"))
        alarms = log.get("alarms", [])
        cutoff_str = (clock.utcnow() - timedelta(hours=lookback_hours)).isoformat()

        active = [
            DataAlarm(
                alarm_id=a["alarm_id"],
                level=AlarmLevel(a["level"]),
                metric=a["metric"],
                source=a["source"],
                message=a["message"],
                signal=a["signal"],
                created_at=a["created_at"],
                resolved_at=a.get("resolved_at"),
            )
            for a in alarms
            if a.get("resolved_at") is None and a.get("created_at", "") >= cutoff_str
        ]
        return active
    except Exception:
        return []
