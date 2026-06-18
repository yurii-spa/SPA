#!/bin/bash
# mac_actions.sh — действия которые нужны только на Mac
# Запуск: bash ~/Documents/SPA_Claude/scripts/mac_actions.sh

echo "═══ SPA Mac Actions ═══"

echo ""
echo "── 1. Перезагрузка cycle_health (исправленный модуль) ─"
cp ~/Documents/SPA_Claude/scripts/com.spa.cycle_health.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.cycle_health.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.cycle_health.plist
echo "✅ cycle_health перезагружен"

echo ""
echo "── 2. Установка всех 19 агентов ───────────────────────"
bash ~/Documents/SPA_Claude/scripts/install_agents.sh 2>&1 | tail -5
echo "✅ Агенты установлены"

echo ""
echo "── 3. Push всех изменений на GitHub ───────────────────"
bash ~/Documents/SPA_Claude/scripts/push_final.sh
bash ~/Documents/SPA_Claude/scripts/push_fix_aave_apy.sh
bash ~/Documents/SPA_Claude/scripts/push_strategy_loop.sh
bash ~/Documents/SPA_Claude/scripts/push_fix_uptime_v2.sh
bash ~/Documents/SPA_Claude/scripts/push_audit_v3.sh
echo "✅ Push завершён"

echo ""
echo "── 4. Статус агентов ──────────────────────────────────"
launchctl list | grep "com.spa" | awk '{
  if ($1 != "-") status="✅ RUNNING (pid="$1")"
  else if ($2 == "0") status="⏸ IDLE"
  else status="❌ CRASHED (exit="$2")"
  printf "  %-44s %s\n", $3, status
}' | sort

echo ""
echo "── 5. cloudflared (если не установлен) ────────────────"
if which cloudflared >/dev/null 2>&1; then
  echo "✅ cloudflared уже установлен"
else
  echo "⚠️  cloudflared не найден. Установи:"
  echo "   brew install cloudflared"
  echo "   cloudflared tunnel login"
  echo "   cloudflared tunnel create spa"
fi

echo ""
echo "═══ DONE ═══"
