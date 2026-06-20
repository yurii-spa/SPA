#!/usr/bin/env bash
# Sprint v10.58 — MP-1442 GoLive final recalculation + progress report
# 20 tests: 20/20 pass | total score: 69→77/100 | gates: 18/20
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/tests/test_golive_final.py" \
    "$REPO_ROOT/docs/GOLIVE_PROGRESS_REPORT_20260619.md" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1057.sh" \
    "$REPO_ROOT/scripts/push_v1058.sh" \
  --message "Sprint v10.58 — MP-1442 GoLive final recalculation + progress report, 20 tests"
