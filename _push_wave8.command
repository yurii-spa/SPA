#!/usr/bin/env bash
# _push_wave8.command
# MP-1470 (v10.86) — Wave 8 double-click push launcher
#
# Double-click this file in Finder to push all Wave 8 sprints (v10.75–v10.86)
# to GitHub. A Terminal window will open and show live progress.
# Log is also written to /tmp/wave8_push.log

cd "$HOME/Documents/SPA_Claude" || {
  echo "ERROR: Cannot cd to ~/Documents/SPA_Claude"
  exit 1
}

echo "=== SPA Wave 8 Push Launcher ==="
echo "Starting: $(date)"
echo ""

bash scripts/run_cpa_wave8_pushes.sh

echo ""
echo "=== Done ==="
echo "Finished: $(date)"
echo "Log: /tmp/wave8_push.log"
echo ""
echo "Press Enter to close this window..."
read -r
