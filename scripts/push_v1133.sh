#!/usr/bin/env bash
# scripts/push_v1133.sh
# Sprint v11.33 — MP-1517 Compliance + AML/KYC policy docs
# Commit: "Sprint v11.33 — MP-1517 Compliance + AML/KYC policy docs"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.33 — MP-1517 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_compliance_docs -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/docs/COMPLIANCE_POLICY.md" \
    "$REPO_ROOT/docs/RISK_DISCLOSURE.md" \
    "$REPO_ROOT/tests/test_compliance_docs.py" \
    "$REPO_ROOT/scripts/push_v1133.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.33 — MP-1517 Compliance + AML/KYC policy docs"

echo ""
echo "=== push_v1133.sh DONE ==="
