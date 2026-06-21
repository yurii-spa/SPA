#!/usr/bin/env bash
# ONE-TIME SETUP — double-click this, then never touch it again.
# После этого все пуши идут автоматически каждый час.
set -e

REPO="$HOME/Documents/SPA_Claude"
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null)
if [ -z "$PAT" ]; then echo "❌ PAT not in Keychain"; read -p "Press Enter"; exit 1; fi

echo "=== Step 1: Push base.py + kanban.py + risk_policy.json ==="
cd "$REPO"
python3 push_to_github.py \
  --files spa_core/base.py spa_core/utils/kanban.py data/risk_policy.json \
  --message "fix: restore base.py + kanban.py + risk_policy.json [skip ci]" \
  --pat "$PAT"
echo ""

echo "=== Step 2: Install autopush daemon ==="
PLIST_SRC="$REPO/com.spa.autopush.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.spa.autopush.plist"
launchctl unload "$PLIST_DST" 2>/dev/null || true
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
launchctl start com.spa.autopush
echo "✅ Autopush daemon installed and started"
echo ""

echo "=== Step 3: Verify ==="
launchctl list | grep com.spa.autopush && echo "✅ Daemon running" || echo "⚠️ Check log"
sleep 4
tail -10 /tmp/spa_autopush.log 2>/dev/null || echo "(log will appear in a minute)"

echo ""
echo "✅ ALL DONE. Pushes are now fully automatic. Never need to do this again."
read -p "Press Enter to close..."
