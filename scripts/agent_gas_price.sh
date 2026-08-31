#!/bin/bash
# scripts/agent_gas_price.sh - launchd wrapper for com.spa.gas_price_agent
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_gas_price_agent.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# ADR-183: агент цены газа. Каждые 30 минут опрашивает публичные RPC четырёх
# сетей (ethereum/base/arbitrum/optimism) + спот ETH, пишет
# data/gas_price_history.json. Отказ источников = запись `unchecked`,
# fallback-констант НЕТ. Advisory: никого не гейтит, де-риска не касается.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh gas_price_agent spa_core.monitoring.gas_price_agent --run
