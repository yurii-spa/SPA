#!/bin/bash
# scripts/agent_swarm_health.sh — launchd wrapper for com.spa.swarm_health
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# SWARM block 5 (docs/SWARM_ARCHITECTURE.md): L4 immune layer — verifies every swarm organ is
# alive+fresh, its fail-closed contract holds IN the artifact, and the last proof line verifies.
# Writes data/swarm/swarm_health.json (OK/WARNING). Exit 1 on WARNING (visible to agent_health).
# ADVISORY — reads swarm artifacts only, moves NO capital.
# Log: /tmp/spa_swarm_health.log
export AGENT_NAME="swarm_health"
export MODULE="spa_core.strategy_lab.swarm.swarm_health"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
RC=$?

# Step 2: S2 lead-time evidence (tier-port) — shadow-signal vs real defense episodes ledger.
# NB: cd first — launchd's cwd is not the repo (immune-layer catch 2026-07-12).
cd /Users/yuriikulieshov/Documents/SPA_Claude && /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.strategy_lab.swarm.leadtime_evidence >> /tmp/spa_swarm_health.log 2>&1 || true

# Step 3: weekly chaos drill (Mondays) — prove the immune layer catches every failure mode
# in a sandbox copy (block 5b). Sandbox-only: live data/swarm is never mutated.
if [ "$(date -u +%u)" = "1" ]; then
  cd /Users/yuriikulieshov/Documents/SPA_Claude && /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.strategy_lab.swarm.chaos_drill >> /tmp/spa_swarm_health.log 2>&1 || true
fi

exit $RC
