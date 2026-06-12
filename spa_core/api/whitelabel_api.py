#!/usr/bin/env python3
"""SPA White-label API v1 (MP-407, SPA-V428) — OFFLINE core.

B2B advisory API «второй revenue stream без кастоди»: чистые handler-функции
поверх СУЩЕСТВУЮЩИХ данных репо (data/*.json), не привязанные к транспорту.
ВАЖНО — границы спринта: песочница без egress → внешняя публикация/деплой
НЕВОЗМОЖНЫ и НЕ выполняются. Реализовано offline-ядро: handlers + dispatch
+ опциональный локальный stdlib ``http.server`` (НЕ дефолтный режим,
localhost only). Публикация наружу — отдельным спринтом.

Эндпоинты (все advisory / read-only, деньги не двигаются):

* ``POST /v1/portfolio/analyze`` — :func:`analyze_portfolio`: риск-скоринг
  ЧУЖИХ позиций клиента. Вход ``{"positions": [{"protocol", "amount_usd",
  "chain"?}, ...]}``; мусор → честная 400-shape ``{"error", "code"}``.
  Скоринг — по реальному ``data/risk_scores.json`` (grade/score_numeric
  движка MP-104; сам движок требует метаданные протоколов и сеть, поэтому
  здесь переиспользуется его ОПУБЛИКОВАННЫЙ снапшот + чистая
  ``grade_for_score`` ИМПОРТОМ из ``spa_core.risk.scoring_engine`` — без
  дублирования порогов грейдов). Протокол не найден → честный
  ``known:false`` / grade null + note, ничего не выдумывается. Портфельные
  агрегаты: взвешенный score (только по известным), доля unknown,
  концентрация top-1, T1/T2 split по ``adapter_orchestrator_status.json``.
* ``GET /v1/allocations/recommended`` — :func:`recommended_allocations`:
  текущее рекомендованное распределение из ``data/target_allocation.json``
  (+ тиры/execution_mode из adapter_orchestrator_status). Advisory,
  disclaimer «NOT investment advice», is_demo честно из файлов (нет поля →
  null + note). Файла нет/битый → честный ``{"available": false, "note"}``.
* ``GET /v1/signals`` — :func:`webhook_signals`: ЗАГОТОВКА webhook-сигналов,
  pull-based: события из существующих data-файлов
  (``risk_policy_blocks.json`` — если появится, ``risk_alerts.json``,
  ``capital_ladder_status.json``, ``proof_of_track_anchors.json`` MP-406)
  с типами и ts; фильтр ``?since=<ISO>``. НИКАКОЙ реальной отправки
  webhook'ов (нет egress) — delivery.mode="pull", push — после деплоя.

Auth: API-ключи в ``data/api_keys.json`` —
``{"keys": [{"key_id", "key_hash" (sha256 hex), "plan", "active"}]}``.
В файле ТОЛЬКО sha256-хэш, plaintext-ключ печатается один раз при
``--gen-key`` и нигде не сохраняется. Файла нет / ключ не найден / неактивен
→ честная 401-shape (API закрыт по умолчанию). Сравнение хэшей —
``hmac.compare_digest``.

Rate limit: чистый in-memory fixed-window per key_id
(:class:`RateLimiter`, :data:`RATE_LIMIT_PER_MIN` = 60 req/min), clock
инжектируется для тестов; превышение → 429-shape.

Billing-заготовка (ТОЛЬКО учёт, никакого биллинга): счётчики usage per
key_id в ``data/api_usage.json`` — схема
``{<key_id>: {"requests_total", "by_endpoint", "last_request_at"}}``,
атомарная запись (tmp + os.replace), битый файл толерантно = пустой,
ротация ≤ :data:`USAGE_MAX_KEYS` ключей (вытесняются самые давние).

:func:`dispatch(method, path, headers, body)` → ``(status_code, dict)``:
маршрутизация трёх эндпоинтов с auth (401) → rate limit (429) → body parse
(400) → handler; неизвестный путь → 404-shape, чужой метод → 405-shape.
Usage учитывается после прохождения auth+rate-limit (независимо от исхода
handler'а — заготовка тарификации по запросам).

CLI (offline, exit 0, без трейсбеков; мусорные аргументы → ERROR в stderr,
exit 0)::

    python3 -m spa_core.api.whitelabel_api --check     # по умолчанию:
        # smoke self-test dispatch на синтетическом ключе во ВРЕМЕННОЙ среде
        # (tempdir; реальные data-файлы только ЧИТАЮТСЯ как копии),
        # печать JSON-сводки, в data/ НИЧЕГО не пишется
    python3 -m spa_core.api.whitelabel_api --gen-key --plan basic
        # сгенерировать ключ: plaintext печатается ОДИН раз,
        # в data/api_keys.json атомарно пишется только sha256
    python3 -m spa_core.api.whitelabel_api --run
        # smoke + атомарная запись usage-снапшота (_selftest) в data/
    python3 -m spa_core.api.whitelabel_api --serve --port 8788
        # ОПЦИОНАЛЬНЫЙ локальный сервер (localhost) — НЕ дефолт

Scope / safety: pure stdlib (json/os/hashlib/hmac/secrets/time/datetime/
argparse/tempfile/re/logging + http.server только в --serve), БЕЗ
requests/web3/LLM SDK. STRICTLY READ-ONLY к чужим данным: risk/execution/
allocator/policy НЕ трогаются, деньги/сделки НЕ затрагиваются — модуль
advisory; пишет только собственные data/api_keys.json и data/api_usage.json.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from spa_core.risk.scoring_engine import grade_for_score
except ModuleNotFoundError:
    # Запуск файла как скрипта (python3 spa_core/api/whitelabel_api.py):
    # sys.path[0] = spa_core/api → добавляем корень репо. Сам модуль также
    # работает через python3 -m spa_core.api.whitelabel_api (требует
    # импортируемости существующего spa_core/api/__init__.py → fastapi).
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from spa_core.risk.scoring_engine import grade_for_score

log = logging.getLogger("spa.api.whitelabel")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "whitelabel_api"
API_VERSION = "v1"

# ─── Файлы (собственные — только эти два модуль ПИШЕТ) ──────────────────────
API_KEYS_FILENAME = "api_keys.json"
USAGE_FILENAME = "api_usage.json"

# ─── Файлы-источники (READ-ONLY, все опциональны) ───────────────────────────
RISK_SCORES_FILENAME = "risk_scores.json"
TARGET_ALLOC_FILENAME = "target_allocation.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"
RISK_BLOCKS_FILENAME = "risk_policy_blocks.json"   # появится с risk policy
RISK_ALERTS_FILENAME = "risk_alerts.json"
LADDER_STATUS_FILENAME = "capital_ladder_status.json"
ANCHORS_FILENAME = "proof_of_track_anchors.json"

SIGNAL_SOURCE_FILES = (
    RISK_BLOCKS_FILENAME,
    RISK_ALERTS_FILENAME,
    LADDER_STATUS_FILENAME,
    ANCHORS_FILENAME,
)

RATE_LIMIT_PER_MIN = 60        # fixed window per key_id
RATE_WINDOW_SEC = 60.0
USAGE_MAX_KEYS = 500           # ротация usage-файла (паттерн HISTORY_MAX)

DISCLAIMER = (
    "Advisory only, NOT investment advice. SPA white-label API возвращает "
    "информационный риск-скоринг и advisory-распределения поверх paper-трека "
    "(read-only simulation); никаких сделок/кастоди не выполняется."
)

WEBHOOK_DELIVERY_NOTE = (
    "webhook delivery not implemented in this sprint (no egress in sandbox) "
    "— pull-based stub; real push delivery deferred to deployment sprint"
)

_PROTO_NORM_RE = re.compile(r"[^a-z0-9]+")


# ─── Толерантный IO (паттерн capital_ladder / proof_of_track / tear_sheet) ───


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
    """Атомарная запись JSON: tmp в той же папке + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


