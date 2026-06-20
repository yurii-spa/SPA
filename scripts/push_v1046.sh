#!/bin/bash
# scripts/push_v1046.sh
# MP-1430 (v10.46): BaseAnalytics Phase 3 Batch B + Final Summary
# Batch B: source_acquisition_tracker, stablecoin_yield_optimizer, t1_data_verifier
# Artifacts: baseanalytics_migration_summary.py, test_phase3_migration.py
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/source_acquisition_tracker.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/stablecoin_yield_optimizer.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/t1_data_verifier.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/baseanalytics_migration_summary.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_phase3_migration.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1046.sh \
  --message "Sprint v10.46 — MP-1430 BaseAnalytics Phase 3 batch B + final summary"

echo "✅ v10.46 pushed"
