#!/bin/bash
# SPA: Fix & Install Telegram Bot (com.spa.bot_commands)
# -------------------------------------------------------
# Диагноз: plist не установлен в ~/Library/LaunchAgents/
# Проблема: /usr/bin/python3 имеет TCC-ограничения (нет доступа к ~/Documents)
# Решение: установить plist с miniconda/Homebrew python3 (как у daily_cycle)

set -euo pipefail
cd "$(dirname "$0")"
SPA="$(pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"

echo "╔════════════════════════════════════════════════╗"
echo "║   SPA: Fix Telegram Bot (com.spa.bot_commands) ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# ── 1. Определяем Python (из daily_cycle plist — он работает) ──────────────────
echo "=== [1/4] Определяю Python-путь ==="

PYTHON_PATH=""

DAILY_PLIST="$AGENTS/com.spa.daily_cycle.plist"
if [ -f "$DAILY_PLIST" ]; then
    PYTHON_PATH=$(grep -oE '/[^<>]*python[^<>]*' "$DAILY_PLIST" | head -1 || true)
    if [ -n "$PYTHON_PATH" ] && [ -x "$PYTHON_PATH" ]; then
        echo "  ✅ Из daily_cycle plist: $PYTHON_PATH"
    else
        PYTHON_PATH=""
    fi
fi

if [ -z "$PYTHON_PATH" ]; then
    echo "  ⚠️  daily_cycle plist не найден, ищу в известных местах..."
    for p in \
        "$HOME/miniconda3/bin/python3" \
        "$HOME/opt/miniconda3/bin/python3" \
        "$HOME/miniforge3/bin/python3" \
        "$HOME/anaconda3/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3"; do
        if [ -x "$p" ]; then
            PYTHON_PATH="$p"
            echo "  ✅ Найден: $PYTHON_PATH"
            break
        fi
    done
fi

if [ -z "$PYTHON_PATH" ]; then
    PYTHON_PATH=$(which python3 2>/dev/null || true)
    [ -n "$PYTHON_PATH" ] && echo "  ℹ️  Используем PATH python3: $PYTHON_PATH"
fi

if [ -z "$PYTHON_PATH" ]; then
    echo "  ❌ Не могу найти python3. Выход."
    exit 1
fi

echo "  Python версия: $($PYTHON_PATH --version 2>&1)"
echo ""

# ── 2. Токен в Keychain ────────────────────────────────────────────────────────
echo "=== [2/4] Проверяю токены в Keychain ==="

TOKEN=$(security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w 2>&1 || true)
CHAT_ID=$(security find-generic-password -s TELEGRAM_CHAT_ID_SPA -a spa -w 2>&1 || true)

if [[ "$TOKEN" == *"could not be found"* ]] || [ -z "$TOKEN" ]; then
    echo "  ❌ TELEGRAM_BOT_TOKEN_SPA не найден в Keychain!"
    echo "     Добавь командой:"
    echo "     security add-generic-password -s TELEGRAM_BOT_TOKEN_SPA -a spa -w 'ВАШ_ТОКЕН'"
    TOKEN_OK=false
else
    echo "  ✅ TELEGRAM_BOT_TOKEN_SPA: найден (${#TOKEN} симв.)"
    TOKEN_OK=true
fi

if [[ "$CHAT_ID" == *"could not be found"* ]] || [ -z "$CHAT_ID" ]; then
    echo "  ❌ TELEGRAM_CHAT_ID_SPA не найден в Keychain!"
    echo "     Добавь командой:"
    echo "     security add-generic-password -s TELEGRAM_CHAT_ID_SPA -a spa -w 'ВАШ_CHAT_ID'"
    CHAT_OK=false
else
    echo "  ✅ TELEGRAM_CHAT_ID_SPA: найден"
    CHAT_OK=true
fi

if [ "$TOKEN_OK" = false ] || [ "$CHAT_OK" = false ]; then
    echo ""
    echo "  ⚠️  Токены отсутствуют — сервис не сможет работать!"
    echo "     После добавления токенов перезапусти этот скрипт."
    echo ""
fi
echo ""

# ── 3. Создаём и устанавливаем plist ──────────────────────────────────────────
echo "=== [3/4] Устанавливаю launchd plist ==="

# Остановить если уже загружен
if launchctl list com.spa.bot_commands &>/dev/null; then
    echo "  ⏹  Выгружаю старый com.spa.bot_commands..."
    launchctl unload "$AGENTS/com.spa.bot_commands.plist" 2>/dev/null || true
fi

# Создать plist с правильным python
cat > "$AGENTS/com.spa.bot_commands.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.bot_commands</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${SPA}/spa_core/alerts/bot_commands.py</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/spa_bot_commands.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spa_bot_commands.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

echo "  ✅ Plist записан: $AGENTS/com.spa.bot_commands.plist"

# Загрузить
launchctl load "$AGENTS/com.spa.bot_commands.plist"
echo "  ✅ Сервис загружен в launchd"
echo ""

# Ждём запуска (RunAtLoad=true → он должен сразу запуститься)
sleep 3

# Статус
echo "  --- Статус всех spa-сервисов ---"
launchctl list | grep spa || echo "  (нет spa-сервисов)"
echo ""

# Проверка bot_commands отдельно
STATUS_LINE=$(launchctl list | grep "com.spa.bot_commands" || true)
if [ -n "$STATUS_LINE" ]; then
    EXIT_CODE=$(echo "$STATUS_LINE" | awk '{print $2}')
    PID=$(echo "$STATUS_LINE" | awk '{print $1}')
    if [ "$EXIT_CODE" = "0" ] || [ "$PID" != "-" ]; then
        echo "  ✅ com.spa.bot_commands работает (PID=$PID, exit=$EXIT_CODE)"
    else
        echo "  ⚠️  com.spa.bot_commands завершился с exit=$EXIT_CODE"
        echo "  Последние ошибки:"
        tail -10 /tmp/spa_bot_commands.err 2>/dev/null || echo "  (лог пуст)"
    fi
fi
echo ""

# ── 4. Тестовое сообщение ──────────────────────────────────────────────────────
echo "=== [4/4] Тестовое сообщение в Telegram ==="

if [ "$TOKEN_OK" = true ] && [ "$CHAT_OK" = true ]; then
    "$PYTHON_PATH" -c "
import sys
sys.path.insert(0, '$SPA')
from spa_core.alerts.telegram_client import send_message
ok = send_message('✅ SPA Bot запущен и работает! Нажми /start чтобы увидеть меню.')
print('  ✅ Сообщение отправлено!' if ok else '  ⚠️  Ошибка отправки — смотри логи')
"
else
    echo "  ⏭  Пропускаю тест — токены не найдены в Keychain"
fi

echo ""
echo "  Логи бота: /tmp/spa_bot_commands.log"
echo "  Ошибки:    /tmp/spa_bot_commands.err"
echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  ✅ Telegram Bot исправлен и запущен!           ║"
echo "║  Бот будет опрашивать Telegram каждые 5 минут  ║"
echo "║  при автозапуске системы.                       ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "Нажми Enter чтобы закрыть..."
read