def _data_dir(data_dir: Optional[str | os.PathLike]) -> Path:
    return Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR


def _now_iso(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.isoformat()


def _num(value: Any) -> Optional[float]:
    """Число или None (bool — не число); NaN/inf — не данные."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _err(code: int, message: str) -> dict:
    """Честная error-shape: {"error", "code"} (code = HTTP-статус)."""
    return {"error": str(message), "code": int(code)}


def is_error(doc: Any) -> bool:
    """True для error-shape, выданной :func:`_err`."""
    return (
        isinstance(doc, dict)
        and "error" in doc
        and isinstance(doc.get("code"), int)
    )


# ─── Нормализация протоколов / риск-индекс (чистые) ──────────────────────────


def normalize_protocol(name: Any) -> str:
    """Канонизация имени протокола: "Aave V3"/"aave-v3" → "aave_v3"."""
    return _PROTO_NORM_RE.sub("_", str(name).strip().lower()).strip("_")


def build_risk_index(scores_doc: Any) -> Dict[str, dict]:
    """Индекс normalized-имя → {protocol, grade, score_numeric} из
    risk_scores.json (снапшот движка MP-104). Чистая функция; индексируются
    и ``protocol``, и ``slug``; мусорные записи молча пропускаются."""
    index: Dict[str, dict] = {}
    if not isinstance(scores_doc, dict):
        return index
    scores = scores_doc.get("scores")
    if not isinstance(scores, list):
        return index
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        proto = entry.get("protocol")
        if not isinstance(proto, str) or not proto.strip():
            continue
        record = {
            "protocol": proto,
            "grade": entry.get("grade"),
            "score_numeric": _num(entry.get("score_numeric")),
        }
        for alias in (proto, entry.get("slug")):
            if isinstance(alias, str) and alias.strip():
                index.setdefault(normalize_protocol(alias), record)
    return index


def build_tier_map(orch_doc: Any) -> Dict[str, str]:
    """normalized-протокол → tier из adapter_orchestrator_status.json."""
    tiers: Dict[str, str] = {}
    if not isinstance(orch_doc, dict) or not isinstance(orch_doc.get("adapters"), list):
        return tiers
    for ad in orch_doc["adapters"]:
        if isinstance(ad, dict) and ad.get("protocol"):
            tiers[normalize_protocol(ad["protocol"])] = str(ad.get("tier") or "unknown")
    return tiers


# ─── POST /v1/portfolio/analyze ──────────────────────────────────────────────


def validate_analyze_payload(payload: Any) -> Tuple[Optional[List[dict]], Optional[dict]]:
    """Строгая валидация входа analyze: (positions, None) | (None, 400-shape).

    Мусор НЕ пропускается молча (это вход клиента, а не свой data-файл):
    любая невалидная позиция → честная ошибка с индексом."""
    if not isinstance(payload, dict):
        return None, _err(400, "payload must be a JSON object")
    raw = payload.get("positions")
    if not isinstance(raw, list) or not raw:
        return None, _err(400, "payload.positions must be a non-empty list")
    positions: List[dict] = []
    total = 0.0
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, _err(400, f"positions[{i}] must be an object")
        proto = item.get("protocol")
        if not isinstance(proto, str) or not proto.strip():
            return None, _err(
                400, f"positions[{i}].protocol must be a non-empty string")
        amount = _num(item.get("amount_usd"))
        if amount is None:
            return None, _err(
                400, f"positions[{i}].amount_usd must be a finite number")
        if amount < 0:
            return None, _err(
                400, f"positions[{i}].amount_usd must be >= 0")
        chain = item.get("chain")
        if chain is not None and not isinstance(chain, str):
            return None, _err(
                400, f"positions[{i}].chain must be a string if present")
        positions.append(
            {"protocol": proto.strip(), "amount_usd": amount, "chain": chain})
        total += amount
    if total <= 0:
        return None, _err(400, "total amount_usd must be > 0")
    return positions, None


def analyze_portfolio(
    payload: dict,
    *,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Риск-скоринг чужого портфеля. Чистый handler (транспорт не нужен).

    Скоринг по реальному data/risk_scores.json; грейд взвешенного score —
    переиспользованием ``grade_for_score`` ИМПОРТОМ (пороги A/B/C/D движка
    MP-104 не дублируются). Неизвестный протокол → known:false + note.
    Мусорный вход → 400-shape ``{"error", "code"}``."""
    positions, error = validate_analyze_payload(payload)
    if error is not None:
        return error
    ddir = _data_dir(data_dir)
    notes: List[str] = []

    risk_index = build_risk_index(_read_json(ddir / RISK_SCORES_FILENAME))
    if not risk_index:
        notes.append(
            f"{RISK_SCORES_FILENAME}: missing/unreadable — all protocols "
            "scored as unknown")
    tier_map = build_tier_map(_read_json(ddir / ORCH_STATUS_FILENAME))
    if not tier_map:
        notes.append(
            f"{ORCH_STATUS_FILENAME}: missing/unreadable — tiers unknown")

    total = sum(p["amount_usd"] for p in positions)
    out_positions: List[dict] = []
    known_weighted = 0.0
    known_total = 0.0
    unknown_total = 0.0
    tier_split: Dict[str, float] = {}
    top1_proto: Optional[str] = None
    top1_amount = -1.0

    for pos in positions:
        norm = normalize_protocol(pos["protocol"])
        share = pos["amount_usd"] / total * 100.0
        entry = risk_index.get(norm)
        known = entry is not None and entry.get("score_numeric") is not None
        if known:
            score = entry["score_numeric"]
            grade = entry.get("grade")
            known_weighted += score * pos["amount_usd"]
            known_total += pos["amount_usd"]
            risk = {"known": True, "grade": grade,
                    "score_numeric": score, "note": None}
        else:
            unknown_total += pos["amount_usd"]
            risk = {"known": False, "grade": None, "score_numeric": None,
                    "note": "protocol unknown to SPA risk engine snapshot — "
                            "no score invented"}
        tier = tier_map.get(norm, "unknown")
        tier_split[tier] = tier_split.get(tier, 0.0) + share
        if pos["amount_usd"] > top1_amount:
            top1_amount = pos["amount_usd"]
            top1_proto = pos["protocol"]
        out_positions.append({
            "protocol": pos["protocol"],
            "protocol_normalized": norm,
            "amount_usd": round(pos["amount_usd"], 2),
            "share_pct": round(share, 4),
            "chain": pos["chain"],
            "tier": tier,
            "risk": risk,
        })

    weighted_score = (
        round(known_weighted / known_total, 6) if known_total > 0 else None)
    weighted_grade = (
        grade_for_score(weighted_score) if weighted_score is not None else None)
    if weighted_score is None:
        notes.append("no known protocols — portfolio score honest null")
    unknown_share = round(unknown_total / total * 100.0, 4)
    if unknown_share > 0:
        notes.append(
            f"weighted score covers known protocols only "
            f"({round(100.0 - unknown_share, 4)}% of portfolio)")

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "endpoint": "/v1/portfolio/analyze",
        "generated_at": _now_iso(now),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "portfolio": {
            "total_usd": round(total, 2),
            "num_positions": len(out_positions),
            "weighted_risk_score": weighted_score,
            "weighted_risk_grade": weighted_grade,
            "unknown_share_pct": unknown_share,
            "top1_protocol": top1_proto,
            "top1_concentration_pct": round(top1_amount / total * 100.0, 4),
            "tier_split_pct": {
                t: round(v, 4) for t, v in sorted(tier_split.items())},
        },
        "positions": out_positions,
        "notes": notes,
    }


