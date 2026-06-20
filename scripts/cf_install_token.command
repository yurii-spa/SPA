#!/bin/bash
# cf_install_token.command — устанавливает cloudflared через Tunnel Token (без cloudflared tunnel login)
# ⚠️  НЕ ПУШИТЬ В GITHUB — содержит Tunnel Token!
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/cf_token_setup_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

# ── Tunnel Token (получен из Cloudflare Zero Trust → Connectors → spa) ────────
CF_TOKEN="eyJhIjoiYjY1MGJkZDMxOGI1YTBkYTcwZDU5ZTlmYzM3MmI3MjMiLCJ0IjoiM2Q4MjEyNmEtNGVlOC00YmM3LWFmMmMtOWJiMTQ3YzI3NGUwIiwicyI6Ik1EY3pNRFl6WkdNdFpXVmpNUzAwWkRZeUxUaG1ORFV0TVdRM09HWmlOelF4T0dFdyJ9"
TUNNEL_NAME="spa"

echo "════════════════════════════════════════════════"
echo " SPA — Cloudflare Tunnel Setup (Token method)"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""

# ── Шаг 1: Установка cloudflared ──────────────────────────────────────────────
echo "▶ Шаг 1/4: Проверка cloudflared..."
if which cloudflared >/dev/null 2>&1; then
  echo "✅ cloudflared уже установлен: $(cloudflared --version 2>&1 | head -1)"
else
  echo "   Устанавливаем через brew..."
  brew install cloudflared
  CF_EXIT=$?
  if [ $CF_EXIT -ne 0 ]; then
    echo "❌ brew install cloudflared завершился с ошибкой ($CF_EXIT)"
    read -rp "Нажми Enter для выхода..."; exit 1
  fi
  echo "✅ cloudflared установлен: $(cloudflared --version 2>&1 | head -1)"
fi
CF_BIN=$(which cloudflared)
echo "   Путь: $CF_BIN"
echo ""

# ── Шаг 2: Сохранение токена в Keychain ───────────────────────────────────────
echo "▶ Шаг 2/4: Сохранение токена в Keychain..."
# Удаляем старый (если есть) и записываем новый
security delete-generic-password -s "CF_TUNNEL_TOKEN_SPA" -a "$USER" 2>/dev/null || true
security add-generic-password -s "CF_TUNNEL_TOKEN_SPA" -a "$USER" -w "$CF_TOKEN"
KEYCHAIN_EXIT=$?
if [ $KEYCHAIN_EXIT -eq 0 ]; then
  echo "✅ Токен сохранён в Keychain (сервис: CF_TUNNEL_TOKEN_SPA)"
else
  echo "⚠️  Не удалось сохранить в Keychain (exit=$KEYCHAIN_EXIT) — продолжаем с inline токеном"
fi
echo ""

# ── Шаг 3: Создание run-wrapper скрипта ───────────────────────────────────────
echo "▶ Шаг 3/4: Создание wrapper скрипта..."
WRAPPER_DIR="$HOME/Library/Application Support/com.spa"
WRAPPER="$WRAPPER_DIR/run_cloudflared.sh"
mkdir -p "$WRAPPER_DIR"

# Пишем wrapper, который читает токен из Keychain
cat > "$WRAPPER" << 'WRAPPER_BODY'
#!/bin/bash
# run_cloudflared.sh — читает токен из Keychain, запускает cloudflared
TOKEN=$(security find-generic-password -s "CF_TUNNEL_TOKEN_SPA" -a "$USER" -w 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "$(date) ERROR: CF_TUNNEL_TOKEN_SPA not found in Keychain" >&2
  exit 1
fi
exec /opt/homebrew/bin/cloudflared tunnel run --token "$TOKEN"
WRAPPER_BODY
chmod +x "$WRAPPER"
echo "✅ Wrapper создан: $WRAPPER"
echo ""

# ── Шаг 4: LaunchAgent plist ───────────────────────────────────────────────────
echo "▶ Шаг 4/4: Настройка LaunchAgent com.spa.cloudflared..."
LOG_DIR="$HOME/Documents/SPA_Claude/logs"
PLIST_PATH="$HOME/Library/LaunchAgents/com.spa.cloudflared.plist"

cat > "$PLIST_PATH" << PLIST_BODY
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.cloudflared</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$HOME/Library/Application Support/com.spa/run_cloudflared.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/cloudflared.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/cloudflared.err</string>
    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
PLIST_BODY

echo "✅ Plist создан: $PLIST_PATH"

# Выгружаем старый агент (если был крашащий)
launchctl unload "$PLIST_PATH" 2>/dev/null || true
sleep 1

# Загружаем новый
launchctl load "$PLIST_PATH"
sleep 4

echo ""
echo "▶ Проверка статуса cloudflared..."
STATUS_LINE=$(launchctl list | grep "com.spa.cloudflared")
echo "   launchctl: $STATUS_LINE"

PID=$(echo "$STATUS_LINE" | awk '{print $1}')
if [ -n "$PID" ] && [ "$PID" != "-" ]; then
  echo "✅ cloudflared запущен! PID=$PID"
else
  echo "⚠️  cloudflared загружен, PID пока нет — KeepAlive перезапустит автоматически"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ Cloudflare Tunnel установлен!"
echo ""
echo "   Туннель:   spa (cloudflare INACTIVE → станет HEALTHY)"
echo "   Dashboar:  dash.cloudflare.com → Networks → Connectors"
echo "   Logs:      ~/Documents/SPA_Claude/logs/cloudflared.log"
echo "   Keychain:  CF_TUNNEL_TOKEN_SPA"
echo ""
echo "   ⚠️  ДЛЯ ПУБЛИЧНОГО URL нужен домен на Cloudflare DNS!"
echo "   Зарегистрируй домен (платный или бесплатный) и добавь в"
echo "   Cloudflare, затем:"
echo "     Connectors → spa → Edit → Add public hostname:"
echo "       Subdomain: dashboard"
echo "       Domain: твой-домен.com"
echo "       Service: HTTP → localhost:8765"
echo ""
echo "   Лог установки: $LOG"
echo "════════════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
