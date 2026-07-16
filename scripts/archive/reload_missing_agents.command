#!/bin/bash
# reload_missing_agents.command — перезапускает пропавшие агенты
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/agent_reload_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "=== SPA Agent Reload $(date) ==="

PLIST_DIR="$HOME/Library/LaunchAgents"
SCRIPTS_DIR="$HOME/Documents/SPA_Claude/scripts"

reload_agent() {
  local label="$1"
  local plist_name="$1.plist"
  local status
  
  status=$(launchctl list "$label" 2>/dev/null | awk '{print $2}' | tail -1)
  if [ -z "$(launchctl list "$label" 2>/dev/null)" ]; then
    echo "❌ NOT LOADED: $label"
    # Copy plist to LaunchAgents if needed
    if [ ! -f "$PLIST_DIR/$plist_name" ] && [ -f "$SCRIPTS_DIR/$plist_name" ]; then
      cp "$SCRIPTS_DIR/$plist_name" "$PLIST_DIR/"
      echo "  → Copied $plist_name to LaunchAgents"
    fi
    if [ -f "$PLIST_DIR/$plist_name" ]; then
      launchctl load "$PLIST_DIR/$plist_name" 2>&1
      echo "  → Loaded $label"
    else
      echo "  ⚠️ Plist not found: $plist_name"
    fi
  else
    echo "✅ RUNNING: $label"
  fi
}

# Reload autopush (critical — processes push scripts)
reload_agent "com.spa.autopush"
reload_agent "com.spa.daily-paper-report"
reload_agent "com.spa.weekly_backup"
reload_agent "com.spa.analytics_tier_c"
reload_agent "com.spa.analytics_tier_b"

echo ""
echo "=== Running auto_push now to catch up ==="
bash ~/Documents/SPA_Claude/scripts/auto_push.sh 2>&1 | tail -20

echo ""
echo "=== Final Status ==="
launchctl list | grep "com.spa" | awk '{print $1, $2, $3}'

echo ""
echo "[Процесс завершен]"
