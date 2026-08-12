#!/usr/bin/env python3
"""
scripts/run_health_check.py
============================
Daily health check runner for the SPA paper trading cycle.

Runs CycleHealthMonitor, saves report to data/cycle_health.json,
and optionally sends a Telegram alert when overall != HEALTHY.

Usage:
    python3 scripts/run_health_check.py           # full run + save + Telegram
    python3 scripts/run_health_check.py --test    # dry-run: no save, no Telegram
    python3 scripts/run_health_check.py --json    # print JSON report to stdout

Exit codes:
    0 — HEALTHY
    1 — WARNING or CRITICAL (or import failure)

Rules:
    - STDLIB ONLY — no external dependencies
    - SECRETS POLICY — no tokens written to this file or any artifact
    - LLM FORBIDDEN
    - Graceful ImportError → prints clear message, exits 1 (no traceback)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Доставка тревоги — ТОЛЬКО через единственную инстанцию (push_policy)
# ---------------------------------------------------------------------------
#
# ── ЗАМЕР 2026-08-12 (цикл #205): третий экземпляр одного класса ────────────
#
# Здесь стоял `TelegramManager(category="p0")`. Менеджер отставлен в ходе
# Phase-1 Telegram rebuild: его `_send_raw` ВСЕГДА возвращает False и уводит
# текст в суточный дайджест. То есть CRITICAL-вердикт о здоровье системы
# push'ем не уходил — ровно как у стоп-крана (10.08) и у внутридневной
# проверки.
#
# Хуже самой потери был ДИАГНОЗ. Ниже стоял запасной путь `except: ok =
# _send_telegram(...)`, но `mgr.send()` не БРОСАЕТ — он возвращает False.
# Значит `except` не срабатывал НИКОГДА, запасной путь был мёртв вместе с
# основным, а оператору печаталось «suppressed (cooldown active)»: никакого
# остывания не было, канал был отставлен насовсем. Благополучное,
# самоустраняющееся объяснение вечной тишины — та же ложь, что «отправлен
# владельцу» в логе цикла, только в другом костюме.
#
# ЧЕСТНАЯ ГРАНИЦА НАХОДКИ (измерено, а не предположено). Живой тревоги этот
# дефект НЕ съел: у `scripts/run_health_check.py` единственный вызывающий —
# скрипт `run_daily_simulation`, который сам лежит в базе неподключённых
# (`agent-unwired-baseline-triage`), и ни один plist/шелл/CI его не зовёт.
# Живой 300-секундный `cycle_health_monitor` уходит в CRITICAL ровно по
# `cycle_gap`, а его закрывает живой `com.spa.cycle_gap_monitor` ключом
# `cycle_gap`. То есть чинится ЛОВУШКА (сработает, когда корень подключат),
# а не восстанавливается потерянная тревога. Заявлять второе было бы враньём.
#
# ПОЧЕМУ ИМЯ ВЫШЕ БЕЗ РАСШИРЕНИЯ — и это не косметика. Храповик неподключённых
# скриптов (`spa_core/tests/_unwired.py`) ищет имя файла ПОДСТРОКОЙ по коду, не
# отличая вызов от УПОМИНАНИЯ В КОММЕНТАРИИ. Первая редакция этого разбора
# написала имя целиком — и храповик счёл скрипт подключённым, то есть мой
# комментарий молча снял бы его с учёта. Написать имя без `.py` — осознанный
# выбор: запись доказательства сохранена (полная, с путями, — в карточке и в
# журнале W33), а с учёта никто не снят. Сам дефект храповика измерен и заведён
# карточкой (`inbox-hrapovik-schitaet-upominanie-v-kommenta`): слепота стоит
# ЕЩЁ двух скриптов, `daily_paper_report` и `guardian_backtest`, — их сегодня
# держит «подключёнными» ровно комментарий. Чинить его здесь нельзя: починка
# добавляет три скрипта к неподключённым, а гасить это дописыванием в базу
# храповик запрещает своим же правилом.
#
# Заодно убран сырой отправитель `_send_telegram`/`_keychain_get`: после
# перевода на `push_policy` его никто не звал, а обход единственной инстанции
# push'а — это ровно тот путь, которым дефект возвращается.

# Ключ закрытого Tier-1 whitelist (docs/TELEGRAM_BOT_ARCHITECTURE.md §2).
HEALTH_EVENT_KEY = "system_critical"


def _critical_checks(report: dict) -> list[str]:
    """Имена проверок с вердиктом CRITICAL — отпечаток КОНКРЕТНОЙ аварии.

    Он же `dedup_key`: пока авария та же, владельцу говорят один раз; ДРУГОЙ
    набор упавших проверок — другое происшествие, и оно обязано прозвучать.
    """
    checks = report.get("checks") or {}
    if not isinstance(checks, dict):
        return []
    return sorted(
        name
        for name, res in checks.items()
        if isinstance(res, dict) and res.get("status") == "CRITICAL"
    )


def _incident_fingerprint(report: dict) -> str:
    """Отпечаток происшествия. Без имён проверок — по первой рекомендации.

    Аварийный отчёт (`run_all_checks` бросил) не содержит ни одной проверки;
    схлопнуть все такие падения в один отпечаток значило бы промолчать о
    втором, ДРУГОМ падении.
    """
    names = _critical_checks(report)
    if names:
        return "health:" + ",".join(names)
    recs = report.get("recommendations") or []
    if recs:
        return "health:" + str(recs[0])[:120]
    return "health:critical-unnamed"


def dispatch_health_alert(
    report: dict,
    *,
    data_dir: str | Path | None = None,
    send: bool = True,
) -> tuple[bool, str]:
    """Доставить вердикт здоровья. Возврат: `(ушло?, ИЗМЕРЕННАЯ причина)`.

    - `CRITICAL` → Tier-1 push через `push_policy` (ключ `system_critical`);
    - всё прочее не-`HEALTHY` → суточный дайджест: это и есть замысел отставки,
      WARNING не будит владельца;
    - `HEALTHY` → молчание.

    `data_dir` инъектируется: состояние push'а обязано следовать за каталогом
    проверки, иначе прогон над песочницей пишет в ЖИВОЕ edge-состояние и глушит
    следующую НАСТОЯЩУЮ тревогу (замер #193).

    Причина возвращается измеренная. Утверждать «cooldown», не измерив
    остывания, запрещено: неверный диагноз хуже молчания — он объясняет тишину
    и тем закрывает вопрос.
    """
    overall = str(report.get("overall", "UNKNOWN"))
    text = _build_alert_text(report)

    if overall == "HEALTHY":
        return False, "здоров — сообщать не о чем"

    try:
        from spa_core.telegram import push_policy

        if overall != "CRITICAL":
            push_policy.enqueue_digest(
                HEALTH_EVENT_KEY,
                f"SPA Health — {overall}",
                text,
                severity=overall,
                reason="не Tier-1: здоровье ниже CRITICAL не будит владельца",
                data_dir=data_dir,
            )
            return False, (
                f"{overall} — не Tier-1: уведено в суточный дайджест (замысел отставки)"
            )

        sent = bool(
            push_policy.push_critical(
                HEALTH_EVENT_KEY,
                "CRITICAL",
                "SPA System Health — CRITICAL",
                text,
                data_dir=data_dir,
                dedup_key=_incident_fingerprint(report),
                send=send,
            )
        )
    except Exception as exc:  # noqa: BLE001 — тревога не смеет уронить проверку
        return False, f"канал отказал: {exc}"

    if sent:
        return True, "Tier-1 push отправлен владельцу"
    return False, (
        "Tier-1 push НЕ ушёл сейчас — гейт политики (тот же отпечаток уже "
        "звучал / суточный потолок / отказ канала); причина в "
        "data/telegram/push_state.json"
    )


def _build_alert_text(report: dict) -> str:
    """Build a concise Telegram alert from a health report."""
    overall = report.get("overall", "UNKNOWN")
    checked_at = report.get("checked_at", "")
    emoji_map = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}
    emoji = emoji_map.get(overall, "❓")

    lines = [
        f"{emoji} *SPA Health: {overall}*",
        f"_{checked_at}_",
        "",
    ]

    status_emoji = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "STALE": "⚠️"}
    for check_name, check_result in report.get("checks", {}).items():
        status = check_result.get("status", "?")
        s_e = status_emoji.get(status, "❓")
        detail = check_result.get("detail", "")
        detail_str = f" — {detail}" if detail else ""
        lines.append(f"{s_e} `{check_name}`: {status}{detail_str}")

    recs = report.get("recommendations", [])
    if recs:
        lines.append("")
        lines.append("*Recommendations:*")
        for rec in recs[:5]:  # cap at 5 to stay under Telegram 4096 char limit
            lines.append(f"• {rec}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_equity_history(data_dir: str = "data") -> list:
    """
    Load equity_history.json.
    Returns [] if file is missing or malformed (CycleHealthMonitor handles this).
    """
    path = ROOT / data_dir / "equity_history.json"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def run_health_check(data_dir: str = "data", send_telegram: bool = True) -> dict:
    """
    1. Import CycleHealthMonitor (with graceful ImportError handling).
    2. Run all checks via monitor.run_all_checks().
    3. Save report to data/cycle_health.json (atomic write).
    4. If overall != HEALTHY and send_telegram → send Telegram alert.
    5. Return the report dict.
    """
    # --- Import CycleHealthMonitor -------------------------------------------
    try:
        from spa_core.monitoring.cycle_health_monitor import CycleHealthMonitor
    except ImportError as exc:
        print(
            f"\n[run_health_check] ERROR: Cannot import CycleHealthMonitor.\n"
            f"  Cause: {exc}\n"
            f"  Make sure spa_core/monitoring/cycle_health_monitor.py exists\n"
            f"  and the project root is correct: {ROOT}\n",
            file=sys.stderr,
        )
        sys.exit(1)

    data_dir_abs = str(ROOT / data_dir)

    # --- Run checks ----------------------------------------------------------
    monitor = CycleHealthMonitor()
    try:
        report = monitor.run_all_checks(data_dir=data_dir_abs)
    except Exception as exc:  # pragma: no cover — fail-safe
        print(
            f"[run_health_check] Unexpected error in run_all_checks: {exc}",
            file=sys.stderr,
        )
        # Return a minimal CRITICAL report so callers can handle it
        report = {
            "overall": "CRITICAL",
            "checks": {},
            "checked_at": datetime.now(tz=timezone.utc).isoformat(),
            "recommendations": [f"run_all_checks raised: {exc}"],
        }

    # --- Save report ---------------------------------------------------------
    try:
        monitor.save_health_report(report, data_dir=data_dir_abs)
    except OSError as exc:
        print(
            f"[run_health_check] WARNING: Could not save cycle_health.json: {exc}",
            file=sys.stderr,
        )

    # --- Telegram alert ------------------------------------------------------
    # Единственная инстанция push'а — `push_policy` (разбор в шапке файла).
    # Печатаем ИЗМЕРЕННУЮ причину: и «ушло», и «не ушло, потому что …».
    overall = report.get("overall", "UNKNOWN")
    if overall != "HEALTHY" and send_telegram:
        ok, why = dispatch_health_alert(report, data_dir=data_dir_abs)
        mark = "sent" if ok else "NOT sent"
        print(f"  [Telegram] health alert {mark}: {why}", file=sys.stderr)

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="SPA daily cycle health check runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit code 0 = HEALTHY, 1 = WARNING/CRITICAL.\n"
            "CRITICAL is delivered through push_policy (Tier-1 key "
            "'system_critical'); anything lower goes to the daily digest."
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Dry-run: no save to disk, no Telegram alert.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print full JSON report to stdout (suppresses human-readable output).",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="DIR",
        help="Path to data directory relative to project root (default: data).",
    )
    args = parser.parse_args()

    # In --test mode we still compute the report but skip save & Telegram
    if args.test:
        # Override save: monkey-patch to no-op for dry-run
        try:
            from spa_core.monitoring.cycle_health_monitor import CycleHealthMonitor
        except ImportError as exc:
            print(
                f"\n[run_health_check] ERROR: Cannot import CycleHealthMonitor.\n"
                f"  Cause: {exc}\n"
                f"  Ensure spa_core/monitoring/cycle_health_monitor.py exists.\n",
                file=sys.stderr,
            )
            return 1

        data_dir_abs = str(ROOT / args.data_dir)
        monitor = CycleHealthMonitor()
        try:
            report = monitor.run_all_checks(data_dir=data_dir_abs)
        except Exception as exc:  # pragma: no cover
            print(f"[run_health_check] run_all_checks error: {exc}", file=sys.stderr)
            report = {
                "overall": "CRITICAL",
                "checks": {},
                "checked_at": datetime.now(tz=timezone.utc).isoformat(),
                "recommendations": [f"run_all_checks raised: {exc}"],
            }
        # No save, no Telegram

    else:
        report = run_health_check(
            data_dir=args.data_dir,
            send_telegram=True,
        )

    # ---- Output -------------------------------------------------------------
    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        overall = report.get("overall", "UNKNOWN")
        emoji_map = {"HEALTHY": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}
        emoji = emoji_map.get(overall, "❓")
        checked_at = report.get("checked_at", "")
        print(f"\n{emoji} Health: {overall}  [{checked_at}]")

        status_emoji = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "STALE": "⚠️"}
        for check_name, check_result in report.get("checks", {}).items():
            status = check_result.get("status", "?")
            s_e = status_emoji.get(status, "❓")
            detail = check_result.get("detail", "")
            detail_str = f" — {detail}" if detail else ""
            # Extra context for cycle_gap
            hours = check_result.get("hours_since")
            hours_str = f" (age={hours:.2f}h)" if hours is not None else ""
            print(f"  {s_e} {check_name}: {status}{hours_str}{detail_str}")

        recs = report.get("recommendations", [])
        if recs:
            print("\nRecommendations:")
            for rec in recs:
                print(f"  • {rec}")

        if args.test:
            print("\n  [--test] Dry-run: report not saved, Telegram not sent.")
        else:
            data_out = ROOT / args.data_dir / "cycle_health.json"
            print(f"\n  → Saved: {data_out}")

        print()

    return 0 if report.get("overall") == "HEALTHY" else 1


if __name__ == "__main__":
    sys.exit(main())
