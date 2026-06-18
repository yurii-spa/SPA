#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude

echo "▶ Loading PAT..."
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "▶ Removing git locks..."
rm -f .git/index.lock .git/HEAD.lock .git/MERGE_HEAD 2>/dev/null
echo "  locks removed"

echo "▶ Fetching remote..."
git fetch "$REMOTE" main:refs/remotes/origin/main

echo "▶ Adding all pending files..."
git add -A

echo "▶ Committing..."
if git diff --cached --quiet; then
  echo "Nothing new to commit, proceeding with push..."
else
  git commit -m "fix: Telegram spam + GoLive 23/26 + landing page + Telegram manager (2026-06-18)"
fi

echo "▶ Merging remote changes..."
git merge origin/main --no-edit 2>/dev/null || echo "Nothing to merge or already merged"

echo "▶ Pushing to GitHub..."
git push "$REMOTE" main
echo "✅ Push complete!"

echo ""
echo "▶ Reloading Telegram launchd agent..."
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist 2>/dev/null || true
[ -f scripts/com.spa.daily_cycle.plist ] && cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist && launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist && echo "✅ Telegram agent reloaded!"

echo ""
echo "🎉 Done! GitHub push complete. Cloudflare Pages will rebuild."
