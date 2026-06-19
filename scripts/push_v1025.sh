#!/usr/bin/env bash
# scripts/push_v1025.sh
# MP-1409 (v10.25) — Evidence Auto-Calculator + 45 tests
# Usage: bash scripts/push_v1025.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/evidence_auto_calculator.py" \
    "$REPO_ROOT/tests/test_evidence_auto_calculator.py" \
    "$REPO_ROOT/scripts/push_v1025.sh" \
  --message "Sprint v10.25 — MP-1409 Evidence auto-calculator, 45 tests"
