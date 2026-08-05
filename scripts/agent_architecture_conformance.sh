#!/bin/bash
# scripts/agent_architecture_conformance.sh - launchd wrapper for com.spa.architecture_conformance
# Canonical bash-wrapper pattern (launchd cannot exec miniconda-python directly, exit 78).
# ADR-066 Phase 1: fleet-vs-constitution watchdog. Log: /tmp/spa_architecture_conformance.log
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh architecture_conformance spa_core.monitoring.architecture_conformance --run --exit-zero
