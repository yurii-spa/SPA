#!/usr/bin/env bash
# Sprint v12.73 — ADR-050 Aerodrome thin-pool: $20M LP TVL depth floor + S41 risk flag
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/adapters/aerodrome_usdc_adapter.py" \
    "${REPO_ROOT}/spa_core/strategies/s41_amm_stable_yield.py" \
    "${REPO_ROOT}/docs/adr/ADR-050-aerodrome-thin-pool.md" \
    "${REPO_ROOT}/tests/test_aerodrome_velodrome.py" \
    "${REPO_ROOT}/scripts/push_v1273.sh" \
  --message "Sprint v12.73 — ADR-050 Aerodrome thin-pool: \$20M LP TVL depth floor, pool_depth_check, S41 15%->5% risk flag, 6 adapter + 2 S41 tests"
