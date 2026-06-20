#!/bin/bash
# push_v1230.sh — push the advanced risk-analytics v2 module set.
#
# Pushes ONLY the explicitly-listed new files via push_to_github.py
# (PAT read at runtime from macOS Keychain — never embedded here).
#
# SECURITY: scripts/cf_install_token.command must NEVER be pushed. This
# script uses an explicit allow-list (no wildcards) and a hard guard that
# aborts if any forbidden path sneaks into the list.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_DIR"

# Explicit absolute-path allow-list (CLAUDE.md: relative paths collapse to basename).
FILES=(
  "$PROJECT_DIR/spa_core/risk/var_calculator.py"
  "$PROJECT_DIR/spa_core/risk/stress_tester.py"
  "$PROJECT_DIR/spa_core/risk/correlation_tracker.py"
  "$PROJECT_DIR/tests/test_risk_analytics_v2.py"
  "$PROJECT_DIR/scripts/push_v1230.sh"
)

# Hard guard: never push the cloudflare install-token script.
FORBIDDEN="cf_install_token.command"
for f in "${FILES[@]}"; do
  case "$f" in
    *"$FORBIDDEN"*)
      echo "ABORT: refusing to push forbidden file: $f" >&2
      exit 1
      ;;
  esac
  if [ ! -f "$f" ]; then
    echo "ABORT: missing file: $f" >&2
    exit 1
  fi
done

python3 push_to_github.py \
  --files "${FILES[@]}" \
  --message "feat(risk): advanced risk analytics v2 — VaR/stress/correlation (v12.30)"
