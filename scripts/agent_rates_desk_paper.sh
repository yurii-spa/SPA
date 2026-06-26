#!/bin/bash
# scripts/agent_rates_desk_paper.sh — launchd wrapper for com.spa.rates_desk_paper
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rates_desk_paper.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="rates_desk_paper"
export MODULE="spa_core.strategy_lab.rates_desk.paper_rates"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
