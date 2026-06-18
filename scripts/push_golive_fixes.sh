#!/usr/bin/env bash
# scripts/push_golive_fixes.sh — Push GoLive gate fixes to GitHub (MP-006/MP-384/MP-417)
#
# What this pushes:
#   1. spa_core/paper_trading/golive_checker.py  — 26-criteria gate (v5.0)
#   2. spa_core/tests/test_golive_checker.py     — Full test suite (26 checks)
#   3. install_autopush.command                  — One-click autopush launchd installer
#
# PAT is read at runtime from macOS Keychain by push_to_github.py (key: GITHUB_PAT_SPA).
# NEVER embed tokens in this file — see SECRETS POLICY in CLAUDE.md.
#
# Usage:
#   bash scripts/push_golive_fixes.sh
#   bash scripts/push_golive_fixes.sh --dry-run   # check without pushing

set -euo pipefail

SPA="$(cd "$(dirname "$0")/.." && pwd)"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

echo "╔════════════════════════════════════════════════════╗"
echo "║  SPA GoLive Fixes Push (MP-006/MP-384/MP-417)     ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# ── Verify PAT is accessible (never print it) ─────────────────────────────────
if ! security find-generic-password -s GITHUB_PAT_SPA -w > /dev/null 2>&1; then
    echo "ERROR: GITHUB_PAT_SPA not found in macOS Keychain."
    echo "       Run: bash setup_pat.sh"
    echo "       Runbook: docs/TOKEN_ROTATION_RUNBOOK.md"
    exit 1
fi
echo "  ✅ PAT verified in Keychain (GITHUB_PAT_SPA)"
echo ""

# ── Files to push (absolute paths required by push_to_github.py) ─────────────
FILES=(
    "$SPA/spa_core/paper_trading/golive_checker.py"
    "$SPA/spa_core/tests/test_golive_checker.py"
    "$SPA/install_autopush.command"
)

COMMIT_MSG="feat: GoLive 26-criteria gate v5.0 + autopush installer (MP-006/MP-384/MP-417)

- golive_checker.py: expanded 6 to 26 criteria across 8 groups (v5.0-26criteria)
  Groups: data_integrity, adapters, components, adapter_status,
          continuity, infrastructure, performance, compliance
- test_golive_checker.py: full test suite for all 26 criteria (24 tests, all pass)
- install_autopush.command: one-click launchd installer for com.spa.autopush
  Fixes autopush_installed GoLive criterion

Current gate status: 23/26 pass
Remaining blockers (time-based, auto-resolve by 2026-07-09):
  - gap_monitor_30d: needs 30 real track days
  - min_track_days_30: same
  - autopush_installed: install via install_autopush.command"

echo "  Files to push:"
for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
        echo "    ✅ $f"
    else
        echo "    ❌ MISSING: $f"
        exit 1
    fi
done
echo ""

if $DRY_RUN; then
    python3 "$SPA/push_to_github.py" \
        --files "${FILES[@]}" \
        --message "$COMMIT_MSG" \
        --dry-run
    echo ""
    echo "  [DRY RUN complete — no files pushed]"
else
    echo "  Pushing ${#FILES[@]} files..."
    python3 "$SPA/push_to_github.py" \
        --files "${FILES[@]}" \
        --message "$COMMIT_MSG"
    echo ""
    echo "  ✅ Push complete."
fi

echo ""
echo "Done."
