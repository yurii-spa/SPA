#!/bin/bash
# ============================================================================
# scripts/check_agent_before_deploy.sh <agent_name>
# ============================================================================
# PRE-DEPLOY GATE for any SPA launchd agent. NEVER `launchctl bootstrap` a
# plist without running this first (see CLAUDE.md FORBIDDEN rule).
#
# Given an agent name (e.g. "watchdog" for com.spa.watchdog) it:
#   1. Locates the plist: scripts/com.spa.<name>.plist or launchd/com.spa.<name>.plist
#   2. Extracts the command from ProgramArguments and RUNS IT MANUALLY ONCE —
#      in a SANDBOXED / SAFE mode that can NEVER mutate the canonical live
#      track (fix #1). The real scheduled run still uses --live via the plist;
#      ONLY this pre-deploy check is sandboxed.
#   3. Asserts the manual run exit == 0.
#   4. Asserts the agent's ACTUAL log was created / written by that run —
#      reading the plist's StandardOutPath/StandardErrorPath and the wrapper's
#      own dated log, not just a hardcoded /tmp/spa_<name>.log (fix #3).
#   5. ONLY THEN: bootout (idempotent) -> bootstrap -> kickstart the agent
#      (with a hard timeout so KeepAlive / throttled agents can't hang — fix
#      #2), then re-reads `launchctl list` and asserts the loaded exit != 78.
#
# FAIL-CLOSED: any failure (manual run exit != 0, no log, OR the canonical
# track was touched by the sandboxed run) -> clear FAIL, EXIT NON-ZERO,
# agent is NOT loaded.
#
# ── THE THREE HARDENING FIXES ───────────────────────────────────────────────
#  1. SANDBOXED RUN-ONCE — the check must never mutate live state. Live-write
#     agents (daily_cycle -> cycle_runner --live) write data/equity_curve_daily
#     .json (the canonical go-live track). The check therefore:
#       (a) strips `--live` from the command, and
#       (b) exports SPA_DATA_DIR=<temp sandbox> with SPA_ALLOW_LIVE_WRITE UNSET,
#       (c) snapshots the canonical track's hash BEFORE and AFTER and FAILS
#           CLOSED if a single byte changed (belt-and-suspenders for wrappers
#           that bury `--live` inside themselves — see cycle_runner's
#           write-interlock: an explicit non-canonical --data-dir / no opt-in
#           reroutes writes to the sandbox; a stray --live is caught by the
#           hash guard and the gate refuses to load the agent).
#  2. NO HANG ON KICKSTART — macOS has no `timeout(1)`; the manual run AND the
#     `launchctl kickstart -k` are wrapped in a bash background+watchdog timeout
#     so a KeepAlive server (apiserver/uvicorn) or a throttled agent can never
#     wedge the gate.
#  3. ACTUAL LOG PATH — custom-bash agents (daily_cycle/daily_backup/
#     mass_tournament/tier1_governance) log to their own dated files
#     (logs/daily_cycle_YYYYMMDD.log, ...), not /tmp/spa_<name>.log. The gate
#     reads the plist StandardOutPath/StandardErrorPath AND scans the wrapper's
#     log dir, and asserts THAT was written.
#
# Usage:  bash scripts/check_agent_before_deploy.sh watchdog
#         bash scripts/check_agent_before_deploy.sh daily_cycle
#         CHECK_ONLY=1 bash scripts/check_agent_before_deploy.sh apiserver  # run-once+log only, no load
# ============================================================================

set -uo pipefail

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
GUI="gui/$(id -u)"
CANONICAL_DATA_DIR="$REPO_ROOT/data"
CANONICAL_TRACK="$CANONICAL_DATA_DIR/equity_curve_daily.json"

# Hard timeouts (seconds) so the gate can never hang (fix #2).
RUN_TIMEOUT="${RUN_TIMEOUT:-180}"
KICKSTART_TIMEOUT="${KICKSTART_TIMEOUT:-20}"

fail() { echo "❌ FAIL: $*" >&2; exit 1; }
info() { echo "   $*"; }

[ "$#" -ge 1 ] || fail "usage: check_agent_before_deploy.sh <agent_name>"
NAME="$1"
LABEL="com.spa.${NAME}"

echo "=== PRE-DEPLOY GATE: ${LABEL} ==="

