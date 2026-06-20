#!/usr/bin/env bash
# Sprint v10.68 — MP-1452: Tests for next 5 untested atomic modules + migration
# Modules: budget, ceo_agent_v2, strategy_agent_v2, refresh_agent_summaries, json_compat
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/tests/test_budget.py" \
    "$REPO_ROOT/tests/test_ceo_agent_v2.py" \
    "$REPO_ROOT/tests/test_strategy_agent_v2.py" \
    "$REPO_ROOT/tests/test_refresh_agent_summaries.py" \
    "$REPO_ROOT/tests/test_json_compat.py" \
    "$REPO_ROOT/spa_core/agent_runtime/budget.py" \
    "$REPO_ROOT/spa_core/utils/refresh_agent_summaries.py" \
    "$REPO_ROOT/spa_core/persistence/json_compat.py" \
    "$REPO_ROOT/scripts/push_v1068.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.68 — MP-1452 Tests + atomic migration next 5 modules (83 tests GREEN)"