# ─── GET /v1/allocations/recommended ─────────────────────────────────────────


def recommended_allocations(
    *,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Текущее рекомендованное распределение (advisory). Чистый handler.

    Источники: data/target_allocation.json (веса-доли) +
    adapter_orchestrator_status.json (тиры, execution_mode). Файлов нет /
    битые → честный ``{"available": false, "note"}``. is_demo честно из
    файлов; поля нет ни в одном → null + note."""
    ddir = _data_dir(data_dir)
    notes: List[str] = []
    target = _read_json(ddir / TARGET_ALLOC_FILENAME)
    base = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "endpoint": "/v1/allocations/recommended",
        "generated_at": _now_iso(now),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
    }
    weights = target.get("target_weights") if isinstance(target, dict) else None
    if not isinstance(weights, dict) or not weights:
        base.update(
            available=False,
            note=f"{TARGET_ALLOC_FILENAME}: missing/unreadable — "
                 "no recommendation available (nothing invented)",
        )
        return base

    orch = _read_json(ddir / ORCH_STATUS_FILENAME)
    tier_map = build_tier_map(orch)
    if not tier_map:
        notes.append(f"{ORCH_STATUS_FILENAME}: missing/unreadable — tiers unknown")
    risk_breakdown = target.get("risk_breakdown")
    risk_breakdown = risk_breakdown if isinstance(risk_breakdown, dict) else {}

    allocations: List[dict] = []
    for proto in sorted(weights):
        weight = _num(weights[proto])
        if weight is None:
            continue
        norm = normalize_protocol(proto)
        rb = risk_breakdown.get(proto)
        grade = rb.get("risk_grade") if isinstance(rb, dict) else None
        allocations.append({
            "protocol": str(proto),
            "weight_pct": round(weight * 100.0, 4),
            "tier": tier_map.get(norm, "unknown"),
            "risk_grade": grade,
        })

    is_demo = None
    for doc in (target, orch):
        if isinstance(doc, dict) and isinstance(doc.get("is_demo"), bool):
            is_demo = doc["is_demo"]
            break
    if is_demo is None:
        notes.append("is_demo not present in source files — honest null")

    cash = _num(target.get("cash_pct"))
    base.update(
        available=True,
        as_of=target.get("timestamp"),
        model_used=target.get("model_used"),
        expected_apy_pct=_num(target.get("expected_apy_pct")),
        is_demo=is_demo,
        execution_mode=orch.get("execution_mode") if isinstance(orch, dict) else None,
        allocations=allocations,
        cash_pct=None if cash is None else round(cash * 100.0, 4),
        notes=notes,
    )
    return base


# ─── GET /v1/signals (webhook-заготовка, pull-based) ─────────────────────────


def _parse_ts(value: Any) -> Optional[datetime]:
    """ISO-строка → aware datetime (UTC при отсутствии tz); мусор → None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def webhook_signals(
    since: Optional[str] = None,
    *,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Сигналы для webhook-подписчиков (ЗАГОТОВКА, pull-based). Чистый handler.

    Источники (все опциональны, битые толерантно пропускаются с note):
    risk_policy_blocks.json (type=risk_policy_block), risk_alerts.json
    (type=risk_alert), capital_ladder_status.json (type=capital_ladder_level
    + type=incident при last_incident), proof_of_track_anchors.json
    (type=proof_of_track_anchor). ``since`` (ISO-8601) фильтрует по ts;
    мусорный since → 400-shape. НИКАКОЙ реальной отправки — нет egress."""
    since_dt: Optional[datetime] = None
    if since is not None:
        since_dt = _parse_ts(since)
        if since_dt is None:
            return _err(400, f"invalid since {since!r}: expected ISO-8601 timestamp")

    ddir = _data_dir(data_dir)
    notes: List[str] = []
    signals: List[dict] = []
    sources: Dict[str, bool] = {}

    blocks_doc = _read_json(ddir / RISK_BLOCKS_FILENAME)
    sources[RISK_BLOCKS_FILENAME] = blocks_doc is not None
    items = blocks_doc if isinstance(blocks_doc, list) else (
        blocks_doc.get("blocks") if isinstance(blocks_doc, dict) else None)
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            signals.append({
                "type": "risk_policy_block",
                "ts": item.get("timestamp") or item.get("ts"),
                "data": item,
            })
    else:
        notes.append(f"{RISK_BLOCKS_FILENAME}: missing/unreadable — skipped")

    alerts_doc = _read_json(ddir / RISK_ALERTS_FILENAME)
    sources[RISK_ALERTS_FILENAME] = alerts_doc is not None
    alerts = alerts_doc.get("alerts") if isinstance(alerts_doc, dict) else None
    if isinstance(alerts, list):
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            signals.append({
                "type": "risk_alert",
                "ts": alert.get("timestamp") or alert.get("ts")
                or (alerts_doc.get("generated_at")
                    if isinstance(alerts_doc, dict) else None),
                "data": alert,
            })
    else:
        notes.append(f"{RISK_ALERTS_FILENAME}: missing/unreadable — skipped")

    ladder = _read_json(ddir / LADDER_STATUS_FILENAME)
    sources[LADDER_STATUS_FILENAME] = ladder is not None
    if isinstance(ladder, dict):
        signals.append({
            "type": "capital_ladder_level",
            "ts": ladder.get("updated_at"),
            "data": {
                "level_code": ladder.get("level_code"),
                "level_name": ladder.get("level_name"),
                "aum_usd": ladder.get("aum_usd"),
                "aum_cap_usd": ladder.get("aum_cap_usd"),
                "incidents_total": ladder.get("incidents_total"),
            },
        })
        incident = ladder.get("last_incident")
        if isinstance(incident, dict):
            signals.append({
                "type": "incident",
                "ts": incident.get("date") or incident.get("timestamp"),
                "data": incident,
            })
    else:
        notes.append(f"{LADDER_STATUS_FILENAME}: missing/unreadable — skipped")

    anchors_doc = _read_json(ddir / ANCHORS_FILENAME)
    sources[ANCHORS_FILENAME] = anchors_doc is not None
    anchors = anchors_doc.get("anchors") if isinstance(anchors_doc, dict) else None
    if isinstance(anchors, list):
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            signals.append({
                "type": "proof_of_track_anchor",
                "ts": anchor.get("computed_at"),
                "data": {
                    "date": anchor.get("date"),
                    "merkle_root": anchor.get("merkle_root"),
                    "leaf_count": anchor.get("leaf_count"),
                    "published": anchor.get("published") is True,
                },
            })
    else:
        notes.append(f"{ANCHORS_FILENAME}: missing/unreadable — skipped")

    if since_dt is not None:
        filtered: List[dict] = []
        dropped_no_ts = 0
        for sig in signals:
            ts = _parse_ts(sig.get("ts"))
            if ts is None:
                dropped_no_ts += 1
                continue
            if ts >= since_dt:
                filtered.append(sig)
        if dropped_no_ts:
            notes.append(
                f"{dropped_no_ts} signal(s) without parseable ts dropped by "
                "since-filter (honest: cannot compare)")
        signals = filtered
    signals.sort(key=lambda s: (s.get("ts") is None, str(s.get("ts") or "")))

    if not signals:
        notes.append("no signals available from source files")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "endpoint": "/v1/signals",
        "generated_at": _now_iso(now),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "since": since,
        "count": len(signals),
        "signals": signals,
        "sources": sources,
        "delivery": {"mode": "pull", "note": WEBHOOK_DELIVERY_NOTE},
        "notes": notes,
    }


# ─── Auth (sha256-ключи, plaintext не хранится) ──────────────────────────────


def hash_api_key(api_key: str) -> str:
    """sha256-хэш plaintext-ключа (hex) — единственное, что персистится."""
    return hashlib.sha256(str(api_key).encode("utf-8")).hexdigest()


def load_api_keys(*, data_dir: Optional[str | os.PathLike] = None) -> List[dict]:
    """Записи ключей из data/api_keys.json; нет файла/битый → [] (API закрыт)."""
    doc = _read_json(_data_dir(data_dir) / API_KEYS_FILENAME)
    keys = doc.get("keys") if isinstance(doc, dict) else None
    if not isinstance(keys, list):
        return []
    return [k for k in keys if isinstance(k, dict)]


def authenticate(
    api_key: Any, *, data_dir: Optional[str | os.PathLike] = None
) -> Optional[dict]:
    """Проверка ключа по sha256: ``{key_id, plan}`` | None.

    None: нет файла ключей (API закрыт по умолчанию), ключ не найден,
    запись неактивна. Сравнение — hmac.compare_digest."""
    if not isinstance(api_key, str) or not api_key:
        return None
    digest = hash_api_key(api_key)
    for entry in load_api_keys(data_dir=data_dir):
        stored = entry.get("key_hash")
        if not isinstance(stored, str):
            continue
        if hmac.compare_digest(stored.lower(), digest):
            if entry.get("active") is not True:
                return None
            return {"key_id": str(entry.get("key_id")),
                    "plan": str(entry.get("plan") or "basic")}
    return None


def generate_api_key(
    plan: str = "basic",
    *,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Сгенерировать ключ: в файл — ТОЛЬКО sha256, plaintext возвращается
    вызывающему один раз (CLI печатает и забывает). Атомарная запись,
    битый существующий файл толерантно = пустой."""
    plaintext = f"spa_wl_{secrets.token_urlsafe(32)}"
    key_id = f"key_{secrets.token_hex(6)}"
    path = _data_dir(data_dir) / API_KEYS_FILENAME
    doc = _read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        doc = {"schema_version": SCHEMA_VERSION, "keys": []}
    doc["keys"] = [k for k in doc["keys"] if isinstance(k, dict)]
    doc["keys"].append({
        "key_id": key_id,
        "key_hash": hash_api_key(plaintext),
        "plan": str(plan),
        "active": True,
        "created": _now_iso(now),
    })
    doc["last_updated"] = _now_iso(now)
    _atomic_write_json(path, doc)
    return {"key_id": key_id, "plan": str(plan), "api_key_plaintext": plaintext}


# ─── Rate limit (чистый in-memory fixed window per key_id) ───────────────────


class RateLimiter:
    """Fixed-window лимитер per key_id; clock инжектируется для тестов."""

    def __init__(
        self,
        limit: int = RATE_LIMIT_PER_MIN,
        window_sec: float = RATE_WINDOW_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = int(limit)
        self.window_sec = float(window_sec)
        self._clock = clock
        self._buckets: Dict[str, Tuple[float, int]] = {}

    def allow(self, key_id: str) -> bool:
        """True — запрос пропущен (счётчик окна инкрементирован), False — 429."""
        now = float(self._clock())
        start, count = self._buckets.get(key_id, (now, 0))
        if now - start >= self.window_sec:
            start, count = now, 0
        if count >= self.limit:
            self._buckets[key_id] = (start, count)
            return False
        self._buckets[key_id] = (start, count + 1)
        return True

    def remaining(self, key_id: str) -> int:
        """Остаток запросов в текущем окне (без инкремента)."""
        now = float(self._clock())
        start, count = self._buckets.get(key_id, (now, 0))
        if now - start >= self.window_sec:
            return self.limit
        return max(0, self.limit - count)


_GLOBAL_LIMITER = RateLimiter()


# ─── Billing-заготовка: учёт usage (атомарно, толерантно, ротация) ───────────


def load_usage(*, data_dir: Optional[str | os.PathLike] = None) -> Dict[str, dict]:
    """data/api_usage.json: {key_id: {requests_total, by_endpoint,
    last_request_at}}; нет/битый → {} (толерантно)."""
    doc = _read_json(_data_dir(data_dir) / USAGE_FILENAME)
    if not isinstance(doc, dict):
        return {}
    return {
        str(k): v for k, v in doc.items()
        if isinstance(v, dict) and isinstance(k, str)
    }


def record_usage(
    key_id: str,
    endpoint: str,
    *,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Инкремент счётчиков usage per key_id (ТОЛЬКО учёт — никакого
    биллинга). Атомарная запись; ротация ≤ USAGE_MAX_KEYS ключей
    (вытесняются записи с самым давним last_request_at)."""
    usage = load_usage(data_dir=data_dir)
    entry = usage.get(key_id)
    if not isinstance(entry, dict):
        entry = {"requests_total": 0, "by_endpoint": {}, "last_request_at": None}
    total = entry.get("requests_total")
    entry["requests_total"] = (total if isinstance(total, int) else 0) + 1
    by_ep = entry.get("by_endpoint")
    by_ep = dict(by_ep) if isinstance(by_ep, dict) else {}
    prev = by_ep.get(endpoint)
    by_ep[endpoint] = (prev if isinstance(prev, int) else 0) + 1
    entry["by_endpoint"] = by_ep
    entry["last_request_at"] = _now_iso(now)
    usage[key_id] = entry
    if len(usage) > USAGE_MAX_KEYS:
        ordered = sorted(
            usage.items(),
            key=lambda kv: str(kv[1].get("last_request_at") or ""),
        )
        for stale_key, _ in ordered[: len(usage) - USAGE_MAX_KEYS]:
            usage.pop(stale_key, None)
    _atomic_write_json(_data_dir(data_dir) / USAGE_FILENAME, usage)
    return entry


# ─── dispatch: маршрутизация + auth + rate limit + usage ─────────────────────

# path → (method, handler_kind)
_ROUTES: Dict[str, Tuple[str, str]] = {
    "/v1/portfolio/analyze": ("POST", "analyze"),
    "/v1/allocations/recommended": ("GET", "allocations"),
    "/v1/signals": ("GET", "signals"),
}


def _header(headers: Any, name: str) -> Optional[str]:
    """Case-insensitive чтение заголовка из dict-подобного объекта."""
    if headers is None:
        return None
    try:
        items = headers.items()
    except AttributeError:
        return None
    target = name.lower()
    for key, value in items:
        if str(key).lower() == target:
            return str(value)
    return None


def extract_api_key(headers: Any) -> Optional[str]:
    """API-ключ из ``X-API-Key`` либо ``Authorization: Bearer <key>``."""
    direct = _header(headers, "x-api-key")
    if direct:
        return direct.strip()
    auth = _header(headers, "authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _parse_query(query: str) -> Dict[str, str]:
    """Минимальный парсер query-string (без urllib): a=b&c=d → dict."""
    out: Dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        out[name] = value
    return out


def _parse_body(body: Any) -> Tuple[Optional[dict], Optional[dict]]:
    """(payload, None) | (None, 400-shape). dict — как есть; str/bytes — JSON."""
    if isinstance(body, dict):
        return body, None
    if body is None:
        return None, _err(400, "request body required (JSON object)")
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return None, _err(400, "request body is not valid UTF-8")
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except ValueError:
            return None, _err(400, "request body is not valid JSON")
        if not isinstance(parsed, dict):
            return None, _err(400, "request body must be a JSON object")
        return parsed, None
    return None, _err(400, "unsupported request body type")


def dispatch(
    method: str,
    path: str,
    headers: Any,
    body: Any,
    *,
    data_dir: Optional[str | os.PathLike] = None,
    limiter: Optional[RateLimiter] = None,
    now: Optional[datetime] = None,
    record: bool = True,
) -> Tuple[int, dict]:
    """Маршрутизатор white-label API: ``(status_code, dict)``.

    Порядок: 404 (неизвестный путь) → 405 (чужой метод) → 401 (auth по
    sha256-ключам; нет файла ключей = API закрыт) → 429 (rate limit per
    key_id) → usage-учёт (billing-заготовка; считается каждый
    аутентифицированный, не-429 запрос) → body parse (400) → handler.
    Никогда не raise: внутренняя ошибка → 500-shape без трейсбека."""
    limiter = limiter or _GLOBAL_LIMITER
    try:
        method = str(method or "").upper()
        raw_path = str(path or "")
        clean, _, query = raw_path.partition("?")
        clean = clean.rstrip("/") or "/"
        route = _ROUTES.get(clean)
        if route is None:
            return 404, _err(404, f"unknown path {clean!r}")
        expected_method, kind = route
        if method != expected_method:
            return 405, _err(
                405, f"method {method} not allowed for {clean} "
                     f"(expected {expected_method})")

        identity = authenticate(extract_api_key(headers), data_dir=data_dir)
        if identity is None:
            return 401, _err(
                401, "unauthorized: missing/invalid/inactive API key "
                     "(API is closed without data/api_keys.json)")
        if not limiter.allow(identity["key_id"]):
            return 429, _err(
                429, f"rate limit exceeded: {limiter.limit} requests per "
                     f"{int(limiter.window_sec)}s window")
        if record:
            record_usage(identity["key_id"], clean, data_dir=data_dir, now=now)

        if kind == "analyze":
            payload, perr = _parse_body(body)
            if perr is not None:
                return perr["code"], perr
            result = analyze_portfolio(payload, data_dir=data_dir, now=now)
        elif kind == "allocations":
            result = recommended_allocations(data_dir=data_dir, now=now)
        else:  # signals
            since = _parse_query(query).get("since") or None
            result = webhook_signals(since, data_dir=data_dir, now=now)
        if is_error(result):
            return result["code"], result
        return 200, result
    except Exception as exc:  # advisory API: никаких трейсбеков наружу
        log.error("dispatch failed: %s: %s", type(exc).__name__, exc)
        return 500, _err(500, f"internal error: {type(exc).__name__}")


# ─── Опциональный локальный сервер (НЕ дефолт; localhost only) ───────────────


def serve(
    port: int,
    *,
    data_dir: Optional[str | os.PathLike] = None,
    limiter: Optional[RateLimiter] = None,
) -> None:
    """Локальный stdlib http.server поверх dispatch — ТОЛЬКО по явному
    ``--serve`` (никогда не запускается по умолчанию), bind 127.0.0.1.
    Импорт http.server — лениво, чтобы offline-ядро не тянуло сокеты."""
    import http.server  # локальный импорт: только для явного --serve

    api_limiter = limiter or _GLOBAL_LIMITER

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else None
            status, doc = dispatch(
                self.command, self.path, dict(self.headers), body,
                data_dir=data_dir, limiter=api_limiter,
            )
            payload = (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _handle
        do_POST = _handle

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            log.info("whitelabel_api serve: " + fmt, *args)

    with http.server.ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler) as srv:
        log.info("whitelabel_api: serving on 127.0.0.1:%s (local only)", port)
        print(f"whitelabel_api: serving on http://127.0.0.1:{port} "
              f"(local only, Ctrl+C to stop)")
        srv.serve_forever()


# ─── Smoke self-test (для --check/--run) ─────────────────────────────────────

_SMOKE_PAYLOAD = {
    "positions": [
        {"protocol": "aave_v3", "amount_usd": 60000.0, "chain": "ethereum"},
        {"protocol": "totally_unknown_proto", "amount_usd": 40000.0},
    ]
}

# read-only источники, копируемые в tempdir для реалистичного smoke
_SMOKE_COPY_FILES = (
    RISK_SCORES_FILENAME,
    TARGET_ALLOC_FILENAME,
    ORCH_STATUS_FILENAME,
    RISK_BLOCKS_FILENAME,
    RISK_ALERTS_FILENAME,
    LADDER_STATUS_FILENAME,
    ANCHORS_FILENAME,
)

_SMOKE_EXPECTED = {
    "POST /v1/portfolio/analyze": 200,
    "GET /v1/allocations/recommended": 200,
    "GET /v1/signals": 200,
    "unauthorized": 401,
    "unknown_path": 404,
    "method_mismatch": 405,
    "rate_limited": 429,
}


def run_smoke(
    *, data_dir: Optional[str | os.PathLike] = None
) -> dict:
    """Smoke self-test dispatch на синтетическом ключе во ВРЕМЕННОЙ среде.

    Реальный data/ только ЧИТАЕТСЯ (источники копируются в tempdir);
    api_keys/usage пишутся ТОЛЬКО в tempdir и удаляются вместе с ним.
    Возвращает JSON-сводку {results, expected, ok}."""
    real = _data_dir(data_dir)
    with tempfile.TemporaryDirectory(prefix="spa_whitelabel_smoke_") as tmp:
        tdir = Path(tmp) / "data"
        tdir.mkdir()
        copied = []
        for name in _SMOKE_COPY_FILES:
            doc = _read_json(real / name)
            if doc is not None:
                _atomic_write_json(tdir / name, doc)
                copied.append(name)
        info = generate_api_key("basic", data_dir=tdir)
        headers = {"X-API-Key": info["api_key_plaintext"]}
        limiter = RateLimiter()
        results: Dict[str, int] = {}

        status, analyze_doc = dispatch(
            "POST", "/v1/portfolio/analyze", headers, dict(_SMOKE_PAYLOAD),
            data_dir=tdir, limiter=limiter)
        results["POST /v1/portfolio/analyze"] = status
        status, _ = dispatch(
            "GET", "/v1/allocations/recommended", headers, None,
            data_dir=tdir, limiter=limiter)
        results["GET /v1/allocations/recommended"] = status
        status, signals_doc = dispatch(
            "GET", "/v1/signals", headers, None,
            data_dir=tdir, limiter=limiter)
        results["GET /v1/signals"] = status
        results["unauthorized"] = dispatch(
            "GET", "/v1/signals", {}, None, data_dir=tdir, limiter=limiter)[0]
        results["unknown_path"] = dispatch(
            "GET", "/v1/nope", headers, None, data_dir=tdir, limiter=limiter)[0]
        results["method_mismatch"] = dispatch(
            "GET", "/v1/portfolio/analyze", headers, None,
            data_dir=tdir, limiter=limiter)[0]
        tiny = RateLimiter(limit=1)
        dispatch("GET", "/v1/signals", headers, None,
                 data_dir=tdir, limiter=tiny)
        results["rate_limited"] = dispatch(
            "GET", "/v1/signals", headers, None,
            data_dir=tdir, limiter=tiny)[0]

        usage = load_usage(data_dir=tdir)
        portfolio = (
            analyze_doc.get("portfolio") if isinstance(analyze_doc, dict) else {}
        ) or {}
        return {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mode": "smoke",
            "generated_at": _now_iso(),
            "synthetic_key_id": info["key_id"],
            "copied_sources": copied,
            "results": results,
            "expected": dict(_SMOKE_EXPECTED),
            "ok": results == _SMOKE_EXPECTED,
            "sample": {
                "weighted_risk_grade": portfolio.get("weighted_risk_grade"),
                "unknown_share_pct": portfolio.get("unknown_share_pct"),
                "signals_count": signals_doc.get("count")
                if isinstance(signals_doc, dict) else None,
                "usage_requests_total": (
                    usage.get(info["key_id"], {}).get("requests_total")),
            },
            "note": "smoke ran in tempdir; real data/ was read-only",
        }


# ─── CLI ─────────────────────────────────────────────────────────────────────


class _QuietParser(argparse.ArgumentParser):
    """argparse, который на мусорные аргументы НЕ делает sys.exit(2) с
    usage-простынёй, а бросает ValueError (CLI ловит → ERROR, exit 0)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValueError(message)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = _QuietParser(
        prog="python3 -m spa_core.api.whitelabel_api",
        description="SPA White-label API v1 (MP-407) — offline core: "
                    "handlers + dispatch + опциональный локальный сервер. "
                    "Advisory only, без egress.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="smoke self-test в tempdir, НИЧЕГО не пишет в "
                           "data/ (режим по умолчанию)")
    mode.add_argument("--run", action="store_true",
                      help="smoke + атомарная запись usage-снапшота "
                           "(_selftest) в data/api_usage.json")
    mode.add_argument("--gen-key", action="store_true",
                      help="сгенерировать API-ключ: plaintext печатается "
                           "ОДИН раз, в файл пишется только sha256")
    mode.add_argument("--serve", action="store_true",
                      help="ОПЦИОНАЛЬНЫЙ локальный http.server на "
                           "127.0.0.1 (НЕ дефолт)")
    p.add_argument("--plan", default="basic",
                   help="тарифный план для --gen-key (default: basic)")
    p.add_argument("--port", default="8788",
                   help="порт для --serve (default: 8788)")
    p.add_argument("--data-dir", default=None,
                   help="каталог data/ (по умолчанию <repo>/data)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = _build_arg_parser().parse_args(argv)
    except (ValueError, SystemExit) as exc:
        # мусорные аргументы → понятный ERROR, exit 0, без трейсбека
        print(f"ERROR: invalid arguments: {exc}", file=sys.stderr)
        return 0
    try:
        if args.gen_key:
            info = generate_api_key(args.plan, data_dir=args.data_dir)
            keys_path = _data_dir(args.data_dir) / API_KEYS_FILENAME
            print(f"whitelabel_api: key generated — key_id={info['key_id']} "
                  f"plan={info['plan']}")
            print(f"whitelabel_api: API key (shown ONCE, only sha256 stored "
                  f"in {keys_path}):")
            print(info["api_key_plaintext"])
            return 0
        if args.serve:
            try:
                port = int(args.port)
                if not (1 <= port <= 65535):
                    raise ValueError(f"port {port} out of range 1..65535")
            except ValueError as exc:
                print(f"ERROR: invalid --port: {exc}", file=sys.stderr)
                return 0
            serve(port, data_dir=args.data_dir)
            return 0
        summary = run_smoke(data_dir=args.data_dir)
        if args.run:
            entry = record_usage("_selftest", "smoke", data_dir=args.data_dir)
            summary["mode"] = "run"
            summary["usage_snapshot"] = {
                "path": str(_data_dir(args.data_dir) / USAGE_FILENAME),
                "key_id": "_selftest",
                "requests_total": entry.get("requests_total"),
            }
            summary["note"] = ("smoke ran in tempdir; usage snapshot written "
                               "atomically to data/")
        else:
            summary["mode"] = "check"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("whitelabel_api: stopped", file=sys.stderr)
        return 0
    except Exception as exc:  # advisory CLI: никогда не трейсбек
        print(f"ERROR: whitelabel_api failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
