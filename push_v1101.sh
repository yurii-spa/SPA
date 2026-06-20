#!/usr/bin/env bash
# Sprint v11.01 — MP-1485 Error catalog complete + machine-readable catalog
set -euo pipefail
cd "$(dirname "$0")/.."

python3 push_to_github.py \
  --files \
    spa_core/utils/error_catalog.py \
    docs/ERROR_CODE_REFERENCE.md \
    tests/test_error_catalog.py \
    scripts/push_v1101.sh \
    KANBAN.json \
  --message "Sprint v11.01 — MP-1485 Error catalog complete + machine-readable catalog"
