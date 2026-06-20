#!/usr/bin/env bash
# Sprint v10.72 — MP-1456: ADR-032/034/035/036 for v10.x architectural decisions
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/docs/adr/ADR-032-live-trading-gate.md" \
    "$REPO_ROOT/docs/adr/ADR-034-atomic-write-centralization.md" \
    "$REPO_ROOT/docs/adr/ADR-035-spaerror-hierarchy.md" \
    "$REPO_ROOT/docs/adr/ADR-036-baseanalytics-migration.md" \
    "$REPO_ROOT/tests/test_new_adrs.py" \
    "$REPO_ROOT/scripts/push_v1072.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.72 — MP-1456 ADR-032/034/035/036 for v10 architectural decisions (LiveTradingGate, AtomicWrite, SPAError, BaseAnalytics)"
