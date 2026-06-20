#!/usr/bin/env bash
# Sprint v11.00 — MP-1484 Public API complete interface + docs
set -euo pipefail
cd "$(dirname "$0")/.."

python3 push_to_github.py \
  --files \
    spa_core/__init__.py \
    spa_core/version.py \
    docs/PUBLIC_API.md \
    tests/test_public_api.py \
    scripts/push_v1100.sh \
    KANBAN.json \
  --message "Sprint v11.00 — MP-1484 Public API complete interface + docs"
