#!/usr/bin/env bash
# Push Sprint v10.19 — MP-1403 Analytics conformance checker
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/scripts/analytics_conformance.py" \
    "$REPO_ROOT/tests/test_analytics_conformance.py" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.19 — MP-1403 Analytics conformance checker, 30 tests"
