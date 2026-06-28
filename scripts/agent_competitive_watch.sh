#!/bin/bash
# scripts/agent_competitive_watch.sh - launchd wrapper for com.spa.competitive_watch
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_competitive_watch.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# WS-E Proof-of-Risk: the Section-7 competitive early-warning monitor. Deterministic,
# fail-CLOSED, idempotent per UTC day (--run alerts ONLY on a NEW transition to
# BREACHED via push_policy edge-trigger; a persistent breach is silent).
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh competitive_watch spa_core.monitoring.competitive_watch --run
