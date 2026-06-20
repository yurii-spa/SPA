#!/usr/bin/env python3
"""Weekly Telegram summary for SPA paper trading (runs Sundays ~10:00 UTC).

Rolls up the trailing 7-day window of the real paper-trading track:

    📋 SPA Weekly Summary — Week 2 (June 15-21, 2026)

    📈 Week performance: +0.09% (+$90)
    📊 APY this week: 4.71% avg
    💼 Starting capital: $100,031
    💼 Ending capital: $100,121

    🏆 Strategy ranking (advisory):
    1. S7 Hybrid: 5.2% APY
    2. S11 sFRAX: 4.8% APY
    3. S0 Conservative: 4.1% APY

    🔄 Rebalances: 3 (threshold triggers)
    🛡️ Risk blocks: 0
    📋 GoLive progress: 25/26 (2 weeks remaining for 30-day track)

    Next week goal: accumulate 7 more track days

Sources (all read-only, all optional — degrade gracefully, never raise):

* ``data/equity_curve_daily.json``    — week window equity + APY
* ``data/tournament_results.json``    — advisory strategy ranking
* ``data/trades.json``                — rebalance count in window
* ``data/risk_policy_blocks.json``    — risk-block count in window
* ``data/golive_status.json``         — passed/total
* ``data/paper_trading_status.json``  — paper_start_date

Stdlib only. Never raises — every public entry point returns a dict.

CLI::

    python3 -m spa_core.reporting.weekly_telegram_report --check   # print, no send
    python3 -m spa_core.reporting.weekly_telegram_report --run     # send to Telegram
    python3 -m spa_core.reporting.weekly_telegram_report --run --end 2026-06-21
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.reporting.weekly_telegram")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

EQUITY_FILENAME = "equity_curve_daily.json"
TOURNAMENT_FILENAME = "tournament_results.json"
TRADES_FILENAME = "trades.json"
RISK_BLOCKS_FILENAME = "risk_policy_blocks.json"
GOLIVE_FILENAME = "golive_status.json"
STATUS_FILENAME = "paper_trading_status.json"

PAPER_START_FALLBACK = "2026-06-10"
TRACK_TARGET_DAYS = 30

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Optional human-friendly strategy names for the ranking block.
STRATEGY_NAMES = {
    "S0": "Conservative",
    "S7": "Hybrid",
    "S8": "Delta-Neutral sUSDe",
    "S9": "E-Mode Looping",
    "S10": "Pendle YT",
    "S11": "sFRAX",
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


def _window_dates(end_date: str) -> tuple[str, str]:
    """7-day window (inclusive) ending on ``end_date`` → (start_str, end_str)."""
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _bars_in_window(equity_doc: Any, start: str, end: str) -> list[dict]:
    """Daily bars whose date is within [start, end] inclusive."""
    if not isinstance(equity_doc, dict):
        return []
    daily = equity_doc.get("daily")
    if not isinstance(daily, list):
        return []
    return [
        b
        for b in daily
        if isinstance(b, dict)
        and isinstance(b.get("date"), str)
        and start <= b["date"] <= end
    ]


def _week_number(end_date: str, paper_start: str) -> int | None:
    """1-based week index of the window end within the real track."""
    try:
        d0 = datetime.strptime(paper_start, "%Y-%m-%d").date()
        d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    delta = (d1 - d0).days
    if delta < 0:
        return None
    return delta // 7 + 1


def _format_range(start: str, end: str) -> str:
    """Human range like ``June 15-21, 2026`` (or cross-month variant)."""
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return f"{start} – {end}"
    if s.month == e.month and s.year == e.year:
        return f"{_MONTHS[s.month - 1]} {s.day}-{e.day}, {e.year}"
    return f"{_MONTHS[s.month - 1]} {s.day} – {_MONTHS[e.month - 1]} {e.day}, {e.year}"


def _avg_apy(bars: list[dict]) -> float | None:
    apys = [
        float(b["apy_today"])
        for b in bars
        if isinstance(b.get("apy_today"), (int, float))
    ]
    return sum(apys) / len(apys) if apys else None


def _rebalances_in_window(trades_doc: Any, start: str, end: str) -> int:
    """Count rebalance trades whose timestamp date falls in the window."""
    if not isinstance(trades_doc, list):
        return 0
    n = 0
    for t in trades_doc:
        if not isinstance(t, dict) or t.get("type") != "rebalance":
            continue
        ts = t.get("ts", "")
        date = ts[:10] if isinstance(ts, str) else ""
        if start <= date <= end:
            n += 1
    return n


def _risk_blocks_in_window(blocks_doc: Any, start: str, end: str) -> int:
    if not isinstance(blocks_doc, list):
        return 0
    return sum(
        1
        for b in blocks_doc
        if isinstance(b, dict)
        and isinstance(b.get("date"), str)
        and start <= b["date"] <= end
    )


def _top_strategies(tournament_doc: Any, limit: int = 3) -> list[dict]:
    """Top active strategies by net APY (advisory)."""
    if not isinstance(tournament_doc, dict):
        return []
    strats = tournament_doc.get("strategies")
    if not isinstance(strats, list):
        return []
    active = [
        s
        for s in strats
        if isinstance(s, dict)
        and s.get("is_active")
        and isinstance(s.get("net_apy"), (int, float))
        and float(s["net_apy"]) > 0
    ]
    active.sort(key=lambda s: float(s["net_apy"]), reverse=True)
    return active[:limit]


# ─── Report assembly ─────────────────────────────────────────────────────────


def build_weekly_data(
    end_date: str | None = None,
    *,
    data_dir: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Collect every field the weekly Telegram message needs. Never raises."""
    now_dt = now or datetime.now(timezone.utc)
    if end_date is None:
        end_date = now_dt.date().isoformat()

    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    equity_doc = _read_json(ddir / EQUITY_FILENAME, {})
    tournament_doc = _read_json(ddir / TOURNAMENT_FILENAME, {})
    trades_doc = _read_json(ddir / TRADES_FILENAME, [])
    blocks_doc = _read_json(ddir / RISK_BLOCKS_FILENAME, [])
    golive_doc = _read_json(ddir / GOLIVE_FILENAME, {})
    status_doc = _read_json(ddir / STATUS_FILENAME, {})

    if not isinstance(golive_doc, dict):
        golive_doc = {}
    if not isinstance(status_doc, dict):
        status_doc = {}

    start, end = _window_dates(end_date)
    paper_start = status_doc.get("paper_start_date") or PAPER_START_FALLBACK

    bars = _bars_in_window(equity_doc, start, end)
    start_equity: float | None = None
    end_equity: float | None = None
    if bars:
        first = bars[0]
        last = bars[-1]
        oe = first.get("open_equity")
        ce = last.get("close_equity", last.get("equity"))
        if isinstance(oe, (int, float)):
            start_equity = float(oe)
        if isinstance(ce, (int, float)):
            end_equity = float(ce)

    week_pnl_usd: float | None = None
    week_pnl_pct: float | None = None
    if isinstance(start_equity, (int, float)) and isinstance(end_equity, (int, float)):
        week_pnl_usd = end_equity - start_equity
        if start_equity:
            week_pnl_pct = week_pnl_usd / start_equity * 100

    day_number = None
    try:
        d0 = datetime.strptime(str(paper_start), "%Y-%m-%d").date()
        d1 = datetime.strptime(end, "%Y-%m-%d").date()
        delta = (d1 - d0).days
        day_number = delta + 1 if delta >= 0 else None
    except (TypeError, ValueError):
        day_number = None
    days_to_target = max(TRACK_TARGET_DAYS - day_number, 0) if day_number else None

    return {
        "window_start": start,
        "window_end": end,
        "range_label": _format_range(start, end),
        "week_number": _week_number(end, str(paper_start)),
        "generated_at": now_dt.isoformat(),
        "start_equity": start_equity,
        "end_equity": end_equity,
        "week_pnl_usd": week_pnl_usd,
        "week_pnl_pct": week_pnl_pct,
        "avg_apy_pct": _avg_apy(bars),
        "rebalances": _rebalances_in_window(trades_doc, start, end),
        "risk_blocks": _risk_blocks_in_window(blocks_doc, start, end),
        "top_strategies": _top_strategies(tournament_doc),
        "golive_passed": golive_doc.get("passed"),
        "golive_total": golive_doc.get("total", 26),
        "days_to_track_target": days_to_target,
    }


