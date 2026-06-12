#!/usr/bin/env python3
"""
Daily Paper Trading Report — MP-419
Reads paper_evidence.json, sends Telegram progress report.
Stdlib only: json, subprocess, urllib.request, urllib.parse, datetime, pathlib, math
"""
import json
import math
import subprocess
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

BASE = Path.home() / "Documents" / "SPA_Claude"
EVIDENCE_FILE = BASE / "data" / "paper_evidence.json"
PAPER_START = date(2026, 6, 12)
MIN_DAYS = 30
GOLIVE_DATE = date(2026, 8, 1)


def get_keychain(key: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", key, "-w"],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def load_evidence() -> dict:
    if not EVIDENCE_FILE.exists():
        return {"days": [], "schema_version": "1.0"}
    with open(EVIDENCE_FILE) as f:
        return json.load(f)


def calc_stats(data: dict) -> dict:
    days = data.get("days", [])
    if not days:
        return {
            "n_days": 0,
            "avg_apy": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "total_return": 0.0,
            "current_equity": 100_000.0,
        }

    n = len(days)
    apys = [d["apy_pct"] for d in days]
    avg_apy = sum(apys) / n

    equities = [d["equity_value"] for d in days]
    current = equities[-1]
    peak = max(equities)
    max_dd = (current - peak) / peak * 100 if peak > 0 else 0.0
    total_return = (current - 100_000) / 100_000 * 100

    # Simple Sharpe approximation (annualised from daily returns)
    if n >= 2:
        daily_returns = [
            (equities[i] - equities[i - 1]) / equities[i - 1]
            for i in range(1, n)
        ]
        mean_r = sum(daily_returns) / len(daily_returns)
        var_r = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.001
        sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "n_days": n,
        "avg_apy": round(avg_apy, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "total_return": round(total_return, 2),
        "current_equity": round(current, 2),
    }


def build_message(stats: dict) -> str:
    today = date.today()
    elapsed = (today - PAPER_START).days
    days_left_evidence = max(0, MIN_DAYS - stats["n_days"])
    days_to_golive = (GOLIVE_DATE - today).days

    # Progress bar (10 chars wide)
    progress_pct = min(100, int(stats["n_days"] / MIN_DAYS * 100))
    filled = progress_pct // 10
    bar = "█" * filled + "░" * (10 - filled)

    # Status emoji
    apy_ok = stats["avg_apy"] >= 7.0
    days_ok = stats["n_days"] >= MIN_DAYS
    if days_ok and apy_ok:
        status_emoji = "✅"
        status_text = "GO-LIVE READY"
    elif days_ok:
        status_emoji = "⚠️"
        status_text = "DAYS OK, CHECK APY"
    elif apy_ok:
        status_emoji = "📈"
        status_text = "APY OK, ACCUMULATING"
    else:
        status_emoji = "🔄"
        status_text = "ACCUMULATING"

    apy_flag = "✅" if apy_ok else "❌"
    dd_flag = "✅" if stats["max_drawdown"] > -5.0 else "❌"
    days_flag = "✅" if days_ok else "🔄"

    msg = (
        f"📊 *Daily Paper Trading Report*\n"
        f"Date: {today.strftime('%Y-%m-%d')} | Day {elapsed}\n"
        f"\n"
        f"{status_emoji} Status: {status_text}\n"
        f"\n"
        f"📅 *Evidence Progress*\n"
        f"`[{bar}]` {stats['n_days']}/{MIN_DAYS} days ({progress_pct}%)\n"
        f"Days until window complete: {days_left_evidence}\n"
        f"Days to go-live: {days_to_golive}\n"
        f"\n"
        f"💰 *Performance*\n"
        f"Equity: ${stats['current_equity']:,.0f}\n"
        f"Avg APY: {stats['avg_apy']}%\n"
        f"Total Return: {stats['total_return']:+.2f}%\n"
        f"Max Drawdown: {stats['max_drawdown']:.2f}%\n"
        f"Sharpe: {stats['sharpe']:.2f}\n"
        f"\n"
        f"🎯 *Targets*\n"
        f"APY: {stats['avg_apy']}% / 7.0% min {apy_flag}\n"
        f"Drawdown: {stats['max_drawdown']:.1f}% / -5% max {dd_flag}\n"
        f"Days: {stats['n_days']} / {MIN_DAYS} min {days_flag}\n"
        f"\n"
        f"📆 Eligible for go-live: 2026-07-12\n"
        f"🚀 Go-live target: 2026-08-01"
    )
    return msg


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
    ).encode()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    return result.get("ok", False)


if __name__ == "__main__":
    bot_token = get_keychain("TELEGRAM_BOT_TOKEN_SPA")
    chat_id = get_keychain("TELEGRAM_CHAT_ID_SPA")

    if not bot_token or not chat_id:
        print("ERROR: Telegram credentials not found in Keychain")
        raise SystemExit(1)

    evidence = load_evidence()
    stats = calc_stats(evidence)
    message = build_message(stats)

    print("Sending report...")
    print(message)

    if send_telegram(message, bot_token, chat_id):
        print("✅ Report sent successfully")
    else:
        print("❌ Failed to send report")
        raise SystemExit(1)
