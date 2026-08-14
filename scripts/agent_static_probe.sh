#!/bin/bash
# ============================================================================
# scripts/agent_static_probe.sh — validate a launchd agent WITHOUT STARTING IT.
# ============================================================================
#
# WHY THIS EXISTS (incident 2026-08-08)
#   The pre-deploy gate (scripts/check_agent_before_deploy.sh) proves an agent
#   works by RUNNING IT ONCE. For an agent that exits, that is exactly right.
#   For a NEVER-EXITING agent it is worse than the failure it guards against:
#
#     measured 2026-08-08 — the gate ran `spa_core.telegram.bot` a second time
#     (pid 90696) beside the live production bot. Two pollers on ONE Telegram
#     token means 409-conflicts on getUpdates: the owner's taps and commands go
#     to whichever poller wins the race, and part of them are simply lost. The
#     second instance lived for the gate's whole RUN_TIMEOUT (~3 minutes) and
#     the gate printed nothing at all — it looked like a wedged check, not like
#     "we are currently jamming the live alert channel".
#
#   So for long-lived agents the run-once must be replaced by checks that prove
#   the SAME things without a process: the entrypoint is really executable
#   (mode 100644 on a launchd entrypoint = exit 126, the 2026-08-04 fleet
#   outage), the shell wrapper parses, the python it targets really imports (in
#   a SEPARATE process — an import failure in-process would be masked), and the
#   log paths launchd writes to are actually writable.
#
# FAIL-CLOSED. Anything unmeasurable is a FAIL, never a silent pass — with ONE
# named exception: an agent whose entrypoint contains no python at all
# (cloudflared, cc-kanban) has no import target by construction. That is said
# OUT LOUD in the output ("no python target"), it is not dressed up as a pass
# of a check that never ran.
#
# NOTHING HERE STARTS THE AGENT. Not the wrapper, not the module: `-m mod` runs
# the module as __main__, `import mod` does not. A module that does real work at
# import time never returns and is reported as a FAIL, not waited out.
#
# Usage:
#   agent_static_probe.sh --is-long-lived <plist>      # 0 = long-lived, 1 = not
#   agent_static_probe.sh --plist-bool <key> <plist>   # prints true|false|dict|""
#   agent_static_probe.sh --targets <plist> <repo_root>  # what would be probed
#   agent_static_probe.sh --probe   <plist> <repo_root>  # the actual probe
#
# Env:
#   SPA_PROBE_PYTHON   interpreter for the import probe (default: pinned
#                      miniconda python, else python3 from PATH)
#   PROBE_TIMEOUT      seconds for a single import probe (default 30)
# ============================================================================

set -uo pipefail

PROBE_TIMEOUT="${PROBE_TIMEOUT:-30}"
PINNED_PY="/Users/yuriikulieshov/miniconda3/bin/python3"

die()  { echo "❌ PROBE FAIL: $*" >&2; exit 1; }
info() { echo "   $*"; }

usage() {
    echo "usage: agent_static_probe.sh --is-long-lived <plist>" >&2
    echo "       agent_static_probe.sh --plist-bool <key> <plist>" >&2
    echo "       agent_static_probe.sh --targets|--probe <plist> <repo_root>" >&2
    exit 64
}

