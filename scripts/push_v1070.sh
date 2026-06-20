#!/usr/bin/env bash
# MP-1454 (v10.70) — Atomic coverage dashboard + KANBAN update
# Push script — run from repo root
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$ROOT/push_to_github.py" \
  --files \
    "$ROOT/docs/ATOMIC_MIGRATION_STATUS.md" \
    "$ROOT/KANBAN.json" \
    "$ROOT/scripts/push_v1069.sh" \
    "$ROOT/scripts/push_v1070.sh" \
  --message "Sprint v10.70 — MP-1454 Atomic coverage dashboard + KANBAN update

- docs/ATOMIC_MIGRATION_STATUS.md: atomic migration status (437 files using atomic_save,
  4 deferred no-test files, 18 documented exceptions, 99.1% effective coverage)
- KANBAN.json: done_count 1228->1232 (+4 for MP-1451/1452/1453/1454), sprint note added
- scripts/push_v1069.sh + push_v1070.sh: push orchestrators for both sprints"

echo "✓ push_v1070 done"