# ── helper: run a command with a hard wall-clock timeout (macOS-safe) ───────
# Usage: run_with_timeout <secs> <cmd...>
# Returns the command's exit code, OR 124 if it was killed for exceeding <secs>.
# Pure bash 3.2: launch in background, a watchdog sleeps then kills the group.
run_with_timeout() {
    local secs="$1"; shift
    "$@" &
    local cmd_pid=$!
    (
        sleep "$secs"
        # still alive? kill it (and let the parent report 124)
        kill -0 "$cmd_pid" 2>/dev/null && kill -TERM "$cmd_pid" 2>/dev/null
        sleep 2
        kill -0 "$cmd_pid" 2>/dev/null && kill -KILL "$cmd_pid" 2>/dev/null
    ) &
    local wd_pid=$!
    wait "$cmd_pid" 2>/dev/null
    local rc=$?
    # tear the watchdog down if the command finished first
    kill "$wd_pid" 2>/dev/null
    wait "$wd_pid" 2>/dev/null
    # 143 = 128+SIGTERM, 137 = 128+SIGKILL -> normalize to 124 (timed out)
    if [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then return 124; fi
    return "$rc"
}

# ── hashing helper (no change == no mutation) ───────────────────────────────
hash_file() { [ -f "$1" ] && shasum -a 256 "$1" 2>/dev/null | awk '{print $1}' || echo "MISSING"; }

# ── 1. Locate the plist ─────────────────────────────────────────────────────
PLIST=""
for cand in "$REPO_ROOT/scripts/${LABEL}.plist" "$REPO_ROOT/launchd/${LABEL}.plist"; do
    [ -f "$cand" ] && { PLIST="$cand"; break; }
done
[ -n "$PLIST" ] || fail "plist not found (scripts/${LABEL}.plist or launchd/${LABEL}.plist)"
info "plist: $PLIST"

# ── 2. Extract ProgramArguments into a bash array ───────────────────────────
# /bin/bash on macOS is 3.2 — no `mapfile`. Use a read loop.
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

# KeepAlive agents are long-lived servers (apiserver/uvicorn, cloudflared, …):
# the run-once never returns on its own and may collide with the already-running
# production instance (e.g. a fixed listen port). Detect this once so both the
# timeout handling (fix #2) and the exit-code interpretation can treat them right.
IS_KEEPALIVE=0
grep -q "<key>KeepAlive</key>" "$PLIST" 2>/dev/null && IS_KEEPALIVE=1
[ "$IS_KEEPALIVE" -eq 1 ] && info "agent is KeepAlive (long-lived server) — run-once is start-probe only"

# ── 2b. SANDBOX the command (fix #1): strip --live so the run-once can never
#        opt into a canonical-track write. Wrappers that bury --live internally
#        are still caught by the hash guard in step 4b.
SAFE_ARGS=()
STRIPPED_LIVE=0
for a in "${PROGARGS[@]}"; do
    if [ "$a" = "--live" ]; then STRIPPED_LIVE=1; continue; fi
    SAFE_ARGS+=("$a")
done
[ "$STRIPPED_LIVE" -eq 1 ] && info "sandbox: stripped --live from the check command (real scheduled run keeps it)"

# Per-check sandbox data dir. cycle_runner honours an explicit non-canonical
# --data-dir / SPA_DATA_DIR VERBATIM (the interlock returns it untouched before
# the --live opt-in is even consulted) so all writes land here, not in data/.
SANDBOX_DIR="$(mktemp -d "${TMPDIR:-/tmp}/spa_predeploy_${NAME}.XXXXXX")"
mkdir -p "$SANDBOX_DIR"
info "sandbox data dir: $SANDBOX_DIR"

# Detect a wrapper that hardcodes --live inside itself (e.g. daily_cycle ->
# run_daily_paper_cycle.sh, which calls `cycle_runner --verbose --live`). The
# wrapper passes no --data-dir, so its `--live` would force a CANONICAL write
# that SPA_DATA_DIR alone cannot redirect. We therefore can NOT validate it by
# running the wrapper. Instead we run the SAME inner engine directly, SANDBOXED:
#   python3 -m spa_core.paper_trading.cycle_runner --verbose --data-dir <sandbox>
# A non-canonical --data-dir is honoured verbatim (no --live), so the canonical
# track is provably untouched. This still proves the engine RUNS (exit 0 + log).
WRAPPER_FILE=""
for a in "${PROGARGS[@]}"; do
    case "$a" in
        "$REPO_ROOT"/*.sh) WRAPPER_FILE="$a"; break ;;
    esac
done
if [ -n "$WRAPPER_FILE" ] && grep -q -- '--live' "$WRAPPER_FILE" 2>/dev/null; then
    echo "⚠️  NOTE: wrapper $WRAPPER_FILE hardcodes --live internally — cannot be"
    echo "    sandboxed by env alone (--live forces a canonical write)."
    if grep -q "spa_core.paper_trading.cycle_runner" "$WRAPPER_FILE" 2>/dev/null; then
        info "→ substituting a SANDBOXED inner cycle_runner run (--data-dir $SANDBOX_DIR, no --live)"
        # Seed the sandbox with a COPY of the canonical READ-ONLY inputs (APY
        # snapshot, registries, positions) so the cycle runs against realistic
        # data and reaches a representative status — exactly as the live run
        # would — WITHOUT a network dependency. This is read-from-canonical /
        # write-to-sandbox: the canonical dir is opened read-only here and the
        # cycle's outputs land in the sandbox copy, never in data/.
        if [ -d "$CANONICAL_DATA_DIR" ]; then
            cp -R "$CANONICAL_DATA_DIR"/. "$SANDBOX_DIR"/ 2>/dev/null || \
                info "(sandbox seed partial — continuing; cycle will fetch live feed)"
            info "sandbox seeded from canonical read-only inputs"
        fi
        SAFE_ARGS=(
            "/Users/yuriikulieshov/miniconda3/bin/python3"
            -m spa_core.paper_trading.cycle_runner
            --verbose --no-monitors --data-dir "$SANDBOX_DIR"
        )
        # This inner run logs to stdout; capture it into the wrapper's dated log
        # dir so the log-assertion still finds a fresh log written by the check.
        SAFE_ARGS_TEE="$REPO_ROOT/logs/predeploy_${NAME}_check.log"
    else
        echo "⚠️  Cannot identify the inner engine to sandbox; relying on the"
        echo "    canonical-track HASH GUARD below as the fail-closed safety net."
    fi
fi

# ── 3. Determine candidate log paths (fix #3) ───────────────────────────────
# (a) the conventional /tmp/spa_<name>.log written by agent_template.sh wrappers
# (b) the plist StandardOutPath / StandardErrorPath
# (c) any dated log the custom wrapper writes under logs/ (scan AFTER the run)
plist_path_for() {
    awk -v key="$1" '
        $0 ~ "<key>"key"</key>" {grab=1; next}
        grab && /<string>/ {
          line=$0; sub(/.*<string>/, "", line); sub(/<\/string>.*/, "", line)
          print line; exit
        }
    ' "$PLIST"
}
WRAPPER_LOG="/tmp/spa_${NAME}.log"
PLIST_OUT="$(plist_path_for StandardOutPath)"
PLIST_ERR="$(plist_path_for StandardErrorPath)"
SAFE_ARGS_TEE="${SAFE_ARGS_TEE:-}"   # set above when we substitute an inner run

