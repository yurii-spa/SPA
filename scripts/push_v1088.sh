#!/usr/bin/env bash
# Sprint v10.88 — MP-1472: Atomic batch 9 data_pipeline+agents+tuner
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/agents/strategy_agent_v2.py" \
    "$REPO_ROOT/spa_core/agents/ceo_agent_v2.py" \
    "$REPO_ROOT/spa_core/agents/reporting_agent.py" \
    "$REPO_ROOT/spa_core/tests/test_strategy_agent_v2.py" \
    "$REPO_ROOT/spa_core/tests/test_ceo_agent_v2.py" \
    "$REPO_ROOT/scripts/push_v1088.sh" \
  --message "Sprint v10.88 — MP-1472 Atomic batch 9 data_pipeline+agents+tuner"
