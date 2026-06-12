#!/bin/bash
# MP-016b: install plist + send test + push to GitHub
# Запусти двойным кликом из Finder (или из Терминала: bash _push_mp016b.command)
set -e
cd "$(dirname "$0")"
REPO="$(pwd)"
echo "=== SPA MP-016b setup ==="
echo "Repo: $REPO"
echo ""

# 1. Install launchd plist
PLIST_SRC="$REPO/com.spa.bot_commands.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.spa.bot_commands.plist"

echo "--- 1/3: Installing launchd plist ---"
if launchctl list com.spa.bot_commands &>/dev/null; then
    echo "  Unloading existing com.spa.bot_commands..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "  ✅ com.spa.bot_commands loaded (every 5 min)"
echo ""

# 2. Send startup test message
echo "--- 2/3: Sending Telegram startup test ---"
python3 -c "
import sys; sys.path.insert(0, '.')
from spa_core.alerts import alert_manager
ok = alert_manager.send_startup_test()
print('  ✅ Test message sent!' if ok else '  ⚠️  send failed (check Keychain / network)')
"
echo ""

# 3. Push to GitHub
echo "--- 3/3: Pushing to GitHub ---"
python3 push_to_github.py \
  --files \
    spa_core/alerts/bot_commands.py \
    spa_core/alerts/alert_manager.py \
    spa_core/alerts/telegram_client.py \
    spa_core/paper_trading/cycle_runner.py \
    spa_core/tests/test_bot_commands.py \
    com.spa.bot_commands.plist \
    KANBAN.json \
  --message "feat(MP-016b): Telegram inline keyboard buttons + period returns in daily report ✅"
echo ""
echo "=== All done! ==="
echo "Press Enter to close..."
read
