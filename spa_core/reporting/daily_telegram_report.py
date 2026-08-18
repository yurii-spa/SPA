#!/usr/bin/env python3
"""Enhanced daily Telegram report for SPA paper trading (runs ~08:00 UTC).

Aggregates one day of the real paper-trading track into a rich, human-readable
Telegram message:

    📊 SPA Daily Report — Day 12 (2026-06-21)

    💰 Portfolio: $100,121 (+$45 today)
    📈 Paper APY: 4.82% (7-day avg: 4.71%)
    🏆 Best strategy today: S7 (+5.2% APY)

    📍 Positions:
      • Aave V3: $23,750 (23.7%) — 3.8% APY
      • Compound: $38,000 (38.0%) — 4.2% APY
      • Cash: $5,000 (5.0%)

    🎯 GoLive: 25/26 (19 days to 30-day track ✅)
    ⚡ Cycle: ran 6x today, 0 errors
    🔒 Risk gate: all positions within limits
    🚦 Daily limits (DL-01..05): PASS — daily loss 0.12% (limit 2.0%)

Sources (all read-only, all optional — a missing/corrupt file degrades the
corresponding fields gracefully, never raises):

* ``data/equity_curve_daily.json``    — equity bar + positions for the date
* ``data/paper_trading_status.json``  — days running, APY, cycle status
* ``data/golive_status.json``         — passed/total + blockers
* ``data/adapter_status.json``        — per-protocol display_name + APY
                                        (execution-owned: READ ONLY, never write)
* ``data/tournament_results.json``    — best active strategy by net APY
* ``data/risk_policy_blocks.json``    — today's RiskPolicy gate blocks
* ``data/risk_limits_check.json``     — DailyLimitsChecker verdict DL-01..DL-05
                                        (cycle-written; read-only here, and a
                                        missing/stale snapshot is reported as
                                        UNKNOWN, never as PASS)

Secrets policy (incident 2026-06-10): Telegram credentials are NEVER stored in
files — ``telegram_client`` reads them from the macOS Keychain at runtime.

Stdlib only. Never raises — every public entry point returns a dict.

CLI::

    python3 -m spa_core.reporting.daily_telegram_report --check   # print, no send
    python3 -m spa_core.reporting.daily_telegram_report --run     # send to Telegram
    python3 -m spa_core.reporting.daily_telegram_report --run --date 2026-06-20
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from spa_core.adapters import status_reader


def _esc(value: Any) -> str:
    """HTML-escape a dynamic value for parse_mode=HTML.

    Protocol/strategy/display names are external data and may contain ``< > &``
    which would break Telegram's HTML parser (a 400). Underscores are HTML-safe
    (the ``_`` problem is Markdown-only). Static template markup is never passed
    through here — only interpolated dynamic strings.
    """
    return html.escape(str(value), quote=False)

log = logging.getLogger("spa.reporting.daily_telegram")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

EQUITY_FILENAME = "equity_curve_daily.json"
STATUS_FILENAME = "paper_trading_status.json"
GOLIVE_FILENAME = "golive_status.json"
ADAPTER_FILENAME = "adapter_status.json"
TOURNAMENT_FILENAME = "tournament_results.json"
RISK_BLOCKS_FILENAME = "risk_policy_blocks.json"
CIO_FILENAME = "portfolio_cio.json"          # Portfolio CIO §34 (advisory, shadow)
#: Снимок старше этого возраста в отчёт НЕ попадает: устаревшая рекомендация
#: опаснее отсутствующей — владелец примет её за сегодняшнюю.
CIO_MAX_AGE_HOURS = 26.0
#: Вердикт DailyLimitsChecker (DL-01…DL-05), который цикл пишет каждый прогон
#: (``cycle_runner`` → ``DailyLimitsChecker.save_result``). Отчёт его только ЧИТАЕТ.
RISK_LIMITS_FILENAME = "risk_limits_check.json"
#: Старше этого возраста вердикт не выдаётся за сегодняшний (цикл ходит ежедневно).
DAILY_LIMITS_MAX_AGE_HOURS = 26.0

# Real track started 2026-06-10 (everything before is demo/teardown-invalid).
PAPER_START_FALLBACK = "2026-06-10"
# Continuous-track requirement before go-live review (ADR-002).
TRACK_TARGET_DAYS = 30
# Cap the per-position list so the Telegram message stays readable; the
# remainder is collapsed into one summary line.
MAX_POSITION_LINES = 8

# Base chain monitoring registry (ADR-025 Phase 1 — merged from the former
# scripts/daily_paper_report.py so this is the single 08:00 morning report).
# ``suspended=True`` → rendered with a SUSPENDED label, no capital allocated.
# ``apy_fallback`` БОЛЬШЕ НЕ ЧИТАЕТСЯ (ADR-089 п.3, 2026-08-18): подстановка
# литерала вместо отсутствующего наблюдения — ровно тот дефект, который эта
# задача закрывает. Поле оставлено как исторический ориентир порядка величины и
# закреплено тестом `test_apy_one_definition.py` как НЕ-вход отчёта; удалять его
# нужно отдельно, вместе с потребителями реестра.
_BASE_ADAPTERS_REGISTRY: dict[str, dict] = {
    "aave_v3_base": {"tier": "T2", "label": "Aave V3 Base", "apy_fallback": 4.5, "suspended": False},
    "morpho_blue_base": {"tier": "T2", "label": "Morpho Blue Base", "apy_fallback": 6.2, "suspended": False},
    "moonwell_base": {"tier": "T3", "label": "Moonwell Base", "apy_fallback": 0.0, "suspended": True},
    "extra_finance_base": {"tier": "T3", "label": "Extra Finance XLend", "apy_fallback": 8.0, "suspended": False},
}


# ─── IO helpers ──────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → ``default`` (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── Pure helpers ────────────────────────────────────────────────────────────


def _find_equity_bar(equity_doc: Any, date_str: str) -> dict | None:
    """The daily bar matching ``date_str``; falls back to the latest bar."""
    if not isinstance(equity_doc, dict):
        return None
    daily = equity_doc.get("daily")
    if not isinstance(daily, list) or not daily:
        return None
    for bar in daily:
        if isinstance(bar, dict) and bar.get("date") == date_str:
            return bar
    last = daily[-1]
    return last if isinstance(last, dict) else None


def _seven_day_avg_apy(equity_doc: Any, date_str: str) -> float | None:
    """Trailing 7-day average of ``apy_today`` up to and including ``date_str``."""
    if not isinstance(equity_doc, dict):
        return None
    daily = equity_doc.get("daily")
    if not isinstance(daily, list) or not daily:
        return None
    bars = [b for b in daily if isinstance(b, dict) and b.get("date", "") <= date_str]
    window = bars[-7:] if bars else daily[-7:]
    apys = [
        float(b["apy_today"])
        for b in window
        if isinstance(b.get("apy_today"), (int, float))
    ]
    if not apys:
        return None
    return sum(apys) / len(apys)


def _track_day_number(date_str: str, paper_start: str) -> int | None:
    """1-based day index of ``date_str`` within the real track."""
    try:
        d0 = datetime.strptime(paper_start, "%Y-%m-%d").date()
        d1 = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    delta = (d1 - d0).days
    return delta + 1 if delta >= 0 else None


#: Как называется отсутствие наблюдения в строке отчёта. Молчаливый пропуск —
#: не вариант: «APY не показали» и «APY 0» читаются одинаково, а «показали
#: литерал» вообще неотличимо от замера. Владелец должен видеть ПРИЧИНУ.
_APY_REASON_RU: dict[str, str] = {
    status_reader.APY_NOT_OBSERVED: "APY не наблюдался",
    status_reader.APY_STALE: "APY: наблюдение протухло",
    status_reader.APY_UNKNOWN_AGE: "APY: возраст наблюдения неизвестен",
}


def _apy_suffix(row: dict) -> str:
    """Хвост строки позиции: наблюдённый APY либо названная причина его отсутствия."""
    apy = row.get("apy") if isinstance(row, dict) else None
    if isinstance(apy, (int, float)) and not isinstance(apy, bool):
        return f" — {apy:.1f}% APY"
    reason = str(row.get("apy_reason") or "") if isinstance(row, dict) else ""
    return f" — {_APY_REASON_RU.get(reason, 'APY не наблюдался')}"


def _adapter_meta(adapter_doc: Any, now_dt: datetime | None = None) -> dict[str, dict]:
    """protocol_key → {display_name, apy, apy_reason} из adapter_status.json.

    ADR-089 п.3 — одно определение наблюдения на репозиторий. Раньше здесь
    читалось соседнее поле ``apy``, а оно при ``live_apy: null`` просто повторяет
    ``fallback_apy`` (``adapter_status_generator``: ``apy_used = live_apy if
    live_apy is not None else fallback_pct``). Замер 2026-08-18 на живом
    ``data/adapter_status.json``: наблюдений — НОЛЬ из 34, а отчёт называл число
    для всех 34 — то есть печатал константу из реестра как доходность позиции.
    Аллокатор в той же ситуации протокол просто не берёт.

    Теперь единственный судья — :func:`status_reader.observed_apy_pct_fresh`
    (``live_apy`` + окно :data:`status_reader.EVIDENCE_MAX_AGE_H`). Второй копии
    правила здесь нет и быть не должно: именно так дефект ADR-063 и расползался.
    ``apy is None`` ⇒ отчёт обязан назвать причину, а не подставить литерал.
    """
    out: dict[str, dict] = {}
    if not isinstance(adapter_doc, dict):
        return out
    adapters = adapter_doc.get("adapters")
    if not isinstance(adapters, dict):
        return out
    for key, meta in adapters.items():
        if isinstance(meta, dict):
            apy, reason = status_reader.observed_apy_pct_fresh(meta, now=now_dt)
            out[str(key)] = {
                "display_name": meta.get("display_name", str(key)),
                "apy": apy,
                "apy_reason": reason,
            }
    return out


def _best_strategy(tournament_doc: Any) -> dict | None:
    """Active strategy with the highest ``net_apy`` (None if none/zero data)."""
    if not isinstance(tournament_doc, dict):
        return None
    strats = tournament_doc.get("strategies")
    if not isinstance(strats, list):
        return None
    active = [
        s
        for s in strats
        if isinstance(s, dict)
        and s.get("is_active")
        and isinstance(s.get("net_apy"), (int, float))
    ]
    if not active:
        return None
    best = max(active, key=lambda s: float(s["net_apy"]))
    if float(best["net_apy"]) <= 0:
        return None
    return best


def _cio_section(cio_doc: Any, now_dt: datetime) -> dict | None:
    """Секция Portfolio CIO для дневного отчёта (§34) — или None.

    Fail-CLOSED тремя способами: нет снимка, снимок протух, снимок не advisory ⇒
    секции нет вовсе. Отчёт при этом остаётся ровно таким, каким был: отсутствие
    рекомендации не должно ломать доставку остальных чисел.
    """
    if not isinstance(cio_doc, dict) or not cio_doc:
        return None
    if cio_doc.get("is_advisory") is not True:
        return None
    stamp = cio_doc.get("generated_at")
    try:
        age_h = (now_dt - datetime.fromisoformat(str(stamp))).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None
    if age_h > CIO_MAX_AGE_HOURS or age_h < -1.0:
        return None
    decision = str(cio_doc.get("decision") or "")
    if decision not in ("KEEP", "REBALANCE", "DEFER"):
        return None
    return {
        "decision": decision,
        "current_apy_pp": cio_doc.get("current_expected_apy_pp"),
        "optimal_apy_pp": cio_doc.get("optimal_expected_apy_pp"),
        "yield_gap_pp": cio_doc.get("yield_gap_pp"),
        "cost_usd": cio_doc.get("switching_cost_usd"),
        "payback_days": cio_doc.get("payback_days"),
        "reasons": [str(r) for r in (cio_doc.get("reasons") or [])][:2],
        "age_hours": round(age_h, 2),
    }


def _daily_limits_section(limits_doc: Any, now_dt: datetime) -> dict:
    """Вердикт дневных лимитов (DL-01…DL-05) для отчёта — ВСЕГДА словарь.

    Отвечает на вопрос, которого в отчёте не было: «дневной лимит убытка сегодня
    сработал?». Читает снимок, который цикл уже пишет сам
    (``data/risk_limits_check.json``); порогов не знает и не считает — вердикт
    вынесен гейтом, отчёт его только показывает.

    Почему словарь, а не ``None`` как у CIO: тишина в строке про лимит убытка
    читается владельцем как «лимит не сработал», то есть «не знаю» и «всё чисто»
    стали бы неразличимы. Fail-CLOSED здесь = НАЗВАТЬ незнание
    (``gate="UNKNOWN"`` + причина словами), а не промолчать и не показать
    вчерашний PASS за сегодняшний.
    """
    unknown: dict[str, Any] = {
        "gate": "UNKNOWN",
        "unknown_reason": "no snapshot on disk",
        "halt_reasons": [],
        "warn_reasons": [],
        "dl01": None,
        "age_hours": None,
    }
    if not isinstance(limits_doc, dict) or not limits_doc:
        return unknown

    stamp = limits_doc.get("checked_at")
    try:
        age_h = (now_dt - datetime.fromisoformat(str(stamp))).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return {**unknown, "unknown_reason": "snapshot has no readable timestamp"}
    if age_h > DAILY_LIMITS_MAX_AGE_HOURS or age_h < -1.0:
        return {
            **unknown,
            "unknown_reason": f"snapshot {age_h:.1f}h old",
            "age_hours": round(age_h, 2),
        }

    gate = str(limits_doc.get("gate") or "")
    if gate not in ("PASS", "WARN", "HALT"):
        return {
            **unknown,
            "unknown_reason": "snapshot carries no known verdict",
            "age_hours": round(age_h, 2),
        }

    dl01: dict | None = None
    checks = limits_doc.get("checks")
    if isinstance(checks, list):
        for chk in checks:
            if isinstance(chk, dict) and chk.get("id") == "DL-01":
                dl01 = {
                    "status": str(chk.get("status") or "?"),
                    "value": chk.get("value"),
                    "limit": chk.get("limit"),
                }
                break

    return {
        "gate": gate,
        "unknown_reason": None,
        "halt_reasons": [str(r) for r in (limits_doc.get("halt_reasons") or [])][:3],
        "warn_reasons": [str(r) for r in (limits_doc.get("warn_reasons") or [])][:3],
        "dl01": dl01,
        "age_hours": round(age_h, 2),
    }


def _risk_blocks_today(blocks_doc: Any, date_str: str) -> int:
    """Number of RiskPolicy gate block events recorded on ``date_str``."""
    if not isinstance(blocks_doc, list):
        return 0
    return sum(
        1
        for b in blocks_doc
        if isinstance(b, dict) and b.get("date") == date_str
    )


def _days_to_track_target(day_number: int | None) -> int | None:
    """Calendar days remaining until the 30-day continuous track completes."""
    if day_number is None:
        return None
    return max(TRACK_TARGET_DAYS - day_number, 0)


def _live_apy(info: dict, now_dt: datetime | None = None) -> tuple[float | None, str]:
    """(APY в процентах, причина) для Base-адаптера — ОДНО определение (ADR-089 п.3).

    Было: ``apy_pct`` → ``apy`` → литерал ``apy_fallback`` из
    ``_BASE_ADAPTERS_REGISTRY``. Поля ``apy_pct`` в блоках
    ``adapter_status.json → adapters`` нет вовсе (это имя из снимка
    оркестратора), поэтому лестница всегда падала на ``apy``, а ``apy`` при
    ``live_apy: null`` — эхо ``fallback_apy``. Если и его не было, печатался
    зашитый прямо здесь литерал (``aave_v3_base: 4.5``) — и всё это выходило
    владельцу строкой «4.5% APY (monitoring)», неотличимой от замера.

    Теперь судит :func:`status_reader.observed_apy_pct_fresh`; литерала в этом
    пути больше нет (`.claude/rules/adapters.md`: нет данных ⇒ ``None``).
    """
    return status_reader.observed_apy_pct_fresh(info, now=now_dt)


def _collect_base_chain(
    adapter_doc: Any, data_dir: Path, now_dt: datetime | None = None
) -> dict:
    """Gas status + Base adapter APYs for the report (ADR-025 Phase 1).

    All read-only and optional — every failure degrades gracefully. Base adapters
    live under ``adapter_status.json → adapters`` (chain == "base").
    """
    gas: dict = {"available": False, "error": None}
    try:
        from spa_core.monitoring.base_gas_monitor import BaseGasMonitor

        status = BaseGasMonitor(data_dir=str(data_dir)).get_status()
        gas = {
            "available": True,
            "gwei": status.get("gwei") or 0.0,
            "consecutive": status.get("consecutive_above", 0),
            "kill": bool(status.get("kill_switch_active", False)),
        }
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        gas = {"available": False, "error": str(exc)}

    live: dict[str, dict] = {}
    if isinstance(adapter_doc, dict):
        adapters = adapter_doc.get("adapters")
        if isinstance(adapters, dict):
            live = {
                k: v
                for k, v in adapters.items()
                if isinstance(v, dict) and v.get("chain") == "base"
            }

    rows: list[dict] = []
    for adapter_id, meta in _BASE_ADAPTERS_REGISTRY.items():
        if meta["suspended"]:
            rows.append({"label": meta["label"], "tier": meta["tier"], "suspended": True})
            continue
        info = live.get(adapter_id, {})
        apy, reason = _live_apy(info, now_dt)
        rows.append({
            "label": meta["label"],
            "tier": meta["tier"],
            "apy": apy,
            "apy_reason": reason,
            "suspended": False,
        })

    # Surface any Base adapter present live but not in the static registry.
    known = set(_BASE_ADAPTERS_REGISTRY)
    for adapter_id, info in live.items():
        if adapter_id not in known:
            apy, reason = _live_apy(info, now_dt)
            rows.append({
                "label": adapter_id,
                "tier": f"T{info['tier']}" if isinstance(info.get("tier"), int) else info.get("tier", "?"),
                "apy": apy,
                "apy_reason": reason,
                "suspended": False,
            })

    return {"gas": gas, "adapters": rows}


# ─── Report assembly ─────────────────────────────────────────────────────────


def build_report_data(
    date_str: str | None = None,
    *,
    data_dir: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Collect every field the daily Telegram message needs.

    ``date_str`` defaults to today (UTC). Never raises.
    """
    now_dt = now or datetime.now(timezone.utc)
    if date_str is None:
        date_str = now_dt.date().isoformat()

    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    equity_doc = _read_json(ddir / EQUITY_FILENAME, {})
    status_doc = _read_json(ddir / STATUS_FILENAME, {})
    golive_doc = _read_json(ddir / GOLIVE_FILENAME, {})
    adapter_doc = _read_json(ddir / ADAPTER_FILENAME, {})
    cio_doc = _read_json(ddir / CIO_FILENAME, {})
    tournament_doc = _read_json(ddir / TOURNAMENT_FILENAME, {})
    blocks_doc = _read_json(ddir / RISK_BLOCKS_FILENAME, [])
    limits_doc = _read_json(ddir / RISK_LIMITS_FILENAME, {})

    if not isinstance(status_doc, dict):
        status_doc = {}
    if not isinstance(golive_doc, dict):
        golive_doc = {}

    paper_start = status_doc.get("paper_start_date") or PAPER_START_FALLBACK
    day_number = _track_day_number(date_str, str(paper_start))

    bar = _find_equity_bar(equity_doc, date_str)
    equity_usd: float | None = None
    daily_pnl_usd: float | None = None
    apy_today: float | None = None
    positions: dict[str, float] = {}
    if bar is not None:
        close = bar.get("close_equity", bar.get("equity"))
        open_ = bar.get("open_equity")
        if isinstance(close, (int, float)):
            equity_usd = float(close)
        if isinstance(close, (int, float)) and isinstance(open_, (int, float)):
            daily_pnl_usd = float(close) - float(open_)
        if isinstance(bar.get("apy_today"), (int, float)):
            apy_today = float(bar["apy_today"])
        bar_pos = bar.get("positions")
        if isinstance(bar_pos, dict):
            positions = {
                str(k): float(v)
                for k, v in bar_pos.items()
                if isinstance(v, (int, float))
            }

    # Fall back to live status when the dated bar is unavailable.
    if equity_usd is None and isinstance(status_doc.get("current_equity"), (int, float)):
        equity_usd = float(status_doc["current_equity"])
    if apy_today is None and isinstance(status_doc.get("apy_today_pct"), (int, float)):
        apy_today = float(status_doc["apy_today_pct"])
    if daily_pnl_usd is None and isinstance(status_doc.get("daily_yield_usd"), (int, float)):
        daily_pnl_usd = float(status_doc["daily_yield_usd"])
    if not positions:
        live_pos = status_doc.get("current_positions")
        if isinstance(live_pos, dict):
            positions = {
                str(k): float(v)
                for k, v in live_pos.items()
                if isinstance(v, (int, float))
            }

    avg7 = _seven_day_avg_apy(equity_doc, date_str)
    adapter_meta = _adapter_meta(adapter_doc, now_dt)
    best_strategy = _best_strategy(tournament_doc)

    golive_passed = golive_doc.get("passed")
    golive_total = golive_doc.get("total", 26)
    golive_blockers = golive_doc.get("blockers", [])
    if not isinstance(golive_blockers, list):
        golive_blockers = []

    cycles_today = status_doc.get("cycles_today")
    cycle_errors = status_doc.get("cycle_errors_today")
    last_cycle_status = status_doc.get("last_cycle_status")
    risk_approved = status_doc.get("risk_policy_approved")
    risk_blocks = _risk_blocks_today(blocks_doc, date_str)

    base_chain = _collect_base_chain(adapter_doc, ddir, now_dt)

    return {
        "date": date_str,
        "generated_at": now_dt.isoformat(),
        "day_number": day_number,
        "equity_usd": equity_usd,
        "daily_pnl_usd": daily_pnl_usd,
        "apy_today_pct": apy_today,
        "apy_7day_avg_pct": avg7,
        "best_strategy": best_strategy,
        "positions": positions,
        "adapter_meta": adapter_meta,
        "golive_passed": golive_passed,
        "golive_total": golive_total,
        "golive_blockers": golive_blockers,
        "days_to_track_target": _days_to_track_target(day_number),
        "cycles_today": cycles_today,
        "cycle_errors_today": cycle_errors,
        "last_cycle_status": last_cycle_status,
        "risk_policy_approved": risk_approved,
        "risk_blocks_today": risk_blocks,
        "daily_limits": _daily_limits_section(limits_doc, now_dt),
        "portfolio_cio": _cio_section(cio_doc, now_dt),
        "base_chain": base_chain,
    }


