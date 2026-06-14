#!/bin/bash
# auto_push.sh — Automatic sequential push of all pending push_v*.sh scripts
# Tracks completed pushes in .push_log so each script runs only once.
# Safe to run multiple times: already-pushed scripts are skipped.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/.."
LOG="$SCRIPT_DIR/.push_log"
LOCK="$SCRIPT_DIR/.push.lock"

# Singleton lock — prevent overlapping runs
if [ -f "$LOCK" ]; then
    LOCK_PID=$(cat "$LOCK" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "$(date): auto_push already running (PID $LOCK_PID), skipping"
        exit 0
    fi
fi
echo $$ > "$LOCK"

cleanup() { rm -f "$LOCK"; }
trap cleanup EXIT INT TERM

touch "$LOG"

PUSHED=0
SKIPPED=0
FAILED=0

# Must run from project root so push scripts find push_to_github.py
cd "$PROJECT_DIR"

for f in $(ls "$SCRIPT_DIR"/push_v*.sh 2>/dev/null | sort -V); do
    name=$(basename "$f")
    if grep -qxF "$name" "$LOG" 2>/dev/null; then
        SKIPPED=$((SKIPPED+1))
        continue
    fi

    echo "$(date): pushing $name ..."
    if bash "$f"; then
        echo "$name" >> "$LOG"
        PUSHED=$((PUSHED+1))
        echo "$(date): ✅ $name done"
        sleep 3
    else
        echo "$(date): ❌ $name FAILED — will retry next run"
        FAILED=$((FAILED+1))
    fi
done

echo "$(date): auto_push complete — pushed=$PUSHED skipped=$SKIPPED failed=$FAILED"
