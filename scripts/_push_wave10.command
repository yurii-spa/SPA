#!/usr/bin/env bash
# _push_wave10.command — macOS double-click launcher for Wave 10 pushes
# Double-click this file in Finder to run the full Wave 10 push sequence.

cd "$(dirname "$0")/.." || exit 1

echo "=== SPA Wave 10 Push (v11.43 → v11.54) ==="
echo "Started: $(date)"
echo ""

bash scripts/run_cpa_wave10_pushes.sh

echo ""
echo "Done: $(date)"
echo "Press Enter to close..."
read -r
