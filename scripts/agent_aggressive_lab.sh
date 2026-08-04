#!/bin/bash
# scripts/agent_aggressive_lab.sh — launchd wrapper for com.spa.aggressive_lab
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# Advances the Aggressive Lab forward paper track by one tick per run (live feeds, no mock).
# ADVISORY / OUTSIDE_RISKPOLICY / paper — moves NO capital, never touches the go-live track.
# The growing forward track is what lets the higher-tier (Balanced/Aggressive) strategies
# reach `trustworthy` (~30 pts) so the packages can be HONESTLY proven (with their tail shown).
# Log: /tmp/spa_aggressive_lab.log
export AGENT_NAME="aggressive_lab"
export MODULE="spa_core.strategy_lab.aggressive_lab.run"
export MODULE_ARGS=(paper)
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh

# Step 2: regenerate the 3-tier $100k paper rollup (Core/Balanced/Aggressive) — read-only view.
/Users/yuriikulieshov/miniconda3/bin/python3 /Users/yuriikulieshov/Documents/SPA_Claude/scripts/tier_paper_rollup.py >> /tmp/spa_aggressive_lab.log 2>&1 || true
