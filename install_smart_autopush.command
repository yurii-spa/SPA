#!/usr/bin/env bash
# install_smart_autopush.command
# Устанавливает com.spa.autopush (smart_autopush.py — API-based, без git-конфликтов).
# Заменяет любой предыдущий вариант autopush (git_autopush.sh / auto_push.py / auto_push.sh).
#
# Двойной клик в Finder — всё делает автоматически.
# SECRETS POLICY: PAT не трогается и не выводится на экран.

set -euo pipefail

REPO="$HOME/Documents/SPA_Claude"
PLIST_SRC="$REPO/com.spa.autopush.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.spa.autopush.plist"
LABEL="com.spa.autopush"

echo "=== SPA Smart Autopush Installer ==="
echo "Repo:  $REPO"
echo "Plist: $PLIST_SRC"
echo ""

# --- Verify source plist exists ---
if [ ! -f "$PLIST_SRC" ]; then
    echo "❌ Not found: $PLIST_SRC"
    echo "   Make sure you're running from the repo root."
    read -rp "Press Enter to close..."
    exit 1
fi

# --- Verify smart_autopush.py exists ---
SCRIPT="$REPO/scripts/smart_autopush.py"
if [ ! -f "$SCRIPT" ]; then
    echo "❌ Not found: $SCRIPT"
    read -rp "Press Enter to close..."
    exit 1
fi

# --- Verify PAT is in Keychain ---
echo "Checking Keychain for GITHUB_PAT_SPA..."
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
    echo "⚠️  PAT not found in Keychain (GITHUB_PAT_SPA)."
    echo "   Run: bash setup_pat.sh  — then re-run this installer."
    read -rp "Press Enter to close..."
    exit 1
fi
echo "✅ PAT found (${#PAT} chars)"
unset PAT

# --- Unload existing daemon if installed ---
echo ""
echo "Unloading existing com.spa.autopush (if any)..."
launchctl unload "$PLIST_DST" 2>/dev/null && echo "  Unloaded" || echo "  (not loaded — OK)"

# --- Copy plist to LaunchAgents ---
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
echo "✅ Copied plist → $PLIST_DST"

# --- Load daemon ---
launchctl load "$PLIST_DST"
echo "✅ Loaded com.spa.autopush"

# --- Trigger first run immediately ---
launchctl start "$LABEL" 2>/dev/null && echo "✅ Started first run" || echo "⚠️  Start returned non-zero (may already be running)"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Monitor:"
echo "  launchctl list | grep com.spa.autopush"
echo "  tail -f /tmp/spa_autopush.log"
echo ""
echo "State file:  $REPO/data/autopush_state.json"
echo ""

# Show log after a brief pause
sleep 6
echo "--- /tmp/spa_autopush.log (last 20 lines) ---"
tail -20 /tmp/spa_autopush.log 2>/dev/null || echo "(log not yet created — first run may still be starting)"
echo ""
read -rp "Press Enter to close..."
