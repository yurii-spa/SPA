#!/bin/bash
# scripts/agent_io_market_regime.sh — launchd wrapper for com.spa.io_market_regime
# AI Investment OS analyst (AAA product-layer, docs/08). Reads its feed(s) fail-CLOSED, evidence-tags
# (L0-L6), emits an ADVISORY artifact to data/investment_os/ + hash-chained proof. Moves NO capital,
# never touches RiskPolicy/kill/live track. Log: /tmp/spa_io_market_regime.log
export AGENT_NAME="io_market_regime"
export MODULE="spa_core.investment_os.agents.market_regime"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
