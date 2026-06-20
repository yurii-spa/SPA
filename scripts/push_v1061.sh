#!/usr/bin/env bash
# scripts/push_v1061.sh
# Sprint v10.61 — MP-1445: Atomic Batch 4 — 16 files migrated to atomic_save
# Test fix: test_loop_scheduler.py patches updated to new binding
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.61 — MP-1445 Atomic Batch 4 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/tuner/allocation_tuner.py" \
    "$REPO_ROOT/spa_core/reporting/tear_sheet.py" \
    "$REPO_ROOT/spa_core/reporting/daily_report.py" \
    "$REPO_ROOT/spa_core/reporting/strategy_summary.py" \
    "$REPO_ROOT/spa_core/reporting/portal_data.py" \
    "$REPO_ROOT/spa_core/strategies/runner.py" \
    "$REPO_ROOT/spa_core/strategies/comparator.py" \
    "$REPO_ROOT/spa_core/scheduler/loop_scheduler.py" \
    "$REPO_ROOT/spa_core/scheduler/adapter_watchdog.py" \
    "$REPO_ROOT/spa_core/agents/alpha_agent.py" \
    "$REPO_ROOT/spa_core/agents/risk_sentinel.py" \
    "$REPO_ROOT/spa_core/agents/protocol_research_agent.py" \
    "$REPO_ROOT/spa_core/agents/reporting_agent.py" \
    "$REPO_ROOT/spa_core/agents/incident_commander.py" \
    "$REPO_ROOT/spa_core/adapter_sdk/registry.py" \
    "$REPO_ROOT/spa_core/alerts/bot_commands.py" \
    "$REPO_ROOT/spa_core/tests/test_loop_scheduler.py" \
    "$REPO_ROOT/scripts/push_v1061.sh" \
  --message "Sprint v10.61 — MP-1445 Atomic batch 4, 16 files migrated to atomic_save"

echo ""
echo "✅ Sprint v10.61 pushed"
