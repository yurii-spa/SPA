"""MP-308: Incident Commander Agent.

При CRITICAL-алерте (из sentinel_status.json) создаёт инцидент-пакет
в data/incidents/: контекстный снэпшот, таймлайн, черновик post-mortem
и чеклист реагирования.

ЗАПРЕЩЕНО: execute_trade, execute_fix, change_allocation, modify_policy.
Агент только пишет отчёты — не исполняет исправляющие транзакции.

Stdlib only. Атомарные записи (tmp + os.replace).
"""
from __future__ import annotations

import enum
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.agents.incident_commander")

# ─── Константы ────────────────────────────────────────────────────────────────

INCIDENTS_DIR = "incidents"
SENTINEL_STATUS_FILENAME = "sentinel_status.json"

# Контекстные файлы, которые снэпшотируются при создании инцидента
_CONTEXT_FILES = [
    "equity_curve_daily.json",
    "kill_switch_status.json",
    "adapter_orchestrator_status.json",
    "analytics_summary.json",
    "red_flags.json",
]

# Дедупликация: не создавать два инцидента одного типа в один UTC-час
_DEDUP_WINDOW_HOURS = 1


# ─── IncidentSeverity ─────────────────────────────────────────────────────────


class IncidentSeverity(str, enum.Enum):
    P1_CRITICAL = "P1_critical"
    P2_HIGH = "P2_high"
    P3_MEDIUM = "P3_medium"


