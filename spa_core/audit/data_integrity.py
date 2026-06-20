#!/usr/bin/env python3
"""spa_core.audit.data_integrity — Data Integrity Sentinel (SPA-V430, OFFLINE).

Read-only кросс-проверка ВЗАИМНОЙ согласованности и свежести data/*.json
артефактов трека, которые пишут независимые модули (cycle_runner,
scoring_engine, capital_ladder MP-505, proof_of_track MP-406, tear_sheet
MP-501, capacity_analytics и т.д.). Никто до этого спринта не проверял их
согласованность единым гейтом: тихое расхождение (gap в equity-кривой,
stale risk_scores, веса позиций ≠ 1, отсутствующий merkle-якорь за день
трека) = потеря доверия к треку — главному активу проекта.

Чеки (каждый возвращает {check, status, details, notes};
status ∈ {"ok","warn","fail","skip"}; ОТСУТСТВУЮЩИЙ входной файл —
честный "skip" + note, НИКОГДА не fail):

1. ``equity_continuity``       — data/equity_curve_daily.json: даты строго
   возрастают, без дублей (нарушение → fail); gap между соседними барами:
   ровно 2 календарных дня → warn, > 2 → fail; ``is_demo: true`` в любом
   баре (или на верхнем уровне) → fail; нечисловые equity → warn.
2. ``positions_consistency``   — data/current_positions.json: сумма долей
   позиций + cash ≈ 100% капитала (допуск ≤ 0.5% → ok, ≤ 2% → warn,
   дальше fail); отрицательные позиции → fail.
3. ``allocation_policy_bounds``— data/target_allocation.json: ни один вес
   > 0.40 (T1 cap), сумма весов ≤ 1.0 + 1e-6. Тиры — из
   data/adapter_orchestrator_status.json; протокол без тира → unknown и
   считается по СТРОГОМУ T2-капу 0.20. Превышение → fail. Это
   advisory-ДУБЛЬ гейта (числовые константы, см. комментарий у T1_CAP),
   RiskPolicy НЕ импортируется и НЕ подменяется.
4. ``freshness``               — generated_at/last_cycle_ts/ts/timestamp
   ключевых файлов не старше порогов (часов): adapter_orchestrator_status
   26, risk_scores 48, paper_trading_status 26, capacity_analytics 48,
   golive_status 48. Старше порога → warn, старше 2× порога → fail.
   Сравнение в UTC; битый/отсутствующий timestamp → warn.
5. ``anchor_coverage``         — каждый день трека из equity-кривой
   (от REAL_TRACK_START=2026-06-10, исключая сегодняшний незавершённый
   UTC-день) имеет запись в data/proof_of_track_anchors.json; отсутствие
   якоря → warn (якорение могло ещё не запуститься), discrepancy-пометка
   в note любого якоря → fail (трек переписан задним числом — MP-406).
6. ``schema_sanity``           — все перечисленные data/*.json парсятся
   как JSON и имеют ожидаемый верхний тип (dict); файл есть, но битый /
   не тот тип → fail; ``*.tmp``-огрызки в data/ → fail.

Агрегат :func:`run_integrity_checks` → dict {generated_at, verdict
("ok"|"warn"|"fail" — худший из чеков; "skip" вердикт НЕ ухудшает),
checks, counts {ok,warn,fail,skip}, advisory_only: true,
execution_mode: "read_only"}. НИКОГДА не raise — внутренняя ошибка
любого чека деградирует в warn + note (паттерн capital_ladder).

Персист (:func:`write_status`): атомарная запись
``data/data_integrity_status.json`` (tmp + os.replace, паттерн
capital_ladder/proof_of_track), история прогонов внутри файла с ротацией
≤ 500. Идемпотентность по :func:`content_fingerprint` (doc без
волатильных ``generated_at``/``history``/``age_hours`` — паттерн
tear_sheet MP-501): повторный --run с теми же данными байт-в-байт не
меняет файл, history не растёт.

CLI (offline, exit 0 всегда, без трейсбеков; мусорные аргументы →
понятный ERROR в stderr)::

    python3 -m spa_core.audit.data_integrity --check    # печать JSON, дефолт
    python3 -m spa_core.audit.data_integrity --run      # + атомарная запись
    python3 -m spa_core.audit.data_integrity --run --data-dir <dir>

Scope / safety: LLM FORBIDDEN — детерминированная логика, pure stdlib
(json/os/sys/datetime/tempfile/argparse/logging/pathlib/math), без
requests/web3/LLM SDK/сети. STRICTLY READ-ONLY (SPA-BL-011): только
читает data/*.json и пишет СОБСТВЕННЫЙ статус-файл; risk/execution/
allocator/cycle_runner/audit_trail/proof_of_track не трогаются.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.audit.data_integrity")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "data_integrity"
STATUS_FILENAME = "data_integrity_status.json"
HISTORY_MAX = 500  # ротация истории прогонов (паттерн capital_ladder/MP-406)

EQUITY_FILENAME = "equity_curve_daily.json"
POSITIONS_FILENAME = "current_positions.json"
ALLOCATION_FILENAME = "target_allocation.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"
RISK_SCORES_FILENAME = "risk_scores.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
CAPACITY_FILENAME = "capacity_analytics.json"
GOLIVE_STATUS_FILENAME = "golive_status.json"
ANCHORS_FILENAME = "proof_of_track_anchors.json"

# Старт РЕАЛЬНОГО трека (KANBAN.json: real_track_start) — дни equity-кривой
# раньше этой даты не требуют merkle-якоря MP-406.
REAL_TRACK_START = "2026-06-10"

# Advisory-ДУБЛЬ числовых констант риск-политики (spa_core/risk/policy.py:
# max_concentration_t1=0.40 / t2=0.20). RiskPolicy НЕ импортируется
# (LLM_FORBIDDEN-домен читается только гейтом) — это независимая
# перекрёстная проверка, НЕ замена детерминированного гейта.
T1_CAP = 0.40
T2_CAP = 0.20           # строгий cap и для unknown/T2/T3 — консервативно
WEIGHT_SUM_MAX = 1.0
WEIGHT_TOL = 1e-6

# Допуски positions_consistency (% от капитала).
POSITIONS_OK_TOL_PCT = 0.5
POSITIONS_WARN_TOL_PCT = 2.0
_EPS = 1e-9  # страховка float-границ «ровно 0.5% / ровно 2%»

# Пороги свежести (часов): age ≤ T → ok, T < age ≤ 2T → warn, age > 2T → fail.
FRESHNESS_THRESHOLDS_HOURS: Dict[str, float] = {
    ORCH_STATUS_FILENAME: 26.0,
    RISK_SCORES_FILENAME: 48.0,
    PT_STATUS_FILENAME: 26.0,
    CAPACITY_FILENAME: 48.0,
    GOLIVE_STATUS_FILENAME: 48.0,
}
# Ключи timestamp'ов в порядке приоритета (golive пишет "timestamp",
# paper_trading — "last_cycle_ts", остальные — "generated_at").
_TS_KEYS = ("generated_at", "last_cycle_ts", "ts", "timestamp")

# schema_sanity: перечисленные артефакты и их ожидаемый верхний JSON-тип.
EXPECTED_TOP_TYPES: Dict[str, type] = {
    EQUITY_FILENAME: dict,
    POSITIONS_FILENAME: dict,
    ALLOCATION_FILENAME: dict,
    ORCH_STATUS_FILENAME: dict,
    RISK_SCORES_FILENAME: dict,
    PT_STATUS_FILENAME: dict,
    CAPACITY_FILENAME: dict,
    GOLIVE_STATUS_FILENAME: dict,
    ANCHORS_FILENAME: dict,
}

_STATUS_RANK = {"skip": 0, "ok": 0, "warn": 1, "fail": 2}
_RANK_STATUS = {0: "ok", 1: "warn", 2: "fail"}


# ─── Толерантный IO / хелперы (паттерн capital_ladder / tear_sheet) ──────────


def _read_json(path: Path) -> Any:
    """Читает JSON терпимо: нет файла / битый файл → None, никогда не raise."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _num(value: Any) -> Optional[float]:
    """Число или None (bool — не число; NaN/inf — не данные)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _parse_date(value: Any) -> Optional[datetime]:
    """YYYY-MM-DD → aware UTC datetime; мусор → None."""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    """ISO-8601 timestamp → aware UTC datetime; мусор → None.

    Понимает суффикс ``Z`` (risk_scores пишет ``...Z``); naive timestamp
    честно трактуется как UTC (конвенция cycle_runner).
    """
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _result(check: str, status: str, details: dict, notes: List[str]) -> dict:
    return {"check": check, "status": status, "details": details, "notes": notes}


def _skip(check: str, note: str) -> dict:
    return _result(check, "skip", {}, [note])


def _worst(*statuses: str) -> str:
    """Худший статус: fail > warn > ok; skip вердикт НЕ ухудшает."""
    rank = max((_STATUS_RANK.get(s, 1) for s in statuses), default=0)
    return _RANK_STATUS[rank]


# ─── Чек 1: equity_continuity ────────────────────────────────────────────────


def check_equity_continuity(equity_doc: Any) -> dict:
    """Непрерывность equity-кривой cycle_runner'а (поля в ПРОЦЕНТАХ).

    Чистая функция от содержимого equity_curve_daily.json:
    * отсутствующий/битый вход → skip + note;
    * даты строго возрастают, дублей нет (нарушение → fail);
    * gap между соседними барами: 2 календарных дня → warn, > 2 → fail;
    * ``is_demo: true`` в любом баре или на верхнем уровне → fail;
    * нечисловой equity (``close_equity``/``equity``) → warn.
    """
    name = "equity_continuity"
    if equity_doc is None:
        return _skip(name, f"{EQUITY_FILENAME}: missing/unreadable — skipped")
    if not isinstance(equity_doc, dict):
        return _skip(name, f"{EQUITY_FILENAME}: unexpected top-level type — skipped")
    daily = equity_doc.get("daily")
    if not isinstance(daily, list):
        return _skip(name, f"{EQUITY_FILENAME}: no 'daily' list — skipped")

    notes: List[str] = []
    status = "ok"
    duplicates: List[str] = []
    order_violations: List[str] = []
    gaps_warn: List[dict] = []
    gaps_fail: List[dict] = []
    demo_bars: List[str] = []
    non_numeric: List[str] = []
    invalid_dates = 0

    if equity_doc.get("is_demo") is True:
        status = "fail"
        notes.append("top-level is_demo=true — demo data on the real track")

    seen: set = set()
    prev_dt: Optional[datetime] = None
    prev_date = ""
    dates: List[str] = []
    for bar in daily:
        if not isinstance(bar, dict):
            invalid_dates += 1
            continue
        date_str = str(bar.get("date"))
        dt = _parse_date(bar.get("date"))
        if dt is None:
            invalid_dates += 1
            continue
        dates.append(date_str)
        if bar.get("is_demo") is True:
            demo_bars.append(date_str)
        eq_keys = [k for k in ("close_equity", "equity") if k in bar]
        if not eq_keys or all(_num(bar.get(k)) is None for k in eq_keys):
            non_numeric.append(date_str)
        if date_str in seen:
            duplicates.append(date_str)
        seen.add(date_str)
        if prev_dt is not None:
            gap_days = (dt - prev_dt).days
            if gap_days <= 0:
                order_violations.append(f"{prev_date} -> {date_str}")
            elif gap_days == 2:
                gaps_warn.append({"from": prev_date, "to": date_str, "days": gap_days})
            elif gap_days > 2:
                gaps_fail.append({"from": prev_date, "to": date_str, "days": gap_days})
        prev_dt, prev_date = dt, date_str

    if invalid_dates:
        status = _worst(status, "warn")
        notes.append(f"{invalid_dates} bar(s) with invalid/missing date — skipped")
    if non_numeric:
        status = _worst(status, "warn")
        notes.append(f"non-numeric equity in bar(s): {', '.join(non_numeric)}")
    if gaps_warn:
        status = _worst(status, "warn")
        notes.append(
            "2-day calendar gap(s): "
            + ", ".join(f"{g['from']}->{g['to']}" for g in gaps_warn)
        )
    if duplicates:
        status = "fail"
        notes.append(f"duplicate date(s): {', '.join(sorted(set(duplicates)))}")
    if order_violations:
        status = "fail"
        notes.append(f"dates not strictly increasing: {'; '.join(order_violations)}")
    if gaps_fail:
        status = "fail"
        notes.append(
            ">2-day gap(s) in the track: "
            + ", ".join(f"{g['from']}->{g['to']} ({g['days']}d)" for g in gaps_fail)
        )
    if demo_bars:
        status = "fail"
        notes.append(f"is_demo=true bar(s): {', '.join(demo_bars)}")
    if not dates:
        notes.append("empty equity curve — nothing to verify")

    details = {
        "bars": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "duplicates": sorted(set(duplicates)),
        "order_violations": order_violations,
        "gaps_warn": gaps_warn,
        "gaps_fail": gaps_fail,
        "demo_bars": demo_bars,
        "non_numeric_equity": non_numeric,
    }
    return _result(name, status, details, notes)


# ─── Чек 2: positions_consistency ────────────────────────────────────────────


def check_positions_consistency(positions_doc: Any) -> dict:
    """Сумма позиций + cash ≈ 100% капитала (current_positions.json).

    Допуски (% от capital_usd): ≤ 0.5 → ok, ≤ 2.0 → warn, дальше fail.
    Отрицательные позиции → fail. Отсутствующий вход → skip; нечисловые
    значения / отсутствующий capital_usd → warn (честно «не можем
    проверить», ничего не выдумываем).
    """
    name = "positions_consistency"
    if positions_doc is None:
        return _skip(name, f"{POSITIONS_FILENAME}: missing/unreadable — skipped")
    if not isinstance(positions_doc, dict):
        return _skip(name, f"{POSITIONS_FILENAME}: unexpected top-level type — skipped")

    notes: List[str] = []
    status = "ok"
    raw = positions_doc.get("positions")
    positions: Dict[str, float] = {}
    negative: List[str] = []
    non_numeric: List[str] = []
    if isinstance(raw, dict):
        for proto, usd in raw.items():
            val = _num(usd)
            if val is None:
                non_numeric.append(str(proto))
            elif val < 0:
                negative.append(str(proto))
                positions[str(proto)] = val
            else:
                positions[str(proto)] = val
    else:
        status = _worst(status, "warn")
        notes.append("'positions' is not a dict — nothing to sum")

    if non_numeric:
        status = _worst(status, "warn")
        notes.append(f"non-numeric position value(s): {', '.join(sorted(non_numeric))}")

    cash = _num(positions_doc.get("cash_usd"))
    if cash is None:
        status = _worst(status, "warn")
        notes.append("cash_usd missing/non-numeric — treated as 0 for the sum")
        cash = 0.0

    capital = _num(positions_doc.get("capital_usd"))
    deviation_pct: Optional[float] = None
    if capital is None or capital <= 0:
        status = _worst(status, "warn")
        notes.append("capital_usd missing/invalid — consistency cannot be verified")
    else:
        total = sum(positions.values()) + cash
        deviation_pct = abs(total - capital) / capital * 100.0
        if deviation_pct <= POSITIONS_OK_TOL_PCT + _EPS:
            pass  # ok
        elif deviation_pct <= POSITIONS_WARN_TOL_PCT + _EPS:
            status = _worst(status, "warn")
            notes.append(
                f"positions+cash deviate from capital by {deviation_pct:.4f}% "
                f"(> {POSITIONS_OK_TOL_PCT}%, ≤ {POSITIONS_WARN_TOL_PCT}%)"
            )
        else:
            status = "fail"
            notes.append(
                f"positions+cash deviate from capital by {deviation_pct:.4f}% "
                f"(> {POSITIONS_WARN_TOL_PCT}%)"
            )
    if negative:
        status = "fail"
        notes.append(f"negative position(s): {', '.join(sorted(negative))}")

    details = {
        "capital_usd": capital,
        "cash_usd": cash,
        "positions_sum_usd": round(sum(positions.values()), 6),
        "deviation_pct": None if deviation_pct is None else round(deviation_pct, 6),
        "ok_tolerance_pct": POSITIONS_OK_TOL_PCT,
        "warn_tolerance_pct": POSITIONS_WARN_TOL_PCT,
        "negative_positions": sorted(negative),
        "num_positions": len(positions),
    }
    return _result(name, status, details, notes)


# ─── Чек 3: allocation_policy_bounds ─────────────────────────────────────────


def _tier_map(orch_doc: Any) -> Dict[str, str]:
    """protocol → tier из adapter_orchestrator_status.json (как tear_sheet)."""
    tiers: Dict[str, str] = {}
    if isinstance(orch_doc, dict) and isinstance(orch_doc.get("adapters"), list):
        for ad in orch_doc["adapters"]:
            if isinstance(ad, dict) and ad.get("protocol"):
                tiers[str(ad["protocol"])] = str(ad.get("tier") or "unknown")
    return tiers


def check_allocation_policy_bounds(allocation_doc: Any, orch_doc: Any) -> dict:
    """Advisory-дубль гейта концентрации: веса target_allocation в границах.

    Правила: вес > cap тира (+1e-6) → fail; cap: T1 → 0.40, иначе
    (T2/T3/unknown) → строгий 0.20; отрицательный вес → fail; сумма весов
    > 1.0 + 1e-6 → fail; нечисловой вес → warn. Тиры — из оркестратора;
    отсутствующий оркестратор → все unknown + note. Отсутствующий
    target_allocation → skip.
    """
    name = "allocation_policy_bounds"
    if allocation_doc is None:
        return _skip(name, f"{ALLOCATION_FILENAME}: missing/unreadable — skipped")
    if not isinstance(allocation_doc, dict):
        return _skip(name, f"{ALLOCATION_FILENAME}: unexpected top-level type — skipped")
    weights_raw = allocation_doc.get("target_weights")
    if not isinstance(weights_raw, dict):
        return _skip(name, f"{ALLOCATION_FILENAME}: no 'target_weights' dict — skipped")

    notes: List[str] = []
    status = "ok"
    tiers = _tier_map(orch_doc)
    if not tiers:
        notes.append(
            f"{ORCH_STATUS_FILENAME}: missing/unreadable — all tiers treated "
            f"as unknown (strict T2 cap {T2_CAP})"
        )

    violations: List[dict] = []
    per_protocol: Dict[str, dict] = {}
    non_numeric: List[str] = []
    weight_sum = 0.0
    for proto in sorted(weights_raw):
        w = _num(weights_raw[proto])
        if w is None:
            non_numeric.append(str(proto))
            continue
        tier = tiers.get(str(proto), "unknown")
        cap = T1_CAP if tier == "T1" else T2_CAP
        weight_sum += w
        entry = {"weight": round(w, 6), "tier": tier, "cap": cap}
        per_protocol[str(proto)] = entry
        if w < 0:
            status = "fail"
            violations.append({"protocol": str(proto), "weight": w, "cap": cap,
                               "kind": "negative_weight"})
        elif w > cap + WEIGHT_TOL:
            status = "fail"
            violations.append({"protocol": str(proto), "weight": w, "cap": cap,
                               "kind": "cap_exceeded"})

    if non_numeric:
        status = _worst(status, "warn")
        notes.append(f"non-numeric weight(s): {', '.join(sorted(non_numeric))}")
    if weight_sum > WEIGHT_SUM_MAX + WEIGHT_TOL:
        status = "fail"
        notes.append(
            f"sum of weights {weight_sum:.6f} > {WEIGHT_SUM_MAX} (+{WEIGHT_TOL})"
        )
    for v in violations:
        notes.append(
            f"{v['protocol']}: weight {v['weight']} violates "
            f"{'cap ' + str(v['cap']) if v['kind'] == 'cap_exceeded' else 'non-negativity'}"
        )

    details = {
        "weights": per_protocol,
        "weight_sum": round(weight_sum, 6),
        "t1_cap": T1_CAP,
        "t2_cap": T2_CAP,
        "violations": violations,
        "policy_note": (
            "advisory duplicate of the deterministic risk gate "
            "(spa_core/risk/policy.py); RiskPolicy is NOT imported"
        ),
    }
    return _result(name, status, details, notes)


# ─── Чек 4: freshness ────────────────────────────────────────────────────────


def _extract_ts(doc: Any) -> Optional[str]:
    """Первый из ключей generated_at/last_cycle_ts/ts/timestamp в doc."""
    if not isinstance(doc, dict):
        return None
    for key in _TS_KEYS:
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def check_freshness(data_dir: Path, now: datetime) -> dict:
    """Свежесть ключевых артефактов (UTC): ok ≤ T < warn ≤ 2T < fail.

    Отсутствующий/нечитаемый файл — per-file skip + note (НЕ ухудшает);
    битый/отсутствующий timestamp в живом файле → warn. Все файлы
    отсутствуют → общий skip.
    """
    name = "freshness"
    files: List[dict] = []
    notes: List[str] = []
    status_rank = 0
    any_present = False
    for fname, threshold in FRESHNESS_THRESHOLDS_HOURS.items():
        doc = _read_json(data_dir / fname)
        entry: Dict[str, Any] = {
            "file": fname,
            "threshold_hours": threshold,
            "ts": None,
            "age_hours": None,
            "status": "skip",
        }
        if doc is None:
            notes.append(f"{fname}: missing/unreadable — skipped")
            files.append(entry)
            continue
        any_present = True
        raw_ts = _extract_ts(doc)
        ts = _parse_ts(raw_ts)
        if ts is None:
            entry["status"] = "warn"
            entry["ts"] = raw_ts
            notes.append(f"{fname}: missing/invalid timestamp — warn")
        else:
            age_hours = (now - ts).total_seconds() / 3600.0
            entry["ts"] = ts.isoformat()
            entry["age_hours"] = round(age_hours, 2)
            if age_hours <= threshold:
                entry["status"] = "ok"
            elif age_hours <= 2.0 * threshold:
                entry["status"] = "warn"
                notes.append(
                    f"{fname}: stale {age_hours:.1f}h > {threshold:.0f}h threshold"
                )
            else:
                entry["status"] = "fail"
                notes.append(
                    f"{fname}: stale {age_hours:.1f}h > 2x threshold "
                    f"({2 * threshold:.0f}h)"
                )
        status_rank = max(status_rank, _STATUS_RANK[entry["status"]])
        files.append(entry)

    if not any_present:
        return _result(name, "skip", {"files": files},
                       notes + ["no freshness-tracked files present — skipped"])
    return _result(name, _RANK_STATUS[status_rank], {"files": files}, notes)


# ─── Чек 5: anchor_coverage ──────────────────────────────────────────────────


def check_anchor_coverage(
    equity_doc: Any, anchors_doc: Any, now: datetime
) -> dict:
    """Покрытие дней реального трека merkle-якорями MP-406.

    Требуемые дни: даты баров equity-кривой ≥ REAL_TRACK_START и СТРОГО
    раньше сегодняшнего (незавершённого) UTC-дня. Отсутствие якоря за
    день → warn (якорение могло ещё не запуститься); discrepancy-пометка
    в note ЛЮБОГО якоря → fail (root дня не сходится с заякоренным —
    переписанный трек). Отсутствующие входы → skip.
    """
    name = "anchor_coverage"
    if anchors_doc is None:
        return _skip(name, f"{ANCHORS_FILENAME}: missing/unreadable — skipped")
    if equity_doc is None or not isinstance(equity_doc, dict) \
            or not isinstance(equity_doc.get("daily"), list):
        return _skip(name, f"{EQUITY_FILENAME}: missing/unreadable — "
                           "no track days to verify, skipped")

    notes: List[str] = []
    status = "ok"
    track_start = _parse_date(REAL_TRACK_START)
    today = now.astimezone(timezone.utc).strftime("%Y-%m-%d")

    anchored_dates: set = set()
    discrepancies: List[str] = []
    anchors = anchors_doc.get("anchors") if isinstance(anchors_doc, dict) else None
    if not isinstance(anchors, list):
        return _skip(name, f"{ANCHORS_FILENAME}: no 'anchors' list — skipped")
    for a in anchors:
        if not isinstance(a, dict):
            continue
        date = a.get("date")
        if _parse_date(date) is not None:
            anchored_dates.add(str(date))
        note = a.get("note")
        if isinstance(note, str) and "discrepancy" in note.lower():
            discrepancies.append(str(date))

    required: List[str] = []
    for bar in equity_doc["daily"]:
        if not isinstance(bar, dict):
            continue
        dt = _parse_date(bar.get("date"))
        if dt is None or (track_start is not None and dt < track_start):
            continue
        date_str = str(bar.get("date"))
        if date_str >= today:  # сегодняшний незавершённый UTC-день исключается
            continue
        required.append(date_str)
    required = sorted(set(required))
    missing = [d for d in required if d not in anchored_dates]

    if missing:
        status = _worst(status, "warn")
        notes.append(
            "track day(s) without merkle anchor (anchoring may not have run "
            "yet): " + ", ".join(missing)
        )
    if discrepancies:
        status = "fail"
        notes.append(
            "discrepancy note in anchor(s) — track rewritten after anchoring: "
            + ", ".join(sorted(set(discrepancies)))
        )
    if not required:
        notes.append("no completed track days to verify yet")

    details = {
        "real_track_start": REAL_TRACK_START,
        "required_days": required,
        "anchored_days": sorted(d for d in anchored_dates if d in set(required)),
        "missing_days": missing,
        "discrepancy_days": sorted(set(discrepancies)),
    }
    return _result(name, status, details, notes)


# ─── Чек 6: schema_sanity ────────────────────────────────────────────────────


def check_schema_sanity(data_dir: Path) -> dict:
    """Все перечисленные data/*.json парсятся и имеют ожидаемый верхний тип.

    Файл отсутствует → note (не ухудшает); файл есть, но не парсится или
    верхний тип не тот → fail; ``*.tmp``-огрызки в data/ (недоигранные
    атомарные записи) → fail. Вообще ничего нет → skip.
    """
    name = "schema_sanity"
    notes: List[str] = []
    status = "ok"
    files: List[dict] = []
    any_present = False
    for fname, expected in EXPECTED_TOP_TYPES.items():
        path = data_dir / fname
        entry: Dict[str, Any] = {
            "file": fname,
            "expected_type": expected.__name__,
            "status": "skip",
        }
        if not path.exists():
            notes.append(f"{fname}: missing — skipped")
            files.append(entry)
            continue
        any_present = True
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            entry["status"] = "fail"
            status = "fail"
            notes.append(f"{fname}: unparseable JSON ({type(exc).__name__})")
            files.append(entry)
            continue
        if not isinstance(doc, expected):
            entry["status"] = "fail"
            status = "fail"
            notes.append(
                f"{fname}: top-level type {type(doc).__name__}, "
                f"expected {expected.__name__}"
            )
        else:
            entry["status"] = "ok"
        files.append(entry)

    tmp_files: List[str] = []
    try:
        tmp_files = sorted(
            p.name for p in Path(data_dir).glob("*.tmp") if p.is_file()
        )
    except OSError:
        notes.append("data dir unreadable — tmp scan skipped")
    if tmp_files:
        status = "fail"
        notes.append(
            "stray *.tmp leftover(s) of interrupted atomic writes: "
            + ", ".join(tmp_files)
        )

    if not any_present and not tmp_files:
        return _result(name, "skip", {"files": files, "tmp_files": []},
                       notes + ["no listed artifacts present — skipped"])
    return _result(name, status, {"files": files, "tmp_files": tmp_files}, notes)


# ─── Агрегат ─────────────────────────────────────────────────────────────────


def _safe_check(fn, name: str, *args) -> dict:
    """Запускает чек fail-safe: внутренняя ошибка → warn + note, не raise."""
    try:
        return fn(*args)
    except Exception as exc:  # никогда не raise из run_integrity_checks
        log.warning("check %s crashed: %s", name, exc)
        return _result(
            name, "warn", {},
            [f"internal error in {name}: {type(exc).__name__}: {exc} — "
             "degraded to warn (advisory, never raises)"],
        )


def run_integrity_checks(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Полный read-only прогон всех 6 чеков согласованности артефактов.

    Возвращает dict: {schema_version, source, generated_at, verdict,
    counts {ok,warn,fail,skip}, checks: [...], advisory_only: true,
    execution_mode: "read_only"}. Вердикт — худший из чеков
    (fail > warn > ok); "skip" вердикт НЕ ухудшает. НИКОГДА не raise:
    битые/отсутствующие входы — это статусы и notes, внутренняя ошибка
    чека деградирует в warn.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        equity_doc = _read_json(ddir / EQUITY_FILENAME)
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        allocation_doc = _read_json(ddir / ALLOCATION_FILENAME)
        orch_doc = _read_json(ddir / ORCH_STATUS_FILENAME)
        anchors_doc = _read_json(ddir / ANCHORS_FILENAME)

        checks = [
            _safe_check(check_equity_continuity, "equity_continuity", equity_doc),
            _safe_check(check_positions_consistency, "positions_consistency",
                        positions_doc),
            _safe_check(check_allocation_policy_bounds, "allocation_policy_bounds",
                        allocation_doc, orch_doc),
            _safe_check(check_freshness, "freshness", ddir, now),
            _safe_check(check_anchor_coverage, "anchor_coverage",
                        equity_doc, anchors_doc, now),
            _safe_check(check_schema_sanity, "schema_sanity", ddir),
        ]
        counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
        for c in checks:
            counts[c.get("status", "warn")] = counts.get(
                c.get("status", "warn"), 0) + 1
        verdict = _worst(*(c.get("status", "warn") for c in checks))
        return {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "generated_at": now.isoformat(),
            "advisory_only": True,
            "execution_mode": "read_only",
            "verdict": verdict,
            "counts": counts,
            "checks": checks,
        }
    except Exception as exc:  # последний рубеж: даже мусорный data_dir не валит
        log.warning("run_integrity_checks degraded: %s", exc)
        return {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "advisory_only": True,
            "execution_mode": "read_only",
            "verdict": "warn",
            "counts": {"ok": 0, "warn": 1, "fail": 0, "skip": 0},
            "checks": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


# ─── Персист (идемпотентно, паттерн tear_sheet MP-501) ───────────────────────


def _scrub_volatile(obj: Any) -> Any:
    """Рекурсивно убирает волатильные ключи (age_hours) для отпечатка."""
    if isinstance(obj, dict):
        return {k: _scrub_volatile(v) for k, v in obj.items() if k != "age_hours"}
    if isinstance(obj, list):
        return [_scrub_volatile(v) for v in obj]
    return obj


def content_fingerprint(doc: Any) -> str:
    """Канонический отпечаток КОНТЕНТА статуса. Чистая функция.

    Волатильные поля исключаются: top-level ``generated_at`` и ``history``
    (паттерн tear_sheet) + per-file ``age_hours`` чека freshness (растёт
    с каждой секундой и не меняет сути вердикта — статусы файлов входят
    в отпечаток). Не-dict вход → отпечаток, который никогда не совпадёт
    с валидным doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k not in ("generated_at", "history")}
    return json.dumps(_scrub_volatile(core), sort_keys=True, ensure_ascii=False)


def write_status(
    doc: dict, data_dir: Optional[str | os.PathLike] = None
) -> dict:
    """Атомарно пишет data/data_integrity_status.json (tmp + os.replace).

    Идемпотентность: если :func:`content_fingerprint` не изменился
    относительно сохранённого статуса — файл НЕ перезаписывается
    (повторный --run байт-в-байт ничего не меняет, history не растёт).
    При изменении контента в ``history`` добавляется краткая запись
    {generated_at, verdict, counts} с ротацией ≤ HISTORY_MAX; битый
    существующий статус толерантно трактуется как отсутствующий.
    Возвращает {"path", "changed"}.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if content_fingerprint(prev) == content_fingerprint(doc) \
            and isinstance(prev, dict):
        log.info("data integrity status unchanged: %s", path)
        return {"path": str(path), "changed": False}
    history: List[dict] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append({
        "generated_at": doc.get("generated_at"),
        "verdict": doc.get("verdict"),
        "counts": doc.get("counts"),
    })
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("data integrity status written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, без трейсбеков) ─────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.audit.data_integrity",
        description=(
            "Data Integrity Sentinel (SPA-V430): read-only кросс-проверка "
            "согласованности и свежести data/*.json артефактов трека. "
            "Advisory only, offline."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="вычислить и напечатать JSON-вердикт БЕЗ записи (по умолчанию)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="вычислить и атомарно записать data/data_integrity_status.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse печатает свою ошибку в stderr и зовёт sys.exit(2);
        # advisory-CLI всегда exit 0 и без трейсбеков.
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0
    try:
        doc = run_integrity_checks(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            counts = doc["counts"]
            print(
                f"data_integrity: verdict={doc['verdict']} "
                f"ok={counts['ok']} warn={counts['warn']} "
                f"fail={counts['fail']} skip={counts['skip']} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
            for c in doc["checks"]:
                if c.get("status") in ("warn", "fail"):
                    print(f"  [{c['status'].upper()}] {c['check']}: "
                          f"{'; '.join(c.get('notes') or [])}")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: никаких трейсбеков, exit 0
        print(f"data_integrity: ERROR — {type(exc).__name__}: {exc}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
