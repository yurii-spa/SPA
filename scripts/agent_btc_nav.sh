#!/bin/bash
# scripts/agent_btc_nav.sh — launchd wrapper for com.spa.btc_nav (ADR-118)
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# Q1-решение владельца 22.08: paper-NAV трек BTC/USDT-движка (чемпион v0.1, k=0.7).
# Два шага: (1) research-продюсер (pandas, СВОЙ слой — инвариант #4 цел) пишет
# data/btc_cycle/target_share.json; (2) stdlib-бухгалтер ведёт отдельную paper-книгу
# data/btc_paper_trading.json (IS_ADVISORY, капитал не двигает, вне kill-switch
# общего NAV по построению). Продюсер без движка честно молчит → бухгалтер пишет gap.
# Log: /tmp/spa_btc_nav.log

# Step 1: producer (research layer; отсутствие движка/сети = записанная дыра, не авария)
/Users/yuriikulieshov/miniconda3/bin/python3 /Users/yuriikulieshov/Documents/SPA_Claude/research/btc_cycle/daily_signal.py >> /tmp/spa_btc_nav.log 2>&1 || true

# Step 2: stdlib book-keeper (MODULE_ARGS — plain STRING; инцидент 2026-08 в шаблоне)
export AGENT_NAME="btc_nav"
export MODULE="spa_core.paper_trading.btc_nav"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
