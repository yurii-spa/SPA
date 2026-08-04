#!/bin/bash
# scripts/agent_io_health.sh — launchd wrapper for com.spa.io_health
# AI Investment OS product-layer health monitor (docs/08). Scans analyst artifacts for freshness/status,
# emits data/investment_os/_health.json. ADVISORY/read-only — no capital, no RiskPolicy/kill/track.
# Log: /tmp/spa_io_health.log
export AGENT_NAME="io_health"
export MODULE="spa_core.investment_os.health"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
