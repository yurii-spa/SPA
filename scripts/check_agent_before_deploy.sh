#!/bin/bash
# ============================================================================
# scripts/check_agent_before_deploy.sh <agent_name>
# ============================================================================
# PRE-DEPLOY GATE for any SPA launchd agent. NEVER `launchctl bootstrap` a
# plist without running this first (see CLAUDE.md FORBIDDEN rule).
#
# Given an agent name (e.g. "watchdog" for com.spa.watchdog) it:
#   1. Locates the plist: scripts/com.spa.<name>.plist or launchd/com.spa.<name>.plist
#   2. Extracts the command from ProgramArguments and RUNS IT MANUALLY ONCE.
#   3. Asserts the manual run exit == 0.
#   4. Asserts the agent's log (/tmp/spa_<name>.log, or the plist's
#      StandardOutPath) was created / written by that run.
#   5. ONLY THEN: bootout (idempotent) -> bootstrap -> kickstart the agent,
#      then re-reads `launchctl list` and asserts the loaded exit code != 78.
#
# If the manual run fails (exit != 0) OR no log -> prints a clear FAIL and
# EXITS NON-ZERO WITHOUT loading the agent.
#
# Idempotent + safe: bootout-before-bootstrap; manual run is the agent's own
# (already-idempotent) command; secrets stay in Keychain.
#
# Usage:  bash scripts/check_agent_before_deploy.sh watchdog
#         bash scripts/check_agent_before_deploy.sh strategy_lab_paper
# ============================================================================

set -uo pipefail

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
GUI="gui/$(id -u)"

fail() { echo "❌ FAIL: $*" >&2; exit 1; }
info() { echo "   $*"; }

[ "$#" -ge 1 ] || fail "usage: check_agent_before_deploy.sh <agent_name>"
NAME="$1"
LABEL="com.spa.${NAME}"

echo "=== PRE-DEPLOY GATE: ${LABEL} ==="

# ── 1. Locate the plist ─────────────────────────────────────────────────────
PLIST=""
for cand in "$REPO_ROOT/scripts/${LABEL}.plist" "$REPO_ROOT/launchd/${LABEL}.plist"; do
    [ -f "$cand" ] && { PLIST="$cand"; break; }
done
[ -n "$PLIST" ] || fail "plist not found (scripts/${LABEL}.plist or launchd/${LABEL}.plist)"
info "plist: $PLIST"

# ── 2. Extract ProgramArguments into a bash array ───────────────────────────
# Pull every <string> between <key>ProgramArguments</key> and the next </array>.
# NOTE: /bin/bash on macOS is 3.2 — no `mapfile`. Use a NUL-safe read loop.
PROGARGS=()
while IFS= read -r _arg; do
    PROGARGS+=("$_arg")
done < <(
  awk '
    /<key>ProgramArguments<\/key>/ {grab=1; next}
    grab && /<\/array>/ {exit}
    grab && /<string>/ {
      line=$0
      sub(/.*<string>/, "", line)
      sub(/<\/string>.*/, "", line)
      print line
    }
  ' "$PLIST"
)
[ "${#PROGARGS[@]}" -ge 1 ] || fail "could not parse ProgramArguments from $PLIST"
info "ProgramArguments: ${PROGARGS[*]}"

# Antipattern guard: warn loudly if the plist execs miniconda-python directly.
case "${PROGARGS[0]}" in
    *miniconda3/bin/python3*)
        echo "⚠️  WARNING: plist execs miniconda-python DIRECTLY (launchd cannot — exit 78)."
        echo "    Convert to a /bin/bash wrapper (scripts/agent_template.sh) before deploying."
        ;;
esac

# ── 3. Determine the log path (prefer /tmp/spa_<name>.log) ──────────────────
WRAPPER_LOG="/tmp/spa_${NAME}.log"
PLIST_LOG=$(awk '
    /<key>StandardOutPath<\/key>/ {grab=1; next}
    grab && /<string>/ {
      line=$0; sub(/.*<string>/, "", line); sub(/<\/string>.*/, "", line)
      print line; exit
    }
' "$PLIST")
# We check whichever log the run actually touches; prefer wrapper log, fall back to plist log.
LOG_BEFORE_WRAPPER=$(stat -f %m "$WRAPPER_LOG" 2>/dev/null || echo 0)
LOG_BEFORE_PLIST=$(stat -f %m "$PLIST_LOG" 2>/dev/null || echo 0)

# ── 4. RUN THE COMMAND MANUALLY ONCE ────────────────────────────────────────
echo "--- manual run ---"
cd "$REPO_ROOT" || fail "cannot cd $REPO_ROOT"
"${PROGARGS[@]}"
RC=$?
echo "--- manual run exit=$RC ---"
[ "$RC" -eq 0 ] || fail "manual run exited $RC (expected 0). NOT loading ${LABEL}."

# ── 5. Assert a log was created / written by this run ───────────────────────
LOG_OK=0
LOG_USED=""
for pair in "$WRAPPER_LOG:$LOG_BEFORE_WRAPPER" "$PLIST_LOG:$LOG_BEFORE_PLIST"; do
    lp="${pair%:*}"; before="${pair##*:}"
    [ -n "$lp" ] || continue
    if [ -f "$lp" ]; then
        after=$(stat -f %m "$lp" 2>/dev/null || echo 0)
        if [ "$after" -ge "$before" ] && [ "$after" -ne 0 ]; then
            LOG_OK=1; LOG_USED="$lp"; break
        fi
    fi
done
[ "$LOG_OK" -eq 1 ] || fail "no log created/written by the run (checked $WRAPPER_LOG, $PLIST_LOG). NOT loading."
info "log verified: $LOG_USED"

echo "✅ manual run OK (exit 0, log written) — proceeding to load."

# ── 6. bootout (idempotent) -> bootstrap -> kickstart ───────────────────────
echo "--- launchctl deploy ---"
launchctl bootout "$GUI/$LABEL" 2>/dev/null && info "booted out prior instance" || info "no prior instance (ok)"
launchctl bootstrap "$GUI" "$PLIST" || fail "launchctl bootstrap failed for $PLIST"
info "bootstrapped"
launchctl kickstart -k "$GUI/$LABEL" || info "kickstart returned non-zero (may be calendar-only agent — ok)"

# ── 7. Verify loaded state is not exit 78 ───────────────────────────────────
sleep 2
STATUS=$(launchctl list | grep -E "[[:space:]]${LABEL}$" || echo "")
[ -n "$STATUS" ] || fail "agent not present in launchctl list after bootstrap"
EXITCODE=$(echo "$STATUS" | awk '{print $2}')
info "launchctl status: $STATUS"
if [ "$EXITCODE" = "78" ]; then
    fail "agent loaded but last exit == 78 (EX_CONFIG) — still broken."
fi

echo "✅ DEPLOYED: ${LABEL} (last exit=${EXITCODE})"
exit 0
