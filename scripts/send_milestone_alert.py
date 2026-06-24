#!/usr/bin/env python3
"""
MP-417: Telegram milestone alert — S7 пробил 10% APY барьер.
Токены читаются только из macOS Keychain; в файл не встраиваются.
Stdlib only (subprocess, urllib.request, urllib.parse, json).
"""
import subprocess
import urllib.request
import urllib.parse
import json
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]


def get_keychain(key: str) -> str | None:
    """Читает секрет из macOS Keychain по имени сервиса."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", key, "-w"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> None:
    bot_token = get_keychain("TELEGRAM_BOT_TOKEN_SPA")
    chat_id = get_keychain("TELEGRAM_CHAT_ID_SPA")

    if not bot_token or not chat_id:
        print("KEYCHAIN_UNAVAILABLE")
        sys.exit(0)

    message = (
        "\U0001f3c6 *MILESTONE: 10% APY БАРЬЕР ПРОБИТ*\n\n"
        "\U0001f4ca *Стратегия S7 — Pendle YT+PT Aggressive*\n"
        "• APY (base): 10.115% ✅\n"
        "• APY (bull): 14.5%\n"
        "• Risk score: 0.52\n"
        "• Tier: T3-SPEC\n\n"
        "\U0001f3af *Статус фонда*\n"
        "• Target: 10–15% APY\n"
        "• Baseline (Aave): 3.2%\n"
        "• Прирост: +6.9% над baseline\n\n"
        "\U0001f4c5 *Paper Trading*\n"
        "• Старт: 2026-06-12 (сегодня)\n"
        "• 30-дневное окно: до 2026-07-12\n"
        "• Go-Live: 2026-08-01\n\n"
        "\U0001f3c1 *Tournament S0–S10*\n"
        "• S0 Aave: 3.2%\n"
        "• S5 Pendle PT: 8.5%\n"
        "• *S7 Pendle YT+PT: 10.1%* ← WINNER\n"
        "• S10 Speculation: 14.0% (research)\n\n"
        "✅ GoLive: 26/26 PASS — система готова к go-live"
    )

    # FLOOD-GUARD: route through the canonical rate-limited client so this
    # one-shot milestone alert shares the cross-process flood guard. Transport
    # only — same Markdown message. Credentials are re-resolved by the canonical
    # client from the Keychain (the presence check above is retained).
    try:
        if str(_BASE) not in sys.path:
            sys.path.insert(0, str(_BASE))
        from spa_core.alerts.telegram_client import send_message
        if send_message(message, parse_mode="Markdown"):
            print("✅ Telegram milestone alert sent successfully")
        else:
            print("❌ Telegram send failed or suppressed by flood guard")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
