#!/usr/bin/env bash
# _push_wave11.command
# MP-1552 (v11.68) — Wave 11 double-click push launcher
#
# Double-click this file in Finder to push all Wave 11 sprints (v11.55–v11.70)
# to GitHub. A Terminal window will open and show live progress.
# Log is also written to /tmp/wave11_push.log

cd "$HOME/Documents/SPA_Claude" || {
  echo "ERROR: Cannot cd to ~/Documents/SPA_Claude"
  exit 1
}

echo "=== SPA Wave 11 Push Launcher ==="
echo "Starting: $(date)"
echo ""

bash scripts/run_cpa_wave11_pushes.sh 2>&1 | tee /tmp/wave11_push.log

echo ""
echo "=== Done ==="
echo "Finished: $(date)"
echo "Log: /tmp/wave11_push.log"
echo ""
echo "Press Enter to close this window..."
read -r
