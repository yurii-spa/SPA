#!/usr/bin/env python3
"""SPA investor portal — единый data-агрегатор (MP-408, SPA-V429) — offline-ядро.

Read-only / advisory агрегатор: собирает из СУЩЕСТВУЮЩИХ data/*.json один
машиночитаемый документ ``data/investor_portal_data.json``, который читает
статический ``investor_portal.html`` (offline-ядро портала; миграция на
Next.js — отдельным спринтом после деплой-инфраструктуры, песочница без
egress → npm/Next.js-сборка невозможна).

Источники (ВСЕ опциональны; отсутствие/битость → честные None/«нет данных»
+ запись в notes, никогда не raise, ничего не выдумываем):
* ``data/equity_curve_daily.json``          — equity curve + P&L; поля в
  ПРОЦЕНТАХ (``daily_return_pct``: 0.0087 == 0.0087%), как пишет cycle_runner;
  глобальный seed-бар (первый бар, его 0.0 — заглушка) исключается из
  return-метрик, как в risk_metrics._daily_returns.
* ``data/current_positions.json``           — exposure по протоколам, cash%.
* ``data/adapter_orchestrator_status.json`` — тиры (T1/T2/...) и chain
  протоколов (chain опционален: нет поля → честный "unknown").
* ``data/risk_scores.json``                 — grade/score по позициям (MP-104;
  нормализация имён «Aave V3»/«aave-v3» → aave_v3, как в whitelabel_api).
* ``data/tear_sheet_latest.json``           — headline-метрики месяца (MP-501):
  net APY / Sharpe / Sortino / PSR / maxDD.
* ``data/capital_ladder_status.json``       — ступень L0–L5, инциденты (MP-505).
* ``data/proof_of_track_anchors.json``      — Merkle-якоря (MP-406) для
  audit trail viewer (published/tx_hash честно как в файле).
* ``data/golive_status.json``               — вердикт anti-demo гейта MP-006.
* ``data/paper_trading_status.json``        — статус трека, is_demo честно.
* ``data/audit_trail.jsonl``                — последние ≤100 событий (MP-310)
  для audit trail viewer (битые строки молча пропускаются).

Переиспользование ИМПОРТОМ (модули НЕ модифицируются):
* ``tear_sheet.build_exposure / compound_return_pct /
  max_drawdown_from_returns`` (MP-501) — exposure и P&L-математика;
* ``capital_ladder.detect_incidents / INCIDENT_THRESHOLD_PCT`` (MP-505) —
  инциденты ≥1% AUM по всему треку.

Персист (атомарная запись tmp + os.replace, паттерн tear_sheet):
``data/investor_portal_data.json``; идемпотентность по
:func:`content_fingerprint` (весь doc без волатильных ``meta.generated_at``
и ``history``) — generated_at обновляется ТОЛЬКО при изменении контента,
повторный --run байт-в-байт ничего не меняет, history (ротация ≤500) не растёт.

CLI::

    python3 -m spa_core.reporting.portal_data --check     # по умолчанию
    python3 -m spa_core.reporting.portal_data --run
    python3 -m spa_core.reporting.portal_data --check --data-dir d

Офлайн, без сети, exit 0 всегда, без трейсбеков даже на пустых данных;
мусорные аргументы → понятный ERROR в stderr, exit 0.

Scope / safety: LLM FORBIDDEN — детерминированная логика, pure stdlib
(json/math/datetime/pathlib/argparse/logging/tempfile/os/re), без
requests/web3/pandas/numpy. STRICTLY READ-ONLY (SPA-BL-011): никогда не
трогает execution path, risk policy, кошельки, money-moving код — только
читает data/*.json и пишет собственный отчётный артефакт.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from spa_core.governance.capital_ladder import (
    INCIDENT_THRESHOLD_PCT,
    detect_incidents,
)
from spa_core.reporting.tear_sheet import (
    build_exposure,
    compound_return_pct,
    max_drawdown_from_returns,
)

log = logging.getLogger("spa.reporting.portal_data")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "portal_data"

STATUS_FILENAME = "investor_portal_data.json"
HISTORY_MAX = 500          # ротация истории прогонов (паттерн tear_sheet)
AUDIT_EVENTS_MAX = 100     # последних событий audit trail для viewer'а

EQUITY_FILENAME = "equity_curve_daily.json"
POSITIONS_FILENAME = "current_positions.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"
RISK_SCORES_FILENAME = "risk_scores.json"
TEAR_SHEET_FILENAME = "tear_sheet_latest.json"
LADDER_STATUS_FILENAME = "capital_ladder_status.json"
ANCHORS_FILENAME = "proof_of_track_anchors.json"
GOLIVE_STATUS_FILENAME = "golive_status.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
AUDIT_TRAIL_FILENAME = "audit_trail.jsonl"

SOURCE_FILES = (
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    ORCH_STATUS_FILENAME,
    RISK_SCORES_FILENAME,
    TEAR_SHEET_FILENAME,
    LADDER_STATUS_FILENAME,
    ANCHORS_FILENAME,
    GOLIVE_STATUS_FILENAME,
    PT_STATUS_FILENAME,
    AUDIT_TRAIL_FILENAME,
)

# Старт реального paper-трека (MP-007 / index.html REAL_TRACK_START).
REAL_TRACK_START = "2026-06-10"

DISCLAIMER = (
    "Paper track (read-only simulation), NOT investment advice. "
    "Все цифры — виртуальный paper-трек SPA без реальных средств; "
    "прошлая доходность не гарантирует будущую."
)


# ─── Толерантный IO (паттерн tear_sheet / capital_ladder) ────────────────────


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
    """Атомарная запись JSON: tmpfile в той же папке + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _num(value: Any) -> Optional[float]:
    """Число или None (bool — не число); NaN/inf — не данные."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _valid_date(value: Any) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def normalize_protocol(name: Any) -> str:
    """«Aave V3» / «aave-v3» / «aave_v3» → ``aave_v3``. Чистая функция."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


