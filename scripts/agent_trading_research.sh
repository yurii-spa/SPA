#!/bin/bash
# scripts/agent_trading_research.sh — launchd wrapper for com.spa.trading_research (ADR-525)
# Forward-paper tick of the Trading Research Engine: research/paper ONLY — no exchange account, no
# keys, no orders. Idempotent + locked; a missed interval is caught up on the next tick.
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern). Log: /tmp/spa_trading_research.log
export AGENT_NAME="trading_research"
export MODULE="spa_core.trading_research"
export MODULE_ARGS="tick"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