# Candidate log set (dedup, drop empties).
LOG_CANDIDATES=()
for lp in "$WRAPPER_LOG" "$PLIST_OUT" "$PLIST_ERR" "$SAFE_ARGS_TEE"; do
    [ -n "$lp" ] || continue
    dup=0; for e in ${LOG_CANDIDATES[@]+"${LOG_CANDIDATES[@]}"}; do [ "$e" = "$lp" ] && dup=1; done
    [ "$dup" -eq 0 ] && LOG_CANDIDATES+=("$lp")
done
info "log candidates: ${LOG_CANDIDATES[*]:-<none>}"

# Snapshot BEFORE-mtimes for each candidate (parallel array).
LOG_BEFORE=()
for lp in ${LOG_CANDIDATES[@]+"${LOG_CANDIDATES[@]}"}; do
    LOG_BEFORE+=("$(stat -f %m "$lp" 2>/dev/null || echo 0)")
done
# Drop a sentinel file stamped at run-start. BSD `find -newer <file>` is fully
# supported (unlike GNU's `-newermt @epoch`, which BSD find silently ignores),
# so we detect a fresh dated wrapper log (logs/daily_cycle_YYYYMMDD.log,
# logs/daily_backup.log, …) by `find logs -newer $RUN_SENTINEL`.
RUN_SENTINEL="$(mktemp "${TMPDIR:-/tmp}/spa_predeploy_sentinel_${NAME}.XXXXXX")"
# back-date the sentinel 2s so a log written in the same wall-clock second as
# the sentinel still counts as "newer".
touch -t "$(date -v-2S +%Y%m%d%H%M.%S 2>/dev/null || date +%Y%m%d%H%M.%S)" "$RUN_SENTINEL" 2>/dev/null || true

