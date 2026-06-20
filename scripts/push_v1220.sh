#!/usr/bin/env bash
# FIX 4 (P1) — Remove live HTTP fetches from risk layer (AUDIT-011)
# Fixes: scoring_engine.py _fetch_defillama_protocols now reads defi_llama_cache.json
#         (local cache) instead of making live urllib calls; bootstrap fallback if absent
#         test_p1_risk_no_network.py (10 tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/risk/scoring_engine.py" \
    "${REPO_ROOT}/tests/test_p1_risk_no_network.py" \
    "${REPO_ROOT}/scripts/push_v1220.sh" \
  --message "FIX-P1 AUDIT-011: scoring_engine reads local cache only — no live HTTP from risk layer"
