#!/bin/bash
# install_bts_agents.command
# Double-click in Finder to install BTS LaunchAgents.
# Safe to run multiple times (idempotent).

set -euo pipefail
LAUNCH_AGENTS=~/Library/LaunchAgents
SPA=~/Documents/SPA_Claude/scripts

for plist in com.spa.bts-feed.plist com.spa.bts-monitor.plist; do
    if [ ! -f "$SPA/$plist" ]; then
        echo "Waiting for $plist..."
        for i in $(seq 1 60); do
            sleep 5
            [ -f "$SPA/$plist" ] && break
        done
    fi
    if [ -f "$SPA/$plist" ]; then
        cp "$SPA/$plist" "$LAUNCH_AGENTS/$plist"
        launchctl unload "$LAUNCH_AGENTS/$plist" 2>/dev/null || true
        launchctl load "$LAUNCH_AGENTS/$plist"
        echo "OK $plist installed"
    else
        echo "MISSING $plist not found -- Phase 1+2 may not have completed yet"
    fi
done
echo "BTS agents installation complete"
