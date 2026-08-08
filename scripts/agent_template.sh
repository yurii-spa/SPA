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
#   - wake-storm hardened: the pre-python readiness section (cd + getcwd +
#     spa_core readable + python executable) retries up to WAKE_RETRY_MAX
#     times with WAKE_RETRY_SLEEP pauses; on give-up logs WAKE_STORM_GIVEUP
#     and exits 75 (EX_TEMPFAIL). Python is launched exactly ONCE — module
#     errors are never retried/masked.
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
# MODULE_ARGS — extra args for the module/script.
#   • Copy-adapted wrapper (mode A, same file): declare an ARRAY — MODULE_ARGS=(--flag value).
#   • Separate parent wrapper that `export`s and then calls this template as a CHILD /bin/bash:
#     a bash ARRAY does NOT survive `export` across a process boundary — it arrives as NOTHING.
#     (Incident 2026-08: `export MODULE_ARGS=(paper)` in agent_aggressive_lab.sh reached the
#     module as ZERO args → mode "both" → the nightly backtest rewrote the forward paper book.)
#     Export a plain STRING instead — MODULE_ARGS="paper" / MODULE_ARGS="--flag value" — and it
#     is split on whitespace here. Pinned by spa_core/tests/test_aggressive_lab_series_rewrite.py.
if ! declare -p MODULE_ARGS >/dev/null 2>&1; then
    MODULE_ARGS=()
elif [[ "$(declare -p MODULE_ARGS 2>/dev/null)" != "declare -a"* ]]; then
    # arrived via the environment as a plain string (the only form that CAN arrive) → split
    read -r -a MODULE_ARGS <<< "${MODULE_ARGS}"
fi
# ────────────────────────────────────────────────────────────────────────────

# SPA_AGENT_REPO_ROOT / SPA_AGENT_PYTHON exist ONLY so tests can point the
# wrapper at a sandbox fixture; production plists never set them.
REPO_ROOT="${SPA_AGENT_REPO_ROOT:-/Users/yuriikulieshov/Documents/SPA_Claude}"
PYTHON="${SPA_AGENT_PYTHON:-/Users/yuriikulieshov/miniconda3/bin/python3}"

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

TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ── Wake-storm resilience (incident 2026-08-04T07:00Z) ──────────────────────
# After the Mac wakes from sleep, access to ~/Documents (TCC / FileProvider
# mediated) transiently fails with EINTR for a few seconds: shell-init cannot
# getcwd, reads of repo files are interrupted, and `python -m` reports
# ModuleNotFoundError: 'spa_core' even though the tree is intact — 39 agents
# exited code=1 in the same second. Response: verify the environment is REALLY
# usable (cd by absolute path + getcwd + spa_core readable + python executable)
# and retry ONLY this pre-python section with short pauses. Python itself is
# launched exactly once — a genuine module error is NEVER masked by a retry.
# Total worst-case delay: (WAKE_RETRY_MAX-1) * WAKE_RETRY_SLEEP = 4*4s = 16s,
# well under launchd's scheduling cadence. On give-up we exit 75 (EX_TEMPFAIL)
# with an explicit WAKE_STORM_GIVEUP marker so monitoring can tell a transient
# wake failure apart from a logic failure (code=1) or a config failure (78).
WAKE_RETRY_MAX="${WAKE_RETRY_MAX:-5}"
WAKE_RETRY_SLEEP="${WAKE_RETRY_SLEEP:-4}"

READY_FAIL=""
startup_ready() {
    # (1) cd by ABSOLUTE path — never relies on the (possibly lost) inherited cwd
    if ! cd "$REPO_ROOT" 2>/dev/null; then READY_FAIL="cd:$REPO_ROOT"; return 1; fi
    # (2) getcwd must actually work (the shell-init/getcwd failure class)
    if ! pwd -P >/dev/null 2>&1; then READY_FAIL="getcwd"; return 1; fi
    # (3) the package python will import must be READABLE right now — a real
    #     1-byte read, because at wake the file exists but reads get EINTR
    if ! head -c 1 "$REPO_ROOT/spa_core/__init__.py" >/dev/null 2>&1; then
        READY_FAIL="read:spa_core/__init__.py"; return 1
    fi
    # (4) the interpreter itself must be executable
    if ! [ -x "$PYTHON" ]; then READY_FAIL="python:$PYTHON"; return 1; fi
    READY_FAIL=""
    return 0
}

