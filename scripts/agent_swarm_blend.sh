#!/bin/bash
# scripts/agent_swarm_blend.sh — launchd wrapper for com.spa.swarm_blend
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# SWARM block 2 (docs/SWARM_ARCHITECTURE.md): forward 3-desk blend paper portfolio (validated
# idea #3, 25/50/25 sUSDe/rates/RWA) recomputed causally over the three live paper legs each run —
# writes data/swarm/blend_forward.json + a daily hash-chained proof line.
# ADVISORY / OUTSIDE_RISKPOLICY / paper — moves NO capital, never touches the go-live track.
# Log: /tmp/spa_swarm_blend.log
export AGENT_NAME="swarm_blend"
export MODULE="spa_core.strategy_lab.swarm.blend_forward"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
