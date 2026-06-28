#!/bin/bash
# scripts/agent_rates_desk_paper.sh — launchd wrapper for com.spa.rates_desk_paper
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rates_desk_paper.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="rates_desk_paper"
export MODULE="spa_core.strategy_lab.rates_desk.paper_rates"
# Step 1: run the paper tick — this is the step that APPENDS to the decision chain and so
# ADVANCES its head_hash (the root cause of the DD_PACK staleness / F1 own-goal).
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh

# Step 2 (the never-rot fix): refresh the PUBLISHED proof bundle over the NEW head so a
# reviewer pulling {decision_log.jsonl, anchors.jsonl, exit_nav.json, DD_PACK.md} at ANY
# instant gets a MUTUALLY CONSISTENT set — DD_PACK's `--expect-head` always equals the
# current decision-chain head. This one step (idempotent, fail-CLOSED, atomic per artifact)
# appends a fresh anchor over the new head + regenerates exit_nav.json + regenerates
# DD_PACK.md + self-verifies (verify_spa --expect-head <DD_PACK head> → exit 0). It SUBSUMES
# the old standalone exit_nav rebuild (refresh regenerates exit_nav itself). Advisory,
# read-only, never moves capital.
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh rates_desk_proof_refresh /Users/yuriikulieshov/Documents/SPA_Claude/scripts/refresh_published_proof.py
