#!/usr/bin/env bash
# git_autopush.sh v2 — SPA автоматичний git push через launchd
# Запускається кожну годину. PAT з macOS Keychain (ніколи з файлів).
# Логи: /tmp/spa_git_autopush.log | /tmp/spa_git_autopush_err.log
#
# Виправлення v2:
#  - git fetch BEFORE commit (щоб знати актуальний стан remote)
#  - git rebase origin/main BEFORE add+commit (уникаємо diverged histories)
#  - Без дублів у логу (stdout ≠ log file)
#  - Видалення stale index.lock

set -uo pipefail

REPO_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
LOG="/tmp/spa_git_autopush.log"
LOCK="/tmp/spa_git_autopush.lock"
MAX_LOG_LINES=500

log() {
    # Пишемо лише у файл (stdout іде в StandardOutPath plist → той же файл → дублі)
    # Щоб уникнути дублів — тільки file write
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

trim_log() {
    if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
        tail -300 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
    fi
}

# --- Singleton lock ---
if [ -f "$LOCK" ]; then
    LOCK_PID=$(cat "$LOCK" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        log "Already running (PID $LOCK_PID), skip"
        exit 0
    fi
    log "Removing stale lock (PID $LOCK_PID)"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

trim_log
log "=== git_autopush v2 start ==="

# --- Перейти в репозиторій ---
if ! cd "$REPO_DIR"; then
    log "❌ Cannot cd to $REPO_DIR"
    exit 1
fi

# --- Видалити stale index.lock ---
if [ -f ".git/index.lock" ] && [ ! -s ".git/index.lock" ]; then
    rm -f ".git/index.lock"
    log "Removed stale .git/index.lock"
fi

# --- Отримати PAT з Keychain (SECRETS POLICY: ніколи з файлів) ---
TOKEN=""
# 1. GITHUB_PAT_SPA / spa
TOKEN=$(security find-generic-password -s "GITHUB_PAT_SPA" -a "spa" -w 2>/dev/null || true)
# 2. GITHUB_PAT_SPA без фільтру по акаунту
if [ -z "$TOKEN" ]; then
    TOKEN=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
fi
# 3. SPA_GITHUB_TOKEN
if [ -z "$TOKEN" ]; then
    TOKEN=$(security find-generic-password -a "$USER" -s "SPA_GITHUB_TOKEN" -w 2>/dev/null || true)
fi
# 4. env fallback
if [ -z "$TOKEN" ]; then
    TOKEN="${GITHUB_PAT:-${GITHUB_TOKEN:-}}"
fi

if [ -z "$TOKEN" ]; then
    log "❌ PAT не знайдено в Keychain. Перервано."
    exit 1
fi
log "PAT found (${#TOKEN} chars)"

# --- GIT_ASKPASS (токен НІКОЛИ не пишеться на диск) ---
ASKPASS="$(mktemp /tmp/spa_askpass.XXXXXX)"
chmod 700 "$ASKPASS"
cat > "$ASKPASS" << 'ASKPASS_SCRIPT'
#!/usr/bin/env bash
case "$1" in
  *Username*) echo "x-access-token" ;;
  *Password*) echo "$SPA_PUSH_TOKEN" ;;
esac
ASKPASS_SCRIPT
trap 'rm -f "$ASKPASS" "$LOCK"' EXIT INT TERM

REMOTE_URL="https://github.com/yurii-spa/SPA.git"

export SPA_PUSH_TOKEN="$TOKEN"
export GIT_ASKPASS="$ASKPASS"
export GIT_TERMINAL_PROMPT=0

# --- КРОК 1: fetch актуального стану remote (ПЕРЕД будь-якими локальними змінами) ---
log "Fetching remote state..."
if git fetch "$REMOTE_URL" main:refs/remotes/origin/main >> "$LOG" 2>&1; then
    log "Fetch OK"
else
    log "⚠️ Fetch failed (network?), proceeding with cached remote state"
fi

# --- КРОК 2: Переконатись що ми на main і HEAD = origin/main ---
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    # Detached HEAD — прикріплюємо до main
    log "Detached HEAD detected, resetting to origin/main..."
    git reset --hard origin/main >> "$LOG" 2>&1 || true
    echo "ref: refs/heads/main" > .git/HEAD
    log "HEAD reattached to main"
fi

# Перевіримо що local main == origin/main (або local ahead)
LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_REF=$(git rev-parse origin/main 2>/dev/null || echo "")
if [ -n "$REMOTE_REF" ] && [ "$LOCAL" != "$REMOTE_REF" ]; then
    # Перевірити: чи local is behind remote?
    if git merge-base --is-ancestor "$LOCAL" "$REMOTE_REF" 2>/dev/null; then
        log "Local is behind remote — fast-forward to origin/main"
        git reset --hard origin/main >> "$LOG" 2>&1 || true
    else
        log "Histories diverged — rebasing onto origin/main..."
        git rebase origin/main >> "$LOG" 2>&1 || {
            log "⚠️ Rebase failed — hard reset to origin/main"
            git rebase --abort >> "$LOG" 2>&1 || true
            git reset --hard origin/main >> "$LOG" 2>&1 || true
        }
    fi
fi

# --- КРОК 3: git add (з урахуванням .gitignore) ---
git add -A
log "git add -A done"

# --- Є що комітити? ---
if git diff --cached --quiet; then
    log "Nothing to commit — working tree clean"
    exit 0
fi

# --- Статистика ---
CHANGED_FILES=$(git diff --cached --name-only | wc -l | tr -d ' ')
STAT=$(git diff --cached --stat | tail -1)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
MSG="auto: sync $TIMESTAMP ($CHANGED_FILES files) [skip ci]"

# --- Commit ---
if ! git commit -m "$MSG" --no-verify >> "$LOG" 2>&1; then
    log "❌ git commit failed"
    exit 1
fi
log "Committed: $MSG"
log "Stats: $STAT"

# --- Push ---
log "Pushing to $REMOTE_URL ..."

do_push() {
    git push "$REMOTE_URL" HEAD:main >> "$LOG" 2>&1
}

if do_push; then
    log "✅ Push OK"
else
    PUSH_EXIT=$?
    log "Push failed (exit $PUSH_EXIT) — trying rebase + retry..."
    if git pull --rebase "$REMOTE_URL" main >> "$LOG" 2>&1; then
        log "Pull-rebase OK — retrying push..."
        if do_push; then
            log "✅ Push OK (after rebase)"
        else
            log "❌ Push FAILED after rebase — rolling back commit"
            git reset HEAD~1
            log "Commit rolled back — retry next run"
            exit 1
        fi
    else
        log "❌ Pull-rebase failed — rolling back commit"
        git reset HEAD~1
        log "Commit rolled back — retry next run"
        exit 1
    fi
fi