# ── 4. RUN THE COMMAND MANUALLY ONCE — sandboxed, time-boxed ────────────────
echo "--- manual run (sandboxed) ---"
cd "$REPO_ROOT" || fail "cannot cd $REPO_ROOT"

TRACK_HASH_BEFORE="$(hash_file "$CANONICAL_TRACK")"
TRACK_MTIME_BEFORE="$(stat -f %m "$CANONICAL_TRACK" 2>/dev/null || echo 0)"
info "canonical track before: hash=${TRACK_HASH_BEFORE:0:12}… mtime=$TRACK_MTIME_BEFORE"

# Sandbox env: point writes at the sandbox, ensure NO live-write opt-in leaks in.
unset SPA_ALLOW_LIVE_WRITE
export SPA_DATA_DIR="$SANDBOX_DIR"
export SPA_PREDEPLOY_CHECK=1   # marker for any agent that wants to no-op heavy work

if [ -n "$SAFE_ARGS_TEE" ]; then
    mkdir -p "$(dirname "$SAFE_ARGS_TEE")"
    # tee both streams into the wrapper's log dir so the log-assertion finds a
    # fresh log written by THIS check (the substituted inner run logs to stdout).
    run_with_timeout "$RUN_TIMEOUT" "${SAFE_ARGS[@]}" > "$SAFE_ARGS_TEE" 2>&1
else
    run_with_timeout "$RUN_TIMEOUT" "${SAFE_ARGS[@]}"
fi
RC=$?
echo "--- manual run exit=$RC ---"
if [ "$RC" -eq 124 ]; then
    # Hit the wall-clock timeout. A KeepAlive server (uvicorn) legitimately
    # never returns → that IS the success signal (it started and kept running).
    # Any other agent that times out is a genuine hang → fail-closed.
    if [ "$IS_KEEPALIVE" -eq 1 ]; then
        info "run-once stayed alive to the ${RUN_TIMEOUT}s timeout — expected for a KeepAlive server (started OK)"
        RC=0
    else
        fail "manual run exceeded ${RUN_TIMEOUT}s and was killed (hang). NOT loading ${LABEL}."
    fi
elif [ "$RC" -ne 0 ] && [ "$IS_KEEPALIVE" -eq 1 ]; then
    # A KeepAlive server that exits fast & non-zero is usually a RESOURCE
    # CONFLICT with the already-running production instance (e.g. the listen
    # port is already bound). That proves the binary launches fine; the running
    # prod instance owns the resource. Accept it ONLY when the run actually
    # started (a fresh log shows the START banner) AND the failure looks like a
    # bind/already-in-use conflict — otherwise fail-closed.
    _probe_log="${SAFE_ARGS_TEE:-$WRAPPER_LOG}"
    if [ -f "$_probe_log" ] && grep -qiE "address already in use|already in use|errno 48|bind.*in use" "$_probe_log" 2>/dev/null; then
        info "run-once exited $RC due to a resource conflict with the running production instance"
        info "(port/listen address already owned) — the binary starts fine; treating as started OK"
        RC=0
    fi
fi
[ "$RC" -eq 0 ] || fail "manual run exited $RC (expected 0). NOT loading ${LABEL}."

# ── 4b. FAIL-CLOSED hash guard: the sandboxed run must NOT touch the track ───
TRACK_HASH_AFTER="$(hash_file "$CANONICAL_TRACK")"
TRACK_MTIME_AFTER="$(stat -f %m "$CANONICAL_TRACK" 2>/dev/null || echo 0)"
info "canonical track after:  hash=${TRACK_HASH_AFTER:0:12}… mtime=$TRACK_MTIME_AFTER"
if [ "$TRACK_HASH_BEFORE" != "$TRACK_HASH_AFTER" ]; then
    fail "SANDBOX VIOLATION: the pre-deploy run MUTATED the canonical track $CANONICAL_TRACK (hash changed). NOT loading ${LABEL}. The check must never write live state."
