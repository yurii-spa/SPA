#!/usr/bin/env bash
# _push_day_summary.command
# Push итогов дня 2026-06-20: GoLive 26/26 READY, autopush_installed, CURRENT_STATE v12.01
# Запуск: bash ~/Documents/SPA_Claude/_push_day_summary.command

set -euo pipefail
cd ~/Documents/SPA_Claude

echo "=== SPA Day Summary Push — 2026-06-20 ==="
echo "GoLive: 26/26 ✅ READY | autopush_installed=true | v12.01"
echo ""

PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
    echo "❌ PAT не найден в Keychain (ключ: GITHUB_PAT_SPA)"
    echo "   Фикс: bash setup_pat.sh"
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "✅ PAT получен из Keychain"
echo ""

python3 push_to_github.py \
    --files \
        data/golive_status.json \
        data/adapter_registry.json \
        data/strategy_summary.json \
        CURRENT_STATE.md \
    --message "feat: GoLive 26/26 READY, autopush installed, CURRENT_STATE v12.01" \
    --pat "$PAT"

echo ""
echo "=== Push complete ==="
read -r -p "Press Enter to close..."
