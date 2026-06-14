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

    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
    ).encode()

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                print("✅ Telegram milestone alert sent successfully")
            else:
                print(f"❌ Telegram API error: {result}")
                sys.exit(1)
    except Exception as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
