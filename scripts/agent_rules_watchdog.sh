#!/bin/bash
# scripts/agent_rules_watchdog.sh - launchd wrapper for com.spa.rules_watchdog
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rules_watchdog.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh rules_watchdog spa_core.monitoring.rules_watchdog
