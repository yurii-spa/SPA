#!/bin/bash
# scripts/agent_self_heal.sh — launchd wrapper for com.spa.self_heal
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_self_heal.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="self_heal"
export MODULE="spa_core.monitoring.self_heal"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
