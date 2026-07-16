#!/bin/bash
# install_autopush_sh.command
# Устанавливает com.spa.autopush LaunchAgent (вызывает scripts/auto_push.sh каждые 90 мин)
# и сразу обрабатывает все ожидающие push_v*.sh из очереди.
#
# Запуск: дважды кликнуть в Finder (откроется Terminal)

set -euo pipefail

AGENTS="$HOME/Library/LaunchAgents"
SPA="$HOME/Documents/SPA_Claude"
PLIST_SRC="$SPA/scripts/com.spa.autopush.plist"
PLIST_DST="$AGENTS/com.spa.autopush.plist"

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Установка com.spa.autopush (auto_push.sh queue)   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. Проверяем исходный plist
if [ ! -f "$PLIST_SRC" ]; then
    echo "❌ Не найден: $PLIST_SRC"
    echo "   Убедись что репо на месте."
    exit 1
fi
echo "✅ Источник: $PLIST_SRC"

# 2. Выгружаем старый если есть
if launchctl list | grep -q "com.spa.autopush" 2>/dev/null; then
    echo "⏹  Выгружаем старый com.spa.autopush..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# 3. Копируем plist
mkdir -p "$AGENTS"
cp "$PLIST_SRC" "$PLIST_DST"
echo "📋 Скопирован → $PLIST_DST"

# 4. Загружаем
launchctl load "$PLIST_DST"
echo "✅ launchctl load: com.spa.autopush активен (интервал 90 мин)"

# 5. Проверяем статус
echo ""
echo "=== launchctl list | grep com.spa ==="
launchctl list | grep "com.spa" || echo "  (нет spa-агентов)"

# 6. Немедленно запускаем auto_push.sh — обработает ожидающие push_v*.sh
echo ""
echo "=== Запускаем auto_push.sh сейчас (обрабатываю очередь) ==="
bash "$SPA/scripts/auto_push.sh" || echo "⚠️  auto_push.sh завершился с ошибкой (см. выше)"

# 7. Итог
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Готово!                                            ║"
echo "║   com.spa.autopush установлен.                       ║"
echo "║   push_v*.sh очередь обработана.                     ║"
echo "║   Следующий авто-пуш — через 90 мин.                 ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Лог авто-пушей: scripts/.push_log"
echo "Вывод launchd:  /tmp/spa_autopush.log"
echo ""
read -rp "Enter для закрытия..."
