#!/bin/bash
# push_v1239.sh — push the v12.05 full KANBAN state synchronization.
#
# Pushes ONLY the explicitly-listed files via push_to_github.py
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
  "$PROJECT_DIR/KANBAN.json"
  "$PROJECT_DIR/CURRENT_STATE.md"
  "$PROJECT_DIR/scripts/push_v1239.sh"
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
  --message "chore(kanban): full state sync v12.05 — done_count 1286, +24 tickets, 32 synced from code"
