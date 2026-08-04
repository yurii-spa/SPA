#!/bin/bash
# scripts/code_sync_from_origin.sh — close the origin→prod gap (ADR pending; card
# agent-prod-clean-checkout-variant2, owner full-approve 2026-08-04).
#
# WHY: pushes land on origin via the GitHub API and never touch this tree, while the
# launchd fleet EXECUTES this tree — by 2026-08-03 prod ran July-15 code and none of the
# delivered fixes (incl. ADR-053/TVL fail-closed) were live. This script makes
# "delivered to origin" == "running in prod" again before every cycle.
#
# RULES (hard-learned, see memory git-push-api-drift):
#   * CODE ONLY, whole directories: spa_core/ scripts/ tests/ + the two root pushers.
#     NEVER data/ (live track), docs/, nimbalyst-local/, .claude/, KANBAN.json.
#   * Whole dirs, never single files — a point-copied file with a new dependency broke
#     the entire adapters package import on 2026-08-03.
#   * Exec-bit safety net after checkout — origin stored agent scripts 100644 once and
#     the whole fleet died with launchd exit 126 (fixed on origin 6cc2863dd, but a
#     regression must never kill the fleet again).
#   * Fail-safe: pre-sync tar snapshot; ANY post-sync verification failure → restore
#     snapshot, exit 1 loudly. Callers proceed on the previous (working) code.
#   * Never git reset / never touches git refs — only `checkout origin/main -- <paths>`.
#
# Status file: data/code_sync_status.json (atomic). Log: /tmp/spa_code_sync.log.
# Exit: 0 = in sync or synced+verified; 1 = sync failed and was rolled back.

main() {
    PYTHON=/Users/yuriikulieshov/miniconda3/bin/python3
    REPO="$HOME/Documents/SPA_Claude"
    CODE_PATHS=(spa_core scripts tests push_to_github.py push_to_github_batch.py)
    LOG=/tmp/spa_code_sync.log
    cd "$REPO" || exit 1

    log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

    write_status() {  # $1=result $2=detail $3=files_changed $4=exec_fixed
        "$PYTHON" - "$1" "$2" "$3" "$4" <<'PYEOF'
import sys, datetime, subprocess
from spa_core.utils.atomic import atomic_save
result, detail, changed, exec_fixed = sys.argv[1:5]
sha = subprocess.run(["git", "rev-parse", "origin/main"], capture_output=True,
                     text=True).stdout.strip()
atomic_save({
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "result": result, "detail": detail, "origin_main": sha,
    "files_changed": int(changed or 0), "exec_bits_fixed": int(exec_fixed or 0),
    "source": "code_sync_from_origin",
}, "data/code_sync_status.json")
PYEOF
    }

    log "code-sync: fetch origin/main"
    if ! git fetch origin main -q 2>>"$LOG"; then
        log "code-sync: FETCH FAILED (offline?) — keeping current code (fail-open for the cycle, loud)"
        write_status "FETCH_FAILED" "git fetch origin failed; cycle runs on previous code" 0 0
        return 0   # do not block the cycle on a network blip; drift monitor stays the alarm
    fi

    CHANGED=$(git diff --name-only origin/main -- "${CODE_PATHS[@]}" | wc -l | tr -d ' ')
    if [ "$CHANGED" = "0" ]; then
        log "code-sync: already in sync with origin/main"
        write_status "IN_SYNC" "no code drift" 0 0
        return 0
    fi

    SNAP="/tmp/spa_code_presync_$(date -u +%Y%m%dT%H%M%SZ).tgz"
    log "code-sync: $CHANGED file(s) drifted — snapshot to $SNAP, then whole-dir checkout"
    if ! tar czf "$SNAP" "${CODE_PATHS[@]}" 2>>"$LOG"; then
        log "code-sync: SNAPSHOT FAILED — refusing to sync without a rollback point"
        write_status "SNAPSHOT_FAILED" "tar failed; sync refused (fail-closed)" "$CHANGED" 0
        return 1
    fi

    git checkout origin/main -- "${CODE_PATHS[@]}" 2>>"$LOG"

    # Exec-bit safety net (fleet-killer class, 2026-08-04): every *.sh under scripts/ must be +x.
    EXEC_FIXED=0
    while IFS= read -r -d '' f; do
        chmod +x "$f" && EXEC_FIXED=$((EXEC_FIXED + 1))
    done < <(find scripts -name '*.sh' ! -perm -100 -print0 2>/dev/null)
    [ "$EXEC_FIXED" -gt 0 ] && log "code-sync: restored exec bit on $EXEC_FIXED script(s) (origin mode regression!)"

    # Verification: the synced tree must IMPORT. Version alone is not workability
    # (deployment_drift showed 0 drift while imports were broken on 2026-08-03).
    if "$PYTHON" -c "import spa_core.adapters, spa_core.risk.policy, spa_core.paper_trading.cycle_runner" 2>>"$LOG"; then
        log "code-sync: synced $CHANGED file(s) + import probe OK"
        write_status "SYNCED" "whole-dir checkout + import probe OK" "$CHANGED" "$EXEC_FIXED"
        return 0
    fi

    log "code-sync: IMPORT PROBE FAILED after sync — ROLLING BACK from $SNAP"
    tar xzf "$SNAP" -C "$REPO" 2>>"$LOG"
    if "$PYTHON" -c "import spa_core.adapters" 2>>"$LOG"; then
        log "code-sync: rollback verified — cycle will run on PREVIOUS code; origin needs a fix"
        write_status "ROLLED_BACK" "post-sync import failed; restored pre-sync code" "$CHANGED" "$EXEC_FIXED"
    else
        log "code-sync: CRITICAL — rollback import probe ALSO failed; manual intervention required"
        write_status "CRITICAL" "sync and rollback both failed import probe" "$CHANGED" "$EXEC_FIXED"
    fi
    return 1
}

main "$@"
exit $?