# ── run a command with a hard wall-clock timeout (macOS has no timeout(1)) ───
# Returns the command's exit code, or 124 if it was killed for exceeding <secs>.
run_with_timeout() {
    local secs="$1"; shift
    "$@" &
    local cmd_pid=$!
    (
        sleep "$secs"
        kill -0 "$cmd_pid" 2>/dev/null && kill -TERM "$cmd_pid" 2>/dev/null
        sleep 2
        kill -0 "$cmd_pid" 2>/dev/null && kill -KILL "$cmd_pid" 2>/dev/null
    ) &
    local wd_pid=$!
    wait "$cmd_pid" 2>/dev/null
    local rc=$?
    kill "$wd_pid" 2>/dev/null
    wait "$wd_pid" 2>/dev/null
    if [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then return 124; fi
    return "$rc"
}

# ── plist readers (awk; the same both-forms parsing the gate uses) ───────────
# Reads the VALUE, not merely the presence of the key: `<key>KeepAlive</key>
# <false/>` must never read as "KeepAlive". Prints true|false|dict|"" (unknown).
plist_bool() {
    awk -v key="$1" '
        # <dict> is tested FIRST: a KeepAlive dict body (e.g.
        # <dict><key>SuccessfulExit</key><false/></dict>) contains <false/>, and
        # reading that as "false" would send a restart-forever agent down the
        # run-once path — the very thing this file exists to prevent.
        $0 ~ "<key>"key"</key>" {
            line = $0
            if (line ~ /<dict>/)    { print "dict";  exit }
            if (line ~ /<true\/>/)  { print "true";  exit }
            if (line ~ /<false\/>/) { print "false"; exit }
            grab = 1; next
        }
        grab && /<dict>/    { print "dict";  exit }
        grab && /<true\/>/  { print "true";  exit }
        grab && /<false\/>/ { print "false"; exit }
        grab && /<key>/     { print "";      exit }
    ' "$2"
}

plist_string() {
    awk -v key="$1" '
        $0 ~ "<key>"key"</key>.*<string>" {
          line=$0; sub(".*<key>"key"</key>[^<]*<string>", "", line)
          sub(/<\/string>.*/, "", line); print line; exit
        }
        $0 ~ "<key>"key"</key>" {grab=1; next}
        grab && /<string>/ {
          line=$0; sub(/.*<string>/, "", line); sub(/<\/string>.*/, "", line)
          print line; exit
        }
    ' "$2"
}

plist_has_key() { grep -q "<key>$1</key>" "$2" 2>/dev/null; }

plist_progargs() {
    awk '
        /<key>ProgramArguments<\/key>/ {grab=1; next}
        grab && /<\/array>/ {exit}
        grab && /<string>/ {
          line=$0; sub(/.*<string>/, "", line); sub(/<\/string>.*/, "", line)
          print line
        }
    ' "$1"
}

# ── long-lived = supervised forever AND not on a schedule ───────────────────
# KeepAlive true (or a KeepAlive dict — a restart POLICY is still "restart it
# forever") with no StartInterval / StartCalendarInterval. A KeepAlive-false
# agent on a calendar is an ordinary run-once agent: it must keep the run-once
# check, and a hang in it must stay a FAIL.
is_long_lived() {
    local plist="$1" ka sched=0
    ka="$(plist_bool KeepAlive "$plist")"
    plist_has_key StartInterval "$plist" && sched=1
    plist_has_key StartCalendarInterval "$plist" && sched=1
    { [ "$ka" = "true" ] || [ "$ka" = "dict" ]; } && [ "$sched" -eq 0 ]
}

resolve_python() {
    if [ -n "${SPA_PROBE_PYTHON:-}" ] && [ -x "${SPA_PROBE_PYTHON}" ]; then
        echo "${SPA_PROBE_PYTHON}"; return 0
    fi
    [ -x "$PINNED_PY" ] && { echo "$PINNED_PY"; return 0; }
    command -v python3 2>/dev/null || echo ""
}

# ── target collection ───────────────────────────────────────────────────────
# MODULES / SCRIPTS are what the agent would hand to python. PY_SEEN records
# "this agent is a python agent at all" — the difference between "no target
# because there is nothing to import" and "no target because we failed to
# work it out", which must NOT be answered the same way.
MODULES=()
SCRIPTS=()
PY_SEEN=0

_valid_module() {
    case "$1" in
        ""|*[!A-Za-z0-9_.]*) return 1 ;;
        .*|*.)               return 1 ;;
    esac
    return 0
}

_add_module() {
    _valid_module "$1" || return 0
    local m
    for m in ${MODULES[@]+"${MODULES[@]}"}; do [ "$m" = "$1" ] && return 0; done
    MODULES+=("$1")
}

_add_script() {
    local s
    for s in ${SCRIPTS[@]+"${SCRIPTS[@]}"}; do [ "$s" = "$1" ] && return 0; done
    SCRIPTS+=("$1")
}

