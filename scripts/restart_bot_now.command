#!/bin/bash
# restart_bot_now.command — перезапуск бота + фиксы агентов
# Двойной клик для запуска

cd ~/Documents/SPA_Claude
LOG="logs/restart_bot_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "=== Перезапуск SPA Telegram Bot ==="
echo "$(date)"
echo ""

# 1. Перезапустить бота (применит фиксы bot.py + reporting_agent.py + alert_manager.py)
echo "▶ Перезапуск bot_commands..."
launchctl unload ~/Library/LaunchAgents/com.spa.bot_commands.plist 2>/dev/null || true
sleep 2
launchctl load ~/Library/LaunchAgents/com.spa.bot_commands.plist
echo "✅ bot_commands перезапущен"
echo ""

# 2. Перезапустить cycle_gap_monitor (убрали --check)
echo "▶ Перезапуск cycle_gap_monitor..."
launchctl unload ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist 2>/dev/null || true
sleep 1
launchctl load ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist 2>/dev/null || \
  echo "  ⚠️ cycle_gap_monitor plist не найден в LaunchAgents (нужен пуш сначала)"
echo "✅ cycle_gap_monitor готов"
echo ""

# 3. Загрузить cycle_health если ещё не загружен
echo "▶ Загрузка cycle_health..."
if [ -f ~/Library/LaunchAgents/com.spa.cycle_health.plist ]; then
  launchctl unload ~/Library/LaunchAgents/com.spa.cycle_health.plist 2>/dev/null || true
  sleep 1
  launchctl load ~/Library/LaunchAgents/com.spa.cycle_health.plist
  echo "✅ cycle_health загружен"
else
  cp scripts/com.spa.cycle_health.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.spa.cycle_health.plist
  echo "✅ cycle_health установлен и загружен (был новый)"
fi
echo ""

echo "=== Готово ==="
echo "Бот перезапущен с новым кодом:"
echo "  • Кнопка 'Подробнее' теперь показывает детали события"
echo "  • Daily Report теперь показывает реальные данные"
echo "  • Telegram алерты: не чаще 1 раза в сутки"
echo ""
echo "Лог: $LOG"
read -rp "Нажми Enter для закрытия..."
