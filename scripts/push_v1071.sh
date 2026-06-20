#!/usr/bin/env bash
# Sprint v10.71 — MP-1455: Evidence seed data +5 pts, evidence infrastructure
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/golive_readiness_report.py" \
    "$REPO_ROOT/data/paper_evidence_history.json" \
    "$REPO_ROOT/scripts/push_v1071.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.71 — MP-1455 Evidence seed data +5 pts, evidence infrastructure (GoLive 77→82)"
