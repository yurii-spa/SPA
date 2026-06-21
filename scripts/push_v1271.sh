#!/usr/bin/env bash
# Sprint v12.71 — APY expectation recalibration (DeFiLlama 2026-06 research)
# CLAUDE.md adapter table + RULES.md benchmark + DECISIONS.md calibration note
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/CLAUDE.md" \
    "${REPO_ROOT}/RULES.md" \
    "${REPO_ROOT}/docs/DECISIONS.md" \
    "${REPO_ROOT}/scripts/push_v1271.sh" \
  --message "docs: recalibrate APY expectations to DeFiLlama 2026-06 (T1 blended 3.5-5%, not 5-6.5%)"
