#!/bin/bash
# scripts/agent_io_chief_investment.sh — launchd wrapper for com.spa.io_chief_investment
# AI Investment OS Chief Investment (Head of Product) — synthesises the analyst artifacts into a house-
# view. RECOMMENDS only, OWNER-GATED, moves NO capital, never touches RiskPolicy/kill/track. Runs AFTER
# the other analysts (later StartInterval offset via ThrottleInterval). Log: /tmp/spa_io_chief_investment.log
export AGENT_NAME="io_chief_investment"
export MODULE="spa_core.investment_os.agents.chief_investment"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
