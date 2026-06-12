#!/bin/bash
# SPA: Telegram Bot — быстрый тест и статус
# Двойной клик = проверить и отправить тест в Telegram

cd "$(dirname "$0")"
SPA="$(pwd)"

echo "=== SPA Telegram Bot — тест и статус ==="
echo ""

# ── Найти Python ──────────────────────────────────────────────────────────────
AGENTS="$HOME/Library/LaunchAgents"
PYTHON=""

DAILY_PLIST="$AGENTS/com.spa.daily_cycle.plist"
if [ -f "$DAILY_PLIST" ]; then
    PYTHON=$(grep -oE '/[^<>]*python[^<>]*' "$DAILY_PLIST" | head -1 || true)
    [ -n "$PYTHON" ] && [ -x "$PYTHON" ] || PYTHON=""
fi

if [ -z "$PYTHON" ]; then
    for p in \
        "$HOME/miniconda3/bin/python3" \
        "$HOME/opt/miniconda3/bin/python3" \
        "$HOME/miniforge3/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3" \
        "$(which python3 2>/dev/null)"; do
        [ -x "$p" ] && PYTHON="$p" && break
    done
fi

echo "Python: ${PYTHON:-НЕ НАЙДЕН}"

if [ -z "$PYTHON" ]; then
    echo "❌ Python не найден!"
    echo "Нажми Enter..."
    read
    exit 1
fi

# ── Проверить токен ────────────────────────────────────────────────────────────
TOKEN=$(security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w 2>/dev/null || true)
if [ -z "$TOKEN" ] || [[ "$TOKEN" == *"could not be found"* ]]; then
    echo "❌ Токен TELEGRAM_BOT_TOKEN_SPA не найден в Keychain!"
    echo ""
    echo "Добавь токен командой в Terminal:"
    echo "  security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w 'ВАШ_ТОКЕН'"
    echo ""
    echo "Нажми Enter..."
    read
    exit 1
fi
echo "✅ Токен найден (${#TOKEN} символов)"

# ── Статус launchd ────────────────────────────────────────────────────────────
echo ""
echo "--- Статус launchd ---"
STATUS_LINE=$(launchctl list | grep "com.spa.bot_commands" || true)
if [ -z "$STATUS_LINE" ]; then
    echo "⚠️  com.spa.bot_commands НЕ загружен в launchd!"
    echo "   Запусти _fix_telegram_bot.command чтобы установить."
else
    EXIT_CODE=$(echo "$STATUS_LINE" | awk '{print $2}')
    PID=$(echo "$STATUS_LINE" | awk '{print $1}')
    echo "   PID=$PID  exit=$EXIT_CODE"
    if [ "$EXIT_CODE" = "0" ]; then
        echo "   ✅ Сервис активен"
    else
        echo "   ⚠️  Последний запуск завершился с ошибкой (exit=$EXIT_CODE)"
    fi
fi

# ── Последние логи ────────────────────────────────────────────────────────────
echo ""
echo "--- Последние строки /tmp/spa_bot_commands.err ---"
tail -5 /tmp/spa_bot_commands.err 2>/dev/null || echo "  (лог пуст — нормально если ошибок нет)"

# ── Отправить тестовое сообщение ──────────────────────────────────────────────
echo ""
echo "--- Отправка тестового сообщения ---"

"$PYTHON" -c "
import sys
sys.path.insert(0, '$SPA')
from spa_core.alerts.telegram_client import send_message
ok = send_message('✅ SPA Bot работает! Используй кнопки ниже или нажми /start.')
print('Тест: ' + ('OK ✅' if ok else 'FAIL ❌'))
"

echo ""
echo "Готово. Проверь Telegram."
echo ""
echo "Нажми Enter чтобы закрыть..."
read
