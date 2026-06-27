#!/bin/bash
# scripts/agent_red_flag_monitor.sh - launchd wrapper for com.spa.red_flag_monitor
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_red_flag_monitor.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh red_flag_monitor spa_core.alerts.red_flag_monitor
