#!/usr/bin/env bash
# scripts/push_v1084.sh
# MP-1468 (v10.84) — Test coverage gaps: top 5 critical untested modules
# Usage: bash scripts/push_v1084.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/tests/test_drawdown_attribution_coverage.py" \
    "$REPO_ROOT/tests/test_capm_decomposition_coverage.py" \
    "$REPO_ROOT/tests/test_regime_detector_coverage.py" \
    "$REPO_ROOT/tests/test_monthly_report_coverage.py" \
    "$REPO_ROOT/tests/test_risk_contribution_coverage.py" \
    "$REPO_ROOT/scripts/push_v1084.sh" \
  --message "Sprint v10.84 — MP-1468 Test coverage gaps top 5 critical modules"
