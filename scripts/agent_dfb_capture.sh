#!/bin/bash
# scripts/agent_dfb_capture.sh - launchd wrapper for com.spa.dfb_capture
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern, CLAUDE.md rule #11).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this bash wrapper runs it
# correctly. Log: /tmp/spa_dfb_capture.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# DFB daily capture (advisory, READ-ONLY): builds the pool universe, overlays every pool through the
# SPA risk engine (proof-chained), writes data/dfb/{pools.json,pool/*.json}, and appends ONE
# idempotent proof-chained history record per pool for today's UTC day. Moves NO capital, never
# touches the go-live track; writes confined to data/dfb/.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh dfb_capture spa_core.dfb.paper_dfb
