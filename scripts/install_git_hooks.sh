#!/usr/bin/env bash
# scripts/install_git_hooks.sh
# Installs SPA git hooks into .git/hooks/
#
# Usage: bash scripts/install_git_hooks.sh
# After install: hooks run automatically on every `git commit`

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# ОБЩИЙ hooks-каталог, а не "$REPO_DIR/.git/hooks": в worktree `.git` — это ФАЙЛ,
# и путь-литерал молча не находит цели. `--git-common-dir` даёт один и тот же
# каталог и из главного дерева, и из любого worktree (правило доставки, п.7).
GIT_COMMON_DIR="$(git -C "$REPO_DIR" rev-parse --git-common-dir 2>/dev/null || echo "")"
case "$GIT_COMMON_DIR" in
  "")  echo "❌ не git-репозиторий: $REPO_DIR"; exit 1 ;;
  /*)  ;;
  *)   GIT_COMMON_DIR="$REPO_DIR/$GIT_COMMON_DIR" ;;
esac
HOOKS_DIR="$GIT_COMMON_DIR/hooks"
mkdir -p "$HOOKS_DIR"
PRE_COMMIT_SRC="$REPO_DIR/scripts/pre_commit_check.sh"
PRE_COMMIT_DST="$HOOKS_DIR/pre-commit"
PRE_PUSH_SRC="$REPO_DIR/scripts/pre_push_check.sh"
PRE_PUSH_DST="$HOOKS_DIR/pre-push"

echo "=== SPA Git Hooks Installer ==="
echo "Repo  : $REPO_DIR"
echo "Hooks : $HOOKS_DIR"
echo ""

# Verify source exists
if [ ! -f "$PRE_COMMIT_SRC" ]; then
  echo "❌ Source not found: $PRE_COMMIT_SRC"
  echo "   Run from the repo root or check scripts/ directory."
  exit 1
fi

# Verify .git directory exists (must be run inside a git repo)
if [ ! -d "$HOOKS_DIR" ]; then
  echo "❌ hooks dir not found: $HOOKS_DIR"
  exit 1
fi

# Backup existing hook if present
if [ -f "$PRE_COMMIT_DST" ]; then
  BACKUP="${PRE_COMMIT_DST}.bak.$(date +%Y%m%d%H%M%S)"
  cp "$PRE_COMMIT_DST" "$BACKUP"
  echo "⚠️  Existing pre-commit hook backed up to: $BACKUP"
fi

# Install
cp "$PRE_COMMIT_SRC" "$PRE_COMMIT_DST"
chmod +x "$PRE_COMMIT_DST"

echo "✅ Pre-commit hook installed: $PRE_COMMIT_DST"

# ── pre-push (авария 2026-08-29: форс-пуш с устаревшей локальной головы
#    откатил main на 1249 коммитов; правило «только push_to_github.py» жило
#    в тексте и не имело исполнителя) ─────────────────────────────────────
if [ ! -f "$PRE_PUSH_SRC" ]; then
  echo "❌ Source not found: $PRE_PUSH_SRC"
  exit 1
fi
if [ -f "$PRE_PUSH_DST" ]; then
  cp "$PRE_PUSH_DST" "${PRE_PUSH_DST}.bak.$(date +%Y%m%d%H%M%S)"
fi
cp "$PRE_PUSH_SRC" "$PRE_PUSH_DST"
chmod +x "$PRE_PUSH_DST"
echo "✅ Pre-push hook installed:   $PRE_PUSH_DST"
echo ""
echo "The hook runs 4 quality gates on every git commit:"
echo "  [1/4] KANBAN health"
echo "  [2/4] Architecture audit (errors only)"
echo "  [3/4] Core tests (fast subset)"
echo "  [4/4] Public API import check (spa_core.VERSION)"
echo ""
echo "The pre-push hook refuses any push to main that would DROP commits:"
echo "  it asks the SERVER for main (not the stale remote-tracking ref)"
echo "  and fails CLOSED when it cannot measure."
echo ""
echo "To skip in an emergency: git commit --no-verify"
echo "                         SPA_ALLOW_HISTORY_REWRITE=1 git push ..."
echo "To uninstall:            rm $PRE_COMMIT_DST $PRE_PUSH_DST"
exit 0
