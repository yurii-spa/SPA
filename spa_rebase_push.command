#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

echo "▶ Loading PAT..."
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "▶ Removing any git locks..."
rm -f .git/index.lock .git/HEAD.lock .git/MERGE_HEAD .git/rebase-merge/head-name 2>/dev/null || true

echo "▶ Committing all local changes first..."
git add -A
if git diff --cached --quiet; then
  echo "  (nothing to commit)"
else
  git commit -m "fix: Telegram spam + GoLive + landing page (2026-06-18)"
fi

echo "▶ Pull with rebase..."
git pull "$REMOTE" main --rebase --no-autostash

echo "▶ Pushing to GitHub..."
git push "$REMOTE" main
echo "✅ Push complete!"

echo ""
echo "▶ Reloading Telegram agent (daily 08:00)..."
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
[ -f scripts/com.spa.daily_cycle.plist ] && \
  cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist && \
  launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist && \
  echo "✅ Telegram agent reloaded!"

echo ""
echo "🎉 Done! Cloudflare Pages will rebuild."
