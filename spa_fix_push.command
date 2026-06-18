#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

echo "▶ Loading PAT..."
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "❌ PAT not found in Keychain"
  exit 1
fi

REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "▶ Pulling remote changes (rebase)..."
git pull "$REMOTE" main --rebase

echo "▶ Pushing to GitHub..."
git push "$REMOTE" main
echo "✅ Push complete!"

echo ""
echo "▶ Reloading Telegram launchd agent..."
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
echo "✅ Telegram agent reloaded!"

echo ""
echo "🎉 All done! Cloudflare Pages will rebuild automatically."