# ─── Equity curve / P&L (чистые функции) ─────────────────────────────────────


def valid_bars(daily: Any) -> List[dict]:
    """Валидные бары кривой, отсортированные по дате; мусор пропускается."""
    if not isinstance(daily, list):
        return []
    bars = [b for b in daily if isinstance(b, dict) and _valid_date(b.get("date"))]
    bars.sort(key=lambda b: str(b.get("date")))
    return bars


def return_series(daily: Any) -> List[dict]:
    """Дневные return'ы (%) ВСЕГО трека: [{date, return_pct}, ...].

    Глобальный seed-бар кривой (самый первый валидный бар — его
    ``daily_return_pct`` это 0.0-заглушка без прошлого close) исключается,
    в точности как ``risk_metrics._daily_returns`` исключает ``curve[0]``.
    Нечисловые return'ы молча пропускаются.
    """
    bars = valid_bars(daily)
    series: List[dict] = []
    for bar in bars[1:]:  # bars[0] — seed-бар
        ret = _num(bar.get("daily_return_pct"))
        if ret is None:
            continue
        series.append({"date": str(bar.get("date")), "return_pct": ret})
    return series


def build_equity_section(equity_doc: Any) -> dict:
    """Секция equity: кривая для графика + P&L (total/daily) в ПРОЦЕНТАХ.

    Чистая функция от содержимого equity_curve_daily.json. Битый/нет вход →
    ``{"available": False}`` с честными None. P&L-математика переиспользуется
    ИМПОРТОМ из tear_sheet (compound_return_pct / max_drawdown_from_returns).
    """
    daily = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    bars = valid_bars(daily)
    series = return_series(daily)
    returns = [p["return_pct"] for p in series]
    if not bars:
        return {
            "available": False,
            "num_days": 0,
            "first_date": None,
            "last_date": None,
            "curve": [],
            "pnl": {
                "total_return_pct": None,
                "today_return_pct": None,
                "num_return_days": 0,
                "max_drawdown_pct": None,
                "daily": [],
            },
        }
    curve = []
    for bar in bars:
        curve.append({
            "date": str(bar.get("date")),
            "equity": _num(bar.get("close_equity")) or _num(bar.get("equity")),
            "daily_return_pct": _num(bar.get("daily_return_pct")),
            "drawdown_pct": _num(bar.get("drawdown_pct")),
        })
    total = compound_return_pct(returns)
    return {
        "available": True,
        "num_days": len(bars),
        "first_date": curve[0]["date"],
        "last_date": curve[-1]["date"],
        "curve": curve,
        "pnl": {
            "total_return_pct": None if total is None else round(total, 6),
            "today_return_pct": series[-1]["return_pct"] if series else None,
            "num_return_days": len(series),
            "max_drawdown_pct": (
                round(max_drawdown_from_returns(returns), 6) if returns else None
            ),
            "daily": series,
        },
    }


