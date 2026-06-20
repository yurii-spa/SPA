#!/usr/bin/env bash
# Sprint v12.66 — Protocol risk map: per-adapter risk_score for all 32 registry
# adapters (T1<0.25 / T2 [0.25,0.60] / T3>0.60) + 10 completeness tests.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/risk/protocol_risk_map.py" \
    "${REPO_ROOT}/tests/test_risk_scoring_completeness.py" \
    "${REPO_ROOT}/data/protocol_risk_map.json" \
    "${REPO_ROOT}/scripts/push_v1266.sh" \
  --message "Sprint v12.66 — protocol_risk_map: per-adapter risk_score x32 adapters + 10 completeness tests"
