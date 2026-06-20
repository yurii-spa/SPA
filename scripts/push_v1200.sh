#!/usr/bin/env bash
# push_v1200.sh — P0 audit fixes: paper_start_date honesty + CURRENT_STATE golive sync
# Changes: cycle_runner.py + readiness_checker.py + checklist.py (2026-05-20→2026-06-10),
#          test_cycle_runner.py assertions, CURRENT_STATE.md (25/26 NOT READY, не 26/26)
set -euo pipefail

REPO=/Users/yuriikulieshov/Documents/SPA_Claude
cd "$REPO"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден в Keychain (GITHUB_PAT_SPA). Запусти: bash setup_pat.sh"
  exit 1
fi

python3 push_to_github.py \
  --pat "$PAT" \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/golive/readiness_checker.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/golive/checklist.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_cycle_runner.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/CURRENT_STATE.md \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1200.sh \
  --message "fix(track): paper_start_date 2026-06-10, CURRENT_STATE golive sync 25/26 v1200"

echo "✅ push_v1200 done"
