#!/usr/bin/env bash
# scripts/push_v1257.sh — push S42 Crisis Refuge + S43 Volatility-Adjusted Yield
#
# MP-1257: two Sky-sUSDS-anchored defensive strategies.
#   S42 Crisis Refuge        — static 100% T1 refuge book, crisis-triggered.
#   S43 Volatility-Adjusted  — APY/daily-vol water-filling under RiskPolicy caps.
#
# PAT is read at runtime from the macOS Keychain by push_to_github.py
# (security find-generic-password -s GITHUB_PAT_SPA -w). NEVER hardcode tokens.
# SECURITY: this script never touches scripts/cf_install_token.command.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FILES=(
  "$REPO_ROOT/spa_core/strategies/s42_crisis_refuge.py"
  "$REPO_ROOT/spa_core/strategies/s43_vol_adjusted.py"
  "$REPO_ROOT/tests/test_s42_s43_defensive.py"
  "$REPO_ROOT/scripts/push_v1257.sh"
)

python3 push_to_github.py \
  --files "${FILES[@]}" \
  --message "feat(MP-1257): S42 Crisis Refuge + S43 Vol-Adjusted Yield (Sky sUSDS defensive), 41 tests [skip ci]"
