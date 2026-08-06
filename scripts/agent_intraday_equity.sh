#!/bin/bash
# scripts/agent_intraday_equity.sh - launchd wrapper for com.spa.intraday_equity
# Canonical bash-wrapper (launchd cannot exec miniconda-python, exit 78).
# ADR-068: 5-min intraday drawdown sensor feeding the SAME governance ladder.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh intraday_equity spa_core.monitoring.intraday_equity --run