# ─── Risk grades / chain exposure (чистые функции) ───────────────────────────


def build_grade_index(scores_doc: Any) -> dict:
    """Индекс normalized protocol → {grade, score_numeric} из risk_scores.json.

    Индексируются и ``protocol`` («Aave V3»), и ``slug`` («aave-v3») с
    нормализацией. Мусорные записи молча пропускаются.
    """
    index: dict = {}
    scores = scores_doc.get("scores") if isinstance(scores_doc, dict) else None
    if not isinstance(scores, list):
        return index
    for item in scores:
        if not isinstance(item, dict):
            continue
        entry = {
            "grade": item.get("grade") if isinstance(item.get("grade"), str) else None,
            "score_numeric": _num(item.get("score_numeric")),
        }
        for key in (item.get("protocol"), item.get("slug")):
            if isinstance(key, str) and key.strip():
                index[normalize_protocol(key)] = entry
    return index


def build_position_grades(positions_doc: Any, scores_doc: Any) -> dict:
    """Grade по каждой текущей позиции; неизвестный протокол → честный null."""
    raw = positions_doc.get("positions") if isinstance(positions_doc, dict) else None
    index = build_grade_index(scores_doc)
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for proto in sorted(raw, key=str):
        entry = index.get(normalize_protocol(proto))
        out[str(proto)] = {
            "known": entry is not None,
            "grade": entry["grade"] if entry else None,
            "score_numeric": entry["score_numeric"] if entry else None,
        }
    return out


def build_chain_exposure(exposure: dict, orch_doc: Any) -> dict:
    """Доли (%) по chain из exposure.by_protocol + chain-поля адаптеров.

    Поле ``chain`` у адаптеров опционально: нет поля / нет оркестратора →
    честный "unknown" (ничего не выдумывается).
    """
    chain_map: dict = {}
    if isinstance(orch_doc, dict) and isinstance(orch_doc.get("adapters"), list):
        for ad in orch_doc["adapters"]:
            if isinstance(ad, dict) and ad.get("protocol"):
                chain = ad.get("chain")
                chain_map[normalize_protocol(ad["protocol"])] = (
                    str(chain) if isinstance(chain, str) and chain.strip()
                    else "unknown"
                )
    by_chain: dict = {}
    by_protocol = exposure.get("by_protocol") if isinstance(exposure, dict) else None
    if not isinstance(by_protocol, dict):
        return by_chain
    for proto, info in by_protocol.items():
        share = _num(info.get("share_pct")) if isinstance(info, dict) else None
        if share is None:
            continue
        chain = chain_map.get(normalize_protocol(proto), "unknown")
        by_chain[chain] = round(by_chain.get(chain, 0.0) + share, 4)
    return dict(sorted(by_chain.items()))


# ─── Прочие секции (чистые функции) ──────────────────────────────────────────


def tear_sheet_headline(ts_doc: Any) -> dict:
    """Headline-метрики из tear_sheet_latest.json (MP-501); нет → available False."""
    if not isinstance(ts_doc, dict):
        return {"available": False, "period": None, "net_return_pct": None,
                "annualized_apy_pct": None, "win_rate_pct": None,
                "sharpe_ratio": None, "sortino_ratio": None, "psr": None,
                "max_drawdown_pct": None}
    meta = ts_doc.get("meta") if isinstance(ts_doc.get("meta"), dict) else {}
    perf = ts_doc.get("performance") if isinstance(ts_doc.get("performance"), dict) else {}
    risk = ts_doc.get("risk") if isinstance(ts_doc.get("risk"), dict) else {}
    psr = risk.get("psr") if isinstance(risk.get("psr"), dict) else {}
    return {
        "available": True,
        "period": meta.get("period"),
        "net_return_pct": _num(perf.get("net_return_pct")),
        "annualized_apy_pct": _num(perf.get("annualized_apy_pct")),
        "win_rate_pct": _num(perf.get("win_rate_pct")),
        "sharpe_ratio": _num(risk.get("sharpe_ratio")),
        "sortino_ratio": _num(risk.get("sortino_ratio")),
        "psr": _num(psr.get("psr")),
        "max_drawdown_pct": _num(risk.get("max_drawdown_pct")),
    }


