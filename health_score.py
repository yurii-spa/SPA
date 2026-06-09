#!/usr/bin/env python3
"""health_score.py — расчёт per-adapter и общего health score для оркестратора (SPA-V386).

STRICTLY READ-ONLY: чистая арифметика поверх словарей результатов адаптеров.
Не делает сетевых вызовов, не трогает execution/risk/wallet/деньги.
Только stdlib.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

# Порог «подозрительно низкого» APY в процентах (apy_pct).
SUSPICIOUS_APY_PCT = 0.1
# Возраст данных, после которого результат считается устаревшим (секунды).
STALE_AFTER_SEC = 3600  # 1 час


def _parse_ts(value: Any) -> datetime | None:
    """Распарсить ISO-8601 timestamp в timezone-aware datetime, иначе None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _is_stale(adapter_result: dict, *, now: datetime | None = None) -> bool:
    """True, если last_updated старше STALE_AFTER_SEC."""
    ts = _parse_ts(adapter_result.get("last_updated"))
    if ts is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() > STALE_AFTER_SEC


def compute_health_score(adapter_result: dict, *, now: datetime | None = None) -> float:
    """Вернуть health score одного адаптера в диапазоне [0.0, 1.0].

    Шкала:
        1.0  — ok, APY > 0, без ошибки
        0.75 — ok, но APY подозрительно низкий (< 0.1 %)
        0.5  — stale (last_updated старше 1 часа)
        0.25 — partial (данные есть, но есть warning)
        0.0  — error / timeout / exception
    """
    status = str(adapter_result.get("status") or "").lower()
    error = adapter_result.get("error")

    # 0.0 — любая ошибка/таймаут/исключение имеет наивысший приоритет.
    if error or status in {"error", "timeout", "exception", "failed"}:
        return 0.0

    # 0.5 — устаревшие данные (по явному статусу или по возрасту last_updated).
    if status == "stale" or _is_stale(adapter_result, now=now):
        return 0.5

    # 0.25 — частичные данные: явный статус partial или наличие warning.
    if status == "partial" or adapter_result.get("warning"):
        return 0.25

    # ok-ветка: оцениваем по APY.
    apy = adapter_result.get("apy_pct")
    if not isinstance(apy, (int, float)):
        # ok-статус, но APY недоступен — трактуем как частичные данные.
        return 0.25
    if apy < SUSPICIOUS_APY_PCT:
        # сюда же попадает apy <= 0: «ok, но APY подозрительно низкий».
        return 0.75
    return 1.0


def grade_for_score(score: float) -> str:
    """Буквенная оценка по среднему health score."""
    if score >= 0.9:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.6:
        return "C"
    if score >= 0.4:
        return "D"
    return "F"


def compute_overall_health(
    adapter_results: Iterable[dict], *, now: datetime | None = None
) -> dict:
    """Свести per-adapter health в общий показатель.

    Возвращает словарь:
        {
          "score": float,          # средний health score
          "grade": "A".."F",
          "total": int,
          "ok_count": int,
          "partial_count": int,
          "stale_count": int,
          "error_count": int,
        }
    """
    results = list(adapter_results)
    scores: list[float] = []
    ok = partial = stale = error = 0

    for r in results:
        score = r.get("health_score")
        if not isinstance(score, (int, float)):
            score = compute_health_score(r, now=now)
        scores.append(float(score))

        status = str(r.get("status") or "").lower()
        if r.get("error") or status in {"error", "timeout", "exception", "failed"}:
            error += 1
        elif status == "stale" or _is_stale(r, now=now):
            stale += 1
        elif status == "partial" or r.get("warning"):
            partial += 1
        else:
            ok += 1

    total = len(results)
    avg = round(sum(scores) / total, 4) if total else 0.0

    return {
        "score": avg,
        "grade": grade_for_score(avg),
        "total": total,
        "ok_count": ok,
        "partial_count": partial,
        "stale_count": stale,
        "error_count": error,
    }
