#!/bin/bash
# cf_install_and_login.command — установка cloudflared + генерация login URL
cd ~/Documents/SPA_Claude
mkdir -p logs
LOG="logs/cf_setup_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════"
echo " SPA — Cloudflare Tunnel Setup"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""

# Шаг 1: установка cloudflared
echo "▶ Шаг 1/4: Проверка cloudflared..."
if which cloudflared >/dev/null 2>&1; then
  echo "✅ cloudflared уже установлен: $(cloudflared --version 2>&1 | head -1)"
else
  echo "   Устанавливаем через brew..."
  if which brew >/dev/null 2>&1; then
    brew install cloudflared
    echo "✅ cloudflared установлен: $(cloudflared --version 2>&1 | head -1)"
  else
    echo "❌ brew не найден. Установи Homebrew:"
    echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    read -rp "Нажми Enter после установки brew, затем перезапусти этот скрипт..."; exit 1
  fi
fi
echo ""

# Шаг 2: login — запускаем и перехватываем URL
echo "▶ Шаг 2/4: Cloudflare login (захватываем URL)..."
URL_FILE="/tmp/cf_login_url.txt"
rm -f "$URL_FILE"

# Запускаем login в фоне, перехватываем URL без открытия браузера
cloudflared tunnel login 2>&1 | tee /tmp/cf_login_raw.txt &
CF_PID=$!

# Ждём URL в выводе (до 30 сек)
for i in $(seq 1 30); do
  URL=$(grep -oE 'https://dash\.cloudflare\.com/[^[:space:]]+' /tmp/cf_login_raw.txt 2>/dev/null | head -1)
  if [ -n "$URL" ]; then
    echo "$URL" > "$URL_FILE"
    break
  fi
  sleep 1
done

if [ -f "$URL_FILE" ] && [ -s "$URL_FILE" ]; then
  URL=$(cat "$URL_FILE")
  echo ""
  echo "══════════════════════════════════════════════════"
  echo " ⚠️  НУЖНО АВТОРИЗОВАТЬ В БРАУЗЕРЕ:"
  echo ""
  echo " Открой эту ссылку:"
  echo " $URL"
  echo ""
  echo " Или Claude откроет её автоматически."
  echo "══════════════════════════════════════════════════"
  echo ""
  # Открываем в браузере автоматически
  open "$URL"
  echo "✅ Ссылка открыта в браузере."
  echo "   Нажми 'Authorize' на странице Cloudflare."
  echo ""
  echo "▶ Ожидаем авторизацию (до 120 сек)..."
  wait $CF_PID
  CF_EXIT=$?
  echo "   cloudflared login завершён (exit=$CF_EXIT)"
else
  echo "❌ URL не получен. Возможно cloudflared уже авторизован или ошибка."
  kill $CF_PID 2>/dev/null
  cat /tmp/cf_login_raw.txt | head -20
fi
echo ""

# Проверяем наличие cert.pem
if [ -f ~/.cloudflared/cert.pem ]; then
  echo "✅ ~/.cloudflared/cert.pem существует — авторизация прошла!"
else
  echo "⚠️  cert.pem не найден — авторизация не завершена. Повтори шаг 2."
  read -rp "Нажми Enter для выхода..."; exit 1
fi

# Шаг 3: создаём туннель spa
echo ""
echo "▶ Шаг 3/4: Создание туннеля 'spa'..."
if cloudflared tunnel list 2>/dev/null | grep -q "spa"; then
  echo "✅ Туннель 'spa' уже существует"
  TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep " spa" | awk '{print $1}' | head -1)
else
  cloudflared tunnel create spa 2>&1
  TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep " spa" | awk '{print $1}' | head -1)
  echo "✅ Туннель создан: $TUNNEL_ID"
fi
echo "   Tunnel ID: $TUNNEL_ID"
echo ""

# Шаг 4: конфиг
echo "▶ Шаг 4/4: Запись конфига..."
mkdir -p ~/.cloudflared

cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /Users/$(whoami)/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: spa.${TUNNEL_ID:0:8}.cfargotunnel.com
    service: http://localhost:8765
  - service: http_status:404
EOF

echo "✅ Конфиг: ~/.cloudflared/config.yml"

# Загружаем launchd агент
if [ -f ~/Documents/SPA_Claude/scripts/com.spa.cloudflared.plist ]; then
  cp ~/Documents/SPA_Claude/scripts/com.spa.cloudflared.plist ~/Library/LaunchAgents/
  launchctl unload ~/Library/LaunchAgents/com.spa.cloudflared.plist 2>/dev/null || true
  sleep 1
  launchctl load ~/Library/LaunchAgents/com.spa.cloudflared.plist
  sleep 2
  STATUS=$(launchctl list | grep "com.spa.cloudflared" | awk '{print $1}')
  if [ -n "$STATUS" ] && [ "$STATUS" != "-" ]; then
    echo "✅ cloudflared запущен (pid=$STATUS)"
  else
    echo "⚠️  cloudflared загружен, запустится автоматически"
  fi
fi

echo ""
echo "════════════════════════════════════════════════"
echo " ✅ Cloudflare tunnel настроен!"
echo "    Tunnel ID: $TUNNEL_ID"
echo "    Лог: $LOG"
echo "════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
