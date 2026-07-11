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
