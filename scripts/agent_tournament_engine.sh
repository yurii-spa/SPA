#!/bin/bash
# scripts/agent_tournament_engine.sh - launchd wrapper for com.spa.tournament_engine
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_tournament_engine.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]

# Step 1: run the tournament engine — regenerates data/strategy_tournament.json (the daily ranking).
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh tournament_engine spa_core.tournament.tournament_engine

# Step 2 (WORKSTREAM 2 proof-breadth, never-rot F1): hash-anchor the FRESH ranking. Appends today's
# ranking to the tamper-evident chain data/tournament/decision_log.jsonl (proof covers the OUTPUTS
# rank/strategy/net_return/sharpe + per-row prev_hash; idempotent per ranking generated_at) so the
# published proof never rots relative to strategy_tournament.json. Read-only over the ranking JSON,
# advisory, atomic. (The hourly refresh_published_proof.py ALSO regenerates it — belt-and-suspenders.)
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh tournament_proof spa_core.tournament.tournament_proof_chain --build
