#!/bin/bash
# scripts/agent_monthly_statement.sh — launchd wrapper for com.spa.monthly_statement
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# Аудит 2026-08-21, вердикт WIRE: месячная выписка (opening/closing NAV, доходность
# периода $ и %, годовая, микс стратегий, аттестация риск-событий) имела рабочий
# CLI и настоящие выписки в data/statements/, ОБРЫВАЮЩИЕСЯ на июне — планировщика
# не было. Тик 1-го числа в 08:30; модуль сам считает DEFAULT_PERIOD (прошлый
# месяц) и идемпотентен по периоду. Read-only по треку, капитал не двигает.
# MODULE_ARGS — plain STRING (bash-массив не переживает export, инцидент 2026-08).
# Log: /tmp/spa_monthly_statement.log
export AGENT_NAME="monthly_statement"
export MODULE="spa_core.compliance.monthly_statement"
export MODULE_ARGS="--run"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
