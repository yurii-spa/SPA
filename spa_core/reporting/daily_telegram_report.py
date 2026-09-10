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

Sources (all read-only, all optional — a missing/corrupt file degrades the
corresponding fields gracefully, never raises):

* ``data/equity_curve_daily.json``    — equity bar + positions for the date
* ``data/paper_trading_status.json``  — days running, APY, cycle status
* ``data/golive_status.json``         — passed/total + blockers
* ``data/adapter_status.json``        — per-protocol display_name + APY
                                        (execution-owned: READ ONLY, never write)
* ``data/tournament_results.json``    — best active strategy by net APY
* ``data/risk_policy_blocks.json``    — today's RiskPolicy gate blocks

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
# ``apy_fallback`` is used only when adapter_status.json has no live datapoint.
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


def _adapter_meta(adapter_doc: Any) -> dict[str, dict]:
    """protocol_key → {display_name, apy} from adapter_status.json (read-only)."""
    out: dict[str, dict] = {}
    if not isinstance(adapter_doc, dict):
        return out
    adapters = adapter_doc.get("adapters")
    if not isinstance(adapters, dict):
        return out
    for key, meta in adapters.items():
        if isinstance(meta, dict):
            out[str(key)] = {
                "display_name": meta.get("display_name", str(key)),
                "apy": meta.get("apy"),
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


def _live_apy(info: dict, fallback: float) -> float:
    """Live APY for a Base adapter, preferring apy_pct then apy then fallback.

    adapter_status.json sometimes carries ``apy_pct: None`` alongside a populated
    ``apy`` (percent units), so a plain ``.get("apy_pct", ...)`` would yield None.
    """
    apy = info.get("apy_pct")
    if apy is None:
        apy = info.get("apy")
    if apy is None:
        apy = fallback
    return float(apy)


def _collect_base_chain(adapter_doc: Any, data_dir: Path) -> dict:
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
        rows.append({
            "label": meta["label"],
            "tier": meta["tier"],
            "apy": _live_apy(info, meta["apy_fallback"]),
            "suspended": False,
        })

    # Surface any Base adapter present live but not in the static registry.
    known = set(_BASE_ADAPTERS_REGISTRY)
    for adapter_id, info in live.items():
        if adapter_id not in known:
            rows.append({
                # Имя для человека, если адаптер его объявил; иначе ключ как есть.
                "label": str(info.get("display_name") or adapter_id),
                "tier": f"T{info['tier']}" if isinstance(info.get("tier"), int) else info.get("tier", "?"),
                "apy": _live_apy(info, 0.0),
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
    tournament_doc = _read_json(ddir / TOURNAMENT_FILENAME, {})
    blocks_doc = _read_json(ddir / RISK_BLOCKS_FILENAME, [])

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
    apy_expected: float | None = None
    unobservable_pools: list[str] = []
    yield_forgone_usd: float | None = None
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
        # ADR-298/299: если часть книги стои́т под НЕнаблюдаемой ставкой, доход ниже
        # ожидаемого — и владелец обязан прочитать ПРИЧИНУ там же, где цифру. Иначе
        # он увидит падение APY и решит, что испортился рынок.
        _unobs = bar.get("unobservable_pools")
        if isinstance(_unobs, list) and _unobs:
            unobservable_pools = [str(x) for x in _unobs]
        _forgone = bar.get("yield_forgone_usd")
        if isinstance(_forgone, (int, float)) and _forgone:
            yield_forgone_usd = float(_forgone)
        _exp = bar.get("apy_expected_pct")
        if isinstance(_exp, (int, float)):
            apy_expected = float(_exp)
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
    adapter_meta = _adapter_meta(adapter_doc)
    best_strategy = _best_strategy(tournament_doc)

    golive_passed = golive_doc.get("passed")
    golive_total = golive_doc.get("total", 26)
    golive_blockers = golive_doc.get("blockers", [])
    if not isinstance(golive_blockers, list):
        golive_blockers = []
    # Честный счётчик дней (аудит 08.09): «Day 91» считался по календарю от
    # paper_start_date, «0 days to 30-day track» — от него же, а сам гейт
    # go-live меряет ПОДТВЕРЖДЁННЫЕ дни от evidenced_anchor (77 с 2026-06-22).
    # Три разных числа об одном треке в одном сообщении. Оба числа остаются,
    # но подписываются тем, что они есть; отсутствие — «не измерено», не 0.
    real_track_days = golive_doc.get("real_track_days")
    if not isinstance(real_track_days, int):
        real_track_days = None
    evidenced_anchor = golive_doc.get("evidenced_anchor")
    if not isinstance(evidenced_anchor, str):
        evidenced_anchor = None

    cycles_today = status_doc.get("cycles_today")
    cycle_errors = status_doc.get("cycle_errors_today")
    last_cycle_status = status_doc.get("last_cycle_status")
    risk_approved = status_doc.get("risk_policy_approved")
    risk_blocks = _risk_blocks_today(blocks_doc, date_str)

    base_chain = _collect_base_chain(adapter_doc, ddir)

    # Все три пакета + общая картина (запрос владельца 2026-08-31; те же числа,
    # что на /admin/portfolio-summary). Fail-closed: недоступная книга видна
    # как «недоступно», никогда не как выдуманный ноль.
    from spa_core.reporting.books_summary import collect_books_summary
    books_summary = collect_books_summary(ddir, now=now_dt)

    return {
        "date": date_str,
        "generated_at": now_dt.isoformat(),
        "day_number": day_number,
        "equity_usd": equity_usd,
        "daily_pnl_usd": daily_pnl_usd,
        "apy_today_pct": apy_today,
        "apy_expected_pct": apy_expected,          # ADR-301
        "unobservable_pools": unobservable_pools,  # ADR-298
        "yield_forgone_usd": yield_forgone_usd,    # ADR-298
        "apy_7day_avg_pct": avg7,
        "best_strategy": best_strategy,
        "positions": positions,
        "adapter_meta": adapter_meta,
        "golive_passed": golive_passed,
        "golive_total": golive_total,
        "golive_blockers": golive_blockers,
        "days_to_track_target": _days_to_track_target(day_number),
        "real_track_days": real_track_days,
        "evidenced_anchor": evidenced_anchor,
        # До 30-дневного трека — от ПОДТВЕРЖДЁННЫХ дней (как считает gate),
        # а не от календаря; None, когда gate не отработал.
        "days_to_track_target_evidenced": _days_to_track_target(real_track_days),
        "cycles_today": cycles_today,
        "cycle_errors_today": cycle_errors,
        "last_cycle_status": last_cycle_status,
        "risk_policy_approved": risk_approved,
        "risk_blocks_today": risk_blocks,
        "base_chain": base_chain,
        "books_summary": books_summary,
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


# Советательные книги: ведут paper-трек, но капитал не двигают (IS_ADVISORY,
# инвариант #9). Их годовая ставка обязана быть подписана — иначе «~11.4% год.»
# читается как живая доходность (аудит 08.09).
_ADVISORY_BOOKS = frozenset({"balanced", "aggressive"})
_ADVISORY_MARK = "(paper, капитал не двигают)"


def _header_lines(data: dict) -> list[str]:
    """Заголовок + честный счётчик дней: календарный И подтверждённый — подписаны оба."""
    day = data.get("day_number")
    date_str = data.get("date", "")
    lines = [f"📊 <b>SPA — отчёт за день</b> ({_esc(date_str)})"]
    cal = f"день {day} по календарю" if isinstance(day, int) else "день по календарю: не измерен"
    real = data.get("real_track_days")
    anchor = data.get("evidenced_anchor")
    if isinstance(real, int):
        since = f" (с {_esc(anchor)})" if anchor else ""
        lines.append(f"🗓 {cal} · подтверждённых дней {real}{since}")
    else:
        lines.append(f"🗓 {cal} · подтверждённых дней: не измерено")
    return lines


def _books_lines(data: dict) -> list[str]:
    """Три независимых пакета + общая картина (owner request 2026-08-31).

    Числа те же, что на /admin/portfolio-summary; недоступная книга видна
    честно, а не выдуманным нулём и не молчаливым пропуском.
    """
    bs = data.get("books_summary")
    if not (isinstance(bs, dict) and bs.get("books")):
        return []
    lines = ["📚 <b>Пакеты (3 независимые книги)</b>"]
    for key in ("conservative", "balanced", "aggressive"):
        b = bs["books"].get(key) or {}
        label = b.get("label") or key.capitalize()
        if not b.get("available"):
            lines.append(f"  • {_esc(label)}: недоступно ({_esc(b.get('reason', '?'))})")
            continue
        ret = b.get("return_pct")
        ret_str = f"{ret:+.2f}%" if isinstance(ret, (int, float)) else "—"
        ann = b.get("annualized_apy_pct")
        mark = f" {_ADVISORY_MARK}" if key in _ADVISORY_BOOKS else ""
        ann_str = f", ~{ann:.1f}% год.{mark}" if isinstance(ann, (int, float)) else ""
        lines.append(f"  • {_esc(label)}: {_fmt_money(b.get('equity'))} ({ret_str}{ann_str})")
    c = bs.get("combined") or {}
    n_avail = c.get("books_available")
    n_total = c.get("books_total")
    comb_ret = c.get("combined_return_pct")
    comb_str = f"{comb_ret:+.2f}%" if isinstance(comb_ret, (int, float)) else "—"
    partial = (
        f" — сумма ЧАСТИЧНАЯ ({n_avail} из {n_total} книг)"
        if isinstance(n_avail, int) and isinstance(n_total, int) and n_avail < n_total
        else ""
    )
    lines.append(f"  Σ Всего: {_fmt_money(c.get('total_equity_usd'))} ({comb_str}){partial}")
    lines.append("")
    return lines


def _positions_lines(data: dict) -> list[str]:
    """Позиции по убыванию суммы, кэш последним."""
    positions = data.get("positions") or {}
    meta = data.get("adapter_meta") or {}
    unobservable = set(data.get("unobservable_pools") or ())   # ADR-298
    equity = data.get("equity_usd")
    total = sum(v for v in positions.values() if isinstance(v, (int, float)))
    equity_base = equity if isinstance(equity, (int, float)) and equity > 0 else total
    lines = ["📍 Позиции:"]
    ordered = sorted(
        ((k, v) for k, v in positions.items() if isinstance(v, (int, float)) and v > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    for key, val in ordered[:MAX_POSITION_LINES]:
        m = meta.get(key, {})
        name = m.get("display_name", key)
        pct = (val / equity_base * 100) if equity_base else 0.0
        apy_p = m.get("apy")
        apy_str = f" — {apy_p:.1f}% APY" if isinstance(apy_p, (int, float)) else ""
        # ADR-298: ставка из реестра рядом с позицией, которая НЕ начисляет, — самая
        # тихая неправда в отчёте: число стои́т, а денег с него нет. Помечаем прямо здесь.
        if key in unobservable:
            apy_str = (f" — {apy_p:.1f}% в справочнике, но НЕ наблюдается ⇒ начисляет 0"
                       if isinstance(apy_p, (int, float))
                       else " — ставка не наблюдается ⇒ начисляет 0")
        lines.append(f"  • {_esc(name)}: ${val:,.0f} ({pct:.1f}%){apy_str}")
    rest = ordered[MAX_POSITION_LINES:]
    if rest:
        rest_usd = sum(v for _, v in rest)
        rest_pct = (rest_usd / equity_base * 100) if equity_base else 0.0
        lines.append(f"  • +{len(rest)} ещё: ${rest_usd:,.0f} ({rest_pct:.1f}%)")
    # Кэш = капитал, не разложенный по позициям.
    if isinstance(equity_base, (int, float)) and equity_base > 0:
        cash = equity_base - total
        if cash > 0.5:
            lines.append(f"  • Кэш: ${cash:,.0f} ({cash / equity_base * 100:.1f}%)")
    lines.append("")
    return lines


def _golive_cycle_risk_lines(data: dict) -> list[str]:
    lines: list[str] = []
    passed = data.get("golive_passed")
    gtotal = data.get("golive_total")
    if isinstance(passed, int) and isinstance(gtotal, int):
        # Остаток до 30-дневного трека — от подтверждённых дней (как у gate);
        # календарный остаток «0 days» врал при 77 подтверждённых.
        left = data.get("days_to_track_target_evidenced")
        if isinstance(left, int):
            note = (" · 30-дневный трек набран ✅" if left == 0
                    else f" · до 30-дневного трека {left} дн.")
        else:
            note = " · трек: не измерен"
        lines.append(f"🎯 Готовность к go-live: {passed}/{gtotal}{note}")

    cycles = data.get("cycles_today")
    errors = data.get("cycle_errors_today")
    if isinstance(cycles, int):
        err_n = errors if isinstance(errors, int) else 0
        lines.append(f"⚡ Цикл: сегодня запусков {cycles}, ошибок {err_n}")
    elif data.get("last_cycle_status"):
        lines.append(f"⚡ Цикл: последний статус {_esc(data['last_cycle_status'])}")

    blocks = data.get("risk_blocks_today", 0)
    approved = data.get("risk_policy_approved")
    if blocks:
        lines.append(f"🔒 Риск-гейт: блокировок сегодня {blocks} (см. risk_policy_blocks.json)")
    elif approved is True:
        lines.append("🔒 Риск-гейт: все позиции в пределах лимитов")
    return lines


def _base_chain_lines(data: dict) -> list[str]:
    """Base Chain — наблюдение без капитала (ADR-025 Phase 1, merged from daily_paper_report)."""
    bc = data.get("base_chain")
    if not isinstance(bc, dict):
        return []
    lines = ["", "🔵 <b>Base Chain (наблюдение без капитала)</b>"]
    gas = bc.get("gas") or {}
    if not gas.get("available"):
        lines.append("  ⚪ Газ: нет данных")
    elif gas.get("kill"):
        lines.append(f"  ⛔ Стоп-кран по газу ВКЛЮЧЁН: {gas.get('gwei', 0.0):.2f} Gwei "
                     f"× {gas.get('consecutive', 0)} дн.")
    elif gas.get("consecutive", 0) > 0:
        lines.append(f"  ⚠️ Газ выше порога: {gas.get('gwei', 0.0):.2f} Gwei "
                     f"({gas.get('consecutive', 0)}/3 дн.)")
    else:
        lines.append(f"  ✅ Газ: {gas.get('gwei', 0.0):.2f} Gwei (норма)")
    for row in bc.get("adapters", []):
        tier = f"уровень {_esc(row['tier'])}"
        if row.get("suspended"):
            lines.append(f"  🚫 {_esc(row['label'])} ({tier}): ПРИОСТАНОВЛЕН")
        else:
            lines.append(f"  📊 {_esc(row['label'])} ({tier}): {row['apy']:.1f}% APY (наблюдение)")
    # Строка «Phase 1 … until 2026-07-12» снята (аудит 08.09): срок истёк,
    # литерал не читал ни одного файла и обещал то, чего никто не мерил.
    return lines


def format_daily_message(data: dict) -> str:
    """Render the HTML Telegram message from :func:`build_report_data` output.

    Русские заголовки (аудит 08.09: английские шапки вперемешку с русским
    хвостом владелец читать не может). Числа и их смысл не меняются — только
    подпись, порядок и язык.
    """
    lines: list[str] = _header_lines(data)
    lines.append("")

    equity = data.get("equity_usd")
    pnl = data.get("daily_pnl_usd")
    lines.append(f"💰 Портфель: {_fmt_money(equity)} ({_fmt_money(pnl, signed=True)} за день)")
    apy = data.get("apy_today_pct")
    avg7 = data.get("apy_7day_avg_pct")
    lines.append(f"📈 APY (paper): {_fmt_pct(apy)} (среднее за 7 дней: {_fmt_pct(avg7)})")
    # ADR-298/299: цифра ниже ожидаемой — рядом её причина. Строки нет, когда вся книга
    # наблюдаема: молчание здесь означает «нечего объяснять», а не «не проверяли».
    _unobs = data.get("unobservable_pools")
    if isinstance(_unobs, list) and _unobs:
        _exp = data.get("apy_expected_pct")
        _forg = data.get("yield_forgone_usd")
        _tail = ""
        if isinstance(_exp, (int, float)):
            _tail += f" · ожидание при полной наблюдаемости {_fmt_pct(_exp)}"
        if isinstance(_forg, (int, float)):
            _tail += f" · недобор {_fmt_money(_forg)}/день"
        lines.append(
            "   ↳ ставка не наблюдается у: " + ", ".join(_esc(x) for x in _unobs) +
            _tail + " — эти позиции начисляют НОЛЬ (ADR-298), а не продаются")

    # Блок рендерится ТОЛЬКО когда турнир кого-то выбрал (`_best_strategy` даёт
    # None при отказе всем / нулевых net_apy) — при пустых данных строки нет.
    best = data.get("best_strategy")
    if isinstance(best, dict):
        sid = best.get("strategy_id", "?")
        lines.append(f"🏆 Лучшая стратегия сегодня: {_esc(sid)} ({_fmt_pct(best.get('net_apy'))} APY)")
    lines.append("")

    lines.extend(_books_lines(data))
    lines.extend(_positions_lines(data))
    lines.extend(_golive_cycle_risk_lines(data))
    lines.extend(_base_chain_lines(data))
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
