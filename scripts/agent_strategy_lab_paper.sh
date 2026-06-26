#!/bin/bash
# scripts/agent_strategy_lab_paper.sh — launchd wrapper for com.spa.strategy_lab_paper
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_strategy_lab_paper.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="strategy_lab_paper"
export RUN_SCRIPT="/Users/yuriikulieshov/Documents/SPA_Claude/scripts/strategy_lab_paper.py"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
