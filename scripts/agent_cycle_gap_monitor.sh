#!/bin/bash
# scripts/agent_cycle_gap_monitor.sh - launchd wrapper for com.spa.cycle_gap_monitor
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_cycle_gap_monitor.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh cycle_gap_monitor spa_core.paper_trading.cycle_gap_monitor
