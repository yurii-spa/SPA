#!/bin/bash
# scripts/agent_swarm_guardian.sh — launchd wrapper for com.spa.swarm_guardian
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# SWARM block 1 (docs/SWARM_ARCHITECTURE.md): L2 position guardians over the LIVE aggressive_lab
# forward paper track — recomputes the OOS-validated vol-guardian overlay per book each run,
# writes data/swarm/guardian_forward.json + a daily hash-chained proof line.
# ADVISORY / OUTSIDE_RISKPOLICY / paper — moves NO capital, never touches the go-live track.
# Log: /tmp/spa_swarm_guardian.log
export AGENT_NAME="swarm_guardian"
export MODULE="spa_core.strategy_lab.swarm.guardian_forward"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
