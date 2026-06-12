#!/bin/bash
# Push MP-310 + MP-311 to GitHub.
# Run once from Finder (double-click) or: bash _push_mp310_311.command
set -e
cd ~/Documents/SPA_Claude

FILES=""
for f in \
  spa_core/audit/__init__.py \
  spa_core/audit/audit_trail.py \
  spa_core/scheduler/__init__.py \
  spa_core/scheduler/loop_scheduler.py \
  spa_core/scheduler/adapter_watchdog.py \
  spa_core/paper_trading/cycle_runner.py \
  spa_core/tests/test_audit_trail.py \
  spa_core/tests/test_loop_scheduler.py \
  spa_core/tests/test_adapter_watchdog.py \
  KANBAN.json
do
  [ -f "$f" ] && FILES="$FILES $f"
done

echo "Files to push:"
for f in $FILES; do echo "  $f"; done
echo ""

python3 push_to_github.py --files $FILES \
  --message "feat: MP-310 decision audit trail + MP-311 3-loop scheduler + adapter watchdog"