# Collect targets from a token list (plist ProgramArguments, or one wrapper line).
collect_from_tokens() {
    local prev="" t mod tmpl_at=-1 i=0
    for t in "$@"; do
        case "$t" in
            *python3|*python)        PY_SEEN=1 ;;
            */agent_template.sh)     PY_SEEN=1; tmpl_at=$i ;;
        esac
        [ "$prev" = "-m" ] && { PY_SEEN=1; _add_module "$t"; }
        case "$t" in
            *.py) PY_SEEN=1; _add_script "$t" ;;
        esac
        # uvicorn-style "package.module:attr" — the importable part is the module
        case "$t" in
            *:*)
                mod="${t%%:*}"
                if _valid_module "$mod"; then PY_SEEN=1; _add_module "$mod"; fi
                ;;
        esac
        prev="$t"
        i=$((i + 1))
    done
    # agent_template.sh <agent_name> <module-or-script> [args...] (generic mode B)
    if [ "$tmpl_at" -ge 0 ]; then
        local target_idx=$((tmpl_at + 2)) j=0
        for t in "$@"; do
            if [ "$j" -eq "$target_idx" ]; then
                case "$t" in
                    *.py) _add_script "$t" ;;
                    *)    _add_module "$t" ;;
                esac
                break
            fi
            j=$((j + 1))
        done
    fi
}

# Copy-adapted wrappers (mode A) carry the target in their header instead.
collect_from_wrapper() {
    local wrapper="$1" line val
    [ -f "$wrapper" ] || return 0
    case "$(basename "$wrapper")" in
        agent_template.sh) return 0 ;;   # the template itself has no per-agent target
    esac
    # (a) lines that invoke python / the template — tokenise and reuse the rules
    while IFS= read -r line; do
        case "$line" in
            \#*) continue ;;
        esac
        # shellcheck disable=SC2086
        local toks=()
        read -r -a toks <<< "$line"
        [ "${#toks[@]}" -ge 1 ] && collect_from_tokens ${toks[@]+"${toks[@]}"}
    done < <(grep -E 'python|agent_template\.sh' "$wrapper" 2>/dev/null | grep -vE '^[[:space:]]*#')
    # (b) header vars: MODULE="x.y" / MODULE="${MODULE:-x.y}" / RUN_SCRIPT="/abs/x.py"
    val="$(grep -E '^[[:space:]]*(export[[:space:]]+)?MODULE=' "$wrapper" 2>/dev/null | head -n1 \
           | sed -E 's/^[[:space:]]*(export[[:space:]]+)?MODULE=//; s/^"//; s/"$//; s/^\$\{MODULE:-//; s/\}$//')"
    [ -n "$val" ] && { PY_SEEN=1; _add_module "$val"; }
    val="$(grep -E '^[[:space:]]*(export[[:space:]]+)?RUN_SCRIPT=' "$wrapper" 2>/dev/null | head -n1 \
           | sed -E 's/^[[:space:]]*(export[[:space:]]+)?RUN_SCRIPT=//; s/^"//; s/"$//; s/^\$\{RUN_SCRIPT:-//; s/\}$//')"
    case "$val" in
        ""|*'$'*) : ;;
        *)        PY_SEEN=1; _add_script "$val" ;;
    esac
}

# --targets ONLY: find the same file inside the tree we were asked about.
#
# A plist names its entrypoint by ABSOLUTE path (that is what launchd execs), so on any
# tree other than the canonical one — a worktree, a CI checkout, a restored backup — that
# path does not exist. `collect_from_wrapper` then reads nothing and the agent is reported
# as `python_agent: 0`: a python agent silently described as "runs no python". Measured
# 2026-08-14 on the Linux CI runner, where it made the "every long-lived agent resolves a
# target" check pass VACUOUSLY — the worst possible outcome for a fail-CLOSED guard.
#
# The import probe already runs with `cd $ROOT` / `PYTHONPATH=$ROOT`, i.e. the modules are
# taken from ROOT while the entrypoint came from the plist's tree — one probe, two trees.
# Here that is made consistent for reporting only. `--probe` is NOT touched: the file
# launchd will exec must exist and be executable AT ITS REAL PATH, and that refusal stays.
#
# Tries the longest matching tail first (…/scripts/agent_x.sh before …/agent_x.sh), so a
# same-named file elsewhere in the tree cannot quietly win. Prints the path, or fails.
rebase_into_root() {
    local cand="${1#/}" root="$2"
    while [ -n "$cand" ]; do
        if [ -e "$root/$cand" ]; then echo "$root/$cand"; return 0; fi
        case "$cand" in
            */*) cand="${cand#*/}" ;;
            *)   break ;;
        esac
    done
    return 1
}

