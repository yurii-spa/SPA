#!/bin/bash
# fix_and_push.command — reload daily_cycle agent + push all pending changes
# Run by double-clicking in Finder

set -uo pipefail

echo "=============================================="
echo " SPA Fix & Push ($(date))"
echo "=============================================="
echo ""

# 1. Reload daily_cycle agent с исправленным run_daily_paper_cycle.sh
echo "--- Step 1: Reload com.spa.daily_cycle ---"
PLIST="$HOME/Library/LaunchAgents/com.spa.daily_cycle.plist"

if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null && echo "  unloaded OK" || echo "  unload skipped (was not loaded)"
    sleep 1
    if launchctl load "$PLIST" 2>&1; then
        echo "  ✅ com.spa.daily_cycle reloaded"
    else
        echo "  ❌ load failed"
    fi
else
    echo "  ❌ plist not found: $PLIST"
fi

echo ""

# 2. Запускаем mp_push_all_changes.command
echo "--- Step 2: Push all pending changes (249 files) ---"
PUSH_CMD="$HOME/Documents/SPA_Claude/mp_push_all_changes.command"

if [ -f "$PUSH_CMD" ]; then
    bash "$PUSH_CMD"
    echo "  ✅ Push done"
else
    echo "  ❌ mp_push_all_changes.command not found, running autopush instead..."
    bash "$HOME/Documents/SPA_Claude/scripts/auto_push.sh"
fi

echo ""
echo "=============================================="
echo " Готово! Нажми Enter чтобы закрыть"
echo "=============================================="
read
