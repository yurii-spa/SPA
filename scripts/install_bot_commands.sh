#!/bin/bash
# Устанавливает launchd агента для Telegram bot_commands
# Запустить один раз: bash ~/Documents/SPA_Claude/scripts/install_bot_commands.sh

set -euo pipefail

mkdir -p ~/Documents/SPA_Claude/logs

# Copy plist
cp ~/Documents/SPA_Claude/launchd/com.spa.bot_commands.plist \
   ~/Library/LaunchAgents/com.spa.bot_commands.plist

# Unload if already running
launchctl unload ~/Library/LaunchAgents/com.spa.bot_commands.plist 2>/dev/null || true

# Load (starts immediately due to RunAtLoad=true)
launchctl load ~/Library/LaunchAgents/com.spa.bot_commands.plist

echo "✅ SPA Bot Commands installed and running"
echo "📋 Logs: ~/Documents/SPA_Claude/logs/bot_commands.log"
echo "🔍 Status: launchctl list | grep spa.bot"
