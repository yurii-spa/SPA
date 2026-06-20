#!/usr/bin/env bash
# install_autopush_silent.command
# Копирует com.spa.autopush.plist в ~/Library/LaunchAgents/ и загружает daemon.
# Без интерактивных пауз — предназначен для запуска двойным кликом из Finder.
# SECRETS POLICY: PAT не трогается и не выводится.
set -euo pipefail

PLIST_SRC="$HOME/Documents/SPA_Claude/com.spa.autopush.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.spa.autopush.plist"
LABEL="com.spa.autopush"

echo "=== SPA autopush silent install ==="
echo "src:  $PLIST_SRC"
echo "dst:  $PLIST_DST"

mkdir -p "$HOME/Library/LaunchAgents"

# Выгрузить старый демон если есть
launchctl unload "$PLIST_DST" 2>/dev/null && echo "unloaded old" || true

# Скопировать plist
cp "$PLIST_SRC" "$PLIST_DST"
echo "✅ plist скопирован"

# Загрузить daemon
launchctl load "$PLIST_DST"
echo "✅ com.spa.autopush загружен"

# Проверка
launchctl list | grep "$LABEL" && echo "✅ daemon активен" || echo "⚠️ daemon не виден в launchctl list (возможно RunAtLoad=true)"

echo ""
echo "Готово. Окно можно закрыть."
