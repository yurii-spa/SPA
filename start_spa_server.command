#!/bin/bash
echo "╔══════════════════════════════════════════╗"
echo "║   SPA Local Server + Cloudflare Tunnel  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Kill any previous instance
pkill -f "python3 -m http.server 8765" 2>/dev/null && echo "⏹  Остановлен старый HTTP-сервер"

# Start HTTP server
cd ~/Documents/SPA_Claude
python3 -m http.server 8765 &
HTTP_PID=$!
sleep 1
echo "✅ HTTP-сервер запущен: http://localhost:8765 (PID $HTTP_PID)"
echo ""

# Install cloudflared if needed
if ! command -v cloudflared &>/dev/null && [ ! -f ~/bin/cloudflared ]; then
    echo "⬇️  Устанавливаю cloudflared..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz"
    else
        URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
    fi
    curl -L "$URL" -o /tmp/cf.tgz 2>/dev/null
    mkdir -p ~/bin
    tar -xzf /tmp/cf.tgz -C ~/bin/
    chmod +x ~/bin/cloudflared
    echo "✅ cloudflared установлен в ~/bin/"
fi

CF=$(command -v cloudflared 2>/dev/null || echo "$HOME/bin/cloudflared")
echo "🌐 Запускаю Cloudflare Tunnel..."
echo "   Через несколько секунд появится публичная ссылка — сохрани её!"
echo "   (нажми Ctrl+C чтобы остановить всё)"
echo ""
"$CF" tunnel --url http://localhost:8765
