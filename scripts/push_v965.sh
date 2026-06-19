#!/usr/bin/env bash
# Sprint v9.65 — MP-1349 CPA Wave 2 master push script (v9.41-v9.70)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/scripts/run_cpa_wave2_pushes.sh" \
    "${REPO_ROOT}/scripts/push_v965.sh" \
    "${REPO_ROOT}/KANBAN.json" \
  --message "Sprint v9.65 — MP-1349 CPA Wave 2 master push script (v9.41-v9.70)"
