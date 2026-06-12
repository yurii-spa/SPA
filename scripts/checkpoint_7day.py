#!/usr/bin/env python3
"""
SPA 7-Day Checkpoint — MP-434
Автоматическая валидация после 7 дней paper trading (2026-06-19).

Checks:
  1. Gap check       — нет пропусков в ежедневных записях за последние 7 дней
  2. Sharpe check    — S7 >= 0.8, S5/S6 >= 0.9, promote >= 1.0
  3. Equity floor    — текущий equity >= $95,000, APY (7d) >= 5%
  4. Files existence — критические файлы data/*.json
  5. Summary output  — форматированный вывод в консоль
  6. Telegram alert  — при FAIL (или PASS) через Keychain-токен

Exit code: 0 = all pass, 1 = any fail
Stdlib only: json, subprocess, urllib.request, os, datetime, pathlib, sys
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────────

BASE = Path.home() / "Documents" / "SPA_Claude"
DATA = BASE / "data"

PAPER_START_DATE = date(2026, 6, 12)
CHECKPOINT_DAY   = 7
CHECKPOINT_DATE  = PAPER_START_DATE + timedelta(days=CHECKPOINT_DAY)  # 2026-06-19

EQUITY_FLOOR_USD  = 95_000.0
BASE_CAPITAL      = 100_000.0
APY_MIN_PCT       = 5.0

# Sharpe thresholds
SHARPE_S7_WARN    = 0.8   # S7 < this → warning
SHARPE_T2_MIN     = 0.9   # S5 / S6 should reach this
SHARPE_PROMOTE    = 1.0   # любая стратегия >= this → PROMOTE candidate

# Telegram Keychain key
TELEGRAM_KEY      = "TELEGRAM_BOT_TOKEN_SPA"

# Critical data files that must exist
CRITICAL_FILES = [
    DATA / "golive_status.json",
    DATA / "paper_evidence.json",
    DATA / "tournament_ranking.json",
    DATA / "adapter_status.json",
]

# ─── Keychain ────────────────────────────────────────────────────────────────

def get_keychain(service: str) -> str | None:
    """Читает секрет из macOS Keychain. Возвращает None при ошибке."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Отправляет сообщение в Telegram. Возвращает True при успехе."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_telegram_chat_id(token: str) -> str | None:
    """Получает chat_id из первого входящего обновления."""
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=1"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        updates = data.get("result", [])
        if updates:
            msg = updates[-1]
            if "message" in msg:
                return str(msg["message"]["chat"]["id"])
            elif "channel_post" in msg:
                return str(msg["channel_post"]["chat"]["id"])
    except Exception:
        pass
    return None


def notify_telegram(msg: str) -> bool:
    """Отправляет уведомление через Telegram, токен из Keychain."""
    token = get_keychain(TELEGRAM_KEY)
    if not token:
        return False
    chat_id = get_telegram_chat_id(token)
    if not chat_id:
        return False
    return send_telegram(token, chat_id, msg)


# ─── Data loaders ────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list | None:
    """Безопасно читает JSON-файл. None если файл отсутствует или повреждён."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─── Check 1: Gap check ──────────────────────────────────────────────────────

def check_gaps(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Читает gap_monitor.json и paper_evidence.json.
    Проверяет: нет пробелов за последние 7 дней.
    """
    result = {
        "name": "gap_check",
        "status": "pass",
        "days_tracked": 0,
        "gap_detected": False,
        "detail": "",
    }

    # Читаем gap_monitor.json
    gm = load_json(data_dir / "gap_monitor.json")
    if gm is not None:
        if gm.get("gap_detected", False):
            result["status"] = "fail"
            result["gap_detected"] = True
            result["detail"] = f"Gap detected: {gm.get('message', 'unknown')}"
        else:
            hours = gm.get("hours_since_last_entry", 999)
            if hours > 26:  # допуск 26 часов (дневной цикл + буфер)
                result["status"] = "fail"
                result["gap_detected"] = True
                result["detail"] = f"Last entry {hours:.1f}h ago (>26h threshold)"
            else:
                result["detail"] = f"OK — last entry {hours:.1f}h ago"
    else:
        result["detail"] = "gap_monitor.json not found — relying on paper_evidence"

    # Читаем paper_evidence.json для подсчёта дней
    pe = load_json(data_dir / "paper_evidence.json")
    if pe is not None:
        days = pe.get("days", [])
        result["days_tracked"] = len(days)

        if len(days) > 0:
            # Проверяем пробелы в датах paper_evidence
            try:
                sorted_days = sorted(days, key=lambda d: d.get("date", ""))
                dates = [date.fromisoformat(d["date"]) for d in sorted_days if "date" in d]
                for i in range(1, len(dates)):
                    delta = (dates[i] - dates[i - 1]).days
                    if delta > 1:
                        result["status"] = "fail"
                        result["gap_detected"] = True
                        result["detail"] = (
                            f"Gap in paper_evidence: {dates[i-1]} → {dates[i]} ({delta} days)"
                        )
                        break
            except Exception as exc:
                result["detail"] += f"; date parse error: {exc}"
    else:
        # Если paper_evidence отсутствует, проверяем equity_curve
        ec = load_json(data_dir / "equity_curve_daily.json")
        if ec is not None:
            daily = ec.get("daily", [])
            result["days_tracked"] = len(daily)

    return result


