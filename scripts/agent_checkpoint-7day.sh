#!/bin/bash
# scripts/agent_checkpoint-7day.sh - launchd wrapper for com.spa.checkpoint-7day
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_checkpoint-7day.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh checkpoint-7day scripts/checkpoint_7day.py
