#!/usr/bin/env bash
# scripts/push_v1085.sh
# MP-1469 (v10.85) — KANBAN health + sprint numbering + audit_status field
# Usage: bash scripts/push_v1085.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1085.sh" \
  --message "Sprint v10.85 — MP-1469 KANBAN health + audit status field"
