#!/bin/bash
# scripts/agent_swarm_dwell.sh — launchd wrapper for com.spa.swarm_dwell
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# Dwell-hysteresis latch paper book (owner decision own-rnd/own-30, 2026-08-05): rule
# «after the slow exit signal ecdr#23(10/30) fires, do not re-enter until the market prints
# 2 consecutive positive days» over the live aggressive-tier forward legs. Three arms per
# row (raw / baseline-no-latch / dwell) so the latch effect is measurable by construction.
# Writes data/swarm/dwell_hysteresis_book.jsonl (append-only, hash-chained) + status json.
# ADVISORY / OUTSIDE_RISKPOLICY / paper — moves NO capital, never touches the go-live track.
# Tick is idempotent per day (hourly StartInterval is safe). Log: /tmp/spa_swarm_dwell.log
export AGENT_NAME="swarm_dwell"
export MODULE="spa_core.strategy_lab.swarm.dwell_hysteresis_forward"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
