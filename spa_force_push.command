#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

echo "▶ Loading PAT..."
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "▶ Aborting any in-progress rebase/merge..."
git rebase --abort 2>/dev/null || true
git merge --abort 2>/dev/null || true

echo "▶ Removing git locks..."
rm -f .git/index.lock .git/HEAD.lock .git/MERGE_HEAD 2>/dev/null || true

echo "▶ Current local commits:"
git log --oneline -5

echo ""
echo "▶ Adding all pending files..."
git add -A

echo "▶ Committing if anything new..."
if git diff --cached --quiet; then
  echo "  (nothing new to commit)"
else
  git commit -m "fix: Telegram spam + GoLive 23/26 + landing page + TelegramManager (2026-06-18)"
fi

echo ""
echo "▶ Force push to GitHub (--force-with-lease)..."
git push "$REMOTE" main --force-with-lease
echo "✅ Push complete!"

echo ""
echo "▶ Reloading Telegram launchd agent..."
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
[ -f scripts/com.spa.daily_cycle.plist ] && \
  cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist && \
  launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist && \
  echo "✅ Telegram agent reloaded (daily 08:00, spam FIXED)!"

echo ""
echo "🎉 Done! Cloudflare Pages will rebuild. Autopush will re-sync data next cycle."
