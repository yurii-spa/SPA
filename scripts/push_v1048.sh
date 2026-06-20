#!/bin/bash
# scripts/push_v1048.sh
# MP-1432 (v10.48): Atomic migration execution+adapters + completion tests
# Adapters migrated: adapter_registry, apy_aggregator, fluid_fusdc_adapter, sky_susds_feed
# Tests: tests/test_atomic_migration_complete.py (34 tests, all pass)
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/adapter_registry.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/apy_aggregator.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/fluid_fusdc_adapter.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/sky_susds_feed.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_atomic_migration_complete.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1048.sh \
  --message "Sprint v10.48 — MP-1432 Atomic migration execution+adapters, completion tests"

echo "v10.48 pushed"
