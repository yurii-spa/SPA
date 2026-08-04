#!/bin/bash
# scripts/agent_realized_at_size.sh — launchd wrapper for com.spa.realized_at_size
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern, CLAUDE.md rule #11).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this bash wrapper runs it
# correctly. Log: /tmp/spa_realized_at_size.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# B2.6 — the STANDING forward-measurement agent for the realized-at-size KILLER TEST. Daily,
# advisory, idempotent per UTC day. Re-runs the killer test on Lane A's freshest books and
# appends/refreshes ONE row in the growing verdict track (data/rates_desk/paper/
# realized_at_size_track.jsonl) so the verdict can be watched evolving forward across the track.
# Moves NO capital, never touches the go-live track, never imports execution/.
export AGENT_NAME="realized_at_size"
export MODULE="spa_core.strategy_lab.rates_desk.paper_realized_at_size"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
