#!/bin/bash
# scripts/agent_system_health_morning.sh - launchd wrapper for com.spa.system_health_morning
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_system_health_morning.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# Runs the WRITER that refreshes data/system_health.json on every run. The old
# target scripts/system_health_check.py only PRINTED PASS/WARN/FAIL and never
# wrote data/system_health.json → the file went days stale while this agent kept
# exiting 0 (the cry-wolf staleness bug). The monitor module --run computes the
# 7-domain report, atomic-writes data/system_health.json, and sends the
# edge-triggered telegram, exactly as intended for the twice-daily run.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh system_health_morning spa_core.monitoring.system_health_monitor --run
