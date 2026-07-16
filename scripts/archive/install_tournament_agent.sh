#!/bin/bash
# install_tournament_agent.sh
# Installs the SPA Tournament Engine launchd agent.
# Run from the project root: bash scripts/install_tournament_agent.sh

set -euo pipefail

PLIST_SRC="launchd/com.spa.tournament_engine.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.spa.tournament_engine.plist"
LABEL="com.spa.tournament_engine"

echo "=== SPA Tournament Engine — launchd install ==="

# Validate plist source exists
if [ ! -f "$PLIST_SRC" ]; then
    echo "ERROR: $PLIST_SRC not found. Run from project root."
    exit 1
fi

# Unload existing agent if already loaded (ignore errors if not loaded)
if launchctl list | grep -q "$LABEL" 2>/dev/null; then
    echo "Unloading existing agent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Copy plist
echo "Copying plist to LaunchAgents..."
cp "$PLIST_SRC" "$PLIST_DEST"

# Load agent
echo "Loading agent..."
launchctl load "$PLIST_DEST"

# Verify
if launchctl list | grep -q "$LABEL"; then
    echo "✅ Tournament Engine agent installed and loaded."
    echo "   Label:   $LABEL"
    echo "   Schedule: daily 09:00"
    echo "   Log:     /tmp/spa_tournament_engine.log"
    echo "   ErrLog:  /tmp/spa_tournament_engine_err.log"
else
    echo "⚠️  Agent may not have loaded. Check with: launchctl list | grep $LABEL"
fi