def ladder_snapshot(ladder_doc: Any) -> Optional[dict]:
    """Срез capital_ladder_status.json (MP-505); битый/нет → None."""
    if not isinstance(ladder_doc, dict):
        return None
    climb = ladder_doc.get("climb") if isinstance(ladder_doc.get("climb"), dict) else {}
    return {
        "current_level": ladder_doc.get("current_level"),
        "level_code": ladder_doc.get("level_code"),
        "level_name": ladder_doc.get("level_name"),
        "aum_cap_usd": ladder_doc.get("aum_cap_usd"),
        "aum_usd": ladder_doc.get("aum_usd"),
        "track_days": ladder_doc.get("track_days"),
        "incidents_total": ladder_doc.get("incidents_total"),
        "last_incident": ladder_doc.get("last_incident"),
        "climb_eligible": climb.get("eligible") is True if climb else None,
        "climb_blockers": (
            [str(b) for b in climb.get("blockers", []) if isinstance(b, str)]
            if isinstance(climb.get("blockers"), list) else []
        ),
    }


def collect_anchors(anchors_doc: Any) -> List[dict]:
    """Все Merkle-якоря из proof_of_track_anchors.json (MP-406), по дате.

    Мусорные записи пропускаются; published/tx_hash честно как в файле.
    """
    out: List[dict] = []
    anchors = anchors_doc.get("anchors") if isinstance(anchors_doc, dict) else None
    if not isinstance(anchors, list):
        return out
    for a in anchors:
        if not isinstance(a, dict) or not _valid_date(a.get("date")):
            continue
        out.append({
            "date": str(a.get("date")),
            "merkle_root": a.get("merkle_root"),
            "leaf_count": a.get("leaf_count"),
            "published": a.get("published") is True,
            "tx_hash": a.get("tx_hash"),
            "note": a.get("note") if isinstance(a.get("note"), str) else None,
        })
    out.sort(key=lambda a: a["date"])
    return out


