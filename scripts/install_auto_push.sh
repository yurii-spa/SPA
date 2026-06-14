#!/bin/bash
# install_auto_push.sh — устанавливает launchd агент для авто-пуша каждые 90 минут

PLIST_SRC="/Users/yuriikulieshov/Documents/SPA_Claude/launchd/com.spa.auto_push.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.spa.auto_push.plist"
LOG_DIR="/Users/yuriikulieshov/Documents/SPA_Claude/logs"

mkdir -p "$LOG_DIR"

# Выгружаем если уже был загружен
launchctl unload "$PLIST_DST" 2>/dev/null || true

cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"

echo "✅ com.spa.auto_push установлен и запущен"
echo "   Интервал: каждые 90 минут"
echo "   Логи: $LOG_DIR/auto_push.log"
echo ""
echo "Проверить статус:"
echo "  launchctl list | grep spa.auto_push"
