#!/usr/bin/env bash
# push_v1252.sh — MP-1252: 3-dimension strategy benchmark comparison system.
# Adds:
#   * spa_core/analytics/strategy_benchmark_tracker.py  (backtest/paper/lazy-Aave per strategy)
#   * spa_core/analytics/monthly_performance_report.py  (monthly SPA vs lazy-Aave report)
#   * tests/test_strategy_benchmark.py                  (37 tests)
#   * data/strategy_benchmark.json                      (snapshot artifact)
#   * data/monthly_reports/2026-06.json + .md           (first partial month)
# SECURITY: never pushes scripts/cf_install_token.command (contains rotated secret).
set -euo pipefail

REPO=/Users/yuriikulieshov/Documents/SPA_Claude
cd "$REPO"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден в Keychain (GITHUB_PAT_SPA). Запусти: bash setup_pat.sh"
  exit 1
fi

python3 push_to_github.py \
  --pat "$PAT" \
  --files \
    "$REPO/spa_core/analytics/strategy_benchmark_tracker.py" \
    "$REPO/spa_core/analytics/monthly_performance_report.py" \
    "$REPO/tests/test_strategy_benchmark.py" \
    "$REPO/data/strategy_benchmark.json" \
    "$REPO/data/monthly_reports/2026-06.json" \
    "$REPO/data/monthly_reports/2026-06.md" \
    "$REPO/scripts/push_v1252.sh" \
  --message "feat(MP-1252): 3D strategy benchmark (backtest/paper/lazy-Aave) + monthly report + 37 tests [skip ci]"

echo "✅ push_v1252 done"
