#!/bin/bash
# scripts/agent_hy_cycle.sh - launchd wrapper for com.spa.hy_cycle
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_hy_cycle.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh hy_cycle spa_core.paper_trading.hy_cycle --run
