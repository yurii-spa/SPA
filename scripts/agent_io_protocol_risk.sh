#!/bin/bash
# scripts/agent_io_protocol_risk.sh — launchd wrapper for com.spa.io_protocol_risk
# AI Investment OS Protocol & Peg Risk analyst (docs/08). Consumes protocol_risk_map + peg_report into an
# advisory risk view; can only RAISE concern. ADVISORY — writes only data/investment_os/, no capital,
# no RiskPolicy/kill/track. Log: /tmp/spa_io_protocol_risk.log
export AGENT_NAME="io_protocol_risk"
export MODULE="spa_core.investment_os.agents.protocol_risk"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
