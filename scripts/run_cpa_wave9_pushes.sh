#!/usr/bin/env bash
# scripts/run_cpa_wave9_pushes.sh
# Wave 9 push orchestrator — sprints v10.99–v11.42 (MP-1523–1526)
# Run: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave9_pushes.sh
# Log: /tmp/wave9_push.log
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG="/tmp/wave9_push.log"

echo "=== SPA Wave 9 Push Orchestrator ===" | tee "$LOG"
echo "Sprints: v11.39 v11.40 v11.41 v11.42" | tee -a "$LOG"
echo "MPs:     MP-1523 MP-1524 MP-1525 MP-1526" | tee -a "$LOG"
echo "Root:    $REPO_ROOT" | tee -a "$LOG"
echo "Log:     $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# v11.39 — MP-1523 SPA Admin CLI
# ---------------------------------------------------------------------------
echo "--- [1/4] v11.39 — MP-1523 SPA Admin CLI ---" | tee -a "$LOG"
python3 -m unittest tests.test_spa_admin -v 2>&1 | tail -5 | tee -a "$LOG"
python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/spa_admin.py" \
    "$REPO_ROOT/tests/test_spa_admin.py" \
    "$REPO_ROOT/scripts/push_v1139.sh" \
  --message "Sprint v11.39 — MP-1523 SPA Admin CLI unified tool (25 tests)" \
  2>&1 | tee -a "$LOG"
echo "v11.39 ✅" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# v11.40 — MP-1524 System Health Check
# ---------------------------------------------------------------------------
echo "--- [2/4] v11.40 — MP-1524 System Health Check ---" | tee -a "$LOG"
python3 -m unittest tests.test_system_health_check -v 2>&1 | tail -5 | tee -a "$LOG"
python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/system_health_check.py" \
    "$REPO_ROOT/tests/test_system_health_check.py" \
    "$REPO_ROOT/scripts/push_v1140.sh" \
  --message "Sprint v11.40 — MP-1524 System health check diagnostic (20 tests)" \
  2>&1 | tee -a "$LOG"
echo "v11.40 ✅" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# v11.41 — MP-1525 Backup + Restore
# ---------------------------------------------------------------------------
echo "--- [3/4] v11.41 — MP-1525 Backup + Restore ---" | tee -a "$LOG"
python3 -m unittest tests.test_backup_restore -v 2>&1 | tail -5 | tee -a "$LOG"
python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/backup_spa_data.py" \
    "$REPO_ROOT/scripts/restore_spa_data.py" \
    "$REPO_ROOT/tests/test_backup_restore.py" \
    "$REPO_ROOT/scripts/push_v1141.sh" \
  --message "Sprint v11.41 — MP-1525 Backup + restore scripts (20 tests)" \
  2>&1 | tee -a "$LOG"
echo "v11.41 ✅" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# v11.42 — MP-1526 Wave 9 push script + CURRENT_STATE + KANBAN
# ---------------------------------------------------------------------------
echo "--- [4/4] v11.42 — MP-1526 Wave 9 orchestrator + CURRENT_STATE ---" | tee -a "$LOG"
python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave9_pushes.sh" \
    "$REPO_ROOT/_push_wave9.command" \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1142.sh" \
  --message "Sprint v11.42 — MP-1526 Wave 9 push script + CURRENT_STATE v11.42" \
  2>&1 | tee -a "$LOG"
echo "v11.42 ✅" | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "=== Wave 9 push COMPLETE ===" | tee -a "$LOG"
echo "Log: $LOG"
