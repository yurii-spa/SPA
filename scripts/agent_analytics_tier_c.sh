#!/bin/bash
# scripts/agent_analytics_tier_c.sh - launchd wrapper for com.spa.analytics_tier_c
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_analytics_tier_c.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh analytics_tier_c spa_core.analytics.signal_aggregator --run --tier C
