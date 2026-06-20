#!/bin/bash
# scripts/atomic_migration_final_count.sh
# MP-1431/MP-1432: Atomic migration count report
# Tracks centralized atomic_save() adoption across spa_core/
set -e
cd ~/Documents/SPA_Claude

echo "=== Atomic Migration Status ==="
echo ""
echo "Files using atomic_save (non-test):" \
  $(grep -rn "from spa_core.utils.atomic import" spa_core/ --include="*.py" -l \
    | grep -v test | grep -v "__pycache__" | wc -l)

echo "Files still with local patterns (non-test, non-exempt):" \
  $(grep -rn "tempfile\.mkstemp" spa_core/ --include="*.py" -l \
    | grep -v test | grep -v "__pycache__" \
    | grep -v "spa_core/utils/atomic.py" \
    | grep -v "proof_of_track" | wc -l)

echo ""
echo "=== In-scope directories (migration batches 1-4) ==="
for dir in spa_core/paper_trading spa_core/safety spa_core/analytics \
           spa_core/backtesting spa_core/family_fund \
           spa_core/execution spa_core/adapters; do
  remaining=$(grep -rn "tempfile\.mkstemp" "$dir/" --include="*.py" -l \
    2>/dev/null | grep -v "__pycache__" | grep -v "proof_of_track" \
    | grep -v "atomic.py" | wc -l)
  migrated=$(grep -rn "from spa_core.utils.atomic import" "$dir/" --include="*.py" -l \
    2>/dev/null | grep -v test | grep -v "__pycache__" | wc -l)
  echo "  $dir: migrated=$migrated remaining=$remaining"
done

echo ""
echo "=== Exempt files (stdlib contract) ==="
echo "  spa_core/audit/proof_of_track.py (stdlib contract — tempfile allowed)"
echo "  spa_core/utils/atomic.py (implements atomic_save — tempfile allowed)"