# The file launchd actually execs: the bash wrapper if there is one, else argv[0].
resolve_entrypoint() {
    local first="$1"; shift
    case "$first" in
        */bash|/usr/bin/env|*/sh)
            local a
            for a in "$@"; do
                case "$a" in
                    *.sh) echo "$a"; return 0 ;;
                esac
            done
            echo "$first"; return 0
            ;;
        *) echo "$first"; return 0 ;;
    esac
}

# ── modes ───────────────────────────────────────────────────────────────────
MODE="${1:-}"
[ -n "$MODE" ] || usage
shift

case "$MODE" in
    --is-long-lived)
        PLIST="${1:-}"
        [ -n "$PLIST" ] || usage
        [ -f "$PLIST" ] || { echo "plist not readable: $PLIST" >&2; exit 2; }
        is_long_lived "$PLIST" && exit 0 || exit 1
        ;;
    --plist-bool)
        KEY="${1:-}"; PLIST="${2:-}"
        [ -n "$KEY" ] && [ -n "$PLIST" ] || usage
        [ -f "$PLIST" ] || { echo "plist not readable: $PLIST" >&2; exit 2; }
        plist_bool "$KEY" "$PLIST"
        exit 0
        ;;
    --targets|--probe)
        PLIST="${1:-}"; ROOT="${2:-}"
        [ -n "$PLIST" ] && [ -n "$ROOT" ] || usage
        [ -f "$PLIST" ] || die "plist not readable: $PLIST"
        [ -d "$ROOT" ] || die "repo root not a directory: $ROOT"
        ;;
    *)
        usage
        ;;
esac

# ── parse the plist ─────────────────────────────────────────────────────────
PROGARGS=()
while IFS= read -r _arg; do
    PROGARGS+=("$_arg")
done < <(plist_progargs "$PLIST")
[ "${#PROGARGS[@]}" -ge 1 ] || die "could not parse ProgramArguments from $PLIST"

ENTRY="$(resolve_entrypoint ${PROGARGS[@]+"${PROGARGS[@]}"})"

# Reporting mode only — see rebase_into_root. The probe path below is untouched.
ENTRY_SOURCE="plist"
if [ "$MODE" = "--targets" ] && [ ! -e "$ENTRY" ]; then
    if _rebased="$(rebase_into_root "$ENTRY" "$ROOT")"; then
        ENTRY="$_rebased"
        ENTRY_SOURCE="rebased-to-root"
    else
        ENTRY_SOURCE="missing"
    fi
fi

collect_from_tokens ${PROGARGS[@]+"${PROGARGS[@]}"}
collect_from_wrapper "$ENTRY"

if [ "$MODE" = "--targets" ]; then
    echo "entrypoint: $ENTRY"
    # Said OUT LOUD: "the entrypoint is not in this tree" must never be readable as
    # "this agent runs no python" (fail-CLOSED in the reporting layer too).
    echo "entrypoint_source: $ENTRY_SOURCE"
    echo "python_agent: $PY_SEEN"
    for m in ${MODULES[@]+"${MODULES[@]}"}; do echo "module: $m"; done
    for s in ${SCRIPTS[@]+"${SCRIPTS[@]}"}; do echo "script: $s"; done
    exit 0
fi

# ── the probe itself ────────────────────────────────────────────────────────
echo "--- static probe (agent is NOT started) ---"

# 1. entrypoint exists and is EXECUTABLE.
#    2026-08-04: a file-level deploy stripped the exec bit from 67 of 69
#    launchd entrypoints — every agent died with 126 and no heartbeat noticed.
[ -e "$ENTRY" ] || die "entrypoint does not exist: $ENTRY"
[ -x "$ENTRY" ] || die "entrypoint is NOT executable: $ENTRY (launchd exec → exit 126). Fix the mode ON ORIGIN, not by hand after each deploy."
info "entrypoint: $ENTRY ✅ executable"

