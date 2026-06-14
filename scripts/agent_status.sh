#!/bin/bash
# agent_status.sh — показывает статус всех com.spa.* launchd агентов
# Использование: bash scripts/agent_status.sh

EXPECTED=(
  com.spa.httpserver
  com.spa.cloudflared
  com.spa.fund-api
  com.spa.uptime_monitor
  com.spa.cycle_health
  com.spa.cycle_gap_monitor
  com.spa.portfolio_monitor
  com.spa.peg_monitor
  com.spa.red_flag_monitor
  com.spa.governance_watcher
  com.spa.autopush
  com.spa.daily_cycle
  com.spa.base_gas_monitor
  com.spa.sky_monitor
  "com.spa.daily-paper-report"
  "com.spa.checkpoint-7day"
  com.spa.weekly_backup
  com.spa.analytics_tier_c
)

echo "=== SPA Agent Status $(date) ==="
echo ""

LOADED=$(launchctl list 2>/dev/null | grep "com.spa")
MISSING=0
ERRORED=0

for label in "${EXPECTED[@]}"; do
  line=$(echo "$LOADED" | grep "$label" || true)
  if [ -z "$line" ]; then
    echo "❌ NOT LOADED: $label"
    ((MISSING++)) || true
  else
    pid=$(echo "$line" | awk '{print $1}')
    status=$(echo "$line" | awk '{print $2}')
    if [ "$status" != "0" ] && [ "$status" != "-" ]; then
      echo "⚠️  ERROR (exit $status): $label (pid=$pid)"
      ((ERRORED++)) || true
    elif [ "$pid" = "-" ]; then
      echo "⏸  IDLE (cron): $label"
    else
      echo "✅ RUNNING (pid=$pid): $label"
    fi
  fi
done

echo ""
echo "Missing: $MISSING | Errored: $ERRORED | Total expected: ${#EXPECTED[@]}"
