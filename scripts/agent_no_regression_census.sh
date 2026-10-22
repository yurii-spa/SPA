#!/bin/bash
# scripts/agent_no_regression_census.sh — launchd wrapper for com.spa.no_regression_census
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# §49 «No regression» (заказ G673 п. 1, ADR-770): производитель отчёта
# data/no_regression_census.json. Прогон населения идёт в СНИМКЕ коммита origin/main
# (git clone --shared во временный каталог, со сторожем записи), не в боевом дереве; в боевое — только отчёт.
# Такт решает возраст отчёта (--max-age-h 120 < предела пробы 192 ч), а не расписание.
#
# ПОДГОТОВЛЕН, НЕ ВКЛЮЧЁН (21.10): строки в scripts/install_all_agents.sh нет, в
# architecture/manifest.json у артефакта producer: null. Включение — отдельное действие:
# scripts/check_agent_before_deploy.sh + launchctl bootstrap + producer в конституции.
# Log: /tmp/spa_no_regression_census.log
export AGENT_NAME="no_regression_census"
# Признак запуска АГЕНТОМ: без него отчёт помечается как ручной (invoked_by.env.via).
export SPA_NO_REGRESSION_VIA="launchd:com.spa.no_regression_census"
export RUN_SCRIPT="/Users/yuriikulieshov/Documents/SPA_Claude/scripts/refresh_no_regression_census.py"
export MODULE_ARGS="--scheduled --live-root /Users/yuriikulieshov/Documents/SPA_Claude --ref origin/main --max-age-h 120 --timeout-s 3600"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
