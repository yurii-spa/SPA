#!/bin/bash
COMMIT_MSG="fix(cycle): daily_limits_check list→dict, fix 3 failing analytics modules"
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found"; exit 1; }
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/analytics_pipeline.py \
  --message "$COMMIT_MSG"
