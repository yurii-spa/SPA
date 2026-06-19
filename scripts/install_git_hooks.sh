#!/usr/bin/env bash
# scripts/install_git_hooks.sh
# Installs SPA git hooks into .git/hooks/
#
# Usage: bash scripts/install_git_hooks.sh
# After install: hooks run automatically on every `git commit`

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

HOOKS_DIR="$REPO_DIR/.git/hooks"
PRE_COMMIT_SRC="$REPO_DIR/scripts/pre_commit_check.sh"
PRE_COMMIT_DST="$HOOKS_DIR/pre-commit"

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
  echo "❌ .git/hooks not found — is this a git repository?"
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
echo ""
echo "The hook runs 4 quality gates on every git commit:"
echo "  [1/4] KANBAN health"
echo "  [2/4] Architecture audit (errors only)"
echo "  [3/4] Core tests (fast subset)"
echo "  [4/4] Public API import check (spa_core.VERSION)"
echo ""
echo "To skip in an emergency: git commit --no-verify"
echo "To uninstall:            rm $PRE_COMMIT_DST"
exit 0
