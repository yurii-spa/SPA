#!/usr/bin/env bash
# Push all sprints v11.03–v11.06 (MP-1487/1488/1489/1490) to GitHub.
# Run from project root:  bash scripts/push_v1103_v1106_all.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Pushing 4 sprints: v11.03 → v11.06 ==="

# v11.03 — MP-1487 Cross-chain yield comparator
echo ""
echo "--- v11.03 (MP-1487) ---"
python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/analytics/cross_chain_yield.py" \
    "${REPO_ROOT}/tests/test_cross_chain_yield.py" \
    "${REPO_ROOT}/scripts/push_v1103.sh" \
  --message "Sprint v11.03 — MP-1487 Cross-chain yield comparator (30 tests)"

# v11.04 — MP-1488 Unified gas monitor
echo ""
echo "--- v11.04 (MP-1488) ---"
python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/monitor/unified_gas_monitor.py" \
    "${REPO_ROOT}/tests/test_unified_gas_monitor.py" \
    "${REPO_ROOT}/scripts/push_v1104.sh" \
  --message "Sprint v11.04 — MP-1488 Unified gas monitor Ethereum+Base (25 tests)"

# v11.05 — MP-1489 Chain allocator
echo ""
echo "--- v11.05 (MP-1489) ---"
python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/analytics/chain_allocator.py" \
    "${REPO_ROOT}/tests/test_chain_allocator.py" \
    "${REPO_ROOT}/scripts/push_v1105.sh" \
  --message "Sprint v11.05 — MP-1489 Chain allocator Ethereum/Base optimizer (25 tests)"

# v11.06 — MP-1490 Dashboard panel + KANBAN
echo ""
echo "--- v11.06 (MP-1490) ---"
python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/landing/src/pages/dashboard.astro" \
    "${REPO_ROOT}/KANBAN.json" \
    "${REPO_ROOT}/scripts/push_v1106.sh" \
    "${REPO_ROOT}/scripts/push_v1103_v1106_all.sh" \
  --message "Sprint v11.06 — MP-1490 Cross-chain dashboard panel + KANBAN v11.06 done_count=1206"

echo ""
echo "✅  All 4 sprints pushed (v11.03 → v11.06)."
