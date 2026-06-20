#!/usr/bin/env bash
# scripts/push_v1171.sh
# feat: smart_autopush.py (API-based, no git conflicts) replaces git_autopush.sh
# Files: scripts/smart_autopush.py, com.spa.autopush.plist,
#        install_smart_autopush.command, data/autopush_state.json
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== push_v1171: smart_autopush (API-based autopush) ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/smart_autopush.py" \
    "$REPO_ROOT/com.spa.autopush.plist" \
    "$REPO_ROOT/install_smart_autopush.command" \
    "$REPO_ROOT/data/autopush_state.json" \
    "$REPO_ROOT/scripts/push_v1171.sh" \
  --message "feat: smart_autopush.py (API-based, no git conflicts) replaces git_autopush.sh"

echo ""
echo "=== push_v1171.sh DONE ==="
