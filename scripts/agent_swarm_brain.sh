#!/bin/bash
# scripts/agent_swarm_brain.sh — launchd wrapper for com.spa.swarm_brain
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# SWARM block 4 (docs/SWARM_ARCHITECTURE.md): L3 dynamic-leverage brain — per-book paper leverage
# recommendation = base_cap(risk_class) × regime × guardian × depth, refusal-first (null when any
# input is missing/stale/flagged; levered books REQUIRE fresh unflagged exit depth).
# Reads only swarm/fleet artifacts; writes data/swarm/leverage_brain.json + daily proof line.
# ADVISORY / OUTSIDE_RISKPOLICY / paper — recommends only, moves NO capital.
# Log: /tmp/spa_swarm_brain.log
export AGENT_NAME="swarm_brain"
export MODULE="spa_core.strategy_lab.swarm.leverage_brain"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
RC=$?

# Step 2: the SWARM BOOK — apply pending bars with the PRIOR decision, then record the new
# decision for future bars (block A: the exercised paper portfolio). Runs right after the
# brain so the decision it persists is at most seconds old.
# NB: launchd's cwd is NOT the repo — cd first or `-m spa_core.*` fails ModuleNotFound
# (caught by the immune layer 2026-07-12: swarm_book stale 7.5h while the brain ticked).
cd /Users/yuriikulieshov/Documents/SPA_Claude && /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.strategy_lab.swarm.swarm_book >> /tmp/spa_swarm_brain.log 2>&1 || true

exit $RC
