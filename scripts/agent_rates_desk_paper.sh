#!/bin/bash
# scripts/agent_rates_desk_paper.sh — launchd wrapper for com.spa.rates_desk_paper
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_rates_desk_paper.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
export AGENT_NAME="rates_desk_paper"
export MODULE="spa_core.strategy_lab.rates_desk.paper_rates"
# Run the paper tick (advances the forward carry track) via the canonical template,
# then ALSO rebuild the investor-facing liquidation-NAV-by-size exit schedule from the
# now-current surface/book (advisory, read-only, fail-CLOSED — never moves capital).
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh rates_desk_exit_nav spa_core.strategy_lab.rates_desk.exit_nav
