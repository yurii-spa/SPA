#!/bin/bash
# scripts/agent_governance_watcher.sh - launchd wrapper for com.spa.governance_watcher
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_governance_watcher.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh governance_watcher spa_core.alerts.governance_watcher --write
