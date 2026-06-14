#!/bin/bash
cd /Users/yuriikulieshov/Documents/SPA_Claude
cp SPA_Kanban.html index.html
git add -A
if ! git diff --staged --quiet; then
  git commit -m "Auto-update $(date '+%Y-%m-%d %H:%M')"
  git push origin main
fi
