#!/usr/bin/env bash
# Push Sprint v11.05 — MP-1489 Chain allocator Ethereum/Base optimizer
# Usage: bash scripts/push_v1105.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Sprint v11.05 — MP-1489 Chain allocator Ethereum/Base optimizer ==="

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/analytics/chain_allocator.py" \
    "${REPO_ROOT}/tests/test_chain_allocator.py" \
  --message "Sprint v11.05 — MP-1489 Chain allocator Ethereum/Base optimizer (25 tests)"

echo "✅  v11.05 pushed."
