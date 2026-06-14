#!/bin/bash
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files \
    spa_core/monitoring/__init__.py \
    spa_core/monitoring/uptime_monitor.py \
    docs/PLAYBOOK_v1.md \
    docs/DR_PROCEDURE_v1.md \
    spa_core/tests/test_uptime_monitor.py \
    KANBAN.json \
  --message "MP-211: 24/7 uptime monitor, incident playbook v1, DR procedure (<4h RTO)"
echo ""
echo "=== Push complete. Press Enter to close ==="
read
