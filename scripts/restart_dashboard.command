#!/bin/bash
# restart_dashboard.command — убивает старый сервер и стартует новый
# Double-click in Finder to run
set -e

PLIST_PATH="$HOME/Library/LaunchAgents/com.spa.dashboard.plist"
DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
PORT=8766

echo "════════════════════════════════════════════"
echo " Restart SPA Dashboard Server (port $PORT)"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"

# 1. Выгружаем старый LaunchAgent (если есть)
launchctl unload "$PLIST_PATH" 2>/dev/null && echo "✅ Old LaunchAgent unloaded" || echo "  (no old LaunchAgent)"
sleep 1

# 2. Убиваем любой python3 на этом порту
PID_OLD=$(lsof -ti tcp:$PORT 2>/dev/null) || true
if [ -n "$PID_OLD" ]; then
  kill -9 $PID_OLD 2>/dev/null && echo "✅ Killed old process PID=$PID_OLD" || true
  sleep 1
fi

# 3. Проверяем python3
PYTHON=$(which python3)
echo "   Python: $PYTHON ($($PYTHON --version 2>&1))"
echo "   Dir: $DIR"
echo "   Index: $(ls $DIR/index.html 2>/dev/null && echo EXISTS || echo MISSING)"

# 4. Создаём plist с правильным python3
mkdir -p "$HOME/Documents/SPA_Claude/logs"
LOG_DIR="$HOME/Documents/SPA_Claude/logs"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>-m</string>
        <string>http.server</string>
        <string>--directory</string>
        <string>$DIR</string>
        <string>$PORT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/dashboard_server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/dashboard_server.err</string>
</dict>
</plist>
PLIST

echo "✅ Plist written to: $PLIST_PATH"
cat "$PLIST_PATH"

# 5. Загружаем
launchctl load "$PLIST_PATH"
sleep 3

# 6. Проверяем
STATUS=$(launchctl list | grep "com.spa.dashboard" || echo "NOT FOUND")
echo ""
echo "Status: $STATUS"

PID=$(echo "$STATUS" | awk '{print $1}')
if [ -n "$PID" ] && [ "$PID" != "-" ] && [ "$PID" != "NOT" ]; then
  echo "✅ Dashboard server running! PID=$PID"
else
  echo "⚠️  Process might be starting..."
fi

sleep 2

# 7. Тест
echo ""
echo "Testing http://localhost:$PORT/ ..."
curl -s -o /dev/null -w "HTTP %{http_code}" "http://localhost:$PORT/" || echo "curl failed"
echo ""
curl -s -o /dev/null -w "HTTP %{http_code}" "http://localhost:$PORT/index.html" || echo "curl failed"
echo ""
echo ""
echo "════════════════════════════════════════════"
echo " Done! Test: https://dashboard.earn-defi.com"
echo "════════════════════════════════════════════"
read -rp "Press Enter to close..."