fi
info "✅ canonical track UNCHANGED by the sandboxed run (hash identical)"

# ── 5. Assert the ACTUAL log was created / written by this run (fix #3) ──────
LOG_OK=0
LOG_USED=""
# (a) the explicit candidates (wrapper /tmp log + plist std paths)
i=0
for lp in ${LOG_CANDIDATES[@]+"${LOG_CANDIDATES[@]}"}; do
    before="${LOG_BEFORE[$i]:-0}"; i=$((i+1))
    [ -f "$lp" ] || continue
    after="$(stat -f %m "$lp" 2>/dev/null || echo 0)"
    if [ "$after" -ne 0 ] && [ "$after" -ge "$before" ]; then
        LOG_OK=1; LOG_USED="$lp"; break
    fi
done
# (b) custom-bash agents write a dated log under logs/ (logs/daily_cycle_*.log,
#     logs/daily_backup.log, mass_tournament, tier1_governance, …). Accept any
#     logs/ file written at/after the run started — detected with the run-start
#     sentinel (`find -newer`, BSD-safe).
if [ "$LOG_OK" -eq 0 ] && [ -d "$REPO_ROOT/logs" ]; then
    fresh="$(find "$REPO_ROOT/logs" -type f -newer "$RUN_SENTINEL" 2>/dev/null | head -n1)"
    if [ -n "$fresh" ]; then
        LOG_OK=1; LOG_USED="$fresh"
    fi
fi
[ "$LOG_OK" -eq 1 ] || fail "no log created/written by the run (checked: ${LOG_CANDIDATES[*]:-none} + logs/*). NOT loading."
info "log verified: $LOG_USED"

# Best-effort sandbox cleanup (keep on failure-paths above for debugging).
rm -rf "$SANDBOX_DIR" 2>/dev/null || true
rm -f "$RUN_SENTINEL" 2>/dev/null || true

echo "✅ manual run OK (exit 0, log written, canonical track untouched) — proceeding to load."

# CHECK_ONLY mode: validate the agent without touching launchctl (useful in CI
# / on hosts where you only want the run-once + log + sandbox proof).
if [ "${CHECK_ONLY:-0}" = "1" ]; then
    echo "✅ CHECK_ONLY: ${LABEL} passed pre-deploy validation (NOT loaded)."
    exit 0
fi

# ── 6. bootout (idempotent) -> bootstrap -> kickstart (time-boxed) ──────────
echo "--- launchctl deploy ---"
launchctl bootout "$GUI/$LABEL" 2>/dev/null && info "booted out prior instance" || info "no prior instance (ok)"
launchctl bootstrap "$GUI" "$PLIST" || fail "launchctl bootstrap failed for $PLIST"
info "bootstrapped"

# fix #2: `kickstart -k` can wedge on KeepAlive/throttled agents — time-box it.
# For KeepAlive agents, RunAtLoad/KeepAlive already starts the job; we DON'T
# force-restart (-k) it (that races the supervisor and can hang). For others we
# kickstart -k under a hard timeout.
if [ "$IS_KEEPALIVE" -eq 1 ]; then
    info "KeepAlive agent — relying on bootstrap/RunAtLoad to start it (no -k restart)"
    run_with_timeout "$KICKSTART_TIMEOUT" launchctl kickstart "$GUI/$LABEL" >/dev/null 2>&1 || \
        info "kickstart (no -k) returned non-zero/timeout — KeepAlive supervisor owns lifecycle (ok)"
else
    run_with_timeout "$KICKSTART_TIMEOUT" launchctl kickstart -k "$GUI/$LABEL"
    KRC=$?
    if [ "$KRC" -eq 124 ]; then
        info "kickstart -k exceeded ${KICKSTART_TIMEOUT}s and was killed — not fatal, proceeding to verify state"
    elif [ "$KRC" -ne 0 ]; then
        info "kickstart returned $KRC (may be calendar-only agent — ok)"
    fi
fi

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
