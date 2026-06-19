#!/usr/bin/env bash
# Sprint v9.66 — MP-1350 Source acquisition tracker 12 protocols, 51 tests
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/analytics/source_acquisition_tracker.py" \
    "${REPO_ROOT}/tests/test_source_acquisition_tracker.py" \
    "${REPO_ROOT}/scripts/push_v966.sh" \
    "${REPO_ROOT}/KANBAN.json" \
  --message "Sprint v9.66 — MP-1350 Source acquisition tracker 12 protocols, 51 tests"
