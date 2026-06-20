#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/tuner/parameter_optimizer.py" \
    "$REPO_ROOT/tests/test_parameter_optimizer.py" \
    "$REPO_ROOT/scripts/push_v1097.sh" \
  --message "Sprint v10.97 — MP-1481 Parameter optimizer S7/S11 (30 tests)"
