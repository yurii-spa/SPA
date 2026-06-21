#!/usr/bin/env bash
# scripts/push_v1272.sh
# ADR-049: Maple tier evaluation (stays T2) + Centrifuge T3 watchlist
# Usage: bash scripts/push_v1272.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/docs/adr/ADR-049-maple-tier-evaluation.md" \
    "$REPO_ROOT/scripts/push_v1272.sh" \
  --message "docs: ADR-049 Maple tier eval — stays T2 (exit latency 336h + 2022 bad debt fail T1 gates); Centrifuge T3 watchlist"
