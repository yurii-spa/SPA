#!/bin/bash
# scripts/agent_dashboard.sh - launchd wrapper for com.spa.dashboard
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_dashboard.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh dashboard http.server 8767 --directory /Users/yuriikulieshov/Documents/SPA_Claude
