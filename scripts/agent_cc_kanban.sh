#!/bin/bash
# ============================================================================
# scripts/agent_cc_kanban.sh — claude-code-kanban backup monitor (ENV_SETUP v3 §4.1)
# ============================================================================
# Read-only web monitor over ~/.claude (tasks/teams/sessions). Manages nothing;
# highlights sessions/tasks — the backup observation surface for headless
# orchestrator sessions that Nimbalyst does NOT track (verified §4.2).
#
# KeepAlive service on port 4455. Logs to /tmp per CLAUDE.md invariant #12.
# Uses a dedicated user-owned npm cache to dodge the root-owned ~/.npm/_cacache
# EACCES (pre-existing env bug; sudo chown -R 501:20 ~/.npm would also fix it).
# ============================================================================

set -uo pipefail

LOG="/tmp/spa_cc_kanban.log"
export HOME="/Users/yuriikulieshov"
export PATH="/usr/local/bin:/Users/yuriikulieshov/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PORT="4455"
export npm_config_cache="$HOME/.cache/cckanban-npm"
mkdir -p "$npm_config_cache"

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
echo "[$(ts)] === cc-kanban START (port $PORT) ===" >> "$LOG"

# Bound the log.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 500 ]; then
    tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# exec so launchd tracks the server process directly (KeepAlive restarts it).
exec npx --yes claude-code-kanban >> "$LOG" 2>&1