def _fmt_money(value: Any, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if signed:
        sign = "+" if value >= 0 else "−"
        return f"{sign}${abs(value):,.0f}"
    return f"${value:,.0f}"


def _fmt_pct(value: Any) -> str:
    return f"{value:.2f}%" if isinstance(value, (int, float)) else "—"


def _fmt_dl01(dl01: Any) -> str:
    """Хвост строки с ЧИСЛОМ дневного убытка — ради него карточка и заведена.

    Нет числа (SKIP / чужой формат) — так и написано; выдумывать «0.00%» нельзя.
    """
    if not isinstance(dl01, dict):
        return ""
    status = dl01.get("status")
    value = dl01.get("value")
    limit = dl01.get("limit")
    if status == "SKIP" or not isinstance(value, (int, float)):
        return " — daily loss: not measured (SKIP)"
    lim = f" (limit {limit:.1f}%)" if isinstance(limit, (int, float)) else ""
    # Отрицательное «падение» — это прибыль дня; печатаем как есть, без знака-ловушки.
    if value < 0:
        return f" — daily change +{abs(value):.2f}%{lim}"
    return f" — daily loss {value:.2f}%{lim}"


def format_daily_message(data: dict) -> str:
    """Render the HTML Telegram message from :func:`build_report_data` output."""
    lines: list[str] = []

    day = data.get("day_number")
    date_str = data.get("date", "")
    header_day = f"Day {day} " if isinstance(day, int) else ""
    lines.append(f"📊 <b>SPA Daily Report</b> — {header_day}({date_str})")
    lines.append("")

    equity = data.get("equity_usd")
    pnl = data.get("daily_pnl_usd")
    lines.append(f"💰 Portfolio: {_fmt_money(equity)} ({_fmt_money(pnl, signed=True)} today)")

    apy = data.get("apy_today_pct")
    avg7 = data.get("apy_7day_avg_pct")
    avg7_str = _fmt_pct(avg7)
    lines.append(f"📈 Paper APY: {_fmt_pct(apy)} (7-day avg: {avg7_str})")

    best = data.get("best_strategy")
    if isinstance(best, dict):
        sid = best.get("strategy_id", "?")
        napy = best.get("net_apy")
        lines.append(f"🏆 Best strategy today: {_esc(sid)} ({_fmt_pct(napy)} APY)")
    lines.append("")

    # Positions block — sorted by USD descending, cash last.
    positions = data.get("positions") or {}
    meta = data.get("adapter_meta") or {}
    total = sum(v for v in positions.values() if isinstance(v, (int, float)))
    equity_base = equity if isinstance(equity, (int, float)) and equity > 0 else total
    lines.append("📍 Positions:")
    ordered = sorted(
        ((k, v) for k, v in positions.items() if isinstance(v, (int, float)) and v > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    shown = ordered[:MAX_POSITION_LINES]
    for key, val in shown:
        m = meta.get(key, {})
        name = m.get("display_name", key)
        pct = (val / equity_base * 100) if equity_base else 0.0
        lines.append(
            f"  • {_esc(name)}: ${val:,.0f} ({pct:.1f}%){_apy_suffix(m)}"
        )
    rest = ordered[MAX_POSITION_LINES:]
    if rest:
        rest_usd = sum(v for _, v in rest)
        rest_pct = (rest_usd / equity_base * 100) if equity_base else 0.0
        lines.append(f"  • +{len(rest)} more: ${rest_usd:,.0f} ({rest_pct:.1f}%)")
    # Cash = equity not deployed into positions.
    if isinstance(equity_base, (int, float)) and equity_base > 0:
        cash = equity_base - total
        if cash > 0.5:
            cash_pct = cash / equity_base * 100
            lines.append(f"  • Cash: ${cash:,.0f} ({cash_pct:.1f}%)")
    lines.append("")

    # GoLive
    passed = data.get("golive_passed")
    gtotal = data.get("golive_total")
    days_left = data.get("days_to_track_target")
    if isinstance(passed, int) and isinstance(gtotal, int):
        track_note = ""
        if isinstance(days_left, int):
            check = " ✅" if days_left == 0 else ""
            track_note = f" ({days_left} days to 30-day track{check})"
        lines.append(f"🎯 GoLive: {passed}/{gtotal}{track_note}")

    # Cycle
    cycles = data.get("cycles_today")
    errors = data.get("cycle_errors_today")
    if isinstance(cycles, int):
        err_n = errors if isinstance(errors, int) else 0
        lines.append(f"⚡ Cycle: ran {cycles}x today, {err_n} errors")
    elif data.get("last_cycle_status"):
        lines.append(f"⚡ Cycle: last status {data['last_cycle_status']}")

    # Risk gate
    blocks = data.get("risk_blocks_today", 0)
    approved = data.get("risk_policy_approved")
    if blocks:
        lines.append(
            f"🔒 Risk gate: {blocks} block event(s) today — "
            f"see data/risk_blocks_daily/{_esc(date_str)}.json"
        )
    elif approved is True:
        lines.append("🔒 Risk gate: all positions within limits")

    # Daily risk limits (DL-01..DL-05, MP-375) — ДРУГОЙ сторож, другой вопрос:
    # «сработал ли сегодня дневной лимит убытка». Строка есть ВСЕГДА, включая
    # «вердикта нет» — иначе молчание читается как «лимит чист».
    dl = data.get("daily_limits")
    if isinstance(dl, dict):
        gate = dl.get("gate")
        if gate == "HALT":
            lines.append("🛑 Daily limits: HALT — allocation blocked today")
            for reason in dl.get("halt_reasons") or []:
                lines.append(f"  • {_esc(reason)}")
        elif gate == "WARN":
            lines.append(f"⚠️ Daily limits: WARN{_fmt_dl01(dl.get('dl01'))}")
            for reason in dl.get("warn_reasons") or []:
                lines.append(f"  • {_esc(reason)}")
        elif gate == "PASS":
            lines.append(
                f"🚦 Daily limits (DL-01..05): PASS{_fmt_dl01(dl.get('dl01'))}"
            )
        else:
            lines.append(
                "⚪ Daily limits: NO FRESH VERDICT "
                f"({_esc(dl.get('unknown_reason') or 'unknown')}) — "
                "daily-loss limit UNCONFIRMED for today"
            )

    # Portfolio CIO (§34) — только если снимок есть и свеж; иначе отчёт как был.
    cio = data.get("portfolio_cio")
    if isinstance(cio, dict):
        _ru = {"KEEP": "ОСТАВЛЯЕМ", "REBALANCE": "ПЕРЕКЛАДЫВАЕМ", "DEFER": "ЖДЁМ УДЕШЕВЛЕНИЯ"}
        lines.append("")
        lines.append("🧠 <b>Portfolio CIO</b>")
        lines.append("Сейчас ожидаем: {} · можно: {} · разрыв: {}".format(
            _fmt_pct(cio.get("current_apy_pp")), _fmt_pct(cio.get("optimal_apy_pp")),
            _fmt_pct(cio.get("yield_gap_pp"))))
        lines.append("Решение: {}".format(_esc(_ru.get(cio.get("decision"), cio.get("decision")))))
        if cio.get("decision") in ("REBALANCE", "DEFER"):
            payback = cio.get("payback_days")
            lines.append("Стоимость: {} · окупаемость: {}".format(
                _fmt_money(cio.get("cost_usd")),
                "—" if payback is None else "{:.0f} дн.".format(float(payback))))
        for reason in cio.get("reasons") or []:
            lines.append("  • {}".format(_esc(reason)))

    # Base chain monitoring (ADR-025 Phase 1 — merged from daily_paper_report).
    bc = data.get("base_chain")
    if isinstance(bc, dict):
        lines.append("")
        lines.append("🔵 <b>Base Chain (ADR-025 Phase 1)</b>")
        gas = bc.get("gas") or {}
        if not gas.get("available"):
            lines.append("  ⚪ Gas: unavailable")
        elif gas.get("kill"):
            lines.append(
                f"  ⛔ Gas Kill-Switch ACTIVE! {gas.get('gwei', 0.0):.2f} Gwei "
                f"× {gas.get('consecutive', 0)} days"
            )
        elif gas.get("consecutive", 0) > 0:
            lines.append(
                f"  ⚠️ Gas above threshold: {gas.get('gwei', 0.0):.2f} Gwei "
                f"({gas.get('consecutive', 0)}/3 days)"
            )
        else:
            lines.append(f"  ✅ Gas: {gas.get('gwei', 0.0):.2f} Gwei (normal)")
        for row in bc.get("adapters", []):
            if row.get("suspended"):
                lines.append(f"  🚫 {_esc(row['label'])} [{_esc(row['tier'])}]: SUSPENDED")
            else:
                lines.append(
                    f"  📊 {_esc(row['label'])} [{_esc(row['tier'])}]: "
                    f"{_apy_suffix(row).removeprefix(' — ')} (monitoring)"
                )
        lines.append("  ℹ️ Phase 1: monitoring without capital → until 2026-07-12")

    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────


def _send_html(message: str) -> bool:
    """Send via Keychain-backed telegram_client (HTML mode). Never raises."""
    try:
        from spa_core.alerts.telegram_client import _post_message as _tg_post
        return _tg_post({"text": message, "parse_mode": "HTML"})
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        log.warning("daily_telegram_report: send failed: %s", exc)
        return False


def run_daily_report(
    date_str: str | None = None,
    *,
    data_dir: str | Path | None = None,
    send: bool = True,
    now: datetime | None = None,
) -> dict:
    """Build and (optionally) send the daily report.

    Returns ``{"sent": bool, "message": str, "data": dict, "error": str | None}``.
    Never raises.
    """
    result: dict[str, Any] = {"sent": False, "message": "", "data": {}, "error": None}
    try:
        data = build_report_data(date_str, data_dir=data_dir, now=now)
        message = format_daily_message(data)
        result["data"] = data
        result["message"] = message
        if send:
            result["sent"] = _send_html(message)
            if not result["sent"]:
                result["error"] = "Telegram send returned False"
    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("run_daily_report: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="daily_telegram_report",
        description="Enhanced daily SPA Telegram report.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print preview, do not send")
    group.add_argument("--run", action="store_true", help="send to Telegram")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        data = build_report_data(args.date, data_dir=args.data_dir)
        message = format_daily_message(data)
        print(re.sub(r"<[^>]+>", "", message))
        return 0

    result = run_daily_report(args.date, data_dir=args.data_dir, send=True)
    if result["sent"]:
        print("✅ Daily report sent")
    else:
        print(f"⚠️  Not sent: {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
