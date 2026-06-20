#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/family_fund/kyc_manager.py" \
    "$REPO_ROOT/tests/test_kyc_manager.py" \
    "$REPO_ROOT/scripts/push_v1096.sh" \
  --message "Sprint v10.96 — MP-1480 Family Fund KYC workflow (25 tests)"
