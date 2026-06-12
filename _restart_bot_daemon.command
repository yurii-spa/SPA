#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# _restart_bot_daemon.command
# Переустанавливает Telegram-бота как ПОСТОЯННЫЙ ДЕМОН (long-polling).
# Старый вариант: раз в 5 минут → ответ приходил через 5 мин.
# Новый вариант: KeepAlive + getUpdates(timeout=30) → ответ < 2 сек.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd ~/Documents/SPA_Claude

PLIST_NAME="com.spa.bot_commands"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PLIST_TMPL="$HOME/Documents/SPA_Claude/com.spa.bot_commands.plist"

echo "=== SPA Bot Daemon Restart ==="
echo ""

# ── 1. Найти правильный Python (с Full Disk Access) ──────────────────────────
echo "1/5  Ищу Python с TCC Full Disk Access..."

PYTHON=""
for candidate in \
    "$(cat "$HOME/Library/LaunchAgents/com.spa.daily_cycle.plist" 2>/dev/null | \
       grep -A1 'ProgramArguments' | grep python | tr -d ' <string>' | head -1)" \
    /opt/miniconda3/bin/python3 \
    /opt/miniconda3/bin/python \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3
do
    if [ -x "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Не нашёл Python. Добавь путь вручную в скрипт."
    exit 1
fi
echo "     Python: $PYTHON"

# ── 2. Проверить токен Telegram ───────────────────────────────────────────────
echo "2/5  Проверяю Telegram токен в Keychain..."
BOT_TOKEN=$(security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w 2>/dev/null || true)
if [ -z "$BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN_SPA не найден в Keychain!"
    echo "       Запусти: security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w <token>"
    exit 1
fi
echo "     ✅ токен найден"

# ── 3. Создать финальный plist из шаблона ─────────────────────────────────────
echo "3/5  Создаю plist с правильным Python..."
sed "s|__PYTHON_PATH__|${PYTHON}|g" "$PLIST_TMPL" > "$PLIST_DEST"
echo "     Записан: $PLIST_DEST"

# ── 4. Выгрузить старый сервис (если был) ────────────────────────────────────
echo "4/5  Останавливаю старый сервис..."
launchctl unload "$PLIST_DEST" 2>/dev/null && echo "     ✅ выгружен" || echo "     (не был загружен)"
sleep 1

# ── 5. Загрузить новый ───────────────────────────────────────────────────────
echo "5/5  Запускаю демон..."
launchctl load "$PLIST_DEST"
sleep 3

# ── Проверка статуса ─────────────────────────────────────────────────────────
echo ""
echo "=== Статус ==="
STATUS=$(launchctl list | grep "$PLIST_NAME" || echo "не найден")
echo "$STATUS"

if echo "$STATUS" | grep -q "$PLIST_NAME"; then
    PID=$(echo "$STATUS" | awk '{print $1}')
    if [ "$PID" != "-" ] && [ -n "$PID" ]; then
        echo ""
        echo "✅ Бот запущен! PID=$PID"
        echo "   Режим: continuous long-polling (ответ < 2 сек)"
        echo "   Логи:  tail -f /tmp/spa_bot_commands.log"
        echo "   Ошибки: tail -f /tmp/spa_bot_commands.err"
        echo ""
        echo "Напиши боту /start — должен ответить мгновенно."
    else
        echo ""
        echo "⚠️  Сервис загружен но процесс не стартовал."
        echo "   Проверь ошибки: cat /tmp/spa_bot_commands.err"
    fi
else
    echo "❌ Не удалось загрузить сервис!"
    cat /tmp/spa_bot_commands.err 2>/dev/null | tail -20 || true
    exit 1
fi
