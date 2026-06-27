#!/bin/bash
# scripts/agent_tournament_engine.sh - launchd wrapper for com.spa.tournament_engine
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_tournament_engine.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh tournament_engine spa_core.tournament.tournament_engine
