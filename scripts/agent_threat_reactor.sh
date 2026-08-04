#!/bin/bash
# scripts/agent_threat_reactor.sh — launchd wrapper for com.spa.threat_reactor
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_threat_reactor.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="threat_reactor"
export MODULE="spa_core.monitoring.threat_reactor"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
