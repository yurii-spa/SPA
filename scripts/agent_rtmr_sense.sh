#!/bin/bash
# scripts/agent_rtmr_sense.sh - launchd wrapper for com.spa.rtmr_sense (RTMR ADR-053 sense+emergency, PAPER).
# Canonical bash-wrapper pattern (launchd can't exec miniconda-python directly -> exit 78).
# Log: /tmp/spa_rtmr_sense.log
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh rtmr_sense spa_core.monitoring.rtmr_service
