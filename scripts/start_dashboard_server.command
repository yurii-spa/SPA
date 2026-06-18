#!/bin/bash
# start_dashboard_server.command — запускает статический сервер дашборда на порту 8766
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/dashboard_server_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

PLIST_PATH="$HOME/Library/LaunchAgents/com.spa.dashboard.plist"
LOG_DIR="$HOME/Documents/SPA_Claude/logs"

echo "════════════════════════════════════════════"
echo " SPA Dashboard Static Server (port 8766)"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"

# Выгружаем старый (если есть)
launchctl unload "$PLIST_PATH" 2>/dev/null || true
sleep 1

# Пишем plist
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>http.server</string>
        <string>8766</string>
        <string>--directory</string>
        <string>/Users/yuriikulieshov/Documents/SPA_Claude</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/dashboard_server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/dashboard_server.err</string>
</dict>
</plist>
PLIST

echo "✅ Plist создан: $PLIST_PATH"

launchctl load "$PLIST_PATH"
sleep 3

STATUS=$(launchctl list | grep "com.spa.dashboard")
echo "   launchctl: $STATUS"
PID=$(echo "$STATUS" | awk '{print $1}')
if [ -n "$PID" ] && [ "$PID" != "-" ]; then
  echo "✅ Dashboard сервер запущен! PID=$PID"
  echo "   URL: http://localhost:8766"
else
  echo "⚠️  Загружен, ждём PID..."
fi

echo ""
echo "════════════════════════════════════════════"
echo " Теперь обнови Cloudflare route:"
echo " localhost:8765 → localhost:8766"
echo "════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
