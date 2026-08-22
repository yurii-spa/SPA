#!/bin/bash
# scripts/agent_swarm_rank_demotion.sh — launchd wrapper for com.spa.swarm_rank_demotion
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# ADR-074 (owner decisions 2026-08-08, варианты A+C + own-rnd-xvd-vol-rank-second-arm вар.1):
# форвардный paper-тик рангового демоушена, ДВЕ РУКИ (drift #40 / vol #45) в одном модуле —
# «через 30 дней форварда мы своими глазами увидим, какая рука лучше». До подключения
# (аудит 2026-08-21, вердикт WIRE) форвард-трек НЕ КОПИЛСЯ вовсе: единственный *_forward
# роя без обёртки. Тик идемпотентен по дате (REFUSED_OUT_OF_ORDER) — час launchd безопасен.
# ADVISORY / OUTSIDE_RISKPOLICY / paper — капитал НЕ двигает, kill-switch не заменяет.
# Пишет data/swarm/rank_demotion_status.json + rank_demotion_book.jsonl.
# Log: /tmp/spa_swarm_rank_demotion.log
export AGENT_NAME="swarm_rank_demotion"
export MODULE="spa_core.strategy_lab.swarm.rank_demotion_forward"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
