#!/usr/bin/env bash
# Sprint v12.65 — DeFi yield research report (live DeFiLlama scan, 2026-06-21)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/research/yield_research_2026.md" \
    "${REPO_ROOT}/scripts/push_v1265.sh" \
  --message "research: DeFi stablecoin yield report (live DeFiLlama scan 2026-06-21)"
