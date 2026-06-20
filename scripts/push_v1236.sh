#!/usr/bin/env bash
# Sprint v12.36 — MP-1236 enhanced performance attribution & investor reporting.
# Pushes ONLY the explicitly listed files (absolute paths — relative paths
# collapse to basename in push_to_github.py). Never lists secrets / token files
# (e.g. scripts/cf_install_token.command).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/reporting/_perf_common.py" \
    "$REPO_ROOT/spa_core/reporting/performance_attributor.py" \
    "$REPO_ROOT/spa_core/reporting/tear_sheet_hf.py" \
    "$REPO_ROOT/spa_core/reporting/benchmark_comparator.py" \
    "$REPO_ROOT/tests/test_mp1236_attribution_reporting.py" \
    "$REPO_ROOT/scripts/push_v1236.sh" \
    "$REPO_ROOT/data/performance_attribution.json" \
    "$REPO_ROOT/data/tear_sheet.json" \
    "$REPO_ROOT/data/benchmark_comparison.json" \
  --message "Sprint v12.36 — MP-1236 perf attribution + HF tear sheet + benchmark comparator (53 tests)"
