#!/usr/bin/env bash
# fix_api_server.command — устанавливает uvicorn + fastapi, останавливает старый httpserver
set -e

echo "=== Fixing SPA API Server ==="
echo ""

# 1. Install uvicorn + fastapi
echo "Installing uvicorn + fastapi..."
pip install uvicorn fastapi --break-system-packages -q
echo "✅ uvicorn + fastapi installed"
echo ""

# 2. Stop old httpserver (python3 -m http.server)
echo "Stopping old com.spa.httpserver..."
launchctl unload ~/Library/LaunchAgents/com.spa.httpserver.plist 2>/dev/null || true
echo "✅ old httpserver stopped"
echo ""

# 3. Restart new apiserver
echo "Restarting com.spa.apiserver..."
launchctl stop com.spa.apiserver 2>/dev/null || true
sleep 2
launchctl start com.spa.apiserver
echo "✅ com.spa.apiserver restarted"
echo ""

# 4. Wait and check
sleep 5
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/health 2>/dev/null || echo "000")
if [ "$HTTP" = "200" ]; then
    echo "✅ API server: HTTP 200 — работает!"
    curl -s http://localhost:8765/health | python3 -m json.tool 2>/dev/null || true
else
    echo "⚠️  API server: HTTP $HTTP"
    echo "Лог:"
    tail -20 /tmp/spa_api_err.log 2>/dev/null || echo "(пусто)"
fi

read -rp "Press Enter to close..."
