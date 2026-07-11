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
