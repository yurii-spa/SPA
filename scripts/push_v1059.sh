#!/usr/bin/env bash
# scripts/push_v1059.sh
# Sprint v10.59 — MP-1443: SPAError batch 3 — execution/ domain (6 files)
# All bare RuntimeError replaced with SourceError/ValidationError/ConfigError/SPAError
# Tests updated: phase2 tests for aave_v3 and compound_v3 updated to SourceError
# Test result: 251 passed (0 regressions vs pre-existing phase3 failures)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.59 — MP-1443 SPAError batch 3 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/execution/eth_signer.py" \
    "$REPO_ROOT/spa_core/execution/mev_protection.py" \
    "$REPO_ROOT/spa_core/execution/safe_tx_builder.py" \
    "$REPO_ROOT/spa_core/execution/aave_v3_adapter.py" \
    "$REPO_ROOT/spa_core/execution/compound_v3_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/morpho_adapter.py" \
    "$REPO_ROOT/spa_core/tests/test_aave_v3_adapter_phase2.py" \
    "$REPO_ROOT/spa_core/tests/test_compound_v3_adapter_phase2.py" \
    "$REPO_ROOT/scripts/push_v1059.sh" \
  --message "Sprint v10.59 — MP-1443 SPAError batch 3, 10 more files"

echo ""
echo "✅ Sprint v10.59 pushed"
