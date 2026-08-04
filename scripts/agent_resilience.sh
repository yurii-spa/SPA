#!/bin/bash
# scripts/agent_resilience.sh - launchd wrapper for com.spa.resilience
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_resilience.log
#
# Runs the R8 resilience posture rollup (reads offsite/restore/fleet drill
# statuses -> data/resilience_status.json). Reporter, exit 0 even on WARNING;
# the freshness is what the daily briefing + agent_health surface.
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh resilience /Users/yuriikulieshov/Documents/SPA_Claude/scripts/resilience_cycle.py
