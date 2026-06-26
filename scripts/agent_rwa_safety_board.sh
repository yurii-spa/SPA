#!/bin/bash
# scripts/agent_rwa_safety_board.sh — launchd wrapper for com.spa.rwa_safety_board
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rwa_safety_board.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="rwa_safety_board"
export MODULE="spa_core.strategy_lab.rwa_backstop.safety_board"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