def read_audit_events(path: Path, limit: int = AUDIT_EVENTS_MAX) -> Optional[List[dict]]:
    """Последние ≤``limit`` событий audit_trail.jsonl (MP-310).

    Нет файла / нечитаем → None (честно «нет данных»). Битые строки и
    не-dict записи молча пропускаются — паттерн толерантного чтения.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    events: List[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events[-int(limit):]


# ─── Сборка полного документа ────────────────────────────────────────────────


def build_portal_data(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Единый документ инвестор-портала из существующих data/*.json.

    Никогда не raise на данных: все источники опциональны, отсутствие/
    битость честно отражается в ``notes`` и None-полях. Секции: meta /
    headline / equity / exposure / risk / tear_sheet / capital_ladder /
    proof_of_track / audit_trail / notes.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    notes: List[str] = []

    equity_doc = _read_json(ddir / EQUITY_FILENAME)
    if not isinstance(equity_doc, dict):
        notes.append(f"{EQUITY_FILENAME}: missing/unreadable — no equity curve/P&L")
    equity = build_equity_section(equity_doc)

    positions_doc = _read_json(ddir / POSITIONS_FILENAME)
    orch_doc = _read_json(ddir / ORCH_STATUS_FILENAME)
    exposure = build_exposure(positions_doc, orch_doc)  # переиспользование MP-501
    if not exposure.get("available"):
        notes.append(f"{POSITIONS_FILENAME}: missing/unreadable — no exposure")
    if not isinstance(orch_doc, dict):
        notes.append(f"{ORCH_STATUS_FILENAME}: missing/unreadable — tiers/chains unknown")
    exposure = dict(exposure)
    exposure["by_chain"] = build_chain_exposure(exposure, orch_doc)

    scores_doc = _read_json(ddir / RISK_SCORES_FILENAME)
    if not isinstance(scores_doc, dict):
        notes.append(f"{RISK_SCORES_FILENAME}: missing/unreadable — grades unknown")
    grades = build_position_grades(positions_doc, scores_doc)

    ts_doc = _read_json(ddir / TEAR_SHEET_FILENAME)
    tear = tear_sheet_headline(ts_doc)
    if not tear["available"]:
        notes.append(f"{TEAR_SHEET_FILENAME}: missing/unreadable — no headline metrics")

    ladder = ladder_snapshot(_read_json(ddir / LADDER_STATUS_FILENAME))
    if ladder is None:
        notes.append(f"{LADDER_STATUS_FILENAME}: missing/unreadable")

    anchors = collect_anchors(_read_json(ddir / ANCHORS_FILENAME))
    if not anchors:
        notes.append(f"{ANCHORS_FILENAME}: missing/unreadable or no anchors")

    golive = _read_json(ddir / GOLIVE_STATUS_FILENAME)
    if not isinstance(golive, dict):
        notes.append(f"{GOLIVE_STATUS_FILENAME}: missing/unreadable")
    pt = _read_json(ddir / PT_STATUS_FILENAME)
    if not isinstance(pt, dict):
        pt = {}
        notes.append(f"{PT_STATUS_FILENAME}: missing/unreadable")

    events = read_audit_events(ddir / AUDIT_TRAIL_FILENAME)
    if events is None:
        notes.append(f"{AUDIT_TRAIL_FILENAME}: missing/unreadable — no audit events")
    audit_trail = {
        "available": events is not None,
        "events_returned": len(events) if events is not None else 0,
        "limit": AUDIT_EVENTS_MAX,
        "events": events if events is not None else [],
    }

    is_demo = None
    for doc in (equity_doc, pt, positions_doc):
        if isinstance(doc, dict) and isinstance(doc.get("is_demo"), bool):
            is_demo = doc["is_demo"]
            break
    if is_demo is None:
        notes.append("is_demo: not reported by any source — honest null")

    # детект инцидентов по всему треку (переиспользование MP-505)
    bars = valid_bars(equity_doc.get("daily") if isinstance(equity_doc, dict) else None)
    incident_items = detect_incidents(bars)

    aum = None
    for candidate in (
        _num(positions_doc.get("capital_usd")) if isinstance(positions_doc, dict) else None,
        _num(pt.get("current_equity")),
        equity["curve"][-1]["equity"] if equity["curve"] else None,
    ):
        if candidate is not None:
            aum = candidate
            break

    headline = {
        "aum_usd": aum,
        "deployed_usd": exposure.get("deployed_usd"),
        "cash_pct": exposure.get("cash_pct"),
        "total_return_pct": equity["pnl"]["total_return_pct"],
        "today_return_pct": equity["pnl"]["today_return_pct"],
        "apy_today_pct": _num(pt.get("apy_today_pct")),
        "net_apy_pct": tear["annualized_apy_pct"],
        "sharpe_ratio": tear["sharpe_ratio"],
        "sortino_ratio": tear["sortino_ratio"],
        "psr": tear["psr"],
        "max_drawdown_pct": equity["pnl"]["max_drawdown_pct"],
        "ladder_level_code": ladder["level_code"] if ladder else None,
        "ladder_level_name": ladder["level_name"] if ladder else None,
        "track_days": pt.get("days_running"),
    }

    track = {
        "real_track_start": REAL_TRACK_START,
        "paper_start_date": pt.get("paper_start_date"),
        "days_running": pt.get("days_running"),
        "execution_mode": pt.get("execution_mode")
        or (equity_doc.get("execution_mode") if isinstance(equity_doc, dict) else None),
        "last_cycle_ts": pt.get("last_cycle_ts"),
        "golive_ready": golive.get("ready") is True
        if isinstance(golive, dict) else None,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "advisory_only": True,
            "is_demo": is_demo,
            "source_files": list(SOURCE_FILES),
            "track": track,
            "disclaimer": DISCLAIMER,
        },
        "headline": headline,
        "equity": equity,
        "exposure": exposure,
        "risk": {
            "grades": grades,
            "max_drawdown_pct": equity["pnl"]["max_drawdown_pct"],
            "incidents": {
                "threshold_pct": INCIDENT_THRESHOLD_PCT,
                "count": len(incident_items),
                "items": incident_items,
                "incidents_total_track": ladder["incidents_total"] if ladder else None,
                "last_incident": ladder["last_incident"] if ladder else None,
            },
        },
        "tear_sheet": tear,
        "capital_ladder": ladder,
        "proof_of_track": {
            "available": bool(anchors),
            "anchors_count": len(anchors),
            "published_count": sum(1 for a in anchors if a["published"]),
            "latest_root": anchors[-1]["merkle_root"] if anchors else None,
            "anchors": anchors,
            "note": "Merkle roots дневного audit-трека (MP-406); "
                    "published=false до on-chain публикации (MP-017)",
        },
        "audit_trail": audit_trail,
        "notes": notes,
    }


# ─── Персист (идемпотентность, паттерн tear_sheet) ───────────────────────────


def content_fingerprint(doc: Any) -> str:
    """Канонический отпечаток КОНТЕНТА документа. Чистая функция.

    Волатильные поля (``meta.generated_at``, top-level ``history``)
    исключаются: generated_at обновляется ТОЛЬКО при изменении контента,
    history — производная прошлых прогонов. Не-dict вход → отпечаток,
    который никогда не совпадёт с валидным doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: dict) -> dict:
    """Краткая запись истории прогонов для investor_portal_data.json."""
    meta = doc.get("meta") or {}
    headline = doc.get("headline") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "aum_usd": headline.get("aum_usd"),
        "total_return_pct": headline.get("total_return_pct"),
        "ladder_level_code": headline.get("ladder_level_code"),
        "incidents_count": ((doc.get("risk") or {}).get("incidents") or {}).get("count"),
    }