def _fmt_money(value: Any, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if signed:
        sign = "+" if value >= 0 else "−"
        return f"{sign}${abs(value):,.0f}"
    return f"${value:,.0f}"


def _fmt_pct(value: Any, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if signed:
        sign = "+" if value >= 0 else "−"
        return f"{sign}{abs(value):.2f}%"
    return f"{value:.2f}%"


def format_weekly_message(data: dict) -> str:
    """Render the HTML Telegram weekly message from :func:`build_weekly_data`."""
    lines: list[str] = []

    week = data.get("week_number")
    week_label = f"Week {week} " if isinstance(week, int) else ""
    lines.append(f"📋 <b>SPA Weekly Summary</b> — {week_label}({data.get('range_label', '')})")
    lines.append("")

    pnl_usd = data.get("week_pnl_usd")
    pnl_pct = data.get("week_pnl_pct")
    lines.append(
        f"📈 Week performance: {_fmt_pct(pnl_pct, signed=True)} ({_fmt_money(pnl_usd, signed=True)})"
    )
    lines.append(f"📊 APY this week: {_fmt_pct(data.get('avg_apy_pct'))} avg")
    lines.append(f"💼 Starting capital: {_fmt_money(data.get('start_equity'))}")
    lines.append(f"💼 Ending capital: {_fmt_money(data.get('end_equity'))}")
    lines.append("")

    top = data.get("top_strategies") or []
    if top:
        lines.append("🏆 <b>Strategy ranking (advisory):</b>")
        for i, s in enumerate(top, 1):
            sid = s.get("strategy_id", "?")
            name = STRATEGY_NAMES.get(sid, "")
            label = f"{sid} {name}".strip()
            lines.append(f"{i}. {label}: {_fmt_pct(s.get('net_apy'))} APY")
        lines.append("")

    lines.append(f"🔄 Rebalances: {data.get('rebalances', 0)} (threshold triggers)")
    lines.append(f"🛡️ Risk blocks: {data.get('risk_blocks', 0)}")

    passed = data.get("golive_passed")
    gtotal = data.get("golive_total")
    days_left = data.get("days_to_track_target")
    if isinstance(passed, int) and isinstance(gtotal, int):
        track_note = ""
        if isinstance(days_left, int):
            weeks_left = -(-days_left // 7)  # ceil
            if days_left == 0:
                track_note = " (30-day track complete ✅)"
            else:
                wk = "week" if weeks_left == 1 else "weeks"
                track_note = f" ({weeks_left} {wk} remaining for 30-day track)"
        lines.append(f"📋 GoLive progress: {passed}/{gtotal}{track_note}")
    lines.append("")

    if isinstance(days_left, int) and days_left > 0:
        goal = min(days_left, 7)
        lines.append(f"Next week goal: accumulate {goal} more track days")
    else:
        lines.append("Next week goal: maintain continuous track + READY streak")

    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────


def _send_html(message: str) -> bool:
    """Send via Keychain-backed telegram_client (HTML mode). Never raises."""
    try:
        from spa_core.alerts.telegram_client import _post_message as _tg_post
        return _tg_post({"text": message, "parse_mode": "HTML"})
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        log.warning("weekly_telegram_report: send failed: %s", exc)
        return False


def run_weekly_report(
    end_date: str | None = None,
    *,
    data_dir: str | Path | None = None,
    send: bool = True,
    now: datetime | None = None,
) -> dict:
    """Build and (optionally) send the weekly report.

    Returns ``{"sent": bool, "message": str, "data": dict, "error": str | None}``.
    Never raises.
    """
    result: dict[str, Any] = {"sent": False, "message": "", "data": {}, "error": None}
    try:
        data = build_weekly_data(end_date, data_dir=data_dir, now=now)
        message = format_weekly_message(data)
        result["data"] = data
        result["message"] = message
        if send:
            result["sent"] = _send_html(message)
            if not result["sent"]:
                result["error"] = "Telegram send returned False"
    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("run_weekly_report: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="weekly_telegram_report",
        description="Weekly SPA Telegram summary.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print preview, do not send")
    group.add_argument("--run", action="store_true", help="send to Telegram")
    parser.add_argument("--end", default=None, help="window end YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        data = build_weekly_data(args.end, data_dir=args.data_dir)
        message = format_weekly_message(data)
        print(re.sub(r"<[^>]+>", "", message))
        return 0

    result = run_weekly_report(args.end, data_dir=args.data_dir, send=True)
    if result["sent"]:
        print("✅ Weekly report sent")
    else:
        print(f"⚠️  Not sent: {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
