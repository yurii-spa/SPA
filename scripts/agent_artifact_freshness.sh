#!/bin/bash
# launchd wrapper for com.spa.artifact_freshness — единый реестр свежести артефактов (advisory).
# Пишет data/artifact_freshness.json + Telegram-алерт на any_stale. Read-only над data/,
# НЕ трогает RiskPolicy/kill-switch/money-path. Owner-approved W1 (2026-07-23).
export AGENT_NAME="artifact_freshness"
export MODULE="spa_core.monitoring.artifact_freshness"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
