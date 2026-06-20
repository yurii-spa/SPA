#!/usr/bin/env bash
# _push_wave9.command — Double-click to push Wave 9 (v11.39–v11.42)
# Sprints: MP-1523 SPA Admin CLI + MP-1524 Health Check + MP-1525 Backup/Restore + MP-1526 Wave 9 push
cd "$(dirname "$0")"
bash scripts/run_cpa_wave9_pushes.sh 2>&1 | tee /tmp/wave9_push.log
echo ""
echo "=== Wave 9 done. Log: /tmp/wave9_push.log ==="
read -p "Press Enter to close..."
