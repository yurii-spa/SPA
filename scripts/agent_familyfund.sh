#!/bin/bash
# scripts/agent_familyfund.sh - launchd wrapper for com.spa.familyfund
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_familyfund.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh familyfund uvicorn spa_core.family_fund.api.app:app --host 127.0.0.1 --port 8766
