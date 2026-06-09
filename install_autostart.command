#!/bin/bash
echo "╔═══════════════════════════════════════════════╗"
echo "║  SPA Autostart Installer (launchd + no-sleep)  ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

SPA_DIR="$HOME/Documents/SPA_Claude"
AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS_DIR"

# --- HTTP server plist ---
cat > "$AGENTS_DIR/com.spa.httpserver.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.httpserver</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>http.server</string>
        <string>8765</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/yuriikulieshov/Documents/SPA_Claude</string>
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
echo "✅ HTTP server plist установлен"

# --- Cloudflare tunnel plist ---
CF_BIN="$HOME/bin/cloudflared"
if command -v cloudflared &>/dev/null; then
    CF_BIN=$(command -v cloudflared)
fi

cat > "$AGENTS_DIR/com.spa.cloudflared.plist" << PLIST2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.cloudflared</string>
    <key>ProgramArguments</key>
    <array>
        <string>$CF_BIN</string>
        <string>tunnel</string>
        <string>--url</string>
        <string>http://localhost:8765</string>
        <string>--logfile</string>
        <string>/Users/yuriikulieshov/Documents/SPA_Claude/tunnel.log</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLIST2
echo "✅ Cloudflare tunnel plist установлен"

# Load services (unload first in case already loaded)
launchctl unload "$AGENTS_DIR/com.spa.httpserver.plist" 2>/dev/null || true
launchctl unload "$AGENTS_DIR/com.spa.cloudflared.plist" 2>/dev/null || true
launchctl load "$AGENTS_DIR/com.spa.httpserver.plist"
launchctl load "$AGENTS_DIR/com.spa.cloudflared.plist"
echo "✅ Службы загружены в launchd (автозапуск при входе)"

# Disable sleep
echo ""
echo "⚙️  Настраиваю режим энергопотребления..."
sudo pmset -a sleep 0 disksleep 0 hibernatemode 0 2>/dev/null && echo "✅ Сон отключён" || echo "⚠️  Введи пароль для отключения сна (или сделай вручную в System Settings → Energy)"

echo ""
echo "═══════════════════════════════════════════"
echo "✅ Установка завершена!"
echo "   Сервер и туннель будут стартовать"
echo "   автоматически при каждом входе в систему."
echo ""
echo "   URL туннеля смотри в файле:"
echo "   ~/Documents/SPA_Claude/tunnel.log"
echo "═══════════════════════════════════════════"
