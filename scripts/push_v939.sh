#!/usr/bin/env bash
# scripts/push_v939.sh
# Sprint v9.39 — MP-1323 CPA integration test suite, 50 tests across full chain
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/tests/test_cpa_integration.py" \
  --message "Sprint v9.39 — MP-1323 CPA integration test suite, 50 tests across full chain"