# 2. the shell wrapper must parse (bash -n executes nothing).
case "$ENTRY" in
    *.sh)
        if ! bash -n "$ENTRY" 2>/tmp/spa_probe_syntax.$$; then
            _msg="$(head -n3 /tmp/spa_probe_syntax.$$ 2>/dev/null)"
            rm -f /tmp/spa_probe_syntax.$$ 2>/dev/null
            die "wrapper has a syntax error: $ENTRY — $_msg"
        fi
        rm -f /tmp/spa_probe_syntax.$$ 2>/dev/null
        info "wrapper syntax: ✅ bash -n OK"
        ;;
esac

# 3. python targets.
if [ "${#MODULES[@]}" -eq 0 ] && [ "${#SCRIPTS[@]}" -eq 0 ]; then
    if [ "$PY_SEEN" -eq 1 ]; then
        die "this IS a python agent, but no import target could be resolved from $PLIST / $ENTRY — refusing (fail-CLOSED). Name the target in the wrapper header (MODULE=/RUN_SCRIPT=) or in ProgramArguments."
    fi
    info "python target: NONE — the entrypoint runs no python (import probe not applicable, and this is said out loud, not passed off as a check)"
else
    PY="$(resolve_python)"
    [ -n "$PY" ] && [ -x "$PY" ] || die "no usable python interpreter for the import probe (tried SPA_PROBE_PYTHON, $PINNED_PY, python3 on PATH)"
    info "import probe interpreter: $PY"
    for m in ${MODULES[@]+"${MODULES[@]}"}; do
        _out="$(mktemp "${TMPDIR:-/tmp}/spa_probe_import.XXXXXX")"
        ( cd "$ROOT" && PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
            run_with_timeout "$PROBE_TIMEOUT" "$PY" -c 'import importlib,sys; importlib.import_module(sys.argv[1])' "$m" \
            >"$_out" 2>&1 )
        _rc=$?
        if [ "$_rc" -eq 124 ]; then
            rm -f "$_out"
            die "module '$m' did not finish IMPORTING within ${PROBE_TIMEOUT}s — it does real work at import time. That is a finding, not something to wait out."
        elif [ "$_rc" -ne 0 ]; then
            _tail="$(tail -n 5 "$_out" 2>/dev/null)"
            rm -f "$_out"
            die "module '$m' does NOT import (exit $_rc): $_tail"
        fi
        rm -f "$_out"
        info "import: $m ✅ (separate process, __main__ NOT executed)"
    done
    for s in ${SCRIPTS[@]+"${SCRIPTS[@]}"}; do
        [ -f "$s" ] || die "target script does not exist: $s"
        _out="$(mktemp "${TMPDIR:-/tmp}/spa_probe_compile.XXXXXX")"
        ( cd "$ROOT" && run_with_timeout "$PROBE_TIMEOUT" "$PY" -m py_compile "$s" >"$_out" 2>&1 )
        _rc=$?
        if [ "$_rc" -ne 0 ]; then
            _tail="$(tail -n 5 "$_out" 2>/dev/null)"
            rm -f "$_out"
            die "target script does NOT compile: $s — $_tail"
        fi
        rm -f "$_out"
        info "compile: $s ✅ (py_compile, script NOT executed)"
    done
fi

# 4. launchd's own log paths must be writable, or the job dies before any code
#    runs (the ~/Documents/TCC form of this is refused earlier by the gate).
for _key in StandardOutPath StandardErrorPath; do
    _lp="$(plist_string "$_key" "$PLIST")"
    [ -n "$_lp" ] || continue
    _dir="$(dirname "$_lp")"
    [ -d "$_dir" ] || die "$_key points at '$_lp' but its directory does not exist ($_dir) — launchd cannot write it"
    [ -w "$_dir" ] || die "$_key points at '$_lp' but its directory is not writable ($_dir) — launchd cannot write it"
    info "$_key: $_lp ✅ writable dir"
done

echo "✅ STATIC PROBE PASSED — nothing was started, no live instance was disturbed."
exit 0
