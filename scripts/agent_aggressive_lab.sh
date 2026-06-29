#!/bin/bash
# scripts/agent_aggressive_lab.sh — launchd wrapper for com.spa.aggressive_lab
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_aggressive_lab.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# Runs the Aggressive-Lab STANDING DAILY tick (advisory): accrue the forward
# paper track (Lane 1) + re-rank the honest scorecard (Lane 2). Idempotent per
# UTC day, fail-CLOSED. NEVER touches the go-live track or live allocation.
export AGENT_NAME="aggressive_lab"
export MODULE="spa_core.strategy_lab.aggressive_lab_runner"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
