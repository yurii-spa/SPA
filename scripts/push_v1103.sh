#!/usr/bin/env bash
# Push Sprint v11.03 — MP-1487 Cross-chain yield comparator
# Usage: bash scripts/push_v1103.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Sprint v11.03 — MP-1487 Cross-chain yield comparator ==="

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/analytics/cross_chain_yield.py" \
    "${REPO_ROOT}/tests/test_cross_chain_yield.py" \
  --message "Sprint v11.03 — MP-1487 Cross-chain yield comparator (30 tests)"

echo "✅  v11.03 pushed."
