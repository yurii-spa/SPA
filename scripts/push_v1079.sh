#!/usr/bin/env bash
# Sprint v10.79 — MP-1463: Evidence +5 pts via extended seed data
# Push: rs002 syntax fix + seed data + tests
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO/push_to_github.py" \
  --files \
    "$REPO/spa_core/analytics/rs002_live_apy_engine.py" \
    "$REPO/data/paper_evidence_history.json" \
    "$REPO/tests/test_evidence_seeded.py" \
    "$REPO/scripts/push_v1079.sh" \
  --message "Sprint v10.79 — MP-1463 Evidence +5 pts via extended seed data"