# ─── Atomic IO helpers ────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default: Any = None) -> Any:
    """Читает JSON защищённо; при ошибке возвращает default (никогда не бросает)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── Context Snapshot ─────────────────────────────────────────────────────────


def _gather_context_snapshot(data_dir: Path) -> dict:
    """Читает ключевые JSON-файлы на момент создания инцидента.

    Fail-safe: отсутствующий/нечитаемый файл → пустой dict под его именем.
    """
    snapshot: dict = {}
    for filename in _CONTEXT_FILES:
        doc = _read_json(data_dir / filename, None)
        snapshot[filename] = doc if doc is not None else {}
    return snapshot


# ─── Timeline ─────────────────────────────────────────────────────────────────


def _build_timeline(data_dir: Path) -> list[dict]:
    """Строит таймлайн из audit_trail.jsonl (последние 20 событий).

    Fail-safe: при отсутствии аудит-трейла возвращает пустой список.
    """
    trail_path = data_dir / "audit_trail.jsonl"
    if not trail_path.exists():
        return []
    try:
        events: list[dict] = []
        with trail_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        events.append({
                            "ts": record.get("timestamp", ""),
                            "event": record.get("event_type", ""),
                            "source": record.get("data", {}).get("source", "audit_trail")
                            if isinstance(record.get("data"), dict) else "audit_trail",
                        })
                except (json.JSONDecodeError, KeyError):
                    continue
        # Возвращаем последние 20
        return events[-20:]
    except Exception as exc:
        log.warning("_build_timeline: failed to read audit_trail (%s)", exc)
        return []


# ─── Postmortem Draft ─────────────────────────────────────────────────────────


def _infer_alert_type(trigger_alert: dict) -> str:
    """Определяет тип алерта из его полей."""
    alert_type = str(trigger_alert.get("type") or "").lower()
    message = str(trigger_alert.get("message") or "").lower()
    source = str(trigger_alert.get("source") or "").lower()

    if alert_type:
        for keyword in ("drawdown", "gap", "credit", "depeg", "kill_switch"):
            if keyword in alert_type:
                return keyword

    # Fallback — ищем в message и source
    combined = f"{message} {source}"
    for keyword in ("drawdown", "gap", "credit", "depeg", "kill_switch"):
        if keyword in combined:
            return keyword

    return "default"


def _compute_impact(context_snapshot: dict) -> str:
    """Оценивает impact по equity curve из снэпшота."""
    equity_doc = context_snapshot.get("equity_curve_daily.json") or {}
    if not isinstance(equity_doc, dict):
        return "Impact unknown — no equity data available."

    daily = equity_doc.get("daily") or []
    if not isinstance(daily, list) or len(daily) < 2:
        return "Impact unknown — insufficient equity history."

    try:
        closes = []
        for bar in daily:
            if isinstance(bar, dict):
                v = bar.get("close_equity") or bar.get("equity") or 0.0
                try:
                    closes.append(float(v))
                except (TypeError, ValueError):
                    pass

        if len(closes) < 2:
            return "Impact unknown — cannot parse equity values."

        closes_pos = [c for c in closes if c > 0]
        if not closes_pos:
            return "Impact unknown — all equity values zero."

        peak = max(closes_pos)
        current = closes_pos[-1]
        dd_pct = (peak - current) / peak * 100.0 if peak > 0 else 0.0
        return (
            f"Equity drawdown of {dd_pct:.2f}% from peak "
            f"(peak=${peak:,.0f}, current=${current:,.0f})."
        )
    except Exception:
        return "Impact unknown — error computing equity drawdown."


def _get_contributing_factors(context_snapshot: dict) -> list[str]:
    """Собирает contributing factors из red_flags.json снэпшота."""
    factors: list[str] = []
    flags_doc = context_snapshot.get("red_flags.json") or {}
    if not isinstance(flags_doc, dict):
        return factors
    for flag in (flags_doc.get("red_flags") or []):
        if isinstance(flag, dict):
            msg = str(flag.get("message") or flag.get("type") or str(flag))
            factors.append(msg)
        elif isinstance(flag, str):
            factors.append(flag)
    return factors


def _get_action_items(alert_type: str) -> list[str]:
    """Возвращает список action items по типу инцидента."""
    actions_by_type: dict[str, list[str]] = {
        "drawdown": [
            "Review kill switch status in data/kill_switch_status.json.",
            "Verify current positions in data/current_positions.json.",
            "Check analytics for contributing factors (Sharpe, volatility).",
            "Notify stakeholders via Telegram alert.",
            "Review RiskPolicy thresholds for continued relevance.",
            "Document observations and open/close position review.",
        ],
        "gap": [
            "Verify launchd com.spa.daily_cycle is running (launchctl list).",
            "Check cycle logs: /tmp/spa_cycle.log and /tmp/spa_cycle_err.log.",
            "Attempt manual cycle run: python3 -m spa_core.paper_trading.cycle_runner.",
            "Review gap_monitor.json for gap length and affected days.",
            "Assess impact on track continuity (ADR-002 go-live requirements).",
            "Update gap_monitor.json if manual recovery performed.",
        ],
        "credit": [
            "Check Maple/Clearpool positions in data/current_positions.json.",
            "Assess exit options and liquidity for credit positions.",
            "Review adapter status for affected protocols.",
            "Escalate to human owner if exposure exceeds 5% of capital.",
            "Consider reducing T2 allocation to minimum allowed.",
            "Document credit event details and market context.",
        ],
        "depeg": [
            "Identify depegged asset and current price from adapter data.",
            "Check if kill switch has been triggered.",
            "Review exposure to depegged protocol.",
            "Escalate to human owner immediately.",
            "Monitor depeg recovery timeline.",
        ],
        "kill_switch": [
            "Verify kill_switch_active.json contents for trigger reason.",
            "Review all four trigger conditions (drawdown/red_flags/manual/sharpe).",
            "Confirm all-cash allocation is in effect.",
            "Plan deactivation only after manual review by Owner.",
            "Document trigger event timeline.",
        ],
        "default": [
            "Investigate root cause of the alert.",
            "Gather additional context from relevant data files.",
            "Escalate to human owner if cause is unclear.",
            "Monitor system for further indicators.",
            "Document findings in incident report.",
        ],
    }
    return actions_by_type.get(alert_type, actions_by_type["default"])


def _build_postmortem_draft(
    trigger_alert: dict,
    context_snapshot: dict,
    alert_type: str,
) -> dict:
    """Строит детерминированный черновик post-mortem."""
    what_happened = str(
        trigger_alert.get("message")
        or trigger_alert.get("description")
        or f"A {alert_type} alert was triggered."
    )
    impact = _compute_impact(context_snapshot)
    contributing_factors = _get_contributing_factors(context_snapshot)
    action_items = _get_action_items(alert_type)

    return {
        "what_happened": what_happened,
        "impact": impact,
        "contributing_factors": contributing_factors,
        "action_items": action_items,
    }


def _build_response_checklist(alert_type: str) -> list[str]:
    """Строит чеклист реагирования по типу инцидента."""
    checklists: dict[str, list[str]] = {
        "drawdown": [
            "[ ] Check kill switch status",
            "[ ] Verify positions are accurate",
            "[ ] Review RiskPolicy limits",
            "[ ] Notify stakeholders",
            "[ ] Document in incident log",
            "[ ] Schedule post-mortem review",
        ],
        "gap": [
            "[ ] Verify launchd service status",
            "[ ] Check error logs",
            "[ ] Attempt recovery run",
            "[ ] Assess track continuity impact",
            "[ ] Update gap_monitor.json",
            "[ ] Notify stakeholders if gap > 2h",
        ],
        "credit": [
            "[ ] Identify affected credit protocol",
            "[ ] Assess current exposure",
            "[ ] Review exit options",
            "[ ] Escalate if exposure > 5% capital",
            "[ ] Document credit event",
        ],
        "depeg": [
            "[ ] Identify depegged asset",
            "[ ] Check kill switch",
            "[ ] Review protocol exposure",
            "[ ] Escalate to owner",
            "[ ] Monitor depeg recovery",
        ],
        "kill_switch": [
            "[ ] Verify kill switch trigger reason",
            "[ ] Confirm all-cash allocation",
            "[ ] Review all trigger conditions",
            "[ ] Plan manual deactivation review",
            "[ ] Document trigger timeline",
        ],
        "default": [
            "[ ] Investigate alert cause",
            "[ ] Gather context data",
            "[ ] Escalate if needed",
            "[ ] Monitor for further indicators",
            "[ ] Document findings",
        ],
    }
    return checklists.get(alert_type, checklists["default"])


# ─── Severity mapping ─────────────────────────────────────────────────────────


def _map_severity(trigger_alert: dict) -> IncidentSeverity:
    """Маппинг severity алерта на IncidentSeverity."""
    severity = str(trigger_alert.get("severity") or "").lower()
    if severity == "critical":
        return IncidentSeverity.P1_CRITICAL
    elif severity == "high":
        return IncidentSeverity.P2_HIGH
    else:
        return IncidentSeverity.P3_MEDIUM


# ─── Public API ───────────────────────────────────────────────────────────────


def create_incident(
    trigger_alert: dict,
    data_dir: str = "data",
) -> dict:
    """Создаёт инцидент-пакет и сохраняет в data/incidents/.

    Parameters
    ----------
    trigger_alert : алерт, вызвавший инцидент
    data_dir      : путь к папке data/

    Returns
    -------
    dict — инцидент-документ (то что записано на диск)
    """
    data_path = Path(data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()
    incident_id = str(uuid.uuid4())
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    alert_type = _infer_alert_type(trigger_alert)
    severity = _map_severity(trigger_alert)
    context_snapshot = _gather_context_snapshot(data_path)
    timeline = _build_timeline(data_path)
    postmortem_draft = _build_postmortem_draft(
        trigger_alert, context_snapshot, alert_type
    )
    response_checklist = _build_response_checklist(alert_type)

    incident: dict = {
        "incident_id": incident_id,
        "created_at": now_ts,
        "severity": severity.value,
        "alert_type": alert_type,
        "trigger_alert": trigger_alert,
        "context_snapshot": context_snapshot,
        "timeline": timeline,
        "postmortem_draft": postmortem_draft,
        "response_checklist": response_checklist,
        "status": "open",
        "resolved_at": None,
    }

    # Сохраняем файл атомарно
    incidents_path = data_path / INCIDENTS_DIR
    filename = f"incident_{date_prefix}_{incident_id[:8]}.json"
    _atomic_write_json(incidents_path / filename, incident)
    log.warning(
        "Incident created: %s (severity=%s, type=%s)",
        incident_id[:8], severity.value, alert_type,
    )

    return incident


def resolve_incident(
    incident_id: str,
    data_dir: str = "data",
) -> bool:
    """Обновляет статус инцидента на 'resolved'.

    Parameters
    ----------
    incident_id : полный UUID4 или префикс (8 символов)
    data_dir    : путь к папке data/

    Returns
    -------
    bool — True если инцидент найден и обновлён
    """
    data_path = Path(data_dir)
    incidents_path = data_path / INCIDENTS_DIR

    if not incidents_path.is_dir():
        log.warning("resolve_incident: incidents directory not found: %s", incidents_path)
        return False

    # Ищем файл инцидента по incident_id (полный или префикс)
    for incident_file in sorted(incidents_path.glob("incident_*.json")):
        try:
            doc = _read_json(incident_file, None)
            if not isinstance(doc, dict):
                continue
            stored_id = str(doc.get("incident_id") or "")
            if stored_id == incident_id or stored_id.startswith(incident_id):
                if doc.get("status") == "resolved":
                    log.info(
                        "resolve_incident: %s already resolved", incident_id[:8]
                    )
                    return True
                doc["status"] = "resolved"
                doc["resolved_at"] = datetime.now(timezone.utc).isoformat()
                _atomic_write_json(incident_file, doc)
                log.info(
                    "resolve_incident: %s resolved", incident_id[:8]
                )
                return True
        except Exception as exc:
            log.warning(
                "resolve_incident: error processing %s (%s)", incident_file.name, exc
            )
            continue

    log.warning("resolve_incident: incident %s not found", incident_id[:8])
    return False


def list_open_incidents(data_dir: str = "data") -> list[dict]:
    """Возвращает список всех открытых инцидентов.

    Returns
    -------
    list[dict] — отсортировано по created_at (новейшие первыми)
    """
    data_path = Path(data_dir)
    incidents_path = data_path / INCIDENTS_DIR

    if not incidents_path.is_dir():
        return []

    open_incidents: list[dict] = []
    for incident_file in sorted(incidents_path.glob("incident_*.json")):
        try:
            doc = _read_json(incident_file, None)
            if isinstance(doc, dict) and doc.get("status") == "open":
                open_incidents.append(doc)
        except Exception as exc:
            log.warning(
                "list_open_incidents: error reading %s (%s)", incident_file.name, exc
            )
            continue

    # Сортируем по created_at (новейшие первыми)
    open_incidents.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return open_incidents


def run_incident_check(data_dir: str = "data") -> dict:
    """Проверяет sentinel_status.json и создаёт инцидент при critical.

    Дедупликация: не создавать два инцидента одного типа в один UTC-час.

    Returns
    -------
    dict — {"checked_at", "action", "incident_id" (если создан), "reason"}
    """
    data_path = Path(data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()
    now_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    sentinel_doc = _read_json(data_path / SENTINEL_STATUS_FILENAME, {})
    if not isinstance(sentinel_doc, dict):
        return {
            "checked_at": now_ts,
            "action": "skip",
            "reason": "sentinel_status.json missing or invalid",
        }

    status = str(sentinel_doc.get("status") or "").lower()
    if status != "critical":
        return {
            "checked_at": now_ts,
            "action": "skip",
            "reason": f"status={status!r} — not critical, no incident needed",
        }

    # Статус critical — ищем подходящий алерт
    # Берём первый critical-алерт из sentinel_status как триггер
    trigger_alert: dict = {
        "source": "sentinel",
        "severity": "critical",
        "message": "Critical status detected by Risk Sentinel",
        "type": "default",
    }

    # Определяем тип инцидента из sentinel_status
    by_class = sentinel_doc.get("by_class") or {}
    alert_type = "default"

    # Пытаемся определить тип из kill_switch_triggered или общего состояния
    if sentinel_doc.get("kill_switch_triggered"):
        alert_type = "kill_switch"
        trigger_alert.update({
            "type": "kill_switch",
            "message": "Kill switch triggered (detected by Risk Sentinel)",
            "kill_switch_active": True,
        })
    else:
        # Пробуем прочитать alerts для определения типа
        risk_doc = _read_json(data_path / "risk_alerts.json", {})
        if isinstance(risk_doc, dict):
            for a in (risk_doc.get("alerts") or []):
                if isinstance(a, dict) and str(a.get("severity") or "").lower() == "critical":
                    trigger_alert = a
                    alert_type = _infer_alert_type(a)
                    break

    # Дедупликация: проверяем инциденты за последний час
    incidents_path = data_path / INCIDENTS_DIR
    if incidents_path.is_dir():
        for incident_file in sorted(incidents_path.glob("incident_*.json"),
                                    reverse=True)[:20]:
            try:
                doc = _read_json(incident_file, None)
                if not isinstance(doc, dict):
                    continue
                created_at = str(doc.get("created_at") or "")
                stored_type = str(doc.get("alert_type") or "default")
                # Сравниваем UTC-час
                if (created_at.startswith(now_hour)
                        and stored_type == alert_type
                        and doc.get("status") == "open"):
                    return {
                        "checked_at": now_ts,
                        "action": "deduplicated",
                        "incident_id": doc.get("incident_id"),
                        "reason": (
                            f"Incident of type={alert_type!r} already exists "
                            f"for hour {now_hour}"
                        ),
                    }
            except Exception:
                continue

    # Создаём новый инцидент
    incident = create_incident(trigger_alert, data_dir=data_dir)
    return {
        "checked_at": now_ts,
        "action": "created",
        "incident_id": incident["incident_id"],
        "reason": (
            f"Critical alert detected (type={alert_type!r}), "
            f"incident {incident['incident_id'][:8]} created"
        ),
    }
