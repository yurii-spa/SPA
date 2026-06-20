#!/usr/bin/env bash
# SETUP_ALL_DAEMONS.command
# Устанавливает ВСЕ SPA launchd демоны одной командой.
# Двойной клик в Finder — запустится Terminal и сделает всё.
# После этого больше никогда не нужно запускать вручную.

set -e
REPO="$HOME/Documents/SPA_Claude"
AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS_DIR"

echo "=============================="
echo " SPA Daemon Setup"
echo "=============================="
echo ""

# Проверка PAT
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
    echo "❌ PAT не найден в Keychain (GITHUB_PAT_SPA)"
    read -rp "Press Enter to close..."
    exit 1
fi
echo "✅ PAT найден (${#PAT} chars)"
unset PAT
echo ""

install_daemon() {
    local label="$1"
    local src="$2"

    if [ ! -f "$src" ]; then
        echo "⚠️  Plist не найден: $src — пропускаю"
        return
    fi

    local dst="$AGENTS_DIR/$label.plist"
    launchctl unload "$dst" 2>/dev/null || true
    cp "$src" "$dst"
    launchctl load "$dst"
    launchctl start "$label" 2>/dev/null || true
    echo "✅ $label — установлен и запущен"
}

# 1. Autopush (каждый час пушит новые скрипты)
install_daemon "com.spa.autopush" "$REPO/com.spa.autopush.plist"

# 2. FastAPI сервер (порт 8765, дашборд + /health)
install_daemon "com.spa.apiserver" "$REPO/com.spa.apiserver.plist"

# 3. Cycle runner (каждые 4 часа, fallback если GH Actions недоступен)
install_daemon "com.spa.cyclerunner" "$REPO/com.spa.cyclerunner.plist"

echo ""
echo "=============================="
echo " Проверка"
echo "=============================="
sleep 4

launchctl list | grep com.spa && echo "" || echo "⚠️ Демоны не видны — проверь /tmp/spa_*.log"

# API health check
sleep 3
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/health 2>/dev/null || echo "000")
if [ "$HTTP" = "200" ]; then
    echo "✅ API сервер отвечает (HTTP 200)"
else
    echo "⚠️  API сервер: HTTP $HTTP (может ещё стартует, проверь: tail -f /tmp/spa_api_err.log)"
fi

echo ""
echo "Логи:"
echo "  tail -f /tmp/spa_autopush.log"
echo "  tail -f /tmp/spa_api.log"
echo ""
echo "✅ Готово. Демоны работают автоматически при каждом входе в систему."
read -rp "Press Enter to close..."
