#!/usr/bin/env bash
# scripts/push_v940.sh
# Sprint v9.40 — MP-1324 CPA wave consolidated push script
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave_pushes.sh" \
    "$REPO_ROOT/scripts/push_v939.sh" \
    "$REPO_ROOT/scripts/push_v940.sh" \
  --message "Sprint v9.40 — MP-1324 CPA wave consolidated push script"
