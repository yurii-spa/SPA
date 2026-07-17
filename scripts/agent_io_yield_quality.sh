#!/bin/bash
# scripts/agent_io_yield_quality.sh — launchd wrapper for com.spa.io_yield_quality
# AI Investment OS Yield Quality analyst (docs/08). Decomposes advertised vs sustainable yield from
# apy_decomposition_log. ADVISORY — writes only data/investment_os/, no capital, no RiskPolicy/kill/track.
# Log: /tmp/spa_io_yield_quality.log
export AGENT_NAME="io_yield_quality"
export MODULE="spa_core.investment_os.agents.yield_quality"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
