#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/scripts/validate_pg_schema.py" \
    "$REPO_ROOT/tests/test_pg_schema.py" \
    "$REPO_ROOT/scripts/push_v1095.sh" \
  --message "Sprint v10.95 — MP-1479 PostgreSQL schema validation (25 tests)"
