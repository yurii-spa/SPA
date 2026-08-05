#!/bin/bash
# scripts/agent_decision_loop.sh - launchd wrapper for com.spa.decision_loop
# Canonical bash-wrapper pattern (launchd cannot exec miniconda-python, exit 78).
# ADR-066 Phase 3: house_view_gap recompute + findings->cards bridge. Log: /tmp/spa_decision_loop.log
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh decision_loop spa_core.monitoring.findings_bridge --run
