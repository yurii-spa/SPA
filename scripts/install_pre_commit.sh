#!/usr/bin/env bash
# scripts/install_pre_commit.sh
# Installs the SPA pre-commit quality gate hook into .git/hooks/
# MP-1522 (v11.38)
#
# Usage:
#   bash scripts/install_pre_commit.sh
#   bash scripts/install_pre_commit.sh --dry-run   # preview only
#   bash scripts/install_pre_commit.sh --force     # overwrite without prompt
#   bash scripts/install_pre_commit.sh --uninstall # remove hook

set -euo pipefail

REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "❌ Not inside a git repository. Aborting."
  exit 1
}
cd "$REPO_DIR"

SRC="$REPO_DIR/scripts/pre_commit_check.sh"
HOOKS_DIR="$REPO_DIR/.git/hooks"
DST="$HOOKS_DIR/pre-commit"
DRY_RUN=0
FORCE=0
UNINSTALL=0

# ── Argument parsing ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --force)     FORCE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *)
      echo "Usage: $0 [--dry-run] [--force] [--uninstall]"
      exit 1
      ;;
  esac
done

echo "=== SPA Pre-commit Hook Installer ==="
echo "Repo : $REPO_DIR"
echo "Src  : $SRC"
echo "Dst  : $DST"
echo ""

# ── Uninstall mode ────────────────────────────────────────────────────────────
if [ "$UNINSTALL" -eq 1 ]; then
  if [ -f "$DST" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "[dry-run] Would remove: $DST"
    else
      rm "$DST"
      echo "✅ Pre-commit hook removed: $DST"
    fi
  else
    echo "⚠️  No pre-commit hook installed at: $DST"
  fi
  exit 0
fi

# ── Checks ────────────────────────────────────────────────────────────────────
if [ ! -f "$SRC" ]; then
  echo "❌ Source script not found: $SRC"
  exit 1
fi

if [ ! -d "$HOOKS_DIR" ]; then
  echo "❌ .git/hooks directory not found — is this a git repo?"
  exit 1
fi

# ── Backup existing hook ──────────────────────────────────────────────────────
if [ -f "$DST" ]; then
  if [ "$FORCE" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "⚠️  A pre-commit hook already exists at: $DST"
    printf "   Overwrite? [y/N] "
    read -r answer
    case "$answer" in
      [Yy]*) ;;
      *)
        echo "Aborted."
        exit 0
        ;;
    esac
  fi
  BACKUP="${DST}.bak.$(date +%Y%m%d%H%M%S)"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] Would backup: $DST → $BACKUP"
  else
    cp "$DST" "$BACKUP"
    echo "📦 Backed up: $BACKUP"
  fi
fi

# ── Install ───────────────────────────────────────────────────────────────────
if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] Would install: $SRC → $DST (chmod +x)"
  echo ""
  echo "Gates that would be active:"
  grep -E "^\s*#\s*\[" "$SRC" | head -10 || true
else
  cp "$SRC" "$DST"
  chmod +x "$DST"
  echo "✅ Installed: $DST"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Active quality gates:"
grep -E "^\s*echo.*\[.*/.*\]" "$SRC" | sed 's/.*echo /  /' | tr -d '"' | head -10 || true
echo ""
echo "The hook runs automatically on every 'git commit'."
echo "To bypass (emergencies only): git commit --no-verify"
echo "To uninstall:                 bash $0 --uninstall"
exit 0