def write_status(
    doc: dict,
    data_dir: Optional[str | os.PathLike] = None,
) -> dict:
    """Атомарно пишет data/investor_portal_data.json.

    Идемпотентность: если контент (см. :func:`content_fingerprint`) не
    изменился относительно сохранённого статуса — файл НЕ перезаписывается
    (повторный --run байт-в-байт ничего не меняет, history не растёт,
    generated_at сохраняется прежний). При изменении контента в history
    добавляется запись (ротация ≤ HISTORY_MAX). Битый существующий
    статус-файл толерантно трактуется как отсутствующий.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    json_path = ddir / STATUS_FILENAME
    prev = _read_json(json_path)
    changed = content_fingerprint(prev) != content_fingerprint(doc)
    if not changed and isinstance(prev, dict):
        log.info("portal data unchanged: %s", json_path)
        return {"json": str(json_path), "changed": False}
    history: List[dict] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    doc = dict(doc)
    doc["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(json_path, doc)
    log.info("portal data written: %s", json_path)
    return {"json": str(json_path), "changed": True}


# ─── CLI ─────────────────────────────────────────────────────────────────────


class _ArgError(Exception):
    """Ошибка аргументов CLI (вместо sys.exit(2) стандартного argparse)."""


class _Parser(argparse.ArgumentParser):
    """argparse без sys.exit(2): мусорные аргументы → _ArgError → exit 0."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _ArgError(message)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="portal_data",
        description="Investor portal data aggregator (MP-408) — "
                    "read-only/advisory, без сети.",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="собрать и напечатать JSON БЕЗ записи (по умолчанию)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="собрать и атомарно записать data/investor_portal_data.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = _build_arg_parser().parse_args(argv)
    except _ArgError as exc:
        print(f"ERROR: invalid arguments: {exc}", file=sys.stderr)
        return 0
    try:
        doc = build_portal_data(data_dir=args.data_dir)
        if args.run:
            result = write_status(doc, data_dir=args.data_dir)
            headline = doc["headline"]
            print(
                f"PORTAL DATA: "
                f"{'written' if result['changed'] else 'unchanged (idempotent)'} "
                f"{result['json']} "
                f"(aum={headline['aum_usd']}, "
                f"total={headline['total_return_pct']}%, "
                f"anchors={doc['proof_of_track']['anchors_count']}, "
                f"audit_events={doc['audit_trail']['events_returned']})"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # advisory CLI: никогда не трейсбек
        print(f"ERROR: portal_data failed: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
