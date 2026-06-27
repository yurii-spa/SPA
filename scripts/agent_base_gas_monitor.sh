#!/bin/bash
# scripts/agent_base_gas_monitor.sh - launchd wrapper for com.spa.base_gas_monitor
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_base_gas_monitor.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh base_gas_monitor spa_core.monitoring.base_gas_monitor --run
