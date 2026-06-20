#!/usr/bin/env bash
# scripts/push_v1226.sh
# Sprint v12.26 — MP-1576..1580: smarter & more autonomous cycle runner.
#
#   MP-1576  Adaptive cycle frequency       spa_core/paper_trading/adaptive_scheduler.py
#   MP-1577  Smart rebalance trigger (RT-05) spa_core/paper_trading/rebalance_trigger.py
#   MP-1578  Daily performance summary agent spa_core/agents/daily_summary_agent.py
#   MP-1579  Anomaly detector                spa_core/monitoring/anomaly_detector.py
#   MP-1580  KANBAN completion metrics       spa_core/reporting/kanban_metrics.py
#   + cycle_runner._run_smart_modules wiring + KANBAN.json
#
# Run: bash ~/Documents/SPA_Claude/scripts/push_v1226.sh
# Log: /tmp/push_v1226.log
#
# SECURITY: never pushes scripts/cf_install_token.command (or any *token*.command).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG="/tmp/push_v1226.log"

echo "=== SPA Sprint v12.26 Push (MP-1576..1580) ===" | tee "$LOG"
echo "Root: $REPO_ROOT" | tee -a "$LOG"
echo "Log:  $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# Pre-flight: run the new test suites (must be green before pushing)
# ---------------------------------------------------------------------------
echo "--- Pre-flight: 104 new tests ---" | tee -a "$LOG"
python3 -m unittest \
  spa_core.tests.test_adaptive_scheduler \
  spa_core.tests.test_rebalance_trigger \
  spa_core.tests.test_daily_summary_agent \
  spa_core.tests.test_anomaly_detector \
  spa_core.tests.test_kanban_metrics \
  2>&1 | tail -4 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# Files to push (absolute paths — push_to_github.py collapses relative paths)
# ---------------------------------------------------------------------------
FILES=(
  # Improvement 1 — adaptive scheduler
  "$REPO_ROOT/spa_core/paper_trading/adaptive_scheduler.py"
  "$REPO_ROOT/spa_core/tests/test_adaptive_scheduler.py"
  # Improvement 2 — smart rebalance trigger (extended in place)
  "$REPO_ROOT/spa_core/paper_trading/rebalance_trigger.py"
  "$REPO_ROOT/spa_core/tests/test_rebalance_trigger.py"
  # Improvement 3 — daily summary agent
  "$REPO_ROOT/spa_core/agents/daily_summary_agent.py"
  "$REPO_ROOT/spa_core/tests/test_daily_summary_agent.py"
  # Improvement 4 — anomaly detector
  "$REPO_ROOT/spa_core/monitoring/anomaly_detector.py"
  "$REPO_ROOT/spa_core/tests/test_anomaly_detector.py"
  # Improvement 5 — KANBAN completion metrics
  "$REPO_ROOT/spa_core/reporting/kanban_metrics.py"
  "$REPO_ROOT/spa_core/tests/test_kanban_metrics.py"
  # Wiring + board
  "$REPO_ROOT/spa_core/paper_trading/cycle_runner.py"
  "$REPO_ROOT/KANBAN.json"
  # this push script
  "$REPO_ROOT/scripts/push_v1226.sh"
)

echo "--- Pushing ${#FILES[@]} files ---" | tee -a "$LOG"
python3 push_to_github.py \
  --files "${FILES[@]}" \
  --message "Sprint v12.26 — MP-1576..1580 smarter autonomous cycle (adaptive cadence, smart rebalance RT-05, daily summary agent, anomaly detector, KANBAN metrics) +104 tests [skip ci]" \
  2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "v12.26 ✅ done" | tee -a "$LOG"
