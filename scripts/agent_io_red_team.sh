#!/bin/bash
# scripts/agent_io_red_team.sh — launchd wrapper for com.spa.io_red_team
# AI Investment OS Red Team analyst (docs/08). Consumes threat-reactor + attack-sim into an advisory
# threat posture; can only RAISE concern, NEVER approves. ADVISORY — writes only data/investment_os/,
# moves NO capital, never touches RiskPolicy/kill/live track. Log: /tmp/spa_io_red_team.log
export AGENT_NAME="io_red_team"
export MODULE="spa_core.investment_os.agents.red_team"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
