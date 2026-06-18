#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

echo "▶ Loading PAT..."
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "❌ PAT not found in Keychain"
  read -p "Press Enter to close..."
  exit 1
fi

REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "▶ Stashing local changes..."
git stash --include-untracked

echo "▶ Pulling remote changes (rebase)..."
git pull "$REMOTE" main --rebase

echo "▶ Restoring stashed changes..."
git stash pop || echo "(No stash to pop)"

echo "▶ Adding pending files..."
git add -A

echo "▶ Committing..."
if git diff --cached --quiet; then
  echo "Nothing new to commit"
else
  git commit -m "fix: Telegram spam + GoLive 23/26 + landing page (2026-06-18)"
fi

echo "▶ Pushing to GitHub..."
git push "$REMOTE" main
echo "✅ Push complete!"

echo ""
echo "▶ Reloading Telegram launchd agent..."
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
if [ -f scripts/com.spa.daily_cycle.plist ]; then
  cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist
  launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist
  echo "✅ Telegram agent reloaded (daily 08:00)!"
else
  echo "⚠️ com.spa.daily_cycle.plist not found, skipping"
fi

echo ""
echo "🎉 All done! Cloudflare Pages will rebuild automatically."
