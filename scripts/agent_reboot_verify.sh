#!/bin/bash
# ============================================================================
# scripts/agent_reboot_verify.sh — launchd wrapper for com.spa.reboot_verify (Q3-8)
# ============================================================================
# Runs scripts/verify_fleet_after_reboot.sh once at LOGIN (RunAtLoad), so the
# post-reboot fleet heal + its auditable status JSON (data/fleet_reboot_status
# .json) are produced automatically — "probably recovered" becomes proven+dated
# without a human remembering to run the command.
#
# bash-wrapper + /tmp log per CLAUDE.md rule #11 (launchd cannot write under
# ~/Documents — TCC; and must not exec non-/bin/bash directly). The inner script
# is READ-MOSTLY + idempotent: it only (re)bootstraps agents that are not loaded
# and NEVER mutates the go-live track. Wrapper exits with the inner script's code.
# ============================================================================
set -uo pipefail
REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
LOG="/tmp/spa_reboot_verify.log"
INNER="$REPO/scripts/verify_fleet_after_reboot.sh"

{
  echo "──────── START $(date -u '+%Y-%m-%dT%H:%M:%SZ') com.spa.reboot_verify ────────"
  cd "$REPO" || { echo "cd $REPO failed"; exit 1; }
  /bin/bash "$INNER"
  rc=$?
  echo "──────── EXIT rc=$rc $(date -u '+%Y-%m-%dT%H:%M:%SZ') ────────"
  exit "$rc"
} >>"$LOG" 2>&1
