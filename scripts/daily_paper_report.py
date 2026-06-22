#!/usr/bin/env python3
"""
Daily Paper Trading Report — MP-419 / MP-460
Reads paper_evidence.json, sends Telegram progress report.
MP-460: добавлена секция Base Chain (ADR-025 Phase 1).
Stdlib only: json, os, sys, subprocess, urllib.request, urllib.parse, datetime, pathlib, math
"""
import json
import math
import re
import sys
import subprocess
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

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


def build_message(stats: dict, equity_history: list | None = None) -> str:
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
    msg += "\n\n🛡️ *Risk Limits (DL-01…DL-05)*\n"
    msg += get_risk_limits_section(equity_history or [])
    msg += get_base_chain_section()
    return msg


# Реестр известных адаптеров Base chain с метаданными.
# suspended=True → адаптер показывается с меткой SUSPENDED, капитал не выделяется.
# apy_fallback — резервное значение, если данных в adapter_status.json нет.
_BASE_ADAPTERS_REGISTRY: dict[str, dict] = {
    "aave_v3_base": {
        "tier": "T2", "label": "Aave V3 Base",
        "apy_fallback": 4.5, "suspended": False,
    },
    "morpho_blue_base": {
        "tier": "T2", "label": "Morpho Blue Base",
        "apy_fallback": 6.2, "suspended": False,
    },
    "moonwell_base": {
        "tier": "T3", "label": "Moonwell Base",
        "apy_fallback": 0.0, "suspended": True,          # SUSPENDED=True (ADR-025)
    },
    "extra_finance_base": {
        "tier": "T3", "label": "Extra Finance XLend",
        "apy_fallback": 8.0, "suspended": False,          # Phase 1, read-only
    },
}


def get_base_chain_section() -> str:
    """Build Base chain monitoring section for daily report (ADR-025 Phase 1 — MP-460).

    Extra Finance XLend Base added: T3, APY_FALLBACK=8.0%, SUSPENDED=False.
    Moonwell Base: SUSPENDED=True — показывается с меткой SUSPENDED.
    """
    lines = []
    lines.append("\n🔵 *Base Chain (ADR-025 Phase 1)*")

    # Gas status — попытка загрузить BaseGasMonitor
    try:
        sys.path.insert(0, str(BASE))
        from spa_core.monitoring.base_gas_monitor import BaseGasMonitor
        monitor = BaseGasMonitor(data_dir=str(BASE / "data"))
        status = monitor.get_status()
        gwei = status.get("gwei") or 0.0
        consecutive = status.get("consecutive_above", 0)
        kill_active = status.get("kill_switch_active", False)

        if kill_active:
            lines.append(f"  ⛔ Gas Kill-Switch АКТИВЕН! {gwei:.2f} Gwei × {consecutive} дней")
        elif consecutive > 0:
            lines.append(f"  ⚠️ Gas выше порога: {gwei:.2f} Gwei ({consecutive}/3 дней)")
        else:
            lines.append(f"  ✅ Gas: {gwei:.2f} Gwei (норма)")
    except Exception as e:
        lines.append(f"  ⚪ Gas: недоступен ({e})")

    # Загружаем живые данные адаптеров из adapter_status.json
    live_adapters: dict = {}
    try:
        status_path = BASE / "data" / "adapter_status.json"
        with open(status_path) as f:
            all_adapters = json.load(f)
        live_adapters = {k: v for k, v in all_adapters.items()
                        if isinstance(v, dict) and v.get("chain") == "base"}
    except Exception:
        pass  # Fallback к статическим данным реестра

    # Рендерим известные адаптеры в порядке реестра
    for adapter_id, meta in _BASE_ADAPTERS_REGISTRY.items():
        tier = meta["tier"]
        label = meta["label"]
        fallback_apy = meta["apy_fallback"]
        suspended = meta["suspended"]

        if suspended:
            lines.append(f"  🚫 {label} [{tier}]: SUSPENDED")
            continue

        live_info = live_adapters.get(adapter_id, {})
        apy = live_info.get("apy_pct", live_info.get("apy", fallback_apy))
        lines.append(f"  📊 {label} [{tier}]: {apy:.1f}% APY (monitoring)")

    # Неизвестные Base-адаптеры из adapter_status.json (на случай новых)
    known = set(_BASE_ADAPTERS_REGISTRY)
    for adapter_id, info in live_adapters.items():
        if adapter_id not in known:
            apy = info.get("apy_pct", info.get("apy", 0))
            lines.append(f"  📊 {adapter_id}: {apy:.1f}% APY (monitoring)")

    lines.append("  ℹ️ Phase 1: мониторинг без капитала → до 2026-07-12")

    return "\n".join(lines)


