"""MP-350: Telegram daily report — активирован, без dry_run.

Оборачивает ``DailyReportBuilder`` (spa_core.alerts.daily_report) и отправляет
через ``telegram_client`` (читает токен/chat_id из macOS Keychain, никогда не
хардкодит секреты).

Rate-limiting: не более одного отчёта в сутки (UTC). Sentinel-файл
``data/.last_daily_report_sent`` хранит ISO-дату последней отправки. Для
форс-отправки используй ``force_send=True`` / CLI ``--test-send``.

Stdlib only. Fail-safe: любая ошибка → WARNING, никогда не бросает
исключение наружу. Атомарных записей нет (sentinel — один-единственный файл
с датой, «портить» нечего).

Публичный API
-------------
    run_daily_report(data_dir, dry_run=False, force_send=False) -> dict

CLI
---
    python3 -m spa_core.paper_trading.daily_report              # обычная rate-limited отправка
    python3 -m spa_core.paper_trading.daily_report --test-send  # форс-отправить прямо сейчас
    python3 -m spa_core.paper_trading.daily_report --dry-run    # собрать отчёт, не отправлять

Интеграция в цикл
-----------------
Вызывается из ``cycle_runner.run_cycle()`` после ``run_reporting_cycle``
(блок MP-350). Fail-safe: исключение → WARNING, цикл продолжается.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.paper_trading.daily_report")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SENTINEL_FILENAME = ".last_daily_report_sent"


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _should_send(data_dir: Path, force_send: bool) -> bool:
    """True если отчёт ещё не отправлялся сегодня (UTC) или force_send=True."""
    if force_send:
        return True
    sentinel = data_dir / SENTINEL_FILENAME
    today = date.today().isoformat()
    try:
        if sentinel.exists():
            stored = sentinel.read_text(encoding="utf-8").strip()
            return stored != today
    except Exception as exc:
        log.warning("sentinel read failed (%s) — assuming should send", exc)
    return True


def _mark_sent(data_dir: Path) -> None:
    """Записывает сегодняшнюю ISO-дату в sentinel-файл."""
    sentinel = data_dir / SENTINEL_FILENAME
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(date.today().isoformat(), encoding="utf-8")
    except Exception as exc:
        log.warning("sentinel write failed (%s)", exc)


def _build_message(data_dir: Path) -> str:
    """Строит Telegram HTML-сообщение через DailyReportBuilder. Fail-safe."""
    try:
        from spa_core.alerts.daily_report import DailyReportBuilder  # noqa: PLC0415
        return DailyReportBuilder(data_dir).build_report()
    except Exception as exc:
        log.warning("DailyReportBuilder failed (%s) — using fallback message", exc)
        today = date.today().isoformat()
        return f"📊 <b>SPA Daily Report — {today}</b>\n\n⚠️ Ошибка при построении отчёта: {exc}"


def _send_telegram(text: str) -> bool:
    """Отправляет сообщение через telegram_client (Keychain credentials). Fail-safe."""
    try:
        from spa_core.alerts import telegram_client  # noqa: PLC0415
        ok = telegram_client.send_message(text)
        if ok:
            log.info("Daily report sent to Telegram")
        else:
            log.warning("telegram_client.send_message returned False")
        return bool(ok)
    except Exception as exc:
        log.warning("telegram send failed (%s)", exc)
        return False


# ─── Public API ───────────────────────────────────────────────────────────────


def run_daily_report(
    data_dir: Optional[str | Path] = None,
    *,
    dry_run: bool = False,
    force_send: bool = False,
) -> dict:
    """Собрать и (опционально) отправить ежедневный Telegram-отчёт.

    Parameters
    ----------
    data_dir   : директория с data/*.json (default: <repo>/data).
    dry_run    : True → собрать отчёт, напечатать в лог, НЕ отправлять.
    force_send : True → отправить, даже если уже отправлялось сегодня (обходит sentinel).

    Returns
    -------
    dict с ключами: sent (bool), dry_run (bool), skipped (bool), message (str),
                    error (str | None).
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    # 1. Построить сообщение
    message = _build_message(ddir)

    # 2. Проверить rate-limit (если не force_send)
    should = _should_send(ddir, force_send)

    if dry_run:
        log.info("run_daily_report [DRY RUN]:\n%s", message)
        return {
            "sent": False,
            "dry_run": True,
            "skipped": False,
            "message": message,
            "error": None,
        }

    if not should:
        log.debug("Daily report already sent today — skipping (use force_send=True to override)")
        return {
            "sent": False,
            "dry_run": False,
            "skipped": True,
            "message": message,
            "error": None,
        }

    # 3. Отправить
    sent = _send_telegram(message)

    if sent:
        _mark_sent(ddir)

    return {
        "sent": sent,
        "dry_run": False,
        "skipped": False,
        "message": message,
        "error": None if sent else "telegram_client.send_message returned False",
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """Entrypoint: ``python3 -m spa_core.paper_trading.daily_report``."""
    parser = argparse.ArgumentParser(
        prog="spa_core.paper_trading.daily_report",
        description="Send (or preview) the SPA daily Telegram report.",
    )
    parser.add_argument(
        "--test-send",
        action="store_true",
        help="Force-send now, bypassing the once-per-day rate limit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the report but do NOT send it — print to stdout.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override the data directory (default: <repo>/data).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_daily_report(
        data_dir=args.data_dir,
        dry_run=args.dry_run,
        force_send=args.test_send,
    )

    if result["dry_run"]:
        print("=== DRY RUN — report NOT sent ===")
        print(result["message"])
    elif result["skipped"]:
        print("Daily report already sent today (use --test-send to override).")
    elif result["sent"]:
        print("✅ Daily report sent to Telegram.")
    else:
        print(f"❌ Failed to send daily report: {result.get('error')}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
