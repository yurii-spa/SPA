#!/bin/bash
# Пуш фиксов:
# 1. cycle_runner: seed=False для equity_curve, rebalance threshold $200
# 2. data/equity_curve_daily.json: 11 реальных bar с 2026-06-10→2026-06-20

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден в Keychain (ключ: GITHUB_PAT_SPA)"
  echo "   Ротация: bash setup_pat.sh"
  exit 1
fi

echo "→ Пушим исправления бага equity_curve + rebalance threshold..."
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/paper_trading/cycle_runner.py" \
    "$REPO_ROOT/data/equity_curve_daily.json" \
  --message "fix: equity_curve real bars seed=False (Jun10-20) + rebalance threshold \$200 paper mode" \
  --pat "$PAT"

echo "✓ Push завершён"
