#!/usr/bin/env bash
# Push Sprint v11.04 — MP-1488 Unified gas monitor Ethereum+Base
# Usage: bash scripts/push_v1104.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Sprint v11.04 — MP-1488 Unified gas monitor Ethereum+Base ==="

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/monitor/unified_gas_monitor.py" \
    "${REPO_ROOT}/tests/test_unified_gas_monitor.py" \
  --message "Sprint v11.04 — MP-1488 Unified gas monitor Ethereum+Base (25 tests)"

echo "✅  v11.04 pushed."
