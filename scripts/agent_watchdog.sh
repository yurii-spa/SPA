#!/bin/bash
# scripts/agent_watchdog.sh — launchd wrapper for com.spa.watchdog
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_watchdog.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="watchdog"
export MODULE="spa_core.monitoring.watchdog"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
