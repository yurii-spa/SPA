"""Owner language (ADR-612) — ONE mapping layer from technical codes to plain Russian.

Director OS shows two layers on every card:

* **owner layer** — what happened and what it means, in plain Russian, no codes;
* **evidence layer** — the technical reason exactly as the producer wrote it (``reason``,
  ``detail``, the code itself), inside an expandable «технические подробности».

This module produces ONLY the owner layer. It never reads a file, never computes a status and
never upgrades one: it is handed a status/code the producer already measured and says it in
words. Three rules, each pinned by ``spa_core/tests/test_mission_owner_language.py``:

1. every code a producer can emit has a phrase here (the test enumerates the producers'
   vocabularies — scope names × statuses, problem families, Tier-1 incident keys, site-freshness
   codes, data-health check names) — a new code without a phrase is a red test;
2. an UNKNOWN code is said as «неизвестная причина», with the raw code left for the evidence
   layer, and its tone is never ``ok`` — not understanding a code is not a green state;
3. nothing here may turn UNKNOWN / NOT_MEASURED / STALE / CORRUPT into an OK-sounding phrase.

Stdlib only, deterministic, no LLM.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

#: tone of a phrase — the UI picks a badge colour from it; "ok" is reserved for producer-OK states
TONES = ("ok", "warn", "alert", "unknown")

UNKNOWN_CODE_RU = "неизвестная причина — что именно это значит, не расшифровано (код в подробностях)"

# ── readiness scopes (readiness_scopes.SCOPES × statuses) ───────────────────────────────────────
SCOPE_STATUS_RU: dict[tuple[str, str], tuple[str, str]] = {
    ("INVESTMENT_ENGINE_READINESS", "READY"): (
        "ok", "Проверка говорит: условия для перехода на реальные деньги выполнены. Решение всё равно за вами."),
    ("INVESTMENT_ENGINE_READINESS", "NOT_READY"): (
        "warn", "Условия для реальных денег не выполнены — для бумажной стадии так и задумано."),
    ("STUDIO_OS_HEALTH", "OK"): ("ok", "Агенты работают нормально."),
    ("STUDIO_OS_HEALTH", "WARN"): ("warn", "Часть агентов с предупреждениями — работа идёт, но есть что чинить."),
    ("STUDIO_OS_HEALTH", "CRITICAL"): ("alert", "Есть агенты в аварии — часть работы стоит."),
    ("PRODUCT_DATA_HEALTH", "OK"): ("ok", "Данные трека согласованы между файлами."),
    ("PRODUCT_DATA_HEALTH", "WARN"): (
        "warn", "Данные трека между файлами расходятся — пока это предупреждение, не авария."),
    ("PRODUCT_DATA_HEALTH", "CRITICAL"): (
        "alert", "Данные трека между файлами расходятся — система не считает их готовыми."),
    ("PUBLICATION_HEALTH", "OK"): ("ok", "Сайт показывает свежие и подтверждённые числа."),
    ("PUBLICATION_HEALTH", "WARN"): ("warn", "У сайта есть замечания: свежесть или подтверждение чисел."),
    ("PUBLICATION_HEALTH", "CRITICAL"): (
        "alert", "Публикация сайта застряла или число на сайте не подтверждено."),
    # review P1-4: what this scope measures is the bot's 300-s LIVENESS beacon
    # (readiness_scopes imports telegram_health.BEACON_MAX_AGE_S). Liveness ≠ «buttons work»:
    # button gating is a separate 6-h capability-list rule (alert_actions.BEACON_MAX_AGE_S, ADR-400).
    ("OWNER_CONTROL_HEALTH", "OK"): (
        "ok", "Бот жив — признак жизни свежий. Работают ли кнопки, проверяется отдельно (по списку умений бота)."),
    ("OWNER_CONTROL_HEALTH", "DEGRADED"): (
        "warn", "Бот давно не подавал признаков жизни — команды и кнопки могут не отвечать."),
    ("PUBLIC_SURFACE", "OK"): (
        "ok", "Посетитель сайта видит счётчик критериев go-live — это инвентарь, не готовность к деньгам."),
}

#: statuses every scope can return whatever its subject (handled before the per-scope table)
GENERIC_STATUS_RU: dict[str, tuple[str, str]] = {
    "UNKNOWN": ("unknown", "Не измерено"),
    "CORRUPT": ("alert", "Отметка времени из будущего — этим данным не верю"),
}

WHY_RU = {
    "missing": "нет файла с замером",
    "stale": "замер устарел",
    "future": "отметка времени из будущего",
    "no_field": "в замере нет нужного поля",
    "unknown_value": "замер вернул значение, которое прибор не знает",
}

#: execution_readiness.live_blockers — free text from the audit; known ones said plainly
LIVE_BLOCKER_RU = {
    "custody/MPC not connected": "не подключено хранение ключей (custody/MPC)",
    "external audit pending": "не пройден внешний аудит",
    "SPA_EXECUTION_MODE not enabled": "режим исполнения выключен (так и задумано на бумаге)",
}
OWNER_GATE_RU = {"custody": "хранение ключей", "audit": "аудит", "legal": "юридическое заключение"}

# ── data-health checks (cycle_health.json + audit/data_integrity.py) ────────────────────────────
CHECK_RU = {
    # cycle_health.json
    "cycle_gap": "дневной цикл запускается вовремя",
    "equity_anomaly": "нет резких скачков капитала",
    "data_freshness": "входные данные свежие",
    "evidence_vs_curve": "журнал доказательств совпадает с кривой капитала",
    "artifact_integrity": "файлы трека целы",
    "replay_from_inputs": "результат цикла воспроизводится из его входов",
    "sleeve_replay": "результаты рукавов воспроизводятся из входов",
    "book_commitments": "заявленные заранее решения книг совпадают с исполненными",
    # audit/data_integrity.py
    "equity_continuity": "в кривой капитала нет пропущенных дней",
    "positions_consistency": "позиции сходятся с капиталом",
    "allocation_policy_bounds": "раскладка в пределах правил риска",
    "freshness": "файлы состояния свежие",
    "anchor_coverage": "журнал можно восстановить из внешней контрольной точки",
    "schema_sanity": "файлы состояния читаются и имеют правильный формат",
}
CHECK_STATUS_RU = {
    "OK": ("ok", "проверено: {what}"), "HEALTHY": ("ok", "проверено: {what}"), "ok": ("ok", "проверено: {what}"),
    "WARNING": ("warn", "под сомнением: {what}"), "warn": ("warn", "под сомнением: {what}"),
    "STALE": ("warn", "давно не перепроверялось: {what}"),
    "CRITICAL": ("alert", "проверка не прошла: {what}"), "FAIL": ("alert", "проверка не прошла: {what}"),
    "fail": ("alert", "проверка не прошла: {what}"),
    "UNCHECKED": ("unknown", "не проверено, что {what}"), "skip": ("unknown", "не проверено, что {what}"),
    "NOT_MEASURED": ("unknown", "не проверено, что {what}"),
}

# ── site freshness codes (scripts/site_freshness_monitor.py) ────────────────────────────────────
SITE_CODE_RU = {
    "COMPARISON_NOT_MEASURED": "не удалось сверить сайт с живыми данными",
    "HONESTY_PLAQUE_UNDELIVERED": "пометка честности не доехала до сайта",
    "MISSING_ASOF": "у числа на сайте нет даты замера",
    "OVERSTATED_METRIC": "число на сайте выше подтверждённого",
    "PUBLISHER_STUCK": "публикация сайта застряла",
    "SHELF_NOT_ON_ORIGIN": "свежая витрина чисел не доставлена в git",
    "SHELF_OVERDUE": "недельная публикация чисел просрочена",
    "SHELF_UNREADABLE": "витрина чисел не читается",
    "SITE_BEHIND_SNAPSHOT": "сайт показывает данные старше последнего снимка",
    "SNAPSHOT_BEHIND_API": "снимок для сайта отстаёт от живого API",
    "STALE_API": "живой API давно не обновлялся",
    "STALE_SNAPSHOT": "снимок для сайта устарел",
    "UNAVAILABLE": "данные для сайта недоступны",
    "VERIFIER_PIN_MISMATCH": "проверка сайта прочитала не тот замер",
}

# ── Tier-1 incident keys (telegram/push_policy.TIER1_WHITELIST) ─────────────────────────────────
INCIDENT_RU = {
    "kill_switch": ("alert", "сработал стоп-кран по просадке"),
    "cycle_failed": ("alert", "дневной цикл упал или не запустился"),
    "cycle_gap": ("alert", "дневной цикл пропущен"),
    "system_critical": ("alert", "критичная авария системы"),
    "agent_health_critical": ("alert", "здоровье агентов в критичном состоянии"),
    "core_agent_down": ("alert", "лежит агент, без которого не работает дневной цикл"),
    "peg_break": ("alert", "стейблкоин в портфеле потерял привязку к доллару"),
    "red_flag": ("alert", "взлом или эксплойт у протокола в портфеле"),
    "rules_critical": ("alert", "критичное нарушение правил"),
    "golive_ready": ("warn", "готовность к go-live изменилась на «готово» — решение за вами"),
    "pilot_request": ("warn", "пришла важная заявка на пилот"),
    "architecture_conformance_critical": ("alert", "запущенные агенты разошлись с объявленной архитектурой"),
    "telegram_down": ("alert", "связь с вами через Telegram сломана"),
    "checkpoint_failed": ("alert", "недельная контрольная проверка не прошла"),
    "resource_critical": ("alert", "на Маке почти закончились диск или память"),
    "site_publisher_stuck": ("alert", "публикация сайта застряла"),
}

# ── problem-store families (monitoring/problem_store.py) ────────────────────────────────────────
#: system_health domains — the wording the daily Telegram report already used (moved here so the
#: report and the cockpit say the same thing; ``telegram/reports/daily.py`` imports this table)
SYSTEM_DOMAIN_RU = {
    "d1_data_pipeline": "данные",
    "d2_connectivity": "связь",
    "d3_strategy_quality": "качество стратегий",
    "d4_external": "внешние сервисы",
    "d5_code_integrity": "целостность кода",
    "d6_risk_gates": "риск-гейты",
    "d7_hygiene": "гигиена",
    "d_dfb_defi_board": "доска DeFi",
    "d_riskwire": "лента рисков (RiskWire)",
}
PROBLEM_FAMILY_RU = {
    "exit_nonzero": "агент «{agent}» завершается с ошибкой (код {n})",
    "stale_log": "агент «{agent}» давно ничего не пишет в журнал — возможно, завис или не запускается",
    "retired_but_loaded": "отключённые агенты всё ещё запущены: {names}",
    "domains_degraded": "проверка здоровья предупреждает в областях: {names}",
    "publication_behind": "сайт отстаёт от свежих данных",
}


def _agent_short(agent: Any) -> str:
    return str(agent or "?").replace("com.spa.", "")


def _n(v: Any) -> str:
    """86.0 → «86»; a missing number stays visibly missing, never 0."""
    if isinstance(v, bool) or v is None:
        return "?"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _join_ru(items: Iterable[str]) -> str:
    items = [i for i in items if i]
    return ", ".join(items) if items else "—"


def scope_plain(item: dict) -> dict:
    """``{"tone", "text"}`` for one ``readiness_scopes`` item — status + ``facts``, never ``reason``."""
    scope = str(item.get("scope") or "")
    status = str(item.get("status") or "UNKNOWN")
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    if status in GENERIC_STATUS_RU:
        tone, head = GENERIC_STATUS_RU[status]
        why = WHY_RU.get(facts.get("why"))
        return {"tone": tone, "text": f"{head}: {why}." if why else f"{head}."}
    entry = SCOPE_STATUS_RU.get((scope, status))
    if entry is None:
        return {"tone": "unknown", "text": f"Состояние «{status}» — {UNKNOWN_CODE_RU}."}
    tone, text = entry
    extra = _scope_extra(scope, facts)
    return {"tone": tone, "text": f"{text} {extra}".strip()}


def _scope_extra(scope: str, f: dict) -> str:
    if scope == "INVESTMENT_ENGINE_READINESS":
        parts = []
        lb = [LIVE_BLOCKER_RU.get(b, b) for b in (f.get("live_blockers") or [])]
        if lb:
            parts.append("Не выполнено: " + _join_ru(lb) + ".")
        gates = [OWNER_GATE_RU.get(g, g) for g in (f.get("open_owner_gates") or [])]
        if gates:
            parts.append(f"Ваших решений открыто: {len(gates)} ({_join_ru(gates)}).")
        return " ".join(parts)
    if scope == "STUDIO_OS_HEALTH" and f.get("total") is not None:
        return (f"В норме {_n(f.get('healthy'))} из {_n(f.get('total'))}, с предупреждениями "
                f"{_n(f.get('warning'))}, в аварии {_n(f.get('critical'))}.")
    if scope == "PRODUCT_DATA_HEALTH":
        parts = []
        if f.get("divergent_days") is not None and f.get("compared_days") is not None:
            parts.append(f"Расходятся {_n(f['divergent_days'])} из {_n(f['compared_days'])} сверенных дней.")
        for name in ("evidence_vs_curve", "artifact_integrity"):
            st = f.get(name)
            if st is not None:
                parts.append(check_plain(name, st)["text"].capitalize() + ".")
        return " ".join(parts)
    if scope == "PUBLICATION_HEALTH" and f.get("codes"):
        return "Замечания: " + _join_ru(SITE_CODE_RU.get(c, f"{UNKNOWN_CODE_RU} ({c})") for c in f["codes"]) + "."
    if scope == "OWNER_CONTROL_HEALTH" and f.get("beacon_age_s") is not None:
        lim = f.get("beacon_max_age_s")
        norm = f" (норма — не старше {_n(lim / 60.0) if isinstance(lim, (int, float)) else '?'} мин)"
        return f"Последний признак жизни: {age_ru(f['beacon_age_s'] / 60.0)}{norm}."
    if scope == "PUBLIC_SURFACE" and f.get("gates_total") is not None:
        return f"Показано {_n(f.get('gates_passed'))}/{_n(f.get('gates_total'))} на {f.get('as_of') or '?'}."
    return ""


def check_plain(name: str, status: Any) -> dict:
    """A data-health check result — «не проверено, что журнал можно восстановить…», never «ok»
    for a check that did not run."""
    what = CHECK_RU.get(str(name))
    if what is None:
        return {"tone": "unknown", "text": f"проверка «{name}»: {UNKNOWN_CODE_RU}"}
    entry = CHECK_STATUS_RU.get(str(status))
    if entry is None:
        return {"tone": "unknown", "text": f"не проверено, что {what} (статус «{status}» не расшифрован)"}
    tone, tpl = entry
    return {"tone": tone, "text": tpl.format(what=what)}


def incident_plain(event_key: Any) -> dict:
    entry = INCIDENT_RU.get(str(event_key or ""))
    if entry is None:
        return {"tone": "unknown", "text": f"тревога: {UNKNOWN_CODE_RU}"}
    tone, text = entry
    return {"tone": tone, "text": text}


_EXIT_RE = re.compile(r"^exit_nonzero[:_](\d+)$")
_LOADED_RE = re.compile(r"загружены:\s*([^;]+)")
_DOMAIN_RE = re.compile(r"([a-z0-9_]+)\s+(WARNING|CRITICAL|DEGRADED|FAIL)")


def problem_plain(agent: Any, cause_code: Any, detail: Any = None) -> dict:
    """A Problem (``agent``, ``cause_code``) in words. A Problem is never ``ok``: an unknown
    family is ``unknown`` tone, a known one ``warn`` (the store has no severity on the item here)."""
    code = str(cause_code or "")
    det = str(detail or "")
    m = _EXIT_RE.match(code)
    if m:
        return {"tone": "warn", "text": PROBLEM_FAMILY_RU["exit_nonzero"].format(agent=_agent_short(agent), n=m.group(1))}
    if code == "stale_log":
        return {"tone": "warn", "text": PROBLEM_FAMILY_RU["stale_log"].format(agent=_agent_short(agent))}
    if code == "retired_but_loaded":
        lm = _LOADED_RE.search(det)
        names = [_agent_short(x.strip()) for x in lm.group(1).split(",")] if lm else []
        return {"tone": "warn", "text": PROBLEM_FAMILY_RU["retired_but_loaded"].format(names=_join_ru(names) if names else "список в подробностях")}
    if code == "domains_degraded":
        doms = [SYSTEM_DOMAIN_RU.get(d, d) for d, _st in _DOMAIN_RE.findall(det)]
        return {"tone": "warn", "text": PROBLEM_FAMILY_RU["domains_degraded"].format(names=_join_ru(doms) if doms else "список в подробностях")}
    if code == "publication_behind":
        return {"tone": "warn", "text": PROBLEM_FAMILY_RU["publication_behind"]}
    if code in SITE_CODE_RU:
        return {"tone": "warn", "text": SITE_CODE_RU[code]}
    return {"tone": "unknown", "text": f"«{_agent_short(agent)}»: {UNKNOWN_CODE_RU}"}


def age_ru(age_min: Optional[float]) -> Optional[str]:
    """«2 ч назад» — for a raw ISO timestamp on the owner layer (the ISO stays in evidence)."""
    if not isinstance(age_min, (int, float)) or isinstance(age_min, bool):
        return None
    # A stamp a few minutes ahead of the reader's clock is a slow build (its `now` is taken at the
    # start), not a lie — the same 10-minute skew readiness_scopes.FUTURE_SKEW_MINUTES allows.
    if age_min < -10:
        return "время из будущего — этой отметке не верю"
    if age_min < 1:
        return "только что"
    if age_min < 60:
        return f"{age_min:.0f} мин назад"
    if age_min < 48 * 60:
        return f"{age_min / 60:.0f} ч назад"
    return f"{age_min / 1440:.0f} дн назад"
