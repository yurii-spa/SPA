#!/bin/bash
# scripts/agent_swarm_regime.sh — launchd wrapper for com.spa.swarm_regime
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# SWARM block 3 (docs/SWARM_ARCHITECTURE.md): L1 funding-regime classifier — GREEN/YELLOW/RED
# carry weather from the 5-venue median funding feed (ETH primary, BTC secondary); the exogenous
# early signal for the L2 guardians and the block-4 leverage brain. Fail-closed to UNKNOWN.
# Writes data/swarm/funding_regime.json + a daily hash-chained proof line.
# ADVISORY / signal-only — moves NO capital, never touches the go-live track.
# Log: /tmp/spa_swarm_regime.log
export AGENT_NAME="swarm_regime"
export MODULE="spa_core.strategy_lab.swarm.funding_regime"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