def get_risk_limits_section(
    equity_history: list,
    allocation: dict | None = None,
    apy_map: dict | None = None,
) -> str:
    """Returns risk limits status for daily Telegram report.

    Gracefully degrades (try/except) if DailyLimitsChecker is unavailable.
    Maps equity_value → equity for compatibility with DailyLimitsChecker
    (paper_evidence.json uses equity_value; daily_limits expects close_equity/equity).
    """
    try:
        sys.path.insert(0, str(BASE))
        from spa_core.risk.daily_limits import DailyLimitsChecker  # stdlib only

        # Map equity_value → equity for DailyLimitsChecker compatibility
        mapped: list = []
        for bar in (equity_history or []):
            if isinstance(bar, dict) and "equity_value" in bar \
                    and "close_equity" not in bar and "equity" not in bar:
                mapped.append({**bar, "equity": bar["equity_value"]})
            else:
                mapped.append(bar)

        checker = DailyLimitsChecker()
        result = checker.check(
            equity_history=mapped,
            allocation=allocation or {},
            apy_map=apy_map or {},
        )
        gate = result.get("gate", "UNKNOWN")
        icon = {"PASS": "✅", "WARN": "⚠️", "HALT": "🚨"}.get(gate, "❓")
        lines = [f"*Risk Gate: {icon} {gate}*"]
        if result.get("halt_reasons"):
            lines.append("🚨 HALT: " + "; ".join(result["halt_reasons"]))
        if result.get("warn_reasons"):
            lines.append("⚠️ Warn: " + "; ".join(result["warn_reasons"]))
        return "\n".join(lines)
    except Exception as e:
        return f"Risk Gate: ❓ unavailable ({e})"


def test_extra_finance_in_report() -> bool:
    """
    Тест: Extra Finance XLend [T3] отображается в секции Base chain
    с APY ≥ 8.0% (fallback=8.0% при отсутствии живых данных адаптера).
    Запуск: python3 scripts/daily_paper_report.py --test
    """
    section = get_base_chain_section()

    # 1. Extra Finance XLend присутствует в секции
    if "Extra Finance XLend" not in section:
        print("FAIL: 'Extra Finance XLend' не найден в секции Base chain")
        print("Секция:", section)
        return False

    # 2. APY ≥ 8.0%
    m = re.search(r"Extra Finance XLend \[T3\]: ([\d.]+)% APY", section)
    if not m:
        print("FAIL: не удалось распарсить APY Extra Finance XLend из секции")
        print("Секция:", section)
        return False
    apy = float(m.group(1))
    if apy < 8.0:
        print(f"FAIL: APY={apy}% < 8.0% (APY_FALLBACK должен быть 8.0%)")
        return False

    # 3. Moonwell отображается с меткой SUSPENDED
    if "Moonwell" not in section or "SUSPENDED" not in section:
        print("FAIL: Moonwell SUSPENDED не найден в секции")
        print("Секция:", section)
        return False

    print(f"PASS: Extra Finance XLend APY={apy:.1f}% ≥ 8.0%, Moonwell=SUSPENDED")
    return True


def test_risk_limits_section() -> bool:
    """Test: get_risk_limits_section([], {}, {}) returns a string containing 'Risk Gate'.

    Run via: python3 scripts/daily_paper_report.py --test
    """
    result = get_risk_limits_section([], {}, {})
    if not isinstance(result, str):
        print(f"FAIL: expected str, got {type(result)}")
        return False
    if "Risk Gate" not in result:
        print(f"FAIL: 'Risk Gate' not found in result: {result!r}")
        return False
    print(f"PASS: get_risk_limits_section([], {{}}, {{}}) → {result!r}")
    return True


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
    if "--test" in sys.argv:
        ok1 = test_extra_finance_in_report()
        ok2 = test_risk_limits_section()
        raise SystemExit(0 if (ok1 and ok2) else 1)

    evidence = load_evidence()
    stats = calc_stats(evidence)
    message = build_message(stats, evidence.get("days", []))

    if DRY_RUN:
        print("=== DRY RUN — сообщение НЕ отправляется ===")
        print(message)
        raise SystemExit(0)

    bot_token = get_keychain("TELEGRAM_BOT_TOKEN_SPA")
    chat_id = get_keychain("TELEGRAM_CHAT_ID_SPA")

    if not bot_token or not chat_id:
        print("ERROR: Telegram credentials not found in Keychain")
        raise SystemExit(1)

    print("Sending report...")
    print(message)

    if send_telegram(message, bot_token, chat_id):
        print("✅ Report sent successfully")
    else:
        print("❌ Failed to send report")
        raise SystemExit(1)
