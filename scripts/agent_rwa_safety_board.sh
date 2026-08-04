#!/bin/bash
# scripts/agent_rwa_safety_board.sh — launchd wrapper for com.spa.rwa_safety_board
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rwa_safety_board.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
# Step 1: run the RWA safety board — builds the report AND appends today's forward NAV point to
# data/rwa_nav_curve.json (nav_curve.record_forward_point is invoked from the board's daily run).
export AGENT_NAME="rwa_safety_board"
export MODULE="spa_core.strategy_lab.rwa_backstop.safety_board"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh

# Step 2 (WORKSTREAM 2 proof-breadth, never-rot F1): hash-anchor the FRESH NAV forward record.
# Regenerates data/rwa_backstop/nav_proof.jsonl from the now-current rwa_nav_curve.json (per-row
# proof_hash over inputs+outputs+prev_hash, chained — exit-NAV pattern) so the published proof never
# rots relative to the forward curve. Read-only over the curve JSON, advisory, atomic.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh rwa_nav_proof spa_core.strategy_lab.rwa_backstop.nav_proof --build
