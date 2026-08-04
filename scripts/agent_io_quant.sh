#!/bin/bash
# scripts/agent_io_quant.sh — launchd wrapper for com.spa.io_quant
# AI Investment OS Quant & Backtesting analyst (docs/08). ADVISORY — writes only data/investment_os/.
export AGENT_NAME="io_quant"
export MODULE="spa_core.investment_os.agents.quant"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
