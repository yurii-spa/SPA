#!/bin/bash
# push_v1360_tournament_engine.sh
# Pushes all Tournament Engine v1.0 files to GitHub via push_to_github.py
# Run from project root: bash scripts/push_v1360_tournament_engine.sh

set -euo pipefail

ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "=== Pushing Tournament Engine v1.0 (MP-136) ==="

"$PYTHON" "$ROOT/push_to_github.py" \
    --files \
    "$ROOT/spa_core/tournament/__init__.py" \
    "$ROOT/spa_core/tournament/tournament_engine.py" \
    "$ROOT/spa_core/tournament/tournament_telegram.py" \
    "$ROOT/launchd/com.spa.tournament_engine.plist" \
    "$ROOT/scripts/install_tournament_agent.sh" \
    "$ROOT/scripts/push_v1360_tournament_engine.sh" \
    "$ROOT/tests/test_tournament_engine.py" \
    --message "MP-136: Tournament Engine v1.0 — TournamentEngine + TournamentTelegram + launchd agent + 50+ tests"

echo "✅ Push complete."
