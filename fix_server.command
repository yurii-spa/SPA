#!/bin/bash
echo "╔══════════════════════════════════════════╗"
echo "║      SPA Server Fix + Security Patch     ║"
echo "╚══════════════════════════════════════════╝"

AGENTS="$HOME/Library/LaunchAgents"
SPA="$HOME/Documents/SPA_Claude"

# 1. Unload broken service
launchctl unload "$AGENTS/com.spa.httpserver.plist" 2>/dev/null || true
echo "⏹  Остановлен старый HTTP-сервер"

# 2. Update plist to use Python wrapper (bypasses os.getcwd TCC issue)
cat > "$AGENTS/com.spa.httpserver.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.httpserver</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/yuriikulieshov/Documents/SPA_Claude/spa_server.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yuriikulieshov/Documents/SPA_Claude/httpserver.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yuriikulieshov/Documents/SPA_Claude/httpserver.log</string>
</dict>
</plist>
PLIST
echo "✅ Plist обновлён (используется spa_server.py)"

# 3. Load updated service
launchctl load "$AGENTS/com.spa.httpserver.plist"
echo "✅ Служба перезапущена"
sleep 3

# 4. Verify
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/ | grep -q "200"; then
    echo "✅ localhost:8765 → HTTP 200 — сервер работает!"
else
    echo "⚠️  Не отвечает. Последние строки лога:"
    tail -5 "$SPA/httpserver.log"
fi

# 5. Show tunnel URL
echo ""
echo "🌐 Текущий URL туннеля:"
grep -o '"https://[a-z-]*\.trycloudflare\.com"' "$SPA/tunnel.log" | tail -1 | tr -d '"'

echo ""
echo "✅ Готово!"
