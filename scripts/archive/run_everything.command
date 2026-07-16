#!/usr/bin/env bash
# run_everything.command — запускает auto_push + install Engine B/C LaunchAgents
cd "$HOME/Documents/SPA_Claude"

echo "======================================"
echo " SPA — Запуск всего автономно"
echo " $(date)"
echo "======================================"
echo ""

# 1. Install Engine B/C LaunchAgents
echo ">>> Шаг 1: Install Engine B/C LaunchAgents"
bash "$HOME/Documents/SPA_Claude/scripts/install_engine_bc_launchd.sh" && echo "✅ Engine B/C LaunchAgents установлены" || echo "⚠️ Ошибка установки LaunchAgents (возможно уже установлены)"
echo ""

# 2. Restart API server if script exists
echo ">>> Шаг 2: Перезапуск API server"
if [ -f "$HOME/Documents/SPA_Claude/scripts/restart_apiserver.command" ]; then
    bash "$HOME/Documents/SPA_Claude/scripts/restart_apiserver.command" && echo "✅ API server перезапущен" || echo "⚠️ Ошибка перезапуска"
else
    echo "ℹ️ restart_apiserver.command не найден — пропускаем"
fi
echo ""

# 3. Run auto_push manually to process all pending scripts
echo ">>> Шаг 3: auto_push — push v1315-v1334"
bash "$HOME/Documents/SPA_Claude/scripts/auto_push.sh" 2>&1
echo ""

# 4. Check Engine B/C status
echo ">>> Шаг 4: Статус Engine B/C"
bash "$HOME/Documents/SPA_Claude/scripts/check_engine_bc_status.sh" 2>/dev/null || echo "check script not found"

echo ""
echo "======================================"
echo " ГОТОВО — $(date)"
echo "======================================"
read -p "Нажмите Enter для закрытия..." _
