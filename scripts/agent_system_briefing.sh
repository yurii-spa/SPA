#!/bin/bash
# scripts/agent_system_briefing.sh - launchd wrapper for com.spa.system_briefing
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_system_briefing.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh system_briefing /Users/yuriikulieshov/Documents/SPA_Claude/scripts/update_system_briefing.py
