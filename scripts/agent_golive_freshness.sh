#!/bin/bash
# scripts/agent_golive_freshness.sh - launchd wrapper for com.spa.golive_freshness (Q1-11)
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this bash
# wrapper runs it correctly. Log: /tmp/spa_golive_freshness.log
#
# Runs the go-live freshness cycle (golive_checker + inert pre_cutover_gate) so the
# readiness verdict + money-path proof stay FRESH and DATED, decoupled from the daily
# cycle. Reporter, exit 0 even when golive_checker reports NOT READY (a verdict, not a
# failure). Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>].
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh golive_freshness /Users/yuriikulieshov/Documents/SPA_Claude/scripts/golive_freshness_cycle.py
