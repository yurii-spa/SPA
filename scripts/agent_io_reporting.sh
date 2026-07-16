#!/bin/bash
# scripts/agent_io_reporting.sh — launchd wrapper for com.spa.io_reporting
# AI Investment OS analyst (AAA product-layer, docs/08). Reads its feed(s) fail-CLOSED, evidence-tags
# (L0-L6), emits an ADVISORY artifact to data/investment_os/ + hash-chained proof. Moves NO capital,
# never touches RiskPolicy/kill/live track. Log: /tmp/spa_io_reporting.log
export AGENT_NAME="io_reporting"
export MODULE="spa_core.investment_os.agents.reporting"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
