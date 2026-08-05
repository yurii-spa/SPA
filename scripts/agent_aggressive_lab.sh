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
# MODULE_ARGS MUST be a plain STRING here: this wrapper calls agent_template.sh as a CHILD
# /bin/bash, and a bash ARRAY does not survive `export` across a process boundary — the old
# `export MODULE_ARGS=(paper)` arrived as NOTHING, the module fell through to mode "both", and
# the nightly backtest rewrote the forward paper book down to a single forward row (incident
# measured 2026-08-05; pinned by spa_core/tests/test_aggressive_lab_series_rewrite.py).
export MODULE_ARGS="paper"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh

# Step 2: regenerate the 3-tier $100k paper rollup (Core/Balanced/Aggressive) — read-only view.
/Users/yuriikulieshov/miniconda3/bin/python3 /Users/yuriikulieshov/Documents/SPA_Claude/scripts/tier_paper_rollup.py >> /tmp/spa_aggressive_lab.log 2>&1 || true