# ─── Check 2: Sharpe check ───────────────────────────────────────────────────

def check_sharpe(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Читает tournament_ranking.json.
    Проверяет Sharpe-пороги для S5/S6/S7 и PROMOTE кандидатов.
    """
    result = {
        "name": "sharpe_check",
        "status": "pass",
        "best_sharpe_id": None,
        "best_sharpe_val": None,
        "promote_candidates": [],
        "warnings": [],
        "detail": "",
    }

    tr = load_json(data_dir / "tournament_ranking.json")
    if tr is None:
        result["status"] = "warn"
        result["detail"] = "tournament_ranking.json not found"
        return result

    strategies = tr.get("strategies", [])
    if not strategies:
        result["status"] = "warn"
        result["detail"] = "No strategies in tournament_ranking.json"
        return result

    # Индексируем по ID
    by_id: dict[str, dict] = {s["id"]: s for s in strategies if "id" in s}

    best_sharpe = 0.0
    best_id = None

    for s in strategies:
        sid = s.get("id", "?")
        sharpe = s.get("sharpe", 0.0) or 0.0
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_id = sid
        if sharpe >= SHARPE_PROMOTE:
            result["promote_candidates"].append({"id": sid, "sharpe": sharpe})

    result["best_sharpe_id"] = best_id
    result["best_sharpe_val"] = best_sharpe

    # S7 check
    s7 = by_id.get("S7", {})
    s7_sharpe = s7.get("sharpe", 0.0) or 0.0
    if s7_sharpe < SHARPE_S7_WARN:
        result["warnings"].append(f"S7 Sharpe={s7_sharpe:.2f} < {SHARPE_S7_WARN} (warning)")

    # S5 / S6 check
    for sid in ("S5", "S6"):
        sx = by_id.get(sid, {})
        sx_sharpe = sx.get("sharpe", 0.0) or 0.0
        if sx_sharpe > 0 and sx_sharpe < SHARPE_T2_MIN:
            result["warnings"].append(
                f"{sid} Sharpe={sx_sharpe:.2f} < {SHARPE_T2_MIN} threshold"
            )

    # Форматируем detail
    promo_str = (
        ", ".join(f"{p['id']} (Sharpe {p['sharpe']:.2f})" for p in result["promote_candidates"])
        or "none"
    )
    warn_str = "; ".join(result["warnings"]) or "none"
    result["detail"] = (
        f"Best Sharpe: {best_id}={best_sharpe:.2f}; "
        f"PROMOTE candidates: {promo_str}; "
        f"Warnings: {warn_str}"
    )

    return result


# ─── Check 3: Equity floor ───────────────────────────────────────────────────

def check_equity(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Читает paper_trading_status.json или equity_curve_daily.json.
    Проверяет equity floor и 7d rolling APY.
    """
    result = {
        "name": "equity_floor",
        "status": "pass",
        "current_equity": None,
        "return_pct": None,
        "apy_7d_pct": None,
        "kill_switch_active": False,
        "detail": "",
    }

    # Приоритет: paper_trading_status.json
    pts = load_json(data_dir / "paper_trading_status.json")
    if pts is not None:
        equity = pts.get("current_equity") or pts.get("equity")
        result["current_equity"] = equity
        result["kill_switch_active"] = pts.get("kill_switch_active", False)
        apy_today = pts.get("apy_today_pct") or pts.get("apy_today")
        result["apy_7d_pct"] = apy_today  # Используем текущий APY как приближение
    else:
        # Fallback: equity_curve_daily.json
        ec = load_json(data_dir / "equity_curve_daily.json")
        if ec is not None:
            summary = ec.get("summary", {})
            equity = summary.get("end_equity")
            result["current_equity"] = equity
            result["apy_7d_pct"] = None  # нет в этом файле напрямую

    if result["current_equity"] is None:
        result["status"] = "fail"
        result["detail"] = "Cannot determine current equity (files missing)"
        return result

    equity = result["current_equity"]

    # Расчёт return %
    if equity and BASE_CAPITAL > 0:
        result["return_pct"] = (equity - BASE_CAPITAL) / BASE_CAPITAL * 100

    # Расчёт 7d rolling APY из equity_curve_daily.json
    ec = load_json(data_dir / "equity_curve_daily.json")
    if ec is not None:
        daily = ec.get("daily", [])
        if len(daily) >= 2:
            # Берём последние 7 (или сколько есть) записей
            window = daily[-7:] if len(daily) >= 7 else daily
            start_eq = window[0].get("open_equity") or window[0].get("equity") or BASE_CAPITAL
            end_eq   = window[-1].get("equity") or window[-1].get("close_equity") or equity
            n_days   = len(window)
            if start_eq > 0 and n_days > 0:
                period_return = (end_eq - start_eq) / start_eq
                apy = period_return / n_days * 365 * 100
                result["apy_7d_pct"] = round(apy, 2)

    # Equity floor check
    if equity < EQUITY_FLOOR_USD:
        result["status"] = "fail"
        result["detail"] = (
            f"Equity ${equity:,.0f} < floor ${EQUITY_FLOOR_USD:,.0f} — ALERT"
        )
    else:
        result["detail"] = f"Equity ${equity:,.2f} OK"

    # APY check
    apy = result["apy_7d_pct"]
    if apy is not None and apy < APY_MIN_PCT:
        if result["status"] == "pass":
            result["status"] = "warn"
        result["detail"] += f"; APY {apy:.1f}% < {APY_MIN_PCT}% threshold (warn)"
    elif apy is not None:
        result["detail"] += f"; APY {apy:.1f}%"

    # Kill switch
    if result["kill_switch_active"]:
        result["status"] = "fail"
        result["detail"] += " — KILL SWITCH ACTIVE"

    return result


# ─── Check 4: Files existence ────────────────────────────────────────────────

def check_files(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Проверяет существование критических data-файлов.
    """
    result = {
        "name": "files_existence",
        "status": "pass",
        "found": [],
        "missing": [],
        "detail": "",
    }
    expected = [
        data_dir / "golive_status.json",
        data_dir / "paper_evidence.json",
        data_dir / "tournament_ranking.json",
        data_dir / "adapter_status.json",
    ]
    for f in expected:
        if f.exists():
            result["found"].append(f.name)
        else:
            result["missing"].append(f.name)
            result["status"] = "fail"

    if result["missing"]:
        result["detail"] = f"Missing: {', '.join(result['missing'])}"
    else:
        result["detail"] = f"All {len(result['found'])} critical files present"

    return result


# ─── Summary formatter ───────────────────────────────────────────────────────

def format_summary(
    gaps: dict,
    sharpe: dict,
    equity: dict,
    files: dict,
    today: date | None = None,
) -> str:
    """Форматирует итоговый вывод в консоль."""
    if today is None:
        today = date.today()

    # Вычисляем days tracked
    days_tracked = gaps.get("days_tracked") or 0
    if days_tracked == 0 and equity.get("current_equity"):
        ec_data = load_json(DATA / "equity_curve_daily.json")
        if ec_data:
            days_tracked = len(ec_data.get("daily", []))

    gap_ok     = gaps["status"] == "pass"
    eq_val     = equity.get("current_equity") or 0
    apy_val    = equity.get("apy_7d_pct")
    ret_pct    = equity.get("return_pct") or 0
    kill_sw    = equity.get("kill_switch_active", False)

    best_id    = sharpe.get("best_sharpe_id", "?")
    best_sh    = sharpe.get("best_sharpe_val")
    promote    = sharpe.get("promote_candidates", [])

    golive_ok  = files["status"] == "pass"

    lines = [
        f"=== SPA 7-Day Checkpoint ({CHECKPOINT_DATE.isoformat()}) ===",
        f"Days tracked:   {days_tracked}/30",
        f"Gap-free:       {'✅ YES' if gap_ok else '❌ NO — ' + gaps.get('detail', '')}",
        f"Equity:         ${eq_val:,.2f} ({ret_pct:+.3f}%)",
        f"APY (7d):       {f'{apy_val:.1f}%' if apy_val is not None else 'N/A'}",
    ]

    if best_id and best_sh is not None:
        promo_label = " [PROMOTE candidate]" if best_sh >= SHARPE_PROMOTE else ""
        lines.append(f"Best Sharpe:    {best_id} = {best_sh:.2f}{promo_label}")

    if promote:
        cands = ", ".join(f"{p['id']} (Sharpe {p['sharpe']:.2f})" for p in promote)
        lines.append(f"PROMOTE ready:  {cands} ← auto-promote candidate")
    else:
        lines.append("PROMOTE ready:  — (no strategy >= 1.0 yet)")

    lines.append(f"Kill-switch:    {'❌ ACTIVE' if kill_sw else '✅ NOT triggered'}")
    lines.append(f"GoLive status:  {'✅ PASS' if golive_ok else '❌ FAIL — missing files'}")

    # Предупреждения Sharpe
    for w in sharpe.get("warnings", []):
        lines.append(f"⚠️  {w}")

    return "\n".join(lines)


# ─── Overall status ──────────────────────────────────────────────────────────

def overall_pass(checks: list[dict]) -> tuple[bool, list[str]]:
    """Возвращает (all_pass, [список failов])."""
    failures = []
    for c in checks:
        if c["status"] == "fail":
            failures.append(f"{c['name']}: {c.get('detail', 'failed')}")
    return len(failures) == 0, failures


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_checkpoint(data_dir: Path = DATA) -> int:
    """
    Запускает все проверки, выводит summary, шлёт Telegram.
    Возвращает exit code (0 = pass, 1 = fail).
    """
    today = date.today()

    # Выполняем все 4 проверки
    gaps   = check_gaps(data_dir)
    sharpe = check_sharpe(data_dir)
    equity = check_equity(data_dir)
    files  = check_files(data_dir)

    checks = [gaps, sharpe, equity, files]
    passed, failures = overall_pass(checks)

    # Summary в консоль
    summary = format_summary(gaps, sharpe, equity, files, today)
    print(summary)

    if not passed:
        print("\n--- FAILURES ---")
        for f in failures:
            print(f"  ❌ {f}")

    # Telegram
    if passed:
        tg_msg = (
            f"✅ SPA 7-Day Checkpoint PASSED — Day {CHECKPOINT_DAY}/30\n"
            f"{summary}"
        )
    else:
        fail_str = "\n".join(f"  • {f}" for f in failures)
        tg_msg = (
            f"⚠️ SPA 7-Day Checkpoint FAILED: {len(failures)} check(s)\n"
            f"{fail_str}\n\n{summary}"
        )

    ok = notify_telegram(tg_msg)
    if not ok:
        print("\n[Telegram] Could not send notification (token/chat_id unavailable).")

    return 0 if passed else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SPA 7-Day Checkpoint MP-434")
    parser.add_argument(
        "--data-dir", type=Path, default=DATA,
        help=f"Path to data directory (default: {DATA})"
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Skip Telegram notification"
    )
    args = parser.parse_args()

    # Переопределяем notify если --no-telegram
    if args.no_telegram:
        def notify_telegram(msg: str) -> bool:   # noqa: F811
            return True

    sys.exit(run_checkpoint(data_dir=args.data_dir))
