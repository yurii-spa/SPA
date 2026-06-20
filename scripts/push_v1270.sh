#!/usr/bin/env bash
# scripts/push_v1270.sh
# Week 2 paper-trading milestone analysis (Jun 18–21)
# Usage: bash scripts/push_v1270.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/data/milestones/week2_analysis.md" \
    "$REPO_ROOT/scripts/push_v1270.sh" \
  --message "docs: Week 2 paper-trading milestone analysis (Jun 10-20, 11/11 days, +0.12%, 4.11% APY)"
