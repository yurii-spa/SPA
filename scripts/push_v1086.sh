#!/usr/bin/env bash
# scripts/push_v1086.sh
# MP-1470 (v10.86) — Wave 8 push script + CURRENT_STATE v10.86
# Usage: bash scripts/push_v1086.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/scripts/run_cpa_wave8_pushes.sh" \
    "$REPO_ROOT/_push_wave8.command" \
    "$REPO_ROOT/scripts/push_v1086.sh" \
  --message "Sprint v10.86 — MP-1470 Wave 8 push script + CURRENT_STATE v10.86"
