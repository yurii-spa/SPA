#!/usr/bin/env bash
# scripts/push_v1083.sh
# MP-1467 (v10.83) — SPAError Final Sweep + Audit Script
# Usage: bash scripts/push_v1083.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/spaerror_final_audit.py" \
    "$REPO_ROOT/tests/test_spaerror_complete.py" \
    "$REPO_ROOT/scripts/push_v1083.sh" \
  --message "Sprint v10.83 — MP-1467 SPAError final sweep + audit script"
