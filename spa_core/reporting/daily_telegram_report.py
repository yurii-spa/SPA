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
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    adapter_meta = _adapter_meta(adapter_doc)
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
        lines.append(f"🏆 Best strategy today: {sid} ({_fmt_pct(napy)} APY)")
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
        apy_p = m.get("apy")
        apy_str = f" — {apy_p:.1f}% APY" if isinstance(apy_p, (int, float)) else ""
        lines.append(f"  • {name}: ${val:,.0f} ({pct:.1f}%){apy_str}")
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
        lines.append(f"🔒 Risk gate: {blocks} block event(s) today — see risk_policy_blocks.json")
    elif approved is True:
        lines.append("🔒 Risk gate: all positions within limits")

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
