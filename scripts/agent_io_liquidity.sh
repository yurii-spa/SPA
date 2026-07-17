#!/bin/bash
# scripts/agent_io_liquidity.sh — launchd wrapper for com.spa.io_liquidity
# AI Investment OS Liquidity analyst (docs/08). Consumes exit_liquidity_log into an advisory exit-
# liquidity posture. ADVISORY — writes only data/investment_os/, no capital, no RiskPolicy/kill/track.
# Log: /tmp/spa_io_liquidity.log
export AGENT_NAME="io_liquidity"
export MODULE="spa_core.investment_os.agents.liquidity"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
