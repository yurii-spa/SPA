#!/bin/bash
# ============================================================================
# scripts/agent_template.sh — CANONICAL launchd wrapper for ANY SPA agent.
# ============================================================================
#
# WHY THIS EXISTS
#   launchd CANNOT directly exec the miniconda python. A plist whose
#   ProgramArguments is
#       [/Users/yuriikulieshov/miniconda3/bin/python3, -m, <module>]
#   fails with exit 78 (EX_CONFIG) — the program never even runs, no log is
#   written. A /bin/bash WRAPPER that calls the SAME python works perfectly
#   (verified: bash-wrapper plist -> exit 0, python inner exit 0, log written).
#
#   THEREFORE: every agent plist must invoke
#       ProgramArguments = [/bin/bash, <this-kind-of-wrapper>]
#   and NEVER call the miniconda python directly. See CLAUDE.md FORBIDDEN rule.
#
# HOW TO USE (two ways)
#   (A) Copy-adapt per agent (RECOMMENDED for permanent agents):
#         cp scripts/agent_template.sh scripts/agent_<name>.sh
#       then edit the two header vars below:
#         AGENT_NAME="<name>"                      # -> log = /tmp/spa_<name>.log
#         MODULE="spa_core.path.to.module"         # python -m target
#       (optional) MODULE_ARGS=(--flag value)      # extra args for the module
#       (optional) RUN_SCRIPT="/abs/path/script.py" to run a SCRIPT instead of -m
#       Then point the plist at the copy:
#         ProgramArguments = [/bin/bash, /abs/.../scripts/agent_<name>.sh]
#
#   (B) Generic / ad-hoc — pass the target on the command line:
#         /bin/bash scripts/agent_template.sh <name> <module-or-script> [args...]
#       e.g.  /bin/bash scripts/agent_template.sh watchdog spa_core.monitoring.watchdog
#       If the 2nd arg ends in .py it is run as a script, else as `python -m`.
#
# CONTRACT
#   - cd to repo root, uses the pinned miniconda python.
#   - logs stdout+stderr to /tmp/spa_<AGENT_NAME>.log with timestamped
#     START / EXIT banner lines.
#   - captures the python exit code and EXITS WITH IT (propagated to launchd).
#   - secrets are NEVER written here — read from Keychain inside the python.
# ============================================================================

set -uo pipefail

# ── PER-AGENT HEADER — edit these when copy-adapting (mode A) ────────────────
AGENT_NAME="${AGENT_NAME:-}"        # e.g. "watchdog"  (blank -> taken from $1)
MODULE="${MODULE:-}"               # e.g. "spa_core.monitoring.watchdog"
RUN_SCRIPT="${RUN_SCRIPT:-}"        # e.g. "/abs/.../scripts/foo.py" (alt to MODULE)
# MODULE_ARGS — extra args for the module/script. Declare as an array; leave
# empty for none. (Declared set-u-safe below.)
if ! declare -p MODULE_ARGS >/dev/null 2>&1; then MODULE_ARGS=(); fi
# ────────────────────────────────────────────────────────────────────────────

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

# launchd hands us a minimal PATH; ensure the standard dirs are present so the
# python (and any subprocess it spawns, e.g. /usr/bin/security for Keychain) is
# resolvable. HOME is required for Keychain access. Self-sufficient: a plist
# pointing here needs no EnvironmentVariables of its own.
export PATH="/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export HOME="${HOME:-/Users/yuriikulieshov}"

# ── Generic mode (B): pull target from CLI args if header vars are unset ─────
if [ -z "$AGENT_NAME" ] && [ "$#" -ge 1 ]; then
    AGENT_NAME="$1"; shift
fi
if [ -z "$MODULE" ] && [ -z "$RUN_SCRIPT" ] && [ "$#" -ge 1 ]; then
    case "$1" in
        *.py) RUN_SCRIPT="$1" ;;
        *)    MODULE="$1" ;;
    esac
    shift
    # any remaining CLI args are module/script args
    if [ "$#" -ge 1 ]; then MODULE_ARGS=("$@"); fi
fi

if [ -z "$AGENT_NAME" ]; then
    echo "agent_template.sh: AGENT_NAME not set (header var or \$1)" >&2
    exit 64  # EX_USAGE
fi
if [ -z "$MODULE" ] && [ -z "$RUN_SCRIPT" ]; then
    echo "agent_template.sh: neither MODULE nor RUN_SCRIPT set" >&2
    exit 64
fi

LOG="/tmp/spa_${AGENT_NAME}.log"

cd "$REPO_ROOT" || { echo "agent_template.sh: cannot cd $REPO_ROOT" >&2; exit 78; }

TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }

{
    echo "==================================================================="
    echo "[$(TS)] START agent=${AGENT_NAME} pid=$$"
    if [ -n "$RUN_SCRIPT" ]; then
        echo "[$(TS)]   exec: $PYTHON $RUN_SCRIPT ${MODULE_ARGS[*]:-}"
        "$PYTHON" "$RUN_SCRIPT" ${MODULE_ARGS[@]+"${MODULE_ARGS[@]}"}
    else
        echo "[$(TS)]   exec: $PYTHON -m $MODULE ${MODULE_ARGS[*]:-}"
        "$PYTHON" -m "$MODULE" ${MODULE_ARGS[@]+"${MODULE_ARGS[@]}"}
    fi
    RC=$?
    echo "[$(TS)] EXIT agent=${AGENT_NAME} code=$RC"
    echo "==================================================================="
    exit $RC
} >> "$LOG" 2>&1
