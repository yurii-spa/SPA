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
RC=$?

# Step 2: EYC v2 shadow allocator (registry idea #6) — equilibrium-vs-spot scoring + own-size
# rate impact over the live apy_ranking; SHADOW-ONLY, logs divergences for the promotion ADR.
# NB: cd first — launchd's cwd is not the repo (immune-layer catch 2026-07-12).
cd /Users/yuriikulieshov/Documents/SPA_Claude && /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.strategy_lab.swarm.eyc_allocator >> /tmp/spa_swarm_regime.log 2>&1 || true

exit $RC
