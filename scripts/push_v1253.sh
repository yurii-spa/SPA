#!/usr/bin/env bash
# push_v1253.sh — Dashboard v4.0 "Full Analytics Suite".
# Integrates tonight's autonomous-session data sources into index.html:
#   * NEW Risk tab           — stress test scenarios + VaR table (color-coded by % NAV)
#                              sources: data/stress_test_results.json, data/var_analytics_v2.json
#   * Backtest tab           — prefers data/backtest_results_real.json (real 365-day),
#                              adds "vs Lazy Aave" color-coded alpha column + benchmark row
#   * Strategies tab         — NEW Portfolio Optimizer block (optimal vs live allocation,
#                              projected APY) from data/optimizer_results.json
#   * Protocols tab          — NEW "Hack Loss" (per-protocol exposure) + "Kelly Weight" columns
#   * Header                 — version bump v3.5 → v4.0 · "Full Analytics Suite"
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
    "$REPO/index.html" \
    "$REPO/scripts/push_v1253.sh" \
  --message "feat(dashboard v4.0): Full Analytics Suite — Risk tab (stress+VaR), real 365d backtest +alpha, optimizer block, protocols hack-loss/kelly cols [skip ci]"

echo "✅ push_v1253 done"
