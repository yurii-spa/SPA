#!/usr/bin/env bash
cd ~/Documents/SPA_Claude
echo "=== SPA Telegram Test ==="
python3 << 'PYEOF'
import subprocess, sys

try:
    token = subprocess.check_output(['security', 'find-generic-password', '-s', 'TELEGRAM_BOT_TOKEN_SPA', '-w'], stderr=subprocess.DEVNULL).decode().strip()
    chat_id = subprocess.check_output(['security', 'find-generic-password', '-s', 'TELEGRAM_CHAT_ID_SPA', '-w'], stderr=subprocess.DEVNULL).decode().strip()
    print(f"✅ BOT_TOKEN found: ...{token[-8:]}")
    print(f"✅ CHAT_ID found: {chat_id}")
except Exception as e:
    print(f"❌ Keychain error: {e}")
    sys.exit(1)

from spa_core.alerts.telegram_manager import TelegramManager
tm = TelegramManager()
result = tm.send(
    message="🧪 SPA Telegram test — 2026-06-20 23:17",
    title="spa_test_ping",
    category="test"
)
print(f"✅ Send result: {result}")
PYEOF
echo "=== Done ==="
read -p "Press Enter to close..."
