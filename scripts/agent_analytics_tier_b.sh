#!/bin/bash
# scripts/agent_analytics_tier_b.sh - launchd wrapper for com.spa.analytics_tier_b
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_analytics_tier_b.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh analytics_tier_b spa_core.analytics.signal_aggregator --run --tier B
