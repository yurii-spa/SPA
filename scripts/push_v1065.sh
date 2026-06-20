#!/usr/bin/env bash
# Sprint v10.65 — MP-1449: SPAError Batch 5 — execution/ + safety/ layer
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/execution/eth_signer.py" \
    "$REPO_ROOT/spa_core/execution/engine_bridge.py" \
    "$REPO_ROOT/spa_core/execution/aave_v3_adapter.py" \
    "$REPO_ROOT/spa_core/execution/compound_v3_adapter.py" \
    "$REPO_ROOT/spa_core/execution/router.py" \
    "$REPO_ROOT/spa_core/execution/safe_tx_builder.py" \
    "$REPO_ROOT/spa_core/execution/wallet.py" \
    "$REPO_ROOT/spa_core/execution/adapters/morpho_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/yearn_v3_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/maple_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/euler_v2_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/sky_susds_adapter.py" \
    "$REPO_ROOT/spa_core/execution/adapters/pendle_pt_adapter.py" \
    "$REPO_ROOT/scripts/push_v1065.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.65 — MP-1449 SPAError Batch 5: execution/ layer (13 files, 0 raise ValueError)"
