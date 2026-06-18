#!/bin/bash
# setup_cloudflared.command — установка cloudflared для SPA
# Дважды кликни в Finder → откроется Terminal и запустится автоматически

echo "╔══════════════════════════════════════╗"
echo "║   SPA — Установка cloudflared        ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Установка через Homebrew ───────────────────────────
echo "── Шаг 1: brew install cloudflared ──"
if which cloudflared >/dev/null 2>&1; then
  echo "✅ cloudflared уже установлен: $(cloudflared --version 2>&1 | head -1)"
else
  echo "📦 Устанавливаю..."
  /opt/homebrew/bin/brew install cloudflared 2>&1
  if which cloudflared >/dev/null 2>&1; then
    echo "✅ cloudflared установлен успешно"
  else
    echo "❌ Ошибка установки. Убедись что Homebrew установлен: https://brew.sh"
    read -p "Нажми Enter для выхода..."
    exit 1
  fi
fi

echo ""
echo "── Шаг 2: Авторизация в Cloudflare ──"
echo "⚡ Откроется браузер — войди в аккаунт Cloudflare и нажми Authorize"
echo ""
sleep 2
cloudflared tunnel login

echo ""
echo "── Шаг 3: Создание туннеля 'spa' ────"
# Проверяем не существует ли уже
if cloudflared tunnel list 2>/dev/null | grep -q "spa"; then
  echo "✅ Туннель 'spa' уже существует"
else
  cloudflared tunnel create spa
  echo "✅ Туннель 'spa' создан"
fi

echo ""
echo "── Шаг 4: Конфиг ────────────────────"
mkdir -p ~/.cloudflared

# Получаем UUID туннеля
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "spa" | awk '{print $1}' | head -1)

if [ -n "$TUNNEL_ID" ]; then
  cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /Users/yuriikulieshov/.cloudflared/$TUNNEL_ID.json

ingress:
  - service: http://localhost:8766
EOF
  echo "✅ Конфиг записан: ~/.cloudflared/config.yml"
  echo "   Туннель ID: $TUNNEL_ID"
else
  echo "⚠️  Не удалось получить ID туннеля — проверь: cloudflared tunnel list"
fi

echo ""
echo "── Шаг 5: Запуск агента ─────────────"
cp ~/Documents/SPA_Claude/scripts/com.spa.cloudflared.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.cloudflared.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.cloudflared.plist
sleep 3
STATUS=$(launchctl list | grep "com.spa.cloudflared" | awk '{print $1}')
if [ "$STATUS" != "-" ]; then
  echo "✅ cloudflared запущен (pid=$STATUS)"
else
  echo "⚠️  cloudflared загружен, запустится при следующем старте"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   ✅ Готово! Туннель настроен.       ║"
echo "╚══════════════════════════════════════╝"
echo ""
read -p "Нажми Enter для закрытия..."
