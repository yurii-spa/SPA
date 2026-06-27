#!/bin/bash
# scripts/agent_tier1_digest.sh - launchd wrapper for com.spa.tier1_digest
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_tier1_digest.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh tier1_digest spa_core.reporting.tier1_digest --send