# ── Свежесть кода перед стартом (решение владельца 2026-08-08, вариант 1) ────
# Карточка `owner-decision-chasovye-agenty-do-sutok-krutyat-staryi`.
#
# ПОЧЕМУ. Пуши уходят прямо на origin через API и НЕ трогают это дерево, а флот
# исполняет именно его. Синхронизация шла раз в сутки, перед утренним циклом —
# для агента, просыпающегося раз в день, этого хватает; для ЧАСОВОГО агента это
# означает до суток работы на старом коде. Не абстрактно: защита от столкновения
# сессий выложена 07.08 и к 08.08 всё ещё не работала в проде — за эти сутки одна
# сессия удалила рабочий каталог другой, вторая умерла, не доставив работу.
#
# УСЛОВИЕ ВЛАДЕЛЬЦА, ЖЁСТКОЕ: GitHub недоступен ⇒ агент СТАРТУЕТ НА СТАРОМ КОДЕ и
# ГОВОРИТ об этом. Отказ синхронизации не имеет права превращаться в отказ агента —
# иначе сеть становится единой точкой отказа всего флота. Поэтому синк здесь
# полностью «мягкий»: он не в `set -e`, его код возврата только логируется.
#
# ТРОТТЛИНГ. Синк общий для всех агентов, а их ~56 и часть просыпается каждые
# несколько минут. Гонять `git checkout` каждым запуском — лишняя нагрузка и гонка
# за один и тот же индекс. Если дерево синхронизировали меньше SYNC_MAX_AGE секунд
# назад — код уже свежий, и пропуск НЕ является работой на старом коде.
SYNC_MAX_AGE="${SPA_AGENT_SYNC_MAX_AGE:-600}"     # 10 минут
SYNC_SCRIPT="$REPO_ROOT/scripts/code_sync_from_origin.sh"
# /tmp, а не data/: правило доставки запрещает синку трогать data/ (там трек).
SYNC_STAMP="${SPA_CODE_SYNC_STAMP:-/tmp/spa_code_sync.stamp}"

maybe_sync_code() {
    # Выключается одной переменной — для ручного запуска на песочнице.
    [ "${SPA_AGENT_SKIP_SYNC:-0}" = "1" ] && return 0
    # Нет скрипта синка в ЭТОМ дереве — синхронизировать нечем и незачем.
    # (Условие намеренно про СКРИПТ, а не про «это песочница»: иначе ни один
    # тест не смог бы проверить сам вызов, и проводка снова осталась бы
    # непокрытой — урок цикла #144.)
    [ -x "$SYNC_SCRIPT" ] || return 0

    if [ -f "$SYNC_STAMP" ]; then
        local now age
        now=$(date +%s)
        age=$(( now - $(stat -f %m "$SYNC_STAMP" 2>/dev/null || echo 0) ))
        if [ "$age" -ge 0 ] && [ "$age" -lt "$SYNC_MAX_AGE" ]; then
            echo "[$(TS)] CODE_SYNC skip agent=${AGENT_NAME} age=${age}s < ${SYNC_MAX_AGE}s (код свежий)" >> "$LOG" 2>/dev/null || true
            return 0
        fi
    fi

    local rc=0
    /bin/bash "$SYNC_SCRIPT" >/dev/null 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
        touch "$SYNC_STAMP" 2>/dev/null || true
        echo "[$(TS)] CODE_SYNC ok agent=${AGENT_NAME}" >> "$LOG" 2>/dev/null || true
    else
        # ГОВОРИМ и идём дальше. Метку НЕ трогаем: следующий агент попробует снова.
        echo "[$(TS)] CODE_SYNC_STALE agent=${AGENT_NAME} rc=${rc} — origin недоступен либо синк откатился; СТАРТУЮ НА СТАРОМ КОДЕ" >> "$LOG" 2>/dev/null || true
    fi
    return 0
}

attempt=1
until startup_ready; do
    if [ "$attempt" -ge "$WAKE_RETRY_MAX" ]; then
        MARKER="[$(TS)] WAKE_STORM_GIVEUP agent=${AGENT_NAME} attempts=$attempt last_fail=${READY_FAIL} repo=$REPO_ROOT"
        # /tmp is a local FS and stays reachable during the storm; still fall
        # back to stderr (launchd .err) if even the log append fails.
        echo "$MARKER" >> "$LOG" 2>/dev/null || echo "$MARKER" >&2
        exit 75  # EX_TEMPFAIL: environment not ready, NOT an agent logic error
    fi
    echo "[$(TS)] wake-storm retry ${attempt}/${WAKE_RETRY_MAX} agent=${AGENT_NAME} fail=${READY_FAIL}" >> "$LOG" 2>/dev/null || true
    attempt=$((attempt + 1))
    sleep "$WAKE_RETRY_SLEEP"
done

# Проводка. Стоит ПОСЛЕ startup_ready (дерево уже точно читаемо) и ДО запуска
# python — иначе агент успел бы стартовать на старом коде. Урок цикла #144:
# функция без вызова оставляет все тесты зелёными, а фичу мёртвой в проде,
# поэтому вызов закреплён отдельным тестом.
maybe_sync_code

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
