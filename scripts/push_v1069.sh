#!/usr/bin/env bash
# MP-1453 (v10.69) — Atomic batch 6: migrate all remaining modules WITH tests
# Push script — run from repo root
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FILES=$(git -C "$ROOT" diff --name-only HEAD | grep -v '^\\.claude\|^\\.github\|^CURRENT_STATE\|^KANBAN\|^data/' | sort)
FILE_ARGS=()
while IFS= read -r f; do
  FILE_ARGS+=("$ROOT/$f")
done <<< "$FILES"

python3 "$ROOT/push_to_github.py" \
  --files "${FILE_ARGS[@]}" \
  --message "Sprint v10.69 — MP-1453 Atomic batch 6: migrate all remaining modules WITH tests

- Replaced tempfile.mkstemp+json.dump+os.replace with atomic_save() across ~300 production modules
- Restored import tempfile in 338 test/prod files where cleanup over-removed it
- Fixed 211 production files where earlier buggy migration ate def/class definitions after mkstemp blocks
- strategy_summary.py: restored _atomic_write as thin wrapper (backward-compat with tests)
- All 781 changed production+utility files verified: 0 syntax errors, 0 missing symbols
- Pre-existing test failures unchanged: fastapi, PositionSizingEngine, KeyError:'id' in ranking"

echo "✓ push_v1069 done"
