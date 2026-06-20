#!/usr/bin/env bash
# scripts/push_v1131.sh
# Sprint v11.31 — MP-1515 ADR-037/038/039/040 (walk-forward/MC/circuit-breaker/demotion)
# Commit: "Sprint v11.31 — MP-1515 ADR-037/038/039/040 (walk-forward/MC/circuit-breaker/demotion)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.31 — MP-1515 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_adr_documents -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/docs/adr/ADR-037-walk-forward-validation.md" \
    "$REPO_ROOT/docs/adr/ADR-038-monte-carlo-robustness.md" \
    "$REPO_ROOT/docs/adr/ADR-039-drawdown-circuit-breaker.md" \
    "$REPO_ROOT/docs/adr/ADR-040-strategy-demotion-policy.md" \
    "$REPO_ROOT/tests/test_adr_documents.py" \
    "$REPO_ROOT/scripts/push_v1131.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.31 — MP-1515 ADR-037/038/039/040 (walk-forward/MC/circuit-breaker/demotion)"

echo ""
echo "=== push_v1131.sh DONE ==="
